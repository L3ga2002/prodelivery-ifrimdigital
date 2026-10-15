"""Additive preparation routes plus mixed legacy/new writes on synthetic Mongo.

Current actor injection here isolates routing contracts. Separate parent QA owns
real cookie/token authentication; these tests do not claim to replace it.
"""

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest

from models.order import PreparationTime
from models.order_preparation_operations import RECEIPT_FIELDS
from test_order_creation_recovery import db, mongo_case, snapshot
from test_order_preparation_recovery import (
    ADMIN, RESTAURANT, ORDER, OP, VERSION, command, seed, admit,
    OrderPreparationService, settle,
)


@pytest.fixture
def routes(monkeypatch):
    auth = ModuleType("auth")
    async def unauthenticated():
        raise HTTPException(401, "Authentication required")
    auth.get_current_user = unauthenticated
    database = ModuleType("database")
    database.db = None
    monkeypatch.setitem(sys.modules, "auth", auth)
    monkeypatch.setitem(sys.modules, "database", database)
    name = "_qa_preparation_routes"
    path = Path(__file__).resolve().parents[1] / "routers/order_operations.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


async def request(routes, database, method, path, actor=ADMIN, **kwargs):
    routes.db = database
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    if actor is not None:
        app.dependency_overrides[routes.get_current_user] = lambda: actor
        kwargs["headers"] = {"X-Expected-Actor-ID": actor["id"], **kwargs.get("headers", {})}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://qa.invalid") as client:
        response = await client.request(method, "/api/orders/operations" + path, **kwargs)
    assert response.headers["cache-control"] == "no-store"
    return response


@pytest.mark.parametrize("legacy", [False, True])
@mongo_case
async def test_http_preparing_ready_lookup_resume_shape(db, routes, legacy):
    await seed(db, legacy=legacy)
    capability = await request(routes, db, "GET", "/preparation/capabilities", RESTAURANT)
    assert capability.status_code == 200 and capability.json() == {"preparation_recovery_enabled": True}
    cmd = command(version=None if legacy else VERSION)
    applied = await request(routes, db, "PUT", f"/preparing/{ORDER}", RESTAURANT, json=cmd.model_dump(mode="json"))
    assert applied.status_code == 200 and applied.json()["state"] == "applied"
    assert set(applied.json()) == {"client_operation_id", "state", "error_code", "retry_after_seconds", *RECEIPT_FIELDS}
    for method, path in (("GET", f"/preparing/{ORDER}/{OP}"), ("POST", f"/preparing/{ORDER}/{OP}/resume")):
        replay = await request(routes, db, method, path, RESTAURANT)
        assert replay.status_code == 200 and replay.json()["state"] == "replayed"
        assert {**replay.json(), "state": "applied"} == applied.json()
    ready = command("ready", op=OP + "ready", version=None if legacy else VERSION + 1)
    result = await request(routes, db, "PUT", f"/ready/{ORDER}", RESTAURANT, json=ready.model_dump(mode="json"))
    assert result.status_code == 200 and result.json()["preparation_status"] == "READY"
    assert result.json()["order_version"] == (None if legacy else VERSION + 2)


@pytest.mark.parametrize("body", [b"{}", b"null", b" ", b"{\"private\":\"QA private input sentinel\"}"])
@mongo_case
async def test_http_resume_rejects_any_nonempty_body_without_effect_or_echo(db, routes, body):
    await seed(db)
    await admit(db)
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/preparing/{ORDER}/{OP}/resume", content=body)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert "QA private input sentinel" not in response.text
    assert await snapshot(db) == before


