import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / "frontend" / ".env")
load_dotenv(ROOT_DIR / "backend" / ".env")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required test environment variable: {name}")
    return value


BASE_URL = _required_env("REACT_APP_BACKEND_URL").rstrip("/")
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
