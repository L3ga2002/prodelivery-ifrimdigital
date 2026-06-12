from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from pymongo import ReturnDocument
from database import db
from auth import get_current_user
from models.emergency_slot import EmergencySlotCreate, EmergencySlot

router = APIRouter(prefix="/schedules/emergency", tags=["emergency-slots"])

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
PEAK_HOURS = ["12:00", "13:00", "19:00", "20:00", "21:00"]


def _extract_hour_from_created_at(created_at):
    if not created_at:
        return None
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return None
    return f"{created_at.hour:02d}:00"


def _required_emergency_spots(hourly_orders: int, scheduled_coverage: int):
    if hourly_orders >= 30:
        target = 4
    elif hourly_orders >= 22:
        target = 3
    elif hourly_orders >= 15:
        target = 2
    elif hourly_orders >= 10:
        target = 1
    else:
        target = 0
    return max(target - scheduled_coverage, 0)


def _allowed_emergency_hours() -> list[str]:
    return [f"{h:02d}:00" for h in range(10, 22)]


def _parse_emergency_hour_range(start_hour: str, end_hour: str) -> list[str]:
    start = int(start_hour.split(":")[0])
    end = int(end_hour.split(":")[0])
    hours: list[str] = []
    current = start
    while current != end:
        hour = f"{current:02d}:00"
        if hour not in _allowed_emergency_hours():
            raise HTTPException(status_code=400, detail="Sloturile de urgență sunt doar între 10:00-22:00")
        hours.append(hour)
        current = (current + 1) % 24
        if len(hours) > 24:
            raise HTTPException(status_code=400, detail="Interval invalid")
    return hours


def _validate_days(days: list[str]) -> None:
    if any(day not in DAYS for day in days):
        raise HTTPException(status_code=400, detail="Zi invalidă")


def _build_bulk_delete_query(week_start: str, days: list[str], hours: list[str], created_by: str) -> dict:
    query = {"week_start": week_start, "day": {"$in": days}, "hour": {"$in": hours}}
    if created_by != "all":
        query["created_by"] = created_by
    return query


async def _cleanup_schedule_emergency_slots(week_start: str, slot_hours: set[tuple[str, str]]) -> tuple[int, int]:
    schedules = await db.schedules.find({"week_start": week_start}, {"_id": 0}).to_list(500)
    cleaned_schedules = 0
    removed_schedule_slots = 0
    for schedule in schedules:
        schedule_slots = schedule.get("slots", {})
        changed = False
        for day, day_slots in list(schedule_slots.items()):
            filtered = [slot for slot in day_slots if not (slot.get("added_by") == "emergency" and (day, slot.get("start")) in slot_hours)]
            removed_schedule_slots += len(day_slots) - len(filtered)
            if len(filtered) != len(day_slots):
                schedule_slots[day] = filtered
                changed = True
        if changed:
            await db.schedules.update_one(
                {"id": schedule["id"]},
                {"$set": {"slots": schedule_slots, "total_hours": sum(len(items) for items in schedule_slots.values())}},
            )
            cleaned_schedules += 1
    return cleaned_schedules, removed_schedule_slots


def _validate_manual_slot(data: EmergencySlotCreate) -> None:
    if data.total_spots < 1:
        raise HTTPException(status_code=400, detail="Minimum 1 loc")
    if data.hour not in _allowed_emergency_hours():
        raise HTTPException(status_code=400, detail="Sloturile de urgență sunt doar între 10:00-22:00")


def _build_hourly_demand(orders: list[dict]) -> dict[str, int]:
    hourly_demand = {hour: 0 for hour in PEAK_HOURS}
    for order in orders:
        hour = _extract_hour_from_created_at(order.get("created_at"))
        if hour in hourly_demand:
            hourly_demand[hour] += 1

    fallback_demand = {"12:00": 18, "13:00": 15, "19:00": 20, "20:00": 28, "21:00": 19}
    for hour in PEAK_HOURS:
        if hourly_demand[hour] == 0:
            hourly_demand[hour] = fallback_demand[hour]
    return hourly_demand


def _build_coverage_map(schedules: list[dict]) -> dict[tuple[str, str], int]:
    coverage = {(day, hour): 0 for day in DAYS for hour in PEAK_HOURS}
    for schedule in schedules:
        for day, slots in (schedule.get("slots") or {}).items():
            for slot in slots:
                hour = slot.get("start")
                if (day, hour) in coverage:
                    coverage[(day, hour)] += 1
    return coverage


async def _apply_auto_slot_update(week_start: str, day: str, hour: str, required_spots: int, existing_slot: dict | None):
    if existing_slot:
        if existing_slot.get("created_by") == "admin":
            return None
        claimed_count = len(existing_slot.get("claimed_by", []))
        total_spots = max(required_spots, claimed_count)
        remaining_spots = max(total_spots - claimed_count, 0)
        await db.emergency_slots.update_one(
            {"id": existing_slot["id"]},
            {"$set": {"total_spots": total_spots, "remaining_spots": remaining_spots, "created_by": "system"}},
        )
        return {"day": day, "hour": hour, "spots": total_spots, "mode": "updated"}

    slot = EmergencySlot(
        week_start=week_start,
        day=day,
        hour=hour,
        total_spots=required_spots,
        remaining_spots=required_spots,
        created_by="system",
    )
    await db.emergency_slots.insert_one(slot.model_dump())
    return {"day": day, "hour": hour, "spots": required_spots, "mode": "created"}


