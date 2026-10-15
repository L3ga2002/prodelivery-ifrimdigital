import re
import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, Header, Request, Response, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta, timezone
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from shapely.geometry import Point, Polygon
from database import db
from auth import get_current_user
from utils.order_revision import ensure_legacy_order, revision_filter, revision_update
from utils.order_finance import FinanceError, guard_generic_problem_link
from utils.order_assignment import MULTI_FIELDS
from utils.order_reads import OrderReadService, read_error, READ_TIMEOUT_SECONDS
from utils.order_financial_reads import private_read, signed_read_actor
from utils.order_finance import FinanceError, order_financial_snapshot
from utils.financial_activity import public_activity_read, read_activity_failures, unavailable_activity_read
from utils.custody_activity import public_custody_read, read_custody_failures, unavailable_custody_read
from models.order import (
    ORDER_STATUS_VALUES,
    Order,
    OrderCreate,
    AssignOrder,
    UpdateOrderStatus,
    PreparationTime,
    ProblemOrderCreate,
)

router = APIRouter(prefix="/orders", tags=["orders"])
logger = logging.getLogger(__name__)

VALID_ORDER_STATUSES = list(ORDER_STATUS_VALUES)
MIN_PREP_WHEN_NO_DRIVERS = 20
RESTAURANT_MUTATION_STATUSES = {"CANCELLED"}
DRIVER_MUTATION_STATUSES = {"ACCEPTED", "PICKED_UP", "DELIVERED"}
GENERIC_STATUS_ENDPOINT_STATUSES = {"ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"}
ASSIGNABLE_ORDER_STATUSES = {"NEW", "PREPARING", "READY", "ASSIGNED"}
ORDER_STATUS_TRANSITIONS = {
    "NEW": {"PREPARING", "ASSIGNED", "CANCELLED"},
    "PREPARING": {"READY", "ASSIGNED", "CANCELLED"},
    "READY": {"ASSIGNED", "CANCELLED"},
    "ASSIGNED": {"ACCEPTED", "CANCELLED"},
    "ACCEPTED": {"PICKED_UP", "CANCELLED"},
    "PICKED_UP": {"DELIVERED"},
    "DELIVERED": set(),
    "CANCELLED": set(),
}
ORDER_COUNTER_ID = "orders.global"
ORDER_NUMBER_RE = re.compile(r"^[^.]+\.(\d+)")
LEGACY_PREPARATION_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?$"
)


