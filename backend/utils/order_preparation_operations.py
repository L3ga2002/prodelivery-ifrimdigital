"""Durable preparation intents, independent of assignment and custody.

The legacy routes remain unchanged. Only this actor's original ledger entry can
confirm a request after a lost acknowledgement; observing a phase is not proof.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import re
import uuid

from bson.int64 import Int64
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference
from pymongo.write_concern import WriteConcern

from models.order_mutation import OperationCommand
from models.order_preparation_operations import (
    COMMAND_TYPES, RECEIPT_FIELDS, PreparationResult, digest, preparation_digest,
)
from utils.order_operation_runtime import OperationRuntime, SessionLifecycle
from utils.order_revision import MAX_ORDER_VERSION, revision_filter, revision_update


logger = logging.getLogger(__name__)
SETTINGS_ID = "order-preparation-v1"
MAX_ATTEMPTS = 3
MAX_COMMIT_ATTEMPTS = 3
DEADLINE_SECONDS = 10
CLEANUP_SECONDS = 0.25
RETRY_AFTER_SECONDS = 2
MIN_PREP_WHEN_NO_DRIVERS = 20
MAJORITY = WriteConcern("majority", wtimeout=3000)
_BACKGROUND_WORK = set()
_runtime = OperationRuntime(lambda: DEADLINE_SECONDS, lambda: CLEANUP_SECONDS,
                            _BACKGROUND_WORK, logger, "order_preparation")
BUSINESS_ERRORS = {
    "ORDER_NOT_FOUND": 404, "ORDER_TARGET_CHANGED": 409, "ORDER_DATA_INVALID": 409,
    "ORDER_VERSION_REQUIRED": 409, "ORDER_VERSION_INVALID": 409,
    "ORDER_VERSION_CONFLICT": 409, "ORDER_VERSION_EXHAUSTED": 409,
    "PREPARATION_TRANSITION_INVALID": 409, "PREPARATION_ALREADY_STARTED": 409,
    "PREPARATION_ALREADY_READY": 409, "PREPARATION_DRIVER_REQUIRED": 409,
}
PREPARATION_FIELDS = tuple(name for name in RECEIPT_FIELDS if name not in {"order_id", "order_version"})
LEGACY_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?$"
)


class PreparationError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


class _RetryPreparation(Exception):
    """Abort every effect after a lost snapshot CAS, then retry finitely."""


@dataclass(frozen=True)
class PreparationOutcome:
    result: PreparationResult
    status_code: int


def _error(status, code, message):
    return PreparationError(status, code, message)


def _identifier(value, status=422, code="INVALID_ORDER_ID"):
    if (not isinstance(value, str) or not 1 <= len(value) <= 120 or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise _error(status, code, "Identitatea este invalida.")
    return value


def _identity(actor):
    return _identifier(actor.get("user_id") or actor.get("id"), 401, "AUTH_REQUIRED")


def operation_key(actor_id, operation_type, client_operation_id):
    if operation_type not in COMMAND_TYPES:
        raise ValueError("Unknown preparation operation")
    return "preparation:" + digest([actor_id, "preparation", client_operation_id])


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _snapshot(document, fields):
    return {name: document[name] if name in document else {"$exists": False} for name in fields}


def _admission_digest(operation):
    return digest({name: operation[name] for name in (
        "_id", "actor_id", "actor_role", "actor_restaurant_id", "operation_type",
        "contract_version", "target_order_id", "restaurant_id", "client_operation_id",
        "payload_digest", "request_id", "created_at",
    )})


def _date(value):
    try:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, str) and LEGACY_TIMESTAMP.fullmatch(value):
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError("Invalid preparation date")
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise _error(409, "ORDER_DATA_INVALID", "Datele de pregatire necesita verificare.") from None


def _preparation(order):
    # The legacy public phase has precedence over additive dispatch metadata.
    status, phase = order.get("status"), order.get("preparation_status")
    if not isinstance(status, str) or status not in {
        "NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED",
    }:
        raise _error(409, "ORDER_DATA_INVALID", "Statusul comenzii necesita verificare.")
    if phase is not None and (not isinstance(phase, str) or phase not in {"NEW", "PREPARING", "READY"}):
        raise _error(409, "ORDER_DATA_INVALID", "Datele de pregatire necesita verificare.")
    if status in {"NEW", "PREPARING", "READY"}:
        return status
    if phase is not None:
        return phase
    for field in ("preparation_started_at", "preparation_ready_at"):
        if order.get(field) is not None:
            _date(order[field])
    if order.get("preparation_ready_at") is not None:
        return "READY"
    return "PREPARING" if order.get("preparation_started_at") is not None else "NEW"


def _integer(value, minimum, maximum):
    if type(value) not in (int, Int64) or not minimum <= value <= maximum:
        raise _error(409, "ORDER_DATA_INVALID", "Timpii de pregatire necesita verificare.")
    return int(value)


class OrderPreparationService:
    def __init__(self, database, operation_type="preparing"):
        if operation_type not in COMMAND_TYPES:
            raise ValueError("Unknown preparation operation")
        self.db, self.operation_type = database, operation_type
        self.command_type = COMMAND_TYPES[operation_type]
        self.operations = database.get_collection("order_operations", write_concern=MAJORITY,
            read_concern=ReadConcern("majority"), read_preference=ReadPreference.PRIMARY)

    async def _actor(self, actor, session=None):
        users = await self.db.users.find({"id": _identity(actor)},
            {"id": 1, "role": 1, "account_disabled": 1, "restaurant_id": 1}, session=session).limit(2).to_list(2)
        if not users:
            raise _error(401, "AUTH_REQUIRED", "Contul nu mai este disponibil.")
        if (len(users) != 1 or users[0].get("id") != _identity(actor)
            or "account_disabled" in users[0] and type(users[0]["account_disabled"]) is not bool):
            raise _error(403, "AUTH_CONTEXT_CHANGED", "Accesul necesita verificare.")
        user = users[0]
        if user.get("account_disabled"):
            raise _error(403, "ACCOUNT_DISABLED", "Contul este dezactivat.")
        if (not isinstance(user.get("role"), str) or user["role"] not in {"admin", "restaurant"}
            or user["role"] != actor.get("role")):
            raise _error(403, "NOT_AUTHORIZED", "Contul nu poate modifica pregatirea.")
        if user["role"] == "restaurant":
            _identifier(user.get("restaurant_id"), 403, "AUTH_CONTEXT_CHANGED")
            if user["restaurant_id"] != actor.get("restaurant_id"):
                raise _error(403, "AUTH_CONTEXT_CHANGED", "Legatura contului s-a schimbat.")
        return user

    @staticmethod
    def _authorized_order(order, actor):
        if actor.get("role") == "admin":
            return
        if (actor.get("role") == "restaurant" and order is not None
            and actor.get("restaurant_id") == order.get("restaurant_id")):
            return
        raise _error(403, "NOT_AUTHORIZED", "Nu poti modifica aceasta comanda.")

    async def _load_order(self, order_id, session=None):
        orders = await self.db.orders.find({"id": order_id}, session=session).limit(2).to_list(2)
        if len(orders) > 1:
            raise _error(409, "ORDER_DATA_INVALID", "Identitatea comenzii necesita verificare.")
        return orders[0] if orders else None

    def _validated_operation(self, operation, key, actor):
        try:
            required = {"_id", "actor_id", "actor_role", "actor_restaurant_id", "operation_type",
                "contract_version", "target_order_id", "restaurant_id", "client_operation_id",
                "payload_digest", "request_id", "created_at", "admission_digest", "command", "state"}
            allowed = required | {"resolved_at", "receipt", "receipt_digest", "error_code", "error_status"}
            if not required <= set(operation) <= allowed:
                raise ValueError("Invalid operation fields")
            command = self.command_type.model_validate(operation["command"])
            actor_id = _identity(actor)
            target = _identifier(operation["target_order_id"], 503, "OPERATION_INVALID")
            tenant = operation["restaurant_id"]
            if tenant is not None:
                _identifier(tenant, 503, "OPERATION_INVALID")
            created = datetime.fromisoformat(operation["created_at"])
            request_id = operation["request_id"]
            if (created.tzinfo is None or not isinstance(request_id, str)
                or str(uuid.UUID(request_id)) != request_id
                or operation["_id"] != key or operation["actor_id"] != actor_id
                or operation["actor_role"] not in {"admin", "restaurant"}
                or operation["actor_role"] != actor.get("role")
                or operation["actor_restaurant_id"] != (actor.get("restaurant_id") if actor.get("role") == "restaurant" else None)
                or operation["operation_type"] != self.operation_type
                or type(operation["contract_version"]) is not int or operation["contract_version"] != 1
                or operation["client_operation_id"] != command.client_operation_id
                or key != operation_key(actor_id, self.operation_type, command.client_operation_id)
                or operation["payload_digest"] != preparation_digest(self.operation_type, target, command)
                or operation["admission_digest"] != _admission_digest(operation)):
                raise ValueError("Invalid operation binding")
            self._outcome(operation)
            return command
        except (KeyError, TypeError, ValueError, PreparationError):
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Pastreaza aceeasi intentie.") from None

    async def _existing_authorized(self, key, order_id, actor, command=None):
        await self._actor(actor)
        existing = await self.operations.find_one({"_id": key})
        if existing is None:
            return None
        stored_type = existing.get("operation_type")
        if not isinstance(stored_type, str) or stored_type not in COMMAND_TYPES:
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Pastreaza aceeasi intentie.")
        stored_service = self if stored_type == self.operation_type else OrderPreparationService(self.db, stored_type)
        stored_service._validated_operation(existing, key, actor)
        if stored_type != self.operation_type:
            if command is None:
                raise _error(404, "OPERATION_NOT_FOUND", "Operatia nu a fost gasita; pastreaza identitatea.")
            raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alta actiune.")
        if existing["target_order_id"] != order_id:
            if command is None:
                raise _error(404, "OPERATION_NOT_FOUND", "Operatia nu a fost gasita; pastreaza identitatea.")
            raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alte date.")
        if command is not None and preparation_digest(self.operation_type, order_id, command) != existing["payload_digest"]:
            raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alte date.")
        if existing["state"] == "pending":
            self._authorized_order(await self._load_order(order_id), actor)
        return existing

    @staticmethod
    def _pending(client_operation_id):
        return PreparationOutcome(PreparationResult(client_operation_id=client_operation_id,
            state="pending", retry_after_seconds=RETRY_AFTER_SECONDS), 202)

    def _outcome(self, operation, replay=True):
        try:
            command = self.command_type.model_validate(operation["command"])
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
                receipt = operation["receipt"]
                if not isinstance(receipt, dict) or set(receipt) != set(RECEIPT_FIELDS):
                    raise ValueError("Invalid receipt fields")
                expected_version = command.expected_order_version
                version = receipt["order_version"]
                if (expected_version is None and version is not None or expected_version is not None and (
                    type(version) not in (int, Int64) or not 1 <= version <= MAX_ORDER_VERSION
                    or version != expected_version + 1
                )):
                    raise ValueError("Invalid original revision")
                if (receipt["order_id"] != operation["target_order_id"]
                    or receipt["preparation_status"] != self.operation_type.upper()
                    or self.operation_type == "preparing" and receipt["preparation_time"] != command.preparation_time
                    or receipt["preparation_started_at" if self.operation_type == "preparing" else "preparation_ready_at"] != operation["resolved_at"]
                    or operation["receipt_digest"] != digest(receipt)
                    or operation.get("error_code") is not None or operation.get("error_status") is not None):
                    raise ValueError("Invalid original receipt")
                return PreparationOutcome(PreparationResult(client_operation_id=command.client_operation_id,
                    state="replayed" if replay else "applied", **receipt), 200)
            if operation.get("receipt") is not None or operation.get("receipt_digest") is not None:
                raise ValueError("Uncommitted effect identity")
            if state == "rejected":
                code, status = operation["error_code"], operation["error_status"]
                if type(status) is not int or BUSINESS_ERRORS.get(code) != status:
                    raise ValueError("Invalid business rejection")
                return PreparationOutcome(PreparationResult(client_operation_id=command.client_operation_id,
                    state="rejected", error_code=code), status)
            if state != "pending" or operation.get("error_code") is not None or operation.get("error_status") is not None:
                raise ValueError("Invalid pending state")
            return self._pending(command.client_operation_id)
        except (KeyError, TypeError, ValueError):
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Pastreaza aceeasi intentie.") from None

    async def _ready(self, new_admission):
        if new_admission:
            setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
            if setting is None or setting.get("enabled") is False:
                raise _error(503, "PREPARATION_NOT_ENABLED", "Fluxul recuperabil nu este activat in acest mediu.")
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
                    return {"preparation_recovery_enabled": False}
                if type(setting.get("enabled")) is not bool:
                    raise _error(503, "CAPABILITIES_INVALID", "Configuratia necesita verificare.")
                if setting["enabled"]:
                    await self._ready(new_admission=False)
                return {"preparation_recovery_enabled": setting["enabled"]}
        except (TimeoutError, PyMongoError):
            logger.warning("order_preparation_capabilities_unavailable")
            raise _error(503, "CAPABILITIES_UNAVAILABLE", "Configuratia nu este disponibila.") from None

    async def lookup(self, order_id, client_operation_id, actor):
        OperationCommand(client_operation_id=client_operation_id)
        _identifier(order_id)
        try:
            async with _runtime.request_deadline():
                key = operation_key(_identity(actor), self.operation_type, client_operation_id)
                existing = await self._existing_authorized(key, order_id, actor)
                if existing is None:
                    raise _error(404, "OPERATION_NOT_FOUND", "Operatia nu a fost gasita; pastreaza aceeasi intentie.")
                return self._outcome(existing)
        except (TimeoutError, PyMongoError):
            logger.warning("order_preparation_lookup_unavailable")
            raise _error(503, "RECOVERY_UNAVAILABLE", "Verificarea nu este disponibila. Pastreaza aceeasi intentie.") from None

    async def resume(self, order_id, client_operation_id, actor):
        OperationCommand(client_operation_id=client_operation_id)
        _identifier(order_id)
        key = operation_key(_identity(actor), self.operation_type, client_operation_id)
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
            logger.warning("order_preparation_resume_unavailable operation_ref=%s executing=%s", key, executing)
            if executing:
                return self._pending(client_operation_id)
            raise _error(503, "RECOVERY_UNAVAILABLE", "Verificarea nu este disponibila. Pastreaza aceeasi intentie.") from None

    async def submit(self, order_id, command, actor):
        if type(command) is not self.command_type:
            raise ValueError("Command does not match preparation operation")
        command = self.command_type.model_validate(command.model_dump(mode="python", exclude_unset=True))
        order_id = _identifier(order_id)
        key = operation_key(_identity(actor), self.operation_type, command.client_operation_id)
        attempted = False
        try:
            async with _runtime.request_deadline():
                existing = await self._existing_authorized(key, order_id, actor, command)
                if existing is not None and existing["state"] != "pending":
                    return self._outcome(existing)
                await self._ready(new_admission=existing is None)
                if existing is None:
                    order = await self._load_order(order_id)
                    self._authorized_order(order, actor)
                    tenant = order.get("restaurant_id") if order else None
                    try:
                        if tenant is not None:
                            _identifier(tenant, 409, "ORDER_DATA_INVALID")
                    except PreparationError:
                        tenant = None
                    operation = {
                        "_id": key, "operation_type": self.operation_type, "contract_version": 1,
                        "actor_id": _identity(actor), "actor_role": actor["role"],
                        "actor_restaurant_id": actor.get("restaurant_id") if actor["role"] == "restaurant" else None,
                        "target_order_id": order_id, "restaurant_id": tenant,
                        "client_operation_id": command.client_operation_id,
                        "payload_digest": preparation_digest(self.operation_type, order_id, command),
                        "command": command.model_dump(mode="json"), "request_id": str(uuid.uuid4()),
                        "state": "pending", "created_at": _timestamp(),
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
            logger.warning("order_preparation_uncertain operation_ref=%s admitted=%s", key, attempted)
            if attempted:
                return self._pending(command.client_operation_id)
            raise _error(503, "PREPARATION_UNAVAILABLE", "Serverul nu raspunde. Pastreaza aceeasi intentie.") from None

    def _order_state(self, operation, command, order):
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
            if command.expected_order_version is not None:
                raise _error(409, "ORDER_VERSION_REQUIRED", "Comanda nu are versiunea asteptata.")
        else:
            version = order["order_version"]
            if type(version) not in (int, Int64) or not 0 <= version <= MAX_ORDER_VERSION:
                raise _error(409, "ORDER_VERSION_INVALID", "Versiunea comenzii este invalida.")
            if command.expected_order_version is None or version != command.expected_order_version:
                raise _error(409, "ORDER_VERSION_CONFLICT", "Comanda a fost modificata intre timp.")
            if version == MAX_ORDER_VERSION:
                raise _error(409, "ORDER_VERSION_EXHAUSTED", "Versiunea comenzii necesita verificare.")
        phase = _preparation(order)
        if order["status"] not in {"NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED"}:
            raise _error(409, "PREPARATION_TRANSITION_INVALID", "Pregatirea nu mai poate fi modificata.")
        if self.operation_type == "preparing" and phase == "PREPARING":
            raise _error(409, "PREPARATION_ALREADY_STARTED", "Pregatirea a fost deja pornita prin alta actiune.")
        if phase == "READY":
            raise _error(409, "PREPARATION_ALREADY_READY", "Comanda a fost deja marcata gata prin alta actiune.")
        if (self.operation_type == "preparing" and phase != "NEW"
            or self.operation_type == "ready" and phase != "PREPARING"):
            raise _error(409, "PREPARATION_TRANSITION_INVALID", "Actiunea nu mai este permisa in starea curenta.")
        if "audit_trail" in order and (not isinstance(order["audit_trail"], list)
                                      or any(not isinstance(entry, dict) for entry in order["audit_trail"])):
            raise _error(409, "ORDER_DATA_INVALID", "Istoricul comenzii necesita verificare.")
        return phase

    async def _eligible_driver(self, order, session):
        # Match the existing preparation policy, including the own assigned slot.
        available = {"is_active": True, "driver_status": "active", "account_disabled": {"$ne": True},
                     "$or": [{"current_order_id": None}, {"current_order_id": {"$exists": False}}]}
        driver = await self.db.drivers.find_one(available, session=session)
        if driver is None and order["status"] in {"ASSIGNED", "ACCEPTED"} and order.get("driver_id"):
            driver = await self.db.drivers.find_one({"id": order["driver_id"], "current_order_id": order["id"],
                "driver_status": "delivery", "is_active": True, "account_disabled": {"$ne": True}}, session=session)
        if driver is None:
            raise _error(409, "PREPARATION_DRIVER_REQUIRED", "Nu exista livratori disponibili. Seteaza minimum 20 minute.")
        return driver

    async def _plan(self, operation, command, session):
        order = await self._load_order(operation["target_order_id"], session)
        self._authorized_order(order, {"role": operation["actor_role"],
                                      "restaurant_id": operation["actor_restaurant_id"]})
        phase = self._order_state(operation, command, order)
        now = datetime.now(timezone.utc)
        driver = None
        if self.operation_type == "preparing":
            if command.preparation_time < MIN_PREP_WHEN_NO_DRIVERS:
                driver = await self._eligible_driver(order, session)
            changed = {"status": "PREPARING" if order["status"] == "NEW" else order["status"],
                "preparation_status": "PREPARING", "preparation_time": command.preparation_time,
                "preparation_estimated_seconds": command.preparation_time * 60,
                "preparation_started_at": now.isoformat(),
                "preparation_due_at": (now + timedelta(minutes=command.preparation_time)).isoformat()}
        else:
            estimate = order.get("preparation_estimated_seconds")
            if estimate is None:
                minutes = order.get("preparation_time")
                estimate = _integer(minutes, 1, 240) * 60 if minutes is not None else 0
            estimate = _integer(estimate, 0, 240 * 60)
            actual, delay = None, 0
            if order.get("preparation_started_at"):
                actual = max(int((now - _date(order["preparation_started_at"])).total_seconds()), 0)
                actual = _integer(actual, 0, MAX_ORDER_VERSION)
                delay = max(actual - estimate, 0)
            changed = {"status": "READY" if order["status"] == "PREPARING" else order["status"],
                "preparation_status": "READY", "preparation_ready_at": now.isoformat(),
                "preparation_actual_seconds": actual, "preparation_delay_seconds": delay}
        changed["updated_at"] = now.isoformat()
        projected = {**order, **changed}
        receipt = {"order_id": order["id"],
                   "order_version": int(order["order_version"]) + 1 if "order_version" in order else None}
        for field in PREPARATION_FIELDS:
            value = projected.get(field)
            if field.endswith("_at") and value is not None:
                value = _date(value).isoformat()
            elif value is not None and field != "preparation_status":
                maximum = 240 if field == "preparation_time" else 14400 if field == "preparation_estimated_seconds" else MAX_ORDER_VERSION
                value = _integer(value, 1 if field == "preparation_time" else 0, maximum)
            receipt[field] = value
        # Validate everything before the first business write, never after one.
        try:
            PreparationResult(client_operation_id=command.client_operation_id, state="applied", **receipt)
        except ValueError:
            raise _error(409, "ORDER_DATA_INVALID", "Datele de pregatire necesita verificare.") from None
        return order, phase, changed, receipt, driver

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
                    command = self._validated_operation(operation, key, actor)
                    user = await lifecycle.wait(self._actor(actor, session))
                    if operation["state"] != "pending":
                        return self._outcome(operation)
                    guard = await lifecycle.wait(self.db.users.update_one(
                        {"_id": user["_id"], "id": user["id"], "role": operation["actor_role"],
                         **_snapshot(user, ("account_disabled", "restaurant_id"))},
                        {"$inc": {"order_admission_revision": 1}}, session=session))
                    if guard.matched_count != 1:
                        raise _error(403, "AUTH_CONTEXT_CHANGED", "Accesul s-a schimbat.")
                    try:
                        plan = await lifecycle.wait(self._plan(operation, command, session))
                    except PreparationError as rejection:
                        if BUSINESS_ERRORS.get(rejection.code) != rejection.status_code:
                            raise
                        result = await lifecycle.wait(self.operations.update_one(
                            {"_id": key, "state": "pending", "admission_digest": operation["admission_digest"]},
                            {"$set": {"state": "rejected", "error_code": rejection.code,
                                      "error_status": rejection.status_code, "resolved_at": _timestamp()}}, session=session))
                        if result.matched_count != 1:
                            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
                        logger.info("order_preparation_rejection_prepared operation_ref=%s code=%s", key, rejection.code)
                    else:
                        await lifecycle.wait(self._apply(operation, user, plan, session))
                    if not await lifecycle.wait(_runtime.commit(session, MAX_COMMIT_ATTEMPTS)):
                        return self._pending(client_operation_id)
                    resolved = await self._existing_authorized(key, operation["target_order_id"], actor)
                    return self._outcome(resolved, replay=False) if resolved is not None else self._pending(client_operation_id)
                except _RetryPreparation:
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
        order, phase, changed, receipt, driver = plan
        if driver is not None:
            # Fence only the availability observation; no reservation/custody edit.
            result = await self.db.drivers.update_one({"_id": driver["_id"],
                **_snapshot(driver, ("id", "current_order_id", "driver_status", "is_active", "account_disabled"))},
                {"$inc": {"order_preparation_revision": 1}}, session=session)
            if result.matched_count != 1:
                raise _RetryPreparation()
        action = "order.preparing_started" if self.operation_type == "preparing" else "order.ready"
        audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":" + self.operation_type))
        changes = {"from_status": order["status"], "to_status": changed["status"],
                   "from_preparation_status": phase, "to_preparation_status": changed["preparation_status"]}
        fields = ("preparation_time", "preparation_due_at") if self.operation_type == "preparing" else (
            "preparation_actual_seconds", "preparation_delay_seconds")
        changes.update({name: receipt[name] for name in fields})
        audit = {"id": audit_id, "action": action, "changes": changes,
            "performed_by": user["id"], "performed_by_role": user["role"], "created_at": changed["updated_at"],
            "operation_ref": operation["_id"], "request_id": operation["request_id"],
            "source": order.get("source") if isinstance(order.get("source"), str) else None,
            "from_order_version": int(order["order_version"]) if "order_version" in order else None,
            "to_order_version": receipt["order_version"]}
        query = {"_id": order["_id"], "id": operation["target_order_id"],
                 "restaurant_id": operation["restaurant_id"], **revision_filter(order),
                 **_snapshot(order, ("status", "driver_id", "driver_name", "assigned_at", "accepted_at",
                    "picked_up_at", "cancelled_at", "delivered_at", "audit_trail", "source", *PREPARATION_FIELDS))}
        updated = await self.db.orders.find_one_and_update(query,
            revision_update(order, {"$set": changed, "$push": {"audit_trail": audit}}),
            session=session, return_document=ReturnDocument.AFTER)
        if updated is None:
            raise _RetryPreparation()
        await self.db.audit_logs.insert_one({"_id": audit_id, **audit, "entity_type": "order", "entity_id": order["id"]}, session=session)
        result = await self.operations.update_one(
            {"_id": operation["_id"], "state": "pending", "admission_digest": operation["admission_digest"]},
            {"$set": {"state": "applied", "receipt": receipt, "receipt_digest": digest(receipt),
                      "resolved_at": changed["updated_at"]}}, session=session)
        if result.matched_count != 1:
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
        logger.info("order_preparation_prepared operation_ref=%s request_id=%s", operation["_id"], operation["request_id"])
