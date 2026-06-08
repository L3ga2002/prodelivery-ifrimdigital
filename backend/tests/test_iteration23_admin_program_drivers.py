"""Iteration 23 regression for Admin Program calendar metrics and Admin Drivers management APIs."""

from datetime import date, timedelta
import uuid
import os

import pytest
import requests
from pymongo import MongoClient

from _settings import BASE_URL, admin_credentials, driver_credentials


def _current_monday_iso() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


def _login(session: requests.Session, creds: dict[str, str]) -> requests.Response:
    response = session.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    return response


def _clear_login_attempts(email: str) -> None:
    # Auth module: keep tests isolated by removing previous lockout records for target user.
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        return
    client = MongoClient(mongo_url)
    try:
        client[db_name]["login_attempts"].delete_many({"email": email})
    finally:
        client.close()


def _total_standard_slots(summary_payload: list, week_start: str) -> int:
    # Admin Program module: count standard slots (excluding emergency) from weekly summary payload.
    total = 0
    for driver in summary_payload:
        schedules = driver.get("schedules") or []
        current = next((sched for sched in schedules if sched.get("week_start") == week_start), None)
        if not current:
            continue
        slots = current.get("slots") or {}
        for day_slots in slots.values():
            total += sum(1 for slot in day_slots if slot.get("added_by") != "emergency")
    return total


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    # Auth module: bootstrap authenticated admin session for protected endpoints.
    _clear_login_attempts(admin_credentials()["email"])
    session = _new_session()
    login = _login(session, admin_credentials())
    assert login.status_code == 200, login.text
    token = login.json().get("token")
    assert isinstance(token, str) and len(token) > 0
    session.headers.update({"Authorization": f"Bearer {token}"})

    seed_response = session.post(f"{BASE_URL}/api/seed", timeout=45)
    assert seed_response.status_code == 200, seed_response.text
    return session


@pytest.fixture(scope="module")
def driver_session() -> requests.Session:
    # Auth module: non-admin session used for authorization rejection checks.
    _clear_login_attempts(driver_credentials()["email"])
    session = _new_session()
    login = _login(session, driver_credentials())
    assert login.status_code == 200, login.text
    token = login.json().get("token")
    assert isinstance(token, str) and len(token) > 0
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


def test_admin_login_sets_http_only_cookies():
    # Auth module: ensure login sets cookie-based session artifacts expected by frontend.
    _clear_login_attempts(admin_credentials()["email"])
    session = _new_session()
    response = _login(session, admin_credentials())
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
    assert "httponly" in set_cookie


def test_auth_cors_preflight_allows_explicit_origin_with_credentials():
    # Auth/CORS module: browser preflight should echo explicit origin when credentials are enabled.
    response = requests.options(
        f"{BASE_URL}/api/auth/login",
        headers={
            "Origin": BASE_URL,
            "Access-Control-Request-Method": "POST",
        },
        timeout=20,
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == BASE_URL
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_auth_lockout_after_five_failed_logins():
    # Auth hardening module: brute-force lockout should trigger after repeated failures.
    email = f"lockout-{uuid.uuid4().hex[:8]}@delivery.ro"
    _clear_login_attempts(email)
    for _ in range(5):
        failed = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "wrong-password"},
            timeout=20,
        )
        assert failed.status_code == 401

    locked = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": "wrong-password"},
        timeout=20,
    )
    assert locked.status_code in (423, 429), locked.text


def test_admin_password_hash_uses_bcrypt_2b_prefix(admin_session: requests.Session):
    # Auth playbook module: persisted admin password hash should use bcrypt $2b$ format.
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        pytest.skip("Missing MONGO_URL/DB_NAME for hash verification")

    client = MongoClient(mongo_url)
    try:
        admin_user = client[db_name]["users"].find_one({"email": admin_credentials()["email"]})
    finally:
        client.close()

    assert admin_user is not None
    password_hash = admin_user.get("password_hash", "")
    assert isinstance(password_hash, str)
    assert password_hash.startswith("$2b$")


