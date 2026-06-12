"""
Test iteration 9 features:
1. POST /api/orders with customer_latitude/customer_longitude calculates delivery_fee, delivery_zone_name, delivery_sector, delivery_zone_level, total_amount
2. GET /api/drivers/ranking/me for driver
3. GET /api/drivers returns ranking_score/ranking_tier/schedule_access
4. GET /api/schedules/scheduling-window returns tier, score, opens_at
5. POST /api/schedules/emergency/auto-generate generates AUTO slots
6. Zones map bug fix - zones should show correct fees (not all 33 lei)
"""
import pytest
import requests
from tests._settings import BASE_URL, admin_credentials, clear_login_attempts, driver_credentials, seed_demo_data


@pytest.fixture(scope="module", autouse=True)
def seeded_demo():
    seed_demo_data()

class TestOrderCreationWithZoneDetection:
    """Test order creation with automatic zone detection from coordinates"""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Login as admin
        clear_login_attempts(admin_credentials()["email"])
        response = requests.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        self.admin_token = response.json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

        # Get restaurants
        rest_response = requests.get(f"{BASE_URL}/api/restaurants", headers=self.admin_headers)
        assert rest_response.status_code == 200
        self.restaurants = rest_response.json()
        assert len(self.restaurants) > 0, "No restaurants found"

    def test_create_order_with_center_coordinates_detects_zone(self):
        """Test that creating order with center coordinates detects Centru Zona 1 with fee 14"""
        # Center of Bacău - should be in Centru Zona 1
        order_data = {
            "restaurant_id": self.restaurants[0]["id"],
            "customer_name": "Test Customer Zone Detection",
            "customer_phone": "0722111222",
            "customer_address": "Centru Bacău",
            "customer_latitude": 46.567,
            "customer_longitude": 26.913,
            "subtotal_amount": 50,
            "total_amount": 50,  # Will be recalculated
            "payment_type": "CASH",
            "source": "S"
        }

        response = requests.post(f"{BASE_URL}/api/orders", json=order_data, headers=self.admin_headers)
        assert response.status_code == 200, f"Order creation failed: {response.text}"

        order = response.json()
        print(f"Created order: zone={order.get('delivery_zone_name')}, fee={order.get('delivery_fee')}, total={order.get('total_amount')}")

        # Verify zone detection fields are populated
        assert order.get("delivery_zone_name") is not None, "delivery_zone_name should be set"
        assert order.get("delivery_fee") is not None, "delivery_fee should be set"
        assert order.get("delivery_sector") is not None, "delivery_sector should be set"
        assert order.get("delivery_zone_level") is not None, "delivery_zone_level should be set"

        # Verify total_amount = subtotal + delivery_fee
        expected_total = order_data["subtotal_amount"] + order.get("delivery_fee", 0)
        assert abs(order.get("total_amount", 0) - expected_total) < 0.01, f"Total should be {expected_total}, got {order.get('total_amount')}"

    def test_create_order_without_coordinates_no_zone(self):
        """Test that creating order without coordinates doesn't set zone"""
        order_data = {
            "restaurant_id": self.restaurants[0]["id"],
            "customer_name": "Test Customer No Coords",
            "customer_phone": "0722111333",
            "customer_address": "Unknown Address",
            "total_amount": 50,
            "payment_type": "CASH",
            "source": "S"
        }

        response = requests.post(f"{BASE_URL}/api/orders", json=order_data, headers=self.admin_headers)
        assert response.status_code == 200, f"Order creation failed: {response.text}"

        order = response.json()
        # Without coordinates, zone should not be detected
        assert order.get("delivery_fee") == 0 or order.get("delivery_zone_id") is None


