import time
from datetime import date, timedelta

import pytest
import requests
from _settings import BASE_URL, admin_credentials, login_session


def _next_monday_iso() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


@pytest.fixture(scope="session")
def base_url():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL is missing")
    return BASE_URL.rstrip("/")


@pytest.fixture(scope="session")
def admin_session(base_url):
    # Auth module coverage
    session, data = login_session(admin_credentials(), timeout=20)
    assert data.get("user", {}).get("role") == "admin"

    # Seed data module coverage
    seed_res = session.post(f"{base_url}/api/seed", timeout=30)
    assert seed_res.status_code == 200
    return session


@pytest.fixture
def created_order(admin_session, base_url):
    # Orders create/preparing/ready module coverage
    create_res = admin_session.post(
        f"{base_url}/api/orders",
        json={
            "restaurant_id": "rest-001",
            "customer_name": "TEST_P1 User",
            "customer_phone": "0712345678",
            "customer_address": "Str. Test 10, Bacau",
            "customer_latitude": 46.5678,
            "customer_longitude": 26.9139,
            "items": [{"name": "Pizza", "quantity": 1, "price": 30}],
            "subtotal_amount": 30,
            "total_amount": 30,
            "payment_type": "CASH",
            "source": "S",
        },
        timeout=20,
    )
    assert create_res.status_code == 200
    payload = create_res.json()
    assert payload.get("id")
    return payload["id"]


def test_order_preparing_persists_preparation_fields(admin_session, base_url, created_order):
    response = admin_session.put(
        f"{base_url}/api/orders/{created_order}/preparing",
        json={"preparation_time": 20},
        timeout=20,
    )
    assert response.status_code == 200

    get_res = admin_session.get(f"{base_url}/api/orders/{created_order}", timeout=20)
    assert get_res.status_code == 200
    order = get_res.json()

    assert order["status"] == "PREPARING"
    assert order["preparation_time"] == 20
    assert order["preparation_estimated_seconds"] == 1200
    assert isinstance(order.get("preparation_started_at"), str)
    assert isinstance(order.get("preparation_due_at"), str)


def test_order_ready_persists_actual_and_delay(admin_session, base_url, created_order):
    admin_session.put(
        f"{base_url}/api/orders/{created_order}/preparing",
        json={"preparation_time": 20},
        timeout=20,
    )
    time.sleep(2)

    ready_res = admin_session.put(f"{base_url}/api/orders/{created_order}/ready", timeout=20)
    assert ready_res.status_code == 200

    get_res = admin_session.get(f"{base_url}/api/orders/{created_order}", timeout=20)
    assert get_res.status_code == 200
    order = get_res.json()

    assert order["status"] == "READY"
    assert isinstance(order.get("preparation_ready_at"), str)
    assert isinstance(order.get("preparation_actual_seconds"), int)
    assert isinstance(order.get("preparation_delay_seconds"), int)
    assert order["preparation_actual_seconds"] >= 0
    assert order["preparation_delay_seconds"] >= 0


def test_restaurant_analytics_returns_non_zero_and_recent_columns(admin_session, base_url):
    # Restaurants analytics module coverage
    response = admin_session.get(f"{base_url}/api/restaurants/rest-001/analytics", timeout=20)
    assert response.status_code == 200
    data = response.json()

    assert data.get("summary", {}).get("total_orders", 0) > 0
    assert "avg_preparation_actual_minutes" in data.get("summary", {})
    assert "avg_preparation_delay_minutes" in data.get("summary", {})
    assert "avg_delivery_minutes" in data.get("summary", {})

    recent = data.get("recent_orders", [])
    assert len(recent) > 0
    sample = recent[0]
    assert "preparation_time" in sample
    assert "preparation_actual_minutes" in sample
    assert "preparation_delay_minutes" in sample
    assert "delivery_minutes" in sample


def test_admin_schedule_auto_generate_and_bulk_delete(admin_session, base_url):
    # Schedules admin normal slot generation + delete module coverage
    week_start = _next_monday_iso()
    generate_res = admin_session.post(
        f"{base_url}/api/schedules/admin/auto-generate",
        json={
            "week_start": week_start,
            "days": ["monday"],
            "start_hour": "10:00",
            "end_hour": "11:00",
            "total_slots": 1,
            "slot_type": "normal",
            "repeat_weeks": 1,
        },
        timeout=20,
    )
    assert generate_res.status_code == 200
    generated = generate_res.json()
    assert isinstance(generated.get("created_slots"), int)

    delete_res = admin_session.post(
        f"{base_url}/api/schedules/admin/bulk-delete",
        json={
            "week_start": week_start,
            "days": ["monday"],
            "start_hour": "10:00",
            "end_hour": "11:00",
            "added_by": "auto",
        },
        timeout=20,
    )
    assert delete_res.status_code == 200
    deleted = delete_res.json()
    assert isinstance(deleted.get("deleted_slots"), int)


def test_emergency_setup_generate_creates_or_updates_slots(admin_session, base_url):
    # Emergency setup-generate module coverage
    week_start = _next_monday_iso()
    setup_res = admin_session.post(
        f"{base_url}/api/schedules/emergency/setup-generate",
        json={
            "week_start": week_start,
            "days": ["monday"],
            "start_hour": "12:00",
            "end_hour": "13:00",
            "total_slots": 2,
            "slot_type": "emergency",
            "repeat_weeks": 1,
        },
        timeout=20,
    )
    assert setup_res.status_code == 200
    payload = setup_res.json()
    assert payload.get("created", 0) + payload.get("updated", 0) >= 1

    list_res = admin_session.get(
        f"{base_url}/api/schedules/emergency",
        params={"week_start": week_start},
        timeout=20,
    )
    assert list_res.status_code == 200
    slots = list_res.json()
    assert any(slot.get("day") == "monday" and slot.get("hour") == "12:00" for slot in slots)
