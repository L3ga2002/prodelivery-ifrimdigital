"""
Phase 3 Backend Tests - Schedule System, Zones, and Order Updates
Tests:
1. POST /api/seed - creates orders with zone field and DELIVERED orders with driver assignments
2. GET /api/schedules/scheduling-window - returns is_open boolean
3. POST /api/schedules with source=admin can set night hours (22:00, 23:00, 00:00, 01:00)
4. POST /api/schedules with source=driver rejects hours outside 10:00-22:00
5. GET /api/schedules/admin/summary - returns orders_by_zone per driver
6. Admin schedule preserves added_by field on slots
"""

import pytest
import requests
from tests._settings import BASE_URL, admin_credentials, driver_credentials

class TestPhase3Features:
    """Tests for Phase 3: Schedule system, zones, and order updates"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - seed data and get tokens"""
        # Seed data
        response = requests.post(f"{BASE_URL}/api/seed")
        assert response.status_code == 200, f"Seed failed: {response.text}"

        # Get admin token
        login_res = requests.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
        assert login_res.status_code == 200, "Admin login failed"
        self.admin_token = login_res.json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

        # Get driver token
        driver_login = requests.post(f"{BASE_URL}/api/auth/login", json=driver_credentials(1))
        assert driver_login.status_code == 200, "Driver login failed"
        self.driver_token = driver_login.json()["token"]
        self.driver_headers = {"Authorization": f"Bearer {self.driver_token}"}
        self.driver_id = driver_login.json()["user"]["driver_id"]

    # ========== SEED DATA TESTS ==========
    def test_seed_creates_orders_with_zone_field(self):
        """Test POST /api/seed creates orders with zone field"""
        # Check orders have zone field
        response = requests.get(f"{BASE_URL}/api/orders", headers=self.admin_headers)
        assert response.status_code == 200
        orders = response.json()

        # Verify orders exist with zone field
        orders_with_zone = [o for o in orders if o.get("zone") is not None]
        assert len(orders_with_zone) > 0, "No orders have zone field"

        # Verify zones are valid
        valid_zones = ["Zona 1", "Zona 2", "Zona 3", "Zona 4"]
        for order in orders_with_zone:
            assert order["zone"] in valid_zones, f"Invalid zone: {order['zone']}"
        print(f"✓ Found {len(orders_with_zone)} orders with valid zone field")

    def test_seed_creates_delivered_orders_with_driver(self):
        """Test POST /api/seed creates DELIVERED orders with driver assignments"""
        response = requests.get(f"{BASE_URL}/api/orders", headers=self.admin_headers)
        assert response.status_code == 200
        orders = response.json()

        # Filter delivered orders
        delivered = [o for o in orders if o.get("status") == "DELIVERED"]
        assert len(delivered) > 0, "No delivered orders found"

        # Verify delivered orders have driver_id
        delivered_with_driver = [o for o in delivered if o.get("driver_id") is not None]
        assert len(delivered_with_driver) > 0, "No delivered orders have driver assignment"
        print(f"✓ Found {len(delivered_with_driver)} DELIVERED orders with driver assignment")

    # ========== SCHEDULING WINDOW TESTS ==========
    def test_scheduling_window_returns_is_open(self):
        """Test GET /api/schedules/scheduling-window returns is_open boolean"""
        response = requests.get(
            f"{BASE_URL}/api/schedules/scheduling-window",
            headers=self.admin_headers
        )
        assert response.status_code == 200
        data = response.json()

        assert "is_open" in data, "Response missing is_open field"
        assert isinstance(data["is_open"], bool), "is_open should be boolean"
        assert "opens_at" in data, "Response missing opens_at field"
        assert "closes_at" in data, "Response missing closes_at field"
        print(f"✓ Scheduling window: is_open={data['is_open']}, opens_at={data['opens_at']}, closes_at={data['closes_at']}")

    # ========== ADMIN SCHEDULE TESTS ==========
    def test_admin_can_set_night_hours(self):
        """Test POST /api/schedules with source=admin can set night hours (22:00-02:00)"""
        # Admin sets night hours
        schedule_data = {
            "driver_id": self.driver_id,
            "week_start": "2026-01-19",
            "slots": {
                "monday": [
                    {"start": "22:00", "end": "23:00", "added_by": "admin"},
                    {"start": "23:00", "end": "00:00", "added_by": "admin"},
                    {"start": "00:00", "end": "01:00", "added_by": "admin"},
                    {"start": "01:00", "end": "02:00", "added_by": "admin"}
                ]
            },
            "source": "admin"
        }

        response = requests.post(
            f"{BASE_URL}/api/schedules",
            json=schedule_data,
            headers=self.admin_headers
        )
        assert response.status_code == 200, f"Admin should be able to set night hours: {response.text}"
        print("✓ Admin successfully set night hours (22:00, 23:00, 00:00, 01:00)")

    def test_admin_can_set_day_hours(self):
        """Test POST /api/schedules with source=admin can set day hours (10:00-22:00)"""
        schedule_data = {
            "driver_id": self.driver_id,
            "week_start": "2026-01-26",
            "slots": {
                "tuesday": [
                    {"start": "10:00", "end": "11:00", "added_by": "admin"},
                    {"start": "14:00", "end": "15:00", "added_by": "admin"}
                ]
            },
            "source": "admin"
        }

        response = requests.post(
            f"{BASE_URL}/api/schedules",
            json=schedule_data,
            headers=self.admin_headers
        )
        assert response.status_code == 200, f"Admin should set day hours: {response.text}"
        print("✓ Admin successfully set day hours (10:00, 14:00)")

    def test_admin_schedule_preserves_added_by_field(self):
        """Test admin schedule preserves added_by field on slots"""
        # Create schedule with admin
        schedule_data = {
            "driver_id": self.driver_id,
            "week_start": "2026-02-02",
            "slots": {
                "wednesday": [
                    {"start": "10:00", "end": "11:00", "added_by": "admin"},
                    {"start": "22:00", "end": "23:00", "added_by": "admin"}
                ]
            },
            "source": "admin"
        }

        response = requests.post(
            f"{BASE_URL}/api/schedules",
            json=schedule_data,
            headers=self.admin_headers
        )
        assert response.status_code == 200

        # Verify by getting the schedule
        get_response = requests.get(
            f"{BASE_URL}/api/schedules/driver/{self.driver_id}?year=2026",
            headers=self.admin_headers
        )
        assert get_response.status_code == 200
        schedules = get_response.json()

        target_schedule = next((s for s in schedules if s.get("week_start") == "2026-02-02"), None)
        assert target_schedule is not None, "Schedule not found"

        wednesday_slots = target_schedule.get("slots", {}).get("wednesday", [])
        for slot in wednesday_slots:
            assert slot.get("added_by") == "admin", f"Slot missing added_by=admin: {slot}"
        print("✓ Admin schedule preserves added_by field on all slots")

    # ========== DRIVER SCHEDULE TESTS ==========
    def test_driver_rejects_night_hours(self):
        """Test POST /api/schedules with source=driver rejects hours outside 10:00-22:00"""
        # Driver tries to set 23:00 hour (should fail)
        schedule_data = {
            "driver_id": self.driver_id,
            "week_start": "2026-02-09",
            "slots": {
                "thursday": [
                    {"start": "23:00", "end": "00:00", "added_by": "driver"}
                ]
            },
            "source": "driver"
        }

        response = requests.post(
            f"{BASE_URL}/api/schedules",
            json=schedule_data,
            headers=self.driver_headers
        )
        assert response.status_code == 400, f"Driver setting 23:00 should fail: {response.text}"
        print("✓ Driver correctly rejected when setting night hour 23:00")

    def test_driver_rejects_00_hour(self):
        """Test driver rejected for 00:00 hour"""
        schedule_data = {
            "driver_id": self.driver_id,
            "week_start": "2026-02-16",
            "slots": {
                "friday": [
                    {"start": "00:00", "end": "01:00", "added_by": "driver"}
                ]
            },
            "source": "driver"
        }

        response = requests.post(
            f"{BASE_URL}/api/schedules",
            json=schedule_data,
            headers=self.driver_headers
        )
        assert response.status_code == 400, f"Driver setting 00:00 should fail: {response.text}"
        print("✓ Driver correctly rejected when setting midnight hour 00:00")

    def test_driver_can_set_allowed_hours(self):
        """Test driver can set hours within 10:00-22:00"""
        # Clean schedule for driver - setting valid hours
        schedule_data = {
            "driver_id": self.driver_id,
            "week_start": "2026-02-23",
            "slots": {
                "saturday": [
                    {"start": "10:00", "end": "11:00", "added_by": "driver"},
                    {"start": "12:00", "end": "13:00", "added_by": "driver"},
                    {"start": "21:00", "end": "22:00", "added_by": "driver"}
                ]
            },
            "source": "driver"
        }

        response = requests.post(
            f"{BASE_URL}/api/schedules",
            json=schedule_data,
            headers=self.driver_headers
        )
        assert response.status_code == 200, f"Driver should be able to set allowed hours: {response.text}"
        print("✓ Driver successfully set allowed hours (10:00, 12:00, 21:00)")

    def test_driver_boundary_hour_21_allowed(self):
        """Test driver can set 21:00 (last allowed hour before night)"""
        schedule_data = {
            "driver_id": self.driver_id,
            "week_start": "2026-03-02",
            "slots": {
                "sunday": [
                    {"start": "21:00", "end": "22:00", "added_by": "driver"}
                ]
            },
            "source": "driver"
        }

        response = requests.post(
            f"{BASE_URL}/api/schedules",
            json=schedule_data,
            headers=self.driver_headers
        )
        assert response.status_code == 200, f"Driver should set 21:00: {response.text}"
        print("✓ Driver successfully set boundary hour 21:00")

    def test_driver_boundary_hour_22_rejected(self):
        """Test driver cannot set 22:00 (first night hour)"""
        schedule_data = {
            "driver_id": self.driver_id,
            "week_start": "2026-03-09",
            "slots": {
                "monday": [
                    {"start": "22:00", "end": "23:00", "added_by": "driver"}
                ]
            },
            "source": "driver"
        }

        response = requests.post(
            f"{BASE_URL}/api/schedules",
            json=schedule_data,
            headers=self.driver_headers
        )
        assert response.status_code == 400, f"Driver setting 22:00 should fail: {response.text}"
        print("✓ Driver correctly rejected when setting boundary hour 22:00")

    # ========== ADMIN SUMMARY WITH ZONES ==========
    def test_admin_summary_returns_orders_by_zone(self):
        """Test GET /api/schedules/admin/summary returns orders_by_zone per driver"""
        response = requests.get(
            f"{BASE_URL}/api/schedules/admin/summary",
            headers=self.admin_headers
        )
        assert response.status_code == 200
        summary = response.json()

        assert isinstance(summary, list), "Summary should be a list of drivers"
        assert len(summary) > 0, "Summary should have drivers"

        # Check first driver has orders_by_zone
        for driver in summary:
            assert "driver_id" in driver, "Driver missing driver_id"
            assert "driver_name" in driver, "Driver missing driver_name"
            assert "orders_by_zone" in driver, f"Driver {driver.get('driver_name')} missing orders_by_zone"
            assert isinstance(driver["orders_by_zone"], dict), "orders_by_zone should be a dict"

        # Check at least one driver has zone data
        drivers_with_zones = [d for d in summary if len(d.get("orders_by_zone", {})) > 0]
        assert len(drivers_with_zones) > 0, "At least one driver should have zone data"
        print(f"✓ Admin summary returns orders_by_zone - {len(drivers_with_zones)} drivers with zone data")

    def test_admin_summary_zone_values(self):
        """Test admin summary zone values are valid"""
        response = requests.get(
            f"{BASE_URL}/api/schedules/admin/summary",
            headers=self.admin_headers
        )
        assert response.status_code == 200
        summary = response.json()

        valid_zones = ["Zona 1", "Zona 2", "Zona 3", "Zona 4", "Neatribuită"]

        for driver in summary:
            zones = driver.get("orders_by_zone", {})
            for zone_name, count in zones.items():
                assert zone_name in valid_zones, f"Invalid zone: {zone_name}"
                assert isinstance(count, int) and count >= 0, f"Invalid count for {zone_name}: {count}"

        print("✓ All zone values in admin summary are valid")

    def test_admin_summary_includes_total_orders_delivered(self):
        """Test admin summary includes total_orders_delivered"""
        response = requests.get(
            f"{BASE_URL}/api/schedules/admin/summary",
            headers=self.admin_headers
        )
        assert response.status_code == 200
        summary = response.json()

        for driver in summary:
            assert "total_orders_delivered" in driver, "Driver missing total_orders_delivered"
            assert isinstance(driver["total_orders_delivered"], int), "total_orders_delivered should be int"

        # Verify at least one driver has delivered orders
        drivers_with_deliveries = [d for d in summary if d.get("total_orders_delivered", 0) > 0]
        assert len(drivers_with_deliveries) > 0, "At least one driver should have delivered orders"
        print(f"✓ Admin summary includes total_orders_delivered - {len(drivers_with_deliveries)} drivers have deliveries")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
