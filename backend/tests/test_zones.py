"""
Test suite for restaurant-scoped Delivery Zones.
Tests: GET/POST/PUT/DELETE /api/zones and POST /api/zones/detect.
"""

import uuid

import pytest
import requests
from tests._settings import (
    BASE_URL,
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    DRIVER_EMAIL,
    DRIVER_PASSWORD,
    RESTAURANT_EMAIL,
    RESTAURANT_PASSWORD,
    clear_login_attempts,
    seed_demo_data,
)


@pytest.fixture(scope="module", autouse=True)
def seeded_demo():
    seed_demo_data()


@pytest.fixture(scope="module")
def admin_token():
    clear_login_attempts(ADMIN_EMAIL)
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def driver_token():
    clear_login_attempts(DRIVER_EMAIL)
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": DRIVER_EMAIL,
        "password": DRIVER_PASSWORD
    })
    assert response.status_code == 200, f"Driver login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def restaurant_token():
    clear_login_attempts(RESTAURANT_EMAIL)
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": RESTAURANT_EMAIL,
        "password": RESTAURANT_PASSWORD
    })
    assert response.status_code == 200, f"Restaurant login failed: {response.text}"
    return response.json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _restaurant(admin_token: str) -> dict:
    response = requests.get(f"{BASE_URL}/api/restaurants", headers=_headers(admin_token))
    assert response.status_code == 200
    restaurants = response.json()
    assert restaurants
    return next((r for r in restaurants if r["id"] == "rest-001"), restaurants[0])


def _zone_payload(admin_token: str, name: str | None = None, **overrides) -> dict:
    restaurant = _restaurant(admin_token)
    payload = {
        "restaurant_id": restaurant["id"],
        "restaurant_name": restaurant["name"],
        "sector": restaurant["name"],
        "zone_level": 1,
        "name": name or f"TEST_Zone_{uuid.uuid4().hex[:8]}",
        "color": "#ff00ff",
        "fee": 20.0,
        "polygon": [
            {"lat": 46.50, "lng": 26.85},
            {"lat": 46.50, "lng": 26.87},
            {"lat": 46.52, "lng": 26.87},
            {"lat": 46.52, "lng": 26.85},
        ],
        "is_active": True,
        "sort_order": 999,
    }
    payload.update(overrides)
    return payload


