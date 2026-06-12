"""Iteration 24: driver status/avatar/profile + assignment regressions for ProDelivery P0/P1."""

from __future__ import annotations

from io import BytesIO
from datetime import datetime
import uuid
import os

import pytest
import requests
from PIL import Image
from pymongo import MongoClient

from _settings import BASE_URL, CORS_ORIGIN, admin_credentials, clear_login_attempts, driver_credentials


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


def _login(session: requests.Session, creds: dict[str, str]) -> dict:
    response = session.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=25)
    assert response.status_code == 200, response.text
    payload = response.json()
    token = payload.get("token")
    assert isinstance(token, str) and len(token) > 0
    session.headers.update({"Authorization": f"Bearer {token}"})
    return payload


def _test_image_bytes(color: tuple[int, int, int] = (240, 120, 20), size: tuple[int, int] = (900, 900)) -> bytes:
    image = Image.new("RGB", size, color=color)
    buff = BytesIO()
    image.save(buff, format="JPEG", quality=90)
    return buff.getvalue()


def _find_driver(drivers: list[dict], email: str | None = None) -> dict:
    if email:
        matched = next((driver for driver in drivers if driver.get("email") == email), None)
        if matched:
            return matched
    first = drivers[0] if drivers else None
    assert first is not None
    return first


def _clear_login_attempts(email: str) -> None:
    clear_login_attempts(email)


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    # Auth module: admin login bootstrap.
    _clear_login_attempts(admin_credentials()["email"])
    session = _session()
    _login(session, admin_credentials())
    return session


@pytest.fixture(scope="module")
def driver_session() -> tuple[requests.Session, dict]:
    # Auth module: driver login bootstrap.
    _clear_login_attempts(driver_credentials()["email"])
    seed_session = _session()
    _login(seed_session, admin_credentials())
    seed_response = seed_session.post(f"{BASE_URL}/api/seed", timeout=45)
    assert seed_response.status_code == 200
    session = _session()
    login_response = session.post(f"{BASE_URL}/api/auth/login", json=driver_credentials(), timeout=25)
    if login_response.status_code != 200:
        pytest.skip(f"Driver credentials unavailable for avatar/assignment regression: {login_response.text}")
    payload = login_response.json()
    token = payload.get("token")
    assert isinstance(token, str) and len(token) > 0
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session, payload


def test_admin_login_sets_http_only_cookies():
    # Auth module: ensure cookie-based auth artifacts are set on login.
    session = _session()
    response = session.post(f"{BASE_URL}/api/auth/login", json=admin_credentials(), timeout=25)
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
    assert "httponly" in set_cookie


def test_admin_password_hash_uses_bcrypt_2b_prefix():
    # Auth playbook module: admin password hash should use bcrypt $2b$ format.
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        pytest.skip("Missing MONGO_URL/DB_NAME for hash validation")

    client = MongoClient(mongo_url)
    try:
        admin_user = client[db_name]["users"].find_one({"email": admin_credentials()["email"]})
    finally:
        client.close()

    assert admin_user is not None
    password_hash = admin_user.get("password_hash", "")
    assert isinstance(password_hash, str)
    assert password_hash.startswith("$2b$")


def test_auth_cors_preflight_requires_explicit_origin_with_credentials():
    # Auth playbook module: CORS preflight should not return wildcard when credentials are enabled.
    response = requests.options(
        f"{BASE_URL}/api/auth/login",
        headers={
            "Origin": CORS_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
        timeout=25,
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == CORS_ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_auth_lockout_after_five_failed_attempts():
    # Auth playbook module: brute-force lockout must trigger after five invalid logins.
    lock_email = f"lockout-{uuid.uuid4().hex[:8]}@delivery.ro"
    _clear_login_attempts(lock_email)

    for _ in range(5):
        failed = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": lock_email, "password": "bad-pass"},
            timeout=25,
        )
        assert failed.status_code == 401

    locked = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": lock_email, "password": "bad-pass"},
        timeout=25,
    )
    assert locked.status_code in (423, 429), locked.text


