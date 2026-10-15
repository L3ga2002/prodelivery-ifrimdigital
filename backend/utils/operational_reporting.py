"""Recoverable closure metadata and incident facts. Never settle or release custody."""
import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import uuid
from bson.int64 import Int64
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference
from pymongo.write_concern import WriteConcern
from models.operational_reporting import OperationalCommand, CloseDayCommand, IncidentCommand
from utils.order_operation_runtime import OperationRuntime, SessionLifecycle
from utils.order_revision import MAX_ORDER_VERSION, revision_filter, revision_update

logger = logging.getLogger(__name__)
DEADLINE_SECONDS = 10
CLEANUP_SECONDS = 0.25
MAJORITY = WriteConcern("majority", wtimeout=3000)
_BACKGROUND_WORK = set()
_runtime = OperationRuntime(lambda: DEADLINE_SECONDS, lambda: CLEANUP_SECONDS,
                            _BACKGROUND_WORK, logger, "operational_report")
SETTINGS = {"close_day": "restaurant-close-day-v1", "incident": "order-incident-v1"}
BUSINESS_ERRORS = {"TARGET_NOT_FOUND": 404, "TARGET_CHANGED": 409, "ORDER_DATA_INVALID": 409,
                   "ORDER_VERSION_CONFLICT": 409, "ORDER_VERSION_EXHAUSTED": 409}

class ReportingError(Exception):
    def __init__(self, status_code, code, message="Operatia necesita verificare. Pastreaza aceeasi intentie."):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message

@dataclass(frozen=True)
class ReportingOutcome:
    result: dict
    status_code: int