def test_admin_program_summary_and_emergency_shape_for_calendar_metrics(admin_session: requests.Session):
    # Admin Program module: API payload should include slot metadata needed by quick calendar metrics.
    week_start = _current_monday_iso()
    summary_response = admin_session.get(
        f"{BASE_URL}/api/schedules/admin/summary",
        params={"week_start": week_start},
        timeout=30,
    )
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert isinstance(summary, list)
    assert len(summary) > 0

    first_driver = summary[0]
    assert "driver_id" in first_driver
    assert "driver_name" in first_driver
    assert "schedules" in first_driver

    emergency_response = admin_session.get(
        f"{BASE_URL}/api/schedules/emergency",
        params={"week_start": week_start},
        timeout=20,
    )
    assert emergency_response.status_code == 200
    emergency = emergency_response.json()
    assert isinstance(emergency, list)
    if emergency:
        sample = emergency[0]
        assert "day" in sample
        assert "hour" in sample
        assert "total_spots" in sample
        assert "remaining_spots" in sample


def test_standard_slot_generation_refreshes_summary_metrics(admin_session: requests.Session):
    # Admin Program module: creating standard slots should increase weekly standard slot totals.
    week_start = _current_monday_iso()
    before_response = admin_session.get(
        f"{BASE_URL}/api/schedules/admin/summary",
        params={"week_start": week_start},
        timeout=30,
    )
    assert before_response.status_code == 200
    before_total = _total_standard_slots(before_response.json(), week_start)

    cleanup_response = admin_session.post(
        f"{BASE_URL}/api/schedules/admin/bulk-delete",
        json={
            "week_start": week_start,
            "days": ["sunday"],
            "start_hour": "01:00",
            "end_hour": "02:00",
            "added_by": "auto",
        },
        timeout=30,
    )
    assert cleanup_response.status_code == 200

    generate_response = admin_session.post(
        f"{BASE_URL}/api/schedules/admin/auto-generate",
        json={
            "week_start": week_start,
            "days": ["sunday"],
            "start_hour": "01:00",
            "end_hour": "02:00",
            "total_slots": 1,
            "slot_type": "normal",
            "repeat_weeks": 1,
        },
        timeout=30,
    )
    assert generate_response.status_code == 200, generate_response.text
    created_slots = generate_response.json().get("created_slots", 0)
    assert created_slots >= 1

    after_response = admin_session.get(
        f"{BASE_URL}/api/schedules/admin/summary",
        params={"week_start": week_start},
        timeout=30,
    )
    assert after_response.status_code == 200
    after_total = _total_standard_slots(after_response.json(), week_start)
    assert after_total >= before_total + 1


def test_emergency_slot_create_and_fetch(admin_session: requests.Session):
    # Emergency slots module: creating emergency slot should be reflected in emergency listing.
    week_start = _current_monday_iso()
    create_response = admin_session.post(
        f"{BASE_URL}/api/schedules/emergency",
        json={
            "week_start": week_start,
            "day": "saturday",
            "hour": "11:00",
            "total_spots": 3,
        },
        timeout=30,
    )
    assert create_response.status_code == 200, create_response.text

    fetch_response = admin_session.get(
        f"{BASE_URL}/api/schedules/emergency",
        params={"week_start": week_start},
        timeout=30,
    )
    assert fetch_response.status_code == 200
    slots = fetch_response.json()
    target = next((item for item in slots if item.get("day") == "saturday" and item.get("hour") == "11:00"), None)
    assert target is not None
    assert target["total_spots"] == 3
    assert target["remaining_spots"] <= target["total_spots"]


