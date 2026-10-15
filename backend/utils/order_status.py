"""Recoverable single-slot custody transitions, without legacy promotion."""

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

from models.order_mutation import StatusOrderCommand, MutationResult, OperationCommand, build_mutation_intent
from utils.order_operation_runtime import OperationRuntime, SessionLifecycle
from utils.order_finance import FinanceError, financial_earned_total, order_financial_snapshot, validate_snapshot
from models.financial_activity import FinancialActivity
from utils.financial_activity import inspect_activity, activity_after_pickup, validate_activity_ledger
from utils.custody_activity import inspect_custody, validate_custody_ledger, CustodyError
from utils.order_preparation import parse_operational_date, parse_preparation
from utils.order_revision import MAX_ORDER_VERSION, revision_filter, revision_update


logger = logging.getLogger(__name__)
SETTINGS_ID = "order-status-v1"
MAX_ATTEMPTS = 3
MAX_COMMIT_ATTEMPTS = 3
DEADLINE_SECONDS = 10
CLEANUP_SECONDS = 0.25
RETRY_AFTER_SECONDS = 2
MAJORITY = WriteConcern("majority", wtimeout=3000)
_BACKGROUND_WORK = set()
_runtime = OperationRuntime(lambda: DEADLINE_SECONDS, lambda: CLEANUP_SECONDS,
                            _BACKGROUND_WORK, logger, "order_status")
