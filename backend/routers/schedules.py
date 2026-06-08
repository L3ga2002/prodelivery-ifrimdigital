from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timedelta, timezone
from database import db
from auth import get_current_user
from models.schedule import AutoGenerateScheduleRequest, BulkDeleteScheduleRequest, ClonePreviousWeekRequest, QuickAdjustScheduleRequest, ScheduleCreate, ScheduleUpdate, Schedule
from utils.driver_ranking import build_driver_ranking_payload, build_tier_access_state, ROMANIA_TZ

router = APIRouter(prefix="/schedules", tags=["schedules"])

# Driver can only set hours 10:00-22:00
DRIVER_ALLOWED_HOURS = [f"{h:02d}:00" for h in range(10, 22)]
# Admin can set all hours 10:00-02:00
ADMIN_ALLOWED_HOURS = [f"{h:02d}:00" for h in list(range(10, 24)) + [0, 1]]
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def calc_total_hours(slots: dict) -> float:
    total = 0.0
    for day, time_slots in slots.items():
        total += len(time_slots)
    return round(total, 2)


def validate_driver_slots(slots: dict):
    """Ensure driver only sets hours within 10:00-22:00"""
    for day, time_slots in slots.items():
        for slot in time_slots:
            if slot.get("added_by") == "admin":
                continue
            if slot["start"] not in DRIVER_ALLOWED_HOURS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Livratorii pot selecta ore doar între 10:00-22:00. Ora {slot['start']} nu este permisă."
                )


async def ensure_schedule_access(current_user: dict, driver_id: str) -> bool:
    is_admin = current_user["role"] == "admin"
    if current_user["role"] == "driver":
        driver = await db.drivers.find_one({"user_id": current_user["user_id"]}, {"_id": 0})
        if not driver or driver["id"] != driver_id:
            raise HTTPException(status_code=403, detail="Cannot edit another driver's schedule")
        ranking = await build_driver_ranking_payload(db, driver)
        if not ranking["schedule_access"]["can_select_schedule"]:
            raise HTTPException(
                status_code=403,
                detail=f"Calendarul se deschide pentru tier-ul {ranking['ranking_tier']} la {ranking['schedule_access']['opens_at']}"
            )
        return False
    if not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    return True


def serialize_slots(slot_groups: dict) -> dict:
    return {day: [slot.model_dump() for slot in slots] for day, slots in slot_groups.items()}


def merge_driver_slots(existing_schedule: dict | None, submitted_slots: dict) -> dict:
    if not existing_schedule or not existing_schedule.get("slots"):
        return submitted_slots

    merged_slots = {day: list(slots) for day, slots in submitted_slots.items()}
    for day, current_slots in existing_schedule["slots"].items():
        admin_slots = [slot for slot in current_slots if slot.get("added_by") == "admin"]
        driver_slots = [slot for slot in merged_slots.get(day, []) if slot.get("added_by") != "admin"]
        merged_slots[day] = driver_slots + admin_slots
    return merged_slots


def tag_admin_slots(slots_dict: dict, source: str) -> None:
    for day, slots in slots_dict.items():
        for slot in slots:
            if "added_by" not in slot:
                slot["added_by"] = source


def _hour_range(start_hour: str, end_hour: str) -> list[str]:
    start = int(start_hour.split(":")[0])
    end = int(end_hour.split(":")[0])
    hours = []
    current = start
    while current != end:
        value = f"{current:02d}:00"
        if value not in ADMIN_ALLOWED_HOURS:
            raise HTTPException(status_code=400, detail=f"Ora {value} nu este permisă pentru program")
        hours.append(value)
        current = (current + 1) % 24
        if len(hours) > 24:
            raise HTTPException(status_code=400, detail="Interval orar invalid")
    return hours


def _slot_end(hour: str) -> str:
    end_h = (int(hour.split(":")[0]) + 1) % 24
    return f"{end_h:02d}:00"


