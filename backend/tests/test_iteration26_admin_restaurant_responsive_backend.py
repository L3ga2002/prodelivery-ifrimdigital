"""Iteration 26: Admin/Restaurant auth + status persistence + availability regression checks."""

from __future__ import annotations

import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from _settings import BASE_URL, CORS_ORIGIN, admin_credentials, clear_login_attempts, restaurant_credentials


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


def _login(session: requests.Session, creds: dict[str, str]) -> dict:
    response = session.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=25)
    assert response.status_code == 200, response.text
    payload = response.json()
    token = payload.get("token")
    assert isinstance(token, str) and token
    session.headers.update({"Authorization": f"Bearer {token}"})
    return payload


def _mongo_client() -> MongoClient | None:
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        return None
    return MongoClient(mongo_url)


def _db_name() -> str | None:
    return os.environ.get("DB_NAME")


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    # Auth module: admin login baseline for management endpoints.
    clear_login_attempts(admin_credentials()["email"])
    session = _session()
    _login(session, admin_credentials())
    return session


@pytest.fixture(scope="module")
def restaurant_session() -> requests.Session:
    # Auth module: restaurant login baseline for self endpoints.
    clear_login_attempts(restaurant_credentials()["email"])
    session = _session()
    _login(session, restaurant_credentials())
    return session


def test_admin_login_and_me_work_with_expected_identity():
    # Auth module: login + /me payload verification.
    session = _session()
    payload = _login(session, admin_credentials())
    assert payload.get("user", {}).get("email") == admin_credentials()["email"]
    assert payload.get("user", {}).get("role") == "admin"

    me_response = session.get(f"{BASE_URL}/api/auth/me", timeout=25)
    assert me_response.status_code == 200
    me_payload = me_response.json()
    assert me_payload.get("email") == admin_credentials()["email"]
    assert me_payload.get("role") == "admin"


def test_restaurant_login_and_me_work_with_restaurant_context():
    # Auth module: restaurant login + /me returns restaurant context.
    session = _session()
    payload = _login(session, restaurant_credentials())
    user = payload.get("user", {})
    assert user.get("email") == restaurant_credentials()["email"]
    assert user.get("role") == "restaurant"
    assert isinstance(user.get("restaurant_id"), str) and user.get("restaurant_id")

    me_response = session.get(f"{BASE_URL}/api/auth/me", timeout=25)
    assert me_response.status_code == 200
    me_payload = me_response.json()
    assert me_payload.get("role") == "restaurant"
    assert me_payload.get("restaurant_id") == user.get("restaurant_id")


def test_restaurant_status_patch_persists_via_get(restaurant_session: requests.Session):
    # Restaurant status module: PATCH + GET persistence with cleanup restore.
    me_response = restaurant_session.get(f"{BASE_URL}/api/auth/me", timeout=25)
    assert me_response.status_code == 200
    restaurant_id = me_response.json().get("restaurant_id")
    assert isinstance(restaurant_id, str) and restaurant_id

    original_response = restaurant_session.get(f"{BASE_URL}/api/restaurants/{restaurant_id}", timeout=25)
    assert original_response.status_code == 200
    original_accepting = original_response.json().get("accepting_orders", True)

    try:
        patch_false = restaurant_session.patch(
            f"{BASE_URL}/api/restaurants/{restaurant_id}/status",
            json={"accepting_orders": False},
            timeout=25,
        )
        assert patch_false.status_code == 200, patch_false.text
        assert not patch_false.json().get("accepting_orders")

        get_false = restaurant_session.get(f"{BASE_URL}/api/restaurants/{restaurant_id}", timeout=25)
        assert get_false.status_code == 200
        assert not get_false.json().get("accepting_orders")

        patch_true = restaurant_session.patch(
            f"{BASE_URL}/api/restaurants/{restaurant_id}/status",
            json={"accepting_orders": True},
            timeout=25,
        )
        assert patch_true.status_code == 200, patch_true.text
        assert patch_true.json().get("accepting_orders")

        get_true = restaurant_session.get(f"{BASE_URL}/api/restaurants/{restaurant_id}", timeout=25)
        assert get_true.status_code == 200
        assert get_true.json().get("accepting_orders")
    finally:
        if original_accepting is not True:
            restaurant_session.patch(
                f"{BASE_URL}/api/restaurants/{restaurant_id}/status",
                json={"accepting_orders": original_accepting},
                timeout=25,
            )
        else:
            restaurant_session.patch(
                f"{BASE_URL}/api/restaurants/{restaurant_id}/status",
                json={"accepting_orders": True},
                timeout=25,
            )