def test_driver_ranking_patch_admin_updates_score_and_tier(admin_session: requests.Session):
    # Driver management module: admin can set manual score and receive updated ranking payload.
    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=20)
    assert drivers_response.status_code == 200
    drivers = drivers_response.json()
    assert len(drivers) > 0
    driver_id = drivers[0]["id"]

    patch_response = admin_session.patch(
        f"{BASE_URL}/api/drivers/{driver_id}/ranking",
        json={"manual_ranking_score": 88.5, "manual_rank_note": "TEST iteration23 manual ranking"},
        timeout=20,
    )
    assert patch_response.status_code == 200, patch_response.text
    payload = patch_response.json()
    assert payload["driver_id"] == driver_id
    assert payload["ranking_score"] == 88.5
    assert payload["ranking_tier"] in {"Gold", "Silver", "Bronze", "Start"}

    verify_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=20)
    assert verify_response.status_code == 200
    updated = next((item for item in verify_response.json() if item.get("id") == driver_id), None)
    assert updated is not None
    assert updated.get("manual_ranking_score") == 88.5


def test_driver_ranking_patch_rejects_non_admin(driver_session: requests.Session, admin_session: requests.Session):
    # Driver management module: non-admin must be blocked from manual ranking endpoint.
    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=20)
    assert drivers_response.status_code == 200
    driver_id = drivers_response.json()[0]["id"]

    forbidden = driver_session.patch(
        f"{BASE_URL}/api/drivers/{driver_id}/ranking",
        json={"manual_ranking_score": 50, "manual_rank_note": "should fail"},
        timeout=20,
    )
    assert forbidden.status_code == 403


def test_driver_delete_flow_requires_confirm_and_then_removes_driver(admin_session: requests.Session):
    # Driver management module: protected delete flow requires confirm flag and removes driver/user/schedules.
    unique_email = f"iter23-delete-{uuid.uuid4().hex[:8]}@example.com"
    create_response = admin_session.post(
        f"{BASE_URL}/api/drivers",
        json={
            "name": "TEST Iter23 Delete",
            "phone": "0711222333",
            "email": unique_email,
            "vehicle_type": "scooter",
        },
        timeout=30,
    )
    assert create_response.status_code == 200, create_response.text
    temp_driver_id = create_response.json().get("driver_id")
    assert isinstance(temp_driver_id, str) and len(temp_driver_id) > 0

    missing_confirm = admin_session.delete(
        f"{BASE_URL}/api/drivers/{temp_driver_id}",
        timeout=20,
    )
    assert missing_confirm.status_code == 409

    confirmed = admin_session.delete(
        f"{BASE_URL}/api/drivers/{temp_driver_id}",
        params={"confirm_delete": True},
        timeout=20,
    )
    assert confirmed.status_code == 200, confirmed.text
    deleted_payload = confirmed.json()
    assert deleted_payload.get("deleted_driver") == 1
    assert deleted_payload.get("deleted_user") == 1

    get_deleted = admin_session.get(f"{BASE_URL}/api/drivers/{temp_driver_id}", timeout=20)
    assert get_deleted.status_code == 404


def test_driver_delete_is_blocked_when_driver_has_active_orders(admin_session: requests.Session):
    # Driver management module: deletion must be blocked for drivers with active (non-finalized) orders.
    orders_response = admin_session.get(f"{BASE_URL}/api/orders", timeout=20)
    assert orders_response.status_code == 200
    assignable = next(
        (
            order for order in orders_response.json()
            if order.get("status") in {"NEW", "PREPARING", "READY"}
        ),
        None,
    )
    assert assignable is not None

    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=20)
    assert drivers_response.status_code == 200
    target_driver = next((driver for driver in drivers_response.json() if driver.get("is_active")), None)
    assert target_driver is not None

    assign_response = admin_session.put(
        f"{BASE_URL}/api/orders/{assignable['id']}/assign",
        json={"driver_id": target_driver["id"]},
        timeout=20,
    )
    assert assign_response.status_code == 200, assign_response.text

    blocked_delete = admin_session.delete(
        f"{BASE_URL}/api/drivers/{target_driver['id']}",
        params={"confirm_delete": True},
        timeout=20,
    )
    assert blocked_delete.status_code == 409