def _week_offset(week_start: str, offset: int) -> str:
    start = datetime.fromisoformat(week_start)
    return (start + timedelta(days=offset * 7)).date().isoformat()


def _copy_slots(slots: dict) -> dict:
    return {day: [dict(slot) for slot in day_slots] for day, day_slots in (slots or {}).items()}


def _validate_auto_generate_request(data: AutoGenerateScheduleRequest) -> None:
    if data.total_slots < 1:
        raise HTTPException(status_code=400, detail="Minimum 1 slot")
    if not data.days or any(day not in DAYS for day in data.days):
        raise HTTPException(status_code=400, detail="Zile invalide")


def _selected_drivers_for_hour(drivers: list[dict], hour_index: int, total_slots: int) -> list[dict]:
    count = min(total_slots, len(drivers))
    return [drivers[(hour_index + idx) % len(drivers)] for idx in range(count)]


async def _upsert_generated_slot(driver: dict, target_week: str, day: str, hour: str) -> bool:
    schedule = await db.schedules.find_one({"driver_id": driver["id"], "week_start": target_week}, {"_id": 0})
    slots = schedule.get("slots", {}) if schedule else {}
    day_slots = slots.get(day, [])
    if any(slot.get("start") == hour for slot in day_slots):
        return False

    day_slots.append({"start": hour, "end": _slot_end(hour), "added_by": "auto"})
    slots[day] = day_slots
    total_hours = calc_total_hours(slots)
    if schedule:
        await db.schedules.update_one(
            {"driver_id": driver["id"], "week_start": target_week},
            {"$set": {"slots": slots, "total_hours": total_hours}},
        )
        return True

    doc = Schedule(driver_id=driver["id"], week_start=target_week, slots=slots, total_hours=total_hours).model_dump()
    await db.schedules.insert_one(doc)
    return True


async def _quick_add_standard_slot(data: QuickAdjustScheduleRequest) -> int:
    drivers = await db.drivers.find({}, {"_id": 0}).sort("name", 1).to_list(300)
    created = 0
    for driver in drivers:
        if created >= data.delta:
            break
        if await _upsert_generated_slot(driver, data.week_start, data.day, data.hour):
            created += 1
    return created


async def _quick_remove_standard_slot(data: QuickAdjustScheduleRequest) -> int:
    target_remove = abs(data.delta)
    schedules = await db.schedules.find({"week_start": data.week_start}, {"_id": 0}).to_list(500)
    removed = 0
    for schedule in schedules:
        if removed >= target_remove:
            break
        slots = schedule.get("slots", {})
        day_slots = slots.get(data.day, [])
        removable = [slot for slot in day_slots if slot.get("start") == data.hour and slot.get("added_by") in ["admin", "auto"]]
        if not removable:
            continue
        to_remove_here = min(len(removable), target_remove - removed)
        remaining_to_remove = to_remove_here
        next_day_slots = []
        for slot in day_slots:
            if remaining_to_remove > 0 and slot.get("start") == data.hour and slot.get("added_by") in ["admin", "auto"]:
                remaining_to_remove -= 1
                removed += 1
                continue
            next_day_slots.append(slot)
        slots[data.day] = next_day_slots
        await db.schedules.update_one(
            {"id": schedule["id"]},
            {"$set": {"slots": slots, "total_hours": calc_total_hours(slots)}},
        )
    return removed