def test_available_restaurants_excludes_paused_restaurant(admin_session: requests.Session):
    # Availability module: accepting_orders=false restaurant must be excluded.
    restaurants_response = admin_session.get(f"{BASE_URL}/api/restaurants", timeout=25)
    assert restaurants_response.status_code == 200
    restaurants = restaurants_response.json()
    target = next((r for r in restaurants if r.get("id") == "rest-001"), None) or restaurants[0]
    assert target is not None

    restaurant_id = target["id"]
    lat = target["latitude"]
    lng = target["longitude"]

    get_before = admin_session.get(f"{BASE_URL}/api/restaurants/{restaurant_id}", timeout=25)
    assert get_before.status_code == 200
    original_accepting = get_before.json().get("accepting_orders", True)

    try:
        pause_response = admin_session.patch(
            f"{BASE_URL}/api/restaurants/{restaurant_id}/status",
            json={"accepting_orders": False},
            timeout=25,
        )
        assert pause_response.status_code == 200, pause_response.text

        available_while_paused = admin_session.post(
            f"{BASE_URL}/api/restaurants/available",
            json={"lat": lat, "lng": lng},
            timeout=25,
        )
        assert available_while_paused.status_code == 200, available_while_paused.text
        paused_ids = {item.get("id") for item in available_while_paused.json().get("restaurants", [])}
        assert restaurant_id not in paused_ids

        resume_response = admin_session.patch(
            f"{BASE_URL}/api/restaurants/{restaurant_id}/status",
            json={"accepting_orders": True},
            timeout=25,
        )
        assert resume_response.status_code == 200, resume_response.text

        available_after_resume = admin_session.post(
            f"{BASE_URL}/api/restaurants/available",
            json={"lat": lat, "lng": lng},
            timeout=25,
        )
        assert available_after_resume.status_code == 200
        resumed_ids = {item.get("id") for item in available_after_resume.json().get("restaurants", [])}
        assert restaurant_id in resumed_ids
    finally:
        admin_session.patch(
            f"{BASE_URL}/api/restaurants/{restaurant_id}/status",
            json={"accepting_orders": original_accepting},
            timeout=25,
        )


def test_auth_login_sets_http_only_cookies_for_admin():
    # Auth cookie module: login should set httpOnly access+refresh cookies.
    session = _session()
    response = session.post(f"{BASE_URL}/api/auth/login", json=admin_credentials(), timeout=25)
    assert response.status_code == 200, response.text
    cookie_header = response.headers.get("set-cookie", "").lower()
    assert "access_token=" in cookie_header
    assert "refresh_token=" in cookie_header
    assert "httponly" in cookie_header


def test_admin_hash_uses_bcrypt_2b_prefix():
    # Auth playbook module: bcrypt format should start with $2b$.
    client = _mongo_client()
    db_name = _db_name()
    if not client or not db_name:
        pytest.skip("MONGO_URL/DB_NAME unavailable")

    try:
        admin_user = client[db_name]["users"].find_one({"email": admin_credentials()["email"]})
    finally:
        client.close()

    assert admin_user is not None
    password_hash = admin_user.get("password_hash", "")
    assert isinstance(password_hash, str)
    assert password_hash.startswith("$2b$")


def test_bruteforce_lockout_after_five_failed_attempts():
    # Auth hardening module: lockout should trigger after repeated failures.
    bogus_identifier = f"lockout-{uuid.uuid4().hex[:12]}@delivery.ro"
    session = _session()
    statuses = []

    for _ in range(6):
        response = session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": bogus_identifier, "password": "wrong-pass"},
            timeout=25,
        )
        statuses.append(response.status_code)

    assert statuses[:4] == [401, 401, 401, 401]
    assert 429 in statuses[4:]


def test_restaurant_and_orders_responses_exclude_mongo_object_id(restaurant_session: requests.Session):
    # Serialization module: ensure no Mongo _id leakage in modified restaurant/order flows.
    me_response = restaurant_session.get(f"{BASE_URL}/api/auth/me", timeout=25)
    assert me_response.status_code == 200
    restaurant_id = me_response.json().get("restaurant_id")
    assert restaurant_id

    restaurant_response = restaurant_session.get(f"{BASE_URL}/api/restaurants/{restaurant_id}", timeout=25)
    assert restaurant_response.status_code == 200
    restaurant_payload = restaurant_response.json()
    assert "_id" not in restaurant_payload

    orders_response = restaurant_session.get(f"{BASE_URL}/api/orders/restaurant/{restaurant_id}", timeout=25)
    assert orders_response.status_code == 200
    orders = orders_response.json()
    if orders:
        assert "_id" not in orders[0]


def test_auth_cors_preflight_uses_explicit_origin_with_credentials():
    # Auth CORS module: wildcard origin is invalid with credentials=true.
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
