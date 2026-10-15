"""Atomic linked deliveries with immutable quotes; no legacy promotion/activation."""

import asyncio
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import uuid

from bson import BSON
from bson.int64 import Int64
from pydantic import ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference

from models.order import Order
from models.order_mutation import CreateOrderCommand, OperationCommand, MAX_ORDER_VERSION
from models.order_remakes import (CloseFinancialRemake, FinancialRemakeTerminal, RemakeCommand, RemakeResult,
    RemakeParent, RemakeParentContext, RemakeReadback, RemakePublicFinancial)
from utils.order_creation import OrderCreationService, CreationError, MAJORITY, COUNTER_ID, VerifiedFinancialContext, _identity
from utils.order_finance import FinanceError, admission_snapshot, order_financial_snapshot, quote_at_admission
from utils.order_operation_runtime import OperationRuntime, SessionLifecycle
from utils.order_revision import revision_filter, revision_update
from utils.custody_activity import inspect_custody, validate_custody_ledger, CustodyError


logger = logging.getLogger(__name__)
SETTINGS_ID = "order-remake-v1"
DEADLINE_SECONDS = 10
MAX_ATTEMPTS = 3
_BACKGROUND_WORK = set()
_runtime = OperationRuntime(lambda: DEADLINE_SECONDS, lambda: 0.25, _BACKGROUND_WORK, logger, "order_remake")
PARENT_FIELDS = ("id", "restaurant_id", "order_version", "status", "source", "customer_name", "customer_phone",
                 "customer_address", "customer_latitude", "customer_longitude", "has_problem_followup",
                 "problem_followup_order_id", "problem_followup_operation_ref", "financial_contract_version",
                 "financial", "creation_operation_ref", "subtotal_amount", "delivery_fee", "total_amount",
                 "payment_type", "delivery_zone_id", "delivery_zone_name", "delivery_sector", "delivery_zone_level", "zone")
CUSTODY_PARENT_FIELDS = ("custody_activity", "custody_contract_version", "driver_id", "assigned_at", "accepted_at",
    "picked_up_at", "delivered_at", "cancelled_at", "cancelled_by", "cancellation_reason", "items",
    "financial_activity", "financial_activity_contract_version")
BUSINESS_ERRORS = {
    "ORDER_NOT_FOUND": 404, "ORDER_VERSION_CONFLICT": 409, "ORDER_VERSION_REQUIRED": 409,
    "ORDER_DATA_INVALID": 409, "ORDER_VERSION_EXHAUSTED": 409, "REMAKE_REQUIRES_DELIVERED": 409,
    "REMAKE_ALREADY_EXISTS": 409, "REMAKE_PARENT_CHANGED": 409, "CUSTODY_RESOLUTION_REQUIRED": 409,
    "RESTAURANT_NOT_FOUND": 404, "RESTAURANT_UNAVAILABLE": 409, "RESTAURANT_PAUSED": 409,
    "RESTAURANT_INVALID": 409, "FINANCIAL_SNAPSHOT_INVALID": 409, "FINANCIAL_AMOUNT_INVALID": 409,
}


class RemakeError(CreationError):
    pass


@dataclass(frozen=True)
class RemakeOutcome:
    result: RemakeResult
    status_code: int


def _error(status, code, message="Refacerea necesita verificare. Pastreaza aceeasi intentie."):
    return RemakeError(status, code, message)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def operation_key(actor_id, client_operation_id):
    return "remake:" + _digest([actor_id, "remake", client_operation_id])