async def _quick_adjust_emergency_slot(data: QuickAdjustScheduleRequest) -> dict:
    if data.hour not in DRIVER_ALLOWED_HOURS:
        raise HTTPException(status_code=400, detail="Urgențele se pot seta doar între 10:00-22:00")
    existing = await db.emergency_slots.find_one(
        {"week_start": data.week_start, "day": data.day, "hour": data.hour},
        {"_id": 0},
    )
    claimed_count = len((existing or {}).get("claimed_by", []))
    current_total = int((existing or {}).get("total_spots", 0))
    next_total = max(current_total + data.delta, claimed_count, 0)
    if next_total == 0 and existing:
        await db.emergency_slots.delete_one({"id": existing["id"]})
        return {"adjusted": -current_total, "total_spots": 0, "remaining_spots": 0}
    if next_total == 0:
        return {"adjusted": 0, "total_spots": 0, "remaining_spots": 0}
    remaining = max(next_total - claimed_count, 0)
    if existing:
        await db.emergency_slots.update_one(
            {"id": existing["id"]},
            {"$set": {"total_spots": next_total, "remaining_spots": remaining, "created_by": "admin"}},
        )
    else:
        from models.emergency_slot import EmergencySlot
        slot = EmergencySlot(week_start=data.week_start, day=data.day, hour=data.hour, total_spots=next_total, remaining_spots=remaining, created_by="admin")
        await db.emergency_slots.insert_one(slot.model_dump())
    return {"adjusted": next_total - current_total, "total_spots": next_total, "remaining_spots": remaining}


async def _generate_week_slots(data: AutoGenerateScheduleRequest, drivers: list[dict], hours: list[str], target_week: str) -> int:
    created = 0
    for day in data.days:
        for hour_index, hour in enumerate(hours):
            selected_drivers = _selected_drivers_for_hour(drivers, hour_index, data.total_slots)
            for driver in selected_drivers:
                if await _upsert_generated_slot(driver, target_week, day, hour):
                    created += 1
    return created


async def upsert_schedule_record(data: ScheduleCreate, slots_dict: dict, total_hours: float) -> dict:
    existing = await db.schedules.find_one(
        {"driver_id": data.driver_id, "week_start": data.week_start}
    )

    if existing:
        await db.schedules.update_one(
            {"driver_id": data.driver_id, "week_start": data.week_start},
            {"$set": {"slots": slots_dict, "total_hours": total_hours}}
        )
        return {"message": "Schedule updated", "total_hours": total_hours}

    schedule = Schedule(
        driver_id=data.driver_id,
        week_start=data.week_start,
        slots=slots_dict,
        total_hours=total_hours
    )
    doc = schedule.model_dump()
    await db.schedules.insert_one(doc)
    return {"message": "Schedule created", "id": schedule.id, "total_hours": total_hours}


async def build_driver_summary(driver: dict, week_start: str | None) -> dict:
    query = {"driver_id": driver["id"]}
    if week_start:
        query["week_start"] = week_start

    schedules = await db.schedules.find(query, {"_id": 0}).to_list(60)
    total_hours = sum(schedule.get("total_hours", 0) for schedule in schedules)
    orders_delivered = await db.orders.count_documents({"driver_id": driver["id"], "status": "DELIVERED"})

    by_restaurant = await db.orders.aggregate([
        {"$match": {"driver_id": driver["id"], "status": "DELIVERED"}},
        {"$group": {"_id": "$restaurant_name", "count": {"$sum": 1}}}
    ]).to_list(100)

    by_zone_raw = await db.orders.aggregate([
        {"$match": {"driver_id": driver["id"]}},
        {"$group": {"_id": "$zone", "count": {"$sum": 1}}}
    ]).to_list(100)

    orders_by_zone = {}
    for zone in by_zone_raw:
        zone_key = zone["_id"] if zone["_id"] else "Neatribuită"
        orders_by_zone[zone_key] = zone["count"]

    ranking = await build_driver_ranking_payload(db, driver)
    return {
        "driver_id": driver["id"],
        "driver_name": driver["name"],
        "phone": driver["phone"],
        "is_active": driver["is_active"],
        "total_hours_scheduled": total_hours,
        "total_orders_delivered": orders_delivered,
        "orders_by_restaurant": {item["_id"]: item["count"] for item in by_restaurant},
        "orders_by_zone": orders_by_zone,
        "schedules": schedules,
        "ranking_priority": ranking["ranking_tier"],
        "ranking_score": ranking["ranking_score"],
        "ranking_base_score": ranking["ranking_base_score"],
        "manual_ranking_score": ranking["manual_ranking_score"],
        "manual_rank_note": ranking["manual_rank_note"],
        "schedule_access": ranking["schedule_access"],
    }