def _normalize_order_source(source: str | None) -> str:
    normalized = (source or "S").strip().upper()
    return normalized or "S"


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _order_audit_entry(action: str, current_user: dict, changes: dict | None = None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "action": action,
        "changes": changes or {},
        "performed_by": current_user.get("user_id") or current_user.get("id"),
        "performed_by_role": current_user.get("role"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _update_with_order_audit(set_data: dict, action: str, current_user: dict, changes: dict | None = None, *, order: dict) -> dict:
    entry = _order_audit_entry(action, current_user, changes)
    if action in {"order.preparing_started", "order.ready"}:
        # Read original DB origin only; never accept an audit source from the request.
        entry["source"] = order.get("source") if isinstance(order.get("source"), str) else None
        entry["request_id"] = str(uuid.uuid4())
        # Server CAS event identity, not a new client recovery intent.
        entry["operation_ref"] = "order-audit:" + entry["id"]
        entry["from_order_version"] = order.get("order_version")
        entry["to_order_version"] = int(order["order_version"]) + 1 if "order_version" in order else None
    if "order_version" in order:
        entry["from_order_version"] = int(order["order_version"])
        entry["to_order_version"] = int(order["order_version"]) + 1
    return revision_update(order, {
        "$set": set_data,
        "$push": {"audit_trail": entry},
    })


def _order_filter_for_loaded_order(order: dict) -> dict:
    current_driver = order.get("driver_id")
    query = {"id": order["id"], "status": order.get("status")}
    query.update(revision_filter(order))
    if current_driver:
        query["driver_id"] = current_driver
    else:
        query["$or"] = [{"driver_id": None}, {"driver_id": {"$exists": False}}]
    return query


def _preparation_status_for_order(order: dict) -> str:
    status = order.get("status")
    if status not in VALID_ORDER_STATUSES:
        raise HTTPException(status_code=409, detail="Comanda are un status invalid")
    preparation_status = order.get("preparation_status")
    if preparation_status is not None:
        if not isinstance(preparation_status, str) or preparation_status not in {"NEW", "PREPARING", "READY"}:
            raise HTTPException(status_code=409, detail="Comanda are date de pregătire invalide")
    if status in {"NEW", "PREPARING", "READY"}:
        return status
    if preparation_status is not None:
        return preparation_status
    # Legacy dispatch status replaced preparation status; retained timestamps recover it.
    for field in ("preparation_started_at", "preparation_ready_at"):
        value = order.get(field)
        if value is None:
            continue
        valid_format = isinstance(value, datetime) or (
            isinstance(value, str) and LEGACY_PREPARATION_TIMESTAMP_RE.fullmatch(value)
        )
        if not valid_format or _parse_datetime(value) is None:
            raise HTTPException(status_code=409, detail="Comanda are date de pregătire invalide; verifică manual")
    if order.get("preparation_ready_at") is not None:
        return "READY"
    if order.get("preparation_started_at") is not None:
        return "PREPARING"
    return "NEW"


def _preparation_snapshot_filter(order: dict) -> dict:
    query = _order_filter_for_loaded_order(order)
    query["restaurant_id"] = order.get("restaurant_id")
    for field in ("preparation_status", "preparation_started_at", "preparation_ready_at", "preparation_due_at"):
        query[field] = order.get(field)
    return query


def _ensure_preparation_mutable(order: dict) -> None:
    status = order.get("status")
    if not isinstance(status, str) or status not in {"NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED"}:
        raise HTTPException(status_code=409, detail="Pregătirea nu mai poate fi modificată pentru această comandă")


async def _has_usable_assigned_driver(order: dict) -> bool:
    if order.get("status") not in {"ASSIGNED", "ACCEPTED"} or not order.get("driver_id"):
        return False
    return bool(await db.drivers.find_one({
        "id": order["driver_id"],
        "current_order_id": order["id"],
        "driver_status": "delivery",
        "is_active": True,
        "account_disabled": {"$ne": True},
    }, {"_id": 0, "id": 1}))


async def _record_order_audit_log(order_id: str, action: str, current_user: dict, changes: dict | None = None, *, event: dict | None = None) -> None:
    try:
        if event is not None:
            # Immutable projection of the already committed embedded event.
            projected = {"_id": event["id"], **event, "entity_type": "order", "entity_id": order_id}
            async with asyncio.timeout(2):
                existing = await db.audit_logs.find_one({"_id": event["id"]})
                if existing is not None:
                    if existing != projected:
                        raise RuntimeError("audit_projection_conflict")
                    return
                try:
                    await db.audit_logs.insert_one(projected)
                except DuplicateKeyError:
                    # A concurrent duplicate can only replay the identical immutable event.
                    existing = await db.audit_logs.find_one({"_id": event["id"]})
                    if existing != projected:
                        raise RuntimeError("audit_projection_conflict")
            return
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "entity_type": "order",
            "entity_id": order_id,
            "action": action,
            "changes": changes or {},
            "performed_by": current_user.get("user_id") or current_user.get("id"),
            "performed_by_role": current_user.get("role"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as error:
        logger.error("order_audit_write_failed order_id=%s action=%s error_type=%s", order_id, action, type(error).__name__)


async def _project_preparation_event(order: dict, action: str, actor: dict) -> None:
    entries = order.get("audit_trail", [])
    if not isinstance(entries, list):
        return
    event = next((entry for entry in reversed(entries) if isinstance(entry, dict) and entry.get("action") == action), None)
    if event is None:
        return
    event_id, request_id = event.get("id"), event.get("request_id")
    # Only the new immutable lineage can repair its deterministic projection.
    # Historical events used unrelated global IDs and require an explicit migration.
    try:
        if not isinstance(event_id, str) or str(uuid.UUID(event_id)) != event_id:
            return
        if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
            return
    except (ValueError, AttributeError):
        return
    if event.get("operation_ref") != "order-audit:" + event_id:
        return
    await _record_order_audit_log(order["id"], action, actor, event=event)


def _log_order_action(action: str, order_id: str, current_user: dict, changes: dict | None = None) -> None:
    # Diagnostic logs carry state metadata, never arbitrary customer/free-text values.
    safe_changes = {key: value for key, value in (changes or {}).items()
                    if key in {"status", "from_status", "to_status", "from_preparation_status", "to_preparation_status"}
                    and isinstance(value, str) and value in VALID_ORDER_STATUSES}
    logger.info(
        "order_action=%s order_id=%s actor_role=%s actor_id=%s changes=%s",
        action,
        order_id,
        current_user.get("role"),
        current_user.get("user_id") or current_user.get("id"),
        safe_changes,
    )


def _expected_actor_context(current_user: dict, expected_actor_id: str | None) -> None:
    if expected_actor_id is None:
        return
    if (not isinstance(expected_actor_id, str) or not 1 <= len(expected_actor_id) <= 120
        or expected_actor_id != expected_actor_id.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in expected_actor_id)):
        raise HTTPException(status_code=422, detail={"code": "INVALID_ACTOR_ID", "message": "Identitate invalida."})
    if expected_actor_id != (current_user.get("user_id") or current_user.get("id")):
        raise HTTPException(status_code=403, detail={"code": "AUTH_CONTEXT_CHANGED", "message": "Sesiunea s-a schimbat. Pastreaza identitatea operatiei."})


def _ensure_order_transition_allowed(order: dict, next_status: str) -> bool:
    current_status = order.get("status")
    if current_status not in VALID_ORDER_STATUSES:
        raise HTTPException(status_code=409, detail="Comanda are un status invalid și trebuie verificată manual")
    if next_status == current_status:
        return False
    if next_status not in ORDER_STATUS_TRANSITIONS.get(current_status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Tranziție invalidă pentru comandă: {current_status} -> {next_status}",
        )
    return True


def _ensure_restaurant_accepts_new_orders(restaurant: dict) -> None:
    pause_until = _parse_datetime(restaurant.get("pause_until"))
    # Accounting close alone does not suspend operational order admission.
    if restaurant.get("accepting_orders") is False:
        if pause_until:
            raise HTTPException(status_code=409, detail="Restaurantul este în pauză și nu acceptă comenzi noi")
        raise HTTPException(status_code=409, detail="Restaurantul nu acceptă comenzi noi")


async def _max_existing_order_sequence() -> int:
    max_sequence = await db.orders.count_documents({})
    async for order in db.orders.find({}, {"_id": 0, "order_number": 1}):
        match = ORDER_NUMBER_RE.match(str(order.get("order_number", "")))
        if match:
            max_sequence = max(max_sequence, int(match.group(1)))
    return max_sequence


async def _ensure_order_counter_initialized() -> None:
    existing = await db.counters.find_one({"_id": ORDER_COUNTER_ID}, {"_id": 1})
    if existing:
        return

    initial_sequence = await _max_existing_order_sequence()
    try:
        await db.counters.insert_one({
            "_id": ORDER_COUNTER_ID,
            "seq": initial_sequence,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except DuplicateKeyError:
        return


async def _next_order_number(source: str | None, suffix: str = "") -> str:
    await _ensure_order_counter_initialized()
    counter = await db.counters.find_one_and_update(
        {"_id": ORDER_COUNTER_ID},
        {"$inc": {"seq": 1}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0, "seq": 1},
    )
    return f"{_normalize_order_source(source)}.{int(counter['seq']):04d}{suffix}"


def _orders_query_for_user(current_user: dict) -> dict:
    role = current_user.get("role")
    if role == "admin":
        return {}
    if role == "restaurant" and current_user.get("restaurant_id"):
        return {"restaurant_id": current_user["restaurant_id"]}
    if role == "driver" and current_user.get("driver_id"):
        return {"driver_id": current_user["driver_id"]}
    raise HTTPException(status_code=403, detail="Not authorized")


def _format_order_dates(order: dict) -> dict:
    if isinstance(order.get("created_at"), str):
        order["created_at"] = _parse_datetime(order["created_at"])
    if isinstance(order.get("updated_at"), str):
        order["updated_at"] = _parse_datetime(order["updated_at"])
    for field in ("created_at", "updated_at"):
        if order.get(field) is not None and not isinstance(order[field], datetime):
            order[field] = None
    return order


def _ensure_order_read_allowed(order: dict, current_user: dict) -> None:
    role = current_user.get("role")
    if role == "admin":
        return
    if role == "restaurant" and current_user.get("restaurant_id") == order.get("restaurant_id"):
        return
    if role == "driver" and current_user.get("driver_id") == order.get("driver_id"):
        return
    raise HTTPException(status_code=403, detail="Not authorized")


def _ensure_restaurant_order_mutation_allowed(order: dict, current_user: dict) -> None:
    role = current_user.get("role")
    if role == "admin":
        return
    if role == "restaurant" and current_user.get("restaurant_id") == order.get("restaurant_id"):
        return
    raise HTTPException(status_code=403, detail="Not authorized")


def _ensure_status_mutation_allowed(order: dict, status: str, current_user: dict) -> None:
    role = current_user.get("role")
    if role == "admin":
        return
    if (
        role == "restaurant"
        and current_user.get("restaurant_id") == order.get("restaurant_id")
        and status in RESTAURANT_MUTATION_STATUSES
    ):
        return
    if (
        role == "driver"
        and current_user.get("driver_id") == order.get("driver_id")
        and status in DRIVER_MUTATION_STATUSES
    ):
        return
    raise HTTPException(status_code=403, detail="Not authorized")


def build_shapely_polygon(coords):
    if len(coords) < 3:
        return None
    ring = [(c["lng"], c["lat"]) for c in coords]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return Polygon(ring)


async def detect_delivery_zone(lat: float | None, lng: float | None, restaurant_id: str | None):
    if lat is None or lng is None:
        return None

    point = Point(lng, lat)
    zones = await db.delivery_zones.find(
        {"is_active": True, "restaurant_id": restaurant_id},
        {"_id": 0},
    ).to_list(300)
    matches = []
    for zone in zones:
        poly = build_shapely_polygon(zone.get("polygon", []))
        if poly and poly.contains(point):
            matches.append((poly.area, zone))
    if matches:
        return sorted(matches, key=lambda item: item[0])[0][1]
    return None


def build_status_update_payload(data: UpdateOrderStatus, current_user: dict, now: datetime | None = None) -> dict:
    if data.status not in VALID_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if data.status == "CANCELLED" and not data.cancellation_reason:
        raise HTTPException(status_code=400, detail="Cancellation reason is required")

    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    update_data = {
        "status": data.status,
        "updated_at": timestamp,
    }
    if data.status == "ACCEPTED":
        update_data["accepted_at"] = timestamp
    if data.status == "PICKED_UP":
        update_data["picked_up_at"] = timestamp
    if data.status == "DELIVERED":
        update_data["delivered_at"] = timestamp
    if data.status == "CANCELLED" and data.cancellation_reason:
        update_data["cancellation_reason"] = data.cancellation_reason
        update_data["cancelled_by"] = current_user.get("role", "unknown")
        update_data["cancelled_at"] = timestamp
    return update_data


async def load_order_for_status_update(order_id: str) -> dict | None:
    return await db.orders.find_one({"id": order_id}, {"_id": 0})


async def clear_driver_assignment(order: dict | None) -> None:
    if order and order.get("driver_id"):
        await db.drivers.update_one(
            {"id": order["driver_id"], "current_order_id": order["id"], "driver_status": "delivery",
             "is_active": True, "account_disabled": {"$ne": True}},
            {"$set": {"current_order_id": None, "driver_status": "active"}}
        )
        await db.drivers.update_one(
            {"id": order["driver_id"], "current_order_id": order["id"]},
            {"$set": {"current_order_id": None}}
        )


async def get_available_driver_count() -> int:
    return await db.drivers.count_documents({
        "is_active": True,
        "driver_status": "active",
        "$or": [{"current_order_id": None}, {"current_order_id": {"$exists": False}}],
        "account_disabled": {"$ne": True},
    })


async def finalize_delivered_order(order: dict | None) -> None:
    if order and order.get("driver_id"):
        await db.drivers.update_one(
            {"id": order["driver_id"]},
            {
                "$inc": {"total_deliveries": 1, "total_earnings": order.get("total_amount", 0) * 0.1}
            }
        )
        await clear_driver_assignment(order)


async def _has_committed_driver_assignment(order: dict | None, driver_id: str) -> bool:
    if not order or order.get("driver_id") != driver_id or order.get("status") not in ("ASSIGNED", "ACCEPTED", "PICKED_UP"):
        return False
    return bool(await db.drivers.find_one({
        "id": driver_id, "current_order_id": order["id"],
    }, {"_id": 0, "id": 1}))


def _financial_read_order(order: dict) -> dict:
    """Keep legacy fields, but never present an invalid financial quote as payable."""
    if "financial" not in order and "financial_contract_version" not in order:
        return {**public_activity_read(order), **{k: v for k, v in public_custody_read(order).items() if k.startswith("custody_") or k.startswith("read_")}}
    result = dict(order)
    try:
        snapshot = order_financial_snapshot(order)
        result.update(financial=snapshot.model_dump(mode="json"), financial_contract_version=1)
    except FinanceError:
        result.update(financial=None, financial_contract_version=None,
                      read_financial_invalid=True, read_actions_unavailable=True)
        logger.warning("order_read_financial_invalid")
    return {**public_activity_read(result), **{k: v for k, v in public_custody_read(result).items() if k.startswith("custody_") or k.startswith("read_")}}


async def _financial_read_orders(orders):
    try:
        async with asyncio.timeout(READ_TIMEOUT_SECONDS):
            invalid = await read_activity_failures(db, orders)
            custody_invalid = await read_custody_failures(db, orders)
            values = [_financial_read_order(order) for order in orders]
            for index in custody_invalid:
                unavailable_custody_read(values[index])
            for index in invalid:
                unavailable_activity_read(values[index])
            return values
    except (TimeoutError, PyMongoError):
        raise read_error(503, "READ_UNAVAILABLE") from None


@private_read(router, "")
async def get_orders(current_user: dict = Depends(signed_read_actor)):
    return await OrderReadService(db).compatibility(current_user)


@private_read(router, "/driver/{driver_id}")
async def get_driver_orders(driver_id: str, current_user: dict = Depends(signed_read_actor)):
    return await OrderReadService(db).compatibility(current_user, kind="driver", identifier_value=driver_id)


@private_read(router, "/restaurant/{restaurant_id}")
async def get_restaurant_orders(restaurant_id: str, current_user: dict = Depends(signed_read_actor)):
    return await OrderReadService(db).compatibility(current_user, kind="restaurant", identifier_value=restaurant_id)


_read_security = HTTPBearer(auto_error=False)


async def _order_read_actor(request: Request):
    return await signed_read_actor(request)


def _order_read_query(request, names):
    if (any(name not in names or len(request.query_params.getlist(name)) != 1 for name in request.query_params)
        or len(request.headers.getlist("X-Expected-Actor-ID")) > 1):
        raise read_error(422, "INVALID_REQUEST")


@private_read(router, "/read/page")
async def read_order_page(request: Request, response: Response, view: str = "active", status: str | None = None,
                          restaurant_id: str | None = None, driver_id: str | None = None,
                          from_date: str | None = None, to_date: str | None = None, limit: str = "25",
                          cursor: str | None = None, current_user: dict = Depends(_order_read_actor),
                          expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    response.headers["Cache-Control"] = "no-store"
    _order_read_query(request, {"view", "status", "restaurant_id", "driver_id", "from_date", "to_date", "limit", "cursor"})
    return await OrderReadService(db).page(current_user, expected_actor_id=expected_actor_id, view=view, status=status,
        restaurant_id=restaurant_id, driver_id=driver_id, from_date=from_date, to_date=to_date, limit=limit, cursor=cursor)


@private_read(router, "/read/detail/{order_id:path}")
async def read_order_detail(order_id: str, request: Request, response: Response, history_before: str | None = None,
                            history_limit: str = "25", current_user: dict = Depends(_order_read_actor),
                            expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    response.headers["Cache-Control"] = "no-store"
    _order_read_query(request, {"history_before", "history_limit"})
    return await OrderReadService(db).detail(current_user, order_id, expected_actor_id=expected_actor_id,
                                            history_before=history_before, history_limit=history_limit)


@private_read(router, "/{order_id}")
async def get_order(order_id: str, current_user: dict = Depends(signed_read_actor)):
    return await OrderReadService(db).compatibility(current_user, kind="one", identifier_value=order_id)


@router.post("")
async def create_order(
    order_data: OrderCreate, current_user: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _expected_actor_context(current_user, expected_actor_id)
    if current_user.get("role") not in ["admin", "restaurant"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_user.get("role") == "restaurant" and current_user.get("restaurant_id") != order_data.restaurant_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        await guard_generic_problem_link(db, order_data)
    except FinanceError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message}) from None

    restaurant = await db.restaurants.find_one({"id": order_data.restaurant_id}, {"_id": 0})
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    _ensure_restaurant_accepts_new_orders(restaurant)

    order_number = await _next_order_number(order_data.source)

    detected_zone = await detect_delivery_zone(
        order_data.customer_latitude,
        order_data.customer_longitude,
        order_data.restaurant_id,
    )
    subtotal_amount = order_data.subtotal_amount if order_data.subtotal_amount is not None else order_data.total_amount
    delivery_fee = detected_zone.get("fee", 0) if detected_zone else (order_data.delivery_fee or 0)
    total_amount = round(subtotal_amount + delivery_fee, 2)

    order = Order(
        order_number=order_number,
        preparation_status="NEW",
        source=order_data.source,
        restaurant_id=order_data.restaurant_id,
        restaurant_name=restaurant["name"],
        customer_name=order_data.customer_name,
        customer_phone=order_data.customer_phone,
        customer_address=order_data.customer_address,
        customer_latitude=order_data.customer_latitude,
        customer_longitude=order_data.customer_longitude,
        items=order_data.items,
        subtotal_amount=subtotal_amount,
        delivery_fee=delivery_fee,
        total_amount=total_amount,
        payment_type=order_data.payment_type,
        notes=order_data.notes,
        linked_problem_order_id=order_data.linked_problem_order_id,
        problem_type=order_data.problem_type,
        problem_description=order_data.problem_description,
        zone=detected_zone.get("name") if detected_zone else None,
        delivery_zone_id=detected_zone.get("id") if detected_zone else None,
        delivery_zone_name=detected_zone.get("name") if detected_zone else None,
        delivery_sector=detected_zone.get("sector") if detected_zone else None,
        delivery_zone_level=detected_zone.get("zone_level") if detected_zone else None,
    )

    doc = order.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    doc["updated_at"] = doc["updated_at"].isoformat()
    doc["audit_trail"] = [_order_audit_entry("order.created", current_user, {"status": "NEW"})]

    await db.orders.insert_one(doc)
    await _record_order_audit_log(doc["id"], "order.created", current_user, {"status": "NEW"})
    _log_order_action("order.created", doc["id"], current_user, {"restaurant_id": doc["restaurant_id"]})
    doc.pop("_id", None)
    return doc


@router.put("/{order_id}/assign")
async def assign_order(order_id: str, data: AssignOrder, current_user: dict = Depends(get_current_user),
                       expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if expected_actor_id is not None:
        if (not isinstance(expected_actor_id, str) or not 1 <= len(expected_actor_id) <= 120
            or expected_actor_id != expected_actor_id.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in expected_actor_id)):
            raise HTTPException(status_code=422, detail={"code": "INVALID_ACTOR_ID", "message": "Identitate invalida."})
        if expected_actor_id != (current_user.get("user_id") or current_user.get("id")):
            raise HTTPException(status_code=403, detail={"code": "AUTH_CONTEXT_CHANGED", "message": "Sesiunea s-a schimbat. Pastreaza identitatea operatiei."})

    driver = await db.drivers.find_one({"id": data.driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    if driver.get("account_disabled"):
        raise HTTPException(status_code=409, detail="Livratorul este dezactivat")

    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if any(name in order or name in driver for name in MULTI_FIELDS):
        raise HTTPException(status_code=409, detail={"code": "ASSIGNMENT_REPRESENTATION_UNSUPPORTED", "message": "Asignarea necesita un protocol compatibil."})
    ensure_legacy_order(order)
    current_status = order.get("status")
    old_driver_id = order.get("driver_id")
    preparation_status = _preparation_status_for_order(order)
    if current_status == "ASSIGNED" and old_driver_id == data.driver_id:
        if not await _has_committed_driver_assignment(order, data.driver_id):
            raise HTTPException(status_code=409, detail="Alocarea este inconsistentă și trebuie verificată manual")
        _log_order_action("order.assign.duplicate", order_id, current_user, {"driver_id": data.driver_id})
        return {"message": "Order already assigned", "idempotent": True}

    if current_status not in ASSIGNABLE_ORDER_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Comanda nu poate fi alocată din statusul {current_status}",
        )
    if current_status != "ASSIGNED":
        _ensure_order_transition_allowed(order, "ASSIGNED")

    if (driver.get("is_active") is not True or ("driver_status" in driver
        and (not isinstance(driver["driver_status"], str) or driver["driver_status"] != "active"))):
        raise HTTPException(status_code=409, detail={"code": "DRIVER_NOT_AVAILABLE", "message": "Livratorul nu este activ si disponibil."})
    for field in ("break_started_at", "break_until"):
        value = driver.get(field)
        if value is not None:
            try:
                if not isinstance(value, str) or value != value.strip() or "T" not in value:
                    raise ValueError("Invalid timestamp")
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=409, detail={"code": "DRIVER_DATA_INVALID", "message": "Datele pauzei necesita verificare."}) from None

    current_driver_order = driver.get("current_order_id")
    if current_driver_order and current_driver_order != order_id:
        raise HTTPException(status_code=409, detail="Livratorul are deja o comandă activă")
    if current_driver_order == order_id:
        raise HTTPException(status_code=409, detail="Alocarea este în curs sau inconsistentă. Reîncarcă și încearcă din nou.")

    now = datetime.now(timezone.utc)
    changes = {
        "from_status": current_status,
        "to_status": "ASSIGNED",
        "old_driver_id": old_driver_id,
        "new_driver_id": data.driver_id,
    }
    if not isinstance(driver.get("name"), str) or not driver["name"].strip():
        raise HTTPException(status_code=409, detail="Livratorul are date invalide")
    assignment_filter = _preparation_snapshot_filter(order)
    assignment_update = _update_with_order_audit(
        {
            "driver_id": data.driver_id,
            "driver_name": driver["name"],
            "status": "ASSIGNED",
            "preparation_status": preparation_status,
            "assigned_at": now.isoformat(),
            "updated_at": now.isoformat(),
        },
        "order.assigned", current_user, changes, order=order,
    )

    claimed_driver = await db.drivers.find_one_and_update(
        {
            "id": data.driver_id,
            "account_disabled": {"$ne": True},
            "is_active": {"$eq": True},
            "driver_status": {"$eq": driver["driver_status"]} if "driver_status" in driver else {"$exists": False},
            "$or": [
                {"current_order_id": None},
                {"current_order_id": {"$exists": False}},
            ],
        },
        {"$set": {"current_order_id": order_id, "driver_status": "delivery", "is_active": True}},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not claimed_driver:
        latest_order = await load_order_for_status_update(order_id)
        if latest_order:
            ensure_legacy_order(latest_order)
        if await _has_committed_driver_assignment(latest_order, data.driver_id):
            _log_order_action("order.assign.duplicate", order_id, current_user, {"driver_id": data.driver_id})
            return {"message": "Order already assigned", "idempotent": True}
        raise HTTPException(status_code=409, detail="Livratorul nu mai este disponibil pentru alocare")

    updated_order = await db.orders.find_one_and_update(
        assignment_filter,
        assignment_update,
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated_order:
        latest_order = await load_order_for_status_update(order_id)
        if latest_order:
            ensure_legacy_order(latest_order)
        if await _has_committed_driver_assignment(latest_order, data.driver_id):
            _log_order_action("order.assign.duplicate", order_id, current_user, {"driver_id": data.driver_id})
            return {"message": "Order already assigned", "idempotent": True}
        await clear_driver_assignment({"id": order_id, "driver_id": data.driver_id})
        raise HTTPException(status_code=409, detail="Comanda a fost modificată între timp. Reîncarcă și încearcă din nou.")

    if old_driver_id and old_driver_id != data.driver_id:
        await clear_driver_assignment({"id": order_id, "driver_id": old_driver_id})

    await _record_order_audit_log(order_id, "order.assigned", current_user, changes)
    _log_order_action("order.assigned", order_id, current_user, changes)
    return {"message": "Order assigned"}


@router.put("/{order_id}/preparing")
async def set_preparing(
    order_id: str, data: PreparationTime, current_user: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _expected_actor_context(current_user, expected_actor_id)
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _ensure_restaurant_order_mutation_allowed(order, current_user)
    revision_filter(order)
    _ensure_preparation_mutable(order)
    preparation_status = _preparation_status_for_order(order)
    if preparation_status == "PREPARING":
        await _project_preparation_event(order, "order.preparing_started", current_user)
        _log_order_action("order.preparing.duplicate", order_id, current_user, {"status": "PREPARING"})
        return {
            "message": "Order already preparing",
            "preparation_due_at": order.get("preparation_due_at"),
            "idempotent": True,
        }
    if preparation_status != "NEW":
        raise HTTPException(status_code=409, detail="Comanda este deja gata; pregătirea nu poate fi reluată")
    next_status = "PREPARING" if order.get("status") == "NEW" else order["status"]

    available_drivers = await get_available_driver_count()
    assigned_driver_available = await _has_usable_assigned_driver(order)
    if available_drivers == 0 and not assigned_driver_available and data.preparation_time < MIN_PREP_WHEN_NO_DRIVERS:
        raise HTTPException(status_code=409, detail=f"Nu există livratori disponibili acum. Setează minimum {MIN_PREP_WHEN_NO_DRIVERS} minute sau așteaptă un livrator activ.")
    now = datetime.now(timezone.utc)
    estimated_seconds = data.preparation_time * 60
    due_at = now + timedelta(seconds=estimated_seconds)
    changes = {
        "from_status": order.get("status"),
        "to_status": next_status,
        "from_preparation_status": preparation_status,
        "to_preparation_status": "PREPARING",
        "preparation_time": data.preparation_time,
        "preparation_due_at": due_at.isoformat(),
    }
    updated_order = await db.orders.find_one_and_update(
        _preparation_snapshot_filter(order),
        _update_with_order_audit({
            "status": next_status,
            "preparation_status": "PREPARING",
            "preparation_time": data.preparation_time,
            "preparation_estimated_seconds": estimated_seconds,
            "preparation_started_at": now.isoformat(),
            "preparation_due_at": due_at.isoformat(),
            "updated_at": now.isoformat()
        }, "order.preparing_started", current_user, changes, order=order),
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated_order:
        latest_order = await load_order_for_status_update(order_id)
        if latest_order:
            _ensure_restaurant_order_mutation_allowed(latest_order, current_user)
            revision_filter(latest_order)
        if latest_order and latest_order.get("status") in {"PREPARING", "ASSIGNED", "ACCEPTED"} and _preparation_status_for_order(latest_order) == "PREPARING":
            await _project_preparation_event(latest_order, "order.preparing_started", current_user)
            _log_order_action("order.preparing.duplicate", order_id, current_user, {"status": "PREPARING"})
            return {
                "message": "Order already preparing",
                "preparation_due_at": latest_order.get("preparation_due_at"),
                "idempotent": True,
            }
        raise HTTPException(status_code=409, detail="Comanda a fost modificată între timp. Reîncarcă și încearcă din nou.")

    await _project_preparation_event(updated_order, "order.preparing_started", current_user)
    _log_order_action("order.preparing_started", order_id, current_user, changes)
    return {"message": "Order preparing", "preparation_due_at": due_at.isoformat()}


@router.get("/restaurant/{restaurant_id}/prep-availability")
async def get_restaurant_preparation_availability(restaurant_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "restaurant"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_user.get("role") == "restaurant" and current_user.get("restaurant_id") != restaurant_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    available_drivers = await get_available_driver_count()
    return {
        "available_drivers": available_drivers,
        "has_available_drivers": available_drivers > 0,
        "minimum_preparation_minutes": MIN_PREP_WHEN_NO_DRIVERS if available_drivers == 0 else 5,
        "blocked_short_options": available_drivers == 0,
    }


@router.post("/{order_id}/problem")
async def create_problem_order(order_id: str, data: ProblemOrderCreate, current_user: dict = Depends(get_current_user)):
    original = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not original:
        raise HTTPException(status_code=404, detail="Order not found")
    _ensure_restaurant_order_mutation_allowed(original, current_user)
    ensure_legacy_order(original)
    if original.get("status") != "DELIVERED":
        raise HTTPException(status_code=409, detail="Doar comenzile livrate pot avea refaceri parțiale")
    if original.get("has_problem_followup"):
        raise HTTPException(status_code=409, detail="Comanda are deja o refacere parțială asociată")
    restaurant = await db.restaurants.find_one({"id": original["restaurant_id"]}, {"_id": 0})
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    _ensure_restaurant_accepts_new_orders(restaurant)
    if data.problem_type not in ["missing_product", "new_product"]:
        raise HTTPException(status_code=400, detail="Tip problemă invalid")
    problem_label = "Produs lipsă" if data.problem_type == "missing_product" else "Produs nou"
    item_name = data.item_name or problem_label
    subtotal = max(float(data.price), 0) * max(int(data.quantity), 1)
    order = Order(
        order_number=await _next_order_number(original.get("source", "S"), "P"),
        preparation_status="NEW",
        source=original.get("source", "S"),
        restaurant_id=original["restaurant_id"],
        restaurant_name=original["restaurant_name"],
        customer_name=original["customer_name"],
        customer_phone=original["customer_phone"],
        customer_address=original["customer_address"],
        customer_latitude=original.get("customer_latitude"),
        customer_longitude=original.get("customer_longitude"),
        items=[{"name": item_name, "quantity": max(int(data.quantity), 1), "price": max(float(data.price), 0)}],
        subtotal_amount=subtotal,
        delivery_fee=0,
        total_amount=subtotal,
        payment_type=original.get("payment_type", "CASH"),
        notes=f"Problemă la {original.get('order_number')}: {data.problem_description.strip()}",
        zone=original.get("zone"),
        delivery_zone_id=original.get("delivery_zone_id"),
        delivery_zone_name=original.get("delivery_zone_name"),
        delivery_sector=original.get("delivery_sector"),
        delivery_zone_level=original.get("delivery_zone_level"),
        linked_problem_order_id=order_id,
        problem_type=data.problem_type,
        problem_description=data.problem_description.strip(),
    )
    doc = order.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    doc["updated_at"] = doc["updated_at"].isoformat()
    await db.orders.insert_one(doc)
    doc.pop("_id", None)
    result = await db.orders.update_one(
        {"id": order_id, **revision_filter(original)},
        {"$set": {"has_problem_followup": True, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    matched = result.get("matched_count", 0) if isinstance(result, dict) else result.matched_count
    if not matched:
        raise HTTPException(status_code=409, detail="Comanda initiala a fost modificata; verifica refacerea creata.")
    return {"message": "Comandă legată creată", "order": doc}


@router.put("/{order_id}/ready")
async def set_ready(
    order_id: str, current_user: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None,
):
    _expected_actor_context(current_user, expected_actor_id)
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _ensure_restaurant_order_mutation_allowed(order, current_user)
    revision_filter(order)
    _ensure_preparation_mutable(order)
    preparation_status = _preparation_status_for_order(order)
    if preparation_status == "READY":
        await _project_preparation_event(order, "order.ready", current_user)
        _log_order_action("order.ready.duplicate", order_id, current_user, {"status": "READY"})
        return {
            "message": "Order already ready",
            "preparation_actual_seconds": order.get("preparation_actual_seconds"),
            "preparation_delay_seconds": order.get("preparation_delay_seconds", 0),
            "idempotent": True,
        }
    if preparation_status != "PREPARING":
        raise HTTPException(status_code=409, detail="Setează timpul de pregătire înainte de a marca această comandă gata")
    next_status = "READY" if order.get("status") == "PREPARING" else order["status"]

    now = datetime.now(timezone.utc)
    started_at_raw = order.get("preparation_started_at")
    estimated_seconds = order.get("preparation_estimated_seconds")
    if estimated_seconds is None:
        minutes = order.get("preparation_time")
        if minutes is not None and (type(minutes) is not int or not 1 <= minutes <= 240):
            raise HTTPException(status_code=409, detail="Comanda are un timp de pregătire invalid")
        estimated_seconds = (minutes or 0) * 60
    if type(estimated_seconds) is not int or not 0 <= estimated_seconds <= 240 * 60:
        raise HTTPException(status_code=409, detail="Comanda are o estimare de pregătire invalidă")
    actual_seconds = None
    delay_seconds = 0
    if started_at_raw:
        started_at = _parse_datetime(started_at_raw)
        if not started_at:
            raise HTTPException(status_code=409, detail="Comanda are o dată de pregătire invalidă")
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        actual_seconds = max(int((now - started_at).total_seconds()), 0)
        delay_seconds = max(actual_seconds - estimated_seconds, 0)

    changes = {
        "from_status": order.get("status"),
        "to_status": next_status,
        "from_preparation_status": preparation_status,
        "to_preparation_status": "READY",
        "preparation_actual_seconds": actual_seconds,
        "preparation_delay_seconds": delay_seconds,
    }
    updated_order = await db.orders.find_one_and_update(
        _preparation_snapshot_filter(order),
        _update_with_order_audit({
            "status": next_status,
            "preparation_status": "READY",
            "preparation_ready_at": now.isoformat(),
            "preparation_actual_seconds": actual_seconds,
            "preparation_delay_seconds": delay_seconds,
            "updated_at": now.isoformat()
        }, "order.ready", current_user, changes, order=order),
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated_order:
        latest_order = await load_order_for_status_update(order_id)
        if latest_order:
            _ensure_restaurant_order_mutation_allowed(latest_order, current_user)
            revision_filter(latest_order)
        if latest_order and latest_order.get("status") in {"READY", "ASSIGNED", "ACCEPTED"} and _preparation_status_for_order(latest_order) == "READY":
            await _project_preparation_event(latest_order, "order.ready", current_user)
            _log_order_action("order.ready.duplicate", order_id, current_user, {"status": "READY"})
            return {
                "message": "Order already ready",
                "preparation_actual_seconds": latest_order.get("preparation_actual_seconds"),
                "preparation_delay_seconds": latest_order.get("preparation_delay_seconds", 0),
                "idempotent": True,
            }
        raise HTTPException(status_code=409, detail="Comanda a fost modificată între timp. Reîncarcă și încearcă din nou.")

    await _project_preparation_event(updated_order, "order.ready", current_user)
    _log_order_action("order.ready", order_id, current_user, changes)
    return {"message": "Order ready", "preparation_actual_seconds": actual_seconds, "preparation_delay_seconds": delay_seconds}


@router.put("/{order_id}/status")
async def update_order_status(order_id: str, data: UpdateOrderStatus, current_user: dict = Depends(get_current_user),
                              expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    if expected_actor_id is not None:
        if (not isinstance(expected_actor_id, str) or not 1 <= len(expected_actor_id) <= 120
            or expected_actor_id != expected_actor_id.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in expected_actor_id)):
            raise HTTPException(status_code=422, detail={"code": "INVALID_ACTOR_ID", "message": "Identitate invalida."})
        if expected_actor_id != (current_user.get("user_id") or current_user.get("id")):
            raise HTTPException(status_code=403, detail={"code": "AUTH_CONTEXT_CHANGED", "message": "Sesiunea s-a schimbat. Pastreaza identitatea operatiei."})
    if data.status not in GENERIC_STATUS_ENDPOINT_STATUSES:
        raise HTTPException(status_code=400, detail="Folosește endpoint-ul dedicat pentru acest status")

    order = await load_order_for_status_update(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _ensure_status_mutation_allowed(order, data.status, current_user)
    ensure_legacy_order(order)
    if data.status == "CANCELLED" and order.get("status") in {"PICKED_UP", "DELIVERED"}:
        raise HTTPException(status_code=409, detail={"code": "CUSTODY_RESOLUTION_REQUIRED", "message": "Comanda ridicata necesita rezolvarea custodiei; anularea directa este blocata."})

    should_update = _ensure_order_transition_allowed(order, data.status)
    if not should_update:
        _log_order_action("order.status.duplicate", order_id, current_user, {"status": data.status})
        return {"message": "Status already applied", "idempotent": True}

    if data.status == "PICKED_UP" and _preparation_status_for_order(order) != "READY":
        raise HTTPException(status_code=409, detail="Restaurantul trebuie să marcheze comanda gata înainte de ridicare")

    now = datetime.now(timezone.utc)
    update_data = build_status_update_payload(data, current_user, now)
    changes = {
        "from_status": order.get("status"),
        "to_status": data.status,
    }
    if data.cancellation_reason:
        changes["cancellation_reason"] = data.cancellation_reason

    updated_order = await db.orders.find_one_and_update(
        _preparation_snapshot_filter(order),
        _update_with_order_audit(update_data, "order.status_changed", current_user, changes, order=order),
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated_order:
        latest_order = await load_order_for_status_update(order_id)
        if latest_order:
            _ensure_status_mutation_allowed(latest_order, data.status, current_user)
            ensure_legacy_order(latest_order)
        if latest_order and latest_order.get("status") == data.status:
            _log_order_action("order.status.duplicate", order_id, current_user, {"status": data.status})
            return {"message": "Status already applied", "idempotent": True}
        raise HTTPException(status_code=409, detail="Comanda a fost modificată între timp. Reîncarcă și încearcă din nou.")

    if data.status == "DELIVERED":
        await finalize_delivered_order(updated_order)

    if data.status == "CANCELLED":
        await clear_driver_assignment(updated_order)

    await _record_order_audit_log(order_id, "order.status_changed", current_user, changes)
    _log_order_action("order.status_changed", order_id, current_user, changes)
    return {"message": "Status updated"}


@router.get("/{order_id}/incidents")
async def get_order_incidents(order_id: str, actor: dict = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=100), cursor: str | None = Query(default=None, max_length=512),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    from utils.operational_reporting import OperationalReportingService, ReportingError
    _expected_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OperationalReportingService(db, "incident").incidents(order_id, actor, limit, cursor),
                            headers={"Cache-Control": "no-store"})
    except ReportingError as error:
        raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message},
                            headers={"Cache-Control": "no-store"}) from None
