from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


ROMANIA_TZ = ZoneInfo("Europe/Bucharest")

TIER_CONFIG = [
    {"key": "gold", "label": "Gold", "min_score": 80, "opens": {"weekday": 6, "hour": 22}},
    {"key": "silver", "label": "Silver", "min_score": 60, "opens": {"weekday": 0, "hour": 2}},
    {"key": "bronze", "label": "Bronze", "min_score": 40, "opens": {"weekday": 0, "hour": 6}},
    {"key": "start", "label": "Start", "min_score": 0, "opens": {"weekday": 0, "hour": 8}},
]

CLOSE_HOUR = 10


def _safe_parse_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def calculate_driver_score(driver: dict, cancelled_by_driver: int):
    total_deliveries = int(driver.get("total_deliveries", 0) or 0)
    punctuality_rate = float(driver.get("punctuality_rate", 0.85) or 0.85)
    handled_orders = max(total_deliveries + cancelled_by_driver, 1)
    cancellation_rate = cancelled_by_driver / handled_orders

    joined_at = _safe_parse_iso(driver.get("joined_at"))
    if joined_at is None:
        joined_at = datetime.now(tz=ROMANIA_TZ) - timedelta(days=30)
    if joined_at.tzinfo is None:
        joined_at = joined_at.replace(tzinfo=ROMANIA_TZ)
    joined_at_local = joined_at.astimezone(ROMANIA_TZ)
    seniority_months = max((datetime.now(tz=ROMANIA_TZ) - joined_at_local).days / 30, 0)

    deliveries_score = min(total_deliveries / 150, 1) * 45
    cancellation_score = max(0, 1 - min(cancellation_rate, 0.3) / 0.3) * 25
    punctuality_score = max(0, min(punctuality_rate, 1)) * 15
    seniority_score = min(seniority_months / 24, 1) * 15

    total_score = round(deliveries_score + cancellation_score + punctuality_score + seniority_score, 1)
    return {
        "score": total_score,
        "breakdown": {
            "deliveries": round(deliveries_score, 1),
            "cancellations": round(cancellation_score, 1),
            "punctuality": round(punctuality_score, 1),
            "seniority": round(seniority_score, 1),
        },
        "metrics": {
            "total_deliveries": total_deliveries,
            "cancelled_by_driver": cancelled_by_driver,
            "cancellation_rate": round(cancellation_rate, 3),
            "punctuality_rate": round(punctuality_rate, 3),
            "seniority_months": round(seniority_months, 1),
        },
    }


def _normalise_manual_score(value):
    if value is None or value == "":
        return None
    try:
        return round(max(0, min(float(value), 100)), 1)
    except (TypeError, ValueError):
        return None


def get_tier_for_score(score: float):
    for tier in TIER_CONFIG:
        if score >= tier["min_score"]:
            return tier
    return TIER_CONFIG[-1]


def get_next_tier_for_score(score: float):
    ascending = sorted(TIER_CONFIG, key=lambda item: item["min_score"])
    for tier in ascending:
        if score < tier["min_score"]:
            return tier
    return None


def _build_cycle_window(now_local: datetime):
    weekday = now_local.weekday()
    if (weekday == 6 and now_local.hour >= 22) or (weekday == 0 and now_local.hour < CLOSE_HOUR):
        monday_date = now_local.date() + timedelta(days=(7 - weekday) % 7)
    else:
        days_ahead = (7 - weekday) % 7
        if days_ahead == 0:
            days_ahead = 7
        monday_date = now_local.date() + timedelta(days=days_ahead)

    monday_start = datetime.combine(monday_date, datetime.min.time(), tzinfo=ROMANIA_TZ)
    sunday_start = monday_start - timedelta(days=1)
    close_at = monday_start.replace(hour=CLOSE_HOUR)
    return sunday_start, monday_start, close_at


def build_tier_access_state(tier_key: str):
    now_local = datetime.now(tz=ROMANIA_TZ)
    sunday_start, monday_start, close_at = _build_cycle_window(now_local)
    tier = next((item for item in TIER_CONFIG if item["key"] == tier_key), TIER_CONFIG[-1])
    opens_at = (sunday_start if tier["opens"]["weekday"] == 6 else monday_start).replace(hour=tier["opens"]["hour"])
    can_select_schedule = opens_at <= now_local < close_at

    next_open_at = opens_at
    if now_local >= close_at:
        next_sunday = sunday_start + timedelta(days=7)
        next_monday = monday_start + timedelta(days=7)
        next_open_at = (next_sunday if tier["opens"]["weekday"] == 6 else next_monday).replace(hour=tier["opens"]["hour"])

    fmt = "%a %H:%M"
    return {
        "tier_key": tier["key"],
        "tier_label": tier["label"],
        "can_select_schedule": can_select_schedule,
        "opens_at": opens_at.isoformat(),
        "opens_at_label": opens_at.strftime(fmt),
        "closes_at": close_at.isoformat(),
        "closes_at_label": close_at.strftime(fmt),
        "next_open_at": next_open_at.isoformat(),
        "next_open_at_label": next_open_at.strftime(fmt),
        "current_local_time": now_local.isoformat(),
    }


async def build_driver_ranking_payload(db, driver: dict):
    cancelled_by_driver = await db.orders.count_documents({
        "driver_id": driver["id"],
        "status": "CANCELLED",
        "cancelled_by": "driver",
    })
    ranking = calculate_driver_score(driver, cancelled_by_driver)
    base_score = ranking["score"]
    manual_score = _normalise_manual_score(driver.get("manual_ranking_score"))
    final_score = manual_score if manual_score is not None else base_score
    manual_delta = round(final_score - base_score, 1)
    tier = get_tier_for_score(final_score)
    next_tier = get_next_tier_for_score(final_score)
    access = build_tier_access_state(tier["key"])
    return {
        "ranking_score": final_score,
        "ranking_base_score": base_score,
        "manual_ranking_score": manual_score,
        "manual_rank_note": driver.get("manual_rank_note"),
        "manual_rank_updated_at": driver.get("manual_rank_updated_at"),
        "ranking_tier": tier["label"],
        "ranking_tier_key": tier["key"],
        "ranking_breakdown": {**ranking["breakdown"], "manual": manual_delta},
        "ranking_metrics": {**ranking["metrics"], "base_score": base_score, "has_manual_override": manual_score is not None},
        "next_tier": next_tier,
        "points_to_next_tier": round(max((next_tier or {}).get("min_score", final_score) - final_score, 0), 1),
        "schedule_access": access,
    }