@router.get("/driver/{driver_id}")
async def get_driver_schedules(driver_id: str, year: int = 2026, current_user: dict = Depends(get_current_user)):
    schedules = await db.schedules.find(
        {"driver_id": driver_id, "week_start": {"$regex": f"^{year}"}},
        {"_id": 0}
    ).to_list(60)
    return schedules


@router.post("")
async def create_or_update_schedule(data: ScheduleCreate, current_user: dict = Depends(get_current_user)):
    is_admin = await ensure_schedule_access(current_user, data.driver_id)

    source = "admin" if is_admin else "driver"
    slots_dict = serialize_slots(data.slots)

    if not is_admin:
        existing = await db.schedules.find_one(
            {"driver_id": data.driver_id, "week_start": data.week_start},
            {"_id": 0}
        )
        validate_driver_slots(slots_dict)
        slots_dict = merge_driver_slots(existing, slots_dict)
    else:
        tag_admin_slots(slots_dict, source)

    total_hours = calc_total_hours(slots_dict)
    return await upsert_schedule_record(data, slots_dict, total_hours)


@router.put("/{schedule_id}")
async def update_schedule(schedule_id: str, data: ScheduleUpdate, current_user: dict = Depends(get_current_user)):
    schedule = await db.schedules.find_one({"id": schedule_id}, {"_id": 0})
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if current_user["role"] == "driver":
        driver = await db.drivers.find_one({"user_id": current_user["user_id"]}, {"_id": 0})
        if not driver or driver["id"] != schedule["driver_id"]:
            raise HTTPException(status_code=403, detail="Not authorized")
    elif current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    slots_dict = {day: [s.model_dump() for s in slots] for day, slots in data.slots.items()}
    total_hours = calc_total_hours(slots_dict)

    await db.schedules.update_one(
        {"id": schedule_id},
        {"$set": {"slots": slots_dict, "total_hours": total_hours}}
    )
    return {"message": "Schedule updated", "total_hours": total_hours}


