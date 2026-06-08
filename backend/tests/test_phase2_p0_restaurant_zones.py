"""
Phase 2 P0 regression tests: auth cookie login, geocoding, restaurant-scoped zones,
available restaurants by coordinate, and order zone detection.
"""

import uuid

import pytest
import requests

from _settings import BASE_URL, admin_credentials


@pytest.fixture(scope="module")
def admin_session_and_token():
    # Auth and cookie/session module setup for admin-only P0 endpoints
    session = requests.Session()
    login_response = session.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
    if login_response.status_code != 200:
        pytest.skip(f"Admin login failed: {login_response.text}")

    data = login_response.json()
    token = data.get("token")
    assert token, "Missing token in login response"

    headers = {"Authorization": f"Bearer {token}"}
    return session, headers, login_response


@pytest.fixture(scope="module")
def seeded(admin_session_and_token):
    # Seed once for deterministic baseline data used by zone/order tests
    session, _, _ = admin_session_and_token
    response = session.post(f"{BASE_URL}/api/seed")
    assert response.status_code == 200
    payload = response.json()
    assert "data" in payload
    return payload


def _pick_restaurant(session, headers):
    restaurants_res = session.get(f"{BASE_URL}/api/restaurants", headers=headers)
    assert restaurants_res.status_code == 200
    restaurants = restaurants_res.json()
    assert isinstance(restaurants, list)
    assert len(restaurants) > 0
    return restaurants[0]


def _create_test_zone(session, headers, restaurant_id, restaurant_name, zone_name_suffix):
    base_lat = 46.567
    base_lng = 26.913
    polygon = [
        {"lat": base_lat + 0.004, "lng": base_lng - 0.004},
        {"lat": base_lat + 0.004, "lng": base_lng + 0.004},
        {"lat": base_lat - 0.004, "lng": base_lng + 0.004},
        {"lat": base_lat - 0.004, "lng": base_lng - 0.004},
    ]
    create_payload = {
        "restaurant_id": restaurant_id,
        "restaurant_name": restaurant_name,
        "sector": restaurant_name,
        "zone_level": 1,
        "name": f"TEST_P0_{zone_name_suffix}",
        "color": "#2563eb",
        "fee": 12.5,
        "polygon": polygon,
        "is_active": True,
        "sort_order": 999,
    }
    create_res = session.post(f"{BASE_URL}/api/zones", json=create_payload, headers=headers)
    assert create_res.status_code == 200, create_res.text
    created = create_res.json()
    assert created["restaurant_id"] == restaurant_id
    assert created["name"].startswith("TEST_P0_")
    return created


class TestP0RestaurantZonesBackend:
    """Backend regression checks for restaurant-specific delivery zones and geocoding."""

    def test_admin_login_sets_cookie_and_me_works(self, admin_session_and_token):
        session, headers, login_response = admin_session_and_token

        assert login_response.status_code == 200
        set_cookie = login_response.headers.get("set-cookie", "").lower()
        assert "access_token" in set_cookie or "refresh_token" in set_cookie

        me_res = session.get(f"{BASE_URL}/api/auth/me", headers=headers)
        assert me_res.status_code == 200
        me = me_res.json()
        assert me["role"] == "admin"
        assert "email" in me

    def test_geocoding_search_bacau_returns_suggestions(self, admin_session_and_token):
        session, headers, _ = admin_session_and_token
        response = session.get(
            f"{BASE_URL}/api/geocoding/search",
            params={"q": "Calea Marasesti", "limit": 3},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)
        assert len(data["suggestions"]) > 0
        first = data["suggestions"][0]
        assert isinstance(first.get("lat"), float)
        assert isinstance(first.get("lng"), float)
        assert "label" in first and len(first["label"]) > 0

    def test_list_zones_with_restaurant_id_returns_only_restaurant_scoped_zones(self, admin_session_and_token, seeded):
        session, headers, _ = admin_session_and_token
        restaurant = _pick_restaurant(session, headers)
        res = session.get(
            f"{BASE_URL}/api/zones",
            params={"restaurant_id": restaurant["id"]},
            headers=headers,
        )
        assert res.status_code == 200
        zones = res.json()
        assert isinstance(zones, list)
        for zone in zones:
            assert zone.get("restaurant_id") == restaurant["id"]

    def test_create_detect_available_and_order_zone_for_restaurant(self, admin_session_and_token):
        session, headers, _ = admin_session_and_token
        restaurant = _pick_restaurant(session, headers)
        suffix = str(uuid.uuid4())[:8]
        zone = _create_test_zone(
            session,
            headers,
            restaurant_id=restaurant["id"],
            restaurant_name=restaurant["name"],
            zone_name_suffix=suffix,
        )

        try:
            detect_res = session.post(
                f"{BASE_URL}/api/zones/detect",
                json={"restaurant_id": restaurant["id"], "lat": 46.567, "lng": 26.913},
                headers=headers,
            )
            assert detect_res.status_code == 200
            detected = detect_res.json()
            assert detected["restaurant_id"] == restaurant["id"]
            assert detected["zone_id"] is not None
            assert detected["fee"] >= 0

            available_res = session.post(
                f"{BASE_URL}/api/restaurants/available",
                json={"lat": 46.567, "lng": 26.913},
                headers=headers,
            )
            assert available_res.status_code == 200
            available = available_res.json()
            assert "restaurants" in available and "count" in available
            assert isinstance(available["restaurants"], list)
            assert any(r["id"] == restaurant["id"] for r in available["restaurants"])

            order_payload = {
                "restaurant_id": restaurant["id"],
                "customer_name": "TEST_P0_Customer",
                "customer_phone": "0700000000",
                "customer_address": "TEST_P0_Address",
                "customer_latitude": 46.567,
                "customer_longitude": 26.913,
                "items": [{"name": "TEST_P0_Item", "quantity": 1, "price": 10}],
                "subtotal_amount": 10,
                "total_amount": 10,
                "payment_type": "CASH",
                "notes": "TEST_P0",
                "source": "S",
            }
            create_order_res = session.post(f"{BASE_URL}/api/orders", json=order_payload, headers=headers)
            assert create_order_res.status_code == 200, create_order_res.text
            order = create_order_res.json()
            assert order["restaurant_id"] == restaurant["id"]
            assert order.get("delivery_zone_id") is not None
            assert order.get("delivery_zone_name")
            assert order.get("delivery_fee") >= 0

            persisted_res = session.get(f"{BASE_URL}/api/orders/{order['id']}", headers=headers)
            assert persisted_res.status_code == 200
            persisted = persisted_res.json()
            assert persisted["delivery_zone_id"] == order["delivery_zone_id"]
            assert persisted["delivery_zone_name"] == order["delivery_zone_name"]
            assert persisted["restaurant_id"] == restaurant["id"]
        finally:
            session.delete(f"{BASE_URL}/api/zones/{zone['id']}", headers=headers)