@pytest.mark.parametrize("payload", [
    {"client_operation_id": OP, "preparation_time": 5},
    {"client_operation_id": OP, "expected_order_version": True, "preparation_time": 5},
    {"client_operation_id": OP, "expected_order_version": None, "preparation_time": "5"},
    {"client_operation_id": OP, "expected_order_version": None, "preparation_time": 0},
    {"client_operation_id": OP, "expected_order_version": None, "preparation_time": 5, "notes": "QA private input sentinel"},
])
@mongo_case
async def test_http_invalid_command_has_no_echo_admission_or_effect(db, routes, payload):
    await seed(db)
    before = await snapshot(db)
    response = await request(routes, db, "PUT", f"/preparing/{ORDER}", json=payload)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert "QA private input sentinel" not in response.text
    assert await snapshot(db) == before


@mongo_case
async def test_http_pending_and_wrong_action_read_are_read_only(db, routes):
    await seed(db)
    await admit(db)
    before = await snapshot(db)
    response = await request(routes, db, "GET", f"/preparing/{ORDER}/{OP}")
    assert response.status_code == 202 and response.headers["retry-after"] == "2"
    assert response.json()["state"] == "pending"
    assert all(response.json()[name] is None for name in RECEIPT_FIELDS)
    response = await request(routes, db, "GET", f"/ready/{ORDER}/{OP}")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "OPERATION_NOT_FOUND"
    assert await snapshot(db) == before


@mongo_case
async def test_http_auth_actor_header_and_other_restaurant_fail_before_admission(db, routes):
    await seed(db)
    before = await snapshot(db)
    response = await request(routes, db, "PUT", f"/preparing/{ORDER}", actor=None, json=command().model_dump(mode="json"))
    assert response.status_code == 401
    response = await request(routes, db, "PUT", f"/preparing/{ORDER}",
        headers={"X-Expected-Actor-ID": "different-actor"}, json=command().model_dump(mode="json"))
    assert response.status_code == 403 and response.json()["detail"]["code"] == "AUTH_CONTEXT_CHANGED"
    assert await snapshot(db) == before
    foreign = {"id": "qa-preparation-foreign", "role": "restaurant", "restaurant_id": "qa-other-restaurant"}
    await db.users.insert_one({**foreign, "account_disabled": False})
    response = await request(routes, db, "PUT", f"/preparing/{ORDER}", actor=foreign, json=command().model_dump(mode="json"))
    assert response.status_code == 403
    assert await db.order_operations.count_documents({}) == 0


@pytest.mark.parametrize("legacy", [False, True])
@mongo_case
async def test_legacy_put_race_never_attributes_other_minutes_to_new_intent(db, routes, monkeypatch, legacy):
    await seed(db, legacy=legacy)
    # Load unchanged real legacy routes with only this synthetic DB and actor.
    project_backend = Path(sys.modules["models.order"].__file__).resolve().parents[1]
    name = "_qa_preparation_legacy_routes"
    spec = importlib.util.spec_from_file_location(name, project_backend / "routers/orders.py")
    old = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, old)
    spec.loader.exec_module(old)
    old.db = db
    cmd = command(version=None if legacy else VERSION)
    modern, previous = await asyncio.gather(
        OrderPreparationService(db).submit(ORDER, cmd, ADMIN),
        old.set_preparing(ORDER, PreparationTime(preparation_time=15), ADMIN),
        return_exceptions=True,
    )
    assert not isinstance(modern, BaseException)
    modern = await settle(db, modern, cmd)
    order = await db.orders.find_one({"id": ORDER})
    assert order["preparation_time"] in {5, 15}
    assert len([event for event in order["audit_trail"] if event["action"] == "order.preparing_started"]) == 1
    assert await db.audit_logs.count_documents({"entity_id": ORDER, "action": "order.preparing_started"}) == 1
    if modern.result.state in {"applied", "replayed"}:
        assert order["preparation_time"] == modern.result.preparation_time == 5
    else:
        assert modern.result.state == "rejected" and order["preparation_time"] == 15
        assert modern.result.error_code in {"ORDER_VERSION_CONFLICT", "PREPARATION_ALREADY_STARTED"}
    if isinstance(previous, BaseException):
        assert isinstance(previous, HTTPException) and previous.status_code == 409
