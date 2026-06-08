"""Iteration 25: Driver mobile/auth/profile regression tests for requested UX/API scope."""

from __future__ import annotations

import os
import requests
import pytest
from pymongo import MongoClient

from _settings import BASE_URL, admin_credentials, driver_credentials


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


def _clear_login_attempts(identifier: str) -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        return
    client = MongoClient(mongo_url)
    try:
        client[db_name]["login_attempts"].delete_many({"email": identifier})
    finally:
        client.close()


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    # Auth module: admin bootstrap session.
    _clear_login_attempts(admin_credentials()["email"])
    session = _session()
    _login(session, admin_credentials())
    return session


@pytest.fixture(scope="module")
def seeded(admin_session: requests.Session) -> None:
    # Seed module: ensure deterministic baseline for phone-login/profile tests.
    seed_response = admin_session.post(f"{BASE_URL}/api/seed", timeout=45)
    assert seed_response.status_code == 200, seed_response.text


def test_auth_login_sets_http_only_cookies():
    # Auth module: login should set secure cookie session artifacts.
    session = _session()
    response = session.post(f"{BASE_URL}/api/auth/login", json=admin_credentials(), timeout=25)
    assert response.status_code == 200
    cookie_header = response.headers.get("set-cookie", "").lower()
    assert "access_token=" in cookie_header
    assert "refresh_token=" in cookie_header
    assert "httponly" in cookie_header


def test_auth_cors_preflight_uses_explicit_origin_for_credentials():
    # Auth module: wildcard origin is invalid with credentials.
    response = requests.options(
        f"{BASE_URL}/api/auth/login",
        headers={
            "Origin": BASE_URL,
            "Access-Control-Request-Method": "POST",
        },
        timeout=25,
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == BASE_URL
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_admin_hash_starts_with_bcrypt_2b_prefix():
    # Auth playbook module: persisted admin hash format.
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        pytest.skip("MONGO_URL/DB_NAME unavailable")

    client = MongoClient(mongo_url)
    try:
        admin_user = client[db_name]["users"].find_one({"email": admin_credentials()["email"]})
    finally:
        client.close()

    assert admin_user is not None
    password_hash = admin_user.get("password_hash", "")
    assert isinstance(password_hash, str)
    assert password_hash.startswith("$2b$")


def test_driver_login_with_email_works(seeded: None):
    # Driver auth module: email login baseline.
    _clear_login_attempts(driver_credentials()["email"])
    session = _session()
    response = session.post(f"{BASE_URL}/api/auth/login", json=driver_credentials(), timeout=25)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("user", {}).get("role") == "driver"
    assert body.get("user", {}).get("email") == driver_credentials()["email"]


def test_self_profile_patch_updates_phone_and_identity(seeded: None):
    # Driver self-profile module: patch + persistence verification via dashboard.
    _clear_login_attempts(driver_credentials()["email"])
    driver_client = _session()
    driver_payload = _login(driver_client, driver_credentials())
    driver_id = driver_payload.get("user", {}).get("driver_id")
    assert isinstance(driver_id, str) and len(driver_id) > 0

    patch_response = driver_client.patch(
        f"{BASE_URL}/api/drivers/{driver_id}/self-profile",
        json={
            "first_name": "Ion",
            "last_name": "Popescu",
            "birth_date": "1994-06-20",
            "gender": "masculin",
            "cnp": "1940620123456",
            "phone": "0722111222",
            "email": driver_credentials()["email"],
        },
        timeout=25,
    )
    assert patch_response.status_code == 200, patch_response.text
    body = patch_response.json()
    assert body.get("driver", {}).get("first_name") == "Ion"
    assert body.get("driver", {}).get("last_name") == "Popescu"
    assert body.get("driver", {}).get("phone") == "0722111222"
    assert "_id" not in body.get("driver", {})

    dashboard_response = driver_client.get(f"{BASE_URL}/api/drivers/{driver_id}/dashboard", timeout=25)
    assert dashboard_response.status_code == 200
    dashboard_driver = dashboard_response.json().get("driver", {})
    assert dashboard_driver.get("phone") == "0722111222"
    assert dashboard_driver.get("cnp") == "1940620123456"


def test_driver_login_with_updated_phone_works():
    # Driver auth module: login using phone after profile update.
    _clear_login_attempts("0722111222")
    session = _session()
    response = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "0722111222", "password": driver_credentials()["password"]},
        timeout=25,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("user", {}).get("role") == "driver"
    assert body.get("user", {}).get("driver_id")


