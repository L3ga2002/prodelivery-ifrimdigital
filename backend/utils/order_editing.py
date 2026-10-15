"""Recoverable operational corrections; never promote legacy orders implicitly."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import math
import uuid

from bson.int64 import Int64
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference
from pymongo.write_concern import WriteConcern

from models.order_mutation import EditOrderCommand, MutationResult, OperationCommand, build_mutation_intent
from utils.order_operation_runtime import OperationRuntime, SessionLifecycle
from utils.order_finance import FinanceError, order_financial_snapshot
from utils.order_revision import MAX_ORDER_VERSION, revision_filter, revision_update


logger = logging.getLogger(__name__)
SETTINGS_ID = "order-edit-v1"
MAX_ATTEMPTS = 3
MAX_COMMIT_ATTEMPTS = 3
DEADLINE_SECONDS = 10
CLEANUP_SECONDS = 0.25
RETRY_AFTER_SECONDS = 2
MAJORITY = WriteConcern("majority", wtimeout=3000)
_BACKGROUND_WORK = set()
_runtime = OperationRuntime(lambda: DEADLINE_SECONDS, lambda: CLEANUP_SECONDS,
                            _BACKGROUND_WORK, logger, "order_edit")
BUSINESS_ERRORS = {
    "ORDER_NOT_FOUND": 404, "ORDER_TARGET_CHANGED": 409, "ORDER_DATA_INVALID": 409,
    "ORDER_VERSION_REQUIRED": 409, "ORDER_VERSION_INVALID": 409,
    "ORDER_VERSION_CONFLICT": 409, "ORDER_VERSION_EXHAUSTED": 409,
    "ORDER_NOT_EDITABLE": 409, "COORDINATES_REQUIRED": 409, "NO_CHANGES": 409,
    "FINANCIAL_ADDRESS_OPERATION_REQUIRED": 409, "FINANCIAL_SNAPSHOT_INVALID": 409,
    "FINANCIAL_AMOUNT_INVALID": 409,
}


class EditingError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


@dataclass(frozen=True)
class EditingOutcome:
    result: MutationResult
    status_code: int


def _error(status, code, message):
    return EditingError(status, code, message)


def _identifier(value, status, code):
    if not isinstance(value, str) or not 1 <= len(value) <= 120 or value != value.strip() or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        raise _error(status, code, "Identitatea este invalida.")
    return value


def _identity(actor):
    return _identifier(actor.get("user_id") or actor.get("id"), 401, "AUTH_REQUIRED")


def operation_key(actor_id, client_operation_id):
    encoded = json.dumps([actor_id, "edit", client_operation_id], separators=(",", ":"))
    return "edit:" + sha256(encoded.encode("utf-8")).hexdigest()


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _admission_digest(operation):
    snapshot = {name: operation[name] for name in (
        "_id", "actor_id", "actor_role", "operation_type", "contract_version",
        "target_order_id", "restaurant_id", "client_operation_id", "payload_digest",
        "request_id", "created_at",
    )}
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _validated_operation(operation, key, actor):
    try:
        command = EditOrderCommand.model_validate(operation["command"])
        actor_id = _identity(actor)
        target = _identifier(operation["target_order_id"], 503, "OPERATION_INVALID")
        intent = build_mutation_intent(actor_id, "edit", target, command)
        tenant = operation["restaurant_id"]
        if tenant is not None:
            _identifier(tenant, 503, "OPERATION_INVALID")
        created = datetime.fromisoformat(operation["created_at"])
        request_id = operation["request_id"]
        if (created.tzinfo is None or not isinstance(request_id, str)
            or str(uuid.UUID(request_id)) != request_id
            or operation["_id"] != key or operation["actor_id"] != actor_id
            or operation["actor_role"] != "admin" or operation["operation_type"] != "edit"
            or type(operation["contract_version"]) is not int or operation["contract_version"] != 1
            or operation["client_operation_id"] != command.client_operation_id
            or key != operation_key(actor_id, command.client_operation_id)
            or operation["payload_digest"] != intent.payload_digest
            or operation["admission_digest"] != _admission_digest(operation)):
            raise ValueError("Invalid stored binding")
        OrderEditingService._outcome(operation)
        return command
    except (KeyError, TypeError, ValueError, EditingError):
        raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Pastreaza aceeasi intentie.") from None


class OrderEditingService:
    def __init__(self, database):
        self.db = database
        self.operations = database.get_collection(
            "order_operations", write_concern=MAJORITY,
            read_concern=ReadConcern("majority"), read_preference=ReadPreference.PRIMARY,
        )

    async def _actor(self, actor, session=None):
        user = await self.db.users.find_one({"id": _identity(actor)},
            {"id": 1, "role": 1, "account_disabled": 1}, session=session)
        if not user:
            raise _error(401, "AUTH_REQUIRED", "Contul nu mai este disponibil.")
        if user.get("account_disabled"):
            raise _error(403, "ACCOUNT_DISABLED", "Contul este dezactivat.")
        if user.get("role") != "admin" or actor.get("role") != "admin":
            raise _error(403, "NOT_AUTHORIZED", "Numai administratorul poate corecta comenzi.")
        return user

    async def _load_order(self, order_id, session=None):
        orders = await self.db.orders.find({"id": order_id}, session=session).limit(2).to_list(2)
        if len(orders) > 1:
            raise _error(409, "ORDER_DATA_INVALID", "Identitatea comenzii necesita verificare.")
        return orders[0] if orders else None

    async def _existing_authorized(self, key, order_id, actor, command=None):
        await self._actor(actor)
        existing = await self.operations.find_one({"_id": key})
        if existing is None:
            return None
        _validated_operation(existing, key, actor)
        if existing["target_order_id"] != order_id:
            if command is None:
                raise _error(404, "OPERATION_NOT_FOUND", "Operatia nu a fost gasita; pastreaza identitatea.")
            raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alte date.")
        if command is not None and build_mutation_intent(_identity(actor), "edit", order_id, command).payload_digest != existing["payload_digest"]:
            raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alte date.")
        return existing

    @staticmethod
    def _pending(client_operation_id):
        return EditingOutcome(MutationResult(client_operation_id=client_operation_id,
            state="pending", retry_after_seconds=RETRY_AFTER_SECONDS), 202)

    @staticmethod
    def _outcome(operation, replay=True):
        try:
            command = EditOrderCommand.model_validate(operation["command"])
            state = operation["state"]
            if state != "pending":
                resolved = datetime.fromisoformat(operation["resolved_at"])
                if resolved.tzinfo is None:
                    raise ValueError("Invalid resolution time")
            elif operation.get("resolved_at") is not None:
                raise ValueError("Pending resolution time")
            if operation.get("retry_after_seconds") is not None:
                raise ValueError("Unexpected persisted retry")
            if state == "applied":
                version = operation["order_version"]
                if type(version) not in (int, Int64) or version != command.expected_order_version + 1 or not 1 <= version <= MAX_ORDER_VERSION:
                    raise ValueError("Invalid committed revision")
                if (operation["order_id"] != operation["target_order_id"]
                    or operation.get("error_code") is not None or operation.get("error_status") is not None):
                    raise ValueError("Invalid committed binding")
                return EditingOutcome(MutationResult(client_operation_id=command.client_operation_id,
                    state="replayed" if replay else "applied", order_id=operation["order_id"], order_version=int(version)), 200)
            if operation.get("order_id") is not None or operation.get("order_version") is not None:
                raise ValueError("Uncommitted effect identity")
            if state == "rejected":
                code, status = operation["error_code"], operation["error_status"]
                if type(status) is not int or BUSINESS_ERRORS.get(code) != status:
                    raise ValueError("Invalid business rejection")
                return EditingOutcome(MutationResult(client_operation_id=command.client_operation_id,
                    state="rejected", error_code=code), status)
            if state != "pending" or operation.get("error_code") is not None or operation.get("error_status") is not None:
                raise ValueError("Invalid pending state")
            return OrderEditingService._pending(command.client_operation_id)
        except (KeyError, TypeError, ValueError):
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Pastreaza aceeasi intentie.") from None

    async def _ready(self, new_admission):
        if new_admission:
            setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
            if setting is None or setting.get("enabled") is False:
                raise _error(503, "EDITING_NOT_ENABLED", "Corectarea recuperabila nu este activata in acest mediu.")
            if type(setting.get("enabled")) is not bool:
                raise _error(503, "CAPABILITIES_INVALID", "Configuratia necesita verificare.")
        hello = await self.db.command("hello", maxTimeMS=2000)
        if not hello.get("setName") and hello.get("msg") != "isdbgrid":
            raise _error(503, "TRANSACTIONS_REQUIRED", "Mediul nu suporta operatii recuperabile.")

    async def capabilities(self, actor):
        try:
            async with _runtime.request_deadline():
                await self._actor(actor)
                setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
                if setting is None:
                    return {"edit_recovery_enabled": False}
                if type(setting.get("enabled")) is not bool:
                    raise _error(503, "CAPABILITIES_INVALID", "Configuratia necesita verificare.")
                if setting["enabled"]:
                    await self._ready(new_admission=False)
                return {"edit_recovery_enabled": setting["enabled"]}
        except (TimeoutError, PyMongoError):
            logger.warning("order_edit_capabilities_unavailable")
            raise _error(503, "CAPABILITIES_UNAVAILABLE", "Configuratia nu este disponibila.") from None

    async def lookup(self, order_id, client_operation_id, actor):
        OperationCommand(client_operation_id=client_operation_id)
        _identifier(order_id, 422, "INVALID_ORDER_ID")
        try:
            async with _runtime.request_deadline():
                existing = await self._existing_authorized(operation_key(_identity(actor), client_operation_id), order_id, actor)
                if existing is None:
                    raise _error(404, "OPERATION_NOT_FOUND", "Operatia nu a fost gasita; pastreaza aceeasi intentie.")
                return self._outcome(existing)
        except (TimeoutError, PyMongoError):
            logger.warning("order_edit_lookup_unavailable")
            raise _error(503, "RECOVERY_UNAVAILABLE", "Verificarea nu este disponibila. Pastreaza aceeasi intentie.") from None

    async def resume(self, order_id, client_operation_id, actor):
        OperationCommand(client_operation_id=client_operation_id)
        _identifier(order_id, 422, "INVALID_ORDER_ID")
        key = operation_key(_identity(actor), client_operation_id)
        executing = False
        try:
            async with _runtime.request_deadline():
                existing = await self._existing_authorized(key, order_id, actor)
                if existing is None:
                    raise _error(404, "OPERATION_NOT_FOUND", "Operatia nu a fost gasita; pastreaza aceeasi intentie.")
                if existing["state"] != "pending":
                    return self._outcome(existing)
                await self._ready(new_admission=False)
                executing = True
                return await self._execute(key, actor, client_operation_id)
        except (TimeoutError, PyMongoError):
            logger.warning("order_edit_resume_unavailable operation_ref=%s executing=%s", key, executing)
            if executing:
                return self._pending(client_operation_id)
            raise _error(503, "RECOVERY_UNAVAILABLE", "Verificarea nu este disponibila. Pastreaza aceeasi intentie.") from None

    async def edit(self, order_id, command, actor):
        command = EditOrderCommand.model_validate(command.model_dump(mode="python", exclude_unset=True))
        order_id = _identifier(order_id, 422, "INVALID_ORDER_ID")
        key = operation_key(_identity(actor), command.client_operation_id)
        attempted = False
        try:
            async with _runtime.request_deadline():
                existing = await self._existing_authorized(key, order_id, actor, command)
                if existing is not None and existing["state"] != "pending":
                    return self._outcome(existing)
                await self._ready(new_admission=existing is None)
                if existing is None:
                    order = await self._load_order(order_id)
                    tenant = order.get("restaurant_id") if order else None
                    if tenant is not None:
                        _identifier(tenant, 409, "ORDER_DATA_INVALID")
                    intent = build_mutation_intent(_identity(actor), "edit", order_id, command)
                    operation = {
                        "_id": key, "operation_type": "edit", "contract_version": 1,
                        "actor_id": _identity(actor), "actor_role": "admin", "target_order_id": order_id,
                        "restaurant_id": tenant, "client_operation_id": command.client_operation_id,
                        "payload_digest": intent.payload_digest, "command": command.model_dump(mode="json"),
                        "request_id": str(uuid.uuid4()), "state": "pending", "created_at": _timestamp(),
                    }
                    operation["admission_digest"] = _admission_digest(operation)
                    attempted = True
                    try:
                        await self.operations.insert_one(operation)
                    except DuplicateKeyError:
                        existing = await self._existing_authorized(key, order_id, actor, command)
                        if existing is None:
                            return self._pending(command.client_operation_id)
                        if existing["state"] != "pending":
                            return self._outcome(existing)
                else:
                    attempted = True
                return await self._execute(key, actor, command.client_operation_id)
        except (TimeoutError, PyMongoError):
            logger.warning("order_edit_uncertain operation_ref=%s admitted=%s", key, attempted)
            if attempted:
                return self._pending(command.client_operation_id)
            raise _error(503, "EDITING_UNAVAILABLE", "Serverul nu raspunde. Pastreaza aceeasi intentie.") from None

    @staticmethod
    def _changes(operation, command, order):
        if order is None:
            raise _error(404, "ORDER_NOT_FOUND", "Comanda nu exista.")
        if "custody_activity" in order or "custody_contract_version" in order:
            raise _error(409, "ORDER_NOT_EDITABLE", "Custodia necesita protocolul dedicat.")
        if order.get("restaurant_id") != operation["restaurant_id"]:
            raise _error(409, "ORDER_TARGET_CHANGED", "Comanda necesita verificare.")
        if not isinstance(order.get("restaurant_id"), str) or not order["restaurant_id"].strip():
            raise _error(409, "ORDER_DATA_INVALID", "Datele comenzii necesita verificare.")
        try:
            financial = order_financial_snapshot(order)
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        if financial is not None and command.changes.model_fields_set & {
            "customer_address", "customer_latitude", "customer_longitude",
        }:
            raise _error(409, "FINANCIAL_ADDRESS_OPERATION_REQUIRED",
                         "Adresa comenzii financiare necesita protocolul dedicat de schimbare si tarifare.")
        if "order_version" not in order:
            raise _error(409, "ORDER_VERSION_REQUIRED", "Comanda necesita protocolul versionat.")
        version = order["order_version"]
        if type(version) not in (int, Int64) or not 0 <= version <= MAX_ORDER_VERSION:
            raise _error(409, "ORDER_VERSION_INVALID", "Versiunea comenzii este invalida.")
        if version != command.expected_order_version:
            raise _error(409, "ORDER_VERSION_CONFLICT", "Comanda a fost modificata intre timp. Pastreaza corectiile.")
        if version == MAX_ORDER_VERSION:
            raise _error(409, "ORDER_VERSION_EXHAUSTED", "Versiunea comenzii necesita verificare.")
        status = order.get("status")
        if not isinstance(status, str):
            raise _error(409, "ORDER_DATA_INVALID", "Statusul comenzii necesita verificare.")
        if (status not in {"NEW", "PREPARING", "READY"} or order.get("driver_id") is not None
            or any(order.get(name) is not None for name in (
                "assigned_at", "accepted_at", "picked_up_at", "delivered_at", "cancelled_at",
                "cancelled_by", "cancellation_reason",
            ))):
            raise _error(409, "ORDER_NOT_EDITABLE", "Comanda nu mai poate fi corectata prin acest formular.")
        if "preparation_status" in order and order["preparation_status"] != status:
            raise _error(409, "ORDER_DATA_INVALID", "Pregatirea comenzii necesita verificare.")
        lat, lng = order.get("customer_latitude"), order.get("customer_longitude")
        if (lat is None) != (lng is None) or any(value is not None and (
            type(value) not in (int, Int64, float) or not math.isfinite(value) or not -bound <= value <= bound
        ) for value, bound in ((lat, 90), (lng, 180))):
            raise _error(409, "ORDER_DATA_INVALID", "Coordonatele comenzii necesita verificare.")
        changes = command.changes.model_dump(mode="json", exclude_unset=True)
        if changes.get("customer_address", order.get("customer_address")) != order.get("customer_address") and lat is not None:
            if ("customer_latitude" not in changes
                or (changes["customer_latitude"], changes["customer_longitude"]) == (lat, lng)):
                raise _error(409, "COORDINATES_REQUIRED", "Adresa noua necesita coordonate noi sau stergerea perechii vechi.")
        changed = {name: value for name, value in changes.items() if order.get(name) != value}
        if not changed:
            raise _error(409, "NO_CHANGES", "Nu exista corectii de salvat.")
        return changed

    async def _execute(self, key, actor, client_operation_id):
        for attempt in range(MAX_ATTEMPTS):
            session = await _runtime.start_session(self.db.client)
            lifecycle = SessionLifecycle(_runtime, session)
            try:
                session.start_transaction(read_concern=ReadConcern("snapshot"), write_concern=MAJORITY,
                    read_preference=ReadPreference.PRIMARY, max_commit_time_ms=2000)
                try:
                    operation = await lifecycle.wait(self.operations.find_one({"_id": key}, session=session))
                    if operation is None:
                        raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
                    command = _validated_operation(operation, key, actor)
                    user = await lifecycle.wait(self._actor(actor, session))
                    if operation["state"] != "pending":
                        return self._outcome(operation)
                    guard = await lifecycle.wait(self.db.users.update_one(
                        {"_id": user["_id"], "role": "admin", "account_disabled": {"$ne": True}},
                        {"$inc": {"order_admission_revision": 1}}, session=session))
                    if guard.matched_count != 1:
                        raise _error(403, "AUTH_CONTEXT_CHANGED", "Accesul s-a schimbat.")
                    try:
                        order = await lifecycle.wait(self._load_order(operation["target_order_id"], session))
                        changed = self._changes(operation, command, order)
                        await lifecycle.wait(self._apply(operation, user, order, changed, session))
                    except EditingError as rejection:
                        if BUSINESS_ERRORS.get(rejection.code) != rejection.status_code:
                            raise
                        result = await lifecycle.wait(self.operations.update_one({"_id": key, "state": "pending"}, {"$set": {
                            "state": "rejected", "error_code": rejection.code, "error_status": rejection.status_code,
                            "resolved_at": _timestamp(),
                        }}, session=session))
                        if result.matched_count != 1:
                            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
                    if not await lifecycle.wait(_runtime.commit(session, MAX_COMMIT_ATTEMPTS)):
                        return self._pending(client_operation_id)
                    resolved = await self._existing_authorized(key, operation["target_order_id"], actor)
                    if resolved is None:
                        return self._pending(client_operation_id)
                    return self._outcome(resolved, replay=False)
                except PyMongoError as exc:
                    if exc.has_error_label("TransientTransactionError") and attempt + 1 < MAX_ATTEMPTS:
                        await asyncio.sleep(0.05 * (attempt + 1))
                        continue
                    raise
            finally:
                await lifecycle.cleanup()
        return self._pending(client_operation_id)

    async def _apply(self, operation, user, order, changed, session):
        now = _timestamp()
        audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":corrected"))
        audit = {
            "id": audit_id, "action": "order.corrected", "changes": {"fields": sorted(changed)},
            "performed_by": user["id"], "performed_by_role": "admin", "created_at": now,
            "operation_ref": operation["_id"], "request_id": operation["request_id"],
            "from_order_version": int(order["order_version"]), "to_order_version": int(order["order_version"]) + 1,
        }
        query = {"_id": order["_id"], "id": operation["target_order_id"],
                 "restaurant_id": operation["restaurant_id"], "status": order["status"], **revision_filter(order)}
        updated = await self.db.orders.find_one_and_update(query, revision_update(order, {
            "$set": {**changed, "updated_at": now}, "$push": {"audit_trail": audit},
        }), session=session, return_document=ReturnDocument.AFTER)
        if updated is None:
            raise _error(409, "ORDER_VERSION_CONFLICT", "Comanda a fost modificata intre timp. Pastreaza corectiile.")
        await self.db.audit_logs.insert_one({"_id": audit_id, **audit, "entity_type": "order", "entity_id": order["id"]}, session=session)
        result = await self.operations.update_one({"_id": operation["_id"], "state": "pending"}, {"$set": {
            "state": "applied", "order_id": order["id"], "order_version": int(order["order_version"]) + 1,
            "resolved_at": now,
        }}, session=session)
        if result.matched_count != 1:
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
        logger.info("order_edit_prepared operation_ref=%s request_id=%s", operation["_id"], operation["request_id"])
