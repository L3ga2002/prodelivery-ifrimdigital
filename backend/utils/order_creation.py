"""Durable create/replay using Mongo transactions; no startup provisioning."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import logging
import math
import uuid

from bson.int64 import Int64
from pydantic import ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference
from pymongo.write_concern import WriteConcern
from shapely.geometry import Point, Polygon

from models.order import Order
from models.order_mutation import (
    CloseFinancialCreation, CreateOrderCommand, FinancialCreationTerminal,
    MutationResult, build_mutation_intent,
)
from utils.order_operation_runtime import OperationRuntime, SessionLifecycle
from utils.order_finance import FinanceError, admission_snapshot, quote_at_admission, guard_generic_problem_link


logger = logging.getLogger(__name__)
SETTINGS_ID = "order-create-v1"
COUNTER_ID = "orders.global"
MAX_ATTEMPTS = 3
MAX_COMMIT_ATTEMPTS = 3
DEADLINE_SECONDS = 10
CLEANUP_SECONDS = 0.25
RETRY_AFTER_SECONDS = 2
MAJORITY = WriteConcern("majority", wtimeout=3000)
_BACKGROUND_WORK = set()
_runtime = OperationRuntime(lambda: DEADLINE_SECONDS, lambda: CLEANUP_SECONDS,
                            _BACKGROUND_WORK, logger, "order_create")


class CreationError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CreationOutcome:
    result: MutationResult
    status_code: int


@dataclass(frozen=True)
class VerifiedFinancialContext:
    """Server-only context supplied after signed-token authentication, never JSON."""
    actor_id: str
    actor_role: str
    restaurant_id: str | None


def _require_financial_context(actor, context):
    if (type(context) is not VerifiedFinancialContext or actor.get("role") != "admin"
            or context.actor_role != "admin" or context.actor_id != _identity(actor)
            or context.restaurant_id != actor.get("restaurant_id")):
        raise _error(403, "FINANCIAL_CONTEXT_REQUIRED", "Verifica sesiunea prin protocolul financiar.")


def operation_key(actor_id, client_operation_id):
    # JSON framing avoids collisions caused by separators inside identifiers.
    encoded = json.dumps([actor_id, "create", client_operation_id], separators=(",", ":"))
    return "create:" + sha256(encoded.encode("utf-8")).hexdigest()


def _error(status, code, message):
    return CreationError(status, code, message)


def _identity(actor):
    actor_id = actor.get("user_id") or actor.get("id")
    if not isinstance(actor_id, str) or not actor_id.strip() or actor_id != actor_id.strip():
        raise _error(401, "AUTH_REQUIRED", "Autentificarea este necesara.")
    return actor_id


def _authorize(user, restaurant_id):
    if not user:
        raise _error(401, "AUTH_REQUIRED", "Contul nu mai este disponibil.")
    if user.get("account_disabled"):
        raise _error(403, "ACCOUNT_DISABLED", "Contul este dezactivat.")
    role = user.get("role")
    if not isinstance(role, str) or role not in {"admin", "restaurant"}:
        raise _error(403, "NOT_AUTHORIZED", "Nu ai acces la aceasta operatie.")
    if role == "restaurant" and user.get("restaurant_id") != restaurant_id:
        raise _error(403, "NOT_AUTHORIZED", "Nu ai acces la aceasta operatie.")


@asynccontextmanager
async def _request_deadline():
    async with _runtime.request_deadline():
        yield


def _validated_operation(operation, key, actor, financial_context=None):
    try:
        actor_id = _identity(actor)
        if "creation_terminal_contract_version" in operation or "terminal_kind" in operation:
            _require_financial_context(actor, financial_context)
            terminal = FinancialCreationTerminal.model_validate(operation)
            when = datetime.fromisoformat(terminal.created_at)
            if (terminal.key != key or key != operation_key(actor_id, terminal.client_operation_id)
                    or terminal.actor_id != actor_id or terminal.created_at != terminal.resolved_at
                    or when.tzinfo is None or when.utcoffset() != timezone.utc.utcoffset(when)):
                raise ValueError("Invalid closed identity")
            OrderCreationService._outcome(operation)
            return None
        if isinstance(operation.get("command"), dict) and "quote_confirmation" in operation["command"]:
            _require_financial_context(actor, financial_context)
        command = CreateOrderCommand.model_validate(operation["command"])
        intent = build_mutation_intent(actor_id, "create", None, command)
        if (
            operation["_id"] != key or operation["actor_id"] != actor_id
            or operation["client_operation_id"] != command.client_operation_id
            or key != operation_key(actor_id, command.client_operation_id)
            or operation["restaurant_id"] != command.order.restaurant_id
            or operation["payload_digest"] != intent.payload_digest
            or operation["actor_role"] not in ("admin", "restaurant")
            or command.quote_confirmation is not None and operation["actor_role"] != "admin"
        ):
            raise ValueError("Inconsistent stored intent")
        if "request_id" in operation:
            request_id = operation["request_id"]
            if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
                raise ValueError("Invalid request correlation")
        OrderCreationService._outcome(operation)
        admission_snapshot(operation, command)
        if financial_context is not None and command.quote_confirmation is None:
            raise _error(409, "FINANCIAL_PROTOCOL_REQUIRED", "Operatia foloseste protocolul initial de recuperare.")
        return command
    except (KeyError, TypeError, ValueError):
        raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Nu crea un duplicat.") from None


def _observe_cleanup(task):
    _runtime.observe(task)


def _tracked(awaitable):
    return _runtime.tracked(awaitable)


async def _bounded_cleanup(action):
    return await _runtime.bounded_cleanup(action)


async def _worker_result(worker):
    return await _runtime.worker_result(worker)


async def _cleanup_session(session):
    await _runtime.cleanup_session(session)


async def _finish_after_worker(worker, session=None):
    await _runtime.finish_after_worker(worker, session)


async def _start_session(client):
    return await _runtime.start_session(client)


class _SessionLifecycle(SessionLifecycle):
    """A cancelled waiter cannot dispose a session still used by Motor."""

    def __init__(self, session):
        super().__init__(_runtime, session)


class OrderCreationService:
    def __init__(self, database):
        self.db = database
        self.operations = database.get_collection(
            "order_operations", write_concern=MAJORITY,
            read_concern=ReadConcern("majority"), read_preference=ReadPreference.PRIMARY,
        )

    async def _actor(self, actor, restaurant_id, session=None):
        user = await self.db.users.find_one(
            {"id": _identity(actor)},
            {"id": 1, "role": 1, "restaurant_id": 1, "account_disabled": 1},
            session=session,
        )
        _authorize(user, restaurant_id)
        # A stale authenticated context cannot silently inherit a new role/tenant.
        if user["role"] != actor.get("role") or (
            user["role"] == "restaurant" and user.get("restaurant_id") != actor.get("restaurant_id")
        ):
            raise _error(403, "AUTH_CONTEXT_CHANGED", "Accesul s-a schimbat. Autentifica-te din nou.")
        return user

    async def _existing_authorized(self, key, actor, command=None, financial_context=None):
        existing = await self.operations.find_one({"_id": key})
        if existing is None:
            return None
        stored_command = _validated_operation(existing, key, actor, financial_context)
        user = await self._actor(actor, existing["restaurant_id"])
        if user["role"] != existing.get("actor_role") or (
            user["role"] == "restaurant" and user.get("restaurant_id") != existing["restaurant_id"]
        ):
            raise _error(403, "AUTH_CONTEXT_CHANGED", "Nu ai acces la aceasta operatie.")
        if command is not None:
            if stored_command is None:
                if command.quote_confirmation is None:
                    self._intent_conflict()
                self._match_close(existing, CloseFinancialCreation(restaurant_id=command.order.restaurant_id,
                    quote_confirmation=command.quote_confirmation))
                return existing
            candidate = build_mutation_intent(_identity(actor), "create", None, command)
            if candidate.payload_digest != existing.get("payload_digest"):
                raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alte date.")
        return existing

    @staticmethod
    def _intent_conflict():
        raise _error(409, "INTENT_CONFLICT", "Identitatea operatiei a fost folosita pentru alte date.")

    @staticmethod
    def _match_close(operation, close):
        confirmation = operation.get("quote_confirmation") if "terminal_kind" in operation else operation["command"].get("quote_confirmation")
        if (operation["restaurant_id"] != close.restaurant_id
                or confirmation != close.quote_confirmation.model_dump(mode="json")):
            OrderCreationService._intent_conflict()

    async def _insert_terminal(self, key, client_operation_id, close, actor, context, code, command=None):
        # Admission and closure both insert this exact _id. Neither may update,
        # replace or delete the other's winner, including an admitted pending.
        now = datetime.now(timezone.utc).isoformat()
        terminal = FinancialCreationTerminal(
            creation_terminal_contract_version=1, terminal_kind="financial_create_not_admitted",
            _id=key, actor_id=_identity(actor), actor_role="admin",
            client_operation_id=client_operation_id, **close.model_dump(mode="python"),
            state="rejected", error_code=code, error_status=409, created_at=now, resolved_at=now,
        ).model_dump(mode="json", by_alias=True)
        try:
            await self.operations.insert_one(terminal)
        except DuplicateKeyError:
            pass
        winner = await self._existing_authorized(key, actor, command, context)
        if winner is None:
            return self._pending(client_operation_id)
        self._match_close(winner, close)
        return self._outcome(winner)

    async def close_financial(self, client_operation_id, close, actor, *, financial_context=None):
        from models.order_mutation import OperationCommand
        OperationCommand(client_operation_id=client_operation_id)
        close = CloseFinancialCreation.model_validate(close.model_dump(mode="python"))
        _require_financial_context(actor, financial_context)
        key = operation_key(_identity(actor), client_operation_id)
        attempted = False
        try:
            async with _request_deadline():
                await self._actor(actor, close.restaurant_id)
                existing = await self._existing_authorized(key, actor, financial_context=financial_context)
                if existing is not None:
                    self._match_close(existing, close)
                    return self._outcome(existing)
                # No quote/key/restaurant readiness/feature-marker dependency.
                attempted = True
                return await self._insert_terminal(key, client_operation_id, close, actor,
                    financial_context, "FINANCIAL_INTENT_CLOSED")
        except (TimeoutError, PyMongoError):
            if attempted:
                return self._pending(client_operation_id)
            raise _error(503, "RECOVERY_UNAVAILABLE", "Pastreaza aceeasi intentie.") from None

    @staticmethod
    def _outcome(operation, replay=True):
        try:
            return OrderCreationService._validated_outcome(operation, replay)
        except (KeyError, TypeError, ValueError):
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Nu crea un duplicat.") from None

    @staticmethod
    def _validated_outcome(operation, replay):
        state = operation.get("state")
        if state == "applied":
            return CreationOutcome(MutationResult(
                client_operation_id=operation["client_operation_id"],
                state="replayed" if replay else "applied",
                order_id=operation["order_id"], order_version=0,
            ), 200 if replay else 201)
        if state == "rejected":
            if type(operation.get("error_status")) is not int or operation["error_status"] not in {404, 409}:
                raise ValueError("Invalid rejection status")
            return CreationOutcome(MutationResult(
                client_operation_id=operation["client_operation_id"], state="rejected",
                error_code=operation["error_code"],
            ), operation["error_status"])
        if state != "pending":
            raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare. Nu crea un duplicat.")
        return OrderCreationService._pending(operation["client_operation_id"])

    @staticmethod
    def _pending(client_operation_id):
        return CreationOutcome(MutationResult(
            client_operation_id=client_operation_id, state="pending",
            retry_after_seconds=RETRY_AFTER_SECONDS,
        ), 202)

    async def _ready(self, new_admission):
        if new_admission:
            setting = await self.db.order_operation_settings.find_one({"_id": SETTINGS_ID})
            if not setting or setting.get("enabled") is not True:
                raise _error(503, "CREATION_NOT_ENABLED", "Crearea recuperabila nu este activata in acest mediu.")
        hello = await self.db.command("hello", maxTimeMS=2000)
        if not hello.get("setName") and hello.get("msg") != "isdbgrid":
            raise _error(503, "TRANSACTIONS_REQUIRED", "Mediul nu suporta inca operatii recuperabile.")

    async def capabilities(self, actor):
        try:
            async with _request_deadline():
                user = await self._actor(actor, actor.get("restaurant_id"))
                if user["role"] != "admin":
                    raise _error(403, "NOT_AUTHORIZED", "Nu ai acces la aceasta operatie.")
                setting = await self.db.order_operation_settings.find_one(
                    {"_id": SETTINGS_ID}, {"enabled": 1, "_id": 0},
                )
                if setting is None:
                    return {"create_recovery_enabled": False}
                if not isinstance(setting, dict) or type(setting.get("enabled")) is not bool:
                    raise _error(503, "CAPABILITIES_INVALID", "Configuratia necesita verificare.")
                return {"create_recovery_enabled": setting["enabled"]}
        except (TimeoutError, PyMongoError):
            logger.warning("order_create_capabilities_unavailable")
            raise _error(503, "CAPABILITIES_UNAVAILABLE", "Configuratia nu este disponibila.") from None

    async def lookup(self, client_operation_id, actor, *, financial_context=None):
        # Reuse the strict key validator without accepting an order payload.
        from models.order_mutation import OperationCommand
        OperationCommand(client_operation_id=client_operation_id)
        try:
            async with _request_deadline():
                existing = await self._existing_authorized(operation_key(_identity(actor), client_operation_id), actor,
                    financial_context=financial_context)
                if existing is None:
                    raise _error(404, "OPERATION_NOT_FOUND", "Operatia nu a fost gasita; reia aceeasi intentie.")
                return self._outcome(existing)
        except (TimeoutError, PyMongoError) as exc:
            logger.warning("order_create_lookup_unavailable")
            raise _error(503, "RECOVERY_UNAVAILABLE", "Verificarea nu este disponibila. Pastreaza aceeasi intentie.") from exc

    async def resume(self, client_operation_id, actor, *, financial_context=None):
        from models.order_mutation import OperationCommand
        OperationCommand(client_operation_id=client_operation_id)
        key = operation_key(_identity(actor), client_operation_id)
        execution_attempted = False
        try:
            async with _request_deadline():
                await self._actor(actor, actor.get("restaurant_id"))
                existing = await self._existing_authorized(key, actor, financial_context=financial_context)
                if existing is None:
                    raise _error(404, "OPERATION_NOT_FOUND", "Operatia nu a fost gasita; pastreaza aceeasi intentie.")
                if existing["state"] != "pending":
                    return self._outcome(existing)
                # An admitted intent survives disabling new admission. Execution
                # rereads its validated command and actor inside the same transaction.
                await self._ready(new_admission=False)
                execution_attempted = True
                if financial_context is None:
                    return await self._execute(key, actor, client_operation_id)
                return await self._execute(key, actor, client_operation_id, financial_context=financial_context)
        except (TimeoutError, PyMongoError):
            logger.warning("order_create_resume_unavailable operation_ref=%s executing=%s", key, execution_attempted)
            if execution_attempted:
                return self._pending(client_operation_id)
            raise _error(503, "RECOVERY_UNAVAILABLE", "Verificarea nu este disponibila. Pastreaza aceeasi intentie.") from None

    async def create(self, command, actor, *, financial_context=None, signing_key=None):
        command = CreateOrderCommand.model_validate(command.model_dump(mode="python", exclude_unset=True))
        key = operation_key(_identity(actor), command.client_operation_id)
        if command.quote_confirmation is not None:
            _require_financial_context(actor, financial_context)
        admission_attempted = False
        try:
            async with _request_deadline():
                existing = await self._existing_authorized(key, actor, command, financial_context)
                if existing and existing["state"] != "pending":
                    return self._outcome(existing)
                user = await self._actor(actor, command.order.restaurant_id)
                await self._ready(new_admission=existing is None)
                if existing is None:
                    await guard_generic_problem_link(self.db, command.order)
                    intent = build_mutation_intent(_identity(actor), "create", None, command)
                    operation = {
                        "_id": key, "actor_id": _identity(actor), "actor_role": user["role"],
                        "restaurant_id": command.order.restaurant_id,
                        "client_operation_id": command.client_operation_id,
                        "payload_digest": intent.payload_digest,
                        "request_id": str(uuid.uuid4()),
                        "command": command.model_dump(mode="json"),
                        "state": "pending", "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    if command.quote_confirmation is not None:
                        # Lazy import avoids the preview service's legacy helper
                        # dependency becoming an import cycle.
                        from utils.order_finance_preview import OrderFinancePreviewService
                        snapshot, fingerprint = await OrderFinancePreviewService(
                            self.db, signing_key=signing_key() if callable(signing_key) else signing_key
                        ).prepare_create_confirmation(command, actor, key)
                        if not hmac.compare_digest(fingerprint, command.quote_confirmation.quote_fingerprint):
                            admission_attempted = True
                            return await self._insert_terminal(key, command.client_operation_id,
                                CloseFinancialCreation(restaurant_id=command.order.restaurant_id,
                                    quote_confirmation=command.quote_confirmation), actor, financial_context,
                                "FINANCIAL_QUOTE_CHANGED", command)
                        operation["financial_snapshot"] = snapshot
                    elif command.financial is not None:
                        if await self.db.delivery_zones.count_documents({"is_active": True,
                                "restaurant_id": command.order.restaurant_id}, limit=301) > 300:
                            raise FinanceError("FINANCIAL_ZONE_UNVERIFIED")
                        zone = await self._zone(command.order, None)
                        operation["financial_snapshot"] = await quote_at_admission(
                            self.db, command, user, key, zone)
                    admission_attempted = True
                    try:
                        await self.operations.insert_one(operation)
                    except DuplicateKeyError:
                        existing = await self._existing_authorized(key, actor, command, financial_context)
                        if existing is None:
                            return self._pending(command.client_operation_id)
                        if existing["state"] != "pending":
                            return self._outcome(existing)
                else:
                    admission_attempted = True
                if financial_context is None:
                    return await self._execute(key, actor, command.client_operation_id)
                return await self._execute(key, actor, command.client_operation_id, financial_context=financial_context)
        except FinanceError as exc:
            raise _error(exc.status_code, exc.code, exc.message) from None
        except (TimeoutError, PyMongoError) as exc:
            logger.warning("order_create_uncertain operation_ref=%s admitted=%s", key, admission_attempted)
            if admission_attempted:
                return self._pending(command.client_operation_id)
            raise _error(503, "CREATION_UNAVAILABLE", "Serverul nu raspunde. Pastreaza aceeasi intentie.") from exc

    async def _execute(self, key, actor, client_operation_id, *, financial_context=None):
        for attempt in range(MAX_ATTEMPTS):
            session = await _start_session(self.db.client)
            lifecycle = _SessionLifecycle(session)
            try:
                session.start_transaction(
                    read_concern=ReadConcern("snapshot"), write_concern=MAJORITY,
                    read_preference=ReadPreference.PRIMARY, max_commit_time_ms=2000,
                )
                try:
                    operation = await lifecycle.wait(self.operations.find_one({"_id": key}, session=session))
                    if not operation:
                        raise _error(503, "OPERATION_INVALID", "Operatia necesita verificare.")
                    command = _validated_operation(operation, key, actor, financial_context)
                    user = await lifecycle.wait(self._actor(actor, operation["restaurant_id"], session))
                    if user["role"] != operation["actor_role"]:
                        raise _error(403, "AUTH_CONTEXT_CHANGED", "Nu ai acces la aceasta operatie.")
                    if operation["state"] != "pending":
                        return self._outcome(operation)
                    # Writes serialize against concurrent role/tenant changes and pause/close.
                    actor_filter = {"_id": user["_id"], "role": user["role"], "account_disabled": {"$ne": True}}
                    if user["role"] == "restaurant":
                        actor_filter["restaurant_id"] = operation["restaurant_id"]
                    guard = await lifecycle.wait(self.db.users.update_one(
                        actor_filter, {"$inc": {"order_admission_revision": 1}}, session=session,
                    ))
                    if guard.matched_count != 1:
                        raise _error(403, "AUTH_CONTEXT_CHANGED", "Accesul s-a schimbat.")
                    restaurant = await lifecycle.wait(self.db.restaurants.find_one(
                        {"id": operation["restaurant_id"]}, session=session))
                    rejection = self._restaurant_rejection(restaurant)
                    if rejection is None:
                        try:
                            await lifecycle.wait(guard_generic_problem_link(self.db, command.order, session))
                        except FinanceError as exc:
                            rejection = _error(exc.status_code, exc.code, exc.message)
                    if restaurant:
                        await lifecycle.wait(self.db.restaurants.update_one(
                            {"_id": restaurant["_id"]}, {"$inc": {"order_admission_revision": 1}}, session=session,
                        ))
                    if rejection:
                        await lifecycle.wait(self.operations.update_one({"_id": key, "state": "pending"}, {"$set": {
                            "state": "rejected", "error_code": rejection.code,
                            "error_status": rejection.status_code,
                            "resolved_at": datetime.now(timezone.utc).isoformat(),
                        }}, session=session))
                    else:
                        await lifecycle.wait(self._apply(operation, command, user, restaurant, session))
                    if not await lifecycle.wait(self._commit(session)):
                        return self._pending(client_operation_id)
                    resolved = await self._existing_authorized(key, actor, financial_context=financial_context)
                    return self._outcome(resolved, replay=False)
                except BaseException as exc:
                    # Unknown commit must never rerun the transaction as though it failed.
                    if isinstance(exc, PyMongoError) and exc.has_error_label("TransientTransactionError"):
                        if attempt + 1 < MAX_ATTEMPTS:
                            await asyncio.sleep(0.05 * (attempt + 1))
                            continue
                    raise
            finally:
                await lifecycle.cleanup()
        return self._pending(client_operation_id)

    @staticmethod
    async def _commit(session):
        return await _runtime.commit(session, MAX_COMMIT_ATTEMPTS)

    @staticmethod
    def _restaurant_rejection(restaurant):
        if not restaurant:
            return _error(404, "RESTAURANT_NOT_FOUND", "Restaurantul nu exista.")
        if restaurant.get("account_disabled") or restaurant.get("is_active") is False:
            return _error(409, "RESTAURANT_UNAVAILABLE", "Restaurantul nu este disponibil.")
        # Accounting close does not imply operational pause; retain old rejection receipts.
        if restaurant.get("accepting_orders") is False:
            return _error(409, "RESTAURANT_PAUSED", "Restaurantul nu accepta comenzi noi.")
        if not isinstance(restaurant.get("name"), str) or not restaurant["name"].strip():
            return _error(409, "RESTAURANT_INVALID", "Restaurantul necesita verificare.")
        return None

    async def _zone(self, order, session):
        if order.customer_latitude is None:
            return None
        zones = await self.db.delivery_zones.find(
            {"is_active": True, "restaurant_id": order.restaurant_id}, session=session,
        ).to_list(300)
        point = Point(order.customer_longitude, order.customer_latitude)
        matches = []
        for zone in zones:
            coords = zone.get("polygon", [])
            if not isinstance(coords, list):
                raise _error(503, "ZONE_CONFIGURATION_INVALID", "Zona de livrare necesita verificare.")
            if len(coords) < 3:
                continue
            try:
                for field, maximum in (("id", 120), ("name", 160), ("sector", 80)):
                    value = zone.get(field)
                    if value is not None and (not isinstance(value, str) or len(value) > maximum):
                        raise ValueError("Invalid zone metadata")
                level = zone.get("zone_level")
                if level is not None and (type(level) not in {int, Int64} or not 0 <= level <= 50):
                    raise ValueError("Invalid zone level")
                polygon = Polygon([(coord["lng"], coord["lat"]) for coord in coords])
                if not polygon.is_valid:
                    raise ValueError("Invalid zone polygon")
            except (KeyError, TypeError, ValueError) as exc:
                raise _error(503, "ZONE_CONFIGURATION_INVALID", "Zona de livrare necesita verificare.") from exc
            if polygon.contains(point):
                matches.append((polygon.area, zone))
        return min(matches, key=lambda pair: pair[0])[1] if matches else None

    async def _apply(self, operation, command, user, restaurant, session):
        counter = await self.db.counters.find_one({"_id": COUNTER_ID}, session=session)
        if not counter or type(counter.get("seq")) not in {int, Int64} or not 0 <= counter["seq"] < 9223372036854775807:
            raise _error(503, "COUNTER_NOT_READY", "Numerotarea comenzilor necesita pregatirea mediului.")
        counter = await self.db.counters.find_one_and_update(
            {"_id": COUNTER_ID}, {"$inc": {"seq": 1}}, session=session,
            return_document=ReturnDocument.AFTER,
        )
        data = command.order
        financial = admission_snapshot(operation, command)
        zone = await self._zone(data, session) if financial is None else None
        subtotal = data.subtotal_amount if data.subtotal_amount is not None else data.total_amount
        fee = zone.get("fee", 0) if zone else (data.delivery_fee or 0)
        if type(fee) not in {int, Int64, float} or not math.isfinite(fee) or not 0 <= fee <= 1000000:
            raise _error(503, "ZONE_CONFIGURATION_INVALID", "Tariful zonei necesita verificare.")
        now = datetime.now(timezone.utc)
        order_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"]))
        audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":created"))
        values = data.model_dump(mode="python")
        for field in ("delivery_zone_id", "delivery_zone_name", "delivery_sector", "delivery_zone_level"):
            values[field] = None
        if zone:
            values.update(delivery_zone_id=zone.get("id"), delivery_zone_name=zone.get("name"),
                          delivery_sector=zone.get("sector"), delivery_zone_level=zone.get("zone_level"))
        values.update(
            id=order_id, order_number=f"{data.source.upper()}.{counter['seq']:04d}",
            restaurant_name=restaurant["name"], preparation_status="NEW",
            subtotal_amount=subtotal, delivery_fee=fee, total_amount=round(subtotal + fee, 2),
            zone=zone.get("name") if zone else None, created_at=now, updated_at=now,
        )
        if financial is not None:
            values.update(
                order_version=0, creation_operation_ref=operation["_id"], financial_contract_version=1,
                financial=financial.model_dump(mode="json"), delivery_zone_id=financial.zone_id,
                delivery_zone_name=financial.zone_name, delivery_sector=financial.zone_sector,
                delivery_zone_level=financial.zone_level, zone=financial.zone_name,
                subtotal_amount=financial.products_bani / 100,
                delivery_fee=financial.restaurant_transport_bani / 100,
                total_amount=financial.client_collection_bani / 100,
            )
        try:
            doc = Order(**values).model_dump(mode="json")
        except ValidationError:
            raise _error(503, "ZONE_CONFIGURATION_INVALID", "Datele serverului necesita verificare.") from None
        audit = {
            "id": audit_id, "action": "order.created", "changes": {"status": "NEW"},
            "performed_by": user["id"], "performed_by_role": user["role"],
            "created_at": now.isoformat(), "operation_ref": operation["_id"],
            "request_id": operation.get("request_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"] + ":request")),
            "from_order_version": None, "to_order_version": 0,
        }
        if financial is not None:
            audit["changes"]["financial_snapshot_digest"] = financial.snapshot_digest
        doc.update(_id=order_id, creation_operation_ref=operation["_id"], audit_trail=[audit])
        await self.db.orders.insert_one(doc, session=session)
        await self.db.audit_logs.insert_one({
            "_id": audit_id, **audit, "entity_type": "order", "entity_id": order_id,
        }, session=session)
        await self.operations.update_one({"_id": operation["_id"], "state": "pending"}, {"$set": {
            "state": "applied", "order_id": order_id, "resolved_at": now.isoformat(),
        }}, session=session)
        logger.info("order_create_prepared operation_ref=%s order_id=%s", operation["_id"], order_id)
