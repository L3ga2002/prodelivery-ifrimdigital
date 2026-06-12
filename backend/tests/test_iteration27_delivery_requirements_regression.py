"""Iteration 27: targeted backend regression for restaurant/admin/driver requested features."""

from __future__ import annotations

import uuid

import pytest
import requests

from _settings import BASE_URL, admin_credentials, restaurant_credentials


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


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    # Auth/admin module
    session = _session()
    _login(session, admin_credentials())
    return session


@pytest.fixture(scope="module")
def restaurant_session() -> requests.Session:
    # Auth/restaurant module
    session = _session()
    _login(session, restaurant_credentials())
    return session


def _restaurant_id(session: requests.Session) -> str:
    me = session.get(f"{BASE_URL}/api/auth/me", timeout=25)
    assert me.status_code == 200
    rid = me.json().get("restaurant_id")
    assert isinstance(rid, str) and rid
    return rid


def _build_order_payload(restaurant_id: str, suffix: str) -> dict:
    return {
        "restaurant_id": restaurant_id,
        "customer_name": f"TEST Client {suffix}",
        "customer_phone": "0712345678",
        "customer_address": f"Str. Test {suffix}, Bacău",
        "customer_latitude": 46.567,
        "customer_longitude": 26.913,
        "items": [{"name": "Pizza Test", "quantity": 1, "price": 35}],
        "subtotal_amount": 35,
        "delivery_fee": 0,
        "total_amount": 35,
        "payment_type": "CASH",
        "notes": "TEST iteration27",
        "source": "S",
    }


def _deliver_order(admin_session: requests.Session, order_id: str) -> None:
    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert drivers_response.status_code == 200, drivers_response.text
    driver = next((item for item in drivers_response.json() if not item.get("current_order_id") and not item.get("account_disabled")), None)
    if not driver:
        pytest.skip("No available driver for problem-order delivery setup")

    assign = admin_session.put(
        f"{BASE_URL}/api/orders/{order_id}/assign",
        json={"driver_id": driver["id"]},
        timeout=25,
    )
    assert assign.status_code == 200, assign.text

    for status in ["ACCEPTED", "PICKED_UP", "DELIVERED"]:
        response = admin_session.put(
            f"{BASE_URL}/api/orders/{order_id}/status",
            json={"status": status},
            timeout=25,
        )
        assert response.status_code == 200, response.text


def test_restaurant_analytics_access_and_shape(restaurant_session: requests.Session):
    # Restaurant analytics module: role restaurant can access own analytics endpoint.
    rid = _restaurant_id(restaurant_session)
    response = restaurant_session.get(f"{BASE_URL}/api/restaurants/{rid}/analytics", timeout=25)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("restaurant", {}).get("id") == rid
    assert "summary" in payload and isinstance(payload["summary"], dict)
    assert "charts" in payload and isinstance(payload["charts"], dict)
    assert "recent_orders" in payload and isinstance(payload["recent_orders"], list)


def test_restaurant_schedule_settings_patch_persists(restaurant_session: requests.Session):
    # Restaurant schedule module: patch schedule-settings and read persisted values.
    rid = _restaurant_id(restaurant_session)
    current = restaurant_session.get(f"{BASE_URL}/api/restaurants/{rid}", timeout=25)
    assert current.status_code == 200
    original_schedule = current.json().get("schedule_settings", {})

    patch_payload = {
        "monday": {"enabled": True, "open_time": "09:30", "close_time": "21:30"},
        "tuesday": {"enabled": False, "open_time": "10:00", "close_time": "22:00"},
    }

    try:
        patch_response = restaurant_session.patch(
            f"{BASE_URL}/api/restaurants/{rid}/schedule-settings",
            json=patch_payload,
            timeout=25,
        )
        assert patch_response.status_code == 200, patch_response.text

        get_after = restaurant_session.get(f"{BASE_URL}/api/restaurants/{rid}", timeout=25)
        assert get_after.status_code == 200
        schedule = get_after.json().get("schedule_settings", {})
        assert schedule.get("monday", {}).get("open_time") == "09:30"
        assert schedule.get("monday", {}).get("close_time") == "21:30"
        assert not schedule.get("tuesday", {}).get("enabled")
    finally:
        if original_schedule:
            restaurant_session.patch(
                f"{BASE_URL}/api/restaurants/{rid}/schedule-settings",
                json=original_schedule,
                timeout=25,
            )


