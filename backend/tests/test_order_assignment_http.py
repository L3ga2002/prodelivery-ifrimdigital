"""Real assignment router/service, synthetic Mongo and injected current actor.

No server/auth/bootstrap imports and no live credentials. Use parent runner only.
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest

from test_order_creation_recovery import db, mongo_case, snapshot
from test_order_assignment_recovery import (
    ADMIN, OTHER, ORDER, SECOND_ORDER, DRIVER, OLD_DRIVER, OP, VERSION, PII,
    SETTINGS_ID, MAX_ORDER_VERSION, admit_pending, assert_effect,
    command, private_free, seed, business_snapshot, unchanged_business,
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
    name = "_pd_assignment_http_routes"
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


def response_receipt(response, state, status, *, version=None, op=OP):
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {
        "client_operation_id", "state", "order_id", "order_version",
        "error_code", "retry_after_seconds",
    }
    assert payload["client_operation_id"] == op and payload["state"] == state
    if state in {"applied", "replayed"}:
        assert payload["order_id"] == ORDER and payload["order_version"] == version
        assert payload["error_code"] is None and payload["retry_after_seconds"] is None
    else:
        assert payload["order_id"] is None and payload["order_version"] is None
        if state == "pending":
            assert payload["error_code"] is None and 1 <= payload["retry_after_seconds"] <= 60
            assert response.headers["retry-after"] == str(payload["retry_after_seconds"])
        else:
            assert payload["error_code"] and payload["retry_after_seconds"] is None
    return payload


@mongo_case
async def test_http_assign_lookup_resume_real_service_atomic_and_historical(db, routes):
    original = await seed(db)
    response = await request(routes, db, "POST", f"/assign/{ORDER}", json=command().model_dump(mode="json"))
    response_receipt(response, "applied", 200, version=VERSION + 1)
    await assert_effect(db, original)
    await db.orders.update_one({"id": ORDER}, {"$set": {"order_version": 25, "status": "DELIVERED"}})
    before = await snapshot(db)
    for method, path in (("GET", f"/assign/{ORDER}/{OP}"), ("POST", f"/assign/{ORDER}/{OP}/resume")):
        response = await request(routes, db, method, path)
        response_receipt(response, "replayed", 200, version=VERSION + 1)
    assert await snapshot(db) == before


@mongo_case
async def test_http_pending_retry_after_readonly_lookup_bodyless_resume_after_disable(db, routes):
    original = await seed(db)
    await admit_pending(db)
    await db.order_operation_settings.update_one({"_id": SETTINGS_ID}, {"$set": {"enabled": False}})
    before = await snapshot(db)
    response_receipt(await request(routes, db, "GET", f"/assign/{ORDER}/{OP}"), "pending", 202)
    assert await snapshot(db) == before
    response_receipt(await request(routes, db, "POST", f"/assign/{ORDER}/{OP}/resume"), "applied", 200, version=VERSION + 1)
    await assert_effect(db, original)
    assert await db.audit_logs.count_documents({}) == 1


@pytest.mark.parametrize("payload", [
    {}, {"client_operation_id": OP, "driver_id": DRIVER},
    {"client_operation_id": OP, "expected_order_version": VERSION},
    {"client_operation_id": OP, "expected_order_version": None, "driver_id": DRIVER},
    {"client_operation_id": OP, "expected_order_version": True, "driver_id": DRIVER},
    {"client_operation_id": OP, "expected_order_version": 7.0, "driver_id": DRIVER},
    {"client_operation_id": OP, "expected_order_version": MAX_ORDER_VERSION + 1, "driver_id": DRIVER},
    {"client_operation_id": OP, "expected_order_version": VERSION, "driver_id": {"private": PII[3]}},
    {"client_operation_id": OP, "expected_order_version": VERSION, "driver_id": " "},
    {"client_operation_id": OP, "expected_order_version": VERSION, "driver_id": " padded"},
    {"client_operation_id": OP, "expected_order_version": VERSION, "driver_id": None},
    {**command().model_dump(mode="json"), "force": True},
    {**command().model_dump(mode="json"), "customer_name": PII[0]},
])
@mongo_case
async def test_http_invalid_body_422_never_echoes_private_input_or_writes(db, routes, payload):
    await seed(db)
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/assign/{ORDER}", json=payload)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert "input" not in response.json()["detail"]
    assert await snapshot(db) == before


@pytest.mark.parametrize("body", [b"{", b"null", b"[]", b"private-invalid-json"])
@mongo_case
async def test_http_malformed_json_is_sanitized_422_without_effect(db, routes, body):
    await seed(db)
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/assign/{ORDER}", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert "private-invalid-json" not in response.text
    assert await snapshot(db) == before


@pytest.mark.parametrize("body", [b"{}", b"null", b" ", b"private-customer-resume-body"])
@mongo_case
async def test_http_resume_rejects_every_nonempty_body_no_echo_no_effect(db, routes, body):
    await seed(db)
    await admit_pending(db)
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/assign/{ORDER}/{OP}/resume", content=body)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert "private-customer-resume-body" not in response.text
    assert await snapshot(db) == before


@pytest.mark.parametrize("method,path", [
    ("GET", "/assign/capabilities"), ("POST", f"/assign/{ORDER}"),
    ("GET", f"/assign/{ORDER}/{OP}"), ("POST", f"/assign/{ORDER}/{OP}/resume"),
])
@mongo_case
async def test_http_unauthenticated_no_store_no_effect(db, routes, method, path):
    await seed(db)
    before = await snapshot(db)
    kwargs = {"json": command().model_dump(mode="json")} if path == f"/assign/{ORDER}" else {}
    response = await request(routes, db, method, path, actor=None, **kwargs)
    assert response.status_code == 401
    assert await snapshot(db) == before


@pytest.mark.parametrize("change", [{"role": "driver"}, {"role": "restaurant"}, {"account_disabled": True}])
@mongo_case
async def test_http_current_role_and_disable_rechecked_even_for_existing_intent(db, routes, change):
    await seed(db)
    await admit_pending(db)
    await db.users.update_one({"id": ADMIN["id"]}, {"$set": change})
    before = await snapshot(db)
    for method, path, kwargs in (
        ("GET", "/assign/capabilities", {}),
        ("POST", f"/assign/{ORDER}", {"json": command().model_dump(mode="json")}),
        ("GET", f"/assign/{ORDER}/{OP}", {}), ("POST", f"/assign/{ORDER}/{OP}/resume", {}),
    ):
        response = await request(routes, db, method, path, **kwargs)
        expected = "ACCOUNT_DISABLED" if change.get("account_disabled") else "NOT_AUTHORIZED"
        assert response.status_code == 403 and response.json()["detail"]["code"] == expected
    assert await snapshot(db) == before


@mongo_case
async def test_http_assignment_default_disabled_create_edit_capabilities_unaffected(db, routes):
    await seed(db)
    await db.order_operation_settings.delete_one({"_id": SETTINGS_ID})
    await db.order_operation_settings.insert_one({"_id": "order-edit-v1", "enabled": True})
    before = await snapshot(db)
    for path, expected in (
        ("/assign/capabilities", {"assign_recovery_enabled": False}),
        ("/capabilities", {"create_recovery_enabled": True}),
        ("/edit/capabilities", {"edit_recovery_enabled": True}),
    ):
        response = await request(routes, db, "GET", path)
        assert response.status_code == 200 and response.json() == expected
    response = await request(routes, db, "POST", f"/assign/{ORDER}", json=command().model_dump(mode="json"))
    assert response.status_code == 503 and response.json()["detail"]["code"] == "ASSIGNMENT_NOT_ENABLED"
    assert await snapshot(db) == before


@pytest.mark.parametrize("method,path", [
    ("GET", f"/assign/%20{ORDER}/{OP}"), ("GET", f"/assign/{ORDER}/short"),
    ("POST", f"/assign/{ORDER}/short/resume"),
])
@mongo_case
async def test_http_invalid_identifiers_422_private_readonly(db, routes, method, path):
    await seed(db)
    before = await snapshot(db)
    response = await request(routes, db, method, path)
    assert response.status_code == 422
    assert await snapshot(db) == before


@mongo_case
async def test_http_actor_target_scoped_404_and_resume_cannot_admit(db, routes):
    await seed(db)
    await admit_pending(db)
    before = await snapshot(db)
    for method, path, actor in (
        ("GET", f"/assign/{ORDER}/{OP}", OTHER),
        ("POST", f"/assign/{ORDER}/{OP}/resume", OTHER),
        ("GET", f"/assign/{SECOND_ORDER}/{OP}", ADMIN),
        ("POST", f"/assign/{SECOND_ORDER}/{OP}/resume", ADMIN),
        ("POST", f"/assign/{ORDER}/qa_s204_not_admitted_01/resume", ADMIN),
    ):
        response = await request(routes, db, method, path, actor=actor)
        assert response.status_code == 404 and response.json()["detail"]["code"] == "OPERATION_NOT_FOUND"
        assert await snapshot(db) == before


@mongo_case
async def test_http_durable_business_conflict_and_changed_intent_409(db, routes):
    await seed(db)
    business = await business_snapshot(db)
    stale = command(version=VERSION - 1).model_dump(mode="json")
    response = await request(routes, db, "POST", f"/assign/{ORDER}", json=stale)
    response_receipt(response, "rejected", 409)
    assert response.json()["error_code"] == "ORDER_VERSION_CONFLICT"
    before = await snapshot(db)
    response_receipt(await request(routes, db, "POST", f"/assign/{ORDER}/{OP}/resume"), "rejected", 409)
    for target, candidate in ((ORDER, command()), (ORDER, command(version=VERSION - 1, driver=OLD_DRIVER)),
                              (SECOND_ORDER, command(version=VERSION - 1))):
        response = await request(routes, db, "POST", f"/assign/{target}", json=candidate.model_dump(mode="json"))
        assert response.status_code == 409 and response.json()["detail"]["code"] == "INTENT_CONFLICT"
        assert await snapshot(db) == before
    await unchanged_business(db, business, admission_fence=True)


def test_http_openapi_bodyless_resume_required_command_and_adjacent_paths_preserved(routes):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    paths = app.openapi()["paths"]
    prefix = "/api/orders/operations"
    assert "requestBody" not in paths[prefix + "/assign/{order_id}/{client_operation_id}/resume"]["post"]
    assert paths[prefix + "/assign/{order_id}"]["post"]["requestBody"]["required"]
    assert prefix + "/assign/capabilities" in paths
    for path in ("/create", "/create/{client_operation_id}", "/create/{client_operation_id}/resume",
                 "/edit/{order_id}", "/edit/{order_id}/{client_operation_id}",
                 "/edit/{order_id}/{client_operation_id}/resume"):
        assert prefix + path in paths
