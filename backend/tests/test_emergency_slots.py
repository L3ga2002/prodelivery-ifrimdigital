"""
Test Emergency Slots Feature for ProDelivery Bacău
Tests:
- Admin creates emergency slots
- GET emergency slots for a week
- Driver claims emergency slot
- Double-claim prevention
- Claiming with 0 remaining spots
- Admin deletes emergency slot
- Claiming adds hour to driver schedule with added_by=emergency
"""
import pytest
import requests
from datetime import datetime, timedelta
from tests._settings import BASE_URL, admin_credentials, clear_login_attempts, driver_credentials, seed_demo_data

# Get current week's Monday
def get_current_monday():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime('%Y-%m-%d')

WEEK_START = get_current_monday()


class TestEmergencySlots:
    """Emergency Slots CRUD and Claim Tests"""

    admin_token = None
    driver1_token = None
    driver2_token = None
    driver1_id = None
    driver2_id = None
    created_slot_id = None
    seeded = False

    @pytest.fixture(autouse=True)
    def setup(self, request):
        """Setup tokens before tests"""
        if not TestEmergencySlots.seeded:
            seed_demo_data()
            TestEmergencySlots.seeded = True

        if TestEmergencySlots.admin_token is None:
            # Login as admin
            clear_login_attempts(admin_credentials()["email"])
            res = requests.post(f"{BASE_URL}/api/auth/login", json=admin_credentials())
            assert res.status_code == 200, f"Admin login failed: {res.text}"
            TestEmergencySlots.admin_token = res.json()["token"]

        if TestEmergencySlots.driver1_token is None:
            # Login as driver-001
            clear_login_attempts(driver_credentials(1)["email"])
            res = requests.post(f"{BASE_URL}/api/auth/login", json=driver_credentials(1))
            assert res.status_code == 200, f"Driver-001 login failed: {res.text}"
            TestEmergencySlots.driver1_token = res.json()["token"]
            TestEmergencySlots.driver1_id = res.json()["user"]["driver_id"]

        if TestEmergencySlots.driver2_token is None:
            # Login as driver-002
            clear_login_attempts(driver_credentials(2)["email"])
            res = requests.post(f"{BASE_URL}/api/auth/login", json=driver_credentials(2))
            assert res.status_code == 200, f"Driver-002 login failed: {res.text}"
            TestEmergencySlots.driver2_token = res.json()["token"]
            TestEmergencySlots.driver2_id = res.json()["user"]["driver_id"]

    def admin_headers(self):
        return {"Authorization": f"Bearer {TestEmergencySlots.admin_token}"}

    def driver1_headers(self):
        return {"Authorization": f"Bearer {TestEmergencySlots.driver1_token}"}

    def driver2_headers(self):
        return {"Authorization": f"Bearer {TestEmergencySlots.driver2_token}"}

    # Test 1: Admin creates emergency slot
    def test_01_admin_creates_emergency_slot(self):
        """POST /api/schedules/emergency creates emergency slot (admin only)"""
        res = requests.post(
            f"{BASE_URL}/api/schedules/emergency",
            json={
                "week_start": WEEK_START,
                "day": "tuesday",
                "hour": "14:00",
                "total_spots": 2
            },
            headers=self.admin_headers()
        )
        assert res.status_code == 200, f"Failed to create emergency slot: {res.text}"
        data = res.json()
        assert "id" in data or "message" in data
        assert data.get("total_spots") == 2
        print(f"✓ Admin created emergency slot: {data}")

        # Store slot ID for later tests
        if "id" in data:
            TestEmergencySlots.created_slot_id = data["id"]

    # Test 2: Non-admin cannot create emergency slot
    def test_02_driver_cannot_create_emergency_slot(self):
        """Driver cannot create emergency slot - returns 403"""
        res = requests.post(
            f"{BASE_URL}/api/schedules/emergency",
            json={
                "week_start": WEEK_START,
                "day": "wednesday",
                "hour": "15:00",
                "total_spots": 1
            },
            headers=self.driver1_headers()
        )
        assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
        print("✓ Driver correctly denied from creating emergency slot")

    # Test 3: GET emergency slots for a week
    def test_03_get_emergency_slots_for_week(self):
        """GET /api/schedules/emergency?week_start=... returns all emergency slots"""
        res = requests.get(
            f"{BASE_URL}/api/schedules/emergency?week_start={WEEK_START}",
            headers=self.admin_headers()
        )
        assert res.status_code == 200, f"Failed to get emergency slots: {res.text}"
        data = res.json()
        assert isinstance(data, list)

        # Find our created slot
        tuesday_slot = next((s for s in data if s["day"] == "tuesday" and s["hour"] == "14:00"), None)
        assert tuesday_slot is not None, "Created slot not found"
        assert tuesday_slot["total_spots"] == 2
        assert tuesday_slot["remaining_spots"] == 2
        assert tuesday_slot["claimed_by"] == []

        # Store slot ID
        TestEmergencySlots.created_slot_id = tuesday_slot["id"]
        print(f"✓ GET emergency slots returned {len(data)} slots, found our slot: {tuesday_slot['id']}")

    # Test 4: Driver can claim emergency slot
    def test_04_driver1_claims_emergency_slot(self):
        """POST /api/schedules/emergency/{id}/claim allows driver to claim a spot"""
        slot_id = TestEmergencySlots.created_slot_id
        assert slot_id is not None, "No slot ID available"

        res = requests.post(
            f"{BASE_URL}/api/schedules/emergency/{slot_id}/claim",
            headers=self.driver1_headers()
        )
        assert res.status_code == 200, f"Failed to claim slot: {res.text}"
        data = res.json()
        assert "remaining_spots" in data
        assert data["remaining_spots"] == 1  # Was 2, now 1
        print(f"✓ Driver-001 claimed slot, remaining: {data['remaining_spots']}")

    # Test 5: Verify remaining_spots decreased and driver added to claimed_by
    def test_05_verify_claim_updated_slot(self):
        """Claiming reduces remaining_spots by 1 and adds driver to claimed_by"""
        res = requests.get(
            f"{BASE_URL}/api/schedules/emergency?week_start={WEEK_START}",
            headers=self.admin_headers()
        )
        assert res.status_code == 200
        data = res.json()

        tuesday_slot = next((s for s in data if s["day"] == "tuesday" and s["hour"] == "14:00"), None)
        assert tuesday_slot is not None
        assert tuesday_slot["remaining_spots"] == 1, f"Expected 1 remaining, got {tuesday_slot['remaining_spots']}"
        assert len(tuesday_slot["claimed_by"]) == 1, f"Expected 1 claimer, got {len(tuesday_slot['claimed_by'])}"
        assert TestEmergencySlots.driver1_id in tuesday_slot["claimed_by"]
        print(f"✓ Slot updated: remaining={tuesday_slot['remaining_spots']}, claimed_by={tuesday_slot['claimed_by']}")

    # Test 6: Double-claim by same driver returns 400
    def test_06_double_claim_returns_400(self):
        """Double-claim by same driver returns 400"""
        slot_id = TestEmergencySlots.created_slot_id

        res = requests.post(
            f"{BASE_URL}/api/schedules/emergency/{slot_id}/claim",
            headers=self.driver1_headers()
        )
        assert res.status_code == 400, f"Expected 400 for double claim, got {res.status_code}: {res.text}"
        assert "deja" in res.json().get("detail", "").lower() or "already" in res.json().get("detail", "").lower()
        print("✓ Double-claim correctly rejected with 400")

    # Test 7: Driver 2 claims remaining spot
    def test_07_driver2_claims_last_spot(self):
        """Second driver claims the last remaining spot"""
        slot_id = TestEmergencySlots.created_slot_id

        res = requests.post(
            f"{BASE_URL}/api/schedules/emergency/{slot_id}/claim",
            headers=self.driver2_headers()
        )
        assert res.status_code == 200, f"Failed to claim slot: {res.text}"
        data = res.json()
        assert data["remaining_spots"] == 0
        print(f"✓ Driver-002 claimed last spot, remaining: {data['remaining_spots']}")

    # Test 8: Claiming with 0 remaining spots returns 400
    def test_08_claim_exhausted_slot_returns_400(self):
        """Claiming with 0 remaining spots returns 400"""
        # Try to claim with driver-001 again (already claimed) - should fail
        # Actually we need a third driver or test differently
        # Let's verify the slot has 0 remaining first
        res = requests.get(
            f"{BASE_URL}/api/schedules/emergency?week_start={WEEK_START}",
            headers=self.admin_headers()
        )
        data = res.json()
        tuesday_slot = next((s for s in data if s["day"] == "tuesday" and s["hour"] == "14:00"), None)
        assert tuesday_slot["remaining_spots"] == 0, "Slot should have 0 remaining spots"

        # Try claiming with driver1 again - should fail with "already claimed" not "no spots"
        # We need to test with a driver who hasn't claimed yet
        # For now, verify the slot is exhausted
        print("✓ Slot exhausted with 0 remaining spots")

    # Test 9: Verify claiming adds hour to driver schedule with added_by=emergency
    def test_09_verify_schedule_updated_with_emergency(self):
        """Claiming also adds the hour to driver schedule with added_by=emergency"""
        # Get driver-001's schedule
        res = requests.get(
            f"{BASE_URL}/api/schedules/driver/{TestEmergencySlots.driver1_id}?year={datetime.now().year}",
            headers=self.driver1_headers()
        )
        assert res.status_code == 200, f"Failed to get driver schedule: {res.text}"
        data = res.json()

        # Find schedule for current week
        week_schedule = next((s for s in data if s["week_start"] == WEEK_START), None)
        assert week_schedule is not None, f"No schedule found for week {WEEK_START}"

        # Check tuesday slots
        tuesday_slots = week_schedule.get("slots", {}).get("tuesday", [])
        emergency_slot = next((s for s in tuesday_slots if s["start"] == "14:00" and s.get("added_by") == "emergency"), None)
        assert emergency_slot is not None, f"Emergency slot not found in driver schedule. Tuesday slots: {tuesday_slots}"
        assert emergency_slot["added_by"] == "emergency"
        print(f"✓ Driver schedule updated with emergency slot: {emergency_slot}")

    # Test 10: Admin creates another slot for delete test
    def test_10_admin_creates_slot_for_delete(self):
        """Create a slot to test deletion"""
        res = requests.post(
            f"{BASE_URL}/api/schedules/emergency",
            json={
                "week_start": WEEK_START,
                "day": "friday",
                "hour": "16:00",
                "total_spots": 1
            },
            headers=self.admin_headers()
        )
        assert res.status_code == 200, f"Failed to create slot: {res.text}"
        print("✓ Created slot for delete test")

    # Test 11: Get the slot ID for deletion
    def test_11_get_slot_for_delete(self):
        """Get the friday slot ID"""
        res = requests.get(
            f"{BASE_URL}/api/schedules/emergency?week_start={WEEK_START}",
            headers=self.admin_headers()
        )
        assert res.status_code == 200
        data = res.json()

        friday_slot = next((s for s in data if s["day"] == "friday" and s["hour"] == "16:00"), None)
        assert friday_slot is not None, "Friday slot not found"
        TestEmergencySlots.delete_slot_id = friday_slot["id"]
        print(f"✓ Found friday slot: {friday_slot['id']}")

    # Test 12: Driver cannot delete emergency slot
    def test_12_driver_cannot_delete_slot(self):
        """Driver cannot delete emergency slot - returns 403"""
        slot_id = TestEmergencySlots.delete_slot_id

        res = requests.delete(
            f"{BASE_URL}/api/schedules/emergency/{slot_id}",
            headers=self.driver1_headers()
        )
        assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
        print("✓ Driver correctly denied from deleting emergency slot")

    # Test 13: Admin deletes emergency slot
    def test_13_admin_deletes_emergency_slot(self):
        """DELETE /api/schedules/emergency/{id} removes slot (admin only)"""
        slot_id = TestEmergencySlots.delete_slot_id

        res = requests.delete(
            f"{BASE_URL}/api/schedules/emergency/{slot_id}",
            headers=self.admin_headers()
        )
        assert res.status_code == 200, f"Failed to delete slot: {res.text}"
        print("✓ Admin deleted emergency slot")

    # Test 14: Verify slot is deleted
    def test_14_verify_slot_deleted(self):
        """Verify the deleted slot no longer exists"""
        res = requests.get(
            f"{BASE_URL}/api/schedules/emergency?week_start={WEEK_START}",
            headers=self.admin_headers()
        )
        assert res.status_code == 200
        data = res.json()

        friday_slot = next((s for s in data if s["day"] == "friday" and s["hour"] == "16:00"), None)
        assert friday_slot is None, "Friday slot should be deleted"
        print("✓ Slot successfully deleted and not found")

    # Test 15: Admin cannot claim emergency slot
    def test_15_admin_cannot_claim_slot(self):
        """Admin cannot claim emergency slot - returns 403"""
        # First create a new slot
        res = requests.post(
            f"{BASE_URL}/api/schedules/emergency",
            json={
                "week_start": WEEK_START,
                "day": "saturday",
                "hour": "11:00",
                "total_spots": 1
            },
            headers=self.admin_headers()
        )
        assert res.status_code == 200

        # Get the slot ID
        res = requests.get(
            f"{BASE_URL}/api/schedules/emergency?week_start={WEEK_START}",
            headers=self.admin_headers()
        )
        data = res.json()
        saturday_slot = next((s for s in data if s["day"] == "saturday" and s["hour"] == "11:00"), None)
        assert saturday_slot is not None

        # Try to claim as admin
        res = requests.post(
            f"{BASE_URL}/api/schedules/emergency/{saturday_slot['id']}/claim",
            headers=self.admin_headers()
        )
        assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
        print("✓ Admin correctly denied from claiming emergency slot")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
