"""Atomic full-products custody with recoverable actor-bound intents."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import uuid

from bson.int64 import Int64
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference

from models.custody_activity import CustodyActivity, CustodyBinding
from utils.custody_activity import inspect_custody, validate_custody_ledger, validate_incident, finance_binding, evolve, CustodyError
from utils.financial_activity import validate_activity_ledger
from models.order_custody import CustodyCommand, ROLES
from models.order_mutation import MutationResult, OperationCommand, StatusOrderCommand, StrictOrderItem
from utils.financial_activity import inspect_activity
from utils.order_finance import FinanceError, order_financial_snapshot
from utils.order_operation_runtime import OperationRuntime, SessionLifecycle
from utils.order_revision import revision_filter, revision_update
from utils.order_status import OrderStatusService, StatusError, StatusOutcome, MAJORITY, _identity, _identifier, _snapshot, _timestamp, BUSINESS_ERRORS as STATUS_ERRORS

logger = logging.getLogger(__name__)
SETTINGS_ID = "order-custody-v1"
DEADLINE_SECONDS = 10
MAX_ATTEMPTS = 3
_BACKGROUND_WORK = set()
_runtime = OperationRuntime(lambda: DEADLINE_SECONDS, lambda: 0.25, _BACKGROUND_WORK, logger, "order_custody")
BUSINESS_ERRORS = {**STATUS_ERRORS, **{name: 409 for name in (
    "CUSTODY_INVALID", "CUSTODY_REQUIRES_PICKUP", "CUSTODY_INCIDENT_INVALID", "CUSTODY_PREDECESSOR_CHANGED",
    "CUSTODY_STATE_CONFLICT", "CUSTODY_WAIT_REQUIRED", "CUSTODY_BINDING_CHANGED")}, "NOT_AUTHORIZED": 403}



def _error(status, code, message="Custodia produselor necesita verificare. Pastreaza aceeasi intentie."):
    return StatusError(status, code, message)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def operation_key(actor_id, client_operation_id):
    return "custody:" + _digest([actor_id, "custody", client_operation_id])


def _intent(order_id, command):
    return _digest({"target": order_id, "command": command.model_dump(mode="json", exclude={"client_operation_id"})})


def _bound_digest(operation):
    return _digest({k: operation[k] for k in ("_id", "operation_type", "contract_version", "actor_id", "actor_role",
        "actor_driver_id", "actor_restaurant_id", "target_order_id", "restaurant_id", "client_operation_id",
        "payload_digest", "command", "binding", "custody_snapshot", "event_id", "created_at", "request_id")})



class OrderCustodyService(OrderStatusService):
    @staticmethod
    def _pending(client_operation_id):
        return StatusOutcome(MutationResult(client_operation_id=client_operation_id, state="pending", retry_after_seconds=2), 202)

    @staticmethod
    def _outcome(operation, replay=True):
        try:
            cmd = CustodyCommand.model_validate(operation["command"])
            state = operation["state"]
            if state == "pending":
                if any(operation.get(k) is not None for k in ("resolved_at", "order_id", "order_version", "error_code", "error_status")):
                    raise ValueError()
                return OrderCustodyService._pending(cmd.client_operation_id)
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
            cmd = CustodyCommand.model_validate(operation["command"])
            expected_role = ROLES[cmd.event_type]
            if (operation["_id"] != key or key != operation_key(_identity(actor), cmd.client_operation_id)
                or operation["actor_id"] != _identity(actor) or operation["actor_role"] != expected_role
                or operation["actor_role"] != actor.get("role")
                or operation["actor_driver_id"] != (actor.get("driver_id") if expected_role == "driver" else None)
                or operation["actor_restaurant_id"] != (actor.get("restaurant_id") if expected_role == "restaurant" else None)
                or operation["operation_type"] != "custody" or type(operation["contract_version"]) is not int
                or operation["contract_version"] != 1 or operation["client_operation_id"] != cmd.client_operation_id
                or operation["payload_digest"] != _intent(operation["target_order_id"], cmd)
                or operation["admission_digest"] != _bound_digest(operation)
                or operation["event_id"] != str(uuid.uuid5(uuid.NAMESPACE_URL, key + ":event"))
                or str(uuid.UUID(operation["request_id"])) != operation["request_id"]
                or datetime.fromisoformat(operation["created_at"]).tzinfo is None):
                raise ValueError()
            for field in ("target_order_id", "restaurant_id"):
                _identifier(operation[field], 503, "OPERATION_INVALID")
            binding = CustodyBinding.model_validate(operation["binding"])
            if binding.order_id != operation["target_order_id"] or binding.restaurant_id != operation["restaurant_id"]:
                raise ValueError()
            snapshot = operation["custody_snapshot"]
            if snapshot is not None and CustodyActivity.model_validate(snapshot).binding != binding:
                raise ValueError()
            cls._outcome(operation)
            return cmd
        except (KeyError, TypeError, ValueError, FinanceError, StatusError):
            raise _error(503, "OPERATION_INVALID") from None

    @staticmethod
    def _scope(order, actor, command):
        if order is None:
            raise _error(404, "ORDER_NOT_FOUND")
        role = ROLES[command.event_type]
        allowed = actor.get("role") == role and (role == "admin" or
            role == "driver" and actor.get("driver_id") == order.get("driver_id") or
            role == "restaurant" and actor.get("restaurant_id") == order.get("restaurant_id"))
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
                raise _error(503, "CUSTODY_NOT_ENABLED")
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
                return {"custody_recovery_enabled": enabled}
        except (TimeoutError, PyMongoError):
            raise _error(503, "CAPABILITIES_UNAVAILABLE") from None

    async def _binding(self, order, driver_user, command, session=None):
        try:
            items = order.get("items")
            if not isinstance(items, list) or len(items) > 200 or len(json.dumps(items, allow_nan=False)) > 65536:
                raise ValueError()
            for item in items:
                StrictOrderItem.model_validate(item)
        except (TypeError, ValueError):
            raise _error(409, "CUSTODY_INVALID") from None
        incident = await self.db.order_incidents.find_one({"_id": command.incident_id}, session=session)
        try:
            validate_incident(incident, order, driver_user["id"])
            if datetime.fromisoformat(incident["reported_at"]) > datetime.now(timezone.utc):
                raise CustodyError()
        except CustodyError:
            raise _error(409, "CUSTODY_INCIDENT_INVALID") from None
        return CustodyBinding(order_id=order["id"], restaurant_id=order["restaurant_id"], driver_id=order["driver_id"],
            driver_user_id=driver_user["id"], assigned_at=order["assigned_at"], accepted_at=order["accepted_at"],
            picked_up_at=order["picked_up_at"], products_digest=_digest(order.get("items")),
            finance_digest=finance_binding(order), incident_digest=_digest({k: v for k, v in incident.items() if k != "_id"})).model_dump(mode="json")

    async def _event_plan(self, order_id, command, actor, session=None, operation=None):
        order = await self._load_order(order_id, session)
        self._scope(order, actor, command)
        if order.get("status") != "PICKED_UP":
            raise _error(409, "CUSTODY_REQUIRES_PICKUP")
        dummy = StatusOrderCommand(client_operation_id=command.client_operation_id,
            expected_order_version=command.expected_order_version, status="DELIVERED")
        status_binding = {"target_order_id": order_id, "restaurant_id": order["restaurant_id"]}
        try:
            quote = order_financial_snapshot(order)
            financial = inspect_activity(order)
            activity = inspect_custody(order)
            await validate_activity_ledger(self.db, order, financial, session)
            await validate_custody_ledger(self.db, order, activity, session)
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        except CustodyError:
            raise _error(409, "CUSTODY_INVALID") from None
        if quote is not None:
            status_binding["financial_snapshot"] = quote.model_dump(mode="json")
        # Reuse lifecycle validation only; ordinary delivery effects and remuneration are never planned.
        shadow = {k: v for k, v in order.items() if k not in {"custody_activity", "custody_contract_version"}}
        OrderStatusService._order_state(status_binding, dummy, shadow)
        driver = await self._driver(order["driver_id"], session)
        driver_user = await self._driver_user(driver, session)
        if (driver.get("account_disabled") or driver_user.get("account_disabled")
            or driver_user.get("role") != "driver" or driver.get("is_active") is not True):
            raise _error(409, "DRIVER_DISABLED")
        claims = await self.db.drivers.find({"current_order_id": order_id}, {"id": 1}, session=session).limit(2).to_list(2)
        orders = await self._current_orders(driver["id"], session)
        if (driver.get("current_order_id") != order_id or driver.get("driver_status") != "delivery" or len(claims) != 1
            or claims[0]["_id"] != driver["_id"] or len(orders) != 1 or orders[0]["_id"] != order["_id"]):
            raise _error(409, "ASSIGNMENT_INCONSISTENT")
        binding = await self._binding(order, driver_user, command, session)
        if activity is not None and (activity.binding.model_dump(mode="json") != binding or activity.incident_id != command.incident_id):
            raise _error(409, "CUSTODY_BINDING_CHANGED")
        if operation is not None and (operation["binding"] != binding
            or operation["custody_snapshot"] != (activity.model_dump(mode="json") if activity else None)):
            raise _error(409, "CUSTODY_BINDING_CHANGED")
        expected = {"delivery_wait_started": None, "delivery_failure_reviewed": "waiting",
            "products_disposition_decided": "reviewed", "products_return_received": "return_requested",
            "products_keep_acknowledged": "keep_authorized"}[command.event_type]
        if (activity.status if activity else None) != expected:
            raise _error(409, "CUSTODY_STATE_CONFLICT")
        if activity is not None:
            if command.predecessor_id != activity.event_ids[-1]:
                raise _error(409, "CUSTODY_PREDECESSOR_CHANGED")
            if command.event_type == "delivery_failure_reviewed" and datetime.now(timezone.utc) < datetime.fromisoformat(activity.wait_eligible_at):
                raise _error(409, "CUSTODY_WAIT_REQUIRED")
        restaurants = await self.db.restaurants.find({"id": order["restaurant_id"]}, session=session).limit(2).to_list(2)
        if len(restaurants) != 1:
            raise _error(409, "ORDER_DATA_INVALID")
        return order, binding, activity, driver, driver_user, restaurants[0]

    async def submit(self, order_id, command, actor):
        command = CustodyCommand.model_validate(command.model_dump(mode="python", exclude_unset=True))
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
                    if order.get("status") != "PICKED_UP":
                        raise _error(409, "CUSTODY_REQUIRES_PICKUP")
                    driver = await self._driver(order.get("driver_id"), None)
                    driver_user = await self._driver_user(driver, None)
                    binding = await self._binding(order, driver_user, command)
                    try:
                        activity = inspect_custody(order)
                    except CustodyError:
                        raise _error(409, "CUSTODY_INVALID") from None
                    operation = {"_id": key, "operation_type": "custody", "contract_version": 1,
                        "actor_id": _identity(actor), "actor_role": actor["role"], "actor_driver_id": actor.get("driver_id") if actor["role"] == "driver" else None,
                        "actor_restaurant_id": actor.get("restaurant_id") if actor["role"] == "restaurant" else None,
                        "target_order_id": order_id, "restaurant_id": order["restaurant_id"], "client_operation_id": command.client_operation_id,
                        "payload_digest": _intent(order_id, command), "command": command.model_dump(mode="json"),
                        "binding": binding, "custody_snapshot": activity.model_dump(mode="json") if activity else None,
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
            logger.warning("order_custody_uncertain operation_ref=%s admitted=%s", key, attempted)
            if attempted:
                return self._pending(command.client_operation_id)
            raise _error(503, "CUSTODY_UNAVAILABLE") from None

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
        order, binding, activity, driver, driver_user, restaurant = plan
        now = _timestamp()
        projection = evolve(activity, command, binding, operation["event_id"], now).model_dump(mode="json")
        terminal = projection["status"] in {"returned", "kept"}
        for collection, record, fields in ((self.db.users, driver_user, ("id", "role", "account_disabled", "driver_id")),
                (self.db.restaurants, restaurant, ("id",))):
            changed = await collection.update_one({"_id": record["_id"], **_snapshot(record, fields)},
                {"$inc": {"order_custody_revision": 1}}, session=session)
            if changed.matched_count != 1:
                raise _error(503, "CUSTODY_WRITE_CONFLICT")
        driver_update = {"$inc": {"order_custody_revision": 1}}
        if terminal:
            driver_update["$set"] = {"current_order_id": None, "driver_status": "active"}
        changed = await self.db.drivers.update_one({"_id": driver["_id"], **_snapshot(driver,
            ("id", "user_id", "current_order_id", "is_active", "driver_status", "account_disabled"))}, driver_update, session=session)
        if changed.matched_count != 1:
            raise _error(503, "CUSTODY_WRITE_CONFLICT")
        audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":audit"))
        audit = {"id": audit_id, "action": "order." + command.event_type,
            "changes": {"custody_status": projection["status"], "incident_id": command.incident_id,
                "custody_event_id": operation["event_id"], "decision": projection["decision"]},
            "performed_by": user["id"], "performed_by_role": user["role"], "created_at": now,
            "operation_ref": operation["_id"], "request_id": operation["request_id"],
            "from_order_version": int(order["order_version"]), "to_order_version": int(order["order_version"]) + 1}
        changed = {"custody_activity": projection, "custody_contract_version": 1, "updated_at": now}
        if terminal:
            changed.update(status="CANCELLED", cancelled_at=now, cancelled_by=user["id"],
                cancellation_reason="custody_" + projection["status"])
        query = {"_id": order["_id"], **revision_filter(order), **_snapshot(order, ("id", "restaurant_id", "status", "driver_id",
            "assigned_at", "accepted_at", "picked_up_at", "delivered_at", "cancelled_at", "items", "financial", "financial_contract_version",
            "creation_operation_ref", "financial_activity", "financial_activity_contract_version", "custody_activity", "custody_contract_version"))}
        updated = await self.db.orders.update_one(query, revision_update(order, {"$set": changed, "$push": {"audit_trail": audit}}), session=session)
        if updated.matched_count != 1:
            raise _error(503, "CUSTODY_WRITE_CONFLICT")
        event = {"_id": operation["event_id"], "id": operation["event_id"], "contract_version": 1,
            "event_type": command.event_type, "order_id": order["id"], "restaurant_id": order["restaurant_id"],
            "driver_id": driver["id"], "actor_id": user["id"], "actor_role": user["role"], "operation_ref": operation["_id"],
            "command": command.model_dump(mode="json"), "binding": binding, "created_at": now,
            "from_order_version": int(order["order_version"]), "to_order_version": int(order["order_version"]) + 1}
        event["event_digest"] = _digest({k: v for k, v in event.items() if k != "_id"})
        await self.db.get_collection("order_custody_events").insert_one(event, session=session)
        await self.db.audit_logs.insert_one({"_id": audit_id, **audit, "entity_type": "order", "entity_id": order["id"]}, session=session)
        changed = await self.operations.update_one({"_id": operation["_id"], "state": "pending", "admission_digest": operation["admission_digest"]},
            {"$set": {"state": "applied", "order_id": order["id"], "order_version": int(order["order_version"]) + 1, "resolved_at": now}}, session=session)
        if changed.matched_count != 1:
            raise _error(503, "OPERATION_INVALID")
        logger.info("order_custody_prepared operation_ref=%s request_id=%s", operation["_id"], operation["request_id"])