def test_self_profile_rejects_invalid_phone():
    # Driver self-profile validation module: reject bad phone format.
    _clear_login_attempts(driver_credentials()["email"])
    client = _session()
    payload = _login(client, driver_credentials())
    driver_id = payload.get("user", {}).get("driver_id")
    assert driver_id

    response = client.patch(
        f"{BASE_URL}/api/drivers/{driver_id}/self-profile",
        json={
            "first_name": "Ion",
            "last_name": "Popescu",
            "birth_date": "1994-06-20",
            "gender": "masculin",
            "cnp": "1940620123456",
            "phone": "12345",
            "email": driver_credentials()["email"],
        },
        timeout=25,
    )
    assert response.status_code == 400
    assert "telefon" in response.text.lower()


def test_self_profile_rejects_invalid_cnp():
    # Driver self-profile validation module: reject malformed CNP.
    _clear_login_attempts(driver_credentials()["email"])
    client = _session()
    payload = _login(client, driver_credentials())
    driver_id = payload.get("user", {}).get("driver_id")
    assert driver_id

    response = client.patch(
        f"{BASE_URL}/api/drivers/{driver_id}/self-profile",
        json={
            "first_name": "Ion",
            "last_name": "Popescu",
            "birth_date": "1994-06-20",
            "gender": "masculin",
            "cnp": "123",
            "phone": "0722111222",
            "email": driver_credentials()["email"],
        },
        timeout=25,
    )
    assert response.status_code == 400
    assert "cnp" in response.text.lower()


def test_email_verification_flow_endpoint_remains_available():
    # Email verification module: endpoint should exist and return validation/auth response, not 404.
    _clear_login_attempts(driver_credentials()["email"])
    client = _session()
    payload = _login(client, driver_credentials())
    driver_id = payload.get("user", {}).get("driver_id")
    assert driver_id

    verify_response = client.post(
        f"{BASE_URL}/api/drivers/{driver_id}/verify-email",
        json={"code": "000000"},
        timeout=25,
    )
    assert verify_response.status_code in (200, 400), verify_response.text


def test_driver_dashboard_response_excludes_mongo_object_id():
    # Serialization module: no ObjectId leakage in dashboard response.
    _clear_login_attempts(driver_credentials()["email"])
    client = _session()
    payload = _login(client, driver_credentials())
    driver_id = payload.get("user", {}).get("driver_id")
    dashboard_response = client.get(f"{BASE_URL}/api/drivers/{driver_id}/dashboard", timeout=25)
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert "_id" not in dashboard
    assert "_id" not in dashboard.get("driver", {})


def test_admin_regression_login_and_me_still_work():
    # Admin regression module: login + /me still valid.
    _clear_login_attempts(admin_credentials()["email"])
    session = _session()
    login_response = session.post(f"{BASE_URL}/api/auth/login", json=admin_credentials(), timeout=25)
    assert login_response.status_code == 200
    token = login_response.json().get("token")
    session.headers.update({"Authorization": f"Bearer {token}"})

    me_response = session.get(f"{BASE_URL}/api/auth/me", timeout=25)
    assert me_response.status_code == 200
    me = me_response.json()
    assert me.get("role") == "admin"
    assert me.get("email") == admin_credentials()["email"]
