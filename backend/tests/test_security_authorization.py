"""Security regression tests for auth, seed, orders, drivers, and schedules."""

from __future__ import annotations

import inspect
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from _settings import (
    BASE_URL,
    admin_credentials,
    driver_credentials,
    restaurant_credentials,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth import set_auth_cookies  # noqa: E402
from routers.auth import _attempt_identifiers  # noqa: E402
from routers.seed import _ensure_seed_allowed, seed_data  # noqa: E402


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


def _request_for_scheme(scheme: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "scheme": scheme,
            "server": ("testserver", 443 if scheme == "https" else 80),
            "client": ("127.0.0.1", 12345),
        }
    )


def _login(credentials: dict[str, str]) -> tuple[requests.Session, dict]:
    session = _session()
    response = session.post(f"{BASE_URL}/api/auth/login", json=credentials, timeout=25)
    assert response.status_code == 200, response.text
    payload = response.json()
    token = payload.get("token")
    assert isinstance(token, str) and token
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session, payload


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    session, _ = _login(admin_credentials())
    return session


@pytest.fixture(scope="module")
def restaurant_session() -> tuple[requests.Session, dict]:
    return _login(restaurant_credentials())


@pytest.fixture(scope="module")
def driver_sessions() -> tuple[tuple[requests.Session, dict], tuple[requests.Session, dict]]:
    return _login(driver_credentials(1)), _login(driver_credentials(2))


def test_seed_helper_requires_explicit_enable_and_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ALLOW_SEED", raising=False)
    with pytest.raises(HTTPException) as disabled:
        _ensure_seed_allowed({"role": "admin"})
    assert disabled.value.status_code == 403

    monkeypatch.setenv("ALLOW_SEED", "true")
    with pytest.raises(HTTPException) as non_admin:
        _ensure_seed_allowed({"role": "driver"})
    assert non_admin.value.status_code == 403

    _ensure_seed_allowed({"role": "admin"})


def test_seed_endpoint_blocks_anonymous_and_does_not_return_credentials():
    anonymous = requests.post(f"{BASE_URL}/api/seed", timeout=25)
    assert anonymous.status_code in (401, 403)

    seed_source = inspect.getsource(seed_data)
    assert '"credentials"' not in seed_source
    assert "demo_credentials[" not in seed_source.split("return", 1)[-1]


def test_auth_cookies_use_lax_samesite_even_on_https():
    response = Response()
    set_auth_cookies(_request_for_scheme("https"), response, "access-token", "refresh-token")
    set_cookie_headers = response.raw_headers
    cookie_text = b"\n".join(value for name, value in set_cookie_headers if name == b"set-cookie").decode()
    assert "SameSite=lax" in cookie_text
    assert "samesite=none" not in cookie_text.lower()


def test_unsafe_cross_origin_request_is_rejected_by_middleware():
    from server import app

    client = TestClient(app)
    response = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Untrusted request origin"


def test_login_lockout_identifiers_ignore_spoofable_forwarded_for():
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.1"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    identifiers = _attempt_identifiers(request, "ADMIN@Example.Test")
    assert identifiers == ["ip:127.0.0.1:admin@example.test", "email:admin@example.test"]
    assert "203.0.113.1" not in " ".join(identifiers)


@pytest.mark.parametrize("role", ["admin", "restaurant"])
def test_public_register_rejects_privileged_roles(role: str):
    response = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={
            "email": f"security-{role}-{uuid.uuid4().hex[:10]}@example.test",
            "password": "test-password-not-secret",
            "name": f"Security {role}",
            "role": role,
            "restaurant_id": "rest-001",
        },
        timeout=25,
    )
    assert response.status_code == 403


def test_public_register_ignores_restaurant_id_injection(admin_session: requests.Session):
    response = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={
            "email": f"security-driver-{uuid.uuid4().hex[:10]}@example.test",
            "password": "test-password-not-secret",
            "name": "Security Driver",
            "role": "driver",
            "restaurant_id": "rest-001",
        },
        timeout=25,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    user = payload.get("user", {})
    driver_id = user.get("driver_id")
    assert user.get("role") == "driver"
    assert user.get("restaurant_id") is None

    if driver_id:
        delete_response = admin_session.delete(
            f"{BASE_URL}/api/drivers/{driver_id}",
            params={"confirm_delete": "true"},
            timeout=25,
        )
        assert delete_response.status_code in (200, 404), delete_response.text


def test_restaurant_order_access_is_tenant_scoped(
    admin_session: requests.Session,
    restaurant_session: tuple[requests.Session, dict],
):
    restaurant_client, restaurant_payload = restaurant_session
    own_restaurant_id = restaurant_payload["user"].get("restaurant_id")
    assert own_restaurant_id

    own_orders = restaurant_client.get(f"{BASE_URL}/api/orders", timeout=25)
    assert own_orders.status_code == 200, own_orders.text
    assert all(order.get("restaurant_id") == own_restaurant_id for order in own_orders.json())

    admin_orders = admin_session.get(f"{BASE_URL}/api/orders", timeout=25)
    assert admin_orders.status_code == 200, admin_orders.text
    other_order = next(
        (order for order in admin_orders.json() if order.get("restaurant_id") != own_restaurant_id),
        None,
    )
    if not other_order:
        pytest.skip("No cross-restaurant order available in current dataset")

    detail = restaurant_client.get(f"{BASE_URL}/api/orders/{other_order['id']}", timeout=25)
    assert detail.status_code == 403

    list_other = restaurant_client.get(
        f"{BASE_URL}/api/orders/restaurant/{other_order['restaurant_id']}",
        timeout=25,
    )
    assert list_other.status_code == 403

    mutate = restaurant_client.put(
        f"{BASE_URL}/api/orders/{other_order['id']}/status",
        json={"status": "CANCELLED", "cancellation_reason": "security regression"},
        timeout=25,
    )
    assert mutate.status_code == 403


def test_driver_profile_and_schedule_access_is_admin_or_self(
    admin_session: requests.Session,
    driver_sessions: tuple[tuple[requests.Session, dict], tuple[requests.Session, dict]],
):
    (driver_one_client, driver_one_payload), (_, driver_two_payload) = driver_sessions
    driver_one_id = driver_one_payload["user"].get("driver_id")
    driver_two_id = driver_two_payload["user"].get("driver_id")
    assert driver_one_id and driver_two_id and driver_one_id != driver_two_id

    admin_drivers = admin_session.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert admin_drivers.status_code == 200, admin_drivers.text

    driver_list = driver_one_client.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert driver_list.status_code == 403

    own_profile = driver_one_client.get(f"{BASE_URL}/api/drivers/{driver_one_id}", timeout=25)
    assert own_profile.status_code == 200, own_profile.text

    other_profile = driver_one_client.get(f"{BASE_URL}/api/drivers/{driver_two_id}", timeout=25)
    assert other_profile.status_code == 403

    own_schedule = driver_one_client.get(
        f"{BASE_URL}/api/schedules/driver/{driver_one_id}?year=2026",
        timeout=25,
    )
    assert own_schedule.status_code == 200, own_schedule.text

    other_schedule = driver_one_client.get(
        f"{BASE_URL}/api/schedules/driver/{driver_two_id}?year=2026",
        timeout=25,
    )
    assert other_schedule.status_code == 403

    admin_schedule = admin_session.get(
        f"{BASE_URL}/api/schedules/driver/{driver_two_id}?year=2026",
        timeout=25,
    )
    assert admin_schedule.status_code == 200, admin_schedule.text