def test_problem_order_creates_linked_followup_and_marks_original(
    admin_session: requests.Session,
    restaurant_session: requests.Session,
):
    # Orders problem module: POST /problem creates linked order and marks original.
    rid = _restaurant_id(restaurant_session)
    status_response = restaurant_session.patch(
        f"{BASE_URL}/api/restaurants/{rid}/status",
        json={"accepting_orders": True},
        timeout=25,
    )
    assert status_response.status_code == 200, status_response.text

    suffix = uuid.uuid4().hex[:8]
    create_order = admin_session.post(
        f"{BASE_URL}/api/orders",
        json=_build_order_payload(rid, suffix),
        timeout=25,
    )
    assert create_order.status_code == 200, create_order.text
    original = create_order.json()
    original_id = original["id"]
    _deliver_order(admin_session, original_id)

    problem_response = restaurant_session.post(
        f"{BASE_URL}/api/orders/{original_id}/problem",
        json={
            "problem_type": "missing_product",
            "item_name": "Sos usturoi",
            "quantity": 1,
            "price": 5,
            "problem_description": "Lipsește sosul din comanda inițială",
        },
        timeout=25,
    )
    assert problem_response.status_code == 200, problem_response.text
    problem_payload = problem_response.json()
    linked = problem_payload.get("order", {})
    linked_id = linked.get("id")
    assert linked.get("linked_problem_order_id") == original_id
    assert linked.get("problem_type") == "missing_product"
    assert linked.get("customer_phone") == original.get("customer_phone")

    original_after = restaurant_session.get(f"{BASE_URL}/api/orders/{original_id}", timeout=25)
    assert original_after.status_code == 200
    assert original_after.json().get("has_problem_followup")

    if linked_id:
        admin_session.put(
            f"{BASE_URL}/api/orders/{linked_id}/status",
            json={"status": "CANCELLED", "cancellation_reason": "TEST cleanup"},
            timeout=25,
        )
    admin_session.put(
        f"{BASE_URL}/api/orders/{original_id}/status",
        json={"status": "CANCELLED", "cancellation_reason": "TEST cleanup"},
        timeout=25,
    )


def test_prep_availability_shape_and_minimum_rule(restaurant_session: requests.Session):
    # Prep availability module: endpoint returns required contract fields.
    rid = _restaurant_id(restaurant_session)
    response = restaurant_session.get(
        f"{BASE_URL}/api/orders/restaurant/{rid}/prep-availability",
        timeout=25,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert isinstance(payload.get("available_drivers"), int)
    assert isinstance(payload.get("blocked_short_options"), bool)
    assert isinstance(payload.get("minimum_preparation_minutes"), int)
    assert payload["minimum_preparation_minutes"] in (5, 20)


def test_disable_driver_blocks_when_active_order_exists(admin_session: requests.Session):
    # Driver disable module: disable endpoint blocked with active order.
    drivers_response = admin_session.get(f"{BASE_URL}/api/drivers", timeout=25)
    assert drivers_response.status_code == 200
    drivers = drivers_response.json()
    target_driver = next((d for d in drivers if d.get("is_active") and not d.get("current_order_id")), None)
    assert target_driver is not None

    create_order = admin_session.post(
        f"{BASE_URL}/api/orders",
        json=_build_order_payload("rest-001", f"disable-{uuid.uuid4().hex[:6]}"),
        timeout=25,
    )
    assert create_order.status_code == 200, create_order.text
    order_id = create_order.json()["id"]

    assign = admin_session.put(
        f"{BASE_URL}/api/orders/{order_id}/assign",
        json={"driver_id": target_driver["id"]},
        timeout=25,
    )
    assert assign.status_code == 200, assign.text

    disable = admin_session.patch(
        f"{BASE_URL}/api/drivers/{target_driver['id']}/disable",
        json={"reason": "TEST should fail with active order"},
        timeout=25,
    )
    assert disable.status_code == 409
    assert "comenzi active" in (disable.json().get("detail", "").lower())

    admin_session.put(
        f"{BASE_URL}/api/orders/{order_id}/status",
        json={"status": "CANCELLED", "cancellation_reason": "TEST cleanup"},
        timeout=25,
    )
