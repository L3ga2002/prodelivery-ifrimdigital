"""Regression tests for refactored restaurant analytics and emergency slot helpers."""

from datetime import date, timedelta

import pytest
import requests

from _settings import BASE_URL, admin_credentials


def _current_monday_iso() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    """Auth module: create admin session for protected endpoints."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    response = session.post(
        f"{BASE_URL}/api/auth/login",
        json=admin_credentials(),
        timeout=20,
    )
    assert response.status_code == 200
    payload = response.json()
    token = payload.get("token")
    assert isinstance(token, str) and len(token) > 0
    assert payload.get("user", {}).get("role") == "admin"

    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


def test_restaurant_analytics_shape_for_rest_001(admin_session: requests.Session):
    """Restaurant analytics module: verify summary/charts/recent_orders payload shape."""
    response = admin_session.get(
        f"{BASE_URL}/api/restaurants/rest-001/analytics",
        timeout=20,
    )

    assert response.status_code == 200
    data = response.json()

    assert isinstance(data.get("summary"), dict)
    assert isinstance(data.get("charts"), dict)
    assert isinstance(data.get("recent_orders"), list)

    summary = data["summary"]
    assert "total_orders" in summary
    assert "avg_preparation_actual_minutes" in summary
    assert "avg_delivery_minutes" in summary

    charts = data["charts"]
    assert isinstance(charts.get("by_hour"), list)
    assert len(charts["by_hour"]) == 24
    assert all("label" in item and "count" in item for item in charts["by_hour"])


def test_emergency_setup_generate_and_bulk_delete_persist(admin_session: requests.Session):
    """Emergency slots module: setup-generate then bulk-delete then GET verification."""
    week_start = _current_monday_iso()
    target_day = "monday"
    target_hours = {"12:00", "13:00"}

    setup_response = admin_session.post(
        f"{BASE_URL}/api/schedules/emergency/setup-generate",
        json={
            "week_start": week_start,
            "days": [target_day],
            "start_hour": "12:00",
            "end_hour": "14:00",
            "total_slots": 2,
        },
        timeout=20,
    )
    assert setup_response.status_code == 200
    setup_data = setup_response.json()
    assert setup_data.get("created", 0) + setup_data.get("updated", 0) >= 1

    before_response = admin_session.get(
        f"{BASE_URL}/api/schedules/emergency",
        params={"week_start": week_start},
        timeout=20,
    )
    assert before_response.status_code == 200
    slots_before = before_response.json()
    matches_before = [
        slot
        for slot in slots_before
        if slot.get("day") == target_day
        and slot.get("hour") in target_hours
        and slot.get("created_by") == "system"
    ]
    assert len(matches_before) >= 1

    delete_response = admin_session.post(
        f"{BASE_URL}/api/schedules/emergency/bulk-delete",
        json={
            "week_start": week_start,
            "days": [target_day],
            "start_hour": "12:00",
            "end_hour": "14:00",
            "created_by": "system",
        },
        timeout=20,
    )
    assert delete_response.status_code == 200
    delete_data = delete_response.json()
    assert isinstance(delete_data.get("deleted_slots"), int)
    assert delete_data["deleted_slots"] >= 1

    after_response = admin_session.get(
        f"{BASE_URL}/api/schedules/emergency",
        params={"week_start": week_start},
        timeout=20,
    )
    assert after_response.status_code == 200
    slots_after = after_response.json()
    matches_after = [
        slot
        for slot in slots_after
        if slot.get("day") == target_day
        and slot.get("hour") in target_hours
        and slot.get("created_by") == "system"
    ]
    assert len(matches_after) == 0
