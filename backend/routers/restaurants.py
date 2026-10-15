from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
import asyncio
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import uuid
import secrets
from shapely.geometry import Point, Polygon
from database import db
from auth import hash_password, get_current_user
from models.restaurant import RestaurantCreate, RestaurantAvailabilityRequest, RestaurantScheduleSettingsUpdate

from models.operational_reporting import CloseDayCommand, OperationalCommand
from utils.operational_reporting import OperationalReportingService, ReportingError, DEADLINE_SECONDS
from utils.order_finance import FinanceError, order_financial_snapshot
from utils.order_reads import OrderReadService, read_error, identifier
from utils.order_financial_reads import private_read, signed_read_actor, OUTER_FIELDS, project_outer
from routers.order_operations import PrivateOperationRoute, _assign_actor_context, _http_error

router = APIRouter(prefix="/restaurants", tags=["restaurants"])
RESTAURANT_TIMEZONE = ZoneInfo("Europe/Bucharest")


def _generate_initial_password() -> str:
    return secrets.token_urlsafe(12)


def _next_restaurant_local_midnight_utc(now: datetime | None = None) -> datetime:
    current_utc = now or datetime.now(timezone.utc)
    if current_utc.tzinfo is None:
        current_utc = current_utc.replace(tzinfo=timezone.utc)
    local_now = current_utc.astimezone(RESTAURANT_TIMEZONE)
    next_local_date = local_now.date() + timedelta(days=1)
    local_midnight = datetime.combine(next_local_date, time.min, tzinfo=RESTAURANT_TIMEZONE)
    return local_midnight.astimezone(timezone.utc)


class RestaurantStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepting_orders: bool
    pause_minutes: int | None = Field(default=None, ge=1, le=720)
    closed_today: bool | None = None


@router.get("")
async def get_restaurants(current_user: dict = Depends(get_current_user)):
    restaurants = await db.restaurants.find({}, {"_id": 0}).to_list(100)
    return restaurants


def build_shapely_polygon(coords):
    if len(coords) < 3:
        return None
    ring = [(c["lng"], c["lat"]) for c in coords]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return Polygon(ring)


async def restaurant_covers_point(restaurant_id: str, point: Point) -> bool:
    zones = await db.delivery_zones.find(
        {"restaurant_id": restaurant_id, "is_active": True},
        {"_id": 0, "polygon": 1},
    ).to_list(300)
    for zone in zones:
        poly = build_shapely_polygon(zone.get("polygon", []))
        if poly and poly.contains(point):
            return True
    return False


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _avg(values: list[float]) -> float:
    usable = [value for value in values if value is not None]
    if not usable:
        return 0
    return round(sum(usable) / len(usable), 2)


def _bucket_counts(orders: list[dict], bucket: str) -> list[dict]:
    counts = {}
    for order in orders:
        created_at = _parse_dt(order.get("created_at"))
        if not created_at:
            continue
        if bucket == "hour":
            key = f"{created_at.hour:02d}:00"
        elif bucket == "day":
            key = created_at.strftime("%a %d.%m")
        elif bucket == "week":
            year, week, _ = created_at.isocalendar()
            key = f"S{week} {year}"
        elif bucket == "month":
            key = created_at.strftime("%Y-%m")
        else:
            key = str(created_at.year)
        counts[key] = counts.get(key, 0) + 1

    if bucket == "hour":
        return [{"label": f"{hour:02d}:00", "count": counts.get(f"{hour:02d}:00", 0)} for hour in range(24)]
    return [{"label": key, "count": value} for key, value in counts.items()]


def _delivery_seconds(order: dict) -> int | None:
    start = _parse_dt(order.get("picked_up_at") or order.get("accepted_at") or order.get("assigned_at"))
    end = _parse_dt(order.get("delivered_at"))
    if not start or not end:
        return None
    return max(int((end - start).total_seconds()), 0)


