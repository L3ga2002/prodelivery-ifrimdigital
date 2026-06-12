"""
Regression tests for restaurant-scoped delivery zones v2.
The current production model stores zones per restaurant, not global map sectors.
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
        "password": ADMIN_PASSWORD,
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def driver_token():
    clear_login_attempts(DRIVER_EMAIL)
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": DRIVER_EMAIL,
        "password": DRIVER_PASSWORD,
    })
    assert response.status_code == 200, f"Driver login failed: {response.text}"
    return response.json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _restaurants(admin_token: str) -> list[dict]:
    response = requests.get(f"{BASE_URL}/api/restaurants", headers=_headers(admin_token))
    assert response.status_code == 200
    restaurants = response.json()
    assert len(restaurants) >= 5
    return restaurants


def _restaurant(admin_token: str) -> dict:
    return _restaurants(admin_token)[0]


def _zone_payload(admin_token: str, *, level: int = 1, fee: float = 14.0, name: str | None = None) -> dict:
    restaurant = _restaurant(admin_token)
    return {
        "restaurant_id": restaurant["id"],
        "restaurant_name": restaurant["name"],
        "sector": restaurant["name"],
        "zone_level": level,
        "name": name or f"TEST_New_Zone_{uuid.uuid4().hex[:8]}",
        "color": "#ff00ff",
        "fee": fee,
        "polygon": [
            {"lat": 46.50, "lng": 26.85},
            {"lat": 46.50, "lng": 26.87},
            {"lat": 46.52, "lng": 26.87},
            {"lat": 46.52, "lng": 26.85},
        ],
        "is_active": True,
        "sort_order": 100,
    }


def _create_zone(admin_token: str, **kwargs) -> dict:
    response = requests.post(
        f"{BASE_URL}/api/zones",
        headers=_headers(admin_token),
        json=_zone_payload(admin_token, **kwargs),
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestGetZones:
    """Tests for GET /api/zones - list seeded restaurant zones."""

    def test_get_zones_returns_seeded_restaurant_zones(self, admin_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        zones = response.json()
        assert len(zones) >= 10, f"Expected at least 10 restaurant zones, got {len(zones)}"

    def test_zones_have_sector_field(self, admin_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        for zone in response.json():
            assert zone.get("sector")

    def test_zones_have_zone_level_field(self, admin_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        for zone in response.json():
            assert zone.get("zone_level") in [1, 2]

    def test_zones_contain_all_seeded_restaurants(self, admin_token):
        restaurants = _restaurants(admin_token)
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        restaurant_ids = {zone.get("restaurant_id") for zone in response.json()}
        for restaurant in restaurants:
            assert restaurant["id"] in restaurant_ids

    def test_each_restaurant_has_at_least_two_zones(self, admin_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        by_restaurant: dict[str, set[int]] = {}
        for zone in response.json():
            by_restaurant.setdefault(zone["restaurant_id"], set()).add(zone["zone_level"])
        assert by_restaurant
        for levels in by_restaurant.values():
            assert levels >= {1, 2}

    def test_fees_are_positive(self, admin_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        for zone in response.json():
            assert zone["fee"] > 0

    def test_get_zones_requires_auth(self):
        response = requests.get(f"{BASE_URL}/api/zones")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"

    def test_driver_can_get_zones(self, driver_token):
        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(driver_token))
        assert response.status_code == 200


class TestCreateZone:
    """Tests for POST /api/zones - admin creates restaurant-scoped zones."""

    def test_admin_can_create_zone_with_sector(self, admin_token):
        created = _create_zone(admin_token, level=2, fee=22.0, name=f"TEST_New_Zone_{uuid.uuid4().hex[:8]}")
        assert created["name"].startswith("TEST_New_Zone_")
        assert created["sector"] == created["restaurant_name"]
        assert created["zone_level"] == 2
        assert created["fee"] == 22.0
        assert created["is_locked"] is True

    def test_zone_fee_persists_from_payload(self, admin_token):
        for level, fee in [(1, 14.0), (2, 22.0)]:
            created = _create_zone(
                admin_token,
                level=level,
                fee=fee,
                name=f"TEST_Fee_Level{level}_{uuid.uuid4().hex[:8]}",
            )
            assert created["zone_level"] == level
            assert created["fee"] == fee

    def test_driver_cannot_create_zone(self, driver_token, admin_token):
        response = requests.post(
            f"{BASE_URL}/api/zones",
            headers=_headers(driver_token),
            json=_zone_payload(admin_token, name="TEST_Driver_Zone"),
        )
        assert response.status_code == 403


class TestUpdateZone:
    """Tests for PUT /api/zones/{zone_id} - protected zone update."""

    def test_admin_can_update_zone_sector(self, admin_token):
        test_zone = _create_zone(admin_token, name=f"TEST_Update_Sector_{uuid.uuid4().hex[:8]}")
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers=_headers(admin_token),
            json={"sector": "TEST_Updated_Sector", "confirm_protected_action": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["sector"] == "TEST_Updated_Sector"

    def test_admin_can_update_zone_level_and_fee(self, admin_token):
        test_zone = _create_zone(admin_token, level=1, fee=14.0, name=f"TEST_Level_{uuid.uuid4().hex[:8]}")
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers=_headers(admin_token),
            json={"zone_level": 2, "fee": 22.0, "confirm_protected_action": True},
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["zone_level"] == 2
        assert updated["fee"] == 22.0

    def test_admin_can_update_polygon(self, admin_token):
        test_zone = _create_zone(admin_token, name=f"TEST_Polygon_{uuid.uuid4().hex[:8]}")
        new_polygon = [
            {"lat": 46.55, "lng": 26.90},
            {"lat": 46.55, "lng": 26.92},
            {"lat": 46.57, "lng": 26.92},
            {"lat": 46.57, "lng": 26.90},
        ]
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers=_headers(admin_token),
            json={"polygon": new_polygon, "confirm_protected_action": True},
        )
        assert update_response.status_code == 200
        assert len(update_response.json()["polygon"]) == 4

    def test_driver_cannot_update_zone(self, driver_token, admin_token):
        zone = _create_zone(admin_token, name=f"TEST_Driver_Update_{uuid.uuid4().hex[:8]}")
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{zone['id']}",
            headers=_headers(driver_token),
            json={"name": "Hacked Zone", "confirm_protected_action": True},
        )
        assert update_response.status_code == 403


class TestDeleteZone:
    """Tests for DELETE /api/zones/{zone_id} - protected zone delete."""

    def test_admin_can_delete_zone(self, admin_token):
        created = _create_zone(admin_token, name=f"TEST_Delete_Zone_{uuid.uuid4().hex[:8]}")
        delete_response = requests.delete(
            f"{BASE_URL}/api/zones/{created['id']}",
            params={"confirm_protected_action": "true"},
            headers=_headers(admin_token),
        )
        assert delete_response.status_code == 200
        get_response = requests.get(f"{BASE_URL}/api/zones/{created['id']}", headers=_headers(admin_token))
        assert get_response.status_code == 404

    def test_driver_cannot_delete_zone(self, driver_token, admin_token):
        zone = _create_zone(admin_token, name=f"TEST_Driver_Delete_{uuid.uuid4().hex[:8]}")
        delete_response = requests.delete(
            f"{BASE_URL}/api/zones/{zone['id']}",
            params={"confirm_protected_action": "true"},
            headers=_headers(driver_token),
        )
        assert delete_response.status_code == 403


class TestZoneDetection:
    """Tests for POST /api/zones/detect - restaurant-scoped detection."""

    def test_detect_zone_returns_sector_and_level(self, admin_token):
        restaurant = _restaurant(admin_token)
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers=_headers(admin_token),
            json={"restaurant_id": restaurant["id"], "lat": restaurant["latitude"], "lng": restaurant["longitude"]},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["sector"]
        assert result["zone_level"] in [1, 2]
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
        assert result["sector"] is None
        assert result["zone_level"] is None
        assert result["fee"] == 0

    def test_detect_zone_returns_configured_fee(self, admin_token):
        restaurant = _restaurant(admin_token)
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers=_headers(admin_token),
            json={"restaurant_id": restaurant["id"], "lat": restaurant["latitude"], "lng": restaurant["longitude"]},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["fee"] > 0

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
            if zone["name"].startswith("TEST_") or zone.get("sector", "").startswith("TEST_"):
                requests.delete(
                    f"{BASE_URL}/api/zones/{zone['id']}",
                    params={"confirm_protected_action": "true"},
                    headers=_headers(admin_token),
                )

        response = requests.get(f"{BASE_URL}/api/zones", headers=_headers(admin_token))
        assert response.status_code == 200
        test_zones = [
            z for z in response.json()
            if z["name"].startswith("TEST_") or z.get("sector", "").startswith("TEST_")
        ]
        assert len(test_zones) == 0, f"Cleanup failed, remaining test zones: {test_zones}"
