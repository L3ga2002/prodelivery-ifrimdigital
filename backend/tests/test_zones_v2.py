"""
Test suite for Delivery Zones feature - 4 Sectors × 3 Zones
Tests: GET/POST/PUT/DELETE /api/zones and POST /api/zones/detect
Sectors: Nord, Centru, Sud, Nord Extrem
Fixed fees: Zone 1 = 14 lei, Zone 2 = 22 lei, Zone 3 = 33 lei
"""
import pytest
import requests
from tests._settings import BASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD, DRIVER_EMAIL, DRIVER_PASSWORD

# Expected zone structure
EXPECTED_SECTORS = ["Nord", "Centru", "Sud", "Nord Extrem"]
FIXED_ZONE_FEES = {1: 14.0, 2: 22.0, 3: 33.0}


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


class TestGetZones:
    """Tests for GET /api/zones - list all delivery zones"""

    def test_get_zones_returns_12_seeded_zones(self, admin_token):
        """GET /api/zones should return 12 zones (4 sectors × 3 zones)"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        zones = response.json()

        # Should have 12 zones (4 sectors × 3 zone levels)
        assert len(zones) >= 12, f"Expected at least 12 zones, got {len(zones)}"

    def test_zones_have_sector_field(self, admin_token):
        """All zones should have sector field"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()

        for zone in zones:
            assert "sector" in zone, f"Zone {zone['name']} missing sector field"
            assert zone["sector"] is not None, f"Zone {zone['name']} has null sector"

    def test_zones_have_zone_level_field(self, admin_token):
        """All zones should have zone_level field (1, 2, or 3)"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()

        for zone in zones:
            assert "zone_level" in zone, f"Zone {zone['name']} missing zone_level field"
            assert zone["zone_level"] in [1, 2, 3], f"Zone {zone['name']} has invalid zone_level: {zone['zone_level']}"

    def test_zones_contain_all_4_sectors(self, admin_token):
        """Zones should contain all 4 sectors: Nord, Centru, Sud, Nord Extrem"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()

        sectors_found = set(z["sector"] for z in zones if z.get("sector"))

        for expected_sector in EXPECTED_SECTORS:
            assert expected_sector in sectors_found, f"Missing sector: {expected_sector}"

    def test_each_sector_has_3_zones(self, admin_token):
        """Each sector should have exactly 3 zones (levels 1, 2, 3)"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()

        # Group by sector
        sector_zones = {}
        for zone in zones:
            sector = zone.get("sector")
            if sector:
                if sector not in sector_zones:
                    sector_zones[sector] = []
                sector_zones[sector].append(zone)

        for sector in EXPECTED_SECTORS:
            assert sector in sector_zones, f"Sector {sector} not found"
            assert len(sector_zones[sector]) == 3, f"Sector {sector} should have 3 zones, got {len(sector_zones[sector])}"

    def test_fixed_fees_applied_correctly(self, admin_token):
        """Zone fees should match fixed pricing: Zone 1=14, Zone 2=22, Zone 3=33"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()

        for zone in zones:
            zone_level = zone.get("zone_level")
            expected_fee = FIXED_ZONE_FEES.get(zone_level)
            if expected_fee:
                assert zone["fee"] == expected_fee, f"Zone {zone['name']} has fee {zone['fee']}, expected {expected_fee}"

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


