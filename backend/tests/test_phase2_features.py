"""
Backend API Tests for ProDelivery Bacău Platform - Phase 2 Features
Tests: Scheduling system, Analytics without financial data, Order cancellation with reason
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
    clear_login_attempts,
    seed_demo_data,
)


@pytest.fixture(scope="module")
def seed_data():
    """Seed database with demo data once for all tests"""
    return seed_demo_data()


@pytest.fixture
def admin_token(seed_data):
    """Get admin authentication token"""
    clear_login_attempts(ADMIN_EMAIL)
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if response.status_code == 200:
        return response.json()["token"]
    pytest.skip("Admin authentication failed")


@pytest.fixture
def driver_token_and_id(seed_data):
    """Get driver authentication token and driver_id"""
    clear_login_attempts(DRIVER_EMAIL)
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": DRIVER_EMAIL,
        "password": DRIVER_PASSWORD
    })
    if response.status_code == 200:
        data = response.json()
        return data["token"], data["user"]["driver_id"]
    pytest.skip("Driver authentication failed")


@pytest.fixture
def restaurant_token_and_id(seed_data):
    """Get restaurant authentication token and restaurant_id"""
    clear_login_attempts(RESTAURANT_EMAIL)
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": RESTAURANT_EMAIL,
        "password": RESTAURANT_PASSWORD
    })
    if response.status_code == 200:
        data = response.json()
        return data["token"], data["user"]["restaurant_id"]
    pytest.skip("Restaurant authentication failed")


class TestAPIRoot:
    """Test API root returns v2.0 message"""

    def test_api_root_returns_v2(self, seed_data):
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Delivery Platform API v2.0"
        assert data["status"] == "running"


class TestSeedEndpoint:
    """Test seed creates proper demo data"""

    def test_seed_creates_100_orders_5_drivers_5_restaurants(self, seed_data):
        assert seed_data["data"]["orders"] >= 100
        assert seed_data["data"]["demo_routes"] == 3
        assert seed_data["data"]["drivers"] == 5
        assert seed_data["data"]["restaurants"] == 5


class TestAuthEndpoints:
    """Test authentication for all 3 roles"""

    def test_admin_login(self, seed_data):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "admin"

    def test_driver_login(self, seed_data):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": DRIVER_EMAIL,
            "password": DRIVER_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "driver"
        assert data["user"]["driver_id"] == "driver-001"

    def test_restaurant_login(self, seed_data):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": RESTAURANT_EMAIL,
            "password": RESTAURANT_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "restaurant"
        assert data["user"]["restaurant_id"] == "rest-001"


class TestStatsEndpoint:
    """Test stats endpoint WITHOUT financial data"""

    def test_stats_has_no_total_revenue(self, admin_token):
        """Phase 2 requirement: stats should NOT have total_revenue"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/stats", headers=headers)
        assert response.status_code == 200
        data = response.json()

        # Should NOT have total_revenue
        assert "total_revenue" not in data

        # Should have these fields
        assert "total_orders" in data
        assert "active_orders" in data
        assert "delivered_orders" in data
        assert "active_drivers" in data
        assert "total_drivers" in data
        assert "total_restaurants" in data
        assert "cancelled_orders" in data