@router.get("/admin/summary")
async def get_admin_schedule_summary(week_start: str = None, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    drivers = await db.drivers.find({}, {"_id": 0}).to_list(100)
    return [await build_driver_summary(driver, week_start) for driver in drivers]


@router.post("/admin/auto-generate")
async def auto_generate_normal_slots(data: AutoGenerateScheduleRequest, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    _validate_auto_generate_request(data)

    hours = _hour_range(data.start_hour, data.end_hour)
    drivers = await db.drivers.find({"is_active": True}, {"_id": 0}).sort("name", 1).to_list(300)
    if not drivers:
        raise HTTPException(status_code=400, detail="Nu există livratori activi")

    touched = 0
    for repeat_index in range(max(data.repeat_weeks, 1)):
        target_week = _week_offset(data.week_start, repeat_index)
        touched += await _generate_week_slots(data, drivers, hours, target_week)

    return {"message": f"Generate normală completă: {touched} sloturi adăugate", "created_slots": touched}


@router.post("/admin/bulk-delete")
async def bulk_delete_generated_slots(data: BulkDeleteScheduleRequest, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    hours = set(_hour_range(data.start_hour, data.end_hour))
    schedules = await db.schedules.find({"week_start": data.week_start}, {"_id": 0}).to_list(500)
    removed = 0
    for schedule in schedules:
        slots = schedule.get("slots", {})
        changed = False
        for day in data.days:
            current_slots = slots.get(day, [])
            filtered = [slot for slot in current_slots if not (slot.get("added_by") == data.added_by and slot.get("start") in hours)]
            removed += len(current_slots) - len(filtered)
            if len(filtered) != len(current_slots):
                slots[day] = filtered
                changed = True
        if changed:
            await db.schedules.update_one(
                {"id": schedule["id"]},
                {"$set": {"slots": slots, "total_hours": calc_total_hours(slots)}},
            )
    return {"message": f"Ștergere bulk completă: {removed} sloturi eliminate", "deleted_slots": removed}


@router.post("/admin/quick-adjust")
async def quick_adjust_schedule_cell(data: QuickAdjustScheduleRequest, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if data.day not in DAYS:
        raise HTTPException(status_code=400, detail="Zi invalidă")
    if data.hour not in ADMIN_ALLOWED_HOURS:
        raise HTTPException(status_code=400, detail="Oră invalidă")
    if data.delta == 0 or abs(data.delta) > 100:
        raise HTTPException(status_code=400, detail="Ajustarea rapidă acceptă valori între -100 și +100")

    if data.slot_type == "emergency":
        result = await _quick_adjust_emergency_slot(data)
        return {"message": "Urgență ajustată rapid", "slot_type": "emergency", **result}

    adjusted = await _quick_add_standard_slot(data) if data.delta > 0 else await _quick_remove_standard_slot(data)
    return {
        "message": f"Sloturi standard ajustate: {adjusted}",
        "slot_type": "normal",
        "adjusted": adjusted,
        "requested_delta": data.delta,
    }


@router.post("/admin/clone-previous-week")
async def clone_previous_week_slots(data: ClonePreviousWeekRequest, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    previous_week = _week_offset(data.week_start, -1)
    previous_schedules = await db.schedules.find({"week_start": previous_week}, {"_id": 0}).to_list(500)
    total_hours = sum(schedule.get("total_hours", 0) for schedule in previous_schedules)
    preview = {
        "previous_week_start": previous_week,
        "target_week_start": data.week_start,
        "drivers_count": len(previous_schedules),
        "total_hours": total_hours,
    }
    if data.preview_only:
        return {"message": "Preview generat", "preview": preview}

    recreated = 0
    for previous in previous_schedules:
        slots = _copy_slots(previous.get("slots", {}))
        total = calc_total_hours(slots)
        existing = await db.schedules.find_one({"driver_id": previous["driver_id"], "week_start": data.week_start}, {"_id": 0})
        if existing:
            await db.schedules.update_one(
                {"id": existing["id"]},
                {"$set": {"slots": slots, "total_hours": total}},
            )
        else:
            doc = Schedule(driver_id=previous["driver_id"], week_start=data.week_start, slots=slots, total_hours=total).model_dump()
            await db.schedules.insert_one(doc)
        recreated += 1
    return {"message": f"Sloturile au fost refăcute pentru {recreated} livratori", "preview": preview, "recreated": recreated}


@router.get("/scheduling-window")
async def get_scheduling_window(current_user: dict = Depends(get_current_user)):
    now_local = datetime.now(ROMANIA_TZ)

    if current_user["role"] == "driver":
        driver = await db.drivers.find_one({"user_id": current_user["user_id"]}, {"_id": 0})
        if not driver:
            raise HTTPException(status_code=404, detail="Driver not found")
        ranking = await build_driver_ranking_payload(db, driver)
        access = ranking["schedule_access"]
        return {
            "is_open": access["can_select_schedule"],
            "can_select_schedule": access["can_select_schedule"],
            "tier": ranking["ranking_tier"],
            "tier_key": ranking["ranking_tier_key"],
            "score": ranking["ranking_score"],
            "breakdown": ranking["ranking_breakdown"],
            "metrics": ranking["ranking_metrics"],
            "next_tier": ranking["next_tier"],
            "points_to_next_tier": ranking["points_to_next_tier"],
            "opens_at": access["opens_at"],
            "opens_at_label": access["opens_at_label"],
            "closes_at": access["closes_at"],
            "closes_at_label": access["closes_at_label"],
            "next_open_at": access["next_open_at"],
            "next_open_at_label": access["next_open_at_label"],
            "current_local_time": access["current_local_time"],
        }

    global_access = build_tier_access_state("gold")
    return {
        "is_open": global_access["can_select_schedule"],
        "opens_at": global_access["opens_at"],
        "closes_at": global_access["closes_at"],
        "current_local_time": now_local.isoformat(),
    }
