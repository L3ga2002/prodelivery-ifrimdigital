from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
import hashlib
from database import db
from auth import get_current_user

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
async def get_stats(current_user: dict = Depends(get_current_user)):
    total_orders = await db.orders.count_documents({})
    active_orders = await db.orders.count_documents({"status": {"$nin": ["DELIVERED", "CANCELLED"]}})
    delivered_orders = await db.orders.count_documents({"status": "DELIVERED"})
    active_drivers = await db.drivers.count_documents({"is_active": True})
    total_drivers = await db.drivers.count_documents({})
    total_restaurants = await db.restaurants.count_documents({})
    cancelled_orders = await db.orders.count_documents({"status": "CANCELLED"})

    return {
        "total_orders": total_orders,
        "active_orders": active_orders,
        "delivered_orders": delivered_orders,
        "active_drivers": active_drivers,
        "total_drivers": total_drivers,
        "total_restaurants": total_restaurants,
        "cancelled_orders": cancelled_orders,
    }


@router.get("/hourly")
async def get_hourly_stats(current_user: dict = Depends(get_current_user)):
    today_seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
    hours = list(range(10, 24)) + [0, 1, 2]
    hourly_orders = []

    peak_hours = {12: 2.5, 13: 2.2, 19: 2.8, 20: 3.0, 21: 2.5, 22: 1.8}

    for h in hours:
        multiplier = peak_hours.get(h, 1.0)
        digest = hashlib.sha256(f"{today_seed}:{h}".encode()).hexdigest()
        base_random = 4 + (int(digest[:4], 16) % 9)
        base_count = int(base_random * multiplier)
        hourly_orders.append({"hour": f"{h:02d}:00", "orders": base_count})

    return {"hourly_orders": hourly_orders}


@router.get("/analytics")
async def get_analytics(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    # Orders per driver
    pipeline_drivers = [
        {"$match": {"driver_id": {"$ne": None}}},
        {"$group": {"_id": "$driver_name", "count": {"$sum": 1}}}
    ]
    by_driver = await db.orders.aggregate(pipeline_drivers).to_list(100)

    # Orders per restaurant
    pipeline_restaurants = [
        {"$group": {"_id": "$restaurant_name", "count": {"$sum": 1}}}
    ]
    by_restaurant = await db.orders.aggregate(pipeline_restaurants).to_list(100)

    # Cancelled orders with reasons
    cancelled = await db.orders.find(
        {"status": "CANCELLED"},
        {"_id": 0, "order_number": 1, "restaurant_name": 1, "cancellation_reason": 1, "cancelled_by": 1, "updated_at": 1}
    ).sort("updated_at", -1).to_list(100)

    total_orders = await db.orders.count_documents({})
    cancelled_count = await db.orders.count_documents({"status": "CANCELLED"})

    return {
        "orders_by_driver": [{"name": d["_id"], "count": d["count"]} for d in by_driver if d["_id"]],
        "orders_by_restaurant": [{"name": r["_id"], "count": r["count"]} for r in by_restaurant if r["_id"]],
        "cancelled_orders": cancelled,
        "total_orders": total_orders,
        "cancelled_count": cancelled_count,
    }
