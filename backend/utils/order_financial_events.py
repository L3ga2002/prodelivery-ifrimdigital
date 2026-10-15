"""Atomic L4A ledger events and projection, with recoverable actor-bound intents."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import uuid

from bson.int64 import Int64
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference

from models.financial_activity import FinancialActivity, activity_digest
from models.order_financial_events import FinancialEventCommand
from models.order_mutation import MutationResult, OperationCommand, StatusOrderCommand
from utils.financial_activity import inspect_activity
from utils.order_finance import FinanceError, order_financial_snapshot, validate_snapshot
from utils.order_operation_runtime import OperationRuntime, SessionLifecycle
from utils.order_revision import revision_filter, revision_update, MAX_ORDER_VERSION
from utils.order_status import OrderStatusService, StatusError, StatusOutcome, MAJORITY, _identity, _identifier, _snapshot, _timestamp, BUSINESS_ERRORS as STATUS_ERRORS

logger = logging.getLogger(__name__)
SETTINGS_ID = "order-financial-events-v1"
DEADLINE_SECONDS = 10
MAX_ATTEMPTS = 3
_BACKGROUND_WORK = set()
_runtime = OperationRuntime(lambda: DEADLINE_SECONDS, lambda: 0.25, _BACKGROUND_WORK, logger, "order_financial_event")
BUSINESS_ERRORS = {**STATUS_ERRORS, "FINANCIAL_ACTIVITY_INVALID": 409, "FINANCIAL_EVENT_REQUIRES_ACCEPTED": 409,
    "FINANCIAL_EVENT_NOT_ELIGIBLE": 409, "FINANCIAL_DECLARATION_EXISTS": 409,
    "FINANCIAL_DECLARATION_REQUIRED": 409, "FINANCIAL_DECLARATION_CHANGED": 409,
    "FINANCIAL_APPROVAL_EXISTS": 409, "FINANCIAL_EVENT_AMOUNT_MISMATCH": 409}


def _error(status, code, message="Evidenta numerarului necesita verificare. Pastreaza aceeasi intentie."):
    return StatusError(status, code, message)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def operation_key(actor_id, client_operation_id):
    return "financial-event:" + _digest([actor_id, "financial-event", client_operation_id])


def _intent(order_id, command):
    return _digest({"target": order_id, "command": command.model_dump(mode="json", exclude={"client_operation_id"})})


def _bound_digest(operation):
    return _digest({k: operation[k] for k in ("_id", "operation_type", "contract_version", "actor_id", "actor_role",
        "actor_driver_id", "actor_restaurant_id", "target_order_id", "restaurant_id", "client_operation_id",
        "payload_digest", "command", "financial_snapshot", "financial_activity_snapshot", "assigned_at", "accepted_at",
        "driver_id", "event_id", "created_at", "request_id")})


class OrderFinancialEventService(OrderStatusService):
    @staticmethod
    def _pending(client_operation_id):
        return StatusOutcome(MutationResult(client_operation_id=client_operation_id, state="pending", retry_after_seconds=2), 202)

    @staticmethod
    def _outcome(operation, replay=True):
        try:
            cmd = FinancialEventCommand.model_validate(operation["command"])
            state = operation["state"]
            if state == "pending":
                if any(operation.get(k) is not None for k in ("resolved_at", "order_id", "order_version", "error_code", "error_status")):
                    raise ValueError()
                return OrderFinancialEventService._pending(cmd.client_operation_id)
            if datetime.fromisoformat(operation["resolved_at"]).tzinfo is None:
                raise ValueError()
            if state == "rejected":
                if (type(operation.get("error_status")) is not int
                    or BUSINESS_ERRORS.get(operation.get("error_code")) != operation["error_status"]
                    or operation.get("order_id") is not None or operation.get("order_version") is not None):
                    raise ValueError()
                return StatusOutcome(MutationResult(client_operation_id=cmd.client_operation_id,
                    state="rejected", error_code=operation["error_code"]), operation["error_status"])
            if (state != "applied" or operation.get("order_id") != operation["target_order_id"]
                or type(operation.get("order_version")) not in (int, Int64)
                or operation["order_version"] != cmd.expected_order_version + 1
                or operation.get("error_code") is not None or operation.get("error_status") is not None):
                raise ValueError()
            return StatusOutcome(MutationResult(client_operation_id=cmd.client_operation_id, state="replayed" if replay else "applied",
                order_id=operation["order_id"], order_version=int(operation["order_version"])), 200)
        except (KeyError, TypeError, ValueError):
            raise _error(503, "OPERATION_INVALID") from None

    @classmethod
    def _validated(cls, operation, key, actor):
        try:
            cmd = FinancialEventCommand.model_validate(operation["command"])
            expected_role = "driver" if cmd.event_type == "advance_not_paid_declared" else "restaurant"
            if (operation["_id"] != key or key != operation_key(_identity(actor), cmd.client_operation_id)
                or operation["actor_id"] != _identity(actor) or operation["actor_role"] != expected_role
                or operation["actor_role"] != actor.get("role")
                or operation["actor_driver_id"] != (actor.get("driver_id") if expected_role == "driver" else None)
                or operation["actor_restaurant_id"] != (actor.get("restaurant_id") if expected_role == "restaurant" else None)
                or operation["operation_type"] != "financial-event" or type(operation["contract_version"]) is not int
                or operation["contract_version"] != 1 or operation["client_operation_id"] != cmd.client_operation_id
                or operation["payload_digest"] != _intent(operation["target_order_id"], cmd)
                or operation["admission_digest"] != _bound_digest(operation)
                or operation["event_id"] != str(uuid.uuid5(uuid.NAMESPACE_URL, key + ":event"))
                or str(uuid.UUID(operation["request_id"])) != operation["request_id"]
                or datetime.fromisoformat(operation["created_at"]).tzinfo is None):
                raise ValueError()
            for field in ("target_order_id", "restaurant_id"):
                _identifier(operation[field], 503, "OPERATION_INVALID")
            if operation["driver_id"] is not None:
                _identifier(operation["driver_id"], 503, "OPERATION_INVALID")
            quote = validate_snapshot(operation["financial_snapshot"])
            if quote.restaurant_id != operation["restaurant_id"] or quote.advance_required_bani <= 0 or quote.collection_mode != "cash":
                raise ValueError()
            snapshot = operation["financial_activity_snapshot"]
            if snapshot is not None:
                activity = FinancialActivity.model_validate(snapshot)
                if (activity.driver_id != operation["driver_id"] or activity.order_id != operation["target_order_id"]
                    or activity.restaurant_id != operation["restaurant_id"] or activity.declared_unpaid_bani != quote.advance_required_bani
                    or activity.financial_snapshot_digest != quote.snapshot_digest
                    or activity.assigned_at != operation["assigned_at"] or activity.accepted_at != operation["accepted_at"]):
                    raise ValueError()
            cls._outcome(operation)
            return cmd
        except (KeyError, TypeError, ValueError, FinanceError, StatusError):
            raise _error(503, "OPERATION_INVALID") from None

    @staticmethod
    def _scope(order, actor, command):
        if order is None:
            raise _error(404, "ORDER_NOT_FOUND")
        if command.event_type == "advance_not_paid_declared":
            allowed = actor.get("role") == "driver" and actor.get("driver_id") == order.get("driver_id")
        else:
            allowed = actor.get("role") == "restaurant" and actor.get("restaurant_id") == order.get("restaurant_id")
        if not allowed:
            raise _error(403, "NOT_AUTHORIZED")

    async def _existing_event(self, key, order_id, actor, command=None):
        await self._actor(actor)
        op = await self.operations.find_one({"_id": key})
        if op is None:
            return None
        admitted = self._validated(op, key, actor)
        if op["target_order_id"] != order_id:
            raise _error(409 if command else 404, "INTENT_CONFLICT" if command else "OPERATION_NOT_FOUND")
        if command is not None and op["payload_digest"] != _intent(order_id, command):
            raise _error(409, "INTENT_CONFLICT")
        if op["state"] == "pending":
            self._scope(await self._load_order(order_id), actor, admitted)
        return op

    async def _ready(self, new_admission):
        if new_admission:
            setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
            if setting is not None and type(setting.get("enabled")) is not bool:
                raise _error(503, "CAPABILITIES_INVALID")
            if not setting or not setting["enabled"]:
                raise _error(503, "FINANCIAL_EVENT_NOT_ENABLED")
        await super()._ready(new_admission=False)

    async def capabilities(self, actor):
        try:
            async with _runtime.request_deadline():
                await self._actor(actor)
                setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
                if setting is not None and type(setting.get("enabled")) is not bool:
                    raise _error(503, "CAPABILITIES_INVALID")
                enabled = bool(setting and setting["enabled"])
                if enabled:
                    await self._ready(new_admission=False)
                return {"financial_event_recovery_enabled": enabled}
        except (TimeoutError, PyMongoError):
            raise _error(503, "CAPABILITIES_UNAVAILABLE") from None

    async def _event_plan(self, order_id, command, actor, session=None, operation=None):
        order = await self._load_order(order_id, session)
        self._scope(order, actor, command)
        # Reuse the custody validator/claim inspector, without executing a cancellation.
        dummy = StatusOrderCommand(client_operation_id=command.client_operation_id,
            expected_order_version=command.expected_order_version, status="CANCELLED", cancellation_reason="Financial pre-pickup validation")
        binding = {"target_order_id": order_id, "restaurant_id": order["restaurant_id"], "actor_role": "admin",
            "actor_driver_id": None, "actor_restaurant_id": None}
        try:
            preliminary_quote = order_financial_snapshot(order)
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        if preliminary_quote is not None:
            binding["financial_snapshot"] = preliminary_quote.model_dump(mode="json")
        if order.get("status") != "ACCEPTED":
            raise _error(409, "FINANCIAL_EVENT_REQUIRES_ACCEPTED")
        await super()._plan(binding, dummy, session)  # Validates revision, chronology, unique claims and driver account.
        driver = await self._driver(order["driver_id"], session)
        driver_user = await self._driver_user(driver, session)
        if driver.get("account_disabled") or driver_user.get("account_disabled") or driver_user.get("role") != "driver" or driver.get("is_active") is not True:
            raise _error(409, "DRIVER_DISABLED")
        try:
            quote = order_financial_snapshot(order)
            activity = inspect_activity(order)
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        if quote is None or order.get("payment_type") != "CASH" or quote.advance_required_bani <= 0:
            raise _error(409, "FINANCIAL_EVENT_NOT_ELIGIBLE")
        if quote.advance_required_bani != command.amount_bani:
            raise _error(409, "FINANCIAL_EVENT_AMOUNT_MISMATCH")
        if command.event_type == "advance_not_paid_declared":
            if activity is not None:
                raise _error(409, "FINANCIAL_DECLARATION_EXISTS")
        else:
            if activity is None:
                raise _error(409, "FINANCIAL_DECLARATION_REQUIRED")
            if activity.declaration_id != command.declaration_id:
                raise _error(409, "FINANCIAL_DECLARATION_CHANGED")
            if activity.status != "declared":
                raise _error(409, "FINANCIAL_APPROVAL_EXISTS")
        if operation is not None:
            if (order["driver_id"] != operation["driver_id"] or order["assigned_at"] != operation["assigned_at"]
                or order["accepted_at"] != operation["accepted_at"] or quote.model_dump(mode="json") != operation["financial_snapshot"]
                or (activity.model_dump(mode="json") if activity else None) != operation["financial_activity_snapshot"]):
                raise _error(409, "FINANCIAL_DECLARATION_CHANGED")
        restaurants = await self.db.restaurants.find({"id": order["restaurant_id"]}, session=session).limit(2).to_list(2)
        if len(restaurants) != 1:
            raise _error(409, "ORDER_DATA_INVALID")
        return order, quote, activity, driver, driver_user, restaurants[0]

    async def submit(self, order_id, command, actor):
        command = FinancialEventCommand.model_validate(command.model_dump(mode="python", exclude_unset=True))
        _identifier(order_id, 422, "INVALID_ORDER_ID")
        key = operation_key(_identity(actor), command.client_operation_id)
        attempted = False
        try:
            async with _runtime.request_deadline():
                existing = await self._existing_event(key, order_id, actor, command)
                if existing is not None and existing["state"] != "pending":
                    return self._outcome(existing)
                await self._ready(new_admission=existing is None)
                if existing is None:
                    order = await self._load_order(order_id)
                    self._scope(order, actor, command)
                    try:
                        quote = order_financial_snapshot(order)
                        activity = inspect_activity(order)
                    except FinanceError as exc:
                        raise _error(exc.status_code, exc.code, exc.message) from None
                    if quote is None or quote.collection_mode != "cash" or quote.advance_required_bani <= 0:
                        raise _error(409, "FINANCIAL_EVENT_NOT_ELIGIBLE")
                    operation = {"_id": key, "operation_type": "financial-event", "contract_version": 1,
                        "actor_id": _identity(actor), "actor_role": actor["role"], "actor_driver_id": actor.get("driver_id") if actor["role"] == "driver" else None,
                        "actor_restaurant_id": actor.get("restaurant_id") if actor["role"] == "restaurant" else None,
                        "target_order_id": order_id, "restaurant_id": order["restaurant_id"], "client_operation_id": command.client_operation_id,
                        "payload_digest": _intent(order_id, command), "command": command.model_dump(mode="json"),
                        "financial_snapshot": quote.model_dump(mode="json"), "financial_activity_snapshot": activity.model_dump(mode="json") if activity else None,
                        "driver_id": order.get("driver_id"), "assigned_at": order.get("assigned_at"), "accepted_at": order.get("accepted_at"),
                        "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, key + ":event")), "state": "pending",
                        "created_at": _timestamp(), "request_id": str(uuid.uuid4())}
                    operation["admission_digest"] = _bound_digest(operation)
                    self._validated(operation, key, actor)
                    attempted = True
                    try:
                        await self.operations.insert_one(operation)
                    except DuplicateKeyError:
                        existing = await self._existing_event(key, order_id, actor, command)
                        if existing is None:
                            return self._pending(command.client_operation_id)
                        if existing["state"] != "pending":
                            return self._outcome(existing)
                attempted = True
                return await self._execute_event(key, actor, command.client_operation_id)
        except (TimeoutError, PyMongoError):
            logger.warning("order_financial_event_uncertain operation_ref=%s admitted=%s", key, attempted)
            if attempted:
                return self._pending(command.client_operation_id)
            raise _error(503, "FINANCIAL_EVENT_UNAVAILABLE") from None

    async def lookup(self, order_id, client_operation_id, actor):
        return await self._recover_event(order_id, client_operation_id, actor, False)

    async def resume(self, order_id, client_operation_id, actor):
        return await self._recover_event(order_id, client_operation_id, actor, True)

    async def _recover_event(self, order_id, client_operation_id, actor, resume):
        _identifier(order_id, 422, "INVALID_ORDER_ID")
        OperationCommand(client_operation_id=client_operation_id)
        key = operation_key(_identity(actor), client_operation_id)
        attempted = False
        try:
            async with _runtime.request_deadline():
                existing = await self._existing_event(key, order_id, actor)
                if existing is None:
                    raise _error(404, "OPERATION_NOT_FOUND")
                if not resume or existing["state"] != "pending":
                    return self._outcome(existing)
                await self._ready(new_admission=False)
                attempted = True
                return await self._execute_event(key, actor, client_operation_id)
        except (TimeoutError, PyMongoError):
            if attempted:
                return self._pending(client_operation_id)
            raise _error(503, "RECOVERY_UNAVAILABLE") from None

    async def _execute_event(self, key, actor, client_operation_id):
        for attempt in range(MAX_ATTEMPTS):
            session = await _runtime.start_session(self.db.client)
            lifecycle = SessionLifecycle(_runtime, session)
            try:
                session.start_transaction(read_concern=ReadConcern("snapshot"), write_concern=MAJORITY,
                    read_preference=ReadPreference.PRIMARY, max_commit_time_ms=2000)
                try:
                    operation = await lifecycle.wait(self.operations.find_one({"_id": key}, session=session))
                    if operation is None:
                        raise _error(503, "OPERATION_INVALID")
                    command = self._validated(operation, key, actor)
                    user = await lifecycle.wait(self._actor(actor, session))
                    if operation["state"] != "pending":
                        return self._outcome(operation)
                    guard = await lifecycle.wait(self.db.users.update_one({"_id": user["_id"],
                        **_snapshot(user, ("id", "role", "account_disabled", "driver_id", "restaurant_id"))},
                        {"$inc": {"order_admission_revision": 1}}, session=session))
                    if guard.matched_count != 1:
                        raise _error(403, "AUTH_CONTEXT_CHANGED")
                    try:
                        plan = await lifecycle.wait(self._event_plan(operation["target_order_id"], command, actor, session, operation))
                    except StatusError as exc:
                        if BUSINESS_ERRORS.get(exc.code) != exc.status_code:
                            raise
                        changed = await lifecycle.wait(self.operations.update_one({"_id": key, "state": "pending", "admission_digest": operation["admission_digest"]},
                            {"$set": {"state": "rejected", "error_code": exc.code, "error_status": exc.status_code, "resolved_at": _timestamp()}}, session=session))
                        if changed.matched_count != 1:
                            raise _error(503, "OPERATION_INVALID")
                    else:
                        await lifecycle.wait(self._apply_event(operation, command, user, plan, session))
                    if not await lifecycle.wait(_runtime.commit(session, 3)):
                        return self._pending(client_operation_id)
                    resolved = await self._existing_event(key, operation["target_order_id"], actor)
                    return self._outcome(resolved, replay=False) if resolved else self._pending(client_operation_id)
                except PyMongoError as exc:
                    if not exc.has_error_label("TransientTransactionError"):
                        raise
                    if attempt + 1 < MAX_ATTEMPTS:
                        await asyncio.sleep(0.05 * (attempt + 1))
            finally:
                await lifecycle.cleanup()
        return self._pending(client_operation_id)

    async def _apply_event(self, operation, command, user, plan, session):
        order, quote, activity, driver, driver_user, restaurant = plan
        now = _timestamp()
        # Write fences serialize changes in authorization, assignment, account and restaurant identity.
        for collection, record, fields in ((self.db.users, driver_user, ("id", "role", "account_disabled", "driver_id")),
                (self.db.drivers, driver, ("id", "user_id", "current_order_id", "is_active", "driver_status", "account_disabled")),
                (self.db.restaurants, restaurant, ("id",))):
            changed = await collection.update_one({"_id": record["_id"], **_snapshot(record, fields)},
                {"$inc": {"order_financial_event_revision": 1}}, session=session)
            if changed.matched_count != 1:
                raise _error(503, "FINANCIAL_EVENT_WRITE_CONFLICT")
        if activity is None:
            value = {"contract_version": 1, "status": "declared", "driver_id": driver["id"],
                "declared_unpaid_bani": command.amount_bani, "declaration_id": operation["event_id"],
                "approval_id": None, "declared_at": now, "approved_at": None, "picked_up_at": None,
                "outstanding_bani": None, "repayment_due_policy": None, "order_id": order["id"],
                "pickup_event_id": None,
                "declaration_actor_id": user["id"], "approval_actor_id": None, "pickup_actor_id": None,
                "restaurant_id": order["restaurant_id"], "assigned_at": order["assigned_at"], "accepted_at": order["accepted_at"],
                "financial_snapshot_digest": quote.snapshot_digest}
        else:
            value = activity.model_dump(mode="json")
            value.update(status="approved", approval_id=operation["event_id"], approved_at=now, approval_actor_id=user["id"])
        value["activity_digest"] = activity_digest(value)
        projection = FinancialActivity.model_validate(value).model_dump(mode="json")
        audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":audit"))
        audit = {"id": audit_id, "action": "order." + command.event_type,
            "changes": {"declared_unpaid_bani": command.amount_bani, "declaration_id": projection["declaration_id"],
                "approval_id": projection["approval_id"], "financial_activity_status": projection["status"]},
            "performed_by": user["id"], "performed_by_role": user["role"], "created_at": now,
            "operation_ref": operation["_id"], "request_id": operation["request_id"],
            "from_order_version": int(order["order_version"]), "to_order_version": int(order["order_version"]) + 1}
        query = {"_id": order["_id"], **revision_filter(order), **_snapshot(order, ("id", "restaurant_id", "status", "driver_id",
            "assigned_at", "accepted_at", "financial", "financial_contract_version", "creation_operation_ref",
            "financial_activity", "financial_activity_contract_version"))}
        updated = await self.db.orders.update_one(query, revision_update(order, {"$set": {
            "financial_activity": projection, "financial_activity_contract_version": 1, "updated_at": now},
            "$push": {"audit_trail": audit}}), session=session)
        if updated.matched_count != 1:
            raise _error(503, "FINANCIAL_EVENT_WRITE_CONFLICT")
        event = {"_id": operation["event_id"], "id": operation["event_id"], "contract_version": 1,
            "event_type": command.event_type, "order_id": order["id"], "restaurant_id": order["restaurant_id"],
            "driver_id": driver["id"], "amount_bani": command.amount_bani, "declaration_id": projection["declaration_id"],
            "actor_id": user["id"], "actor_role": user["role"], "operation_ref": operation["_id"],
            "financial_snapshot_digest": quote.snapshot_digest, "activity_digest": projection["activity_digest"],
            "assigned_at": projection["assigned_at"], "accepted_at": projection["accepted_at"],
            "from_order_version": int(order["order_version"]), "to_order_version": int(order["order_version"]) + 1,
            "created_at": now, "request_id": operation["request_id"]}
        event["event_digest"] = _digest({k: v for k, v in event.items() if k != "_id"})
        await self.db.get_collection("order_financial_events").insert_one(event, session=session)
        await self.db.audit_logs.insert_one({"_id": audit_id, **audit, "entity_type": "order", "entity_id": order["id"]}, session=session)
        changed = await self.operations.update_one({"_id": operation["_id"], "state": "pending", "admission_digest": operation["admission_digest"]},
            {"$set": {"state": "applied", "order_id": order["id"], "order_version": int(order["order_version"]) + 1, "resolved_at": now}}, session=session)
        if changed.matched_count != 1:
            raise _error(503, "OPERATION_INVALID")
        logger.info("order_financial_event_prepared operation_ref=%s request_id=%s", operation["_id"], operation["request_id"])
