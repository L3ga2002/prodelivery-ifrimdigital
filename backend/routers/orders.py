import re
import logging
import uuid

from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timedelta, timezone
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from shapely.geometry import Point, Polygon
from database import db
from auth import get_current_user
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
DRIVER_MUTATION_STATUSES = {"ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"}
GENERIC_STATUS_ENDPOINT_STATUSES = {"ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"}
ASSIGNABLE_ORDER_STATUSES = {"NEW", "PREPARING", "READY", "ASSIGNED"}
ORDER_STATUS_TRANSITIONS = {
    "NEW": {"PREPARING", "ASSIGNED", "CANCELLED"},
    "PREPARING": {"READY", "ASSIGNED", "CANCELLED"},
    "READY": {"ASSIGNED", "CANCELLED"},
    "ASSIGNED": {"ACCEPTED", "CANCELLED"},
    "ACCEPTED": {"PICKED_UP", "CANCELLED"},
    "PICKED_UP": {"DELIVERED", "CANCELLED"},
    "DELIVERED": set(),
    "CANCELLED": set(),
}
ORDER_COUNTER_ID = "orders.global"
ORDER_NUMBER_RE = re.compile(r"^[^.]+\.(\d+)")


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


def _update_with_order_audit(set_data: dict, action: str, current_user: dict, changes: dict | None = None) -> dict:
    return {
        "$set": set_data,
        "$push": {"audit_trail": _order_audit_entry(action, current_user, changes)},
    }


def _order_filter_for_loaded_order(order: dict) -> dict:
    current_driver = order.get("driver_id")
    query = {"id": order["id"], "status": order.get("status")}
    if current_driver:
        query["driver_id"] = current_driver
    else:
        query["$or"] = [{"driver_id": None}, {"driver_id": {"$exists": False}}]
    return query


async def _record_order_audit_log(order_id: str, action: str, current_user: dict, changes: dict | None = None) -> None:
    try:
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
    except Exception:
        logger.exception("Failed to write order audit log for order_id=%s action=%s", order_id, action)


def _log_order_action(action: str, order_id: str, current_user: dict, changes: dict | None = None) -> None:
    logger.info(
        "order_action=%s order_id=%s actor_role=%s actor_id=%s changes=%s",
        action,
        order_id,
        current_user.get("role"),
        current_user.get("user_id") or current_user.get("id"),
        changes or {},
    )


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
    if restaurant.get("closed_today"):
        raise HTTPException(status_code=409, detail="Restaurantul este închis pentru ziua curentă")
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
        order["created_at"] = datetime.fromisoformat(order["created_at"])
    if isinstance(order.get("updated_at"), str):
        order["updated_at"] = datetime.fromisoformat(order["updated_at"])
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
            {"id": order["driver_id"]},
            {"$set": {"current_order_id": None, "driver_status": "active", "is_active": True}}
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
                "$set": {"current_order_id": None, "driver_status": "active", "is_active": True},
                "$inc": {"total_deliveries": 1, "total_earnings": order.get("total_amount", 0) * 0.1}
            }
        )


@router.get("")
async def get_orders(current_user: dict = Depends(get_current_user)):
    orders = await db.orders.find(_orders_query_for_user(current_user), {"_id": 0}).to_list(1000)
    return [_format_order_dates(order) for order in orders]


@router.get("/driver/{driver_id}")
async def get_driver_orders(driver_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin" and not (
        current_user.get("role") == "driver" and current_user.get("driver_id") == driver_id
    ):
        raise HTTPException(status_code=403, detail="Not authorized")
    orders = await db.orders.find(
        {"driver_id": driver_id, "status": {"$nin": ["DELIVERED"]}},
        {"_id": 0}
    ).to_list(100)
    return orders


