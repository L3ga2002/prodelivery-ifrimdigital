"""Recoverable manual single-slot assignment, without legacy promotion."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import uuid

from bson.int64 import Int64
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference
from pymongo.write_concern import WriteConcern

from models.order_mutation import AssignOrderCommand, MutationResult, OperationCommand, build_mutation_intent
from utils.order_operation_runtime import OperationRuntime, SessionLifecycle
from utils.order_preparation import parse_operational_date, parse_preparation
from utils.order_revision import MAX_ORDER_VERSION, revision_filter, revision_update


logger = logging.getLogger(__name__)
SETTINGS_ID = "order-assign-v1"
MAX_ATTEMPTS = 3
MAX_COMMIT_ATTEMPTS = 3
DEADLINE_SECONDS = 10
CLEANUP_SECONDS = 0.25
RETRY_AFTER_SECONDS = 2
MAJORITY = WriteConcern("majority", wtimeout=3000)
_BACKGROUND_WORK = set()
_runtime = OperationRuntime(lambda: DEADLINE_SECONDS, lambda: CLEANUP_SECONDS,
                            _BACKGROUND_WORK, logger, "order_assign")
BUSINESS_ERRORS = {
    "ORDER_NOT_FOUND": 404, "ORDER_TARGET_CHANGED": 409, "ORDER_DATA_INVALID": 409,
    "ORDER_VERSION_REQUIRED": 409, "ORDER_VERSION_INVALID": 409,
    "ORDER_VERSION_CONFLICT": 409, "ORDER_VERSION_EXHAUSTED": 409,
    "ORDER_NOT_ASSIGNABLE": 409, "DRIVER_NOT_FOUND": 404, "DRIVER_DATA_INVALID": 409,
    "DRIVER_DISABLED": 409, "DRIVER_NOT_AVAILABLE": 409, "DRIVER_BUSY": 409,
    "ASSIGNMENT_INCONSISTENT": 409, "ASSIGNMENT_REPRESENTATION_UNSUPPORTED": 409,
    "NO_CHANGES": 409,
}
MULTI_FIELDS = (
    "current_order_ids", "active_order_ids", "assigned_order_ids", "reserved_order_ids",
    "current_orders", "active_orders", "assigned_orders", "reserved_orders", "pending_order_ids",
    "order_ids", "driver_ids", "assignments", "assignment_ids", "active_assignment_ids",
    "reserved_assignment_ids", "active_assignments", "reserved_assignments", "pending_assignments",
    "current_assignment_id", "assignment_id", "assignment_version", "dispatch_version", "route_version",
    "active_count", "reserved_count",
)
PREPARATION_FIELDS = (
    "preparation_status", "preparation_time", "preparation_started_at", "preparation_due_at",
    "preparation_ready_at", "preparation_estimated_seconds", "preparation_actual_seconds",
    "preparation_delay_seconds",
)


class AssignmentError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


class _RetryAssignment(Exception):
    """An effect CAS lost; abort all effects before retrying the snapshot."""


@dataclass(frozen=True)
class AssignmentOutcome:
    result: MutationResult
    status_code: int


def _error(status, code, message):
    return AssignmentError(status, code, message)


def _identifier(value, status, code):
    if not isinstance(value, str) or not 1 <= len(value) <= 120 or value != value.strip() or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        raise _error(status, code, "Identitatea este invalida.")
    return value


def _identity(actor):
    return _identifier(actor.get("user_id") or actor.get("id"), 401, "AUTH_REQUIRED")


def operation_key(actor_id, client_operation_id):
    encoded = json.dumps([actor_id, "assign", client_operation_id], separators=(",", ":"))
    return "assign:" + sha256(encoded.encode("utf-8")).hexdigest()


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
        command = AssignOrderCommand.model_validate(operation["command"])
        _identifier(command.driver_id, 503, "OPERATION_INVALID")
        actor_id = _identity(actor)
        target = _identifier(operation["target_order_id"], 503, "OPERATION_INVALID")
        intent = build_mutation_intent(actor_id, "assign", target, command)
        tenant = operation["restaurant_id"]
        if tenant is not None:
            _identifier(tenant, 503, "OPERATION_INVALID")
        created = datetime.fromisoformat(operation["created_at"])
        request_id = operation["request_id"]
        if (created.tzinfo is None or not isinstance(request_id, str)
            or str(uuid.UUID(request_id)) != request_id
            or operation["_id"] != key or operation["actor_id"] != actor_id
            or operation["actor_role"] != "admin" or operation["operation_type"] != "assign"
            or type(operation["contract_version"]) is not int or operation["contract_version"] != 1
            or operation["client_operation_id"] != command.client_operation_id
            or key != operation_key(actor_id, command.client_operation_id)
            or operation["payload_digest"] != intent.payload_digest
            or operation["admission_digest"] != _admission_digest(operation)):
            raise ValueError("Invalid stored binding")
        OrderAssignmentService._outcome(operation)
        return command
    except (KeyError, TypeError, ValueError, AssignmentError):
        raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Pastreaza aceeasi intentie.") from None


def _snapshot(document, fields):
    # Distinguish absent fields from null and pin every release/claim input.
    return {name: document[name] if name in document else {"$exists": False} for name in fields}


def _single_representation(document):
    if any(name in document for name in MULTI_FIELDS):
        raise _error(409, "ASSIGNMENT_REPRESENTATION_UNSUPPORTED", "Asignarea necesita un protocol compatibil.")


def _date(value, code):
    return parse_operational_date(value, code, _error, datetime_type=datetime)


def _preparation(order):
    return parse_preparation(order, _error, _date, MAX_ORDER_VERSION)


class OrderAssignmentService:
    def __init__(self, database):
        self.db = database
        self.operations = database.get_collection(
            "order_operations", write_concern=MAJORITY,
            read_concern=ReadConcern("majority"), read_preference=ReadPreference.PRIMARY,
        )

    async def _actor(self, actor, session=None):
        users = await self.db.users.find({"id": _identity(actor)},
            {"id": 1, "role": 1, "account_disabled": 1}, session=session).limit(2).to_list(2)
        if not users:
            raise _error(401, "AUTH_REQUIRED", "Contul nu mai este disponibil.")
        if len(users) != 1 or ("account_disabled" in users[0] and type(users[0]["account_disabled"]) is not bool):
            raise _error(403, "AUTH_CONTEXT_CHANGED", "Accesul necesita verificare.")
        user = users[0]
        if not isinstance(user.get("id"), str) or user["id"] != _identity(actor):
            raise _error(403, "AUTH_CONTEXT_CHANGED", "Identitatea contului necesita verificare.")
        if user.get("account_disabled"):
            raise _error(403, "ACCOUNT_DISABLED", "Contul este dezactivat.")
        if user.get("role") != "admin" or actor.get("role") != "admin":
            raise _error(403, "NOT_AUTHORIZED", "Numai administratorul poate asigna comenzi.")
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
        if command is not None and build_mutation_intent(_identity(actor), "assign", order_id, command).payload_digest != existing["payload_digest"]:
            raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alte date.")
        return existing

    @staticmethod
    def _pending(client_operation_id):
        return AssignmentOutcome(MutationResult(client_operation_id=client_operation_id,
            state="pending", retry_after_seconds=RETRY_AFTER_SECONDS), 202)

    @staticmethod
    def _outcome(operation, replay=True):
        try:
            command = AssignOrderCommand.model_validate(operation["command"])
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
                return AssignmentOutcome(MutationResult(client_operation_id=command.client_operation_id,
                    state="replayed" if replay else "applied", order_id=operation["order_id"], order_version=int(version)), 200)
            if operation.get("order_id") is not None or operation.get("order_version") is not None:
                raise ValueError("Uncommitted effect identity")
            if state == "rejected":
                code, status = operation["error_code"], operation["error_status"]
                if type(status) is not int or BUSINESS_ERRORS.get(code) != status:
                    raise ValueError("Invalid business rejection")
                return AssignmentOutcome(MutationResult(client_operation_id=command.client_operation_id,
                    state="rejected", error_code=code), status)
            if state != "pending" or operation.get("error_code") is not None or operation.get("error_status") is not None:
                raise ValueError("Invalid pending state")
            return OrderAssignmentService._pending(command.client_operation_id)
        except (KeyError, TypeError, ValueError):
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Pastreaza aceeasi intentie.") from None

    async def _ready(self, new_admission):
        if new_admission:
            setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
            if setting is None or setting.get("enabled") is False:
                raise _error(503, "ASSIGNMENT_NOT_ENABLED", "Asignarea recuperabila nu este activata in acest mediu.")
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
                    return {"assign_recovery_enabled": False}
                if type(setting.get("enabled")) is not bool:
                    raise _error(503, "CAPABILITIES_INVALID", "Configuratia necesita verificare.")
                if setting["enabled"]:
                    await self._ready(new_admission=False)
                return {"assign_recovery_enabled": setting["enabled"]}
        except (TimeoutError, PyMongoError):
            logger.warning("order_assign_capabilities_unavailable")
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
            logger.warning("order_assign_lookup_unavailable")
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
            logger.warning("order_assign_resume_unavailable operation_ref=%s executing=%s", key, executing)
            if executing:
                return self._pending(client_operation_id)
            raise _error(503, "RECOVERY_UNAVAILABLE", "Verificarea nu este disponibila. Pastreaza aceeasi intentie.") from None

    async def assign(self, order_id, command, actor):
        command = AssignOrderCommand.model_validate(command.model_dump(mode="python", exclude_unset=True))
        _identifier(command.driver_id, 422, "INVALID_DRIVER_ID")
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
                    # Invalid/duplicate business targets are rejected durably in the transaction.
                    orders = await self.db.orders.find({"id": order_id}, {"restaurant_id": 1}).limit(2).to_list(2)
                    tenant = orders[0].get("restaurant_id") if len(orders) == 1 else None
                    try:
                        if tenant is not None:
                            _identifier(tenant, 409, "ORDER_DATA_INVALID")
                    except AssignmentError:
                        tenant = None
                    intent = build_mutation_intent(_identity(actor), "assign", order_id, command)
                    operation = {
                        "_id": key, "operation_type": "assign", "contract_version": 1,
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
            logger.warning("order_assign_uncertain operation_ref=%s admitted=%s", key, attempted)
            if attempted:
                return self._pending(command.client_operation_id)
            raise _error(503, "ASSIGNMENT_UNAVAILABLE", "Serverul nu raspunde. Pastreaza aceeasi intentie.") from None

    @staticmethod
    def _order_state(operation, command, order):
        if order is None:
            raise _error(404, "ORDER_NOT_FOUND", "Comanda nu exista.")
        if "custody_activity" in order or "custody_contract_version" in order:
            raise _error(409, "ORDER_DATA_INVALID", "Custodia necesita protocolul dedicat.")
        if not isinstance(order.get("id"), str) or order["id"] != operation["target_order_id"]:
            raise _error(409, "ORDER_DATA_INVALID", "Identitatea comenzii necesita verificare.")
        _identifier(order.get("restaurant_id"), 409, "ORDER_DATA_INVALID")
        if order["restaurant_id"] != operation["restaurant_id"]:
            raise _error(409, "ORDER_TARGET_CHANGED", "Comanda necesita verificare.")
        if "order_version" not in order:
            raise _error(409, "ORDER_VERSION_REQUIRED", "Comanda necesita protocolul versionat.")
        version = order["order_version"]
        if type(version) not in (int, Int64) or not 0 <= version <= MAX_ORDER_VERSION:
            raise _error(409, "ORDER_VERSION_INVALID", "Versiunea comenzii este invalida.")
        if version != command.expected_order_version:
            raise _error(409, "ORDER_VERSION_CONFLICT", "Comanda a fost modificata intre timp.")
        if version == MAX_ORDER_VERSION:
            raise _error(409, "ORDER_VERSION_EXHAUSTED", "Versiunea comenzii necesita verificare.")
        _single_representation(order)
        status = order.get("status")
        if not isinstance(status, str) or status not in {
            "NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED",
        }:
            raise _error(409, "ORDER_DATA_INVALID", "Statusul comenzii necesita verificare.")
        if status not in {"NEW", "PREPARING", "READY", "ASSIGNED"} or any(
            order.get(name) is not None for name in (
                "accepted_at", "picked_up_at", "delivered_at", "cancelled_at", "cancelled_by", "cancellation_reason",
            )
        ):
            raise _error(409, "ORDER_NOT_ASSIGNABLE", "Comanda nu mai poate fi asignata prin acest protocol.")
        if "audit_trail" in order and (not isinstance(order["audit_trail"], list)
                                      or any(not isinstance(entry, dict) for entry in order["audit_trail"])):
            raise _error(409, "ORDER_DATA_INVALID", "Istoricul comenzii necesita verificare.")
        old_id = order.get("driver_id")
        if status == "ASSIGNED":
            _identifier(old_id, 409, "ASSIGNMENT_INCONSISTENT")
            _date(order.get("assigned_at"), "ASSIGNMENT_INCONSISTENT")
            if order.get("driver_name") is not None and (
                not isinstance(order["driver_name"], str) or not order["driver_name"].strip()
            ):
                raise _error(409, "ASSIGNMENT_INCONSISTENT", "Datele asignarii necesita verificare.")
        elif old_id is not None or order.get("driver_name") is not None or order.get("assigned_at") is not None:
            raise _error(409, "ASSIGNMENT_INCONSISTENT", "Asignarea comenzii necesita verificare.")
        return _preparation(order), old_id

    async def _driver(self, driver_id, session):
        drivers = await self.db.drivers.find({"id": driver_id}, session=session).limit(2).to_list(2)
        if not drivers:
            raise _error(404, "DRIVER_NOT_FOUND", "Livratorul nu exista.")
        if len(drivers) != 1:
            raise _error(409, "DRIVER_DATA_INVALID", "Identitatea livratorului necesita verificare.")
        driver = drivers[0]
        if not isinstance(driver.get("id"), str) or driver["id"] != driver_id:
            raise _error(409, "DRIVER_DATA_INVALID", "Identitatea livratorului necesita verificare.")
        _single_representation(driver)
        _identifier(driver.get("user_id"), 409, "DRIVER_DATA_INVALID")
        if (not isinstance(driver.get("name"), str) or not driver["name"].strip()
            or type(driver.get("is_active")) is not bool
            or not isinstance(driver.get("driver_status"), str)
            or driver["driver_status"] not in {"active", "delivery", "break", "offline"}
            or "account_disabled" in driver and type(driver["account_disabled"]) is not bool):
            raise _error(409, "DRIVER_DATA_INVALID", "Datele livratorului necesita verificare.")
        if driver.get("current_order_id") is not None:
            _identifier(driver["current_order_id"], 409, "DRIVER_DATA_INVALID")
        for field in ("break_started_at", "break_until"):
            if driver.get(field) is not None:
                _date(driver[field], "DRIVER_DATA_INVALID")
        return driver

    async def _driver_user(self, driver, session):
        users = await self.db.users.find({"id": driver["user_id"]},
            {"id": 1, "role": 1, "account_disabled": 1}, session=session).limit(2).to_list(2)
        if (len(users) != 1 or not isinstance(users[0].get("id"), str)
            or users[0]["id"] != driver["user_id"] or not isinstance(users[0].get("role"), str) or (
            "account_disabled" in users[0] and type(users[0]["account_disabled"]) is not bool
        )):
            raise _error(409, "DRIVER_DATA_INVALID", "Contul livratorului necesita verificare.")
        links = await self.db.drivers.find({"user_id": driver["user_id"]}, {"id": 1}, session=session).limit(2).to_list(2)
        if len(links) != 1 or links[0]["_id"] != driver["_id"]:
            raise _error(409, "DRIVER_DATA_INVALID", "Legatura contului necesita verificare.")
        return users[0]

    async def _current_orders(self, driver_id, session):
        # Unknown/malformed statuses are not terminal and cannot free a slot.
        return await self.db.orders.find({"driver_id": driver_id, "$or": [
            {"status": {"$nin": ["DELIVERED", "CANCELLED"]}},
            {"status": {"$type": "array"}}, {"status": {"$not": {"$type": "string"}}},
        ]}, {"id": 1, "driver_id": 1, "status": 1}, session=session).limit(2).to_list(2)

    async def _plan(self, operation, command, session):
        order = await self._load_order(operation["target_order_id"], session)
        prep, old_id = self._order_state(operation, command, order)
        claims = await self.db.drivers.find({"current_order_id": order["id"]},
            {"id": 1, "current_order_id": 1}, session=session).limit(2).to_list(2)
        old_driver = old_user = None
        if old_id is not None:
            try:
                old_driver = await self._driver(old_id, session)
            except AssignmentError as exc:
                if exc.code != "DRIVER_NOT_FOUND":
                    raise
                raise _error(409, "ASSIGNMENT_INCONSISTENT", "Livratorul vechi nu mai exista.") from None
            old_user = await self._driver_user(old_driver, session)
            orders = await self._current_orders(old_id, session)
            if (old_driver.get("current_order_id") != order["id"] or len(claims) != 1
                or claims[0]["_id"] != old_driver["_id"] or len(orders) != 1
                or orders[0]["_id"] != order["_id"]):
                raise _error(409, "ASSIGNMENT_INCONSISTENT", "Asignarea veche necesita verificare.")
        elif claims:
            raise _error(409, "ASSIGNMENT_INCONSISTENT", "Comanda are un claim necorelat.")
        if old_id == command.driver_id:
            raise _error(409, "NO_CHANGES", "Comanda este deja asignata acestui livrator.")
        driver = await self._driver(command.driver_id, session)
        driver_user = await self._driver_user(driver, session)
        if driver.get("account_disabled") or driver_user.get("account_disabled"):
            raise _error(409, "DRIVER_DISABLED", "Livratorul este dezactivat.")
        if driver_user["role"] != "driver":
            raise _error(409, "DRIVER_NOT_AVAILABLE", "Contul nu mai are rolul de livrator.")
        if driver.get("current_order_id") is not None or await self._current_orders(driver["id"], session):
            raise _error(409, "DRIVER_BUSY", "Livratorul are un claim sau o comanda neinchisa.")
        if driver["is_active"] is not True or driver["driver_status"] != "active":
            raise _error(409, "DRIVER_NOT_AVAILABLE", "Livratorul nu este activ si disponibil.")
        # Explicit active ends a break in the current writer, which retains its timers.
        return order, prep, driver, driver_user, old_driver, old_user

    async def _execute(self, key, actor, client_operation_id):
        for attempt in range(MAX_ATTEMPTS):
            session = await _runtime.start_session(self.db.client)
            lifecycle = SessionLifecycle(_runtime, session)
            retry = False
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
                        {"_id": user["_id"], "id": user["id"], "role": "admin",
                         **_snapshot(user, ("account_disabled",))},
                        {"$inc": {"order_admission_revision": 1}}, session=session))
                    if guard.matched_count != 1:
                        raise _error(403, "AUTH_CONTEXT_CHANGED", "Accesul s-a schimbat.")
                    try:
                        plan = await lifecycle.wait(self._plan(operation, command, session))
                    except AssignmentError as rejection:
                        if BUSINESS_ERRORS.get(rejection.code) != rejection.status_code:
                            raise
                        result = await lifecycle.wait(self.operations.update_one(
                            {"_id": key, "state": "pending", "admission_digest": operation["admission_digest"]},
                            {"$set": {"state": "rejected", "error_code": rejection.code,
                                      "error_status": rejection.status_code, "resolved_at": _timestamp()}}, session=session))
                        if result.matched_count != 1:
                            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
                        logger.info("order_assign_rejection_prepared operation_ref=%s request_id=%s code=%s",
                                    key, operation["request_id"], rejection.code)
                    else:
                        # No business rejection is committed after any assignment effect.
                        await lifecycle.wait(self._apply(operation, user, plan, session))
                    if not await lifecycle.wait(_runtime.commit(session, MAX_COMMIT_ATTEMPTS)):
                        return self._pending(client_operation_id)
                    resolved = await self._existing_authorized(key, operation["target_order_id"], actor)
                    if resolved is None:
                        return self._pending(client_operation_id)
                    return self._outcome(resolved, replay=False)
                except _RetryAssignment:
                    retry = True
                except PyMongoError as exc:
                    if not exc.has_error_label("TransientTransactionError"):
                        raise
                    retry = True
            finally:
                await lifecycle.cleanup()
            if retry and attempt + 1 < MAX_ATTEMPTS:
                await asyncio.sleep(0.05 * (attempt + 1))
        return self._pending(client_operation_id)

    async def _apply(self, operation, user, plan, session):
        order, prep, driver, driver_user, old_driver, old_user = plan
        now = _timestamp()
        driver_fields = ("id", "user_id", "name", "current_order_id", "driver_status", "is_active",
                         "account_disabled", "break_started_at", "break_until", *MULTI_FIELDS)
        # Write fences include old role/account too: release must not reactivate a changed account.
        for account in sorted([driver_user] + ([old_user] if old_user else []), key=lambda item: item["id"]):
            guard = await self.db.users.update_one(
                {"_id": account["_id"], **_snapshot(account, ("id", "role", "account_disabled"))},
                {"$inc": {"order_assignment_revision": 1}}, session=session)
            if guard.matched_count != 1:
                raise _RetryAssignment()
        for item in sorted([driver] + ([old_driver] if old_driver else []), key=lambda item: item["id"]):
            if item["_id"] == driver["_id"]:
                changed = {"current_order_id": order["id"], "driver_status": "delivery", "is_active": True}
            else:
                changed = {"current_order_id": None}
                # Retained break timers are metadata, not a pause; never gate release on them.
                if (item["driver_status"] == "delivery" and item["is_active"] is True
                    and not item.get("account_disabled") and not old_user.get("account_disabled")
                    and old_user["role"] == "driver"):
                    changed["driver_status"] = "active"
            result = await self.db.drivers.update_one(
                {"_id": item["_id"], **_snapshot(item, driver_fields)}, {"$set": changed}, session=session)
            if result.matched_count != 1:
                raise _RetryAssignment()
        audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":assigned"))
        audit = {
            "id": audit_id, "action": "order.assigned", "changes": {
                "from_status": order["status"], "to_status": "ASSIGNED",
                "old_driver_id": old_driver["id"] if old_driver else None, "new_driver_id": driver["id"],
            },
            "performed_by": user["id"], "performed_by_role": "admin", "created_at": now,
            "operation_ref": operation["_id"], "request_id": operation["request_id"],
            "from_order_version": int(order["order_version"]), "to_order_version": int(order["order_version"]) + 1,
        }
        query = {"_id": order["_id"], "id": operation["target_order_id"],
                 "restaurant_id": operation["restaurant_id"], **revision_filter(order),
                 **_snapshot(order, ("status", "driver_id", "driver_name", "assigned_at", "accepted_at",
                    "picked_up_at", "delivered_at", "cancelled_at", "cancelled_by", "cancellation_reason",
                    *PREPARATION_FIELDS, *MULTI_FIELDS))}
        updated = await self.db.orders.find_one_and_update(query, revision_update(order, {
            "$set": {"driver_id": driver["id"], "driver_name": driver["name"], "status": "ASSIGNED",
                     "preparation_status": prep, "assigned_at": now, "updated_at": now},
            "$push": {"audit_trail": audit},
        }), session=session, return_document=ReturnDocument.AFTER)
        if updated is None:
            raise _RetryAssignment()
        await self.db.audit_logs.insert_one({"_id": audit_id, **audit, "entity_type": "order", "entity_id": order["id"]}, session=session)
        result = await self.operations.update_one(
            {"_id": operation["_id"], "state": "pending", "admission_digest": operation["admission_digest"]},
            {"$set": {"state": "applied", "order_id": order["id"],
                      "order_version": int(order["order_version"]) + 1, "resolved_at": now}}, session=session)
        if result.matched_count != 1:
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
        logger.info("order_assign_prepared operation_ref=%s request_id=%s", operation["_id"], operation["request_id"])
