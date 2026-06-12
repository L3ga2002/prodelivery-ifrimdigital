"""
Backend API Tests for ProDelivery Bacău Platform
Tests all core endpoints: Auth, Orders, Drivers, Restaurants, Stats
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


@pytest.fixture(scope="module", autouse=True)
def seeded_demo():
    return seed_demo_data()


class TestSeedEndpoint:
    """Test the seed endpoint creates proper demo data"""

    def test_seed_creates_demo_orders(self, seeded_demo):
        data = seeded_demo
        assert data["message"] == "Demo data seeded successfully - 100 orders created"
        assert data["data"]["orders"] >= 100
        assert data["data"]["demo_routes"] == 3
        assert data["data"]["drivers"] == 5
        assert data["data"]["restaurants"] == 5


class TestAuthEndpoints:
    """Test authentication flows for all roles"""

    def test_admin_login_success(self):
        clear_login_attempts(ADMIN_EMAIL)
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "admin"
        assert data["user"]["email"] == ADMIN_EMAIL

    def test_driver_login_success(self):
        clear_login_attempts(DRIVER_EMAIL)
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": DRIVER_EMAIL,
            "password": DRIVER_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "driver"
        assert "driver_id" in data["user"]
        assert data["user"]["driver_id"] is not None

    def test_restaurant_login_success(self):
        clear_login_attempts(RESTAURANT_EMAIL)
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": RESTAURANT_EMAIL,
            "password": RESTAURANT_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "restaurant"
        assert "restaurant_id" in data["user"]

    def test_invalid_credentials_fail(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "invalid@test.ro",
            "password": "wrongpassword"
        })
        assert response.status_code == 401


@pytest.fixture
def admin_token():
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
def driver_token_and_id():
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
def restaurant_token_and_id():
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


class TestRestaurantsEndpoints:
    """Test restaurants have Bacău data"""

    def test_get_restaurants_has_bacau_names(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/restaurants", headers=headers)
        assert response.status_code == 200
        restaurants = response.json()

        # Check we have 5 restaurants
        assert len(restaurants) == 5

        # Verify Bacău restaurant names
        expected_names = [
            "Trattoria Da Vinci",
            "La Cuptor Bacău",
            "Sushi Room",
            "Burger Craft",
            "Casa Moldoveanu"
        ]
        actual_names = [r["name"] for r in restaurants]
        for name in expected_names:
            assert name in actual_names, f"Missing restaurant: {name}"

    def test_restaurants_have_bacau_addresses(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/restaurants", headers=headers)
        assert response.status_code == 200
        restaurants = response.json()

        for r in restaurants:
            assert "Bacău" in r["address"], f"Restaurant {r['name']} missing Bacău in address: {r['address']}"

    def test_restaurants_have_bacau_coordinates(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/restaurants", headers=headers)
        assert response.status_code == 200
        restaurants = response.json()

        # Bacău coordinates are roughly latitude 46.56, longitude 26.91
        for r in restaurants:
            assert 46.5 < r["latitude"] < 46.6, f"Restaurant {r['name']} latitude out of Bacău range"
            assert 26.8 < r["longitude"] < 27.0, f"Restaurant {r['name']} longitude out of Bacău range"


class TestDriversEndpoints:
    """Test drivers have Bacău locations"""

    def test_get_drivers(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/drivers", headers=headers)
        assert response.status_code == 200
        drivers = response.json()
        assert len(drivers) == 5

    def test_drivers_have_bacau_coordinates(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/drivers", headers=headers)
        assert response.status_code == 200
        drivers = response.json()

        for d in drivers:
            assert 46.5 < d["latitude"] < 46.6, f"Driver {d['name']} latitude out of Bacău range"
            assert 26.8 < d["longitude"] < 27.0, f"Driver {d['name']} longitude out of Bacău range"


class TestOrdersEndpoints:
    """Test orders have Bacău addresses (not București)"""

    def test_get_orders(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/orders", headers=headers)
        assert response.status_code == 200
        orders = response.json()
        assert len(orders) >= 100

    def test_orders_have_bacau_addresses(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/orders", headers=headers)
        assert response.status_code == 200
        orders = response.json()

        # Check all orders have Bacău in address, not București
        bucuresti_count = 0
        bacau_count = 0
        for order in orders:
            addr = order["customer_address"]
            if "Bacău" in addr:
                bacau_count += 1
            if "București" in addr:
                bucuresti_count += 1

        assert bacau_count == len(orders), f"Only {bacau_count}/{len(orders)} orders have Bacău address"
        assert bucuresti_count == 0, f"Found {bucuresti_count} orders with București address"

    def test_get_restaurant_orders(self, restaurant_token_and_id):
        token, restaurant_id = restaurant_token_and_id
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{BASE_URL}/api/orders/restaurant/{restaurant_id}", headers=headers)
        assert response.status_code == 200
        orders = response.json()
        # Should have some orders for this restaurant
        assert len(orders) > 0
        # All orders should belong to this restaurant
        for order in orders:
            assert order["restaurant_id"] == restaurant_id


class TestHourlyStatsEndpoint:
    """Test hourly stats endpoint for analytics charts"""

    def test_hourly_stats_returns_arrays(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/stats/hourly", headers=headers)
        assert response.status_code == 200
        data = response.json()

        # Check both arrays exist
        assert "hourly_orders" in data
        assert "hourly_revenue" not in data

        # Check arrays are not empty
        assert len(data["hourly_orders"]) > 0

    def test_hourly_stats_data_structure(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/stats/hourly", headers=headers)
        assert response.status_code == 200
        data = response.json()

        # Check hourly_orders has correct structure
        for item in data["hourly_orders"]:
            assert "hour" in item
            assert "orders" in item
            assert isinstance(item["orders"], int)


class TestGeneralStatsEndpoint:
    """Test general stats endpoint"""

    def test_stats_returns_all_fields(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.get(f"{BASE_URL}/api/stats", headers=headers)
        assert response.status_code == 200
        data = response.json()

        # Check all expected fields exist
        assert "total_orders" in data
        assert "active_orders" in data
        assert "delivered_orders" in data
        assert "active_drivers" in data
        assert "total_drivers" in data
        assert "total_restaurants" in data
        assert "total_revenue" not in data

        # Verify data counts
        assert data["total_orders"] >= 100


class TestOrderWorkflow:
    """Test complete order workflow: assign -> status updates"""

    def test_assign_order_to_driver(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Get a NEW order
        response = requests.get(f"{BASE_URL}/api/orders", headers=headers)
        orders = response.json()
        new_orders = [o for o in orders if o["status"] == "NEW"]

        if not new_orders:
            pytest.skip("No NEW orders available")

        order = new_orders[0]
        order_id = order["id"]

        # Get available drivers
        drivers_response = requests.get(f"{BASE_URL}/api/drivers", headers=headers)
        drivers = drivers_response.json()
        active_drivers = [d for d in drivers if d["is_active"] and not d.get("current_order_id")]

        if not active_drivers:
            pytest.skip("No active drivers available")

        driver_id = active_drivers[0]["id"]

        # Assign order
        assign_response = requests.put(
            f"{BASE_URL}/api/orders/{order_id}/assign",
            headers=headers,
            json={"driver_id": driver_id}
        )
        assert assign_response.status_code == 200

        # Verify assignment
        order_response = requests.get(f"{BASE_URL}/api/orders/{order_id}", headers=headers)
        updated_order = order_response.json()
        assert updated_order["driver_id"] == driver_id
        assert updated_order["status"] == "ASSIGNED"

    def test_order_status_progression(self, driver_token_and_id):
        token, driver_id = driver_token_and_id
        headers = {"Authorization": f"Bearer {token}"}

        # Get driver's assigned orders
        response = requests.get(f"{BASE_URL}/api/orders/driver/{driver_id}", headers=headers)
        orders = response.json()

        if not orders:
            pytest.skip("No orders assigned to driver")

        order = orders[0]
        order_id = order["id"]

        # Test status progression based on current status
        if order["status"] == "ASSIGNED":
            # Accept order
            response = requests.put(
                f"{BASE_URL}/api/orders/{order_id}/status",
                headers=headers,
                json={"status": "ACCEPTED"}
            )
            assert response.status_code == 200


class TestRestaurantWorkflow:
    """Test restaurant preparation workflow"""

    def test_set_preparation_time(self, restaurant_token_and_id, admin_token):
        token, restaurant_id = restaurant_token_and_id
        headers = {"Authorization": f"Bearer {token}"}

        # Get restaurant orders
        response = requests.get(f"{BASE_URL}/api/orders/restaurant/{restaurant_id}", headers=headers)
        orders = response.json()
        new_orders = [o for o in orders if o["status"] == "NEW"]

        if not new_orders:
            pytest.skip("No NEW orders for restaurant")

        order_id = new_orders[0]["id"]

        # Set preparation time
        response = requests.put(
            f"{BASE_URL}/api/orders/{order_id}/preparing",
            headers=headers,
            json={"preparation_time": 20}
        )
        assert response.status_code == 200

        # Verify status changed to PREPARING
        order_response = requests.get(f"{BASE_URL}/api/orders/{order_id}", headers=headers)
        updated_order = order_response.json()
        assert updated_order["status"] == "PREPARING"
        assert updated_order["preparation_time"] == 20

    def test_mark_order_ready(self, restaurant_token_and_id):
        token, restaurant_id = restaurant_token_and_id
        headers = {"Authorization": f"Bearer {token}"}

        # Get restaurant orders
        response = requests.get(f"{BASE_URL}/api/orders/restaurant/{restaurant_id}", headers=headers)
        orders = response.json()
        preparing_orders = [o for o in orders if o["status"] == "PREPARING"]

        if not preparing_orders:
            pytest.skip("No PREPARING orders for restaurant")

        order_id = preparing_orders[0]["id"]

        # Mark as ready
        response = requests.put(f"{BASE_URL}/api/orders/{order_id}/ready", headers=headers)
        assert response.status_code == 200

        # Verify status
        order_response = requests.get(f"{BASE_URL}/api/orders/{order_id}", headers=headers)
        updated_order = order_response.json()
        assert updated_order["status"] == "READY"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
