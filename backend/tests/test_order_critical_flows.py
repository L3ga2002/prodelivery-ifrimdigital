from __future__ import annotations

import asyncio
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.order import AssignOrder, OrderCreate, PreparationTime, ProblemOrderCreate, UpdateOrderStatus  # noqa: E402
from routers import orders as orders_router  # noqa: E402
from routers import restaurants as restaurants_router  # noqa: E402


ADMIN_USER = {"role": "admin", "user_id": "admin-user", "id": "admin-user"}
RESTAURANT_USER = {
    "role": "restaurant",
    "user_id": "restaurant-user",
    "id": "restaurant-user",
    "restaurant_id": "rest-1",
}
DRIVER_USER = {
    "role": "driver",
    "user_id": "driver-user",
    "id": "driver-user",
    "driver_id": "driver-1",
}


def run_async(coro):
    return asyncio.run(coro)


class FakeCursor:
    def __init__(self, docs):
        self.docs = [copy.deepcopy(doc) for doc in docs]

    def sort(self, key, direction):
        reverse = direction == -1
        self.docs.sort(key=lambda doc: doc.get(key) or "", reverse=reverse)
        return self

    async def to_list(self, length):
        return copy.deepcopy(self.docs[:length])

    def __aiter__(self):
        self._iter = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return copy.deepcopy(next(self._iter))
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [copy.deepcopy(doc) for doc in (docs or [])]

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return self._project(doc, projection)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        return FakeCursor([self._project(doc, projection) for doc in self.docs if self._matches(doc, query)])

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches(doc, query))

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))
        return {"inserted_id": doc.get("id") or doc.get("_id")}

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply_update(doc, update)
                return {"matched_count": 1, "modified_count": 1}
        return {"matched_count": 0, "modified_count": 0}

    async def find_one_and_update(self, query, update, upsert=False, return_document=None, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                self._apply_update(doc, update)
                return self._project(doc, projection)

        if not upsert:
            return None

        doc = {key: value for key, value in query.items() if not key.startswith("$") and not isinstance(value, dict)}
        self._apply_update(doc, update)
        self.docs.append(doc)
        return self._project(doc, projection)

    def _matches(self, doc, query):
        for key, expected in (query or {}).items():
            if key == "$or":
                if not any(self._matches(doc, option) for option in expected):
                    return False
                continue

            actual = doc.get(key)
            if isinstance(expected, dict):
                for operator, value in expected.items():
                    if operator == "$ne" and actual == value:
                        return False
                    if operator == "$exists" and ((key in doc) != value):
                        return False
                    if operator == "$nin" and actual in value:
                        return False
                continue

            if actual != expected:
                return False
        return True

    def _project(self, doc, projection):
        cloned = copy.deepcopy(doc)
        if not projection:
            return cloned

        include_keys = {key for key, value in projection.items() if value}
        if include_keys:
            projected = {key: cloned[key] for key in include_keys if key in cloned}
            if projection.get("_id") == 0:
                projected.pop("_id", None)
            return projected

        for key, value in projection.items():
            if value == 0:
                cloned.pop(key, None)
        return cloned

    def _apply_update(self, doc, update):
        for key, value in update.get("$set", {}).items():
            doc[key] = copy.deepcopy(value)
        for key, value in update.get("$inc", {}).items():
            doc[key] = doc.get(key, 0) + value
        for key, value in update.get("$push", {}).items():
            doc.setdefault(key, []).append(copy.deepcopy(value))


class FakeDb:
    def __init__(self):
        self.restaurants = FakeCollection([
            {
                "id": "rest-1",
                "name": "Restaurant Test",
                "accepting_orders": True,
                "closed_today": False,
                "pause_until": None,
            }
        ])
        self.drivers = FakeCollection([
            {
                "id": "driver-1",
                "name": "Driver Test",
                "is_active": True,
                "driver_status": "active",
                "current_order_id": None,
                "account_disabled": False,
                "total_deliveries": 0,
                "total_earnings": 0,
            }
        ])
        self.orders = FakeCollection()
        self.delivery_zones = FakeCollection()
        self.audit_logs = FakeCollection()
        self.counters = FakeCollection()


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(orders_router, "db", db)
    monkeypatch.setattr(restaurants_router, "db", db)
    return db


def order_payload(total=40):
    return {
        "restaurant_id": "rest-1",
        "customer_name": "Client Test",
        "customer_phone": "0712345678",
        "customer_address": "Strada Test 1, Bacau",
        "items": [{"name": "Pizza", "quantity": 1, "price": total}],
        "subtotal_amount": total,
        "delivery_fee": 0,
        "total_amount": total,
        "payment_type": "CASH",
        "source": "S",
    }


async def create_test_order(total=40, user=ADMIN_USER):
    return await orders_router.create_order(OrderCreate(**order_payload(total)), user)


def audit_actions(order):
    return [entry["action"] for entry in order.get("audit_trail", [])]


def test_complete_order_delivery_flow_records_real_state_changes(fake_db):
    async def scenario():
        created = await create_test_order()
        assert created["status"] == "NEW"
        assert created["order_number"] == "S.0001"

        preparing = await orders_router.set_preparing(
            created["id"],
            PreparationTime(preparation_time=15),
            RESTAURANT_USER,
        )
        assert preparing["message"] == "Order preparing"
        order = await fake_db.orders.find_one({"id": created["id"]})
        assert order["status"] == "PREPARING"
        assert order["preparation_time"] == 15
        assert order["preparation_estimated_seconds"] == 900
        assert order["preparation_due_at"]
        assert "order.preparing_started" in audit_actions(order)

        ready = await orders_router.set_ready(created["id"], RESTAURANT_USER)
        assert ready["message"] == "Order ready"
        order = await fake_db.orders.find_one({"id": created["id"]})
        assert order["status"] == "READY"
        assert "order.ready" in audit_actions(order)

        assigned = await orders_router.assign_order(
            created["id"],
            AssignOrder(driver_id="driver-1"),
            ADMIN_USER,
        )
        assert assigned["message"] == "Order assigned"
        order = await fake_db.orders.find_one({"id": created["id"]})
        driver = await fake_db.drivers.find_one({"id": "driver-1"})
        assert order["status"] == "ASSIGNED"
        assert order["driver_id"] == "driver-1"
        assert driver["current_order_id"] == created["id"]
        assert driver["driver_status"] == "delivery"

        await orders_router.update_order_status(
            created["id"],
            UpdateOrderStatus(status="ACCEPTED"),
            DRIVER_USER,
        )
        order = await fake_db.orders.find_one({"id": created["id"]})
        assert order["status"] == "ACCEPTED"
        assert order["accepted_at"]

        await orders_router.update_order_status(
            created["id"],
            UpdateOrderStatus(status="PICKED_UP"),
            DRIVER_USER,
        )
        order = await fake_db.orders.find_one({"id": created["id"]})
        assert order["status"] == "PICKED_UP"
        assert order["picked_up_at"]

        await orders_router.update_order_status(
            created["id"],
            UpdateOrderStatus(status="DELIVERED"),
            DRIVER_USER,
        )
        order = await fake_db.orders.find_one({"id": created["id"]})
        driver = await fake_db.drivers.find_one({"id": "driver-1"})
        assert order["status"] == "DELIVERED"
        assert order["delivered_at"]
        assert driver["current_order_id"] is None
        assert driver["driver_status"] == "active"
        assert driver["total_deliveries"] == 1
        assert driver["total_earnings"] == 4
        assert audit_actions(order).count("order.status_changed") == 3
        assert await fake_db.audit_logs.count_documents({"entity_id": created["id"]}) >= 6

    run_async(scenario())


def test_duplicate_order_actions_are_idempotent_and_do_not_rewrite_flow(fake_db):
    async def scenario():
        created = await create_test_order()

        await orders_router.set_preparing(created["id"], PreparationTime(preparation_time=20), RESTAURANT_USER)
        duplicate_preparing = await orders_router.set_preparing(
            created["id"],
            PreparationTime(preparation_time=45),
            RESTAURANT_USER,
        )
        order = await fake_db.orders.find_one({"id": created["id"]})
        assert duplicate_preparing["idempotent"] is True
        assert order["preparation_time"] == 20
        assert audit_actions(order).count("order.preparing_started") == 1

        await orders_router.set_ready(created["id"], RESTAURANT_USER)
        duplicate_ready = await orders_router.set_ready(created["id"], RESTAURANT_USER)
        order = await fake_db.orders.find_one({"id": created["id"]})
        assert duplicate_ready["idempotent"] is True
        assert audit_actions(order).count("order.ready") == 1

        await orders_router.assign_order(created["id"], AssignOrder(driver_id="driver-1"), ADMIN_USER)
        duplicate_assign = await orders_router.assign_order(created["id"], AssignOrder(driver_id="driver-1"), ADMIN_USER)
        order = await fake_db.orders.find_one({"id": created["id"]})
        assert duplicate_assign["idempotent"] is True
        assert order["status"] == "ASSIGNED"
        assert audit_actions(order).count("order.assigned") == 1

        await orders_router.update_order_status(created["id"], UpdateOrderStatus(status="ACCEPTED"), DRIVER_USER)
        duplicate_accept = await orders_router.update_order_status(
            created["id"],
            UpdateOrderStatus(status="ACCEPTED"),
            DRIVER_USER,
        )
        order = await fake_db.orders.find_one({"id": created["id"]})
        assert duplicate_accept["idempotent"] is True
        assert order["status"] == "ACCEPTED"
        assert audit_actions(order).count("order.status_changed") == 1

    run_async(scenario())


def test_invalid_status_and_invalid_transition_are_rejected_without_mutating_order(fake_db):
    async def scenario():
        created = await create_test_order()

        with pytest.raises(HTTPException) as dedicated_status:
            await orders_router.update_order_status(
                created["id"],
                UpdateOrderStatus(status="PREPARING"),
                ADMIN_USER,
            )
        assert dedicated_status.value.status_code == 400

        with pytest.raises(HTTPException) as invalid_jump:
            await orders_router.update_order_status(
                created["id"],
                UpdateOrderStatus(status="DELIVERED"),
                ADMIN_USER,
            )
        assert invalid_jump.value.status_code == 409

        with pytest.raises(ValidationError):
            UpdateOrderStatus(status="BROKEN")

        order = await fake_db.orders.find_one({"id": created["id"]})
        assert order["status"] == "NEW"
        assert audit_actions(order) == ["order.created"]

    run_async(scenario())


def test_restaurant_pause_and_close_day_persist_and_block_new_orders(fake_db):
    async def scenario():
        pause = await restaurants_router.update_restaurant_status(
            "rest-1",
            restaurants_router.RestaurantStatusUpdate(accepting_orders=False, pause_minutes=30),
            RESTAURANT_USER,
        )
        restaurant = await fake_db.restaurants.find_one({"id": "rest-1"})
        assert pause["accepting_orders"] is False
        assert pause["pause_until"]
        assert restaurant["closed_today"] is False

        with pytest.raises(HTTPException) as paused_create:
            await create_test_order()
        assert paused_create.value.status_code == 409

        await restaurants_router.update_restaurant_status(
            "rest-1",
            restaurants_router.RestaurantStatusUpdate(accepting_orders=True),
            RESTAURANT_USER,
        )

        closed = await restaurants_router.update_restaurant_status(
            "rest-1",
            restaurants_router.RestaurantStatusUpdate(accepting_orders=False, closed_today=True),
            RESTAURANT_USER,
        )
        restaurant = await fake_db.restaurants.find_one({"id": "rest-1"})
        assert closed["closed_today"] is True
        assert restaurant["accepting_orders"] is False
        assert restaurant["closed_today"] is True
        assert restaurant["pause_until"]

        with pytest.raises(HTTPException) as closed_create:
            await create_test_order()
        assert closed_create.value.status_code == 409

    run_async(scenario())


def test_close_day_uses_next_bucharest_midnight():
    close_time = restaurants_router._next_restaurant_local_midnight_utc(
        datetime(2026, 6, 12, 13, 31, tzinfo=timezone.utc),
    )

    assert close_time.isoformat() == "2026-06-12T21:00:00+00:00"


def test_problem_order_creates_linked_followup_and_marks_original(fake_db):
    async def scenario():
        original = await create_test_order(total=55)
        await fake_db.orders.update_one({"id": original["id"]}, {"$set": {"status": "DELIVERED"}})
        response = await orders_router.create_problem_order(
            original["id"],
            ProblemOrderCreate(
                problem_type="missing_product",
                item_name="Sos lipsa",
                quantity=2,
                price=5,
                problem_description="Clientul nu a primit sosurile",
            ),
            RESTAURANT_USER,
        )

        linked = response["order"]
        assert response["message"] == "Comandă legată creată"
        assert linked["id"] != original["id"]
        assert linked["order_number"].endswith("P")
        assert linked["linked_problem_order_id"] == original["id"]
        assert linked["problem_type"] == "missing_product"
        assert linked["items"] == [{"name": "Sos lipsa", "quantity": 2, "price": 5.0}]
        assert linked["delivery_fee"] == 0
        assert linked["total_amount"] == 10

        original_after = await fake_db.orders.find_one({"id": original["id"]})
        assert original_after["has_problem_followup"] is True

    run_async(scenario())


def test_problem_order_requires_delivered_original(fake_db):
    async def scenario():
        original = await create_test_order(total=55)

        with pytest.raises(HTTPException) as exc:
            await orders_router.create_problem_order(
                original["id"],
                ProblemOrderCreate(
                    problem_type="missing_product",
                    item_name="Sos lipsa",
                    quantity=1,
                    price=0,
                    problem_description="Clientul nu a primit sosul",
                ),
                RESTAURANT_USER,
            )

        assert exc.value.status_code == 409
        assert await fake_db.orders.count_documents({"linked_problem_order_id": original["id"]}) == 0

    run_async(scenario())


def test_problem_order_is_blocked_when_restaurant_is_closed(fake_db):
    async def scenario():
        original = await create_test_order(total=55)
        await fake_db.orders.update_one({"id": original["id"]}, {"$set": {"status": "DELIVERED"}})
        await restaurants_router.update_restaurant_status(
            "rest-1",
            restaurants_router.RestaurantStatusUpdate(accepting_orders=False, closed_today=True),
            RESTAURANT_USER,
        )

        with pytest.raises(HTTPException) as exc:
            await orders_router.create_problem_order(
                original["id"],
                ProblemOrderCreate(
                    problem_type="missing_product",
                    item_name="Sos lipsa",
                    quantity=1,
                    price=0,
                    problem_description="Clientul nu a primit sosul",
                ),
                RESTAURANT_USER,
            )

        assert exc.value.status_code == 409
        assert await fake_db.orders.count_documents({"linked_problem_order_id": original["id"]}) == 0
        original_after = await fake_db.orders.find_one({"id": original["id"]})
        assert original_after.get("has_problem_followup") is None

    run_async(scenario())


def test_duplicate_problem_order_is_rejected(fake_db):
    async def scenario():
        original = await create_test_order(total=55)
        await fake_db.orders.update_one({"id": original["id"]}, {"$set": {"status": "DELIVERED"}})
        payload = ProblemOrderCreate(
            problem_type="missing_product",
            item_name="Sos lipsa",
            quantity=1,
            price=0,
            problem_description="Clientul nu a primit sosul",
        )

        await orders_router.create_problem_order(original["id"], payload, RESTAURANT_USER)

        with pytest.raises(HTTPException) as exc:
            await orders_router.create_problem_order(original["id"], payload, RESTAURANT_USER)

        assert exc.value.status_code == 409
        assert await fake_db.orders.count_documents({"linked_problem_order_id": original["id"]}) == 1

    run_async(scenario())