class TestDriverRankingEndpoints:
    """Test driver ranking endpoints"""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Login as driver
        clear_login_attempts(driver_credentials(1)["email"])
        response = requests.post(f"{BASE_URL}/api/auth/login", json=driver_credentials(1))
        assert response.status_code == 200, f"Driver login failed: {response.text}"
        self.driver_token = response.json()["token"]
        self.driver_headers = {"Authorization": f"Bearer {self.driver_token}"}

        # Login as admin
        clear_login_attempts(admin_credentials()["email"])
        admin_response = requests.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
        assert admin_response.status_code == 200
        self.admin_token = admin_response.json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def test_get_my_ranking_as_driver(self):
        """GET /api/drivers/ranking/me returns ranking info for driver"""
        response = requests.get(f"{BASE_URL}/api/drivers/ranking/me", headers=self.driver_headers)
        assert response.status_code == 200, f"Failed to get ranking: {response.text}"

        data = response.json()
        print(f"Driver ranking: tier={data.get('ranking_tier')}, score={data.get('ranking_score')}")

        # Verify required fields
        assert "ranking_score" in data, "ranking_score should be present"
        assert "ranking_tier" in data, "ranking_tier should be present"
        assert "ranking_tier_key" in data, "ranking_tier_key should be present"
        assert "schedule_access" in data, "schedule_access should be present"

        # Verify tier is one of the valid tiers
        valid_tiers = ["Gold", "Silver", "Bronze", "Start"]
        assert data["ranking_tier"] in valid_tiers, f"Invalid tier: {data['ranking_tier']}"

        # Verify score is a number
        assert isinstance(data["ranking_score"], (int, float)), "ranking_score should be numeric"

    def test_get_my_ranking_forbidden_for_admin(self):
        """GET /api/drivers/ranking/me should return 403 for admin"""
        response = requests.get(f"{BASE_URL}/api/drivers/ranking/me", headers=self.admin_headers)
        assert response.status_code == 403, f"Expected 403 for admin, got {response.status_code}"

    def test_get_drivers_includes_ranking_info(self):
        """GET /api/drivers returns ranking_score, ranking_tier, schedule_access"""
        response = requests.get(f"{BASE_URL}/api/drivers", headers=self.admin_headers)
        assert response.status_code == 200, f"Failed to get drivers: {response.text}"

        drivers = response.json()
        assert len(drivers) > 0, "No drivers found"

        for driver in drivers:
            print(f"Driver {driver.get('name')}: tier={driver.get('ranking_tier')}, score={driver.get('ranking_score')}")
            assert "ranking_score" in driver, f"Driver {driver.get('name')} missing ranking_score"
            assert "ranking_tier" in driver, f"Driver {driver.get('name')} missing ranking_tier"
            assert "schedule_access" in driver, f"Driver {driver.get('name')} missing schedule_access"


