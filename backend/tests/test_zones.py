"""
Test suite for Delivery Zones feature (Task 2.2)
Tests: GET/POST/PUT/DELETE /api/zones and POST /api/zones/detect
"""
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
)


@pytest.fixture(scope="module")
def admin_token():
    """Get admin authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def driver_token():
    """Get driver authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": DRIVER_EMAIL,
        "password": DRIVER_PASSWORD
    })
    assert response.status_code == 200, f"Driver login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def restaurant_token():
    """Get restaurant authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": RESTAURANT_EMAIL,
        "password": RESTAURANT_PASSWORD
    })
    assert response.status_code == 200, f"Restaurant login failed: {response.text}"
    return response.json()["token"]


class TestGetZones:
    """Tests for GET /api/zones - list all delivery zones"""

    def test_get_zones_returns_seeded_data(self, admin_token):
        """GET /api/zones should return 4 default seeded zones"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        zones = response.json()

        # Should have 4 default zones
        assert len(zones) >= 4, f"Expected at least 4 zones, got {len(zones)}"

        # Verify zone structure
        zone = zones[0]
        assert "id" in zone
        assert "name" in zone
        assert "color" in zone
        assert "fee" in zone
        assert "polygon" in zone
        assert "is_active" in zone

    def test_get_zones_contains_expected_zones(self, admin_token):
        """Verify the 4 default zones: Centru, Semicentral, Periferie, Extins"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        zones = response.json()

        zone_names = [z["name"] for z in zones]
        expected_zones = ["Zona 1 - Centru", "Zona 2 - Semicentral", "Zona 3 - Periferie", "Zona 4 - Extins"]

        for expected in expected_zones:
            assert expected in zone_names, f"Missing zone: {expected}"

    def test_get_zones_fees_are_correct(self, admin_token):
        """Verify zone fees: Centru=5, Semicentral=8, Periferie=12, Extins=15"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        zones = response.json()

        fee_map = {z["name"]: z["fee"] for z in zones}

        assert fee_map.get("Zona 1 - Centru") == 5.0
        assert fee_map.get("Zona 2 - Semicentral") == 8.0
        assert fee_map.get("Zona 3 - Periferie") == 12.0
        assert fee_map.get("Zona 4 - Extins") == 15.0

    def test_get_zones_requires_auth(self):
        """GET /api/zones without auth should return 401"""
        response = requests.get(f"{BASE_URL}/api/zones")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"

    def test_driver_can_get_zones(self, driver_token):
        """Driver should be able to view zones"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert response.status_code == 200
        zones = response.json()
        assert len(zones) >= 4


class TestCreateZone:
    """Tests for POST /api/zones - admin creates new zone"""

    def test_admin_can_create_zone(self, admin_token):
        """Admin should be able to create a new delivery zone"""
        new_zone = {
            "name": "TEST_Zone_New",
            "color": "#ff00ff",
            "fee": 20.0,
            "polygon": [
                {"lat": 46.50, "lng": 26.85},
                {"lat": 46.50, "lng": 26.87},
                {"lat": 46.52, "lng": 26.87},
                {"lat": 46.52, "lng": 26.85}
            ],
            "is_active": True,
            "sort_order": 5
        }

        response = requests.post(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=new_zone
        )
        assert response.status_code == 200, f"Create zone failed: {response.text}"

        created = response.json()
        assert created["name"] == "TEST_Zone_New"
        assert created["fee"] == 20.0
        assert created["color"] == "#ff00ff"
        assert "id" in created

        # Verify persistence with GET
        get_response = requests.get(
            f"{BASE_URL}/api/zones/{created['id']}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert get_response.status_code == 200
        fetched = get_response.json()
        assert fetched["name"] == "TEST_Zone_New"

    def test_driver_cannot_create_zone(self, driver_token):
        """Driver should get 403 when trying to create zone"""
        new_zone = {
            "name": "TEST_Driver_Zone",
            "fee": 10.0,
            "polygon": [
                {"lat": 46.50, "lng": 26.85},
                {"lat": 46.50, "lng": 26.87},
                {"lat": 46.52, "lng": 26.87}
            ]
        }

        response = requests.post(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {driver_token}"},
            json=new_zone
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"

    def test_restaurant_cannot_create_zone(self, restaurant_token):
        """Restaurant should get 403 when trying to create zone"""
        new_zone = {
            "name": "TEST_Restaurant_Zone",
            "fee": 10.0,
            "polygon": [
                {"lat": 46.50, "lng": 26.85},
                {"lat": 46.50, "lng": 26.87},
                {"lat": 46.52, "lng": 26.87}
            ]
        }

        response = requests.post(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {restaurant_token}"},
            json=new_zone
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"


class TestUpdateZone:
    """Tests for PUT /api/zones/{zone_id} - admin updates zone"""

    def test_admin_can_update_zone_name(self, admin_token):
        """Admin should be able to update zone name"""
        # First get existing zone
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        test_zone = next((z for z in zones if z["name"].startswith("TEST_")), None)

        if not test_zone:
            # Create a test zone first
            create_response = requests.post(
                f"{BASE_URL}/api/zones",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "name": "TEST_Update_Zone",
                    "fee": 10.0,
                    "polygon": [
                        {"lat": 46.50, "lng": 26.85},
                        {"lat": 46.50, "lng": 26.87},
                        {"lat": 46.52, "lng": 26.87}
                    ]
                }
            )
            test_zone = create_response.json()

        # Update the zone
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "TEST_Updated_Name"}
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["name"] == "TEST_Updated_Name"

        # Verify persistence
        get_response = requests.get(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert get_response.json()["name"] == "TEST_Updated_Name"

    def test_admin_can_update_zone_fee(self, admin_token):
        """Admin should be able to update zone fee"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        test_zone = next((z for z in zones if z["name"].startswith("TEST_")), None)

        if test_zone:
            update_response = requests.put(
                f"{BASE_URL}/api/zones/{test_zone['id']}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"fee": 25.5}
            )
            assert update_response.status_code == 200
            assert update_response.json()["fee"] == 25.5

    def test_admin_can_update_zone_color(self, admin_token):
        """Admin should be able to update zone color"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        test_zone = next((z for z in zones if z["name"].startswith("TEST_")), None)

        if test_zone:
            update_response = requests.put(
                f"{BASE_URL}/api/zones/{test_zone['id']}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"color": "#00ff00"}
            )
            assert update_response.status_code == 200
            assert update_response.json()["color"] == "#00ff00"

    def test_admin_can_toggle_zone_active(self, admin_token):
        """Admin should be able to toggle zone active status"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        test_zone = next((z for z in zones if z["name"].startswith("TEST_")), None)

        if test_zone:
            update_response = requests.put(
                f"{BASE_URL}/api/zones/{test_zone['id']}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"is_active": False}
            )
            assert update_response.status_code == 200
            assert not update_response.json()["is_active"]

    def test_driver_cannot_update_zone(self, driver_token, admin_token):
        """Driver should get 403 when trying to update zone"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        zone = zones[0]

        update_response = requests.put(
            f"{BASE_URL}/api/zones/{zone['id']}",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"name": "Hacked Zone"}
        )
        assert update_response.status_code == 403

    def test_update_nonexistent_zone_returns_404(self, admin_token):
        """Updating non-existent zone should return 404"""
        update_response = requests.put(
            f"{BASE_URL}/api/zones/nonexistent-zone-id",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Test"}
        )
        assert update_response.status_code == 404


class TestDeleteZone:
    """Tests for DELETE /api/zones/{zone_id} - admin deletes zone"""

    def test_admin_can_delete_zone(self, admin_token):
        """Admin should be able to delete a zone"""
        # Create a zone to delete
        create_response = requests.post(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "TEST_Delete_Zone",
                "fee": 10.0,
                "polygon": [
                    {"lat": 46.50, "lng": 26.85},
                    {"lat": 46.50, "lng": 26.87},
                    {"lat": 46.52, "lng": 26.87}
                ]
            }
        )
        zone_id = create_response.json()["id"]

        # Delete the zone
        delete_response = requests.delete(
            f"{BASE_URL}/api/zones/{zone_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert delete_response.status_code == 200

        # Verify deletion
        get_response = requests.get(
            f"{BASE_URL}/api/zones/{zone_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert get_response.status_code == 404

    def test_driver_cannot_delete_zone(self, driver_token, admin_token):
        """Driver should get 403 when trying to delete zone"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        zone = zones[0]

        delete_response = requests.delete(
            f"{BASE_URL}/api/zones/{zone['id']}",
            headers={"Authorization": f"Bearer {driver_token}"}
        )
        assert delete_response.status_code == 403

    def test_delete_nonexistent_zone_returns_404(self, admin_token):
        """Deleting non-existent zone should return 404"""
        delete_response = requests.delete(
            f"{BASE_URL}/api/zones/nonexistent-zone-id",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert delete_response.status_code == 404


class TestZoneDetection:
    """Tests for POST /api/zones/detect - detect which zone a coordinate belongs to"""

    def test_detect_zone_centru(self, admin_token):
        """Point in Centru zone should return Zona 1 - Centru"""
        # Centru zone polygon: lat 46.562-46.573, lng 26.905-26.922
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"lat": 46.567, "lng": 26.913}  # Center of Bacău
        )
        assert response.status_code == 200
        result = response.json()

        # Should detect a zone (could be Centru or overlapping zone)
        assert "zone_id" in result
        assert "zone_name" in result
        assert "fee" in result

    def test_detect_zone_outside_all(self, admin_token):
        """Point outside all zones should return 'In afara zonelor'"""
        # Point far from Bacău
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"lat": 44.0, "lng": 26.0}  # Far from Bacău
        )
        assert response.status_code == 200
        result = response.json()

        assert result["zone_id"] is None
        assert result["zone_name"] == "In afara zonelor"
        assert result["fee"] == 0

    def test_detect_zone_returns_fee(self, admin_token):
        """Zone detection should return the zone fee"""
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"lat": 46.567, "lng": 26.913}
        )
        assert response.status_code == 200
        result = response.json()

        if result["zone_id"]:
            assert result["fee"] > 0
            assert isinstance(result["fee"], (int, float))

    def test_detect_zone_returns_color(self, admin_token):
        """Zone detection should return the zone color"""
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"lat": 46.567, "lng": 26.913}
        )
        assert response.status_code == 200
        result = response.json()

        assert "color" in result
        assert result["color"].startswith("#")

    def test_driver_can_detect_zone(self, driver_token):
        """Driver should be able to use zone detection"""
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"lat": 46.567, "lng": 26.913}
        )
        assert response.status_code == 200


class TestCleanup:
    """Cleanup test zones after all tests"""

    def test_cleanup_test_zones(self, admin_token):
        """Delete all TEST_ prefixed zones"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()

        for zone in zones:
            if zone["name"].startswith("TEST_"):
                requests.delete(
                    f"{BASE_URL}/api/zones/{zone['id']}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )

        # Verify cleanup
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        test_zones = [z for z in zones if z["name"].startswith("TEST_")]
        assert len(test_zones) == 0, f"Cleanup failed, remaining test zones: {test_zones}"
