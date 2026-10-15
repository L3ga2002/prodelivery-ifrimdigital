"""Independent router QA on staged source and owned synthetic documents only.

All matching delegates to the independent BSON-aware matcher, never the baseline
matcher. Deterministic interleaving checks wiring, not real Mongo atomicity.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson.int64 import Int64
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest

import test_order_critical_flows as baseline
from test_order_revision_compat import (
    INVALID_VERSIONS, MAX_VERSION, MISSING, apply_update, matches,
)
from models.order import AssignOrder, PreparationTime, ProblemOrderCreate, UpdateOrderStatus
from routers import orders as api


ADMIN = baseline.ADMIN_USER
RESTAURANT = baseline.RESTAURANT_USER
DRIVER = baseline.DRIVER_USER
ORDER_ID = "qa-revision-order"


class WriteResult(dict):
    def __getattr__(self, name):
        return self[name]


class StrictCollection(baseline.FakeCollection):
    def __init__(self, owner, name, docs):
        super().__init__(docs)
        self.owner, self.name = owner, name
        self.before_write = None

    def _matches(self, document, query):
        return matches(document, query or {})

    def _apply_update(self, document, update):
        apply_update(document, update)

    async def _before_write(self, method, query, update):
        # Validate even an empty collection; unsupported operators must not hide.
        matches({}, query)
        self.owner.attempts.append((self.name, method, deepcopy(query), deepcopy(update)))
        hook, self.before_write = self.before_write, None
        if hook:
            await hook()

    async def insert_one(self, document):
        self.owner.attempts.append((self.name, "insert_one", {}, deepcopy(document)))
        result = await super().insert_one(document)
        self.owner.commits.append((self.name, "insert_one"))
        return result

    async def update_one(self, query, update):
        await self._before_write("update_one", query, update)
        result = WriteResult(await super().update_one(query, update))
        if result.matched_count:
            self.owner.commits.append((self.name, "update_one"))
        return result

    async def find_one_and_update(self, query, update, upsert=False, return_document=None, projection=None):
        await self._before_write("find_one_and_update", query, update)
        # All test factories seed the counter; no upsert emulation is needed.
        assert not upsert or any(self._matches(doc, query) for doc in self.docs)
        result = await super().find_one_and_update(query, update, upsert, return_document, projection)
        if result is not None:
            self.owner.commits.append((self.name, "find_one_and_update"))
        return result


@pytest.fixture
def db(monkeypatch):
    assert Path(api.__file__).resolve() == Path(__file__).resolve().parents[1] / "routers" / "orders.py"
    fake = baseline.FakeDb()
    for name, collection in list(vars(fake).items()):
        setattr(fake, name, StrictCollection(fake, name, collection.docs))
    fake.attempts, fake.commits = [], []
    fake.counters.docs.append({"_id": api.ORDER_COUNTER_ID, "seq": 1})
    monkeypatch.setattr(api, "db", fake)
    return fake


def run(coroutine):
    return asyncio.run(coroutine)


def stored(db):
    return next(doc for doc in db.orders.docs if doc["id"] == ORDER_ID)


def state(db):
    return deepcopy({key: value.docs for key, value in vars(db).items()
                     if isinstance(value, StrictCollection)})


def seed(db, version=0, preparation="NEW", dispatch="ASSIGNED"):
    now = datetime.now(timezone.utc)
    order = {
        **baseline.order_payload(), "id": ORDER_ID, "order_number": "S.0001",
        "restaurant_name": "Restaurant Test", "status": dispatch,
        "preparation_status": preparation, "driver_id": "driver-1",
        "driver_name": "Driver Test", "audit_trail": [],
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
    }
    if preparation in {"PREPARING", "READY"}:
        order.update(preparation_time=20, preparation_estimated_seconds=1200,
                     preparation_started_at=(now - timedelta(minutes=25)).isoformat(),
                     preparation_due_at=(now - timedelta(minutes=5)).isoformat())
    if preparation == "READY":
        order.update(preparation_ready_at=now.isoformat(), preparation_actual_seconds=1500,
                     preparation_delay_seconds=300)
    if version is not MISSING:
        order["order_version"] = version
    db.orders.docs.append(order)
    if dispatch in {"ASSIGNED", "ACCEPTED", "PICKED_UP"}:
        db.drivers.docs[0].update(current_order_id=ORDER_ID, driver_status="delivery")
    return order


async def prepare_or_ready(operation, user=RESTAURANT):
    if operation == "prepare":
        return await api.set_preparing(ORDER_ID, PreparationTime(preparation_time=20), user)
    return await api.set_ready(ORDER_ID, user)


async def assert_denied(db, operation, code):
    before, writes = state(db), len(db.attempts)
    with pytest.raises(HTTPException) as error:
        await operation
    assert error.value.status_code == code
    assert len(db.attempts) == writes, f"Rejected operation attempted persistence: {db.attempts[writes:]}"
    assert state(db) == before


@pytest.mark.parametrize("operation", ["prepare", "ready"])
@pytest.mark.parametrize("version", [0, Int64(2**31), MAX_VERSION - 1, MISSING])
@pytest.mark.parametrize("user", [ADMIN, RESTAURANT])
def test_supported_mutation_atomic_revision_and_embedded_audit(db, operation, version, user):
    order = seed(db, version, "NEW" if operation == "prepare" else "PREPARING")
    drivers_before = deepcopy(db.drivers.docs)
    run(prepare_or_ready(operation, user))
    assert order["status"] == "ASSIGNED"
    assert order["preparation_status"] == ("PREPARING" if operation == "prepare" else "READY")
    assert db.drivers.docs == drivers_before
    action = "order.preparing_started" if operation == "prepare" else "order.ready"
    assert len(order["audit_trail"]) == 1
    audit = order["audit_trail"][0]
    assert audit["action"] == action
    assert audit["performed_by"] == user["user_id"]
    writes = [event for event in db.attempts if event[0] == "orders"]
    assert len(writes) == 1
    update = writes[0][3]
    assert update["$push"]["audit_trail"] == audit
    if version is MISSING:
        assert "order_version" not in order
        assert "order_version" not in update.get("$inc", {})
    else:
        assert order["order_version"] == version + 1
        assert update["$inc"]["order_version"] == 1
        assert audit["from_order_version"] == version
        assert audit["to_order_version"] == version + 1


@pytest.mark.parametrize("operation", ["prepare", "ready"])
@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("version", [None, False, True, "0", 0.0, -1, MAX_VERSION + 1, [0]])
def test_malformed_revision_rejected_before_write_including_noop(db, operation, noop, version):
    prep = ("PREPARING" if noop else "NEW") if operation == "prepare" else ("READY" if noop else "PREPARING")
    seed(db, version, prep)
    run(assert_denied(db, prepare_or_ready(operation), 409))


@pytest.mark.parametrize("operation", ["prepare", "ready"])
def test_exhausted_revision_rejects_mutation_without_write(db, operation):
    seed(db, MAX_VERSION, "NEW" if operation == "prepare" else "PREPARING")
    run(assert_denied(db, prepare_or_ready(operation), 409))


@pytest.mark.parametrize("operation", ["prepare", "ready"])
@pytest.mark.parametrize("version", [0, MAX_VERSION, MISSING])
def test_valid_noop_is_read_only_and_does_not_increment(db, operation, version):
    seed(db, version, "PREPARING" if operation == "prepare" else "READY")
    before = state(db)
    assert run(prepare_or_ready(operation))["idempotent"] is True
    assert state(db) == before
    assert db.attempts == []


@pytest.mark.parametrize("operation", ["prepare", "ready"])
@pytest.mark.parametrize("user", [DRIVER, {"role": "customer"}, {"role": "dispatcher"},
                                   {"role": "restaurant", "restaurant_id": "foreign"},
                                   {"role": "restaurant"}, {}])
@pytest.mark.parametrize("version", [0, None])
def test_foreign_roles_are_denied_before_revision_validation_or_side_effect(db, operation, user, version):
    seed(db, version, "NEW" if operation == "prepare" else "PREPARING")
    run(assert_denied(db, prepare_or_ready(operation, user), 403))


@pytest.mark.parametrize("operation", ["prepare", "ready"])
@pytest.mark.parametrize("race", ["revision", "bool", "float", "null", "string", "array", "missing", "terminal", "tenant"])
def test_stale_mutation_cannot_write_over_revision_type_state_or_owner_race(db, operation, race):
    order = seed(db, 0, "NEW" if operation == "prepare" else "PREPARING")
    raced = {}

    async def interleave():
        if race == "missing":
            order.pop("order_version")
        elif race == "terminal":
            order.update(status="CANCELLED", order_version=1)
        elif race == "tenant":
            order.update(restaurant_id="foreign", order_version=1)
        else:
            order["order_version"] = {"revision": 1, "bool": False, "float": 0.0,
                                      "null": None, "string": "0", "array": [0]}[race]
        raced.update(state(db))

    db.orders.before_write = interleave
    with pytest.raises(HTTPException) as error:
        run(prepare_or_ready(operation))
    assert error.value.status_code == (403 if race == "tenant" else 409)
    assert state(db) == raced
    assert db.commits == []
    assert len(db.attempts) == 1 and db.attempts[0][0] == "orders"


@pytest.mark.parametrize("operation", ["prepare", "ready"])
def test_two_same_target_snapshots_commit_revision_and_audit_once(db, operation):
    order = seed(db, 0, "NEW" if operation == "prepare" else "PREPARING")

    async def winner():
        await prepare_or_ready(operation)

    db.orders.before_write = winner
    try:
        response = run(prepare_or_ready(operation))
        assert response.get("idempotent") is True
    except HTTPException as error:
        assert error.status_code == 409
    assert order["order_version"] == 1
    assert len(order["audit_trail"]) == 1
    assert [commit for commit in db.commits if commit[0] == "orders"] == [("orders", "find_one_and_update")]
    assert len(db.audit_logs.docs) <= 1


UNSUPPORTED = ["assign", "assign_noop", "accept", "status_noop", "cancel", "deliver", "problem", "problem_noop"]


def seed_unsupported(db, operation, version):
    dispatch = {"assign": "NEW", "assign_noop": "ASSIGNED", "accept": "ASSIGNED",
                "status_noop": "ACCEPTED", "cancel": "ASSIGNED", "deliver": "PICKED_UP",
                "problem": "DELIVERED", "problem_noop": "DELIVERED"}[operation]
    order = seed(db, version, "READY", dispatch)
    if operation == "assign":
        order.update(driver_id=None, driver_name=None, preparation_status="NEW")
    if operation == "problem_noop":
        order["has_problem_followup"] = True
    return order


async def unsupported(operation):
    if operation.startswith("assign"):
        return await api.assign_order(ORDER_ID, AssignOrder(driver_id="driver-1"), ADMIN)
    if operation.startswith("problem"):
        return await api.create_problem_order(ORDER_ID, ProblemOrderCreate(
            problem_type="missing_product", problem_description="Missing test product",
            item_name="Test item", quantity=1, price=10), RESTAURANT)
    target = {"accept": "ACCEPTED", "status_noop": "ACCEPTED", "cancel": "CANCELLED", "deliver": "DELIVERED"}[operation]
    return await api.update_order_status(ORDER_ID, UpdateOrderStatus(
        status=target, cancellation_reason="Test cancellation" if operation == "cancel" else None), ADMIN)


@pytest.mark.parametrize("operation", UNSUPPORTED)
@pytest.mark.parametrize("version", [0, Int64(0), MAX_VERSION] + INVALID_VERSIONS)
def test_unsupported_versioned_routes_have_zero_write_attempts(db, operation, version):
    seed_unsupported(db, operation, version)
    run(assert_denied(db, unsupported(operation), 409))


@pytest.mark.parametrize("operation", ["assign", "status", "problem"])
@pytest.mark.parametrize("user", [{"role": "customer"}, {"role": "dispatcher"},
                                   {"role": "restaurant", "restaurant_id": "foreign"},
                                   {"role": "driver", "driver_id": "foreign"}])
@pytest.mark.parametrize("version", [0, MISSING])
def test_unsupported_routes_foreign_roles_cannot_write(db, operation, user, version):
    seed_unsupported(db, "accept" if operation == "status" else operation, version)
    if operation == "assign":
        coroutine = api.assign_order(ORDER_ID, AssignOrder(driver_id="driver-1"), user)
    elif operation == "status":
        coroutine = api.update_order_status(ORDER_ID, UpdateOrderStatus(status="ACCEPTED"), user)
    else:
        coroutine = api.create_problem_order(ORDER_ID, ProblemOrderCreate(
            problem_type="missing_product", problem_description="Synthetic missing item"), user)
    run(assert_denied(db, coroutine, 403))


@pytest.mark.parametrize("operation", ["assign", "accept", "cancel", "deliver", "problem"])
def test_supported_legacy_multidocument_routes_keep_existing_bodies_and_no_backfill(db, operation):
    seed_unsupported(db, operation, MISSING)
    result = run(unsupported(operation))
    assert result.get("message")
    assert db.commits
    assert all("order_version" not in order for order in db.orders.docs)
    if operation == "problem":
        assert len(db.orders.docs) == 2
        assert stored(db)["has_problem_followup"] is True


@pytest.mark.parametrize("operation,version", [(op, MISSING) for op in
                        ["prepare", "ready", "assign", "accept", "cancel", "problem"]]
                        + [("prepare", 0), ("ready", 0)])
def test_existing_ui_request_shapes_work_through_http_without_revision_fields(db, operation, version):
    if operation in {"prepare", "ready"}:
        seed(db, version, "NEW" if operation == "prepare" else "PREPARING")
    else:
        seed_unsupported(db, operation, MISSING)
    user = RESTAURANT if operation in {"prepare", "ready", "problem"} else ADMIN
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    app.dependency_overrides[api.get_current_user] = lambda: user
    suffix = {"prepare": "preparing", "ready": "ready", "assign": "assign",
              "accept": "status", "cancel": "status", "problem": "problem"}[operation]
    body = {"prepare": {"preparation_time": 20}, "ready": None,
            "assign": {"driver_id": "driver-1"}, "accept": {"status": "ACCEPTED"},
            "cancel": {"status": "CANCELLED", "cancellation_reason": "Test cancellation"},
            "problem": {"problem_type": "missing_product", "problem_description": "Test missing item"}}[operation]

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
            return await client.request("POST" if operation == "problem" else "PUT",
                                        f"/api/orders/{ORDER_ID}/{suffix}", json=body)

    response = run(request())
    assert response.status_code == 200, response.text
    assert response.json().get("message")
    if version is MISSING:
        assert all("order_version" not in order for order in db.orders.docs)
    else:
        assert stored(db)["order_version"] == version + 1
        assert len(stored(db)["audit_trail"]) == 1
