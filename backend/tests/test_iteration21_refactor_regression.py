"""Iteration 21 regression tests for seed, schedules helper flow, zones update, and role auth smoke."""

from datetime import date, timedelta

import pytest
import requests

from _settings import BASE_URL, admin_credentials, driver_credentials, login_session, restaurant_credentials


def _current_monday_iso() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def _login_session(credentials: dict[str, str]) -> tuple[requests.Session, dict]:
    return login_session(credentials, timeout=20)


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    """Auth module: authenticated admin session for protected endpoints."""
    session, payload = _login_session(admin_credentials())
    assert payload.get("user", {}).get("role") == "admin"
    return session


def test_seed_endpoint_creates_100_orders(admin_session: requests.Session):
    """Seed module: /api/seed should rebuild dataset and create 100 orders."""
    seed_response = admin_session.post(f"{BASE_URL}/api/seed", timeout=40)
    assert seed_response.status_code == 200
    seed_data = seed_response.json()
    assert seed_data.get("data", {}).get("orders") >= 100
    assert seed_data.get("data", {}).get("demo_routes") == 3

    orders_response = admin_session.get(f"{BASE_URL}/api/orders", timeout=20)
    assert orders_response.status_code == 200
    orders = orders_response.json()
    assert isinstance(orders, list)
    assert len(orders) >= 100


def test_restaurant_analytics_hour_buckets(admin_session: requests.Session):
    """Restaurant analytics module: by_hour chart should keep 24 buckets."""
    response = admin_session.get(f"{BASE_URL}/api/restaurants/rest-001/analytics", timeout=20)
    assert response.status_code == 200
    data = response.json()

    assert isinstance(data.get("summary"), dict)
    assert isinstance(data.get("charts"), dict)
    by_hour = data["charts"].get("by_hour")
    assert isinstance(by_hour, list)
    assert len(by_hour) == 24
    assert all("label" in item and "count" in item for item in by_hour)


def test_schedule_auto_generate_and_bulk_delete(admin_session: requests.Session):
    """Schedules module: /admin/auto-generate then /admin/bulk-delete should both succeed."""
    week_start = _current_monday_iso()

    generate_response = admin_session.post(
        f"{BASE_URL}/api/schedules/admin/auto-generate",
        json={
            "week_start": week_start,
            "days": ["monday"],
            "start_hour": "10:00",
            "end_hour": "12:00",
            "total_slots": 1,
            "repeat_weeks": 1,
        },
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


def test_zones_update_payload_persists_changes(admin_session: requests.Session):
    """Zones module: zone update should persist scalar field edits and allow restore."""
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
    updated_name = f"{original_name}-iter21"
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


def test_restaurant_and_driver_auth_smoke():
    """Auth module: restaurant and driver credentials should login and return correct roles."""
    driver_session, driver_payload = _login_session(driver_credentials())
    assert driver_payload.get("user", {}).get("role") == "driver"

    driver_me = driver_session.get(f"{BASE_URL}/api/auth/me", timeout=20)
    assert driver_me.status_code == 200
    assert driver_me.json().get("role") == "driver"

    rest_session, rest_payload = _login_session(restaurant_credentials())
    assert rest_payload.get("user", {}).get("role") == "restaurant"

    rest_me = rest_session.get(f"{BASE_URL}/api/auth/me", timeout=20)
    assert rest_me.status_code == 200
    assert rest_me.json().get("role") == "restaurant"
