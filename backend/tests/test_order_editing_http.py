"""Actual router/service HTTP checks on the verified owned Mongo fixture."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest

from test_order_creation_recovery import db, mongo_case, snapshot
from test_order_editing_recovery import (
    ADMIN, ORDER, OP, VERSION, PII, OrderEditingService, admit_pending,
    command, private_free, seed, unchanged_business,
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
    name = "_pd_edit_http_routes"
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://qa.invalid") as client:
        response = await client.request(method, "/api/orders/operations" + path, **kwargs)
    assert response.headers["cache-control"] == "no-store"
    private_free(response.text)
    return response


@mongo_case
async def test_http_edit_lookup_resume_atomic_and_historical_receipt(db, routes):
    await seed(db)
    response = await request(routes, db, "POST", f"/edit/{ORDER}", json=command().model_dump(mode="json"))
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["state"] == "applied" and receipt["order_id"] == ORDER
    assert receipt["order_version"] == VERSION + 1 and receipt["client_operation_id"] == OP
    await db.orders.update_one({"id": ORDER}, {"$set": {"order_version": 20, "status": "DELIVERED"}})
    before = await snapshot(db)
    for method, path in (("GET", f"/edit/{ORDER}/{OP}"), ("POST", f"/edit/{ORDER}/{OP}/resume")):
        response = await request(routes, db, method, path)
        assert response.status_code == 200 and response.json()["state"] == "replayed"
        assert response.json()["order_version"] == VERSION + 1
    assert await snapshot(db) == before


@mongo_case
async def test_http_pending_lookup_then_bodyless_resume_after_disable(db, routes):
    await seed(db)
    await admit_pending(db)
    await db.order_operation_settings.update_one({"_id": "order-edit-v1"}, {"$set": {"enabled": False}})
    before = await snapshot(db)
    response = await request(routes, db, "GET", f"/edit/{ORDER}/{OP}")
    assert response.status_code == 202 and response.json()["state"] == "pending"
    assert response.headers["retry-after"] == str(response.json()["retry_after_seconds"])
    assert await snapshot(db) == before
    response = await request(routes, db, "POST", f"/edit/{ORDER}/{OP}/resume")
    assert response.status_code == 200 and response.json()["state"] == "applied"
    assert await db.audit_logs.count_documents({}) == 1


@pytest.mark.parametrize("payload", [
    {}, {"client_operation_id": OP, "changes": {"customer_name": PII[4]}},
    {"client_operation_id": OP, "expected_order_version": True, "changes": {"customer_name": PII[4]}},
    {"client_operation_id": OP, "expected_order_version": VERSION, "changes": {"restaurant_id": "other"}},
    {"client_operation_id": OP, "expected_order_version": VERSION, "changes": {"customer_name": None}},
    {"client_operation_id": OP, "expected_order_version": VERSION, "changes": {"customer_latitude": 12.0}},
])
@mongo_case
async def test_http_invalid_body_never_echoes_or_writes(db, routes, payload):
    await seed(db)
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/edit/{ORDER}", json=payload)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert await snapshot(db) == before


@pytest.mark.parametrize("body", [b"{}", b"null", b" ", b"secret-customer-body"])
@mongo_case
async def test_http_resume_rejects_any_nonempty_body_without_effect(db, routes, body):
    await seed(db)
    await admit_pending(db)
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/edit/{ORDER}/{OP}/resume", content=body)
    assert response.status_code == 422
    assert "secret-customer-body" not in response.text
    assert await snapshot(db) == before


@pytest.mark.parametrize("method,path", [
    ("GET", "/edit/capabilities"), ("POST", f"/edit/{ORDER}"),
    ("GET", f"/edit/{ORDER}/{OP}"), ("POST", f"/edit/{ORDER}/{OP}/resume"),
])
@mongo_case
async def test_http_authentication_required_no_store_no_effect(db, routes, method, path):
    await seed(db)
    before = await snapshot(db)
    kwargs = {"json": command().model_dump(mode="json")} if path == f"/edit/{ORDER}" else {}
    response = await request(routes, db, method, path, actor=None, **kwargs)
    assert response.status_code == 401
    assert await snapshot(db) == before


@pytest.mark.parametrize("role", ["driver", "restaurant"])
@mongo_case
async def test_http_current_role_rechecked_before_new_or_existing_actions(db, routes, role):
    await seed(db)
    await admit_pending(db)
    await db.users.update_one({"id": ADMIN["id"]}, {"$set": {"role": role}})
    before = await snapshot(db)
    for method, path, kwargs in (
        ("GET", "/edit/capabilities", {}),
        ("POST", f"/edit/{ORDER}", {"json": command().model_dump(mode="json")}),
        ("GET", f"/edit/{ORDER}/{OP}", {}),
        ("POST", f"/edit/{ORDER}/{OP}/resume", {}),
    ):
        response = await request(routes, db, method, path, **kwargs)
        assert response.status_code == 403 and response.json()["detail"]["code"] == "NOT_AUTHORIZED"
    assert await snapshot(db) == before


@mongo_case
async def test_http_default_disabled_marker_does_not_change_creation_capability(db, routes):
    original = await seed(db)
    await db.order_operation_settings.delete_one({"_id": "order-edit-v1"})
    before = await snapshot(db)
    response = await request(routes, db, "GET", "/edit/capabilities")
    assert response.status_code == 200 and response.json() == {"edit_recovery_enabled": False}
    response = await request(routes, db, "GET", "/capabilities")
    assert response.status_code == 200 and response.json() == {"create_recovery_enabled": True}
    response = await request(routes, db, "POST", f"/edit/{ORDER}", json=command().model_dump(mode="json"))
    assert response.status_code == 503 and response.json()["detail"]["code"] == "EDITING_NOT_ENABLED"
    assert await snapshot(db) == before
    await unchanged_business(db, original)


@pytest.mark.parametrize("path", [f"/edit/%20{ORDER}/{OP}", f"/edit/{ORDER}/short", f"/edit/{ORDER}/short/resume"])
@mongo_case
async def test_http_invalid_path_identifiers_are_private_and_read_only(db, routes, path):
    await seed(db)
    before = await snapshot(db)
    method = "POST" if path.endswith("/resume") else "GET"
    response = await request(routes, db, method, path)
    assert response.status_code == 422
    assert await snapshot(db) == before


@mongo_case
async def test_http_business_conflict_durable_and_new_payload_cannot_reuse_id(db, routes):
    original = await seed(db)
    response = await request(routes, db, "POST", f"/edit/{ORDER}", json=command(version=VERSION - 1).model_dump(mode="json"))
    assert response.status_code == 409 and response.json()["error_code"] == "ORDER_VERSION_CONFLICT"
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/edit/{ORDER}/{OP}/resume")
    assert response.status_code == 409 and response.json()["error_code"] == "ORDER_VERSION_CONFLICT"
    response = await request(routes, db, "POST", f"/edit/{ORDER}", json=command().model_dump(mode="json"))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "INTENT_CONFLICT"
    assert await snapshot(db) == before
    await unchanged_business(db, original)


def test_edit_openapi_resume_has_no_body_and_legacy_creation_paths_remain(routes):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    paths = app.openapi()["paths"]
    prefix = "/api/orders/operations"
    assert "requestBody" not in paths[prefix + "/edit/{order_id}/{client_operation_id}/resume"]["post"]
    assert paths[prefix + "/edit/{order_id}"]["post"]["requestBody"]["required"]
    assert prefix + "/create" in paths and prefix + "/create/{client_operation_id}/resume" in paths
