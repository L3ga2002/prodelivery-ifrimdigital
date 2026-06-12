"""Regression tests for seed/orders, restaurant analytics, schedules helpers, and zones updates."""

from datetime import date, timedelta

import pytest
import requests

from _settings import BASE_URL, admin_credentials, login_session


def _current_monday_iso() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    """Auth module: create authenticated admin session for protected endpoints."""
    session, payload = login_session(admin_credentials(), timeout=20)
    assert payload.get("user", {}).get("role") == "admin"
    return session


def test_seed_endpoint_creates_100_orders(admin_session: requests.Session):
    """Seed module: verify /api/seed works and creates 100 orders."""
    seed_response = admin_session.post(f"{BASE_URL}/api/seed", timeout=30)
    assert seed_response.status_code == 200
    seed_data = seed_response.json()
    assert seed_data.get("data", {}).get("orders") >= 100
    assert seed_data.get("data", {}).get("demo_routes") == 3

    orders_response = admin_session.get(f"{BASE_URL}/api/orders", timeout=20)
    assert orders_response.status_code == 200
    orders = orders_response.json()
    assert isinstance(orders, list)
    assert len(orders) >= 100


def test_restaurant_analytics_payload_shape(admin_session: requests.Session):
    """Restaurant analytics module: validate summary/charts/recent_orders payload."""
    response = admin_session.get(
        f"{BASE_URL}/api/restaurants/rest-001/analytics",
        timeout=20,
    )

    assert response.status_code == 200
    data = response.json()

    assert isinstance(data.get("summary"), dict)
    assert isinstance(data.get("charts"), dict)
    assert isinstance(data.get("recent_orders"), list)

    assert "total_orders" in data["summary"]
    assert "avg_preparation_actual_minutes" in data["summary"]
    assert "avg_delivery_minutes" in data["summary"]

    assert isinstance(data["charts"].get("by_hour"), list)
    assert len(data["charts"]["by_hour"]) == 24
    assert all("label" in item and "count" in item for item in data["charts"]["by_hour"])


def test_schedule_auto_generate_and_bulk_delete(admin_session: requests.Session):
    """Schedules module: verify /admin/auto-generate and /admin/bulk-delete end-to-end."""
    week_start = _current_monday_iso()
    payload = {
        "week_start": week_start,
        "days": ["monday"],
        "start_hour": "10:00",
        "end_hour": "12:00",
        "total_slots": 1,
        "repeat_weeks": 1,
    }

    generate_response = admin_session.post(
        f"{BASE_URL}/api/schedules/admin/auto-generate",
        json=payload,
        timeout=30,
    )
    assert generate_response.status_code == 200
    generate_data = generate_response.json()
    assert isinstance(generate_data.get("created_slots"), int)
    assert generate_data["created_slots"] >= 1

    delete_response = admin_session.post(
        f"{BASE_URL}/api/schedules/admin/bulk-delete",
        json={
            "week_start": week_start,
            "days": ["monday"],
            "start_hour": "10:00",
            "end_hour": "12:00",
            "added_by": "auto",
        },
        timeout=30,
    )
    assert delete_response.status_code == 200
    delete_data = delete_response.json()
    assert isinstance(delete_data.get("deleted_slots"), int)
    assert delete_data["deleted_slots"] >= 1


def test_zones_update_payload_still_updates_zone(admin_session: requests.Session):
    """Zones module: verify zone update endpoint persists edited scalar fields."""
    zones_response = admin_session.get(
        f"{BASE_URL}/api/zones",
        params={"restaurant_id": "rest-001"},
        timeout=20,
    )
    assert zones_response.status_code == 200
    zones = zones_response.json()
    assert isinstance(zones, list)
    assert len(zones) >= 1

    zone = zones[0]
    zone_id = zone["id"]
    original_name = zone["name"]
    original_fee = float(zone["fee"])
    updated_name = f"{original_name} - iter20"
    updated_fee = round(original_fee + 0.5, 2)

    update_response = admin_session.put(
        f"{BASE_URL}/api/zones/{zone_id}",
        json={"name": updated_name, "fee": updated_fee, "confirm_protected_action": True},
        timeout=20,
    )
    assert update_response.status_code == 200
    updated_zone = update_response.json()
    assert updated_zone["id"] == zone_id
    assert updated_zone["name"] == updated_name
    assert float(updated_zone["fee"]) == updated_fee

    restore_response = admin_session.put(
        f"{BASE_URL}/api/zones/{zone_id}",
        json={"name": original_name, "fee": original_fee, "confirm_protected_action": True},
        timeout=20,
    )
    assert restore_response.status_code == 200
    restored_zone = restore_response.json()
    assert restored_zone["name"] == original_name
    assert float(restored_zone["fee"]) == original_fee
