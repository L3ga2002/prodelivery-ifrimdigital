"""Independent maintenance-gate QA; only exact owned in-memory DB handles.

No production maintenance grant, promotion exclusion or Mongo migration proof.
"""
import asyncio
from contextvars import copy_context
from copy import deepcopy
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest

from routers import drivers, seed
from utils import order_revision as revision
from test_order_revision_compat import INVALID_VERSIONS, MAX_VERSION, MISSING, matches
from test_order_revision_routes import ADMIN, StrictCollection, run


OPERATIONS = ["delete", "seed", "clear", "demo_orders", "demo_routes"]
COLLECTIONS = ["orders", "drivers", "users", "restaurants", "schedules", "emergency_slots",
               "delivery_zones", "login_attempts", "registration_attempts", "counters", "audit_logs"]


class Collection(StrictCollection):
    async def delete_many(self, query):
        await self._before_write("delete_many", query, {})
        kept = [doc for doc in self.docs if not matches(doc, query)]
        count = len(self.docs) - len(kept)
        self.docs[:] = kept
        self.owner.commits.append((self.name, "delete_many"))
        return SimpleNamespace(deleted_count=count)

    async def delete_one(self, query):
        await self._before_write("delete_one", query, {})
        for index, doc in enumerate(self.docs):
            if matches(doc, query):
                self.docs.pop(index)
                self.owner.commits.append((self.name, "delete_one"))
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def update_many(self, query, update):
        await self._before_write("update_many", query, update)
        count = 0
        for doc in self.docs:
            if matches(doc, query):
                self._apply_update(doc, update)
                count += 1
        self.owner.commits.append((self.name, "update_many"))
        return SimpleNamespace(matched_count=count, modified_count=count)


class OwnedDb:
    def __init__(self):
        self.attempts, self.commits = [], []
        for name in COLLECTIONS:
            setattr(self, name, Collection(self, name, [{"id": "sentinel-" + name}]))
        self.orders.docs = [{"id": "historical", "driver_id": "driver-1", "status": "DELIVERED"}]
        self.drivers.docs = [{"id": "driver-1", "name": "QA driver", "user_id": "user-1"}]
        self.users.docs = [{"id": "admin-qa", "role": "admin"}, {"id": "user-1", "role": "driver"}]
        self.schedules.docs = [{"id": "schedule-1", "driver_id": "driver-1"}]
        self.emergency_slots.docs = [{"id": "slot-1", "claimed_by": ["driver-1"],
                                      "claimed_names": ["QA driver"], "total_spots": 1,
                                      "remaining_spots": 0}]


@pytest.fixture
def owned(monkeypatch):
    backend = Path(__file__).resolve().parents[1]
    for module, filename in [(drivers, "drivers.py"), (seed, "seed.py")]:
        assert Path(module.__file__).resolve() == backend / "routers" / filename
    fake = OwnedDb()
    monkeypatch.setattr(drivers, "db", fake)
    monkeypatch.setattr(seed, "db", fake)
    for key in ["APP_ENV", "ENVIRONMENT", "ENV", "FASTAPI_ENV"]:
        monkeypatch.setenv(key, "development")
    monkeypatch.setenv("ALLOW_SEED", "true")

    def no_credentials():
        raise AssertionError("Maintenance refusal must precede credential access")

    monkeypatch.setattr(seed, "_get_demo_credentials", no_credentials)
    return fake


def snapshot(db):
    return deepcopy({name: getattr(db, name).docs for name in COLLECTIONS})


async def invoke(operation):
    if operation == "delete":
        return await drivers.delete_driver("driver-1", confirm_delete=True, current_user=ADMIN)
    if operation == "seed":
        return await seed.seed_data(ADMIN)
    if operation == "clear":
        return await seed.clear_demo_collections()
    if operation == "demo_orders":
        return await seed.seed_demo_orders([])
    return await seed.seed_demo_map_routes()


async def denied(db, coroutine):
    before = snapshot(db)
    with pytest.raises(HTTPException) as error:
        await coroutine
    assert error.value.status_code == 409
    assert db.attempts == [], f"Refused maintenance attempted writes: {db.attempts}"
    assert snapshot(db) == before
    return error.value


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("flags", [False, True])
def test_all_legacy_normal_runtime_maintenance_is_default_denied(owned, monkeypatch, operation, flags):
    if flags:
        for name in ["ISOLATED_MAINTENANCE", "ALLOW_MAINTENANCE", "MAINTENANCE_MODE",
                     "PRODELIVERY_ISOLATED_MAINTENANCE", "ALLOW_SEED"]:
            monkeypatch.setenv(name, "true")
    error = run(denied(owned, invoke(operation)))
    assert error.detail["code"] == "MAINTENANCE_ISOLATION_REQUIRED"


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("version", [0, MAX_VERSION] + INVALID_VERSIONS)
def test_authorized_fixture_refuses_any_revision_presence_before_all_collection_writes(owned, operation, version):
    owned.orders.docs[0]["order_version"] = version

    async def scenario():
        with revision.isolated_maintenance_for_fixture(owned):
            error = await denied(owned, invoke(operation))
            assert error.detail["code"] == "ORDER_VERSIONED_OPERATION_UNSUPPORTED"

    run(scenario())