BUSINESS_ERRORS = {
    "ORDER_NOT_FOUND": 404, "ORDER_TARGET_CHANGED": 409, "ORDER_DATA_INVALID": 409,
    "ORDER_VERSION_REQUIRED": 409, "ORDER_VERSION_INVALID": 409,
    "ORDER_VERSION_CONFLICT": 409, "ORDER_VERSION_EXHAUSTED": 409,
    "STATUS_TRANSITION_INVALID": 409, "ORDER_NOT_READY": 409,
    "CUSTODY_RESOLUTION_REQUIRED": 409, "DRIVER_NOT_FOUND": 404, "DRIVER_DATA_INVALID": 409,
    "DRIVER_DISABLED": 409,
    "ASSIGNMENT_INCONSISTENT": 409, "ASSIGNMENT_REPRESENTATION_UNSUPPORTED": 409,
    "FINANCIAL_SNAPSHOT_INVALID": 409, "FINANCIAL_AMOUNT_INVALID": 409,
    "FINANCIAL_DRIVER_TOTAL_INVALID": 409,
    "FINANCIAL_ACTIVITY_INVALID": 409, "FINANCIAL_PICKUP_APPROVAL_REQUIRED": 409, "CUSTODY_INVALID": 409,
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


class StatusError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


class _RetryStatus(Exception):
    """An effect CAS lost; abort all effects before retrying the snapshot."""


@dataclass(frozen=True)
class StatusOutcome:
    result: MutationResult
    status_code: int


def _error(status, code, message):
    return StatusError(status, code, message)


def _identifier(value, status, code):
    if not isinstance(value, str) or not 1 <= len(value) <= 120 or value != value.strip() or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        raise _error(status, code, "Identitatea este invalida.")
    return value


def _identity(actor):
    return _identifier(actor.get("user_id") or actor.get("id"), 401, "AUTH_REQUIRED")


def operation_key(actor_id, client_operation_id):
    encoded = json.dumps([actor_id, "status", client_operation_id], separators=(",", ":"))
    return "status:" + sha256(encoded.encode("utf-8")).hexdigest()


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _admission_digest(operation):
    snapshot = {name: operation[name] for name in (
        "_id", "actor_id", "actor_role", "operation_type", "contract_version",
        "target_order_id", "restaurant_id", "client_operation_id", "payload_digest",
        "request_id", "created_at", "actor_driver_id", "actor_restaurant_id",
    )}
    if "financial_snapshot" in operation:
        snapshot["financial_snapshot"] = operation["financial_snapshot"]
    if "financial_activity_snapshot" in operation:
        snapshot["financial_activity_snapshot"] = operation["financial_activity_snapshot"]
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _validated_operation(operation, key, actor):
    try:
        command = StatusOrderCommand.model_validate(operation["command"])
        actor_id = _identity(actor)
        target = _identifier(operation["target_order_id"], 503, "OPERATION_INVALID")
        intent = build_mutation_intent(actor_id, "status", target, command)
        tenant = operation["restaurant_id"]
        if tenant is not None:
            _identifier(tenant, 503, "OPERATION_INVALID")
        created = datetime.fromisoformat(operation["created_at"])
        request_id = operation["request_id"]
        if (created.tzinfo is None or not isinstance(request_id, str)
            or str(uuid.UUID(request_id)) != request_id
            or operation["_id"] != key or operation["actor_id"] != actor_id
            or operation["actor_role"] not in {"admin", "restaurant", "driver"}
            or operation["actor_role"] != actor.get("role")
            or operation["actor_driver_id"] != (actor.get("driver_id") if actor.get("role") == "driver" else None)
            or operation["actor_restaurant_id"] != (actor.get("restaurant_id") if actor.get("role") == "restaurant" else None)
            or operation["operation_type"] != "status"
            or type(operation["contract_version"]) is not int or operation["contract_version"] != 1
            or operation["client_operation_id"] != command.client_operation_id
            or key != operation_key(actor_id, command.client_operation_id)
            or operation["payload_digest"] != intent.payload_digest
            or operation["admission_digest"] != _admission_digest(operation)):
            raise ValueError("Invalid stored binding")
        OrderStatusService._outcome(operation)
        if "financial_snapshot" in operation:
            validate_snapshot(operation["financial_snapshot"])
        if operation.get("financial_activity_snapshot") is not None:
            FinancialActivity.model_validate(operation["financial_activity_snapshot"])
        return command
    except (KeyError, TypeError, ValueError, StatusError):
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


class OrderStatusService:
    def __init__(self, database):
        self.db = database
        self.operations = database.get_collection(
            "order_operations", write_concern=MAJORITY,
            read_concern=ReadConcern("majority"), read_preference=ReadPreference.PRIMARY,
        )

    async def _actor(self, actor, session=None):
        users = await self.db.users.find({"id": _identity(actor)},
            {"id": 1, "role": 1, "account_disabled": 1, "driver_id": 1, "restaurant_id": 1}, session=session).limit(2).to_list(2)
        if not users:
            raise _error(401, "AUTH_REQUIRED", "Contul nu mai este disponibil.")
        if len(users) != 1 or ("account_disabled" in users[0] and type(users[0]["account_disabled"]) is not bool):
            raise _error(403, "AUTH_CONTEXT_CHANGED", "Accesul necesita verificare.")
        user = users[0]
        if not isinstance(user.get("id"), str) or user["id"] != _identity(actor):
            raise _error(403, "AUTH_CONTEXT_CHANGED", "Identitatea contului necesita verificare.")
        if user.get("account_disabled"):
            raise _error(403, "ACCOUNT_DISABLED", "Contul este dezactivat.")
        if (not isinstance(user.get("role"), str) or user["role"] not in {"admin", "restaurant", "driver"}
            or user["role"] != actor.get("role")):
            raise _error(403, "NOT_AUTHORIZED", "Contul nu poate modifica aceasta comanda.")
        if user["role"] == "driver":
            # Real authentication derives driver_id from drivers.user_id, not a mandatory user field.
            links = await self.db.drivers.find({"user_id": user["id"]}, {"id": 1}, session=session).limit(2).to_list(2)
            if len(links) != 1:
                raise _error(403, "AUTH_CONTEXT_CHANGED", "Legatura contului necesita verificare.")
            _identifier(links[0].get("id"), 403, "AUTH_CONTEXT_CHANGED")
            if (links[0]["id"] != actor.get("driver_id")
                or "driver_id" in user and user["driver_id"] != links[0]["id"]):
                raise _error(403, "AUTH_CONTEXT_CHANGED", "Legatura contului s-a schimbat.")
        if user["role"] == "restaurant":
            _identifier(user.get("restaurant_id"), 403, "AUTH_CONTEXT_CHANGED")
            if user["restaurant_id"] != actor.get("restaurant_id"):
                raise _error(403, "AUTH_CONTEXT_CHANGED", "Legatura contului s-a schimbat.")
        return user

    @staticmethod
    def _authorized_order(order, actor, command):
        role = actor.get("role")
        if role == "admin":
            return
        if (role == "driver" and command.status != "CANCELLED" and order is not None
            and actor.get("driver_id") == order.get("driver_id")):
            return
        if (role == "restaurant" and command.status == "CANCELLED" and order is not None
            and actor.get("restaurant_id") == order.get("restaurant_id")):
            return
        raise _error(403, "NOT_AUTHORIZED", "Nu poti modifica aceasta comanda.")

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
        admitted_command = _validated_operation(existing, key, actor)
        if existing["target_order_id"] != order_id:
            if command is None:
                raise _error(404, "OPERATION_NOT_FOUND", "Operatia nu a fost gasita; pastreaza identitatea.")
            raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alte date.")
        if command is not None and build_mutation_intent(_identity(actor), "status", order_id, command).payload_digest != existing["payload_digest"]:
            raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alte date.")
        if existing["state"] == "pending":
            self._authorized_order(await self._load_order(order_id), actor, admitted_command)
        # A terminal receipt proves only this actor's original operation, not current custody.
        return existing

    @staticmethod
    def _pending(client_operation_id):
        return StatusOutcome(MutationResult(client_operation_id=client_operation_id,
            state="pending", retry_after_seconds=RETRY_AFTER_SECONDS), 202)

    @staticmethod
    def _outcome(operation, replay=True):
        try:
            command = StatusOrderCommand.model_validate(operation["command"])
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
                return StatusOutcome(MutationResult(client_operation_id=command.client_operation_id,
                    state="replayed" if replay else "applied", order_id=operation["order_id"], order_version=int(version)), 200)
            if operation.get("order_id") is not None or operation.get("order_version") is not None:
                raise ValueError("Uncommitted effect identity")
            if state == "rejected":
                code, status = operation["error_code"], operation["error_status"]
                if type(status) is not int or BUSINESS_ERRORS.get(code) != status:
                    raise ValueError("Invalid business rejection")
                return StatusOutcome(MutationResult(client_operation_id=command.client_operation_id,
                    state="rejected", error_code=code), status)
            if state != "pending" or operation.get("error_code") is not None or operation.get("error_status") is not None:
                raise ValueError("Invalid pending state")
            return OrderStatusService._pending(command.client_operation_id)
        except (KeyError, TypeError, ValueError):
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Pastreaza aceeasi intentie.") from None

    async def _ready(self, new_admission):
        if new_admission:
            setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
            if setting is None or setting.get("enabled") is False:
                raise _error(503, "STATUS_NOT_ENABLED", "Fluxul recuperabil nu este activat in acest mediu.")
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
                    return {"status_recovery_enabled": False}
                if type(setting.get("enabled")) is not bool:
                    raise _error(503, "CAPABILITIES_INVALID", "Configuratia necesita verificare.")
                if setting["enabled"]:
                    await self._ready(new_admission=False)
                return {"status_recovery_enabled": setting["enabled"]}
        except (TimeoutError, PyMongoError):
            logger.warning("order_status_capabilities_unavailable")
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
            logger.warning("order_status_lookup_unavailable")
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
            logger.warning("order_status_resume_unavailable operation_ref=%s executing=%s", key, executing)
            if executing:
                return self._pending(client_operation_id)
            raise _error(503, "RECOVERY_UNAVAILABLE", "Verificarea nu este disponibila. Pastreaza aceeasi intentie.") from None

    async def status(self, order_id, command, actor):
        command = StatusOrderCommand.model_validate(command.model_dump(mode="python", exclude_unset=True))
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
                    target = await self._load_order(order_id)
                    self._authorized_order(target, actor, command)
                    try:
                        financial = order_financial_snapshot(target) if target is not None else None
                    except FinanceError as exc:
                        raise _error(exc.status_code, exc.code, exc.message) from None
                    # Invalid/duplicate business targets are rejected durably in the transaction.
                    orders = await self.db.orders.find({"id": order_id}, {"restaurant_id": 1}).limit(2).to_list(2)
                    tenant = orders[0].get("restaurant_id") if len(orders) == 1 else None
                    try:
                        if tenant is not None:
                            _identifier(tenant, 409, "ORDER_DATA_INVALID")
                    except StatusError:
                        tenant = None
                    intent = build_mutation_intent(_identity(actor), "status", order_id, command)
                    operation = {
                        "_id": key, "operation_type": "status", "contract_version": 1,
                        "actor_id": _identity(actor), "actor_role": actor["role"], "target_order_id": order_id,
                        "actor_driver_id": actor.get("driver_id") if actor["role"] == "driver" else None,
                        "actor_restaurant_id": actor.get("restaurant_id") if actor["role"] == "restaurant" else None,
                        "restaurant_id": tenant, "client_operation_id": command.client_operation_id,
                        "payload_digest": intent.payload_digest, "command": command.model_dump(mode="json"),
                        "request_id": str(uuid.uuid4()), "state": "pending", "created_at": _timestamp(),
                    }
                    if financial is not None:
                        operation["financial_snapshot"] = financial.model_dump(mode="json")
                    if command.status == "PICKED_UP":
                        # Pins absence too; a declaration admitted concurrently cannot be bypassed.
                        try:
                            activity = inspect_activity(target)
                        except FinanceError as exc:
                            raise _error(exc.status_code, exc.code, exc.message) from None
                        operation["financial_activity_snapshot"] = activity.model_dump(mode="json") if activity else None
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
            logger.warning("order_status_uncertain operation_ref=%s admitted=%s", key, attempted)
            if attempted:
                return self._pending(command.client_operation_id)
            raise _error(503, "STATUS_UNAVAILABLE", "Serverul nu raspunde. Pastreaza aceeasi intentie.") from None

    @staticmethod
    def _order_state(operation, command, order):
        if order is None:
            raise _error(404, "ORDER_NOT_FOUND", "Comanda nu exista.")
        if not isinstance(order.get("id"), str) or order["id"] != operation["target_order_id"]:
            raise _error(409, "ORDER_DATA_INVALID", "Identitatea comenzii necesita verificare.")
        _identifier(order.get("restaurant_id"), 409, "ORDER_DATA_INVALID")
        if order["restaurant_id"] != operation["restaurant_id"]:
            raise _error(409, "ORDER_TARGET_CHANGED", "Comanda necesita verificare.")
        try:
            financial = order_financial_snapshot(order)
            if ((financial is None) != ("financial_snapshot" not in operation)
                    or financial is not None and financial.model_dump(mode="json") != operation["financial_snapshot"]):
                raise FinanceError("FINANCIAL_SNAPSHOT_INVALID")
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        try:
            activity = inspect_activity(order)
            if "financial_activity_snapshot" in operation and (activity.model_dump(mode="json") if activity else None) != operation["financial_activity_snapshot"]:
                raise FinanceError("FINANCIAL_ACTIVITY_INVALID")
            if command.status == "PICKED_UP" and activity is not None and activity.status != "approved":
                raise FinanceError("FINANCIAL_PICKUP_APPROVAL_REQUIRED",
                    "Restaurantul trebuie sa aprobe ridicarea fara plata inainte de preluarea produselor.")
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        try:
            custody = inspect_custody(order)
            if custody is not None and custody.status not in {"waiting", "reviewed"}:
                raise _error(409, "CUSTODY_RESOLUTION_REQUIRED", "Restaurantul a decis rezolutia produselor.")
        except CustodyError:
            raise _error(409, "CUSTODY_INVALID", "Custodia necesita verificare.") from None
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
        if command.status == "CANCELLED" and status in {"PICKED_UP", "DELIVERED"}:
            raise _error(409, "CUSTODY_RESOLUTION_REQUIRED", "Comanda are custodie. Este necesar un incident, nu o anulare simpla.")
        transitions = {
            "NEW": {"CANCELLED"}, "PREPARING": {"CANCELLED"}, "READY": {"CANCELLED"},
            "ASSIGNED": {"ACCEPTED", "CANCELLED"}, "ACCEPTED": {"PICKED_UP", "CANCELLED"},
            "PICKED_UP": {"DELIVERED"}, "DELIVERED": set(), "CANCELLED": set(),
        }
        if command.status not in transitions[status]:
            raise _error(409, "STATUS_TRANSITION_INVALID", "Actiunea nu mai este permisa in starea curenta.")
        # Custody evidence must agree with the current lifecycle; do not infer a lost pickup.
        required = {"ASSIGNED": ("assigned_at",), "ACCEPTED": ("assigned_at", "accepted_at"),
                    "PICKED_UP": ("assigned_at", "accepted_at", "picked_up_at")}.get(status, ())
        times = []
        for field in required:
            value = _date(order.get(field), "ORDER_DATA_INVALID")
            if value.tzinfo is None:
                raise _error(409, "ORDER_DATA_INVALID", "Ora custodiei necesita fus orar.")
            times.append(value)
        if times != sorted(times) or any(time > datetime.now(timezone.utc) for time in times):
            raise _error(409, "ORDER_DATA_INVALID", "Ordinea custodiei necesita verificare.")
        allowed = set(required)
        if any(order.get(field) is not None for field in (
            "accepted_at", "picked_up_at", "delivered_at", "cancelled_at", "cancelled_by", "cancellation_reason",
        ) if field not in allowed):
            raise _error(409, "ORDER_DATA_INVALID", "Custodia comenzii necesita verificare.")
        if "audit_trail" in order and (not isinstance(order["audit_trail"], list)
                                      or any(not isinstance(entry, dict) for entry in order["audit_trail"])):
            raise _error(409, "ORDER_DATA_INVALID", "Istoricul comenzii necesita verificare.")
        old_id = order.get("driver_id")
        if status in {"ASSIGNED", "ACCEPTED", "PICKED_UP"}:
            _identifier(old_id, 409, "ASSIGNMENT_INCONSISTENT")
            if order.get("driver_name") is not None and (
                not isinstance(order["driver_name"], str) or not order["driver_name"].strip()
            ):
                raise _error(409, "ASSIGNMENT_INCONSISTENT", "Datele asignarii necesita verificare.")
        elif old_id is not None or order.get("driver_name") is not None or order.get("assigned_at") is not None:
            raise _error(409, "ASSIGNMENT_INCONSISTENT", "Asignarea comenzii necesita verificare.")
        prep = _preparation(order)
        if (command.status == "PICKED_UP" or status == "PICKED_UP") and prep != "READY":
            raise _error(409, "ORDER_NOT_READY", "Restaurantul trebuie sa marcheze comanda gata inainte de ridicare.")
        return prep, old_id

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
            {"id": 1, "role": 1, "account_disabled": 1, "driver_id": 1}, session=session).limit(2).to_list(2)
        if (len(users) != 1 or not isinstance(users[0].get("id"), str)
            or users[0]["id"] != driver["user_id"] or not isinstance(users[0].get("role"), str) or (
            "account_disabled" in users[0] and type(users[0]["account_disabled"]) is not bool
        )):
            raise _error(409, "DRIVER_DATA_INVALID", "Contul livratorului necesita verificare.")
        links = await self.db.drivers.find({"user_id": driver["user_id"]}, {"id": 1}, session=session).limit(2).to_list(2)
        if len(links) != 1 or links[0]["_id"] != driver["_id"]:
            raise _error(409, "DRIVER_DATA_INVALID", "Legatura contului necesita verificare.")
        if "driver_id" in users[0] and users[0]["driver_id"] != driver["id"]:
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
        self._authorized_order(order, {"role": operation["actor_role"],
            "driver_id": operation["actor_driver_id"], "restaurant_id": operation["actor_restaurant_id"]}, command)
        prep, old_id = self._order_state(operation, command, order)
        try:
            await validate_activity_ledger(self.db, order, inspect_activity(order), session)
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        try:
            await validate_custody_ledger(self.db, order, inspect_custody(order), session)
        except CustodyError:
            raise _error(409, "CUSTODY_INVALID", "Custodia necesita verificare.") from None
        claims = await self.db.drivers.find({"current_order_id": order["id"]},
            {"id": 1, "current_order_id": 1}, session=session).limit(2).to_list(2)
        old_driver = old_user = None
        if old_id is not None:
            try:
                old_driver = await self._driver(old_id, session)
            except StatusError as exc:
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
        if old_driver is not None and command.status != "CANCELLED":
            if old_driver.get("account_disabled") or old_user.get("account_disabled"):
                raise _error(409, "DRIVER_DISABLED", "Livratorul este dezactivat; este necesara interventia administratorului.")
            if old_user["role"] != "driver":
                raise _error(409, "DRIVER_DATA_INVALID", "Contul nu mai are rolul de livrator.")
        if command.status == "DELIVERED":
            self._delivery_totals(order, old_driver)
        return order, prep, old_driver, old_user, command

    @staticmethod
    def _delivery_totals(order, driver):
        amount = order.get("total_amount")
        try:
            financial = order_financial_snapshot(order)
            if financial is not None:
                financial_earned_total(driver, financial.courier_remuneration_bani)
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        earned = financial.courier_remuneration_bani / 100 if financial is not None else amount * 0.1 if type(amount) in (int, Int64, float) else None
        for field in ("total_amount", "subtotal_amount", "delivery_fee"):
            if field != "total_amount" and field not in order:
                continue
            value = order.get(field)
            if (type(value) not in (int, Int64, float) or not math.isfinite(value)
                or not 0 <= value <= 1000000):
                raise _error(409, "ORDER_DATA_INVALID", "Valorile comenzii necesita verificare; livrarea nu a fost aplicata.")
        deliveries = driver.get("total_deliveries", 0)
        earnings = driver.get("total_earnings", 0)
        if (type(deliveries) not in (int, Int64) or not 0 <= deliveries < MAX_ORDER_VERSION
            or type(earnings) not in (int, Int64, float) or not math.isfinite(earnings)
            or not 0 <= earnings <= 1e15 or earnings + earned > 1e15):
            raise _error(409, "DRIVER_DATA_INVALID", "Contorii financiari necesita verificare; livrarea nu a fost aplicata.")
        return earned

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
                        {"_id": user["_id"], "id": user["id"], "role": operation["actor_role"],
                         **_snapshot(user, ("account_disabled", "driver_id", "restaurant_id"))},
                        {"$inc": {"order_admission_revision": 1}}, session=session))
                    if guard.matched_count != 1:
                        raise _error(403, "AUTH_CONTEXT_CHANGED", "Accesul s-a schimbat.")
                    try:
                        plan = await lifecycle.wait(self._plan(operation, command, session))
                    except StatusError as rejection:
                        if BUSINESS_ERRORS.get(rejection.code) != rejection.status_code:
                            raise
                        result = await lifecycle.wait(self.operations.update_one(
                            {"_id": key, "state": "pending", "admission_digest": operation["admission_digest"]},
                            {"$set": {"state": "rejected", "error_code": rejection.code,
                                      "error_status": rejection.status_code, "resolved_at": _timestamp()}}, session=session))
                        if result.matched_count != 1:
                            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
                        logger.info("order_status_rejection_prepared operation_ref=%s request_id=%s code=%s",
                                    key, operation["request_id"], rejection.code)
                    else:
                        # A business rejection cannot follow a partially applied custody effect.
                        await lifecycle.wait(self._apply(operation, user, plan, session))
                    if not await lifecycle.wait(_runtime.commit(session, MAX_COMMIT_ATTEMPTS)):
                        return self._pending(client_operation_id)
                    resolved = await self._existing_authorized(key, operation["target_order_id"], actor)
                    if resolved is None:
                        return self._pending(client_operation_id)
                    return self._outcome(resolved, replay=False)
                except _RetryStatus:
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
        order, prep, driver, driver_user, command = plan
        now = _timestamp()
        driver_fields = ("id", "user_id", "name", "current_order_id", "driver_status", "is_active",
                         "account_disabled", "break_started_at", "break_until", "total_deliveries",
                          "total_earnings", "financial_earned_bani", *MULTI_FIELDS)
        if driver is not None:
            guard = await self.db.users.update_one(
                {"_id": driver_user["_id"], **_snapshot(driver_user, ("id", "role", "account_disabled", "driver_id"))},
                {"$inc": {"order_custody_revision": 1}}, session=session)
            if guard.matched_count != 1:
                raise _RetryStatus()
            changed = {}
            if command.status in {"DELIVERED", "CANCELLED"}:
                changed = {"current_order_id": None}
                if (driver["driver_status"] == "delivery" and driver["is_active"] is True
                    and not driver.get("account_disabled") and not driver_user.get("account_disabled")
                    and driver_user["role"] == "driver"):
                    changed["driver_status"] = "active"
            update = {"$set": changed} if changed else {"$inc": {"order_custody_revision": 1}}
            if command.status == "DELIVERED":
                update["$inc"] = {"total_deliveries": 1, "total_earnings": self._delivery_totals(order, driver)}
                financial = order_financial_snapshot(order)
                if financial is not None:
                    update["$inc"]["financial_earned_bani"] = financial.courier_remuneration_bani
            result = await self.db.drivers.update_one(
                {"_id": driver["_id"], **_snapshot(driver, driver_fields)}, update, session=session)
            if result.matched_count != 1:
                raise _RetryStatus()
        audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":status"))
        audit = {
            "id": audit_id, "action": "order.status_changed", "changes": {
                "from_status": order["status"], "to_status": command.status,
            },
            "performed_by": user["id"], "performed_by_role": user["role"], "created_at": now,
            "operation_ref": operation["_id"], "request_id": operation["request_id"],
            "from_order_version": int(order["order_version"]), "to_order_version": int(order["order_version"]) + 1,
        }
        if "financial_snapshot" in operation:
            audit["changes"]["financial_snapshot_digest"] = operation["financial_snapshot"]["snapshot_digest"]
            if command.status == "DELIVERED":
                audit["changes"]["courier_remuneration_bani"] = operation["financial_snapshot"]["courier_remuneration_bani"]
        query = {"_id": order["_id"], "id": operation["target_order_id"],
                 "restaurant_id": operation["restaurant_id"], **revision_filter(order),
                 **_snapshot(order, ("status", "driver_id", "driver_name", "assigned_at", "accepted_at",
                    "picked_up_at", "delivered_at", "cancelled_at", "cancelled_by", "cancellation_reason",
                    "total_amount", "subtotal_amount", "delivery_fee", "financial", "financial_contract_version",
                    "creation_operation_ref", *PREPARATION_FIELDS, *MULTI_FIELDS))}
        query.update(_snapshot(order, ("financial_activity", "financial_activity_contract_version", "custody_activity", "custody_contract_version")))
        changed = {"status": command.status, "preparation_status": prep, "updated_at": now}
        field = {"ACCEPTED": "accepted_at", "PICKED_UP": "picked_up_at", "DELIVERED": "delivered_at",
                 "CANCELLED": "cancelled_at"}[command.status]
        changed[field] = now
        if command.status == "PICKED_UP":
            activity = inspect_activity(order)
            if activity is not None:
                event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":financial-pickup"))
                changed["financial_activity"] = activity_after_pickup(activity, now, event_id, user["id"])
                changed["financial_activity_contract_version"] = 1
                audit["changes"].update(financial_activity_status="outstanding",
                    declared_unpaid_bani=activity.declared_unpaid_bani, declaration_id=activity.declaration_id,
                    approval_id=activity.approval_id, repayment_due_policy="next_pickup_else_shift_end")
        if command.status == "CANCELLED":
            changed.update(cancellation_reason=command.cancellation_reason, cancelled_by=user["role"])
            audit["changes"]["cancellation_reason"] = command.cancellation_reason
        updated = await self.db.orders.find_one_and_update(query, revision_update(order, {
            "$set": changed,
            "$push": {"audit_trail": audit},
        }), session=session, return_document=ReturnDocument.AFTER)
        if updated is None:
            raise _RetryStatus()
        if command.status == "PICKED_UP" and "financial_activity" in changed:
            event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":financial-pickup"))
            activity = changed["financial_activity"]
            event = {"_id": event_id, "id": event_id, "contract_version": 1, "event_type": "unpaid_pickup_recorded",
                "order_id": order["id"], "restaurant_id": order["restaurant_id"], "driver_id": driver["id"],
                "amount_bani": activity["outstanding_bani"], "declaration_id": activity["declaration_id"],
                "approval_id": activity["approval_id"], "repayment_due_policy": activity["repayment_due_policy"],
                "financial_snapshot_digest": activity["financial_snapshot_digest"], "activity_digest": activity["activity_digest"],
                "assigned_at": activity["assigned_at"], "accepted_at": activity["accepted_at"],
                "actor_id": user["id"], "actor_role": user["role"], "operation_ref": operation["_id"],
                "request_id": operation["request_id"], "created_at": now,
                "from_order_version": int(order["order_version"]), "to_order_version": int(order["order_version"]) + 1}
            event["event_digest"] = sha256(json.dumps({k: v for k, v in event.items() if k != "_id"},
                sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            await self.db.get_collection("order_financial_events").insert_one(event, session=session)
        await self.db.audit_logs.insert_one({"_id": audit_id, **audit, "entity_type": "order", "entity_id": order["id"]}, session=session)
        result = await self.operations.update_one(
            {"_id": operation["_id"], "state": "pending", "admission_digest": operation["admission_digest"]},
            {"$set": {"state": "applied", "order_id": order["id"],
                      "order_version": int(order["order_version"]) + 1, "resolved_at": now}}, session=session)
        if result.matched_count != 1:
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
        logger.info("order_status_prepared operation_ref=%s request_id=%s", operation["_id"], operation["request_id"])