def _split_orders_by_status(orders: list[dict]) -> dict[str, list[dict]]:
    return {
        "delivered": [order for order in orders if order.get("status") == "DELIVERED"],
        "cancelled": [order for order in orders if order.get("status") == "CANCELLED"],
        "active": [order for order in orders if order.get("status") not in ["DELIVERED", "CANCELLED"]],
    }


def _preparation_metric_lists(orders: list[dict], delivered: list[dict]) -> dict[str, list[float]]:
    return {
        "estimated": [(order.get("preparation_estimated_seconds") or 0) / 60 for order in orders if order.get("preparation_estimated_seconds")],
        "actual": [(order.get("preparation_actual_seconds") or 0) / 60 for order in orders if order.get("preparation_actual_seconds") is not None],
        "delay": [(order.get("preparation_delay_seconds") or 0) / 60 for order in orders if order.get("preparation_delay_seconds") is not None],
        "delivery": [seconds / 60 for seconds in (_delivery_seconds(order) for order in delivered) if seconds is not None],
    }


def _build_order_analytics_summary(orders: list[dict], status_groups: dict[str, list[dict]], metrics: dict[str, list[float]]) -> dict:
    return {
        "total_orders": len(orders),
        "active_orders": len(status_groups["active"]),
        "delivered_orders": len(status_groups["delivered"]),
        "cancelled_orders": len(status_groups["cancelled"]),
        "avg_preparation_estimated_minutes": _avg(metrics["estimated"]),
        "avg_preparation_actual_minutes": _avg(metrics["actual"]),
        "avg_preparation_delay_minutes": _avg(metrics["delay"]),
        "avg_delivery_minutes": _avg(metrics["delivery"]),
    }


def _build_restaurant_charts(orders: list[dict]) -> dict:
    return {
        "by_hour": _bucket_counts(orders, "hour"),
        "by_day": _bucket_counts(orders, "day"),
        "by_week": _bucket_counts(orders, "week"),
        "by_month": _bucket_counts(orders, "month"),
        "by_year": _bucket_counts(orders, "year"),
    }


def _build_recent_order_row(order: dict) -> dict:
    delivery_seconds = _delivery_seconds(order)
    row = {
        "id": order.get("id"),
        "order_number": order.get("order_number"),
        "status": order.get("status"),
        "customer_address": order.get("customer_address"),
        "total_amount": order.get("total_amount", 0),
        "created_at": order.get("created_at"),
        "preparation_time": order.get("preparation_time"),
        "preparation_actual_minutes": round((order.get("preparation_actual_seconds") or 0) / 60, 2) if order.get("preparation_actual_seconds") is not None else None,
        "preparation_delay_minutes": round((order.get("preparation_delay_seconds") or 0) / 60, 2) if order.get("preparation_delay_seconds") is not None else None,
        "delivery_minutes": round(delivery_seconds / 60, 2) if delivery_seconds is not None else None,
    }
    if "financial" in order or "financial_contract_version" in order:
        try:
            financial = order_financial_snapshot(order)
            row.update(financial=financial.model_dump(mode="json"), financial_contract_version=1,
                       creation_operation_ref=financial.operation_ref, restaurant_id=financial.restaurant_id,
                       payment_type=order["payment_type"])
        except FinanceError:
            row.update(financial=None, financial_contract_version=None, read_financial_invalid=True,
                       read_actions_unavailable=True)
    return row


