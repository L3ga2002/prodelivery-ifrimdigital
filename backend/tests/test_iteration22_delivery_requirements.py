"""Iteration 22 targeted regression for auth, drivers metadata, schedules preview, and zones protection."""

from datetime import date, timedelta
import uuid

import pytest
import requests

from _settings import BASE_URL, admin_credentials


def _current_monday_iso() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def _login_admin_session() -> tuple[requests.Session, requests.Response]:
    # Auth module: admin login bootstrap for protected endpoint testing.
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    response = session.post(f"{BASE_URL}/api/auth/login", json=admin_credentials(), timeout=20)
    assert response.status_code == 200
    payload = response.json()
    token = payload.get("token")
    assert isinstance(token, str) and len(token) > 0
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session, response


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    # Seed module: refresh demo data once for stable assertions.
    session, _ = _login_admin_session()
    seed_response = session.post(f"{BASE_URL}/api/seed", timeout=45)
    assert seed_response.status_code == 200
    return session


def test_login_sets_http_only_access_and_refresh_cookies():
    # Auth module: cookie-based session contract for frontend security.
    _, login_response = _login_admin_session()
    set_cookie_header = login_response.headers.get("set-cookie", "").lower()
    assert "access_token=" in set_cookie_header
    assert "refresh_token=" in set_cookie_header
    assert "httponly" in set_cookie_header


def test_cors_preflight_allows_credentials_for_explicit_origin():
    # Auth/CORS module: frontend origin must be explicitly allowed with credentials.
    origin = BASE_URL
    response = requests.options(
        f"{BASE_URL}/api/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        },
        timeout=20,
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_drivers_endpoint_returns_required_new_fields(admin_session: requests.Session):
    # Drivers module: enriched payload required for map/schedule/ranking UX.
    response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=20)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    sample = data[0]
    for field in [
        "vehicle_type",
        "email_verified",
        "is_scheduled_today",
        "is_on_shift_now",
        "next_tier",
    ]:
        assert field in sample

    assert sample["vehicle_type"] in ("scooter", "car")
    assert isinstance(sample["email_verified"], bool)
    assert isinstance(sample["is_scheduled_today"], bool)
    assert isinstance(sample["is_on_shift_now"], bool)


def test_clone_previous_week_preview_endpoint(admin_session: requests.Session):
    # Schedules module: admin clone previous week preview should be available.
    response = admin_session.post(
        f"{BASE_URL}/api/schedules/admin/clone-previous-week",
        json={"week_start": _current_monday_iso(), "preview_only": True},
        timeout=30,
    )
    assert response.status_code == 200
    payload = response.json()
    preview = payload.get("preview")
    assert isinstance(preview, dict)
    assert preview.get("target_week_start") == _current_monday_iso()
    assert "drivers_count" in preview
    assert "total_hours" in preview


def test_create_driver_accepts_vehicle_type_and_sets_email_unverified(admin_session: requests.Session):
    # Drivers + Resend module: create should accept vehicle and return non-crashing email delivery result.
    unique_email = f"iter22-driver-{uuid.uuid4().hex[:8]}@example.com"
    create_response = admin_session.post(
        f"{BASE_URL}/api/drivers",
        json={
            "name": "TEST Iter22 Driver",
            "phone": "0711000000",
            "email": unique_email,
            "vehicle_type": "car",
        },
        timeout=30,
    )
    assert create_response.status_code == 200
    create_data = create_response.json()
    assert isinstance(create_data.get("driver_id"), str) and len(create_data["driver_id"]) > 0
    assert create_data.get("email_delivery", {}).get("status") in {"sent", "failed", "not_sent"}

    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=20)
    assert drivers_response.status_code == 200
    created = next((d for d in drivers_response.json() if d.get("id") == create_data["driver_id"]), None)
    assert created is not None
    assert created.get("vehicle_type") == "car"
    assert not created.get("email_verified")


def test_zone_protection_blocks_update_and_delete_without_confirm(admin_session: requests.Session):
    # Zones module: protected zones must return 409 unless explicit confirm is sent.
    zones_response = admin_session.get(
        f"{BASE_URL}/api/zones",
        params={"restaurant_id": "rest-001"},
        timeout=20,
    )
    assert zones_response.status_code == 200
    zones = zones_response.json()
    assert isinstance(zones, list)
    locked_zone = next((zone for zone in zones if zone.get("is_locked", True)), None)
    assert locked_zone is not None

    zone_id = locked_zone["id"]

    update_response = admin_session.put(
        f"{BASE_URL}/api/zones/{zone_id}",
        json={"name": f"{locked_zone['name']}-probe"},
        timeout=20,
    )
    assert update_response.status_code == 409

    delete_response = admin_session.delete(f"{BASE_URL}/api/zones/{zone_id}", timeout=20)
    assert delete_response.status_code == 409


def test_auth_bruteforce_lockout_after_five_failed_attempts():
    # Auth hardening module: brute-force guard should lock account after repeated failures.
    email = admin_credentials()["email"]
    for _ in range(5):
        failed = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "wrong-password"},
            timeout=20,
        )
        assert failed.status_code == 401

    locked = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": admin_credentials()["password"]},
        timeout=20,
    )
    assert locked.status_code in (423, 429), locked.text