def _create_test_zone(admin_token: str, **overrides) -> dict:
    response = requests.post(
        f"{BASE_URL}/api/zones",
        headers=_headers(admin_token),
        json=_zone_payload(admin_token, **overrides),
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestGetZones:
    """Tests for GET /api/zones - list restaurant-scoped delivery zones."""

    def test_get_zones_returns_seeded_data(self, admin_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        zones = response.json()
        assert len(zones) >= 10, f"Expected seeded restaurant zones, got {len(zones)}"

        zone = zones[0]
        for field in ["id", "restaurant_id", "name", "color", "fee", "polygon", "is_active", "is_locked"]:
            assert field in zone

    def test_get_zones_contains_restaurant_scoped_levels(self, admin_token):
        restaurant = _restaurant(admin_token)
        response = requests.get(
            f"{BASE_URL}/api/zones",
            params={"restaurant_id": restaurant["id"]},
            headers=_headers(admin_token),
        )
        assert response.status_code == 200
        zones = response.json()
        assert {zone["zone_level"] for zone in zones} >= {1, 2}
        assert all(zone["restaurant_id"] == restaurant["id"] for zone in zones)

    def test_get_zones_fees_are_positive(self, admin_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        zones = response.json()
        assert all(isinstance(zone["fee"], (int, float)) and zone["fee"] > 0 for zone in zones)

    def test_get_zones_requires_auth(self):
        response = requests.get(f"{BASE_URL}/api/zones")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"

    def test_driver_can_get_zones(self, driver_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(driver_token))
        assert response.status_code == 200
        assert len(response.json()) >= 10


class TestCreateZone:
    """Tests for POST /api/zones - admin creates new restaurant-scoped zone."""

    def test_admin_can_create_zone(self, admin_token):
        created = _create_test_zone(admin_token, name=f"TEST_Zone_New_{uuid.uuid4().hex[:8]}")
        assert created["name"].startswith("TEST_Zone_New_")
        assert created["restaurant_id"]
        assert created["fee"] == 20.0
        assert created["color"] == "#ff00ff"
        assert created["is_locked"] is True

        get_response = requests.get(f"{BASE_URL}/api/zones/{created['id']}", headers=_headers(admin_token))
        assert get_response.status_code == 200
        assert get_response.json()["name"] == created["name"]

    def test_driver_cannot_create_zone(self, driver_token, admin_token):
        response = requests.post(
            f"{BASE_URL}/api/zones",
            headers=_headers(driver_token),
            json=_zone_payload(admin_token, name="TEST_Driver_Zone"),
        )
        assert response.status_code == 403

    def test_restaurant_cannot_create_zone(self, restaurant_token, admin_token):
        response = requests.post(
            f"{BASE_URL}/api/zones",
            headers=_headers(restaurant_token),
            json=_zone_payload(admin_token, name="TEST_Restaurant_Zone"),
        )
        assert response.status_code == 403


class TestUpdateZone:
    """Tests for PUT /api/zones/{zone_id} - protected zone update."""

    def test_admin_can_update_zone_name(self, admin_token):
        test_zone = _create_test_zone(admin_token, name=f"TEST_Update_Zone_{uuid.uuid4().hex[:8]}")
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers=_headers(admin_token),
            json={"name": "TEST_Updated_Name", "confirm_protected_action": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "TEST_Updated_Name"

    def test_admin_can_update_zone_fee(self, admin_token):
        test_zone = _create_test_zone(admin_token, name=f"TEST_Fee_Zone_{uuid.uuid4().hex[:8]}")
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers=_headers(admin_token),
            json={"fee": 25.5, "confirm_protected_action": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["fee"] == 25.5

    def test_admin_can_update_zone_color(self, admin_token):
        test_zone = _create_test_zone(admin_token, name=f"TEST_Color_Zone_{uuid.uuid4().hex[:8]}")
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers=_headers(admin_token),
            json={"color": "#00ff00", "confirm_protected_action": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["color"] == "#00ff00"

    def test_admin_can_toggle_zone_active(self, admin_token):
        test_zone = _create_test_zone(admin_token, name=f"TEST_Toggle_Zone_{uuid.uuid4().hex[:8]}")
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers=_headers(admin_token),
            json={"is_active": False, "confirm_protected_action": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_active"] is False

    def test_driver_cannot_update_zone(self, driver_token, admin_token):
        zone = _create_test_zone(admin_token, name=f"TEST_Driver_Update_{uuid.uuid4().hex[:8]}")
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{zone['id']}",
            headers=_headers(driver_token),
            json={"name": "Hacked Zone", "confirm_protected_action": True},
        )
        assert update_response.status_code == 403

    def test_update_nonexistent_zone_returns_404(self, admin_token):
        update_response = requests.put(
            f"{BASE_URL}/api/zones/nonexistent-zone-id",
            headers=_headers(admin_token),
            json={"name": "Test", "confirm_protected_action": True},
        )
        assert update_response.status_code == 404


class TestDeleteZone:
    """Tests for DELETE /api/zones/{zone_id} - protected zone delete."""

    def test_admin_can_delete_zone(self, admin_token):
        created = _create_test_zone(admin_token, name=f"TEST_Delete_Zone_{uuid.uuid4().hex[:8]}")
        delete_response = requests.delete(
            f"{BASE_URL}/api/zones/{created['id']}",
            params={"confirm_protected_action": "true"},
            headers=_headers(admin_token),
        )
        assert delete_response.status_code == 200

        get_response = requests.get(f"{BASE_URL}/api/zones/{created['id']}", headers=_headers(admin_token))
        assert get_response.status_code == 404

    def test_driver_cannot_delete_zone(self, driver_token, admin_token):
        zone = _create_test_zone(admin_token, name=f"TEST_Driver_Delete_{uuid.uuid4().hex[:8]}")
        delete_response = requests.delete(
            f"{BASE_URL}/api/zones/{zone['id']}",
            params={"confirm_protected_action": "true"},
            headers=_headers(driver_token),
        )
        assert delete_response.status_code == 403

    def test_delete_nonexistent_zone_returns_404(self, admin_token):
        delete_response = requests.delete(
            f"{BASE_URL}/api/zones/nonexistent-zone-id",
            params={"confirm_protected_action": "true"},
            headers=_headers(admin_token),
        )
        assert delete_response.status_code == 404


class TestZoneDetection:
    """Tests for POST /api/zones/detect - detect which zone a coordinate belongs to."""

    def test_detect_zone_centru(self, admin_token):
        restaurant = _restaurant(admin_token)
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers=_headers(admin_token),
            json={"restaurant_id": restaurant["id"], "lat": restaurant["latitude"], "lng": restaurant["longitude"]},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["restaurant_id"] == restaurant["id"]
        assert result["zone_id"] is not None
        assert result["fee"] > 0

    def test_detect_zone_outside_all(self, admin_token):
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers=_headers(admin_token),
            json={"lat": 44.0, "lng": 26.0},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["zone_id"] is None
        assert result["zone_name"] == "In afara zonelor"
        assert result["fee"] == 0

    def test_detect_zone_returns_fee(self, admin_token):
        restaurant = _restaurant(admin_token)
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers=_headers(admin_token),
            json={"restaurant_id": restaurant["id"], "lat": restaurant["latitude"], "lng": restaurant["longitude"]},
        )
        assert response.status_code == 200
        result = response.json()
        assert isinstance(result["fee"], (int, float))

    def test_detect_zone_returns_color(self, admin_token):
        restaurant = _restaurant(admin_token)
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers=_headers(admin_token),
            json={"restaurant_id": restaurant["id"], "lat": restaurant["latitude"], "lng": restaurant["longitude"]},
        )
        assert response.status_code == 200
        assert response.json()["color"].startswith("#")

    def test_driver_can_detect_zone(self, driver_token, admin_token):
        restaurant = _restaurant(admin_token)
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers=_headers(driver_token),
            json={"restaurant_id": restaurant["id"], "lat": restaurant["latitude"], "lng": restaurant["longitude"]},
        )
        assert response.status_code == 200


class TestCleanup:
    """Cleanup test zones after all tests."""

    def test_cleanup_test_zones(self, admin_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        zones = response.json()

        for zone in zones:
            if zone["name"].startswith("TEST_"):
                requests.delete(
                    f"{BASE_URL}/api/zones/{zone['id']}",
                    params={"confirm_protected_action": "true"},
                    headers=_headers(admin_token),
                )

        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        test_zones = [z for z in response.json() if z["name"].startswith("TEST_")]
        assert len(test_zones) == 0, f"Cleanup failed, remaining test zones: {test_zones}"