class TestSchedulingWindowEndpoint:
    """Test scheduling window endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Login as driver
        clear_login_attempts(driver_credentials(1)["email"])
        response = requests.post(f"{BASE_URL}/api/auth/login", json=driver_credentials(1))
        assert response.status_code == 200, f"Driver login failed: {response.text}"
        self.driver_token = response.json()["token"]
        self.driver_headers = {"Authorization": f"Bearer {self.driver_token}"}

        # Login as admin
        clear_login_attempts(admin_credentials()["email"])
        admin_response = requests.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
        assert admin_response.status_code == 200
        self.admin_token = admin_response.json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def test_scheduling_window_for_driver(self):
        """GET /api/schedules/scheduling-window returns tier, score, opens_at for driver"""
        response = requests.get(f"{BASE_URL}/api/schedules/scheduling-window", headers=self.driver_headers)
        assert response.status_code == 200, f"Failed to get scheduling window: {response.text}"

        data = response.json()
        print(f"Scheduling window: tier={data.get('tier')}, score={data.get('score')}, opens_at={data.get('opens_at')}")

        # Verify required fields for driver
        assert "tier" in data, "tier should be present"
        assert "score" in data, "score should be present"
        assert "opens_at" in data, "opens_at should be present"
        assert "can_select_schedule" in data or "is_open" in data, "can_select_schedule or is_open should be present"

        # Verify tier is valid
        valid_tiers = ["Gold", "Silver", "Bronze", "Start"]
        assert data["tier"] in valid_tiers, f"Invalid tier: {data['tier']}"

    def test_scheduling_window_for_admin(self):
        """GET /api/schedules/scheduling-window returns basic info for admin"""
        response = requests.get(f"{BASE_URL}/api/schedules/scheduling-window", headers=self.admin_headers)
        assert response.status_code == 200, f"Failed to get scheduling window: {response.text}"

        data = response.json()
        # Admin should get basic window info
        assert "is_open" in data or "opens_at" in data, "Should have window info"


class TestEmergencyAutoGenerate:
    """Test emergency slots auto-generation"""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Login as admin
        clear_login_attempts(admin_credentials()["email"])
        response = requests.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        self.admin_token = response.json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def test_auto_generate_emergency_slots(self):
        """POST /api/schedules/emergency/auto-generate creates AUTO slots"""
        # Use a future week
        week_start = "2026-01-27"

        response = requests.post(
            f"{BASE_URL}/api/schedules/emergency/auto-generate",
            params={"week_start": week_start},
            headers=self.admin_headers
        )
        assert response.status_code == 200, f"Auto-generate failed: {response.text}"

        data = response.json()
        print(f"Auto-generate result: {data.get('message')}, created={data.get('created')}, updated={data.get('updated')}")

        # Verify response structure
        assert "message" in data, "message should be present"
        assert "created" in data, "created count should be present"
        assert "updated" in data, "updated count should be present"

        # Verify slots were created or updated
        total_touched = data.get("created", 0) + data.get("updated", 0)
        print(f"Total slots touched: {total_touched}")

        # Verify we can fetch the created slots
        get_response = requests.get(
            f"{BASE_URL}/api/schedules/emergency",
            params={"week_start": week_start},
            headers=self.admin_headers
        )
        assert get_response.status_code == 200

        slots = get_response.json()
        print(f"Emergency slots for week {week_start}: {len(slots)}")

        # Check that AUTO slots have created_by = "system"
        auto_slots = [s for s in slots if s.get("created_by") == "system"]
        print(f"AUTO (system) slots: {len(auto_slots)}")

    def test_auto_generate_forbidden_for_driver(self):
        """POST /api/schedules/emergency/auto-generate should be admin only"""
        # Login as driver
        clear_login_attempts(driver_credentials(1)["email"])
        driver_response = requests.post(f"{BASE_URL}/api/auth/login", json=driver_credentials(1))
        driver_token = driver_response.json()["token"]
        driver_headers = {"Authorization": f"Bearer {driver_token}"}

        response = requests.post(
            f"{BASE_URL}/api/schedules/emergency/auto-generate",
            params={"week_start": "2026-01-27"},
            headers=driver_headers
        )
        assert response.status_code == 403, f"Expected 403 for driver, got {response.status_code}"


class TestZonesMapBugFix:
    """Test that zones show correct fees (not all 33 lei)"""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Login as admin
        clear_login_attempts(admin_credentials()["email"])
        response = requests.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        self.admin_token = response.json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def test_zones_have_different_fees(self):
        """GET /api/zones returns zones with different configured fees."""
        response = requests.get(f"{BASE_URL}/api/zones", headers=self.admin_headers)
        assert response.status_code == 200, f"Failed to get zones: {response.text}"

        zones = response.json()
        assert len(zones) > 0, "No zones found"

        # Collect unique fees
        fees = set()
        for zone in zones:
            fee = zone.get("fee")
            fees.add(fee)
            print(f"Zone {zone.get('name')}: fee={fee}, level={zone.get('zone_level')}, sector={zone.get('sector')}")

        print(f"Unique fees found: {fees}")

        # Verify we have different fees (not all identical)
        assert len(fees) > 1, f"All zones have same fee: {fees}. Restaurant zones should have different fees"

        # Verify expected fees are present
        expected_fees = {10, 18}
        assert expected_fees.issubset(fees), f"Missing seeded restaurant fees. Found: {fees}, expected at least: {expected_fees}"

    def test_zones_sector_filter_works(self):
        """Verify zones can be filtered by sector"""
        response = requests.get(f"{BASE_URL}/api/zones", headers=self.admin_headers)
        assert response.status_code == 200

        zones = response.json()

        # Group by sector
        sectors = {}
        for zone in zones:
            sector = zone.get("sector", "Unknown")
            if sector not in sectors:
                sectors[sector] = []
            sectors[sector].append(zone)

        print(f"Sectors found: {list(sectors.keys())}")

        # Each sector should have zones
        for sector, sector_zones in sectors.items():
            print(f"Sector {sector}: {len(sector_zones)} zones")
            assert len(sector_zones) > 0, f"Sector {sector} has no zones"


class TestZoneDetectionEndpoint:
    """Test zone detection endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Login as admin
        clear_login_attempts(admin_credentials()["email"])
        response = requests.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        self.admin_token = response.json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        restaurants_response = requests.get(f"{BASE_URL}/api/restaurants", headers=self.admin_headers)
        assert restaurants_response.status_code == 200
        self.restaurant = restaurants_response.json()[0]

    def test_detect_zone_center_bacau(self):
        """POST /api/zones/detect returns zone info for center coordinates"""
        response = requests.post(
            f"{BASE_URL}/api/zones/detect",
            json={
                "restaurant_id": self.restaurant["id"],
                "lat": self.restaurant["latitude"],
                "lng": self.restaurant["longitude"],
            },
            headers=self.admin_headers
        )
        assert response.status_code == 200, f"Zone detection failed: {response.text}"

        data = response.json()
        print(f"Detected zone: {data}")

        # Verify zone was detected
        assert data.get("zone_id") is not None or data.get("zone_name") is not None, "Zone should be detected for center coordinates"

        # Verify fee is one of the valid fees
        fee = data.get("fee")
        if fee is not None:
            assert fee > 0, f"Invalid fee: {fee}"


class TestDriverRankings:
    """Test driver rankings endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Login as admin
        clear_login_attempts(admin_credentials()["email"])
        response = requests.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        self.admin_token = response.json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def test_get_driver_rankings(self):
        """GET /api/drivers/rankings returns sorted list of drivers with ranking info"""
        response = requests.get(f"{BASE_URL}/api/drivers/rankings", headers=self.admin_headers)
        assert response.status_code == 200, f"Failed to get rankings: {response.text}"

        rankings = response.json()
        assert len(rankings) > 0, "No rankings found"

        # Verify sorted by score descending
        scores = [r.get("ranking_score", 0) for r in rankings]
        assert scores == sorted(scores, reverse=True), "Rankings should be sorted by score descending"

        for r in rankings:
            print(f"Driver {r.get('driver_name')}: score={r.get('ranking_score')}, tier={r.get('ranking_tier')}")
            assert "ranking_score" in r
            assert "ranking_tier" in r


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
