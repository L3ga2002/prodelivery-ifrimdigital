#!/usr/bin/env python3
"""
Backend Regression Testing After Refactor
Tests the specific endpoints mentioned in the review request to ensure refactoring didn't break functionality.
"""

import requests
import json
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv(Path(__file__).resolve().parent / "backend" / ".env")

BACKEND_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("BACKEND_URL")
    or "http://127.0.0.1:8000/api"
).rstrip("/")

ADMIN_EMAIL = os.environ.get("DEMO_ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("DEMO_ADMIN_PASSWORD", "")

class BackendTester:
    def __init__(self):
        self.session = requests.Session()
        self.admin_token = None
        self.test_results = []

    def log_test(self, test_name: str, success: bool, details: str, response_data: Any = None):
        """Log test results"""
        status = "PASS" if success else "FAIL"
        print(f"{status} {test_name}")
        if not success or response_data:
            print(f"   Details: {details}")
            if response_data:
                print(f"   Response: {response_data}")
        print()

        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details,
            "response_data": response_data
        })

    def test_seed_endpoint(self):
        """Test 1: POST /api/seed -> 200 și răspuns valid"""
        try:
            response = self.session.post(f"{BACKEND_URL}/seed")

            if response.status_code == 200:
                data = response.json()
                # Check if response contains expected seed data structure
                if isinstance(data, dict) and ("message" in data or "status" in data or "users" in data):
                    self.log_test("POST /api/seed", True, f"Status: {response.status_code}, Valid response structure", data)
                else:
                    self.log_test("POST /api/seed", False, f"Status: {response.status_code}, Invalid response structure", data)
            else:
                self.log_test("POST /api/seed", False, f"Status: {response.status_code}", response.text)

        except Exception as e:
            self.log_test("POST /api/seed", False, f"Exception: {str(e)}")

    def test_admin_login(self):
        """Test 2: POST /api/auth/login admin -> 200"""
        if not ADMIN_EMAIL or not ADMIN_PASSWORD:
            self.log_test(
                "POST /api/auth/login (admin)",
                False,
                "Missing DEMO_ADMIN_EMAIL or DEMO_ADMIN_PASSWORD in environment",
            )
            return

        try:
            login_data = {
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD
            }

            response = self.session.post(f"{BACKEND_URL}/auth/login", json=login_data)

            if response.status_code == 200:
                data = response.json()
                # Check for token and user in response
                if "token" in data and "user" in data:
                    self.admin_token = data["token"]
                    # Check if httpOnly cookies are set
                    cookies_set = "access_token" in [cookie.name for cookie in self.session.cookies]
                    cookie_info = f"httpOnly cookies: {cookies_set}"
                    self.log_test("POST /api/auth/login (admin)", True, f"Status: {response.status_code}, Token received, {cookie_info}", {"user": data["user"]})
                else:
                    self.log_test("POST /api/auth/login (admin)", False, f"Status: {response.status_code}, Missing token or user", data)
            else:
                self.log_test("POST /api/auth/login (admin)", False, f"Status: {response.status_code}", response.text)

        except Exception as e:
            self.log_test("POST /api/auth/login (admin)", False, f"Exception: {str(e)}")

    def test_zones_get(self):
        """Test 3: GET /api/zones cu token admin -> 200"""
        if not self.admin_token:
            self.log_test("GET /api/zones", False, "No admin token available")
            return

        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = self.session.get(f"{BACKEND_URL}/zones", headers=headers)

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    self.log_test("GET /api/zones", True, f"Status: {response.status_code}, Returned {len(data)} zones", f"First zone: {data[0] if data else 'No zones'}")
                else:
                    self.log_test("GET /api/zones", True, f"Status: {response.status_code}, Valid response", data)
            else:
                self.log_test("GET /api/zones", False, f"Status: {response.status_code}", response.text)

        except Exception as e:
            self.log_test("GET /api/zones", False, f"Exception: {str(e)}")

    def test_zones_detect(self):
        """Test 4: POST /api/zones/detect cu coordonate valide -> 200 și răspuns coerent"""
        if not self.admin_token:
            self.log_test("POST /api/zones/detect", False, "No admin token available")
            return

        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            # Use valid coordinates for Bucharest center
            detect_data = {
                "lat": 44.4268,
                "lng": 26.1025
            }

            response = self.session.post(f"{BACKEND_URL}/zones/detect", json=detect_data, headers=headers)

            if response.status_code == 200:
                data = response.json()
                # Check if response contains zone information
                if isinstance(data, dict) and ("zone" in data or "zone_id" in data or "name" in data):
                    self.log_test("POST /api/zones/detect", True, f"Status: {response.status_code}, Zone detected", data)
                else:
                    self.log_test("POST /api/zones/detect", True, f"Status: {response.status_code}, Response received", data)
            else:
                self.log_test("POST /api/zones/detect", False, f"Status: {response.status_code}", response.text)

        except Exception as e:
            self.log_test("POST /api/zones/detect", False, f"Exception: {str(e)}")

    def test_orders_get(self):
        """Test 5: GET /api/orders -> 200"""
        if not self.admin_token:
            self.log_test("GET /api/orders", False, "No admin token available")
            return

        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = self.session.get(f"{BACKEND_URL}/orders", headers=headers)

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    self.log_test("GET /api/orders", True, f"Status: {response.status_code}, Returned {len(data)} orders", f"First order: {data[0] if data else 'No orders'}")
                else:
                    self.log_test("GET /api/orders", True, f"Status: {response.status_code}, Valid response", data)
            else:
                self.log_test("GET /api/orders", False, f"Status: {response.status_code}", response.text)

        except Exception as e:
            self.log_test("GET /api/orders", False, f"Exception: {str(e)}")

    def test_order_status_update(self):
        """Test 6: PUT /api/orders/{id}/status pentru un order NEW -> CANCELLED cu cancellation_reason -> 200"""
        if not self.admin_token:
            self.log_test("PUT /api/orders/{id}/status", False, "No admin token available")
            return

        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}

            # First get orders to find a NEW order
            response = self.session.get(f"{BACKEND_URL}/orders", headers=headers)
            if response.status_code != 200:
                self.log_test("PUT /api/orders/{id}/status", False, "Could not fetch orders to find NEW order")
                return

            orders = response.json()
            new_order = None

            # Look for a NEW order
            if isinstance(orders, list):
                for order in orders:
                    if isinstance(order, dict) and order.get("status") == "NEW":
                        new_order = order
                        break

            if not new_order:
                self.log_test("PUT /api/orders/{id}/status", False, "No NEW orders found to test status update")
                return

            order_id = new_order.get("id") or new_order.get("_id")
            if not order_id:
                self.log_test("PUT /api/orders/{id}/status", False, "Order ID not found in NEW order")
                return

            # Update order status to CANCELLED
            update_data = {
                "status": "CANCELLED",
                "cancellation_reason": "Test cancellation for regression testing"
            }

            response = self.session.put(f"{BACKEND_URL}/orders/{order_id}/status", json=update_data, headers=headers)

            if response.status_code == 200:
                data = response.json()
                self.log_test("PUT /api/orders/{id}/status", True, f"Status: {response.status_code}, Order {order_id} updated to CANCELLED", data)
            else:
                self.log_test("PUT /api/orders/{id}/status", False, f"Status: {response.status_code}", response.text)

        except Exception as e:
            self.log_test("PUT /api/orders/{id}/status", False, f"Exception: {str(e)}")

    def test_schedules_admin_summary(self):
        """Test 7: GET /api/schedules/admin/summary -> 200"""
        if not self.admin_token:
            self.log_test("GET /api/schedules/admin/summary", False, "No admin token available")
            return

        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = self.session.get(f"{BACKEND_URL}/schedules/admin/summary", headers=headers)

            if response.status_code == 200:
                data = response.json()
                self.log_test("GET /api/schedules/admin/summary", True, f"Status: {response.status_code}, Summary received", data)
            else:
                self.log_test("GET /api/schedules/admin/summary", False, f"Status: {response.status_code}", response.text)

        except Exception as e:
            self.log_test("GET /api/schedules/admin/summary", False, f"Exception: {str(e)}")

    def test_emergency_auto_generate(self):
        """Test 8: POST /api/schedules/emergency/auto-generate -> 200"""
        if not self.admin_token:
            self.log_test("POST /api/schedules/emergency/auto-generate", False, "No admin token available")
            return

        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            # Add required week_start parameter
            params = {"week_start": "2026-04-28"}  # Use next Monday as week start
            response = self.session.post(f"{BACKEND_URL}/schedules/emergency/auto-generate", headers=headers, params=params)

            if response.status_code == 200:
                data = response.json()
                self.log_test("POST /api/schedules/emergency/auto-generate", True, f"Status: {response.status_code}, Emergency slots generated", data)
            else:
                self.log_test("POST /api/schedules/emergency/auto-generate", False, f"Status: {response.status_code}", response.text)

        except Exception as e:
            self.log_test("POST /api/schedules/emergency/auto-generate", False, f"Exception: {str(e)}")

    def run_all_tests(self):
        """Run all backend regression tests"""
        print("Starting Backend Regression Tests After Refactor")
        print("=" * 60)
        print()

        # Run tests in order
        self.test_seed_endpoint()
        self.test_admin_login()
        self.test_zones_get()
        self.test_zones_detect()
        self.test_orders_get()
        self.test_order_status_update()
        self.test_schedules_admin_summary()
        self.test_emergency_auto_generate()

        # Summary
        print("=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)

        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)

        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print()

        if total - passed > 0:
            print("FAILED TESTS:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  - {result['test']}: {result['details']}")
            print()

        if passed == total:
            print("ALL TESTS PASSED - Refactor successful!")
        else:
            print("Some tests failed - Review needed")

        return passed == total

if __name__ == "__main__":
    tester = BackendTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)