async def _load_claim_context(slot_id: str, current_user: dict) -> tuple[dict, dict, dict | None]:
    slot = await db.emergency_slots.find_one({"id": slot_id}, {"_id": 0})
    if not slot:
        raise HTTPException(status_code=404, detail="Slot negăsit")
    if slot["remaining_spots"] <= 0:
        raise HTTPException(status_code=400, detail="Nu mai sunt locuri disponibile")

    driver = await db.drivers.find_one({"user_id": current_user["user_id"]}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver negăsit")
    if driver["id"] in slot.get("claimed_by", []):
        raise HTTPException(status_code=400, detail="Ai luat deja acest slot")

    schedule = await db.schedules.find_one({
        "driver_id": driver["id"],
        "week_start": slot["week_start"]
    }, {"_id": 0})

    if schedule:
        day_slots = schedule.get("slots", {}).get(slot["day"], [])
        has_schedule = any(item["start"] == slot["hour"] for item in day_slots)
        if has_schedule:
            raise HTTPException(status_code=400, detail="Ai deja program la această oră")

    return slot, driver, schedule


async def _attach_emergency_slot_to_schedule(driver: dict, slot: dict, schedule: dict | None) -> bool:
    end_h = (int(slot["hour"].split(":")[0]) + 1) % 24
    emergency_slot_data = {
        "start": slot["hour"],
        "end": f"{end_h:02d}:00",
        "added_by": "emergency"
    }

    if schedule:
        day_key = f"slots.{slot['day']}"
        result = await db.schedules.update_one(
            {
                "driver_id": driver["id"],
                "week_start": slot["week_start"],
                f"{day_key}.start": {"$ne": slot["hour"]},
            },
            {"$push": {day_key: emergency_slot_data}, "$inc": {"total_hours": 1}}
        )
        return result.modified_count == 1

    from models.schedule import Schedule

    new_schedule = Schedule(
        driver_id=driver["id"],
        week_start=slot["week_start"],
        slots={slot["day"]: [emergency_slot_data]},
        total_hours=1.0
    )
    await db.schedules.insert_one(new_schedule.model_dump())
    return True


async def _rollback_emergency_slot_claim(slot_id: str, driver: dict) -> None:
    await db.emergency_slots.update_one(
        {"id": slot_id, "claimed_by": driver["id"]},
        {
            "$pull": {
                "claimed_by": driver["id"],
                "claimed_names": driver["name"],
            },
            "$inc": {"remaining_spots": 1},
        },
    )


@router.post("")
async def create_emergency_slot(data: EmergencySlotCreate, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    _validate_manual_slot(data)

    # Check if slot already exists for this day/hour/week
    existing = await db.emergency_slots.find_one({
        "week_start": data.week_start,
        "day": data.day,
        "hour": data.hour
    })

    if existing:
        # Update existing
        claimed_count = len(existing.get("claimed_by", []))
        total_spots = max(data.total_spots, claimed_count)
        await db.emergency_slots.update_one(
            {"week_start": data.week_start, "day": data.day, "hour": data.hour},
            {"$set": {
                "total_spots": total_spots,
                "remaining_spots": max(total_spots - claimed_count, 0)
            }}
        )
        return {"message": "Slot urgență actualizat", "total_spots": total_spots}

    slot = EmergencySlot(
        week_start=data.week_start,
        day=data.day,
        hour=data.hour,
        total_spots=data.total_spots,
        remaining_spots=data.total_spots,
    )
    doc = slot.model_dump()
    await db.emergency_slots.insert_one(doc)
    return {"message": "Slot urgență creat", "id": slot.id, "total_spots": data.total_spots}


@router.get("")
async def get_emergency_slots(week_start: str, current_user: dict = Depends(get_current_user)):
    slots = await db.emergency_slots.find(
        {"week_start": week_start},
        {"_id": 0}
    ).to_list(200)
    return slots


@router.post("/auto-generate")
async def auto_generate_emergency_slots(week_start: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    schedules = await db.schedules.find({"week_start": week_start}, {"_id": 0}).to_list(500)
    orders = await db.orders.find({}, {"_id": 0, "created_at": 1}).to_list(1000)

    hourly_demand = _build_hourly_demand(orders)
    coverage = _build_coverage_map(schedules)

    created = 0
    updated = 0
    touched_slots = []
    existing_slots = await db.emergency_slots.find({"week_start": week_start}, {"_id": 0}).to_list(500)
    existing_map = {(slot["day"], slot["hour"]): slot for slot in existing_slots}

    for day in DAYS:
        for hour in PEAK_HOURS:
            required_spots = _required_emergency_spots(hourly_demand[hour], coverage[(day, hour)])
            if required_spots <= 0:
                continue

            touched_slot = await _apply_auto_slot_update(week_start, day, hour, required_spots, existing_map.get((day, hour)))
            if not touched_slot:
                continue
            touched_slots.append(touched_slot)
            if touched_slot["mode"] == "updated":
                updated += 1
            else:
                created += 1

    return {
        "message": f"Auto-generator complet: {created} create, {updated} actualizate",
        "created": created,
        "updated": updated,
        "hourly_demand": hourly_demand,
        "slots": touched_slots,
    }


@router.post("/setup-generate")
async def setup_generate_emergency_slots(payload: dict, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    week_start = payload.get("week_start")
    days = payload.get("days") or []
    start_hour = payload.get("start_hour")
    end_hour = payload.get("end_hour")
    total_spots = int(payload.get("total_slots") or 0)
    if not week_start or not days or total_spots < 1:
        raise HTTPException(status_code=400, detail="Setări invalide")
    _validate_days(days)
    hours = _parse_emergency_hour_range(start_hour, end_hour)

    created = 0
    updated = 0
    for day in days:
        for hour in hours:
            existing = await db.emergency_slots.find_one({"week_start": week_start, "day": day, "hour": hour})
            if existing:
                claimed_count = len(existing.get("claimed_by", []))
                await db.emergency_slots.update_one(
                    {"week_start": week_start, "day": day, "hour": hour},
                    {"$set": {"total_spots": total_spots, "remaining_spots": max(total_spots - claimed_count, 0), "created_by": "system"}},
                )
                updated += 1
                continue
            slot = EmergencySlot(week_start=week_start, day=day, hour=hour, total_spots=total_spots, remaining_spots=total_spots, created_by="system")
            await db.emergency_slots.insert_one(slot.model_dump())
            created += 1
    return {"message": f"Sloturi generate: {created} create, {updated} actualizate", "created": created, "updated": updated}


@router.post("/bulk-delete")
async def bulk_delete_emergency_slots(payload: dict, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    week_start = payload.get("week_start")
    days = payload.get("days") or []
    start_hour = payload.get("start_hour")
    end_hour = payload.get("end_hour")
    created_by = payload.get("created_by", "system")
    if not week_start or not days or not start_hour or not end_hour:
        raise HTTPException(status_code=400, detail="Setări invalide")

    _validate_days(days)
    hours = _parse_emergency_hour_range(start_hour, end_hour)
    query = _build_bulk_delete_query(week_start, days, hours, created_by)

    slots = await db.emergency_slots.find(query, {"_id": 0}).to_list(500)
    slot_hours = {(slot["day"], slot["hour"]) for slot in slots}
    result = await db.emergency_slots.delete_many(query)

    cleaned_schedules, removed_schedule_slots = await _cleanup_schedule_emergency_slots(week_start, slot_hours)

    return {
        "message": f"Ștergere urgențe completă: {result.deleted_count} sloturi eliminate",
        "deleted_slots": result.deleted_count,
        "cleaned_schedules": cleaned_schedules,
        "removed_schedule_slots": removed_schedule_slots,
    }


@router.post("/{slot_id}/claim")
async def claim_emergency_slot(slot_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "driver":
        raise HTTPException(status_code=403, detail="Doar livratorul poate lua sloturi")

    slot, driver, schedule = await _load_claim_context(slot_id, current_user)

    claimed_slot = await db.emergency_slots.find_one_and_update(
        {
            "id": slot_id,
            "remaining_spots": {"$gt": 0},
            "claimed_by": {"$ne": driver["id"]},
        },
        {
            "$push": {
                "claimed_by": driver["id"],
                "claimed_names": driver["name"]
            },
            "$inc": {"remaining_spots": -1}
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )

    if not claimed_slot:
        current_slot = await db.emergency_slots.find_one({"id": slot_id}, {"_id": 0})
        if not current_slot:
            raise HTTPException(status_code=404, detail="Slot negăsit")
        if driver["id"] in current_slot.get("claimed_by", []):
            raise HTTPException(status_code=400, detail="Ai luat deja acest slot")
        if current_slot.get("remaining_spots", 0) <= 0:
            raise HTTPException(status_code=400, detail="Nu mai sunt locuri disponibile")
        raise HTTPException(status_code=409, detail="Slotul a fost modificat. Reîncarcă și încearcă din nou.")

    attached = await _attach_emergency_slot_to_schedule(driver, claimed_slot, schedule)
    if not attached:
        await _rollback_emergency_slot_claim(slot_id, driver)
        raise HTTPException(status_code=400, detail="Ai deja program la această oră")

    return {
        "message": f"Slot de urgență luat! Rămân {claimed_slot['remaining_spots']} locuri",
        "remaining_spots": claimed_slot["remaining_spots"]
    }


@router.delete("/{slot_id}")
async def delete_emergency_slot(slot_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    result = await db.emergency_slots.delete_one({"id": slot_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Slot negăsit")
    return {"message": "Slot urgență șters"}