class TestCreateZone:
    """Tests for POST /api/zones - admin creates new zone"""

    def test_admin_can_create_zone_with_sector(self, admin_token):
        """Admin should be able to create a new zone with sector and zone_level"""
        new_zone = {
            "sector": "TEST_Sector",
            "zone_level": 2,
            "name": "TEST_New_Zone",
            "color": "#ff00ff",
            "polygon": [
                {"lat": 46.50, "lng": 26.85},
                {"lat": 46.50, "lng": 26.87},
                {"lat": 46.52, "lng": 26.87},
                {"lat": 46.52, "lng": 26.85}
            ],
            "is_active": True,
            "sort_order": 100
        }

        response = requests.post(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=new_zone
        )
        assert response.status_code == 200, f"Create zone failed: {response.text}"

        created = response.json()
        assert created["name"] == "TEST_New_Zone"
        assert created["sector"] == "TEST_Sector"
        assert created["zone_level"] == 2
        # Fee should be auto-set to 22 for zone_level 2
        assert created["fee"] == 22.0, f"Expected fee 22.0 for zone_level 2, got {created['fee']}"

    def test_zone_fee_auto_set_by_level(self, admin_token):
        """Zone fee should be automatically set based on zone_level"""
        for level, expected_fee in FIXED_ZONE_FEES.items():
            new_zone = {
                "sector": "TEST_AutoFee",
                "zone_level": level,
                "name": f"TEST_AutoFee_Level{level}",
                "polygon": [
                    {"lat": 46.50, "lng": 26.85},
                    {"lat": 46.50, "lng": 26.87},
                    {"lat": 46.52, "lng": 26.87}
                ]
            }

            response = requests.post(
                f"{BASE_URL}/api/zones",
                headers={"Authorization": f"Bearer {admin_token}"},
                json=new_zone
            )
            assert response.status_code == 200
            created = response.json()
            assert created["fee"] == expected_fee, f"Level {level} should have fee {expected_fee}, got {created['fee']}"

    def test_driver_cannot_create_zone(self, driver_token):
        """Driver should get 403 when trying to create zone"""
        new_zone = {
            "sector": "TEST_Driver",
            "zone_level": 1,
            "name": "TEST_Driver_Zone",
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
        assert response.status_code == 403


class TestUpdateZone:
    """Tests for PUT /api/zones/{zone_id} - admin updates zone"""

    def test_admin_can_update_zone_sector(self, admin_token):
        """Admin should be able to update zone sector"""
        # Get a test zone
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        test_zone = next((z for z in zones if z["name"].startswith("TEST_")), None)

        if not test_zone:
            # Create one
            create_response = requests.post(
                f"{BASE_URL}/api/zones",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "sector": "TEST_Original",
                    "zone_level": 1,
                    "name": "TEST_Update_Sector",
                    "polygon": [
                        {"lat": 46.50, "lng": 26.85},
                        {"lat": 46.50, "lng": 26.87},
                        {"lat": 46.52, "lng": 26.87}
                    ]
                }
            )
            test_zone = create_response.json()

        # Update sector
        update_response = requests.put(
            f"{BASE_URL}/api/zones/{test_zone['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"sector": "TEST_Updated_Sector"}
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["sector"] == "TEST_Updated_Sector"

    def test_admin_can_update_zone_level_and_fee_updates(self, admin_token):
        """When zone_level is updated, fee should auto-update"""
        # Get a test zone
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        test_zone = next((z for z in zones if z["name"].startswith("TEST_")), None)

        if test_zone:
            # Update zone_level to 3
            update_response = requests.put(
                f"{BASE_URL}/api/zones/{test_zone['id']}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"zone_level": 3}
            )
            assert update_response.status_code == 200
            updated = update_response.json()
            assert updated["zone_level"] == 3
            assert updated["fee"] == 33.0, f"Fee should auto-update to 33 for level 3, got {updated['fee']}"

    def test_admin_can_update_polygon(self, admin_token):
        """Admin should be able to update zone polygon (redraw contour)"""
        response = requests.get(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        zones = response.json()
        test_zone = next((z for z in zones if z["name"].startswith("TEST_")), None)

        if test_zone:
            new_polygon = [
                {"lat": 46.55, "lng": 26.90},
                {"lat": 46.55, "lng": 26.92},
                {"lat": 46.57, "lng": 26.92},
                {"lat": 46.57, "lng": 26.90}
            ]

            update_response = requests.put(
                f"{BASE_URL}/api/zones/{test_zone['id']}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"polygon": new_polygon}
            )
            assert update_response.status_code == 200
            updated = update_response.json()
            assert len(updated["polygon"]) == 4

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


class TestDeleteZone:
    """Tests for DELETE /api/zones/{zone_id} - admin deletes zone"""

    def test_admin_can_delete_zone(self, admin_token):
        """Admin should be able to delete a zone"""
        # Create a zone to delete
        create_response = requests.post(
            f"{BASE_URL}/api/zones",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "sector": "TEST_Delete",
                "zone_level": 1,
                "name": "TEST_Delete_Zone",
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


class TestZoneDetection:
    """Tests for POST /api/zones/detect - detect which zone a coordinate belongs to"""

    def test_detect_zone_returns_sector_and_level(self, admin_token):
        """Zone detection should return sector and zone_level"""
        # Test with Nord sector center
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"lat": 46.5905, "lng": 26.9085}
        )
        assert response.status_code == 200
        result = response.json()

        assert "sector" in result
        assert "zone_level" in result
        assert "fee" in result

    def test_detect_zone_outside_all(self, admin_token):
        """Point outside all zones should return 'In afara zonelor'"""
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"lat": 44.0, "lng": 26.0}
        )
        assert response.status_code == 200
        result = response.json()

        assert result["zone_id"] is None
        assert result["zone_name"] == "In afara zonelor"
        assert result["sector"] is None
        assert result["zone_level"] is None
        assert result["fee"] == 0

    def test_detect_zone_returns_correct_fee(self, admin_token):
        """Zone detection should return correct fixed fee based on zone_level"""
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"lat": 46.5905, "lng": 26.9085}
        )
        assert response.status_code == 200
        result = response.json()

        if result["zone_id"]:
            zone_level = result["zone_level"]
            expected_fee = FIXED_ZONE_FEES.get(zone_level)
            if expected_fee:
                assert result["fee"] == expected_fee, f"Fee should be {expected_fee} for level {zone_level}"

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
            if zone["name"].startswith("TEST_") or zone.get("sector", "").startswith("TEST_"):
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
        test_zones = [z for z in zones if z["name"].startswith("TEST_") or z.get("sector", "").startswith("TEST_")]
        assert len(test_zones) == 0, f"Cleanup failed, remaining test zones: {test_zones}"