def _identifier(value, status=422):
    if (not isinstance(value, str) or not 1 <= len(value) <= 120 or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ReportingError(status, "INVALID_ID")
    return value

def _identity(actor):
    return _identifier(actor.get("user_id") or actor.get("id"), 401)

def _stamp():
    return datetime.now(timezone.utc).isoformat()

def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def operation_key(kind, actor_id, operation_id):
    return kind + ":" + _digest([actor_id, kind, operation_id])

def _binding(operation):
    return {k: operation[k] for k in ("_id", "operation_type", "contract_version", "actor_id", "actor_role",
             "actor_restaurant_id", "actor_driver_id", "target_id", "restaurant_id", "client_operation_id",
             "payload_digest", "command", "request_id", "created_at")}

class OperationalReportingService:
    def __init__(self, database, kind):
        if kind not in SETTINGS:
            raise ValueError("Unsupported operation")
        self.db, self.kind = database, kind
        self.command_type = CloseDayCommand if kind == "close_day" else IncidentCommand
        self.operations = database.get_collection("operational_operations", write_concern=MAJORITY,
            read_concern=ReadConcern("majority"), read_preference=ReadPreference.PRIMARY)

    async def _actor(self, actor, session=None):
        user = await self.db.users.find_one({"id": _identity(actor)},
            {"id": 1, "role": 1, "restaurant_id": 1, "driver_id": 1, "account_disabled": 1}, session=session)
        if not user:
            raise ReportingError(401, "AUTH_REQUIRED")
        if user.get("account_disabled"):
            raise ReportingError(403, "ACCOUNT_DISABLED")
        if user.get("role") != actor.get("role") or user.get("role") not in {"admin", "restaurant", "driver"}:
            raise ReportingError(403, "AUTH_CONTEXT_CHANGED")
        if user["role"] == "restaurant":
            _identifier(user.get("restaurant_id"), 403)
            if user["restaurant_id"] != actor.get("restaurant_id"):
                raise ReportingError(403, "AUTH_CONTEXT_CHANGED")
        if user["role"] == "driver":
            links = await self.db.drivers.find({"user_id": user["id"]}, session=session).limit(2).to_list(2)
            if len(links) != 1 or links[0].get("id") != actor.get("driver_id"):
                raise ReportingError(403, "AUTH_CONTEXT_CHANGED")
            _identifier(links[0].get("id"), 403)
            if "driver_id" in user and user["driver_id"] != links[0]["id"]:
                raise ReportingError(403, "AUTH_CONTEXT_CHANGED")
            user["driver_id"] = links[0]["id"]
        if self.kind == "close_day" and user["role"] == "driver":
            raise ReportingError(403, "NOT_AUTHORIZED")
        return user

    async def _target(self, target_id, session=None):
        collection = self.db.restaurants if self.kind == "close_day" else self.db.orders
        docs = await collection.find({"id": target_id}, session=session).limit(2).to_list(2)
        if len(docs) > 1:
            raise ReportingError(409, "ORDER_DATA_INVALID")
        return docs[0] if docs else None

    async def _scope(self, target, user, session=None, execute=True):
        if target is None:
            if user["role"] != "admin":
                raise ReportingError(403, "NOT_AUTHORIZED")
            return
        tenant = target["id"] if self.kind == "close_day" else target.get("restaurant_id")
        _identifier(tenant, 409)
        if user["role"] == "restaurant" and user["restaurant_id"] != tenant:
            raise ReportingError(403, "NOT_AUTHORIZED")
        if self.kind == "close_day" and (target.get("account_disabled") or target.get("is_active") is False):
            raise ReportingError(403, "ACCOUNT_DISABLED")
        if user["role"] == "driver" and execute:
            driver = await self.db.drivers.find_one({"id": user["driver_id"], "user_id": user["id"]}, session=session)
            active = await self.db.orders.find({"driver_id": user["driver_id"],
                "status": {"$nin": ["DELIVERED", "CANCELLED"]}}, session=session).limit(2).to_list(2)
            if (target.get("driver_id") != user["driver_id"] or target.get("status") not in {"ASSIGNED", "ACCEPTED", "PICKED_UP"}
                or not driver or driver.get("account_disabled") or driver.get("is_active") is False
                or driver.get("current_order_id") != target["id"] or driver.get("driver_status") != "delivery"
                or len(active) != 1 or active[0].get("id") != target["id"]):
                raise ReportingError(403, "NOT_AUTHORIZED")

    def _validated(self, operation, key):
        try:
            command = self.command_type.model_validate(operation["command"])
            if (operation["_id"] != key or operation["operation_type"] != self.kind
                or type(operation["contract_version"]) is not int or operation["contract_version"] != 1
                or key != operation_key(self.kind, operation["actor_id"], command.client_operation_id)
                or operation["client_operation_id"] != command.client_operation_id
                or operation["payload_digest"] != _digest([operation["target_id"], command.model_dump(mode="json")])
                or operation["admission_digest"] != _digest(_binding(operation))
                or str(uuid.UUID(operation["request_id"])) != operation["request_id"]
                or datetime.fromisoformat(operation["created_at"]).tzinfo is None):
                raise ValueError("Invalid admission")
            self._outcome(operation)
            return command
        except (KeyError, TypeError, ValueError, ReportingError):
            raise ReportingError(503, "OPERATION_INVALID") from None

    async def _existing(self, target_id, operation_id, actor, command=None):
        user = await self._actor(actor)
        key = operation_key(self.kind, user["id"], operation_id)
        operation = await self.operations.find_one({"_id": key})
        if operation is None:
            return None
        self._validated(operation, key)
        if operation["target_id"] != target_id:
            raise ReportingError(409 if command else 404, "INTENT_CONFLICT" if command else "OPERATION_NOT_FOUND")
        if (operation["actor_role"] != user["role"] or operation["actor_restaurant_id"] != user.get("restaurant_id")
            or operation["actor_driver_id"] != user.get("driver_id")):
            raise ReportingError(403, "AUTH_CONTEXT_CHANGED")
        target = await self._target(target_id)
        if target is not None:
            tenant = target["id"] if self.kind == "close_day" else target.get("restaurant_id")
            if tenant != operation["restaurant_id"]:
                raise ReportingError(403, "AUTH_CONTEXT_CHANGED")
        await self._scope(target, user, execute=operation["state"] == "pending")
        if command and operation["payload_digest"] != _digest([target_id, command.model_dump(mode="json")]):
            raise ReportingError(409, "INTENT_CONFLICT")
        return operation

    def _pending(self, operation_id):
        return ReportingOutcome({"client_operation_id": operation_id, "operation_type": self.kind,
                                 "state": "pending", "retry_after_seconds": 2}, 202)

    def _outcome(self, operation, replay=True):
        state = operation["state"]
        base = {"client_operation_id": operation["client_operation_id"], "operation_type": self.kind}
        if state == "pending":
            if any(k in operation for k in ("receipt", "resolved_at", "error_code", "error_status")):
                raise ReportingError(503, "OPERATION_INVALID")
            return self._pending(operation["client_operation_id"])
        if datetime.fromisoformat(operation["resolved_at"]).tzinfo is None:
            raise ReportingError(503, "OPERATION_INVALID")
        if state == "rejected":
            if BUSINESS_ERRORS.get(operation["error_code"]) != operation["error_status"] or "receipt" in operation:
                raise ReportingError(503, "OPERATION_INVALID")
            return ReportingOutcome({**base, "state": "rejected", "error_code": operation["error_code"]}, operation["error_status"])
        if state != "applied" or "error_code" in operation or "error_status" in operation:
            raise ReportingError(503, "OPERATION_INVALID")
        receipt = operation["receipt"]
        if self.kind == "close_day":
            if (set(receipt) != {"restaurant_id", "closed_today", "closed_at", "close_day_operation_id"}
                or receipt["restaurant_id"] != operation["target_id"] or receipt["closed_today"] is not True
                or receipt["close_day_operation_id"] != operation["client_operation_id"]
                or datetime.fromisoformat(receipt["closed_at"]).tzinfo is None):
                raise ReportingError(503, "OPERATION_INVALID")
        else:
            version = operation["command"]["expected_order_version"]
            receipt_version = receipt.get("order_version")
            valid_version = receipt_version is None if version is None else (
                type(receipt_version) in (int, Int64) and receipt_version == version + 1)
            if (set(receipt) != {"order_id", "order_version", "incident_id"}
                or receipt["order_id"] != operation["target_id"]
                or receipt["incident_id"] != str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":incident"))
                or not valid_version):
                raise ReportingError(503, "OPERATION_INVALID")
        return ReportingOutcome({**base, "state": "replayed" if replay else "applied", **receipt}, 200)

    async def _response(self, operation, replay=True):
        outcome = self._outcome(operation, replay)
        if self.kind == "close_day" and outcome.status_code == 200:
            current = await self._target(operation["target_id"])
            if current is None:
                raise ReportingError(503, "RECOVERY_UNAVAILABLE")
            # Fresh operational state is a read projection, never stored/replayed intent data.
            outcome.result.update(accepting_orders=current.get("accepting_orders", True), pause_until=current.get("pause_until"))
        return outcome

    async def _ready(self, admission):
        if admission:
            setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS[self.kind]})
            if setting is None or setting.get("enabled") is False:
                raise ReportingError(503, "CLOSE_DAY_NOT_ENABLED" if self.kind == "close_day" else "INCIDENT_NOT_ENABLED")
            if type(setting.get("enabled")) is not bool:
                raise ReportingError(503, "CAPABILITIES_INVALID")
        hello = await self.db.command("hello", maxTimeMS=2000)
        if not hello.get("setName") and hello.get("msg") != "isdbgrid":
            raise ReportingError(503, "TRANSACTIONS_REQUIRED")

    async def capabilities(self, actor, target_id=None):
        try:
            async with _runtime.request_deadline():
                user = await self._actor(actor)
                if target_id is not None:
                    await self._scope(await self._target(_identifier(target_id)), user)
                setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS[self.kind]})
                enabled = setting.get("enabled") if setting else False
                if type(enabled) is not bool:
                    raise ReportingError(503, "CAPABILITIES_INVALID")
                if enabled:
                    await self._ready(False)
                return {"close_day_enabled" if self.kind == "close_day" else "incident_reporting_enabled": enabled}
        except (TimeoutError, PyMongoError):
            raise ReportingError(503, "CAPABILITIES_UNAVAILABLE") from None

    async def submit(self, target_id, command, actor):
        target_id = _identifier(target_id)
        command = self.command_type.model_validate(command.model_dump(mode="json"))
        operation_id = command.client_operation_id
        key = operation_key(self.kind, _identity(actor), operation_id)
        admitted = False
        try:
            async with _runtime.request_deadline():
                operation = await self._existing(target_id, operation_id, actor, command)
                if operation and operation["state"] != "pending":
                    return await self._response(operation)
                await self._ready(operation is None)
                if operation is None:
                    user = await self._actor(actor)
                    target = await self._target(target_id)
                    await self._scope(target, user)
                    tenant = target_id if self.kind == "close_day" else target.get("restaurant_id") if target else None
                    operation = {"_id": key, "operation_type": self.kind, "contract_version": 1,
                        "actor_id": user["id"], "actor_role": user["role"], "actor_restaurant_id": user.get("restaurant_id"),
                        "actor_driver_id": user.get("driver_id"), "target_id": target_id, "restaurant_id": tenant,
                        "client_operation_id": operation_id, "command": command.model_dump(mode="json"),
                        "payload_digest": _digest([target_id, command.model_dump(mode="json")]),
                        "request_id": str(uuid.uuid4()), "created_at": _stamp(), "state": "pending"}
                    operation["admission_digest"] = _digest(_binding(operation))
                    admitted = True
                    try:
                        await self.operations.insert_one(operation)
                    except DuplicateKeyError:
                        operation = await self._existing(target_id, operation_id, actor, command)
                        if operation is None:
                            return self._pending(operation_id)
                        if operation["state"] != "pending":
                            return await self._response(operation)
                admitted = True
                return await self._execute(key, actor, operation_id)
        except (TimeoutError, PyMongoError):
            logger.warning("operational_report_uncertain operation_ref=%s admitted=%s", key, admitted)
            if admitted:
                return self._pending(operation_id)
            raise ReportingError(503, "REPORTING_UNAVAILABLE") from None

    async def lookup(self, target_id, operation_id, actor):
        _identifier(target_id); OperationalCommand(client_operation_id=operation_id)
        try:
            async with _runtime.request_deadline():
                operation = await self._existing(target_id, operation_id, actor)
                if operation is None:
                    raise ReportingError(404, "OPERATION_NOT_FOUND")
                return await self._response(operation)
        except (TimeoutError, PyMongoError):
            raise ReportingError(503, "RECOVERY_UNAVAILABLE") from None

    async def resume(self, target_id, operation_id, actor):
        _identifier(target_id); OperationalCommand(client_operation_id=operation_id)
        executing = False
        try:
            async with _runtime.request_deadline():
                operation = await self._existing(target_id, operation_id, actor)
                if operation is None:
                    raise ReportingError(404, "OPERATION_NOT_FOUND")
                if operation["state"] != "pending":
                    return await self._response(operation)
                await self._ready(False)
                executing = True
                return await self._execute(operation["_id"], actor, operation_id)
        except (TimeoutError, PyMongoError):
            if executing:
                return self._pending(operation_id)
            raise ReportingError(503, "RECOVERY_UNAVAILABLE") from None

    async def _execute(self, key, actor, operation_id):
        for attempt in range(3):
            session = await _runtime.start_session(self.db.client)
            lifecycle = SessionLifecycle(_runtime, session)
            try:
                session.start_transaction(read_concern=ReadConcern("snapshot"), write_concern=MAJORITY,
                    read_preference=ReadPreference.PRIMARY, max_commit_time_ms=2000)
                try:
                    operation = await lifecycle.wait(self.operations.find_one({"_id": key}, session=session))
                    if operation is None:
                        raise ReportingError(503, "OPERATION_INVALID")
                    command = self._validated(operation, key)
                    user = await lifecycle.wait(self._actor(actor, session))
                    if (operation["actor_role"] != user["role"] or operation["actor_restaurant_id"] != user.get("restaurant_id")
                        or operation["actor_driver_id"] != user.get("driver_id")):
                        raise ReportingError(403, "AUTH_CONTEXT_CHANGED")
                    if operation["state"] != "pending":
                        return await self._response(operation)
                    user_query = {"_id": user["_id"], "role": user["role"], "account_disabled": {"$ne": True}}
                    if user["role"] == "restaurant":
                        user_query["restaurant_id"] = user["restaurant_id"]
                    guard = await lifecycle.wait(self.db.users.update_one(user_query,
                        {"$inc": {"operational_admission_revision": 1}}, session=session))
                    if guard.matched_count != 1:
                        raise ReportingError(403, "AUTH_CONTEXT_CHANGED")
                    try:
                        target = await lifecycle.wait(self._target(operation["target_id"], session))
                        await lifecycle.wait(self._scope(target, user, session))
                        if target is None:
                            raise ReportingError(404, "TARGET_NOT_FOUND")
                        tenant = target["id"] if self.kind == "close_day" else target.get("restaurant_id")
                        if tenant != operation["restaurant_id"]:
                            raise ReportingError(409, "TARGET_CHANGED")
                        await lifecycle.wait(self._apply(operation, command, user, target, session))
                    except ReportingError as error:
                        if BUSINESS_ERRORS.get(error.code) != error.status_code:
                            raise
                        changed = await lifecycle.wait(self.operations.update_one({"_id": key, "state": "pending"},
                            {"$set": {"state": "rejected", "error_code": error.code, "error_status": error.status_code,
                                      "resolved_at": _stamp()}}, session=session))
                        if changed.matched_count != 1:
                            raise ReportingError(503, "OPERATION_INVALID")
                    if not await lifecycle.wait(_runtime.commit(session, 3)):
                        return self._pending(operation_id)
                    resolved = await self._existing(operation["target_id"], operation_id, actor)
                    if resolved is None:
                        return self._pending(operation_id)
                    return await self._response(resolved, replay=False)
                except PyMongoError as error:
                    if error.has_error_label("TransientTransactionError") and attempt < 2:
                        await asyncio.sleep(0.05 * (attempt + 1)); continue
                    raise
            finally:
                await lifecycle.cleanup()
        return self._pending(operation_id)

    async def _apply(self, operation, command, user, target, session):
        now = _stamp()
        audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":audit"))
        audit = {"id": audit_id, "action": "restaurant.closed_day" if self.kind == "close_day" else "order.incident_reported",
            "performed_by": user["id"], "performed_by_role": user["role"], "created_at": now,
            "operation_ref": operation["_id"], "request_id": operation["request_id"]}
        if self.kind == "close_day":
            receipt = {"restaurant_id": target["id"], "closed_today": True, "closed_at": now,
                       "close_day_operation_id": command.client_operation_id}
            result = await self.db.restaurants.update_one({"_id": target["_id"]},
                {"$set": {"closed_today": True, "closed_at": now, "closed_by": user["id"],
                          "close_day_operation_id": command.client_operation_id}, "$push": {"closure_audit_trail": audit}}, session=session)
            audit.update(entity_type="restaurant", entity_id=target["id"], changes={"closed_today": True})
        else:
            if target.get("status") not in {"NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"}:
                raise ReportingError(409, "ORDER_DATA_INVALID")
            version = target.get("order_version")
            if "order_version" in target and (type(version) not in (int, Int64) or not 0 <= version <= MAX_ORDER_VERSION):
                raise ReportingError(409, "ORDER_DATA_INVALID")
            if command.expected_order_version != version:
                raise ReportingError(409, "ORDER_VERSION_CONFLICT")
            if version == MAX_ORDER_VERSION:
                raise ReportingError(409, "ORDER_VERSION_EXHAUSTED")
            incident_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":incident"))
            summary = {"id": incident_id, "incident_type": command.incident_type, "reported_at": now,
                       "performed_by": user["id"], "performed_by_role": user["role"], "operation_ref": operation["_id"]}
            # Exact authoritative DB origin; legacy Order has no source-length enum.
            audit["source"] = target.get("source") if isinstance(target.get("source"), str) else None
            audit.update(from_order_version=version, to_order_version=int(version) + 1 if version is not None else None,
                         changes={"incident_id": incident_id, "incident_type": command.incident_type})
            query = {"_id": target["_id"], "restaurant_id": target["restaurant_id"], "status": target["status"],
                     "driver_id": target.get("driver_id"), **revision_filter(target)}
            update = revision_update(target, {"$push": {"incident_summary": summary, "audit_trail": audit}})
            result = await self.db.orders.update_one(query, update, session=session)
            if result.matched_count != 1:
                raise ReportingError(409, "ORDER_VERSION_CONFLICT")
            if user["role"] == "driver":
                # Claim serialization prevents an independent pause/reassign/terminal race.
                guard = await self.db.drivers.update_one({"id": user["driver_id"], "user_id": user["id"],
                    "current_order_id": target["id"], "driver_status": "delivery", "is_active": {"$ne": False},
                    "account_disabled": {"$ne": True}}, {"$inc": {"operational_admission_revision": 1}}, session=session)
                if guard.matched_count != 1:
                    raise ReportingError(403, "AUTH_CONTEXT_CHANGED")
            await self.db.order_incidents.insert_one({"_id": incident_id, **summary, "order_id": target["id"],
                "restaurant_id": target["restaurant_id"], "description": command.description,
                "driver_id_at_report": target.get("driver_id"), "status_at_report": target["status"],
                "from_order_version": version, "to_order_version": int(version) + 1 if version is not None else None,
                "request_id": operation["request_id"]}, session=session)
            receipt = {"order_id": target["id"], "order_version": int(version) + 1 if version is not None else None,
                       "incident_id": incident_id}
            audit.update(entity_type="order", entity_id=target["id"])
        if result.matched_count != 1:
            raise ReportingError(409, "ORDER_VERSION_CONFLICT")
        await self.db.audit_logs.insert_one({"_id": audit_id, **audit}, session=session)
        changed = await self.operations.update_one({"_id": operation["_id"], "state": "pending"},
            {"$set": {"state": "applied", "receipt": receipt, "resolved_at": now}}, session=session)
        if changed.matched_count != 1:
            raise ReportingError(503, "OPERATION_INVALID")

    async def incidents(self, target_id, actor, limit=50, cursor=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ReportingError(422, "INVALID_PAGE")
        position = None
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or not 1 <= len(cursor) <= 512:
                    raise ValueError("Invalid cursor")
                position = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                if (not isinstance(position, list) or len(position) != 3 or position[0] != target_id
                    or datetime.fromisoformat(position[1]).tzinfo is None or str(uuid.UUID(position[2])) != position[2]):
                    raise ValueError("Invalid cursor")
            except (ValueError, TypeError, UnicodeError):
                raise ReportingError(422, "INVALID_PAGE") from None
        try:
            async with _runtime.request_deadline():
                user = await self._actor(actor)
                target = await self._target(_identifier(target_id))
                await self._scope(target, user)
                if target is None:
                    raise ReportingError(404, "TARGET_NOT_FOUND")
                query = {"order_id": target_id, "restaurant_id": target["restaurant_id"]}
                if position is not None:
                    query["$or"] = [{"reported_at": {"$lt": position[1]}},
                                    {"reported_at": position[1], "id": {"$lt": position[2]}}]
                docs = await self.db.order_incidents.find(query, {"_id": 0}).sort(
                    [("reported_at", -1), ("id", -1)]).limit(limit + 1).to_list(limit + 1)
                next_cursor = None
                if len(docs) > limit:
                    last = docs[limit - 1]
                    next_cursor = base64.urlsafe_b64encode(json.dumps([target_id, last["reported_at"], last["id"]],
                        separators=(",", ":")).encode()).decode().rstrip("=")
                return {"incidents": docs[:limit], "next_cursor": next_cursor}
        except (TimeoutError, PyMongoError):
            raise ReportingError(503, "RECOVERY_UNAVAILABLE") from None