@router.get("/restaurant/{restaurant_id}")
async def get_restaurant_orders(restaurant_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin" and not (
        current_user.get("role") == "restaurant" and current_user.get("restaurant_id") == restaurant_id
    ):
        raise HTTPException(status_code=403, detail="Not authorized")
    orders = await db.orders.find(
        {"restaurant_id": restaurant_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return orders


@router.get("/{order_id}")
async def get_order(order_id: str, current_user: dict = Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _ensure_order_read_allowed(order, current_user)
    return order


@router.post("")
async def create_order(order_data: OrderCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "restaurant"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_user.get("role") == "restaurant" and current_user.get("restaurant_id") != order_data.restaurant_id:
        raise HTTPException(status_code=403, detail="Not authorized")

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
async def assign_order(order_id: str, data: AssignOrder, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    driver = await db.drivers.find_one({"id": data.driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    if driver.get("account_disabled"):
        raise HTTPException(status_code=409, detail="Livratorul este dezactivat")

    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    current_status = order.get("status")
    old_driver_id = order.get("driver_id")
    if current_status == "ASSIGNED" and old_driver_id == data.driver_id:
        _log_order_action("order.assign.duplicate", order_id, current_user, {"driver_id": data.driver_id})
        return {"message": "Order already assigned", "idempotent": True}

    if current_status not in ASSIGNABLE_ORDER_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Comanda nu poate fi alocată din statusul {current_status}",
        )
    if current_status != "ASSIGNED":
        _ensure_order_transition_allowed(order, "ASSIGNED")

    current_driver_order = driver.get("current_order_id")
    if current_driver_order and current_driver_order != order_id:
        raise HTTPException(status_code=409, detail="Livratorul are deja o comandă activă")

    now = datetime.now(timezone.utc)
    changes = {
        "from_status": current_status,
        "to_status": "ASSIGNED",
        "old_driver_id": old_driver_id,
        "new_driver_id": data.driver_id,
    }

    claimed_driver = await db.drivers.find_one_and_update(
        {
            "id": data.driver_id,
            "account_disabled": {"$ne": True},
            "$or": [
                {"current_order_id": None},
                {"current_order_id": {"$exists": False}},
                {"current_order_id": order_id},
            ],
        },
        {"$set": {"current_order_id": order_id, "driver_status": "delivery", "is_active": True}},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not claimed_driver:
        raise HTTPException(status_code=409, detail="Livratorul nu mai este disponibil pentru alocare")

    updated_order = await db.orders.find_one_and_update(
        _order_filter_for_loaded_order(order),
        _update_with_order_audit(
            {
                "driver_id": data.driver_id,
                "driver_name": driver["name"],
                "status": "ASSIGNED",
                "assigned_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
            "order.assigned",
            current_user,
            changes,
        ),
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated_order:
        if current_driver_order != order_id:
            await db.drivers.update_one(
                {"id": data.driver_id, "current_order_id": order_id},
                {"$set": {"current_order_id": None, "driver_status": "active", "is_active": True}},
            )
        latest_order = await load_order_for_status_update(order_id)
        if latest_order and latest_order.get("status") == "ASSIGNED" and latest_order.get("driver_id") == data.driver_id:
            _log_order_action("order.assign.duplicate", order_id, current_user, {"driver_id": data.driver_id})
            return {"message": "Order already assigned", "idempotent": True}
        raise HTTPException(status_code=409, detail="Comanda a fost modificată între timp. Reîncarcă și încearcă din nou.")

    if old_driver_id and old_driver_id != data.driver_id:
        await db.drivers.update_one(
            {"id": old_driver_id, "current_order_id": order_id},
            {"$set": {"current_order_id": None, "driver_status": "active", "is_active": True}},
        )

    await _record_order_audit_log(order_id, "order.assigned", current_user, changes)
    _log_order_action("order.assigned", order_id, current_user, changes)
    return {"message": "Order assigned"}


@router.put("/{order_id}/preparing")
async def set_preparing(order_id: str, data: PreparationTime, current_user: dict = Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _ensure_restaurant_order_mutation_allowed(order, current_user)
    if order.get("status") == "PREPARING":
        _log_order_action("order.preparing.duplicate", order_id, current_user, {"status": "PREPARING"})
        return {
            "message": "Order already preparing",
            "preparation_due_at": order.get("preparation_due_at"),
            "idempotent": True,
        }
    _ensure_order_transition_allowed(order, "PREPARING")

    available_drivers = await get_available_driver_count()
    if available_drivers == 0 and data.preparation_time < MIN_PREP_WHEN_NO_DRIVERS:
        raise HTTPException(status_code=409, detail=f"Nu există livratori disponibili acum. Setează minimum {MIN_PREP_WHEN_NO_DRIVERS} minute sau așteaptă un livrator activ.")
    now = datetime.now(timezone.utc)
    estimated_seconds = data.preparation_time * 60
    due_at = now + timedelta(seconds=estimated_seconds)
    changes = {
        "from_status": order.get("status"),
        "to_status": "PREPARING",
        "preparation_time": data.preparation_time,
        "preparation_due_at": due_at.isoformat(),
    }
    updated_order = await db.orders.find_one_and_update(
        {"id": order_id, "status": "NEW"},
        _update_with_order_audit({
            "status": "PREPARING",
            "preparation_time": data.preparation_time,
            "preparation_estimated_seconds": estimated_seconds,
            "preparation_started_at": now.isoformat(),
            "preparation_due_at": due_at.isoformat(),
            "updated_at": now.isoformat()
        }, "order.preparing_started", current_user, changes),
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated_order:
        latest_order = await load_order_for_status_update(order_id)
        if latest_order and latest_order.get("status") == "PREPARING":
            _log_order_action("order.preparing.duplicate", order_id, current_user, {"status": "PREPARING"})
            return {
                "message": "Order already preparing",
                "preparation_due_at": latest_order.get("preparation_due_at"),
                "idempotent": True,
            }
        raise HTTPException(status_code=409, detail="Comanda a fost modificată între timp. Reîncarcă și încearcă din nou.")

    await _record_order_audit_log(order_id, "order.preparing_started", current_user, changes)
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
    await db.orders.update_one({"id": order_id}, {"$set": {"has_problem_followup": True, "updated_at": datetime.now(timezone.utc).isoformat()}})
    return {"message": "Comandă legată creată", "order": doc}


@router.put("/{order_id}/ready")
async def set_ready(order_id: str, current_user: dict = Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _ensure_restaurant_order_mutation_allowed(order, current_user)
    if order.get("status") == "READY":
        _log_order_action("order.ready.duplicate", order_id, current_user, {"status": "READY"})
        return {
            "message": "Order already ready",
            "preparation_actual_seconds": order.get("preparation_actual_seconds"),
            "preparation_delay_seconds": order.get("preparation_delay_seconds", 0),
            "idempotent": True,
        }
    _ensure_order_transition_allowed(order, "READY")

    now = datetime.now(timezone.utc)
    started_at_raw = order.get("preparation_started_at")
    estimated_seconds = order.get("preparation_estimated_seconds") or ((order.get("preparation_time") or 0) * 60)
    actual_seconds = None
    delay_seconds = 0
    if started_at_raw:
        started_at = _parse_datetime(started_at_raw)
        if started_at:
            actual_seconds = max(int((now - started_at).total_seconds()), 0)
            delay_seconds = max(actual_seconds - estimated_seconds, 0)

    changes = {
        "from_status": order.get("status"),
        "to_status": "READY",
        "preparation_actual_seconds": actual_seconds,
        "preparation_delay_seconds": delay_seconds,
    }
    updated_order = await db.orders.find_one_and_update(
        {"id": order_id, "status": "PREPARING"},
        _update_with_order_audit({
            "status": "READY",
            "preparation_ready_at": now.isoformat(),
            "preparation_actual_seconds": actual_seconds,
            "preparation_delay_seconds": delay_seconds,
            "updated_at": now.isoformat()
        }, "order.ready", current_user, changes),
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated_order:
        latest_order = await load_order_for_status_update(order_id)
        if latest_order and latest_order.get("status") == "READY":
            _log_order_action("order.ready.duplicate", order_id, current_user, {"status": "READY"})
            return {
                "message": "Order already ready",
                "preparation_actual_seconds": latest_order.get("preparation_actual_seconds"),
                "preparation_delay_seconds": latest_order.get("preparation_delay_seconds", 0),
                "idempotent": True,
            }
        raise HTTPException(status_code=409, detail="Comanda a fost modificată între timp. Reîncarcă și încearcă din nou.")

    await _record_order_audit_log(order_id, "order.ready", current_user, changes)
    _log_order_action("order.ready", order_id, current_user, changes)
    return {"message": "Order ready", "preparation_actual_seconds": actual_seconds, "preparation_delay_seconds": delay_seconds}


@router.put("/{order_id}/status")
async def update_order_status(order_id: str, data: UpdateOrderStatus, current_user: dict = Depends(get_current_user)):
    if data.status not in GENERIC_STATUS_ENDPOINT_STATUSES:
        raise HTTPException(status_code=400, detail="Folosește endpoint-ul dedicat pentru acest status")

    order = await load_order_for_status_update(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _ensure_status_mutation_allowed(order, data.status, current_user)

    should_update = _ensure_order_transition_allowed(order, data.status)
    if not should_update:
        _log_order_action("order.status.duplicate", order_id, current_user, {"status": data.status})
        return {"message": "Status already applied", "idempotent": True}

    now = datetime.now(timezone.utc)
    update_data = build_status_update_payload(data, current_user, now)
    changes = {
        "from_status": order.get("status"),
        "to_status": data.status,
    }
    if data.cancellation_reason:
        changes["cancellation_reason"] = data.cancellation_reason

    updated_order = await db.orders.find_one_and_update(
        {"id": order_id, "status": order.get("status")},
        _update_with_order_audit(update_data, "order.status_changed", current_user, changes),
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated_order:
        latest_order = await load_order_for_status_update(order_id)
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