@pytest.mark.parametrize("operation", OPERATIONS)
def test_permit_for_different_db_handle_cannot_authorize_route(owned, operation):
    other = OwnedDb()

    async def scenario():
        with revision.isolated_maintenance_for_fixture(other):
            await denied(owned, invoke(operation))
            assert other.attempts == []

    run(scenario())


@pytest.mark.parametrize("operation", OPERATIONS)
def test_child_task_inherited_context_has_no_maintenance_permission(owned, operation):
    async def scenario():
        with revision.isolated_maintenance_for_fixture(owned):
            revision.require_isolated_maintenance(owned)
            await asyncio.create_task(denied(owned, invoke(operation)))
            revision.require_isolated_maintenance(owned)
        await denied(owned, invoke(operation))

    run(scenario())


def test_permit_issued_outside_loop_does_not_authorize_new_async_task(owned):
    with revision.isolated_maintenance_for_fixture(owned):
        revision.require_isolated_maintenance(owned)
        run(denied(owned, invoke("clear")))


def test_copied_context_in_another_thread_cannot_use_permit(owned):
    results = []

    def check():
        try:
            revision.require_isolated_maintenance(owned)
        except HTTPException as error:
            results.append(error.status_code)
        else:
            results.append("unexpected permit")

    with revision.isolated_maintenance_for_fixture(owned):
        context = copy_context()
        thread = threading.Thread(target=lambda: context.run(check))
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert results == [409]
        revision.require_isolated_maintenance(owned)
    assert owned.attempts == []


def test_nested_permit_refused_without_destroying_outer_permission(owned):
    with revision.isolated_maintenance_for_fixture(owned):
        for handle in [owned, OwnedDb()]:
            with pytest.raises(RuntimeError, match="Nested"):
                with revision.isolated_maintenance_for_fixture(handle):
                    pytest.fail("Nested permit unexpectedly granted")
        revision.require_isolated_maintenance(owned)
    with pytest.raises(HTTPException) as error:
        revision.require_isolated_maintenance(owned)
    assert error.value.status_code == 409
    assert owned.attempts == []


def test_exception_restores_default_deny_and_future_permit_works(owned):
    with pytest.raises(ValueError, match="sentinel"):
        with revision.isolated_maintenance_for_fixture(owned):
            revision.require_isolated_maintenance(owned)
            raise ValueError("sentinel")
    with pytest.raises(HTTPException):
        revision.require_isolated_maintenance(owned)
    with revision.isolated_maintenance_for_fixture(owned):
        revision.require_isolated_maintenance(owned)
    assert owned.attempts == []


@pytest.mark.parametrize("operation", ["clear", "delete", "demo_routes"])
def test_owned_legacy_fixture_can_exercise_gate_and_final_absence_predicate(owned, operation):
    async def scenario():
        with revision.isolated_maintenance_for_fixture(owned):
            await invoke(operation)

    run(scenario())
    assert owned.attempts
    order_writes = [event for event in owned.attempts if event[0] == "orders" and event[1] != "insert_one"]
    assert order_writes
    for _, _, query, _ in order_writes:
        assert query.get("order_version") == {"$exists": False}
        assert not matches({"id": "historical", "driver_id": "driver-1", "order_version": None}, query)
    assert all("order_version" not in doc for doc in owned.orders.docs)


@pytest.mark.parametrize("operation", ["delete", "seed"])
@pytest.mark.parametrize("request_flag", ["isolated_maintenance", "allow_maintenance", "maintenance_mode"])
def test_http_query_header_body_flags_do_not_grant_normal_runtime_permission(owned, monkeypatch, operation, request_flag):
    monkeypatch.setenv(request_flag.upper(), "true")
    app = FastAPI()
    app.include_router(drivers.router, prefix="/api")
    app.include_router(seed.router, prefix="/api")
    app.dependency_overrides[drivers.get_current_user] = lambda: ADMIN
    before = snapshot(owned)

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
            path = "/api/drivers/driver-1" if operation == "delete" else "/api/seed"
            return await client.request("DELETE" if operation == "delete" else "POST", path,
                                        params={"confirm_delete": "true", request_flag: "true"},
                                        headers={"X-Isolated-Maintenance": "true", "X-Maintenance-Token": "true"},
                                        json={request_flag: True, "confirm_delete": True})

    response = run(request())
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "MAINTENANCE_ISOLATION_REQUIRED"
    assert owned.attempts == []
    assert snapshot(owned) == before
