import os
import re
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
import requests


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / "frontend" / ".env")
load_dotenv(ROOT_DIR / "backend" / ".env")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required test environment variable: {name}")
    return value


BASE_URL = _required_env("REACT_APP_BACKEND_URL").rstrip("/")
CORS_ORIGIN = os.getenv("CORS_ORIGINS", BASE_URL).split(",")[0].strip() or BASE_URL
ADMIN_EMAIL = _required_env("DEMO_ADMIN_EMAIL")
ADMIN_PASSWORD = _required_env("DEMO_ADMIN_PASSWORD")
DRIVER_EMAIL = _required_env("DEMO_DRIVER_1_EMAIL")
DRIVER2_EMAIL = _required_env("DEMO_DRIVER_2_EMAIL")
DRIVER_PASSWORD = _required_env("DEMO_DRIVER_PASSWORD")
RESTAURANT_EMAIL = _required_env("DEMO_RESTAURANT_1_EMAIL")
RESTAURANT_PASSWORD = _required_env("DEMO_RESTAURANT_PASSWORD")


def admin_credentials() -> dict[str, str]:
    return {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}


def driver_credentials(index: int = 1) -> dict[str, str]:
    email = DRIVER_EMAIL if index == 1 else DRIVER2_EMAIL
    return {"email": email, "password": DRIVER_PASSWORD}


def restaurant_credentials() -> dict[str, str]:
    return {"email": RESTAURANT_EMAIL, "password": RESTAURANT_PASSWORD}


def clear_login_attempts(identifier: str) -> None:
    mongo_url = os.getenv("MONGO_URL")
    db_name = os.getenv("DB_NAME")
    if not mongo_url or not db_name:
        return
    normalized = identifier.strip().lower()
    escaped = re.escape(normalized)
    client = MongoClient(mongo_url)
    try:
        client[db_name]["login_attempts"].delete_many({
            "$or": [
                {"email": normalized},
                {"identifier": {"$regex": f":{escaped}$"}},
            ]
        })
    finally:
        client.close()


def login_session(credentials: dict[str, str], timeout: int = 25) -> tuple[requests.Session, dict]:
    clear_login_attempts(credentials["email"])
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    response = session.post(f"{BASE_URL}/api/auth/login", json=credentials, timeout=timeout)
    assert response.status_code == 200, response.text
    payload = response.json()
    token = payload.get("token")
    assert isinstance(token, str) and token
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session, payload


def admin_session(timeout: int = 25) -> tuple[requests.Session, dict]:
    return login_session(admin_credentials(), timeout=timeout)


def seed_demo_data(timeout: int = 45) -> dict:
    session, _ = admin_session()
    response = session.post(f"{BASE_URL}/api/seed", timeout=timeout)
    assert response.status_code == 200, response.text
    return response.json()