class TestHourlyStatsEndpoint:
    """Test hourly stats endpoint WITHOUT revenue data"""

    def test_hourly_returns_orders_only_no_revenue(self, admin_token):
        """Phase 2 requirement: hourly stats should have hourly_orders only, NOT hourly_revenue"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/stats/hourly", headers=headers)
        assert response.status_code == 200
        data = response.json()

        # Should have hourly_orders
        assert "hourly_orders" in data
        assert len(data["hourly_orders"]) > 0

        # Should NOT have hourly_revenue
        assert "hourly_revenue" not in data

        # Verify structure
        for item in data["hourly_orders"]:
            assert "hour" in item
            assert "orders" in item
            assert isinstance(item["orders"], int)


class TestAnalyticsEndpoint:
    """Test analytics endpoint with required fields"""

    def test_analytics_returns_required_fields(self, admin_token):
        """Phase 2 requirement: analytics returns orders_by_driver, orders_by_restaurant, cancelled_orders, cancelled_count"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/stats/analytics", headers=headers)
        assert response.status_code == 200
        data = response.json()

        # Required fields
        assert "orders_by_driver" in data
        assert "orders_by_restaurant" in data
        assert "cancelled_orders" in data
        assert "cancelled_count" in data

    def test_analytics_orders_by_restaurant_structure(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/stats/analytics", headers=headers)
        data = response.json()

        # orders_by_restaurant should be a list with name and count
        for item in data["orders_by_restaurant"]:
            assert "name" in item
            assert "count" in item

    def test_analytics_requires_admin_role(self, driver_token_and_id):
        """Analytics endpoint should be admin-only"""
        token, _ = driver_token_and_id
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{BASE_URL}/api/stats/analytics", headers=headers)
        assert response.status_code == 403


class TestScheduleEndpoints:
    """Test driver scheduling system"""

    def test_create_schedule(self, driver_token_and_id, admin_token):
        """Test POST /api/schedules creates/updates driver schedule"""
        _, driver_id = driver_token_and_id
        headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

        response = requests.post(f"{BASE_URL}/api/schedules", headers=headers, json={
            "driver_id": driver_id,
            "week_start": "2026-01-12",
            "slots": {
                "monday": [{"start": "08:00", "end": "09:00"}, {"start": "09:00", "end": "10:00"}],
                "wednesday": [{"start": "14:00", "end": "15:00"}]
            }
        })
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "total_hours" in data
        assert data["total_hours"] == 3

    def test_get_driver_schedules(self, driver_token_and_id):
        """Test GET /api/schedules/driver/{driver_id}?year=2026"""
        token, driver_id = driver_token_and_id
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.get(f"{BASE_URL}/api/schedules/driver/{driver_id}?year=2026", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_admin_schedule_summary(self, admin_token):
        """Test GET /api/schedules/admin/summary returns all drivers with schedule summaries"""
        headers = {"Authorization": f"Bearer {admin_token}"}

        response = requests.get(f"{BASE_URL}/api/schedules/admin/summary", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        assert len(data) == 5  # 5 drivers

        # Each driver should have these fields
        for driver in data:
            assert "driver_id" in driver
            assert "driver_name" in driver
            assert "phone" in driver
            assert "is_active" in driver
            assert "total_hours_scheduled" in driver
            assert "total_orders_delivered" in driver
            assert "schedules" in driver

    def test_schedule_update_existing(self, driver_token_and_id, admin_token):
        """Test updating an existing schedule for same week"""
        _, driver_id = driver_token_and_id
        headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

        # Create initial schedule
        requests.post(f"{BASE_URL}/api/schedules", headers=headers, json={
            "driver_id": driver_id,
            "week_start": "2026-01-19",
            "slots": {"monday": [{"start": "08:00", "end": "09:00"}]}
        })

        # Update same week
        response = requests.post(f"{BASE_URL}/api/schedules", headers=headers, json={
            "driver_id": driver_id,
            "week_start": "2026-01-19",
            "slots": {"monday": [{"start": "08:00", "end": "09:00"}, {"start": "09:00", "end": "10:00"}, {"start": "10:00", "end": "11:00"}]}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Schedule updated"
        assert data["total_hours"] == 3


class TestOrderCancellation:
    """Test order cancellation with mandatory reason"""

    def test_cancel_without_reason_returns_400(self, admin_token):
        """Phase 2 requirement: CANCELLED status requires cancellation_reason"""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Get a NEW order
        orders_response = requests.get(f"{BASE_URL}/api/orders", headers=headers)
        orders = orders_response.json()
        new_order = next((o for o in orders if o["status"] == "NEW"), None)

        if not new_order:
            pytest.skip("No NEW orders available")

        # Try to cancel without reason
        response = requests.put(
            f"{BASE_URL}/api/orders/{new_order['id']}/status",
            headers=headers,
            json={"status": "CANCELLED"}
        )
        assert response.status_code == 400
        data = response.json()
        assert "reason" in data["detail"].lower()

    def test_cancel_with_reason_succeeds(self, admin_token):
        """Cancel with reason should succeed and store the reason"""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Get a NEW order
        orders_response = requests.get(f"{BASE_URL}/api/orders", headers=headers)
        orders = orders_response.json()
        new_order = next((o for o in orders if o["status"] == "NEW"), None)

        if not new_order:
            pytest.skip("No NEW orders available")

        # Cancel with reason
        response = requests.put(
            f"{BASE_URL}/api/orders/{new_order['id']}/status",
            headers=headers,
            json={
                "status": "CANCELLED",
                "cancellation_reason": "TEST_Client a anulat comanda"
            }
        )
        assert response.status_code == 200

        # Verify the order was cancelled and reason stored
        order_response = requests.get(f"{BASE_URL}/api/orders/{new_order['id']}", headers=headers)
        order = order_response.json()
        assert order["status"] == "CANCELLED"
        assert order["cancellation_reason"] == "TEST_Client a anulat comanda"
        assert "cancelled_by" in order


class TestOrderWorkflow:
    """Test order workflow with confirmations"""

    def test_restaurant_set_preparing_time(self, restaurant_token_and_id, admin_token):
        """Restaurant sets preparation time - order goes to PREPARING"""
        token, restaurant_id = restaurant_token_and_id
        headers = {"Authorization": f"Bearer {token}"}

        # Get restaurant orders
        response = requests.get(f"{BASE_URL}/api/orders/restaurant/{restaurant_id}", headers=headers)
        orders = response.json()
        new_order = next((o for o in orders if o["status"] == "NEW"), None)

        if not new_order:
            pytest.skip("No NEW orders for restaurant")

        # Set preparation time
        response = requests.put(
            f"{BASE_URL}/api/orders/{new_order['id']}/preparing",
            headers=headers,
            json={"preparation_time": 20}
        )
        assert response.status_code == 200

        # Verify status
        order_response = requests.get(f"{BASE_URL}/api/orders/{new_order['id']}", headers=headers)
        order = order_response.json()
        assert order["status"] == "PREPARING"
        assert order["preparation_time"] == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
