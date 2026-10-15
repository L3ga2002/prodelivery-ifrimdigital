"""Independent contract tests. Run only through the coordinator's isolated runner.

No implementation helpers are mocked: only persistence is replaced. The protected
suite supplies data/projection helpers; its permissive matcher is never used here.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import test_order_critical_flows as baseline
from models.order import AssignOrder, OrderCreate, PreparationTime, UpdateOrderStatus
from routers import orders as api

ADMIN = baseline.ADMIN_USER
RESTAURANT = baseline.RESTAURANT_USER
DRIVER = baseline.DRIVER_USER
MISSING = object()
FIELD_OPS = {"$eq", "$ne", "$in", "$nin", "$exists", "$gt", "$gte", "$lt", "$lte"}
LOGICAL_OPS = {"$or", "$and", "$nor"}


def validate_query(query):
    for key, expected in query.items():
        if key.startswith("$"):
            assert key in LOGICAL_OPS, f"Unsupported logical operator: {key}"
            assert isinstance(expected, list) and expected
            for branch in expected:
                validate_query(branch)
        elif isinstance(expected, dict) and any(k.startswith("$") for k in expected):
            for operator in expected:
                assert operator in FIELD_OPS, f"Unsupported field operator: {operator}"


def field_value(doc, key):
    value = doc
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def strict_matches(doc, query):
    validate_query(query)
    for key, expected in query.items():
        if key in LOGICAL_OPS:
            results = [strict_matches(doc, branch) for branch in expected]
            if key == "$and" and not all(results):
                return False
            if key == "$or" and not any(results):
                return False
            if key == "$nor" and any(results):
                return False
            continue
        actual = field_value(doc, key)
        # Mongo equality to null also matches a missing field.
        comparable = None if actual is MISSING else actual
        if not isinstance(expected, dict) or not any(k.startswith("$") for k in expected):
            if comparable != expected:
                return False
            continue
        for operator, value in expected.items():
            if operator == "$exists":
                passed = (actual is not MISSING) == value
            elif operator == "$eq":
                passed = comparable == value
            elif operator == "$ne":
                passed = comparable != value
            elif operator in {"$in", "$nin"}:
                included = any(item in value for item in comparable) if isinstance(comparable, list) else comparable in value
                passed = included if operator == "$in" else not included
            elif actual is MISSING or actual is None:
                passed = False
            elif operator == "$gt":
                passed = actual > value
            elif operator == "$gte":
                passed = actual >= value
            elif operator == "$lt":
                passed = actual < value
            else:
                passed = actual <= value
            if not passed:
                return False
    return True


class WriteResult(dict):
    def __getattr__(self, key):
        return self[key]


class StrictCollection(baseline.FakeCollection):
    def __init__(self, docs=None):
        super().__init__(docs)
        self.before_write = None
        self.after_read = None

    def _matches(self, doc, query):
        return strict_matches(doc, query or {})

    async def find_one(self, query, projection=None):
        validate_query(query)
        snapshot = await super().find_one(query, projection)
        if self.after_read:
            await self.after_read(snapshot)
        return snapshot

    def find(self, query=None, projection=None):
        validate_query(query or {})
        return super().find(query, projection)

    async def count_documents(self, query):
        validate_query(query)
        return await super().count_documents(query)

    def _apply_update(self, doc, update):
        assert set(update) <= {"$set", "$inc", "$push", "$unset", "$setOnInsert"}, f"Unsupported update: {update}"
        super()._apply_update(doc, update)
        for key in update.get("$unset", {}):
            doc.pop(key, None)

    async def _interleave(self, query, update):
        validate_query(query)
        hook, self.before_write = self.before_write, None
        if hook:
            await hook(query, update)

    async def update_one(self, query, update):
        await self._interleave(query, update)
        return WriteResult(await super().update_one(query, update))

    async def find_one_and_update(self, query, update, upsert=False, return_document=None, projection=None):
        await self._interleave(query, update)
        exists = any(self._matches(doc, query) for doc in self.docs)
        if upsert and not exists:
            update = copy.deepcopy(update)
            update.setdefault("$set", {}).update(update.pop("$setOnInsert", {}))
        return await super().find_one_and_update(query, update, upsert, return_document, projection)


@pytest.fixture
def db(monkeypatch):
    fake = baseline.FakeDb()
    for key, collection in vars(fake).items():
        setattr(fake, key, StrictCollection(collection.docs))
    monkeypatch.setattr(api, "db", fake)
    monkeypatch.setattr(baseline.restaurants_router, "db", fake)
    return fake


def run(coro):
    return asyncio.run(coro)


async def create():
    return await api.create_order(OrderCreate(**baseline.order_payload()), ADMIN)


async def change(order_id, status, user=DRIVER):
    return await api.update_order_status(order_id, UpdateOrderStatus(status=status), user)


async def start(order_id, minutes=5, user=RESTAURANT):
    return await api.set_preparing(order_id, PreparationTime(preparation_time=minutes), user)


async def assign(order_id):
    return await api.assign_order(order_id, AssignOrder(driver_id="driver-1"), ADMIN)


def stored(db, order_id):
    return next(doc for doc in db.orders.docs if doc["id"] == order_id)


def snapshot(db):
    return copy.deepcopy({key: value.docs for key, value in vars(db).items()})


async def reject_without_changes(db, operation, code):
    before = snapshot(db)
    with pytest.raises(HTTPException) as error:
        await operation
    assert error.value.status_code == code
    assert snapshot(db) == before


def actions(order):
    return baseline.audit_actions(order)


def assert_single_audit(db, order_id, action):
    assert actions(stored(db, order_id)).count(action) == 1
    assert sum(log["action"] == action and log["entity_id"] == order_id for log in db.audit_logs.docs) == 1


@pytest.mark.parametrize("query", [
    {"status": {"$unknown": True}}, {"$where": "anything"},
    {"id": "not-matching", "$or": [{"status": {"$unknown": 1}}]},
])
def test_fake_rejects_unknown_operators_even_on_nonmatching_documents(query):
    with pytest.raises(AssertionError, match="Unsupported"):
        strict_matches({"id": "o", "status": "READY"}, query)


@pytest.mark.parametrize("status,expected", [("NEW", False), ("ASSIGNED", True), ("ACCEPTED", True), ("READY", False)])
def test_fake_in_is_not_silently_ignored(status, expected):
    assert strict_matches({"status": status}, {"status": {"$in": ["ASSIGNED", "ACCEPTED"]}}) is expected


@pytest.mark.parametrize("user", [DRIVER, ADMIN])
def test_driver_feed_excludes_both_terminal_states_but_history_keeps_them(db, user):
    async def scenario():
        for state in ["ASSIGNED", "ACCEPTED", "PICKED_UP", "CANCELLED", "DELIVERED"]:
            order = await create()
            stored(db, order["id"]).update(status=state, driver_id="driver-1")
        other = await create()
        stored(db, other["id"]).update(status="ASSIGNED", driver_id="driver-other")
        before = snapshot(db)
        feed = await api.get_driver_orders("driver-1", user)
        assert {order["status"] for order in feed} == {"ASSIGNED", "ACCEPTED", "PICKED_UP"}
        assert all(order["driver_id"] == "driver-1" for order in feed)
        history = await api.get_orders(user)
        assert {"CANCELLED", "DELIVERED"} <= {order["status"] for order in history}
        if user == DRIVER:
            assert all(order["driver_id"] == "driver-1" for order in history)
        assert snapshot(db) == before
    run(scenario())


@pytest.mark.parametrize("user", [RESTAURANT, {"role": "customer"}, {**DRIVER, "driver_id": "driver-other"}, {"role": "driver"}])
def test_driver_feed_rejects_other_objects_and_roles(db, user):
    run(reject_without_changes(db, api.get_driver_orders("driver-1", user), 403))


@pytest.mark.parametrize("assignment_phase", ["before_prepare", "during_prepare", "after_ready"])
@pytest.mark.parametrize("accept_before_ready", [False, True])
def test_full_flow_keeps_preparation_and_dispatch_independent(db, assignment_phase, accept_before_ready):
    async def scenario():
        order_id = (await create())["id"]
        if assignment_phase == "before_prepare":
            await assign(order_id)
        await start(order_id)
        order = stored(db, order_id)
        assert order["preparation_status"] == "PREPARING"
        assert order["status"] == ("ASSIGNED" if assignment_phase == "before_prepare" else "PREPARING")
        assert order["preparation_estimated_seconds"] == 300
        if assignment_phase == "during_prepare":
            await assign(order_id)
        if accept_before_ready and assignment_phase != "after_ready":
            await change(order_id, "ACCEPTED")
            await reject_without_changes(db, change(order_id, "PICKED_UP"), 409)
        dispatch_before = stored(db, order_id)["status"]
        reservation_before = copy.deepcopy(db.drivers.docs)
        await api.set_ready(order_id, RESTAURANT)
        order = stored(db, order_id)
        assert order["preparation_status"] == "READY"
        assert order["preparation_ready_at"]
        assert order["status"] == (dispatch_before if dispatch_before in {"ASSIGNED", "ACCEPTED"} else "READY")
        assert db.drivers.docs == reservation_before
        if assignment_phase == "after_ready":
            await assign(order_id)
        order = stored(db, order_id)
        assert order["driver_id"] == "driver-1" and order["driver_name"] == "Driver Test"
        assert db.drivers.docs[0]["current_order_id"] == order_id
        before_duplicate = snapshot(db)
        assert (await api.set_ready(order_id, RESTAURANT))["idempotent"] is True
        assert snapshot(db) == before_duplicate
        if order["status"] != "ACCEPTED":
            await change(order_id, "ACCEPTED")
        await change(order_id, "PICKED_UP")
        before_pickup = snapshot(db)
        assert (await change(order_id, "PICKED_UP"))["idempotent"] is True
        assert snapshot(db) == before_pickup
        await change(order_id, "DELIVERED")
        before_delivered = snapshot(db)
        assert (await change(order_id, "DELIVERED"))["idempotent"] is True
        assert snapshot(db) == before_delivered
        assert stored(db, order_id)["status"] == "DELIVERED"
        assert db.drivers.docs[0]["current_order_id"] is None
        assert db.drivers.docs[0]["total_deliveries"] == 1
        assert db.drivers.docs[0]["total_earnings"] == 4
        assert_single_audit(db, order_id, "order.preparing_started")
        assert_single_audit(db, order_id, "order.ready")
    run(scenario())


def test_new_orders_explicitly_initialize_additive_preparation_status(db):
    async def scenario():
        created = await create()
        assert created["preparation_status"] == "NEW"
        assert stored(db, created["id"])["preparation_status"] == "NEW"
    run(scenario())


@pytest.mark.parametrize("operation", ["start", "ready"])
def test_missing_order_returns_controlled_404_without_writes(db, operation):
    call = start("missing") if operation == "start" else api.set_ready("missing", RESTAURANT)
    run(reject_without_changes(db, call, 404))


@pytest.mark.parametrize("status", ["NEW", "ASSIGNED", "ACCEPTED"])
@pytest.mark.parametrize("operation", ["start", "ready"])
def test_invalid_additive_preparation_state_is_rejected_without_writes(db, status, operation):
    async def scenario():
        order_id = (await create())["id"]
        if status != "NEW":
            await assign(order_id)
        if status == "ACCEPTED":
            await change(order_id, "ACCEPTED")
        stored(db, order_id)["preparation_status"] = "BROKEN"
        call = start(order_id) if operation == "start" else api.set_ready(order_id, RESTAURANT)
        await reject_without_changes(db, call, 409)
    run(scenario())


@pytest.mark.parametrize("metadata", ["missing", "started_only", "expired_only", "ready"])
def test_legacy_accepted_pickup_uses_ready_metadata_not_estimate(db, metadata):
    async def scenario():
        order_id = (await create())["id"]
        await assign(order_id)
        await change(order_id, "ACCEPTED")
        order = stored(db, order_id)
        order.pop("preparation_status", None)
        if metadata == "started_only":
            order["preparation_started_at"] = "2026-10-02T10:00:00+00:00"
        elif metadata == "expired_only":
            order["preparation_due_at"] = "2020-01-01T00:00:00+00:00"
        elif metadata == "ready":
            order["preparation_ready_at"] = "2026-10-02T10:05:00+00:00"
        if metadata == "ready":
            await change(order_id, "PICKED_UP")
            assert order["status"] == "PICKED_UP"
        else:
            await reject_without_changes(db, change(order_id, "PICKED_UP"), 409)
    run(scenario())


@pytest.mark.parametrize("public_status", ["ASSIGNED", "ACCEPTED"])
def test_duplicate_start_preserves_timer_dispatch_driver_reservation_and_audit(db, public_status):
    async def scenario():
        order_id = (await create())["id"]
        await assign(order_id)
        if public_status == "ACCEPTED":
            await change(order_id, "ACCEPTED")
        await start(order_id, 5)
        before = snapshot(db)
        duplicate = await start(order_id, 45)
        assert duplicate["idempotent"] is True
        assert snapshot(db) == before
        assert stored(db, order_id)["status"] == public_status
        assert stored(db, order_id)["driver_name"] == "Driver Test"
        assert_single_audit(db, order_id, "order.preparing_started")
    run(scenario())


@pytest.mark.parametrize("public_status", ["ASSIGNED", "ACCEPTED"])
@pytest.mark.parametrize("eligibility", ["bound", "unbound", "other_order", "disabled", "inactive", "missing"])
def test_short_preparation_requires_free_or_own_usable_bound_driver(db, public_status, eligibility):
    async def scenario():
        order_id = (await create())["id"]
        await assign(order_id)
        if public_status == "ACCEPTED":
            await change(order_id, "ACCEPTED")
        driver = db.drivers.docs[0]
        if eligibility == "unbound":
            driver["current_order_id"] = None
        elif eligibility == "other_order":
            driver["current_order_id"] = "different-order"
        elif eligibility == "disabled":
            driver["account_disabled"] = True
        elif eligibility == "inactive":
            driver["is_active"] = False
        elif eligibility == "missing":
            db.drivers.docs.clear()
        assert await api.get_available_driver_count() == 0
        if eligibility == "bound":
            await start(order_id, 5)
            assert stored(db, order_id)["preparation_status"] == "PREPARING"
            assert driver["current_order_id"] == order_id
        else:
            await reject_without_changes(db, start(order_id, 5), 409)
            await start(order_id, 20)
            assert stored(db, order_id)["status"] == public_status
    run(scenario())


def test_unassigned_short_preparation_without_free_driver_is_rejected(db):
    async def scenario():
        order_id = (await create())["id"]
        db.drivers.docs[0]["current_order_id"] = "other"
        await reject_without_changes(db, start(order_id, 5), 409)
        await start(order_id, 20)
        assert stored(db, order_id)["status"] == "PREPARING"
    run(scenario())


@pytest.mark.parametrize("phase", ["NEW", "PREPARING", "READY"])
def test_legacy_public_preparation_status_without_additive_field_still_works(db, phase):
    async def scenario():
        order_id = (await create())["id"]
        order = stored(db, order_id)
        order.pop("preparation_status", None)
        order["status"] = phase
        if phase == "PREPARING":
            order.update(preparation_started_at="2026-10-02T10:00:00+00:00", preparation_time=5)
            await api.set_ready(order_id, RESTAURANT)
            assert order["status"] == "READY" and order["preparation_status"] == "READY"
        elif phase == "NEW":
            await start(order_id)
            assert order["status"] == "PREPARING" and order["preparation_status"] == "PREPARING"
        else:
            before = snapshot(db)
            assert (await api.set_ready(order_id, RESTAURANT))["idempotent"] is True
            assert snapshot(db) == before
    run(scenario())


@pytest.mark.parametrize("public_status", ["ASSIGNED", "ACCEPTED"])
@pytest.mark.parametrize("metadata_phase", ["NEW", "PREPARING", "READY"])
def test_legacy_dispatch_status_uses_started_and_ready_metadata(db, public_status, metadata_phase):
    async def scenario():
        order_id = (await create())["id"]
        await assign(order_id)
        if public_status == "ACCEPTED":
            await change(order_id, "ACCEPTED")
        order = stored(db, order_id)
        order.pop("preparation_status", None)
        if metadata_phase != "NEW":
            order.update(preparation_started_at="2026-10-02T10:00:00+00:00", preparation_time=5)
        if metadata_phase == "READY":
            order["preparation_ready_at"] = "2026-10-02T10:05:00+00:00"
            before = snapshot(db)
            assert (await api.set_ready(order_id, RESTAURANT))["idempotent"] is True
            assert snapshot(db) == before
            await reject_without_changes(db, start(order_id), 409)
        elif metadata_phase == "PREPARING":
            before = snapshot(db)
            assert (await start(order_id, 45))["idempotent"] is True
            assert snapshot(db) == before
            await api.set_ready(order_id, RESTAURANT)
            assert order["preparation_status"] == "READY"
        else:
            await reject_without_changes(db, api.set_ready(order_id, RESTAURANT), 409)
            await start(order_id)
            assert order["preparation_status"] == "PREPARING"
        assert order["status"] == public_status
        assert db.drivers.docs[0]["current_order_id"] == order_id
    run(scenario())


@pytest.mark.parametrize("user", [DRIVER, {"role": "customer"}, {**RESTAURANT, "restaurant_id": "rest-other"}, {"role": "restaurant"}, {}])
@pytest.mark.parametrize("operation", ["start", "ready"])
def test_preparation_role_and_restaurant_ownership_checks(db, user, operation):
    async def scenario():
        order_id = (await create())["id"]
        await start(order_id)
        call = start(order_id, user=user) if operation == "start" else api.set_ready(order_id, user)
        await reject_without_changes(db, call, 403)
    run(scenario())


@pytest.mark.parametrize("public_status", ["PICKED_UP", "CANCELLED", "DELIVERED", "BROKEN"])
@pytest.mark.parametrize("operation", ["start", "ready"])
def test_terminal_inflight_or_invalid_public_status_cannot_be_reopened(db, public_status, operation):
    async def scenario():
        order_id = (await create())["id"]
        await start(order_id)
        order = stored(db, order_id)
        order["status"] = public_status
        # Even stale READY preparation cannot bypass the public terminal gate.
        order["preparation_status"] = "READY" if operation == "ready" else "PREPARING"
        call = start(order_id) if operation == "start" else api.set_ready(order_id, RESTAURANT)
        await reject_without_changes(db, call, 409)
    run(scenario())


@pytest.mark.parametrize("status", ["NEW", "ASSIGNED", "ACCEPTED"])
def test_ready_requires_preparation_to_have_started(db, status):
    async def scenario():
        order_id = (await create())["id"]
        if status != "NEW":
            await assign(order_id)
        if status == "ACCEPTED":
            await change(order_id, "ACCEPTED")
        await reject_without_changes(db, api.set_ready(order_id, RESTAURANT), 409)
    run(scenario())


@pytest.mark.parametrize("assigned", [False, True])
def test_preparation_cannot_restart_after_ready(db, assigned):
    async def scenario():
        order_id = (await create())["id"]
        await start(order_id)
        await api.set_ready(order_id, RESTAURANT)
        if assigned:
            await assign(order_id)
        await reject_without_changes(db, start(order_id, 45), 409)
    run(scenario())


@pytest.mark.parametrize("expired", [False, True])
def test_pickup_requires_actual_ready_not_estimated_expiry(db, expired):
    async def scenario():
        order_id = (await create())["id"]
        await assign(order_id)
        await start(order_id)
        await change(order_id, "ACCEPTED")
        order = stored(db, order_id)
        if expired:
            order["preparation_due_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await reject_without_changes(db, change(order_id, "PICKED_UP"), 409)
        assert order["preparation_status"] == "PREPARING"
        await api.set_ready(order_id, RESTAURANT)
        await change(order_id, "PICKED_UP")
        assert order["status"] == "PICKED_UP"
    run(scenario())


@pytest.mark.parametrize("user", [RESTAURANT, {"role": "customer"}, {**DRIVER, "driver_id": "other-driver"}])
@pytest.mark.parametrize("status", ["ACCEPTED", "PICKED_UP", "DELIVERED"])
def test_driver_status_ownership_remains_strict(db, user, status):
    async def scenario():
        order_id = (await create())["id"]
        await start(order_id)
        await api.set_ready(order_id, RESTAURANT)
        await assign(order_id)
        if status in {"PICKED_UP", "DELIVERED"}:
            await change(order_id, "ACCEPTED")
        if status == "DELIVERED":
            await change(order_id, "PICKED_UP")
        await reject_without_changes(db, change(order_id, status, user), 403)
    run(scenario())


@pytest.mark.parametrize("value", [0, -1, 241, "invalid", None])
def test_preparation_time_invalid_payloads_still_fail_validation(value):
    with pytest.raises(ValidationError):
        PreparationTime(preparation_time=value)


@pytest.mark.parametrize("timestamp", ["garbage", "2026-10-02T10:00:00", datetime(2026, 10, 2, 10), 123, {"bad": "timestamp"}])
def test_malformed_legacy_started_timestamp_has_controlled_response_not_500(db, timestamp):
    async def scenario():
        order_id = (await create())["id"]
        await start(order_id)
        stored(db, order_id)["preparation_started_at"] = timestamp
        before = snapshot(db)
        try:
            response = await api.set_ready(order_id, RESTAURANT)
        except HTTPException as error:
            assert error.status_code in {400, 409, 422}
            assert snapshot(db) == before
        else:
            assert isinstance(response, dict)
            order = stored(db, order_id)
            assert order["status"] == "READY" and order["preparation_status"] == "READY"
            assert order.get("preparation_actual_seconds") is None or order["preparation_actual_seconds"] >= 0
            assert_single_audit(db, order_id, "order.ready")
    run(scenario())


@pytest.mark.parametrize("assigned", [False, True])
def test_two_starts_loaded_from_same_snapshot_only_start_once(db, assigned):
    async def scenario():
        order_id = (await create())["id"]
        if assigned:
            await assign(order_id)
        gate = asyncio.Event()
        count = 0

        async def synchronize_reads(doc):
            nonlocal count
            if doc and doc.get("id") == order_id and count < 2:
                count += 1
                if count == 2:
                    gate.set()
                await gate.wait()

        db.orders.after_read = synchronize_reads
        responses = await asyncio.wait_for(asyncio.gather(start(order_id, 5), start(order_id, 45)), timeout=5)
        db.orders.after_read = None
        assert count == 2
        assert sum(response.get("idempotent", False) for response in responses) == 1
        order = stored(db, order_id)
        assert order["preparation_time"] in {5, 45}
        assert order["preparation_estimated_seconds"] == order["preparation_time"] * 60
        duration = datetime.fromisoformat(order["preparation_due_at"]) - datetime.fromisoformat(order["preparation_started_at"])
        assert duration.total_seconds() == order["preparation_estimated_seconds"]
        assert order["status"] == ("ASSIGNED" if assigned else "PREPARING")
        assert_single_audit(db, order_id, "order.preparing_started")
    run(scenario())


@pytest.mark.parametrize("race", ["cancel", "reassign"])
def test_ready_loses_compare_and_swap_against_cancellation_or_reassignment(db, race):
    async def scenario():
        order_id = (await create())["id"]
        await assign(order_id)
        await start(order_id)
        concurrent_state = None

        async def competing_write(query, update):
            nonlocal concurrent_state
            assert update.get("$set", {}).get("preparation_ready_at"), "Hook must precede ready write"
            if race == "cancel":
                await api.update_order_status(order_id, UpdateOrderStatus(status="CANCELLED", cancellation_reason="QA race"), ADMIN)
            else:
                second = copy.deepcopy(db.drivers.docs[0])
                second.update(id="driver-2", name="Second driver", current_order_id=None, driver_status="active")
                db.drivers.docs.append(second)
                await api.assign_order(order_id, AssignOrder(driver_id="driver-2"), ADMIN)
            concurrent_state = snapshot(db)

        db.orders.before_write = competing_write
        with pytest.raises(HTTPException) as error:
            await api.set_ready(order_id, RESTAURANT)
        assert error.value.status_code == 409
        assert concurrent_state is not None
        assert snapshot(db) == concurrent_state
        assert "order.ready" not in actions(stored(db, order_id))
        if race == "cancel":
            assert stored(db, order_id)["status"] == "CANCELLED"
            assert db.drivers.docs[0]["current_order_id"] is None
        else:
            assert stored(db, order_id)["driver_id"] == "driver-2"
            assert db.drivers.docs[1]["current_order_id"] == order_id
    run(scenario())


def add_replacement_driver(db):
    replacement = copy.deepcopy(db.drivers.docs[0])
    replacement.update(id="driver-2", name="Replacement driver", current_order_id=None,
                       driver_status="active", is_active=True, account_disabled=False,
                       total_deliveries=0, total_earnings=0)
    db.drivers.docs.append(replacement)
    return replacement


async def prepare_to_phase(order_id, phase):
    if phase in {"PREPARING", "READY"}:
        await start(order_id)
    if phase == "READY":
        await api.set_ready(order_id, RESTAURANT)


def preparation_metadata(order):
    return copy.deepcopy({key: value for key, value in order.items() if key.startswith("preparation_")})


async def outcome_or_conflict(operation):
    try:
        return await operation
    except HTTPException as error:
        assert error.status_code == 409
        return error


@pytest.mark.parametrize("phase", ["NEW", "PREPARING", "READY"])
@pytest.mark.parametrize("replacement", [False, True])
def test_b1_same_snapshot_duplicate_assignment_preserves_winner_and_safe_retry(db, phase, replacement):
    async def scenario():
        order_id = (await create())["id"]
        await prepare_to_phase(order_id, phase)
        target = "driver-1"
        if replacement:
            await assign(order_id)
            add_replacement_driver(db)
            target = "driver-2"
        metadata_before = preparation_metadata(stored(db, order_id))
        audit_before = actions(stored(db, order_id)).count("order.assigned")
        gate = asyncio.Event()
        reads = 0
        winner_snapshot = None

        async def same_snapshot(doc):
            nonlocal reads
            if doc and doc.get("id") == order_id and reads < 2:
                reads += 1
                if reads == 2:
                    gate.set()
                await gate.wait()

        async def attempt():
            nonlocal winner_snapshot
            result = await outcome_or_conflict(api.assign_order(order_id, AssignOrder(driver_id=target), ADMIN))
            if isinstance(result, dict) and not result.get("idempotent"):
                winner_snapshot = snapshot(db)
            return result

        db.orders.after_read = same_snapshot
        results = await asyncio.wait_for(asyncio.gather(attempt(), attempt()), timeout=5)
        db.orders.after_read = None
        assert reads == 2
        committed = [result for result in results if isinstance(result, dict) and not result.get("idempotent")]
        assert len(committed) == 1
        assert winner_snapshot is not None
        assert snapshot(db) == winner_snapshot
        order = stored(db, order_id)
        driver = next(doc for doc in db.drivers.docs if doc["id"] == target)
        assert order["status"] == "ASSIGNED" and order["driver_id"] == target
        assert order["driver_name"] == driver["name"]
        assert driver["current_order_id"] == order_id and driver["driver_status"] == "delivery"
        assert preparation_metadata(order) == metadata_before
        assert actions(order).count("order.assigned") == audit_before + 1
        assert sum(log["action"] == "order.assigned" and log["entity_id"] == order_id for log in db.audit_logs.docs) == audit_before + 1
        assert order["assigned_at"] and order["updated_at"]
        if replacement:
            assert db.drivers.docs[0]["current_order_id"] is None
        winner = snapshot(db)
        retry = await api.assign_order(order_id, AssignOrder(driver_id=target), ADMIN)
        assert retry["idempotent"] is True
        assert snapshot(db) == winner
    run(scenario())


@pytest.mark.parametrize("phase", ["NEW", "PREPARING"])
def test_b1_preparation_cas_loss_and_competing_same_driver_claim_do_not_release_winner(db, phase):
    async def scenario():
        order_id = (await create())["id"]
        await prepare_to_phase(order_id, phase)
        winning_preparation = None
        competing_result = None

        async def preparation_and_competing_assignment(query, update):
            nonlocal winning_preparation, competing_result
            assert update.get("$set", {}).get("status") == "ASSIGNED"
            if phase == "NEW":
                await start(order_id, 20)
            else:
                await api.set_ready(order_id, RESTAURANT)
            winning_preparation = preparation_metadata(stored(db, order_id))
            competing_result = await outcome_or_conflict(assign(order_id))

        db.orders.before_write = preparation_and_competing_assignment
        stale_result = await outcome_or_conflict(assign(order_id))
        assert winning_preparation is not None and competing_result is not None
        assert isinstance(stale_result, HTTPException) or stale_result.get("idempotent") is True
        if isinstance(competing_result, dict):
            assert db.drivers.docs[0]["current_order_id"] == order_id
            before_retry = snapshot(db)
            assert (await assign(order_id))["idempotent"] is True
            assert snapshot(db) == before_retry
        else:
            await assign(order_id)
        assert preparation_metadata(stored(db, order_id)) == winning_preparation
        assert stored(db, order_id)["driver_id"] == "driver-1"
        assert db.drivers.docs[0]["current_order_id"] == order_id
        assert_single_audit(db, order_id, "order.assigned")
    run(scenario())


@pytest.mark.parametrize("state", ["NEW", "PREPARING", "READY", "ASSIGNED_SAME", "ASSIGNED_REPLACEMENT"])
@pytest.mark.parametrize("bad_metadata", ["INVALID", ["READY"], {"status": "READY"}])
def test_b2_bad_preparation_metadata_assignment_or_replacement_has_no_db_writes(db, state, bad_metadata):
    async def scenario():
        order_id = (await create())["id"]
        await prepare_to_phase(order_id, state if state in {"NEW", "PREPARING", "READY"} else "PREPARING")
        add_replacement_driver(db)
        target = "driver-1"
        if state.startswith("ASSIGNED"):
            await assign(order_id)
            if state == "ASSIGNED_REPLACEMENT":
                target = "driver-2"
        stored(db, order_id)["preparation_status"] = copy.deepcopy(bad_metadata)
        await reject_without_changes(db, api.assign_order(order_id, AssignOrder(driver_id=target), ADMIN), 409)
    run(scenario())


async def terminal_action(order_id, terminal):
    if terminal == "CANCELLED":
        return await api.update_order_status(order_id, UpdateOrderStatus(status="CANCELLED", cancellation_reason="Synthetic QA"), ADMIN)
    return await change(order_id, "DELIVERED")


async def old_order_for_terminal(terminal):
    order_id = (await create())["id"]
    await prepare_to_phase(order_id, "READY")
    await assign(order_id)
    if terminal == "DELIVERED":
        await change(order_id, "ACCEPTED")
        await change(order_id, "PICKED_UP")
    return order_id


@pytest.mark.parametrize("terminal", ["CANCELLED", "DELIVERED"])
@pytest.mark.parametrize("disabled", [False, True])
def test_b3_terminal_old_order_a_preserves_driver_currently_bound_to_b_and_delivery_credit(db, terminal, disabled):
    async def scenario():
        old_id = await old_order_for_terminal(terminal)
        new_id = (await create())["id"]
        # Synthetic inconsistent old binding reproduces the reviewed legacy risk.
        db.drivers.docs[0].update(current_order_id=None, driver_status="active")
        await assign(new_id)
        driver = db.drivers.docs[0]
        if disabled:
            driver.update(account_disabled=True, is_active=False)
        new_before = copy.deepcopy(stored(db, new_id))
        driver_before = copy.deepcopy(driver)
        audit_before = actions(stored(db, old_id)).count("order.status_changed")
        await terminal_action(old_id, terminal)
        expected_driver = copy.deepcopy(driver_before)
        if terminal == "DELIVERED":
            expected_driver["total_deliveries"] += 1
            expected_driver["total_earnings"] += 4
        assert driver == expected_driver
        assert stored(db, new_id) == new_before
        assert driver["current_order_id"] == new_id
        old = stored(db, old_id)
        assert old["status"] == terminal
        assert actions(old).count("order.status_changed") == audit_before + 1
        before_duplicate = snapshot(db)
        assert (await terminal_action(old_id, terminal))["idempotent"] is True
        assert snapshot(db) == before_duplicate
    run(scenario())


@pytest.mark.parametrize("terminal", ["CANCELLED", "DELIVERED"])
def test_b3_releasing_disabled_drivers_own_order_does_not_reactivate_account(db, terminal):
    async def scenario():
        order_id = await old_order_for_terminal(terminal)
        driver = db.drivers.docs[0]
        driver.update(account_disabled=True, is_active=False, driver_status="offline")
        await terminal_action(order_id, terminal)
        assert driver["current_order_id"] is None
        assert driver["account_disabled"] is True and driver["is_active"] is False
        assert driver["driver_status"] != "active"
        assert driver["total_deliveries"] == (1 if terminal == "DELIVERED" else 0)
        assert driver["total_earnings"] == (4 if terminal == "DELIVERED" else 0)
        winner = snapshot(db)
        assert (await terminal_action(order_id, terminal))["idempotent"] is True
        assert snapshot(db) == winner
    run(scenario())


@pytest.mark.parametrize("target_status", ["ACCEPTED", "CANCELLED"])
def test_b4_stale_driver_fallback_cannot_return_success_for_new_owners_action(db, target_status):
    async def scenario():
        order_id = (await create())["id"]
        await assign(order_id)
        add_replacement_driver(db)
        new_driver_user = {**DRIVER, "driver_id": "driver-2", "user_id": "second-user", "id": "second-user"}
        competing_state = None

        async def reassign_and_apply_same_target(query, update):
            nonlocal competing_state
            assert update.get("$set", {}).get("status") == target_status
            await api.assign_order(order_id, AssignOrder(driver_id="driver-2"), ADMIN)
            await api.update_order_status(order_id, UpdateOrderStatus(status=target_status, cancellation_reason="Synthetic QA" if target_status == "CANCELLED" else None), new_driver_user)
            competing_state = snapshot(db)

        db.orders.before_write = reassign_and_apply_same_target
        with pytest.raises(HTTPException) as error:
            await api.update_order_status(order_id, UpdateOrderStatus(status=target_status, cancellation_reason="Synthetic QA" if target_status == "CANCELLED" else None), DRIVER)
        assert error.value.status_code in {403, 409}
        assert competing_state is not None
        assert snapshot(db) == competing_state
        assert stored(db, order_id)["driver_id"] == "driver-2"
        assert stored(db, order_id)["status"] == target_status
    run(scenario())


@pytest.mark.parametrize("target_status", ["ACCEPTED", "PICKED_UP", "DELIVERED"])
def test_b4_same_owner_status_cas_fallback_remains_idempotent_without_double_credit(db, target_status):
    async def scenario():
        order_id = (await create())["id"]
        await prepare_to_phase(order_id, "READY")
        await assign(order_id)
        if target_status in {"PICKED_UP", "DELIVERED"}:
            await change(order_id, "ACCEPTED")
        if target_status == "DELIVERED":
            await change(order_id, "PICKED_UP")
        winning_state = None

        async def duplicate_commits_first(query, update):
            nonlocal winning_state
            await change(order_id, target_status)
            winning_state = snapshot(db)

        db.orders.before_write = duplicate_commits_first
        assert (await change(order_id, target_status))["idempotent"] is True
        assert winning_state is not None
        assert snapshot(db) == winning_state
        if target_status == "DELIVERED":
            assert db.drivers.docs[0]["total_deliveries"] == 1
            assert db.drivers.docs[0]["total_earnings"] == 4
    run(scenario())


MALFORMED_LEGACY_TIMESTAMPS = [
    pytest.param("not-a-date", id="garbage"),
    pytest.param("", id="empty-nonnull"),
    pytest.param("2026-10-02", id="date-without-time"),
    pytest.param("2026-10-02T10:00", id="missing-seconds"),
    pytest.param("2026-02-30T10:00:00+00:00", id="impossible-february-30"),
    pytest.param(123, id="number"),
    pytest.param(0, id="falsey-number"),
    pytest.param(False, id="boolean"),
    pytest.param([], id="list"),
    pytest.param({}, id="object"),
]
VALID_LEGACY_TIMESTAMPS = [
    pytest.param("2026-10-02T10:00:00+00:00", id="iso-offset"),
    pytest.param("2026-10-02T10:00:00Z", id="iso-z"),
    pytest.param(datetime(2026, 10, 2, 10, tzinfo=timezone.utc), id="native-aware"),
    pytest.param(datetime(2026, 10, 2, 10), id="native-naive-mongo"),
]


def set_legacy_additive_absence(order, absence):
    if absence == "missing":
        order.pop("preparation_status", None)
    else:
        order["preparation_status"] = None


async def dispatched_order(public_status):
    order_id = (await create())["id"]
    await assign(order_id)
    if public_status == "ACCEPTED":
        await change(order_id, "ACCEPTED")
    return order_id


@pytest.mark.parametrize("public_status", ["ASSIGNED", "ACCEPTED"])
@pytest.mark.parametrize("absence", ["missing", "null"])
@pytest.mark.parametrize("field", ["preparation_started_at", "preparation_ready_at"])
@pytest.mark.parametrize("bad_timestamp", MALFORMED_LEGACY_TIMESTAMPS)
@pytest.mark.parametrize("operation", ["assignment", "preparing", "ready", "pickup"])
def test_f1_malformed_nonnull_legacy_dispatch_timestamp_rejects_before_any_writes(
    db, public_status, absence, field, bad_timestamp, operation,
):
    async def scenario():
        order_id = await dispatched_order(public_status)
        add_replacement_driver(db)
        order = stored(db, order_id)
        set_legacy_additive_absence(order, absence)
        # A valid counterpart must not mask another malformed non-null field.
        order.update(preparation_started_at="2026-10-02T10:00:00+00:00",
                     preparation_ready_at="2026-10-02T10:05:00+00:00",
                     preparation_time=5, preparation_estimated_seconds=300)
        order[field] = copy.deepcopy(bad_timestamp)
        if operation == "assignment":
            call = api.assign_order(order_id, AssignOrder(driver_id="driver-2"), ADMIN)
        elif operation == "preparing":
            call = start(order_id)
        elif operation == "ready":
            call = api.set_ready(order_id, RESTAURANT)
        else:
            call = change(order_id, "PICKED_UP")
        await reject_without_changes(db, call, 409)
    run(scenario())


@pytest.mark.parametrize("public_status", ["ASSIGNED", "ACCEPTED"])
@pytest.mark.parametrize("absence", ["missing", "null"])
@pytest.mark.parametrize("timestamp", VALID_LEGACY_TIMESTAMPS)
@pytest.mark.parametrize("phase", ["PREPARING", "READY"])
def test_f1_valid_iso_and_native_legacy_dispatch_metadata_preserves_full_flow(
    db, public_status, absence, timestamp, phase,
):
    async def scenario():
        order_id = await dispatched_order(public_status)
        order = stored(db, order_id)
        set_legacy_additive_absence(order, absence)
        order.update(preparation_started_at=copy.deepcopy(timestamp),
                     preparation_ready_at=copy.deepcopy(timestamp) if phase == "READY" else None,
                     preparation_time=5, preparation_estimated_seconds=300)
        before = snapshot(db)
        if phase == "PREPARING":
            assert (await start(order_id, 45))["idempotent"] is True
            assert snapshot(db) == before
            await api.set_ready(order_id, RESTAURANT)
            assert order["preparation_status"] == "READY"
            assert_single_audit(db, order_id, "order.ready")
        else:
            assert (await api.set_ready(order_id, RESTAURANT))["idempotent"] is True
            assert snapshot(db) == before
            await reject_without_changes(db, start(order_id), 409)
        assert order["status"] == public_status
        assert db.drivers.docs[0]["current_order_id"] == order_id
        if public_status == "ASSIGNED":
            await change(order_id, "ACCEPTED")
        await change(order_id, "PICKED_UP")
        assert order["status"] == "PICKED_UP"
    run(scenario())


@pytest.mark.parametrize("public_status", ["ASSIGNED", "ACCEPTED"])
@pytest.mark.parametrize("absence", ["missing", "null"])
@pytest.mark.parametrize("timestamp_absence", ["missing", "null"])
def test_f1_missing_or_null_legacy_timestamps_infer_new_not_ready(
    db, public_status, absence, timestamp_absence,
):
    async def scenario():
        order_id = await dispatched_order(public_status)
        order = stored(db, order_id)
        set_legacy_additive_absence(order, absence)
        for field in ("preparation_started_at", "preparation_ready_at"):
            if timestamp_absence == "missing":
                order.pop(field, None)
            else:
                order[field] = None
        await reject_without_changes(db, api.set_ready(order_id, RESTAURANT), 409)
        await reject_without_changes(db, change(order_id, "PICKED_UP"), 409)
        await start(order_id)
        assert order["preparation_status"] == "PREPARING" and order["status"] == public_status
        await api.set_ready(order_id, RESTAURANT)
        assert order["preparation_status"] == "READY" and order["status"] == public_status
    run(scenario())


@pytest.mark.parametrize("public_status", ["ASSIGNED", "ACCEPTED"])
@pytest.mark.parametrize("explicit_phase", ["NEW", "PREPARING", "READY"])
@pytest.mark.parametrize("bad_field", ["preparation_started_at", "preparation_ready_at"])
def test_f1_valid_explicit_dispatch_phase_is_authoritative_over_bad_old_timestamps(
    db, public_status, explicit_phase, bad_field,
):
    async def scenario():
        order_id = await dispatched_order(public_status)
        order = stored(db, order_id)
        order.update(preparation_status=explicit_phase,
                     preparation_started_at="2026-10-02T10:00:00+00:00",
                     preparation_ready_at="2026-10-02T10:05:00+00:00",
                     preparation_time=5, preparation_estimated_seconds=300)
        order[bad_field] = {"malformed": "old metadata"}
        before = snapshot(db)
        if explicit_phase != "READY":
            await reject_without_changes(db, change(order_id, "PICKED_UP"), 409)
        if explicit_phase == "NEW":
            await reject_without_changes(db, api.set_ready(order_id, RESTAURANT), 409)
            await start(order_id)
            assert order["preparation_status"] == "PREPARING"
        elif explicit_phase == "PREPARING":
            assert (await start(order_id, 45))["idempotent"] is True
            assert snapshot(db) == before
        else:
            assert (await api.set_ready(order_id, RESTAURANT))["idempotent"] is True
            assert snapshot(db) == before
            await reject_without_changes(db, start(order_id), 409)
            if public_status == "ASSIGNED":
                await change(order_id, "ACCEPTED")
            await change(order_id, "PICKED_UP")
            assert order["status"] == "PICKED_UP"
    run(scenario())


@pytest.mark.parametrize("public_phase", ["NEW", "PREPARING", "READY"])
@pytest.mark.parametrize("explicit_phase", ["NEW", "PREPARING", "READY"])
@pytest.mark.parametrize("bad_field", ["preparation_started_at", "preparation_ready_at"])
def test_f1_public_preparation_phase_keeps_precedence_over_valid_explicit_and_old_metadata(
    db, public_phase, explicit_phase, bad_field,
):
    async def scenario():
        order_id = (await create())["id"]
        order = stored(db, order_id)
        order.update(status=public_phase, preparation_status=explicit_phase,
                     preparation_started_at="2026-10-02T10:00:00+00:00",
                     preparation_ready_at="2026-10-02T10:05:00+00:00")
        order[bad_field] = "2026-02-30T10:00:00+00:00"
        before = snapshot(db)
        if public_phase == "NEW":
            await start(order_id)
            assert order["status"] == "PREPARING" and order["preparation_status"] == "PREPARING"
        elif public_phase == "PREPARING":
            assert (await start(order_id))["idempotent"] is True
            assert snapshot(db) == before
        else:
            assert (await api.set_ready(order_id, RESTAURANT))["idempotent"] is True
            assert snapshot(db) == before
    run(scenario())


def test_f2_real_stats_mixed_three_orders_excludes_terminals_from_active_and_preserves_history(db, monkeypatch):
    from routers import stats as stats_api

    monkeypatch.setattr(stats_api, "db", db)

    async def scenario():
        expected_ids = set()
        for status in ("ASSIGNED", "CANCELLED", "DELIVERED"):
            order_id = (await create())["id"]
            stored(db, order_id).update(status=status, driver_id="driver-1")
            expected_ids.add(order_id)
        before = snapshot(db)
        stats = await stats_api.get_stats(ADMIN)
        assert stats == {
            "total_orders": 3, "active_orders": 1, "delivered_orders": 1,
            "cancelled_orders": 1, "active_drivers": 1, "total_drivers": 1,
            "total_restaurants": 1,
        }
        history = await api.get_orders(ADMIN)
        assert {order["id"] for order in history} == expected_ids
        assert {order["status"] for order in history} == {"ASSIGNED", "CANCELLED", "DELIVERED"}
        driver_history = await api.get_orders(DRIVER)
        assert {order["id"] for order in driver_history} == expected_ids
        driver_feed = await api.get_driver_orders("driver-1", DRIVER)
        assert len(driver_feed) == 1 and driver_feed[0]["status"] == "ASSIGNED"
        assert snapshot(db) == before
    run(scenario())


@pytest.mark.parametrize("absence", ["missing", "null"])
@pytest.mark.parametrize("timestamp", VALID_LEGACY_TIMESTAMPS)
@pytest.mark.parametrize("phase", ["PREPARING", "READY"])
def test_f1_reassignment_preserves_valid_iso_or_native_legacy_preparation(db, absence, timestamp, phase):
    async def scenario():
        order_id = await dispatched_order("ASSIGNED")
        add_replacement_driver(db)
        order = stored(db, order_id)
        set_legacy_additive_absence(order, absence)
        order.update(preparation_started_at=copy.deepcopy(timestamp),
                     preparation_ready_at=copy.deepcopy(timestamp) if phase == "READY" else None,
                     preparation_time=5, preparation_estimated_seconds=300)
        metadata_before = preparation_metadata(order)
        metadata_before.pop("preparation_status", None)
        await api.assign_order(order_id, AssignOrder(driver_id="driver-2"), ADMIN)
        metadata_after = preparation_metadata(order)
        metadata_after.pop("preparation_status", None)
        assert metadata_after == metadata_before
        assert order["preparation_status"] == phase
        assert order["status"] == "ASSIGNED" and order["driver_id"] == "driver-2"
        assert db.drivers.docs[0]["current_order_id"] is None
        assert db.drivers.docs[1]["current_order_id"] == order_id
        before_duplicate = snapshot(db)
        assert (await api.assign_order(order_id, AssignOrder(driver_id="driver-2"), ADMIN))["idempotent"] is True
        assert snapshot(db) == before_duplicate
    run(scenario())


@pytest.mark.parametrize("pointer", ["B", "null", "missing"])
def test_b3r_stale_cleanup_a_cannot_mutate_any_field_of_unowned_driver(db, pointer):
    async def scenario():
        driver = db.drivers.docs[0]
        driver.update(current_order_id="B", driver_status="delivery")
        if pointer == "null":
            driver["current_order_id"] = None
        elif pointer == "missing":
            driver.pop("current_order_id")
        db.orders.docs.append({"id": "B", "status": "ASSIGNED", "driver_id": "driver-1"})
        before = snapshot(db)
        await api.clear_driver_assignment({"id": "A", "driver_id": "driver-1"})
        assert snapshot(db) == before
    run(scenario())


def test_b3r_eligible_driver_own_a_release_clears_pointer_and_activates_only_status(db):
    async def scenario():
        driver = db.drivers.docs[0]
        driver.update(current_order_id="A", driver_status="delivery", is_active=True, account_disabled=False)
        expected = snapshot(db)
        expected["drivers"][0].update(current_order_id=None, driver_status="active")
        await api.clear_driver_assignment({"id": "A", "driver_id": "driver-1"})
        assert snapshot(db) == expected
    run(scenario())


@pytest.mark.parametrize("condition", ["disabled", "inactive", "disabled_and_inactive"])
def test_b3r_ineligible_driver_own_a_release_changes_only_pointer(db, condition):
    async def scenario():
        driver = db.drivers.docs[0]
        driver.update(current_order_id="A", driver_status="delivery",
                      account_disabled=condition != "inactive", is_active=condition == "disabled")
        expected = snapshot(db)
        expected["drivers"][0]["current_order_id"] = None
        await api.clear_driver_assignment({"id": "A", "driver_id": "driver-1"})
        assert snapshot(db) == expected
    run(scenario())


@pytest.mark.parametrize("new_pointer", ["B", "null", "missing"])
def test_b3r_cleanup_interleaving_new_b_after_first_write_preserves_complete_winner(db, monkeypatch, new_pointer):
    async def scenario():
        driver = db.drivers.docs[0]
        driver.update(current_order_id="A", driver_status="delivery")
        original_update = db.drivers.update_one
        writes = 0
        winner = None

        async def insert_b_after_first_cleanup_write(query, update):
            nonlocal writes, winner
            result = await original_update(query, update)
            writes += 1
            if writes == 1:
                # The adversarial B null/missing binding is deliberately synthetic.
                db.orders.docs.append({"id": "B", "status": "ASSIGNED", "driver_id": "driver-1"})
                driver.update(current_order_id="B", driver_status="delivery", is_active=True, account_disabled=False)
                if new_pointer == "null":
                    driver["current_order_id"] = None
                elif new_pointer == "missing":
                    driver.pop("current_order_id")
                winner = snapshot(db)
            return result

        monkeypatch.setattr(db.drivers, "update_one", insert_b_after_first_cleanup_write)
        await api.clear_driver_assignment({"id": "A", "driver_id": "driver-1"})
        assert writes >= 1 and winner is not None
        assert snapshot(db) == winner
    run(scenario())


@pytest.mark.parametrize("offset", ["+00:60", "+01:99", "-00:60", "-01:99"])
@pytest.mark.parametrize("absence", ["missing", "null"])
@pytest.mark.parametrize("field", ["preparation_started_at", "preparation_ready_at"])
@pytest.mark.parametrize("operation", ["assign", "reassign", "start", "ready", "pickup"])
def test_f1r_invalid_signed_offset_minutes_rejected_without_any_db_writes(db, offset, absence, field, operation):
    async def scenario():
        status = "ACCEPTED" if operation == "pickup" else "ASSIGNED"
        order_id = await dispatched_order(status)
        add_replacement_driver(db)
        order = stored(db, order_id)
        set_legacy_additive_absence(order, absence)
        order.update(preparation_started_at="2026-10-02T10:00:00+00:00",
                     preparation_ready_at="2026-10-02T10:05:00+00:00" if operation == "pickup" or field == "preparation_ready_at" else None,
                     preparation_time=5, preparation_estimated_seconds=300)
        order[field] = "2026-10-02T10:00:00" + offset
        if operation in {"assign", "reassign"}:
            call = api.assign_order(order_id, AssignOrder(driver_id="driver-1" if operation == "assign" else "driver-2"), ADMIN)
        elif operation == "start":
            call = start(order_id)
        elif operation == "ready":
            call = api.set_ready(order_id, RESTAURANT)
        else:
            call = change(order_id, "PICKED_UP")
        await reject_without_changes(db, call, 409)
    run(scenario())


@pytest.mark.parametrize("offset", ["+23:59", "-23:59"])
@pytest.mark.parametrize("absence", ["missing", "null"])
@pytest.mark.parametrize("status", ["ASSIGNED", "ACCEPTED"])
@pytest.mark.parametrize("field,expected_phase", [("preparation_started_at", "PREPARING"), ("preparation_ready_at", "READY")])
def test_f1r_valid_extreme_signed_offsets_keep_legacy_helper_compatible(db, offset, absence, status, field, expected_phase):
    async def scenario():
        order_id = await dispatched_order(status)
        order = stored(db, order_id)
        set_legacy_additive_absence(order, absence)
        order.update(preparation_started_at=None, preparation_ready_at=None)
        order[field] = "2026-10-02T10:00:00" + offset
        before = snapshot(db)
        assert api._preparation_status_for_order(order) == expected_phase
        assert snapshot(db) == before
    run(scenario())
