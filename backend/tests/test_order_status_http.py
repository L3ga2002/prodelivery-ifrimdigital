"""Independent status router/service ASGI tests on synthetic owned Mongo.

Current actor is injected here. Parent test_order_status_owner_guard.py owns
real cookie-first auth and header-before-business-DB coverage; no duplication.
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest

from test_order_creation_recovery import db, mongo_case, snapshot
from test_order_status_recovery import (
    ADMIN, OTHER, ORDER, SECOND_ORDER, DRIVER, OP, VERSION, PII,
    RESTAURANT, FOREIGN_RESTAURANT, DRIVER_ACTOR, FOREIGN_DRIVER,
    SETTINGS_ID, MAX_ORDER_VERSION, OrderStatusService, DatabaseProxy, Faults,
    admit_pending, assert_effect, business_snapshot, command, private_free,
    seed, unchanged_business,
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
    name = "_pd_status_independent_http_routes"
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
    assert response.headers.get("cache-control") == "no-store"
    private_free(response.text)
    return response


def response_receipt(response, state, status=200, *, version=None, op=OP, code=None):
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
        assert "retry-after" not in response.headers
    else:
        assert payload["order_id"] is None and payload["order_version"] is None
        if state == "pending":
            assert payload["error_code"] is None and 1 <= payload["retry_after_seconds"] <= 60
            assert response.headers["retry-after"] == str(payload["retry_after_seconds"])
        else:
            assert payload["error_code"] and payload["retry_after_seconds"] is None
            if code is not None:
                assert payload["error_code"] == code
    return payload


@pytest.mark.parametrize("role", ["admin", "driver"])
@mongo_case
async def test_http_custody_apply_lookup_resume_historical_original_receipt(db, routes, role):
    original = await seed(db)
    actor = ADMIN if role == "admin" else DRIVER_ACTOR
    driver = await db.drivers.find_one({"id": DRIVER})
    response_receipt(await request(routes, db, "POST", f"/status/{ORDER}", actor,
                                   json=command().model_dump(mode="json")), "applied", version=VERSION + 1)
    await assert_effect(db, original, command(), actor, driver)
    # Advance through valid operations, then recover the earlier acceptance receipt.
    for i, target in enumerate(("PICKED_UP", "DELIVERED"), 1):
        cmd = command(op=OP + str(i), version=VERSION + i, target=target)
        response_receipt(await request(routes, db, "POST", f"/status/{ORDER}", actor,
                                       json=cmd.model_dump(mode="json")), "applied", op=cmd.client_operation_id, version=VERSION + i + 1)
    before = await snapshot(db)
    for method, path in (("GET", f"/status/{ORDER}/{OP}"), ("POST", f"/status/{ORDER}/{OP}/resume")):
        response_receipt(await request(routes, db, method, path, actor), "replayed", version=VERSION + 1)
    response_receipt(await request(routes, db, "POST", f"/status/{ORDER}", actor,
                                   json=command().model_dump(mode="json")), "replayed", version=VERSION + 1)
    assert await snapshot(db) == before
    assert (await db.drivers.find_one({"id": DRIVER}))["total_deliveries"] == 9


@pytest.mark.parametrize("role", ["admin", "restaurant", "driver"])
@mongo_case
async def test_http_eligible_owned_cancellation_reason_trimmed_and_audited(db, routes, role):
    original = await seed(db)
    actor = {"admin": ADMIN, "restaurant": RESTAURANT, "driver": DRIVER_ACTOR}[role]
    driver = await db.drivers.find_one({"id": DRIVER})
    cmd = command(target="CANCELLED", reason="  QA owned reason  ")
    body = cmd.model_dump(mode="json")
    body["cancellation_reason"] = "  QA owned reason  "
    response_receipt(await request(routes, db, "POST", f"/status/{ORDER}", actor, json=body), "applied", version=VERSION + 1)
    await assert_effect(db, original, cmd, actor, driver)


@mongo_case
async def test_http_pending_retry_after_readonly_lookup_bodyless_resume_after_disable(db, routes):
    original = await seed(db, "PICKED_UP")
    cmd = command(target="DELIVERED")
    driver = await db.drivers.find_one({"id": DRIVER})
    await admit_pending(db, cmd)
    await db.order_operation_settings.update_one({"_id": SETTINGS_ID}, {"$set": {"enabled": False}})
    before = await snapshot(db)
    response_receipt(await request(routes, db, "GET", f"/status/{ORDER}/{OP}"), "pending", 202)
    assert await snapshot(db) == before
    response_receipt(await request(routes, db, "POST", f"/status/{ORDER}/{OP}/resume"), "applied", version=VERSION + 1)
    await assert_effect(db, original, cmd, ADMIN, driver)
    before = await snapshot(db)
    response_receipt(await request(routes, db, "POST", f"/status/{ORDER}/{OP}/resume"), "replayed", version=VERSION + 1)
    assert await snapshot(db) == before


@mongo_case
async def test_http_lost_ack_is_recovered_not_second_delivery_credit(db, routes):
    original = await seed(db, "PICKED_UP")
    driver = await db.drivers.find_one({"id": DRIVER})
    cmd = command(target="DELIVERED")
    faults = Faults()
    faults.ack_losses = 3
    out = await OrderStatusService(DatabaseProxy(db, faults)).status(ORDER, cmd, ADMIN)
    assert out.result.state in {"applied", "pending"} and faults.injections == 3
    response_receipt(await request(routes, db, "GET", f"/status/{ORDER}/{OP}"), "replayed", version=VERSION + 1)
    response_receipt(await request(routes, db, "POST", f"/status/{ORDER}/{OP}/resume"), "replayed", version=VERSION + 1)
    await assert_effect(db, original, cmd, ADMIN, driver)


@pytest.mark.parametrize("payload", [
    {}, {"client_operation_id": OP, "status": "ACCEPTED"},
    {"client_operation_id": OP, "expected_order_version": VERSION},
    {"client_operation_id": OP, "expected_order_version": None, "status": "ACCEPTED"},
    {"client_operation_id": OP, "expected_order_version": True, "status": "ACCEPTED"},
    {"client_operation_id": OP, "expected_order_version": 7.0, "status": "ACCEPTED"},
    {"client_operation_id": OP, "expected_order_version": MAX_ORDER_VERSION + 1, "status": "ACCEPTED"},
    {"client_operation_id": "short", "expected_order_version": VERSION, "status": "ACCEPTED"},
    {"client_operation_id": OP, "expected_order_version": VERSION, "status": {"private": PII[3]}},
    {"client_operation_id": OP, "expected_order_version": VERSION, "status": "READY"},
    {"client_operation_id": OP, "expected_order_version": VERSION, "status": "CANCELLED"},
    {"client_operation_id": OP, "expected_order_version": VERSION, "status": "CANCELLED", "cancellation_reason": "  "},
    {**command().model_dump(mode="json"), "cancellation_reason": PII[3]},
    {**command().model_dump(mode="json"), "force": True},
    {**command().model_dump(mode="json"), "driver_id": DRIVER},
    {**command().model_dump(mode="json"), "total_amount": 0},
    {**command().model_dump(mode="json"), "customer_name": PII[0]},
])
@mongo_case
async def test_http_invalid_command_422_sanitized_without_any_admission_or_effect(db, routes, payload):
    await seed(db)
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/status/{ORDER}", json=payload)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert "input" not in response.json()["detail"]
    assert await snapshot(db) == before


@pytest.mark.parametrize("body", [b"{", b"null", b"[]", b"private-invalid-json"])
@mongo_case
async def test_http_malformed_json_is_sanitized_no_admission(db, routes, body):
    await seed(db)
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/status/{ORDER}", content=body,
                             headers={"content-type": "application/json"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert "private-invalid-json" not in response.text
    assert await snapshot(db) == before


@pytest.mark.parametrize("body", [b"{}", b"null", b" ", b"private-customer-resume-body"])
@mongo_case
async def test_http_resume_rejects_every_nonempty_body_never_echoes_or_executes(db, routes, body):
    await seed(db)
    await admit_pending(db)
    before = await snapshot(db)
    response = await request(routes, db, "POST", f"/status/{ORDER}/{OP}/resume", content=body)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert "private-customer-resume-body" not in response.text
    assert await snapshot(db) == before


@pytest.mark.parametrize("method,path", [
    ("GET", "/status/capabilities"), ("POST", f"/status/{ORDER}"),
    ("GET", f"/status/{ORDER}/{OP}"), ("POST", f"/status/{ORDER}/{OP}/resume"),
])
@mongo_case
async def test_http_unauthenticated_no_store_no_admission(db, routes, method, path):
    await seed(db)
    before = await snapshot(db)
    kwargs = {"json": command().model_dump(mode="json")} if path == f"/status/{ORDER}" else {}
    response = await request(routes, db, method, path, actor=None, **kwargs)
    assert response.status_code == 401
    assert await snapshot(db) == before


@pytest.mark.parametrize("actor,target", [
    (RESTAURANT, "ACCEPTED"), (RESTAURANT, "PICKED_UP"), (RESTAURANT, "DELIVERED"),
    (FOREIGN_RESTAURANT, "CANCELLED"), (FOREIGN_DRIVER, "ACCEPTED"), (FOREIGN_DRIVER, "CANCELLED"),
])
@mongo_case
async def test_http_wrong_owner_or_role_403_not_a_durable_business_rejection(db, routes, actor, target):
    await seed(db)
    before = await snapshot(db)
    cmd = command(target=target, reason="QA cancellation" if target == "CANCELLED" else None)
    response = await request(routes, db, "POST", f"/status/{ORDER}", actor, json=cmd.model_dump(mode="json"))
    assert response.status_code == 403 and response.json()["detail"]["code"] == "NOT_AUTHORIZED"
    assert await snapshot(db) == before


@pytest.mark.parametrize("role", ["admin", "restaurant", "driver"])
@mongo_case
async def test_http_actor_role_tenant_or_link_change_blocks_existing_recovery(db, routes, role):
    await seed(db)
    actor = {"admin": ADMIN, "restaurant": RESTAURANT, "driver": DRIVER_ACTOR}[role]
    cmd = command(target="CANCELLED", reason="QA reason") if role == "restaurant" else command()
    await admit_pending(db, cmd, actor)
    change = {"role": "restaurant"} if role == "admin" else {"restaurant_id": "qa-foreign"} if role == "restaurant" else {"driver_id": "qa-changed-driver"}
    await db.users.update_one({"id": actor["id"]}, {"$set": change})
    before = await snapshot(db)
    for method, path, kwargs in (
        ("POST", f"/status/{ORDER}", {"json": cmd.model_dump(mode="json")}),
        ("GET", f"/status/{ORDER}/{OP}", {}), ("POST", f"/status/{ORDER}/{OP}/resume", {}),
    ):
        response = await request(routes, db, method, path, actor, **kwargs)
        assert response.status_code == 403
        assert await snapshot(db) == before


@pytest.mark.parametrize("role", ["admin", "restaurant", "driver"])
@mongo_case
async def test_http_capabilities_readonly_for_each_enabled_actor_and_separate_marker(db, routes, role):
    await seed(db)
    actor = {"admin": ADMIN, "restaurant": RESTAURANT, "driver": DRIVER_ACTOR}[role]
    before = await snapshot(db)
    response = await request(routes, db, "GET", "/status/capabilities", actor)
    assert response.status_code == 200 and response.json() == {"status_recovery_enabled": True}
    assert await snapshot(db) == before
    await db.order_operation_settings.delete_one({"_id": SETTINGS_ID})
    before = await snapshot(db)
    response = await request(routes, db, "GET", "/status/capabilities", actor)
    assert response.status_code == 200 and response.json() == {"status_recovery_enabled": False}
    response = await request(routes, db, "POST", f"/status/{ORDER}", actor,
                             json=(command(target="CANCELLED", reason="QA reason") if role == "restaurant" else command()).model_dump(mode="json"))
    assert response.status_code == 503 and response.json()["detail"]["code"] == "STATUS_NOT_ENABLED"
    assert await snapshot(db) == before


@pytest.mark.parametrize("method,path", [
    ("GET", f"/status/%20{ORDER}/{OP}"), ("GET", f"/status/{ORDER}/short"),
    ("POST", f"/status/{ORDER}/short/resume"),
])
@mongo_case
async def test_http_invalid_identifiers_422_readonly(db, routes, method, path):
    await seed(db)
    before = await snapshot(db)
    response = await request(routes, db, method, path)
    assert response.status_code == 422
    assert await snapshot(db) == before


@mongo_case
async def test_http_actor_target_scoped_404_and_unknown_resume_never_admits(db, routes):
    await seed(db)
    await admit_pending(db)
    before = await snapshot(db)
    for method, path, actor in (
        ("GET", f"/status/{ORDER}/{OP}", OTHER), ("POST", f"/status/{ORDER}/{OP}/resume", OTHER),
        ("GET", f"/status/{SECOND_ORDER}/{OP}", ADMIN), ("POST", f"/status/{SECOND_ORDER}/{OP}/resume", ADMIN),
        ("POST", f"/status/{ORDER}/{OP}absent/resume", ADMIN),
    ):
        response = await request(routes, db, method, path, actor)
        assert response.status_code == 404 and response.json()["detail"]["code"] == "OPERATION_NOT_FOUND"
        assert await snapshot(db) == before


@pytest.mark.parametrize("failure", ["stale", "not_ready", "custody", "not_found"])
@mongo_case
async def test_http_durable_business_refusal_exact_status_code_and_replay(db, routes, failure):
    state = "PICKED_UP" if failure == "custody" else "ACCEPTED" if failure == "not_ready" else "ASSIGNED"
    await seed(db, state, preparation="PREPARING" if failure == "not_ready" else "READY")
    cmd = command(version=VERSION - 1) if failure == "stale" else command(target="PICKED_UP") if failure == "not_ready" else command(target="CANCELLED", reason="QA late reason") if failure == "custody" else command()
    code = {"stale": "ORDER_VERSION_CONFLICT", "not_ready": "ORDER_NOT_READY",
            "custody": "CUSTODY_RESOLUTION_REQUIRED", "not_found": "ORDER_NOT_FOUND"}[failure]
    if failure == "not_found":
        await db.orders.delete_one({"id": ORDER})
    business = await business_snapshot(db)
    http = 404 if failure == "not_found" else 409
    response_receipt(await request(routes, db, "POST", f"/status/{ORDER}", json=cmd.model_dump(mode="json")),
                     "rejected", http, code=code)
    await unchanged_business(db, business, fenced_actor=ADMIN)
    before = await snapshot(db)
    for method, path in (("GET", f"/status/{ORDER}/{OP}"), ("POST", f"/status/{ORDER}/{OP}/resume")):
        response_receipt(await request(routes, db, method, path), "rejected", http, code=code)
        assert await snapshot(db) == before


@mongo_case
async def test_http_changed_intent_conflict_never_executes_or_overwrites_admission(db, routes):
    await seed(db)
    await admit_pending(db)
    before = await snapshot(db)
    for target, cmd in ((ORDER, command(target="PICKED_UP")), (ORDER, command(version=VERSION + 1)),
                        (ORDER, command(target="CANCELLED", reason="QA changed reason")), (SECOND_ORDER, command())):
        response = await request(routes, db, "POST", f"/status/{target}", json=cmd.model_dump(mode="json"))
        assert response.status_code == 409 and response.json()["detail"]["code"] == "INTENT_CONFLICT"
        assert await snapshot(db) == before


def test_http_openapi_required_status_body_bodyless_resume_and_adjacent_contracts_preserved(routes):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    paths = app.openapi()["paths"]
    prefix = "/api/orders/operations"
    assert "requestBody" not in paths[prefix + "/status/{order_id}/{client_operation_id}/resume"]["post"]
    assert paths[prefix + "/status/{order_id}"]["post"]["requestBody"]["required"]
    assert "get" in paths[prefix + "/status/capabilities"]
    assert "get" in paths[prefix + "/status/{order_id}/{client_operation_id}"]
    for path in ("/create", "/create/{client_operation_id}", "/create/{client_operation_id}/resume",
                 "/edit/{order_id}", "/edit/{order_id}/{client_operation_id}",
                 "/edit/{order_id}/{client_operation_id}/resume", "/assign/{order_id}",
                 "/assign/{order_id}/{client_operation_id}", "/assign/{order_id}/{client_operation_id}/resume"):
        assert prefix + path in paths