def _identifier(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 120 or value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise _error(422, "INVALID_ORDER_ID")
    return value


def _intent(order_id, command):
    return _digest({"contract_version": 1, "type": "remake", "parent": order_id,
                    "command": command.model_dump(mode="json", exclude={"client_operation_id"})})


def _bound_digest(operation):
    return _digest({key: operation[key] for key in (
        "_id", "operation_type", "contract_version", "actor_id", "actor_role", "restaurant_id",
        "target_order_id", "client_operation_id", "payload_digest", "command", "parent_snapshot",
        "child_command", "child_order_id", "financial_snapshot", "created_at", "request_id")})


def _parent_snapshot(order):
    # Older admitted remakes keep their exact snapshot shape after upgrade.
    fields = PARENT_FIELDS
    if "custody_activity" in order or "custody_contract_version" in order:
        fields += CUSTODY_PARENT_FIELDS
    return {name: order[name] for name in fields if name in order}


def _policy(command):
    expected = command.financial.products_bani if command.payment_type == "CASH" else 0
    basis = "new_receipt" if command.payment_type == "CASH" else "prepaid_new_order"
    if (sum(item.quantity * item.unit_price_bani for item in command.items) != command.financial.products_bani
            or command.collection_basis != basis or command.client_collection_bani != expected
            or command.advance_required_bani != expected):
        raise _error(409, "FINANCIAL_REMAKE_POLICY_REQUIRED",
                     "Sumele necesita un protocol financiar distinct. Nu se presupune gratuitate sau plata.")


def _build_child_command(parent, command):
    # Relationship fields are supplied only by the atomic protocol, after quote validation.
    return CreateOrderCommand(client_operation_id=command.client_operation_id, financial=command.financial,
        order={"restaurant_id": parent["restaurant_id"], "customer_name": parent["customer_name"],
            "customer_phone": parent["customer_phone"], "customer_address": parent["customer_address"],
            "customer_latitude": parent.get("customer_latitude"), "customer_longitude": parent.get("customer_longitude"),
            "source": parent.get("source", "S"), "total_amount": command.financial.products_bani / 100,
            "payment_type": command.payment_type,
            "items": [{"name": item.name, "quantity": item.quantity, "price": item.unit_price_bani / 100} for item in command.items],
            "notes": command.description})


def _child_command(parent, command):
    try:
        return _build_child_command(parent, command)
    except (KeyError, TypeError, ValidationError):
        raise _error(409, "ORDER_DATA_INVALID") from None


def _validate_parent(parent, command):
    if parent is None:
        raise _error(404, "ORDER_NOT_FOUND")
    version = parent.get("order_version")
    if "order_version" not in parent:
        raise _error(409, "ORDER_VERSION_REQUIRED")
    if type(version) not in (int, Int64) or not 0 <= version <= MAX_ORDER_VERSION:
        raise _error(409, "ORDER_DATA_INVALID")
    if version == MAX_ORDER_VERSION:
        raise _error(409, "ORDER_VERSION_EXHAUSTED")
    if version != command.expected_order_version:
        raise _error(409, "ORDER_VERSION_CONFLICT")
    if parent.get("status") != "DELIVERED":
        raise _error(409, "REMAKE_REQUIRES_DELIVERED")
    if "has_problem_followup" in parent and type(parent["has_problem_followup"]) is not bool:
        raise _error(409, "ORDER_DATA_INVALID")
    if parent.get("has_problem_followup") or any(parent.get(name) is not None for name in
            ("problem_followup_order_id", "problem_followup_operation_ref")):
        raise _error(409, "REMAKE_ALREADY_EXISTS")
    order_financial_snapshot(parent)
    try:
        inspect_custody(parent)
    except CustodyError:
        raise _error(409, "ORDER_DATA_INVALID", "Custodia necesita verificare inainte de refacere.") from None


def _require_financial_context(actor, context):
    if (type(context) is not VerifiedFinancialContext or context.actor_role not in ("admin", "restaurant")
            or context.actor_id != _identity(actor) or context.actor_role != actor.get("role")
            or context.restaurant_id != actor.get("restaurant_id")):
        raise _error(403, "FINANCIAL_CONTEXT_REQUIRED")
    _identifier(context.actor_id)
    if context.actor_role == "restaurant":
        _identifier(context.restaurant_id)


def _confirmed(operation):
    return "remake_terminal_contract_version" in operation or "terminal_kind" in operation or (
        isinstance(operation.get("command"), dict) and "quote_confirmation" in operation["command"])


def _terminal(operation):
    return "remake_terminal_contract_version" in operation or "terminal_kind" in operation


class _BoundedCursor:
    """Read-only F3 adapter: server size/row bounds, retaining transaction session."""
    def __init__(self, collection, query, projection, session):
        self.collection, self.query, self.projection, self.session = collection, query, projection, session
        self.bound = 2

    def limit(self, limit):
        if type(limit) is not int or not 1 <= limit <= 5:
            raise _error(503, "REMAKE_DATA_INVALID")
        self.bound = limit
        return self

    async def to_list(self, length):
        if type(length) is not int or not 1 <= length <= 5:
            raise _error(503, "REMAKE_DATA_INVALID")
        size = self.collection.size
        pipeline = [{"$match": self.query}, {"$limit": min(length, self.bound)}, {"$project": {"_id": 0,
            "document": {"$cond": [{"$lte": [{"$bsonSize": "$$ROOT"}, size]}, "$$ROOT", None]}}}]
        kwargs = {"maxTimeMS": 2000}
        if self.session is not None:
            kwargs["session"] = self.session
        rows = await self.collection.raw.aggregate(pipeline, **kwargs).to_list(min(length, self.bound))
        result = []
        for row in rows:
            document = row.get("document")
            if not isinstance(document, dict):
                raise _error(503, "REMAKE_DATA_INVALID")
            if self.projection:
                document = {key: value for key, value in document.items()
                    if self.projection.get(key, key == "_id")}
            result.append(document)
        return result


class _BoundedCollection:
    def __init__(self, raw, size):
        self.raw, self.size = raw, size

    def find(self, query, projection=None, *, session=None):
        return _BoundedCursor(self, query, projection, session)

    async def find_one(self, query, projection=None, *, session=None):
        rows = await self.find(query, projection, session=session).to_list(2)
        if len(rows) > 1:
            raise _error(503, "REMAKE_DATA_INVALID")
        return rows[0] if rows else None


class _BoundedDatabase:
    SIZES = {"users": 8192, "drivers": 8192, "restaurants": 16384, "orders": 65536,
        "order_operations": 65536, "order_operation_settings": 4096,
        "order_custody_events": 16384, "order_incidents": 8192}

    def __init__(self, raw):
        self.raw = raw

    def get_collection(self, name, **options):
        return _BoundedCollection(self.raw.get_collection(name, **options), self.SIZES[name])

    def __getattr__(self, name):
        if name in self.SIZES:
            return self.get_collection(name)
        raise AttributeError(name)


def _parent_public(parent):
    if "order_version" not in parent:
        raise _error(409, "ORDER_VERSION_REQUIRED")
    values = {key: parent.get(key) for key in RemakeParent.model_fields if key not in ("order_id", "source", "has_problem_followup")}
    values.update(order_id=parent.get("id"), source=parent.get("source", "S"),
        has_problem_followup=parent.get("has_problem_followup", False))
    for key in ("order_version", "delivery_zone_level"):
        if type(values[key]) is Int64:
            values[key] = int(values[key])
    try:
        result = RemakeParent.model_validate(values)
        ref = parent.get("problem_followup_operation_ref")
        if result.has_problem_followup != (ref is not None):
            raise ValueError()
        if ref is not None:
            _identifier(ref)
        return result
    except (ValidationError, ValueError):
        raise _error(409, "ORDER_DATA_INVALID") from None


def _restaurant_flags(restaurant):
    if restaurant is not None and any(name in restaurant and type(restaurant[name]) is not bool
            for name in ("account_disabled", "is_active", "accepting_orders")):
        raise _error(409, "RESTAURANT_INVALID")


class OrderRemakeService:
    def __init__(self, database):
        self.db = database
        self.creation = OrderCreationService(database)
        self.operations = database.get_collection("order_operations", write_concern=MAJORITY,
            read_concern=ReadConcern("majority"), read_preference=ReadPreference.PRIMARY)
        self.reads = _BoundedDatabase(database)
        self.financial_creation = OrderCreationService(self.reads)
        self.financial_operations = _BoundedCollection(self.operations, 65536)

    async def _actor(self, actor, restaurant_id, context, session=None):
        if context is None:
            return await self.creation._actor(actor, restaurant_id, session)
        _require_financial_context(actor, context)
        return await self.financial_creation._actor(actor, restaurant_id, session)

    @staticmethod
    def _pending(client_operation_id):
        return RemakeOutcome(RemakeResult(client_operation_id=client_operation_id, state="pending", retry_after_seconds=2), 202)

    @staticmethod
    def _outcome(operation, replay=True):
        try:
            state = operation["state"]
            if state == "pending":
                return OrderRemakeService._pending(operation["client_operation_id"])
            if state == "rejected":
                if _terminal(operation):
                    FinancialRemakeTerminal.model_validate(operation)
                    return RemakeOutcome(RemakeResult(client_operation_id=operation["client_operation_id"],
                        state="rejected", error_code=operation["error_code"]), 409)
                if (type(operation.get("error_status")) is not int
                        or BUSINESS_ERRORS.get(operation.get("error_code")) != operation["error_status"]):
                    raise ValueError()
                return RemakeOutcome(RemakeResult(client_operation_id=operation["client_operation_id"], state="rejected",
                    error_code=operation["error_code"]), operation["error_status"])
            if (state != "applied" or operation["order_id"] != operation["child_order_id"]
                    or type(operation["order_version"]) not in (int, Int64) or operation["order_version"] != 0
                    or type(operation["parent_order_version"]) not in (int, Int64)
                    or operation["parent_order_version"] != operation["command"]["expected_order_version"] + 1):
                raise ValueError()
            return RemakeOutcome(RemakeResult(client_operation_id=operation["client_operation_id"],
                state="replayed" if replay else "applied", order_id=operation["order_id"], order_version=0,
                parent_order_id=operation["target_order_id"], parent_order_version=operation["parent_order_version"]), 200 if replay else 201)
        except (KeyError, TypeError, ValueError):
            raise _error(503, "OPERATION_INVALID") from None

    @classmethod
    def _validated(cls, operation, key, actor, *, financial_context=None):
        if _confirmed(operation):
            _require_financial_context(actor, financial_context)
        elif financial_context is not None:
            raise _error(409, "FINANCIAL_PROTOCOL_REQUIRED")
        try:
            if _terminal(operation):
                terminal = FinancialRemakeTerminal.model_validate(operation)
                for value in (terminal.actor_id, terminal.restaurant_id, terminal.target_order_id):
                    _identifier(value)
                instant = datetime.fromisoformat(terminal.created_at)
                if (terminal.key != key or key != operation_key(_identity(actor), terminal.client_operation_id)
                        or terminal.actor_id != _identity(actor) or terminal.actor_role != actor.get("role")
                        or (terminal.actor_role == "restaurant" and terminal.restaurant_id != actor.get("restaurant_id"))
                        or instant.tzinfo is None or instant.utcoffset().total_seconds() != 0
                        or terminal.created_at != terminal.resolved_at):
                    raise ValueError()
                return None, None
            command = RemakeCommand.model_validate(operation["command"])
            _policy(command)
            target = _identifier(operation["target_order_id"])
            parent = operation["parent_snapshot"]
            child = _child_command(parent, command)
            if (operation["_id"] != key or operation["actor_id"] != _identity(actor)
                    or key != operation_key(_identity(actor), command.client_operation_id)
                    or operation["client_operation_id"] != command.client_operation_id
                    or operation["operation_type"] != "remake" or type(operation["contract_version"]) is not int
                    or operation["contract_version"] != 1 or operation["actor_role"] not in ("admin", "restaurant")
                    or parent["id"] != target or operation["restaurant_id"] != parent["restaurant_id"]
                    or operation["child_order_id"] != str(uuid.uuid5(uuid.NAMESPACE_URL, key))
                    or operation["payload_digest"] != _intent(target, command)
                    or operation["admission_digest"] != _bound_digest(operation)
                    or operation["child_command"] != child.model_dump(mode="json")
                    or str(uuid.UUID(operation["request_id"])) != operation["request_id"]):
                raise ValueError()
            _validate_parent(parent, command)
            admission_snapshot(operation, child)
            cls._outcome(operation)
            return command, child
        except (KeyError, TypeError, ValueError, CreationError):
            raise _error(503, "OPERATION_INVALID") from None

    async def _custody(self, order, session=None, *, financial_context=None):
        try:
            await validate_custody_ledger(self.reads if financial_context is not None else self.db,
                order, inspect_custody(order), session)
        except CustodyError:
            raise _error(409, "ORDER_DATA_INVALID", "Custodia necesita verificare inainte de refacere.") from None

    async def _existing(self, key, order_id, actor, command=None, *, financial_context=None):
        operation = await (self.financial_operations if financial_context is not None else self.operations).find_one({"_id": key})
        if operation is None:
            return None
        self._validated(operation, key, actor, financial_context=financial_context)
        user = await self._actor(actor, operation["restaurant_id"], financial_context)
        if user["role"] != operation["actor_role"]:
            raise _error(403, "AUTH_CONTEXT_CHANGED")
        if order_id != operation["target_order_id"]:
            raise _error(409 if command is not None else 404, "INTENT_CONFLICT" if command is not None else "OPERATION_NOT_FOUND")
        if command is not None:
            if _terminal(operation):
                self._match_close(operation, order_id, CloseFinancialRemake(restaurant_id=operation["restaurant_id"],
                    expected_order_version=command.expected_order_version, quote_confirmation=command.quote_confirmation))
            elif _intent(order_id, command) != operation["payload_digest"]:
                raise _error(409, "INTENT_CONFLICT")
        return operation

    async def _ready(self, new_admission):
        if new_admission:
            setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
            if not setting or setting.get("enabled") is not True:
                raise _error(503, "REMAKE_NOT_ENABLED")
        await self.creation._ready(new_admission=False)

    async def capabilities(self, actor):
        try:
            async with _runtime.request_deadline():
                await self.creation._actor(actor, actor.get("restaurant_id"))
                setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
                if setting is not None and type(setting.get("enabled")) is not bool:
                    raise _error(503, "CAPABILITIES_INVALID")
                finance = await self.db.order_operation_settings.find_one({"_id": "order-finance-v1"})
                return {"remake_recovery_enabled": bool(setting and setting["enabled"] and finance and finance.get("enabled") is True)}
        except (TimeoutError, PyMongoError):
            raise _error(503, "CAPABILITIES_UNAVAILABLE") from None

    @staticmethod
    def _match_close(operation, order_id, close):
        payload = operation if _terminal(operation) else operation["command"]
        if (operation["target_order_id"] != order_id or operation["restaurant_id"] != close.restaurant_id
                or payload["expected_order_version"] != close.expected_order_version
                or payload["quote_confirmation"] != close.quote_confirmation.model_dump(mode="json")):
            raise _error(409, "INTENT_CONFLICT")

    async def _insert_terminal(self, key, order_id, client_operation_id, close, actor, context, code):
        now = datetime.now(timezone.utc).isoformat()
        operation = {"_id": key, "remake_terminal_contract_version": 1,
            "terminal_kind": "financial_remake_not_admitted", "actor_id": _identity(actor),
            "actor_role": actor["role"], "restaurant_id": close.restaurant_id, "target_order_id": order_id,
            "expected_order_version": close.expected_order_version, "client_operation_id": client_operation_id,
            "quote_confirmation": close.quote_confirmation.model_dump(mode="json"), "state": "rejected",
            "error_code": code, "error_status": 409, "created_at": now, "resolved_at": now}
        self._validated(operation, key, actor, financial_context=context)
        try:
            await self.operations.insert_one(operation)
        except DuplicateKeyError:
            pass
        winner = await self._existing(key, order_id, actor, financial_context=context)
        if winner is None:
            return self._pending(client_operation_id)
        self._match_close(winner, order_id, close)
        return self._outcome(winner)

    async def close_financial(self, order_id, client_operation_id, close, actor, *, financial_context):
        _require_financial_context(actor, financial_context)
        _identifier(order_id)
        OperationCommand(client_operation_id=client_operation_id)
        close = CloseFinancialRemake.model_validate(close.model_dump(mode="python"))
        key = operation_key(_identity(actor), client_operation_id)
        attempted = False
        try:
            async with _runtime.request_deadline():
                await self._actor(actor, close.restaurant_id, financial_context)
                existing = await self._existing(key, order_id, actor, financial_context=financial_context)
                if existing is not None:
                    self._match_close(existing, order_id, close)
                    return self._outcome(existing)
                attempted = True
                return await self._insert_terminal(key, order_id, client_operation_id, close, actor,
                    financial_context, "FINANCIAL_INTENT_CLOSED")
        except (TimeoutError, PyMongoError):
            if attempted:
                return self._pending(client_operation_id)
            raise _error(503, "RECOVERY_UNAVAILABLE") from None

    async def parent_context(self, order_id, actor, *, financial_context):
        _require_financial_context(actor, financial_context)
        _identifier(order_id)
        try:
            async with _runtime.request_deadline():
                user = await self._actor(actor, actor.get("restaurant_id"), financial_context)
                query = {"id": order_id}
                if user["role"] == "restaurant":
                    query["restaurant_id"] = user["restaurant_id"]
                parent = await self.reads.orders.find_one(query)
                if parent is None:
                    raise _error(404, "ORDER_NOT_FOUND")
                restaurant_id = _identifier(parent.get("restaurant_id"))
                public = _parent_public(parent)
                await self._actor(actor, restaurant_id, financial_context)
                restaurant = await self.reads.restaurants.find_one({"id": restaurant_id})
                _restaurant_flags(restaurant)
                rejection = self.creation._restaurant_rejection(restaurant)
                if rejection is not None and rejection.code not in ("RESTAURANT_PAUSED", "RESTAURANT_UNAVAILABLE"):
                    raise rejection
                from utils.order_finance_preview import OrderFinancePreviewService
                flags = await OrderFinancePreviewService(self.db)._flags()
                # Invalid stored financial/custody material is never a false capability.
                order_financial_snapshot(parent)
                await self._custody(parent, financial_context=financial_context)
                code = rejection.code if rejection else None
                if code is None and (not flags["finance"] or not flags["remake"]):
                    code = "FINANCIAL_REMAKE_NOT_ENABLED"
                if code is None and public.order_version == MAX_ORDER_VERSION:
                    code = "ORDER_VERSION_EXHAUSTED"
                if code is None and public.status != "DELIVERED":
                    code = "REMAKE_REQUIRES_DELIVERED"
                if code is None and public.has_problem_followup:
                    code = "REMAKE_ALREADY_EXISTS"
                await self._actor(actor, restaurant_id, financial_context)
                return RemakeParentContext(contract_version=1, kind="remake_parent", actor_id=_identity(actor),
                    actor_role=user["role"], restaurant_id=restaurant_id, parent=public,
                    eligibility={"can_preview": code is None, "blocking_code": code}).model_dump(mode="json")
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code) from None
        except (TimeoutError, PyMongoError):
            raise _error(503, "REMAKE_UNAVAILABLE") from None

    async def readback(self, order_id, client_operation_id, actor, *, financial_context):
        _require_financial_context(actor, financial_context)
        _identifier(order_id)
        OperationCommand(client_operation_id=client_operation_id)
        key = operation_key(_identity(actor), client_operation_id)
        try:
            async with _runtime.request_deadline():
                await self._actor(actor, actor.get("restaurant_id"), financial_context)
                operation = await self._existing(key, order_id, actor, financial_context=financial_context)
                if operation is None:
                    raise _error(404, "OPERATION_NOT_FOUND")
                if operation["state"] != "applied":
                    raise _error(409, "REMAKE_READBACK_UNAVAILABLE")
                command, child_command = self._validated(operation, key, actor, financial_context=financial_context)
                restaurant_id = operation["restaurant_id"]
                parent = await self.reads.orders.find_one({"id": order_id, "restaurant_id": restaurant_id})
                child = await self.reads.orders.find_one({"id": operation["child_order_id"], "restaurant_id": restaurant_id})
                if parent is None or child is None:
                    raise _error(503, "REMAKE_READBACK_INVALID")
                receipt = self._outcome(operation).result
                admitted = admission_snapshot(operation, child_command)
                actual = order_financial_snapshot(child)
                original = order_financial_snapshot(operation["parent_snapshot"])
                current_original = order_financial_snapshot(parent)
                if (actual != admitted or original != current_original
                        or parent.get("has_problem_followup") is not True
                        or parent.get("problem_followup_order_id") != child["id"]
                        or child.get("linked_problem_order_id") != parent["id"]
                        or parent.get("problem_followup_operation_ref") != key
                        or child.get("remake_operation_ref") != key or child.get("creation_operation_ref") != key
                        or child.get("payment_type") != command.payment_type
                        or child.get("source") != child_command.order.source):
                    raise _error(503, "REMAKE_READBACK_INVALID")
                versions = [parent.get("order_version"), child.get("order_version")]
                if any(type(value) not in (int, Int64) or not 0 <= value <= MAX_ORDER_VERSION for value in versions):
                    raise _error(503, "REMAKE_READBACK_INVALID")
                if versions[0] < receipt.parent_order_version or versions[1] < receipt.order_version:
                    raise _error(503, "REMAKE_READBACK_INVALID")
                snapshot = admitted.model_dump(mode="json")
                public_financial = {name: snapshot[name] for name in RemakePublicFinancial.model_fields}
                result = RemakeReadback(contract_version=1, kind="remake_readback", actor_id=_identity(actor),
                    actor_role=actor["role"], restaurant_id=restaurant_id, client_operation_id=client_operation_id,
                    quote_confirmation=command.quote_confirmation, receipt=receipt,
                    parent={"order_id": parent["id"], "order_version": int(versions[0]), "status": parent.get("status"),
                        "has_problem_followup": True, "problem_followup_order_id": child["id"]},
                    child={"order_id": child["id"], "order_version": int(versions[1]), "status": child.get("status"),
                        "linked_problem_order_id": parent["id"], "creation_kind": "remake",
                        "source": child.get("source"), "payment_type": child.get("payment_type")}, financial=public_financial)
                await self._actor(actor, restaurant_id, financial_context)
                return result.model_dump(mode="json")
        except (ValidationError, FinanceError, KeyError, TypeError, ValueError):
            raise _error(503, "REMAKE_READBACK_INVALID") from None
        except (TimeoutError, PyMongoError):
            raise _error(503, "RECOVERY_UNAVAILABLE") from None

    @staticmethod
    def _operation_size(operation):
        # Reserve both successful receipt and longest refusal before admission.
        complete = {**operation, "order_id": operation["child_order_id"], "order_version": 0,
            "parent_order_version": operation["command"]["expected_order_version"] + 1,
            "resolved_at": operation["created_at"], "error_code": "FINANCIAL_SNAPSHOT_INVALID", "error_status": 409}
        if len(BSON.encode(complete)) > 65536:
            raise _error(413, "REQUEST_TOO_LARGE")

    async def _submit_confirmed(self, order_id, command, actor, context, signing_key):
        _require_financial_context(actor, context)
        if command.quote_confirmation is None:
            raise _error(422, "QUOTE_CONFIRMATION_REQUIRED")
        key = operation_key(_identity(actor), command.client_operation_id)
        attempted = False
        try:
            async with _runtime.request_deadline():
                await self._actor(actor, actor.get("restaurant_id"), context)
                existing = await self._existing(key, order_id, actor, command, financial_context=context)
                if existing is not None and existing["state"] != "pending":
                    return self._outcome(existing)
                # Admitted recovery is independent of current markers, signing key and grids.
                await self._ready(new_admission=False)
                if existing is None:
                    from utils.order_finance_preview import OrderFinancePreviewService
                    key_material = signing_key() if callable(signing_key) else signing_key
                    prepared = await OrderFinancePreviewService(self.db, signing_key=key_material).prepare_remake_confirmation(
                        order_id, command, actor, key)
                    user = await self._actor(actor, prepared.parent_snapshot["restaurant_id"], context)
                    if not hmac.compare_digest(prepared.quote_fingerprint, command.quote_confirmation.quote_fingerprint):
                        close = CloseFinancialRemake(restaurant_id=prepared.parent_snapshot["restaurant_id"],
                            expected_order_version=command.expected_order_version, quote_confirmation=command.quote_confirmation)
                        attempted = True
                        return await self._insert_terminal(key, order_id, command.client_operation_id, close, actor,
                            context, "FINANCIAL_QUOTE_CHANGED")
                    operation = {"_id": key, "operation_type": "remake", "contract_version": 1,
                        "actor_id": _identity(actor), "actor_role": user["role"], "restaurant_id": prepared.parent_snapshot["restaurant_id"],
                        "target_order_id": order_id, "client_operation_id": command.client_operation_id,
                        "payload_digest": _intent(order_id, command), "command": command.model_dump(mode="json"),
                        "parent_snapshot": prepared.parent_snapshot, "child_command": prepared.child_command.model_dump(mode="json"),
                        "child_order_id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)), "state": "pending",
                        "request_id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
                        "financial_snapshot": prepared.financial_snapshot}
                    operation["admission_digest"] = _bound_digest(operation)
                    self._validated(operation, key, actor, financial_context=context)
                    self._operation_size(operation)
                    attempted = True
                    try:
                        await self.operations.insert_one(operation)
                    except DuplicateKeyError:
                        existing = await self._existing(key, order_id, actor, command, financial_context=context)
                        if existing is None:
                            return self._pending(command.client_operation_id)
                        if existing["state"] != "pending":
                            return self._outcome(existing)
                attempted = True
                return await self._execute(key, actor, command.client_operation_id, financial_context=context)
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        except (TimeoutError, PyMongoError):
            if attempted:
                return self._pending(command.client_operation_id)
            raise _error(503, "REMAKE_UNAVAILABLE") from None

    async def submit(self, order_id, command, actor, *, financial_context=None, signing_key=None):
        command = RemakeCommand.model_validate(command.model_dump(mode="python", exclude_unset=True))
        order_id = _identifier(order_id)
        _policy(command)
        if command.quote_confirmation is not None or financial_context is not None:
            return await self._submit_confirmed(order_id, command, actor, financial_context, signing_key)
        key = operation_key(_identity(actor), command.client_operation_id)
        attempted = False
        try:
            async with _runtime.request_deadline():
                existing = await self._existing(key, order_id, actor, command)
                if existing is not None and existing["state"] != "pending":
                    return self._outcome(existing)
                await self._ready(new_admission=existing is None)
                if existing is None:
                    parent = await self.db.orders.find_one({"id": order_id})
                    # Authorize before revealing any order state or financial details.
                    await self.creation._actor(actor, parent.get("restaurant_id") if parent else actor.get("restaurant_id"))
                    _validate_parent(parent, command)
                    await self._custody(parent)
                    user = await self.creation._actor(actor, parent["restaurant_id"])
                    child = _child_command(parent, command)
                    if await self.db.delivery_zones.count_documents({"is_active": True,
                            "restaurant_id": parent["restaurant_id"]}, limit=301) > 300:
                        raise FinanceError("FINANCIAL_ZONE_UNVERIFIED")
                    zone = await self.creation._zone(child.order, None)
                    operation = {"_id": key, "operation_type": "remake", "contract_version": 1,
                        "actor_id": _identity(actor), "actor_role": user["role"], "restaurant_id": parent["restaurant_id"],
                        "target_order_id": order_id, "client_operation_id": command.client_operation_id,
                        "payload_digest": _intent(order_id, command), "command": command.model_dump(mode="json"),
                        "parent_snapshot": _parent_snapshot(parent), "child_command": child.model_dump(mode="json"),
                        "child_order_id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)), "state": "pending",
                        "request_id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
                        "financial_snapshot": await quote_at_admission(self.db, child, user, key, zone)}
                    operation["admission_digest"] = _bound_digest(operation)
                    self._validated(operation, key, actor)
                    attempted = True
                    try:
                        await self.operations.insert_one(operation)
                    except DuplicateKeyError:
                        existing = await self._existing(key, order_id, actor, command)
                        if existing is None:
                            return self._pending(command.client_operation_id)
                        if existing["state"] != "pending":
                            return self._outcome(existing)
                attempted = True
                return await self._execute(key, actor, command.client_operation_id)
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        except ValidationError:
            raise _error(409, "ORDER_DATA_INVALID") from None
        except (TimeoutError, PyMongoError):
            logger.warning("order_remake_uncertain operation_ref=%s admitted=%s", key, attempted)
            if attempted:
                return self._pending(command.client_operation_id)
            raise _error(503, "REMAKE_UNAVAILABLE") from None

    async def lookup(self, order_id, client_operation_id, actor, *, financial_context=None):
        if financial_context is None:
            return await self._recover(order_id, client_operation_id, actor, resume=False)
        return await self._recover(order_id, client_operation_id, actor, resume=False, financial_context=financial_context)

    async def resume(self, order_id, client_operation_id, actor, *, financial_context=None):
        if financial_context is None:
            return await self._recover(order_id, client_operation_id, actor, resume=True)
        return await self._recover(order_id, client_operation_id, actor, resume=True, financial_context=financial_context)

    async def _recover(self, order_id, client_operation_id, actor, resume, *, financial_context=None):
        if financial_context is not None:
            _require_financial_context(actor, financial_context)
        _identifier(order_id)
        OperationCommand(client_operation_id=client_operation_id)
        key = operation_key(_identity(actor), client_operation_id)
        attempted = False
        try:
            async with _runtime.request_deadline():
                await self._actor(actor, actor.get("restaurant_id"), financial_context)
                operation = await self._existing(key, order_id, actor, financial_context=financial_context)
                if operation is None:
                    raise _error(404, "OPERATION_NOT_FOUND")
                if not resume or operation["state"] != "pending":
                    return self._outcome(operation)
                await self._ready(new_admission=False)
                attempted = True
                if financial_context is None:
                    return await self._execute(key, actor, client_operation_id)
                return await self._execute(key, actor, client_operation_id, financial_context=financial_context)
        except (TimeoutError, PyMongoError):
            if attempted:
                return self._pending(client_operation_id)
            raise _error(503, "RECOVERY_UNAVAILABLE") from None

    async def _execute(self, key, actor, client_operation_id, *, financial_context=None):
        if financial_context is not None:
            _require_financial_context(actor, financial_context)
        reads = self.reads if financial_context is not None else self.db
        for attempt in range(MAX_ATTEMPTS):
            session = await _runtime.start_session(self.db.client)
            lifecycle = SessionLifecycle(_runtime, session)
            try:
                session.start_transaction(read_concern=ReadConcern("snapshot"), write_concern=MAJORITY,
                    read_preference=ReadPreference.PRIMARY, max_commit_time_ms=2000)
                try:
                    operation = await lifecycle.wait((self.financial_operations if financial_context is not None else self.operations)
                        .find_one({"_id": key}, session=session))
                    if operation is None:
                        raise _error(503, "OPERATION_INVALID")
                    command, child = self._validated(operation, key, actor, financial_context=financial_context)
                    user = await lifecycle.wait(self._actor(actor, operation["restaurant_id"], financial_context, session))
                    if user["role"] != operation["actor_role"]:
                        raise _error(403, "AUTH_CONTEXT_CHANGED")
                    if operation["state"] != "pending":
                        return self._outcome(operation)
                    actor_filter = {"_id": user["_id"], "role": user["role"], "account_disabled": {"$ne": True}}
                    if user["role"] == "restaurant":
                        actor_filter["restaurant_id"] = operation["restaurant_id"]
                    guard = await lifecycle.wait(self.db.users.update_one(actor_filter,
                        {"$inc": {"order_admission_revision": 1}}, session=session))
                    if guard.matched_count != 1:
                        raise _error(403, "AUTH_CONTEXT_CHANGED")
                    rejection = None
                    try:
                        parent = await lifecycle.wait(reads.orders.find_one({"id": operation["target_order_id"],
                            "restaurant_id": operation["restaurant_id"]}, session=session)) if financial_context is not None else await lifecycle.wait(
                            self.db.orders.find_one({"id": operation["target_order_id"]}, session=session))
                        if parent and parent.get("restaurant_id") != operation["restaurant_id"]:
                            raise _error(403, "AUTH_CONTEXT_CHANGED")
                        _validate_parent(parent, command)
                        if financial_context is None:
                            await lifecycle.wait(self._custody(parent, session))
                        else:
                            await lifecycle.wait(self._custody(parent, session, financial_context=financial_context))
                        if _parent_snapshot(parent) != operation["parent_snapshot"]:
                            raise _error(409, "REMAKE_PARENT_CHANGED")
                        if await lifecycle.wait(reads.drivers.find_one({"current_order_id": parent["id"]}, session=session)):
                            raise _error(409, "CUSTODY_RESOLUTION_REQUIRED")
                        restaurant = await lifecycle.wait(reads.restaurants.find_one({"id": operation["restaurant_id"]}, session=session))
                        if financial_context is not None:
                            _restaurant_flags(restaurant)
                        rejection = self.creation._restaurant_rejection(restaurant)
                        if restaurant:
                            await lifecycle.wait(self.db.restaurants.update_one({"_id": restaurant["_id"]},
                                {"$inc": {"order_admission_revision": 1}}, session=session))
                    except (CreationError, FinanceError) as exc:
                        rejection = exc
                    # Business refusal is recorded only before any order/counter/audit write.
                    if rejection is not None:
                        if BUSINESS_ERRORS.get(rejection.code) != rejection.status_code:
                            raise rejection
                        updated = await lifecycle.wait(self.operations.update_one({"_id": key, "state": "pending"}, {"$set": {
                            "state": "rejected", "error_code": rejection.code, "error_status": rejection.status_code,
                            "resolved_at": datetime.now(timezone.utc).isoformat()}}, session=session))
                        if updated.matched_count != 1:
                            raise _error(503, "OPERATION_INVALID")
                    else:
                        await lifecycle.wait(self._apply(operation, command, child, user, parent, restaurant, session))
                    if not await lifecycle.wait(_runtime.commit(session, 3)):
                        return self._pending(client_operation_id)
                    resolved = await self._existing(key, operation["target_order_id"], actor, financial_context=financial_context)
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

    async def _apply(self, operation, command, child, user, parent, restaurant, session):
        financial = admission_snapshot(operation, child)
        now = datetime.now(timezone.utc).isoformat()
        child_id = operation["child_order_id"]
        audit_parent_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":parent"))
        audit_child_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":child"))
        audit_base = {"performed_by": user["id"], "performed_by_role": user["role"], "created_at": now,
                      "operation_ref": operation["_id"], "request_id": operation["request_id"]}
        parent_audit = {**audit_base, "id": audit_parent_id, "action": "order.remake_linked",
            "changes": {"problem_followup_order_id": child_id},
            "from_order_version": int(parent["order_version"]), "to_order_version": int(parent["order_version"]) + 1}
        query = {"_id": parent["_id"], "id": parent["id"], "restaurant_id": operation["restaurant_id"],
                 "status": "DELIVERED", "has_problem_followup": {"$ne": True},
                 "problem_followup_order_id": None, "problem_followup_operation_ref": None, **revision_filter(parent)}
        updated = await self.db.orders.update_one(query, revision_update(parent, {"$set": {
            "has_problem_followup": True, "problem_followup_order_id": child_id,
            "problem_followup_operation_ref": operation["_id"], "updated_at": now}, "$push": {"audit_trail": parent_audit}}), session=session)
        if updated.matched_count != 1:
            raise _error(503, "REMAKE_WRITE_CONFLICT")
        counter = await self.db.counters.find_one({"_id": COUNTER_ID}, session=session)
        if not counter or type(counter.get("seq")) not in (int, Int64) or not 0 <= counter["seq"] < MAX_ORDER_VERSION:
            raise _error(503, "COUNTER_NOT_READY")
        counter = await self.db.counters.find_one_and_update({"_id": COUNTER_ID}, {"$inc": {"seq": 1}},
            session=session, return_document=ReturnDocument.AFTER)
        child_audit = {**audit_base, "id": audit_child_id, "action": "order.remake_created",
            "changes": {"linked_problem_order_id": parent["id"], "financial_snapshot_digest": financial.snapshot_digest},
            "from_order_version": None, "to_order_version": 0}
        values = child.order.model_dump(mode="python")
        values.update(id=child_id, order_number=f"{child.order.source.upper()}.{counter['seq']:04d}P",
            restaurant_name=restaurant["name"], order_version=0, preparation_status="NEW", status="NEW",
            subtotal_amount=financial.products_bani / 100, delivery_fee=financial.restaurant_transport_bani / 100,
            total_amount=financial.client_collection_bani / 100, financial_contract_version=1,
            financial=financial.model_dump(mode="json"), creation_operation_ref=operation["_id"],
            delivery_zone_id=financial.zone_id, delivery_zone_name=financial.zone_name,
            delivery_sector=financial.zone_sector, delivery_zone_level=financial.zone_level, zone=financial.zone_name,
            linked_problem_order_id=parent["id"], problem_type=command.problem_type, problem_description=command.description,
            remake_operation_ref=operation["_id"], created_at=now, updated_at=now, audit_trail=[child_audit])
        doc = Order(**values).model_dump(mode="json")
        await self.db.orders.insert_one({"_id": child_id, **doc}, session=session)
        for audit, order_id in ((parent_audit, parent["id"]), (child_audit, child_id)):
            await self.db.audit_logs.insert_one({"_id": audit["id"], **audit, "entity_type": "order", "entity_id": order_id}, session=session)
        receipt = await self.operations.update_one({"_id": operation["_id"], "state": "pending"}, {"$set": {
            "state": "applied", "order_id": child_id, "order_version": 0,
            "parent_order_version": int(parent["order_version"]) + 1, "resolved_at": now}}, session=session)
        if receipt.matched_count != 1:
            raise _error(503, "OPERATION_INVALID")
        logger.info("order_remake_prepared operation_ref=%s request_id=%s", operation["_id"], operation["request_id"])