@router.post("")
async def create_restaurant(data: RestaurantCreate, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    restaurant_id = str(uuid.uuid4())

    restaurant_doc = {
        "id": restaurant_id,
        "name": data.name,
        "address": data.address,
        "phone": data.phone,
        "contact_name": data.contact_name,
        "email": data.email,
        "latitude": data.latitude,
        "longitude": data.longitude,
        "location_source": data.location_source,
        "accepting_orders": True,
        "pause_until": None,
        "closed_today": False,
        "schedule_settings": _default_schedule_settings(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.restaurants.insert_one(restaurant_doc)
    restaurant_doc.pop("_id", None)

    user_id = str(uuid.uuid4())
    email = f"restaurant-{restaurant_id[:8]}@delivery.ro"
    initial_password = _generate_initial_password()

    user_doc = {
        "id": user_id,
        "email": email,
        "name": data.name,
        "role": "restaurant",
        "phone": data.phone,
        "restaurant_id": restaurant_id,
        "restaurant_name": data.name,
        "password_hash": hash_password(initial_password),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)

    return {
        "message": "Restaurant created",
        "restaurant_id": restaurant_id,
        "restaurant": restaurant_doc,
        "login_email": email,
        "password": initial_password
    }


@router.post("/available")
async def get_available_restaurants(
    data: RestaurantAvailabilityRequest,
    current_user: dict = Depends(get_current_user),
):
    point = Point(data.lng, data.lat)
    restaurants = await db.restaurants.find({"accepting_orders": {"$ne": False}}, {"_id": 0}).to_list(1000)
    available = []
    for restaurant in restaurants:
        if await restaurant_covers_point(restaurant["id"], point):
            available.append(restaurant)
    return {"restaurants": available, "count": len(available)}


@router.get("/{restaurant_id}")
async def get_restaurant(restaurant_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "restaurant" and current_user.get("restaurant_id") != restaurant_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    restaurant = await db.restaurants.find_one({"id": restaurant_id}, {"_id": 0})
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant


@router.patch("/{restaurant_id}/status")
async def update_restaurant_status(restaurant_id: str, data: RestaurantStatusUpdate, current_user: dict = Depends(get_current_user)):
    # Pause/resume is administrative; closure uses its own durable intent route.
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"code": "NOT_AUTHORIZED", "message": "Pauza este administrata separat."})
    if data.closed_today is True:
        raise HTTPException(status_code=422, detail={"code": "CLOSE_DAY_OPERATION_REQUIRED", "message": "Foloseste actiunea distincta de inchidere."})
    restaurant = await db.restaurants.find_one({"id": restaurant_id}, {"_id": 0})
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    now = datetime.now(timezone.utc)
    update = {
        "accepting_orders": data.accepting_orders,
        "status_updated_at": now.isoformat(),
        "status_updated_by": current_user.get("user_id"),
        "pause_until": None,
    }
    if not data.accepting_orders and data.pause_minutes:
        minutes = max(1, min(int(data.pause_minutes), 720))
        update["pause_until"] = (now + timedelta(minutes=minutes)).isoformat()
    await db.restaurants.update_one({"id": restaurant_id}, {"$set": update})
    return {"message": "Status restaurant actualizat", **update}


def _default_schedule_settings() -> dict:
    return {
        day: {"enabled": True, "open_time": "10:00", "close_time": "22:00"}
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    }


@router.patch("/{restaurant_id}/schedule-settings")
async def update_restaurant_schedule_settings(restaurant_id: str, data: RestaurantScheduleSettingsUpdate, current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "restaurant" and current_user.get("restaurant_id") != restaurant_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_user["role"] not in ["restaurant", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    restaurant = await db.restaurants.find_one({"id": restaurant_id}, {"_id": 0})
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    schedule = _default_schedule_settings()
    incoming = data.model_dump(exclude_none=True)
    for day, value in incoming.items():
        schedule[day] = value
    update = {"schedule_settings": schedule, "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.restaurants.update_one({"id": restaurant_id}, {"$set": update})
    return {"message": "Program restaurant actualizat", **update}


@private_read(router, "/{restaurant_id}/analytics")
async def get_restaurant_analytics(restaurant_id: str, current_user: dict = Depends(signed_read_actor)):
    service = OrderReadService(db)
    async def execute():
        identifier(restaurant_id)
        context = await service.authorize_read(current_user)
        if context.role != "admin" and (context.role != "restaurant" or context.restaurant_id != restaurant_id):
            raise read_error(403, "NOT_AUTHORIZED")
        restaurants = await service.outer_documents(db.restaurants, {"id": restaurant_id}, OUTER_FIELDS["restaurant"])
        if len(restaurants) != 1:
            raise read_error(404 if not restaurants else 409, "RESTAURANT_NOT_FOUND" if not restaurants else "RESTAURANT_AMBIGUOUS")
        restaurant = project_outer(restaurants[0], "restaurant")
        if restaurant.get("id") != restaurant_id:
            raise read_error(503, "READ_UNAVAILABLE")
        orders = await service.load_orders(context, query={"restaurant_id": restaurant_id}, limit=2000, sort={"created_at": -1})
        projected, _ = await service.serialize_orders(orders[:80], context)
        status_groups = _split_orders_by_status(orders)
        metrics = _preparation_metric_lists(orders, status_groups["delivered"])
        recent = []
        for document, validated in zip(orders[:80], projected):
            row = _build_recent_order_row(document)
            for key in ("financial", "financial_contract_version", "creation_operation_ref",
                        "read_financial_invalid", "read_actions_unavailable"):
                row.pop(key, None)
            row.update({k: v for k, v in validated.items() if k.startswith(("financial", "custody", "read_"))
                or k in ("restaurant_id", "driver_id", "payment_type", "creation_operation_ref")})
            recent.append(row)
        await service.revalidate_read(context)
        return {"restaurant": restaurant, "program": restaurant.get("program") or "Program nesetat",
            "summary": _build_order_analytics_summary(orders, status_groups, metrics),
            "charts": _build_restaurant_charts(orders), "recent_orders": recent}
    return await service._bounded(execute)


close_day_router = APIRouter(prefix="/{restaurant_id}/close-day", route_class=PrivateOperationRoute)

def _close_day_path(operation_id):
    try:
        OperationalCommand(client_operation_id=operation_id)
    except ValidationError:
        raise HTTPException(status_code=422, detail={"code": "INVALID_OPERATION_ID", "message": "Identitate invalida."}) from None

async def _close_day_response(outcome):
    headers = {"Cache-Control": "no-store"}
    if outcome.result["state"] == "pending":
        headers["Retry-After"] = str(outcome.result["retry_after_seconds"])
    return JSONResponse(outcome.result, status_code=outcome.status_code, headers=headers)

@close_day_router.get("/capabilities")
async def close_day_capabilities(restaurant_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _assign_actor_context(actor, expected_actor_id)
    try:
        return JSONResponse(await OperationalReportingService(db, "close_day").capabilities(actor, restaurant_id),
                            headers={"Cache-Control": "no-store"})
    except ReportingError as error:
        raise _http_error(error) from None

@close_day_router.patch("")
async def close_restaurant_day(restaurant_id: str, command: CloseDayCommand, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _assign_actor_context(actor, expected_actor_id)
    try:
        return await _close_day_response(await OperationalReportingService(db, "close_day").submit(restaurant_id, command, actor))
    except ReportingError as error:
        raise _http_error(error) from None

@close_day_router.get("/operations/{client_operation_id}")
async def lookup_close_day(restaurant_id: str, client_operation_id: str, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _assign_actor_context(actor, expected_actor_id); _close_day_path(client_operation_id)
    try:
        return await _close_day_response(await OperationalReportingService(db, "close_day").lookup(restaurant_id, client_operation_id, actor))
    except ReportingError as error:
        raise _http_error(error) from None

@close_day_router.post("/operations/{client_operation_id}/resume")
async def resume_close_day(restaurant_id: str, client_operation_id: str, request: Request, actor: dict = Depends(get_current_user),
    expected_actor_id: Annotated[str | None, Header(alias="X-Expected-Actor-ID")] = None):
    _assign_actor_context(actor, expected_actor_id); _close_day_path(client_operation_id)
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(status_code=422, detail={"code": "INVALID_REQUEST", "message": "Cererea nu accepta date."})
    except TimeoutError:
        raise HTTPException(status_code=408, detail={"code": "REQUEST_TIMEOUT", "message": "Cererea nu s-a incheiat la timp."}) from None
    try:
        return await _close_day_response(await OperationalReportingService(db, "close_day").resume(restaurant_id, client_operation_id, actor))
    except ReportingError as error:
        raise _http_error(error) from None

router.include_router(close_day_router)