def test_status_break_for_non_busy_driver_returns_countdown(admin_session: requests.Session):
    # Driver status module: set break for non-busy driver and verify remaining pause is exposed.
    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert drivers_response.status_code == 200
    target = next((d for d in drivers_response.json() if not d.get("current_order_id")), None)
    assert target is not None

    update_response = admin_session.put(
        f"{BASE_URL}/api/drivers/{target['id']}/status",
        json={"status": "break", "break_minutes": 7},
        timeout=25,
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json().get("operational_status") == "break"

    dashboard_response = admin_session.get(f"{BASE_URL}/api/drivers/{target['id']}/dashboard", timeout=25)
    assert dashboard_response.status_code == 200
    dashboard_driver = dashboard_response.json().get("driver", {})
    assert dashboard_driver.get("operational_status") == "break"
    assert isinstance(dashboard_driver.get("break_remaining_seconds"), int)
    assert dashboard_driver.get("break_remaining_seconds", 0) > 0

    back_active = admin_session.put(
        f"{BASE_URL}/api/drivers/{target['id']}/status",
        json={"status": "active"},
        timeout=25,
    )
    assert back_active.status_code == 200


def test_busy_driver_cannot_be_set_to_break_or_offline(admin_session: requests.Session):
    # Driver status + orders integration: active order blocks break/offline transitions.
    seed_response = admin_session.post(f"{BASE_URL}/api/seed", timeout=45)
    assert seed_response.status_code == 200

    orders_response = admin_session.get(f"{BASE_URL}/api/orders", timeout=25)
    assert orders_response.status_code == 200
    assignable = next((o for o in orders_response.json() if o.get("status") in {"NEW", "PREPARING", "READY"}), None)
    assert assignable is not None

    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert drivers_response.status_code == 200
    available_driver = next((d for d in drivers_response.json() if not d.get("current_order_id") and d.get("is_active")), None)
    if not available_driver:
        available_driver = next((d for d in drivers_response.json() if not d.get("current_order_id")), None)
        assert available_driver is not None
        force_active = admin_session.put(
            f"{BASE_URL}/api/drivers/{available_driver['id']}/status",
            json={"status": "active"},
            timeout=25,
        )
        assert force_active.status_code == 200

    assign_response = admin_session.put(
        f"{BASE_URL}/api/orders/{assignable['id']}/assign",
        json={"driver_id": available_driver["id"]},
        timeout=25,
    )
    assert assign_response.status_code == 200, assign_response.text

    block_break = admin_session.put(
        f"{BASE_URL}/api/drivers/{available_driver['id']}/status",
        json={"status": "break", "break_minutes": 5},
        timeout=25,
    )
    assert block_break.status_code == 409

    block_offline = admin_session.put(
        f"{BASE_URL}/api/drivers/{available_driver['id']}/status",
        json={"status": "offline"},
        timeout=25,
    )
    assert block_offline.status_code == 409


def test_profile_edit_updates_driver_and_creates_audit_log(admin_session: requests.Session):
    # Driver profile module: update contact fields, verify persistence and audit.
    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert drivers_response.status_code == 200
    target = next((d for d in drivers_response.json() if d.get("email") != driver_credentials()["email"]), None)
    assert target is not None

    stamp = datetime.utcnow().strftime("%H%M%S")
    patch_payload = {
        "name": f"{target['name']} T{stamp}",
        "phone": target.get("phone") or "0711000000",
        "email": target.get("email") or f"driver.profile.{uuid.uuid4().hex[:6]}@delivery.ro",
        "new_password": None,
    }
    patch_response = admin_session.patch(
        f"{BASE_URL}/api/drivers/{target['id']}/profile",
        json=patch_payload,
        timeout=25,
    )
    assert patch_response.status_code == 200, patch_response.text
    body = patch_response.json()
    assert body.get("message")
    assert isinstance(body.get("driver"), dict)
    assert "_id" not in body.get("driver", {})
    assert body["driver"].get("name") == patch_payload["name"]

    dashboard_response = admin_session.get(f"{BASE_URL}/api/drivers/{target['id']}/dashboard", timeout=25)
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["driver"].get("name") == patch_payload["name"]
    assert any(log.get("action") == "driver_profile_updated" for log in dashboard.get("audit_logs", []))


def test_profile_edit_rejects_short_manual_password(admin_session: requests.Session):
    # Driver profile validation module: manual password shorter than 6 chars must fail.
    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert drivers_response.status_code == 200
    target = _find_driver(drivers_response.json())

    short_password_response = admin_session.patch(
        f"{BASE_URL}/api/drivers/{target['id']}/profile",
        json={
            "name": target["name"],
            "phone": target.get("phone") or "0711000000",
            "email": target.get("email"),
            "new_password": "12345",
        },
        timeout=25,
    )
    assert short_password_response.status_code == 400


def test_admin_avatar_upload_is_immediately_approved_and_image_serves(admin_session: requests.Session):
    # Avatar module: admin upload should be active immediately with compressed image endpoint available.
    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert drivers_response.status_code == 200
    target = _find_driver(drivers_response.json())

    files = {"file": ("admin_avatar.jpg", _test_image_bytes((255, 140, 0)), "image/jpeg")}
    admin_session.headers.pop("Content-Type", None)
    upload_response = admin_session.post(
        f"{BASE_URL}/api/drivers/{target['id']}/avatar",
        files=files,
        timeout=35,
    )
    assert upload_response.status_code == 200, upload_response.text
    avatar_payload = upload_response.json().get("avatar", {})
    assert avatar_payload.get("status") == "approved"
    assert avatar_payload.get("is_active")
    assert avatar_payload.get("content_type") == "image/webp"
    assert avatar_payload.get("size", 0) > 0

    image_url = avatar_payload.get("image_url")
    assert image_url
    image_response = admin_session.get(f"{BASE_URL}{image_url}", timeout=25)
    assert image_response.status_code == 200
    assert image_response.headers.get("content-type") == "image/webp"
    assert len(image_response.content) > 0


def test_driver_avatar_upload_creates_pending_then_admin_can_approve(admin_session: requests.Session, driver_session: tuple[requests.Session, dict]):
    # Avatar moderation module: driver upload should be pending and require admin approve/reject.
    driver_client, driver_payload = driver_session
    driver_id = driver_payload.get("user", {}).get("driver_id")
    assert isinstance(driver_id, str) and len(driver_id) > 0

    files = {"file": ("driver_avatar.jpg", _test_image_bytes((120, 170, 255)), "image/jpeg")}
    driver_client.headers.pop("Content-Type", None)
    upload_response = driver_client.post(
        f"{BASE_URL}/api/drivers/{driver_id}/avatar",
        files=files,
        timeout=35,
    )
    assert upload_response.status_code == 200, upload_response.text
    avatar_payload = upload_response.json().get("avatar", {})
    assert avatar_payload.get("status") == "pending"
    assert not avatar_payload.get("is_active")
    avatar_id = avatar_payload.get("id")
    assert avatar_id

    approve_response = admin_session.patch(
        f"{BASE_URL}/api/drivers/{driver_id}/avatars/{avatar_id}",
        json={"action": "approve", "note": "test approval"},
        timeout=25,
    )
    assert approve_response.status_code == 200, approve_response.text

    dashboard_response = admin_session.get(f"{BASE_URL}/api/drivers/{driver_id}/dashboard", timeout=25)
    assert dashboard_response.status_code == 200
    driver_data = dashboard_response.json().get("driver", {})
    assert driver_data.get("active_avatar_id") == avatar_id
    assert isinstance(driver_data.get("avatar_url"), str)

    image_response = admin_session.get(f"{BASE_URL}{driver_data['avatar_url']}", timeout=25)
    assert image_response.status_code == 200
    assert image_response.headers.get("content-type") == "image/webp"


def test_avatar_upload_rejects_payload_over_4mb(admin_session: requests.Session):
    # Avatar validation module: backend should reject upload larger than 4MB.
    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert drivers_response.status_code == 200
    target = _find_driver(drivers_response.json())

    big_bytes = b"x" * (4 * 1024 * 1024 + 10)
    files = {"file": ("too_big.jpg", big_bytes, "image/jpeg")}
    admin_session.headers.pop("Content-Type", None)
    upload_response = admin_session.post(
        f"{BASE_URL}/api/drivers/{target['id']}/avatar",
        files=files,
        timeout=35,
    )
    assert upload_response.status_code == 413


def test_create_driver_regression_vehicle_type_and_verification_fields(admin_session: requests.Session):
    # Driver creation regression module: create still accepts vehicle_type and starts unverified email state.
    unique_email = f"iter24-{uuid.uuid4().hex[:8]}@delivery.ro"
    create_response = admin_session.post(
        f"{BASE_URL}/api/drivers",
        json={
            "name": "TEST Iter24 Create",
            "phone": "0722999888",
            "email": unique_email,
            "vehicle_type": "car",
        },
        timeout=35,
    )
    assert create_response.status_code == 200, create_response.text
    payload = create_response.json()
    driver_id = payload.get("driver_id")
    assert isinstance(driver_id, str) and len(driver_id) > 0

    dashboard_response = admin_session.get(f"{BASE_URL}/api/drivers/{driver_id}/dashboard", timeout=25)
    assert dashboard_response.status_code == 200
    driver_data = dashboard_response.json().get("driver", {})
    assert driver_data.get("vehicle_type") == "car"
    assert not driver_data.get("email_verified")


def test_order_assignment_regression_and_driver_current_order_endpoint(admin_session: requests.Session, driver_session: tuple[requests.Session, dict]):
    # Orders-driver integration module: assign order and verify driver current order feed works.
    driver_client, driver_payload = driver_session
    driver_id = driver_payload.get("user", {}).get("driver_id")
    assert driver_id

    seed_response = admin_session.post(f"{BASE_URL}/api/seed", timeout=45)
    assert seed_response.status_code == 200

    current_orders = driver_client.get(f"{BASE_URL}/api/orders/driver/{driver_id}", timeout=25)
    assert current_orders.status_code == 200
    for current_order in current_orders.json():
        if current_order.get("status") == "PICKED_UP":
            delivered = driver_client.put(
                f"{BASE_URL}/api/orders/{current_order['id']}/status",
                json={"status": "DELIVERED"},
                timeout=25,
            )
            assert delivered.status_code == 200, delivered.text

    activate_response = admin_session.put(
        f"{BASE_URL}/api/drivers/{driver_id}/status",
        json={"status": "active"},
        timeout=25,
    )
    assert activate_response.status_code == 200

    orders_response = admin_session.get(f"{BASE_URL}/api/orders", timeout=25)
    assert orders_response.status_code == 200
    order = next((o for o in orders_response.json() if o.get("status") in {"NEW", "PREPARING", "READY"}), None)
    assert order is not None

    assign_response = admin_session.put(
        f"{BASE_URL}/api/orders/{order['id']}/assign",
        json={"driver_id": driver_id},
        timeout=25,
    )
    assert assign_response.status_code == 200, assign_response.text

    current_orders_response = admin_session.get(f"{BASE_URL}/api/orders/driver/{driver_id}", timeout=25)
    assert current_orders_response.status_code == 200
    current_orders = current_orders_response.json()
    assert any(o.get("id") == order["id"] for o in current_orders)


def test_auth_me_session_check(admin_session: requests.Session):
    # Auth module: /me should return logged in user payload for current session.
    me_response = admin_session.get(f"{BASE_URL}/api/auth/me", timeout=25)
    assert me_response.status_code == 200
    me = me_response.json()
    assert me.get("email") == admin_credentials()["email"]
    assert me.get("role") == "admin"
