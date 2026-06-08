"""Regression tests for emergency setup/bulk-delete admin flow."""

from datetime import date, timedelta

import pytest
import requests
from _settings import admin_credentials


def _current_monday_iso() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


@pytest.fixture(scope="session")
def base_url() -> str:
    value = os.environ.get("REACT_APP_BACKEND_URL")
    if not value:
        pytest.skip("Missing REACT_APP_BACKEND_URL")
    return value.rstrip("/")


@pytest.fixture(scope="session")
def admin_session(base_url: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    login_res = session.post(
        f"{base_url}/api/auth/login",
        json=admin_credentials(),
        timeout=20,
    )
    assert login_res.status_code == 200

    payload = login_res.json()
    assert payload.get("user", {}).get("role") == "admin"
    token = payload.get("token")
    assert isinstance(token, str) and len(token) > 0
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


def test_emergency_setup_bulk_delete_returns_deleted_slots_and_persists(base_url: str, admin_session: requests.Session):
    """Emergency slots module: setup-generate -> bulk-delete -> GET verification."""
    week_start = _current_monday_iso()
    target_day = "monday"
    target_hours = {"12:00", "13:00"}

    setup_res = admin_session.post(
        f"{base_url}/api/schedules/emergency/setup-generate",
        json={
            "week_start": week_start,
            "days": [target_day],
            "start_hour": "12:00",
            "end_hour": "14:00",
            "total_slots": 2,
            "slot_type": "emergency",
            "repeat_weeks": 1,
        },
        timeout=20,
    )
    assert setup_res.status_code == 200
    setup_data = setup_res.json()
    assert setup_data.get("created", 0) + setup_data.get("updated", 0) >= 1

    list_before_res = admin_session.get(
        f"{base_url}/api/schedules/emergency",
        params={"week_start": week_start},
        timeout=20,
    )
    assert list_before_res.status_code == 200
    slots_before = list_before_res.json()

    matching_before = [
        slot for slot in slots_before
        if slot.get("day") == target_day and slot.get("hour") in target_hours and slot.get("created_by") == "system"
    ]
    assert len(matching_before) >= 1

    delete_res = admin_session.post(
        f"{base_url}/api/schedules/emergency/bulk-delete",
        json={
            "week_start": week_start,
            "days": [target_day],
            "start_hour": "12:00",
            "end_hour": "14:00",
            "created_by": "system",
        },
        timeout=20,
    )
    assert delete_res.status_code == 200
    delete_data = delete_res.json()
    assert isinstance(delete_data.get("deleted_slots"), int)
    assert delete_data["deleted_slots"] >= 1
    assert isinstance(delete_data.get("cleaned_schedules"), int)
    assert isinstance(delete_data.get("removed_schedule_slots"), int)

    list_after_res = admin_session.get(
        f"{base_url}/api/schedules/emergency",
        params={"week_start": week_start},
        timeout=20,
    )
    assert list_after_res.status_code == 200
    slots_after = list_after_res.json()

    matching_after = [
        slot for slot in slots_after
        if slot.get("day") == target_day and slot.get("hour") in target_hours and slot.get("created_by") == "system"
    ]
    assert len(matching_after) == 0
