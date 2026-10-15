"""Actual FastAPI routers/JWT decoder with isolated synthetic DB/import stubs."""
import asyncio
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import jwt
import pytest

from test_order_financial_public_reads import ADMIN, RESTAURANT, DRIVER, SECRET, database, financial_order, legacy_order


KEY = "P1-owner-synthetic-signing-material-only"
PATHS = ["/api/orders", "/api/orders/driver/d1", "/api/orders/restaurant/r1", "/api/orders/o1",
    "/api/orders/read/page", "/api/orders/read/detail/o1", "/api/restaurants/r1/analytics", "/api/drivers/d1/dashboard"]


def load(monkeypatch, name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    db = database()
    database_stub = ModuleType("database"); database_stub.db = db
    monkeypatch.setitem(sys.modules, "database", database_stub)
    # Loading this one actual auth source is intentional. Its DB is synthetic,
    # and its os binding is replaced before any signing/decoding is invoked.
    auth = load(monkeypatch, "auth", root / "auth.py")
    auth.os = SimpleNamespace(environ={"JWT_SECRET": KEY})
    email = ModuleType("utils.email_service")
    email.EmailDeliveryError = RuntimeError
    async def forbidden(*args, **kwargs): raise AssertionError("Outbound side effect forbidden")
    email.send_driver_verification_email = forbidden
    avatar = ModuleType("utils.avatar_storage"); avatar.process_driver_avatar = forbidden
    monkeypatch.setitem(sys.modules, "utils.email_service", email)
    monkeypatch.setitem(sys.modules, "utils.avatar_storage", avatar)
    # Operation routes are unrelated to these GETs. Keep their class and imported
    # callbacks inert while loading the real restaurants router, without loading
    # operational auth/database singletons or enabling any mutation endpoint.
    from fastapi.routing import APIRoute
    operations = ModuleType("routers.order_operations")
    operations.PrivateOperationRoute = APIRoute
    operations._assign_actor_context = forbidden
    operations._http_error = forbidden
    monkeypatch.setitem(sys.modules, "routers.order_operations", operations)
    app = FastAPI()
    for module in ("orders", "restaurants", "drivers"):
        route = load(monkeypatch, "_p1_owner_" + module, root / "routers" / (module + ".py"))
        app.include_router(route.router, prefix="/api")
    return app, db, auth


def token(actor, **changes):
    payload = {"user_id": actor["id"], "role": actor["role"], "restaurant_id": actor.get("restaurant_id"),
        "driver_id": actor.get("driver_id"), "type": "access", "exp": time.time() + 600, **changes}
    return jwt.encode(payload, KEY, algorithm="HS256")


def get(server, path, actor=ADMIN, **kwargs):
    async def request():
        headers = kwargs.pop("headers", {})
        if actor is not None: headers.setdefault("Authorization", "Bearer " + token(actor))
        async with AsyncClient(transport=ASGITransport(app=server[0]), base_url="http://synthetic.invalid") as client:
            return await client.get(path, headers=headers, **kwargs)
    return asyncio.run(request())


def recent(response, index):
    body = response.json()
    if index in (0, 1, 2): return body
    if index == 3: return [body]
    if index == 4: return body["items"]
    if index == 5: return [body["order"]]
    return body["recent_orders"]


@pytest.mark.parametrize("index", range(8))
@pytest.mark.parametrize("actor", [ADMIN, RESTAURANT, DRIVER], ids=["admin", "restaurant", "driver"])
def test_eight_real_routes_role_projection_no_store(server, index, actor):
    before = deepcopy(server[1].orders.values)
    response = get(server, PATHS[index], actor)
    allowed = actor is ADMIN or actor is RESTAURANT and index in (0, 2, 3, 4, 5, 6) or actor is DRIVER and index in (0, 1, 3, 4, 5, 7)
    assert response.status_code == (200 if allowed else 403), response.text
    assert response.headers["cache-control"] == "no-store"
    assert server[1].orders.values == before
    if allowed:
        values = recent(response, index); assert len(values) == 1
        f = values[0]["financial"]
        if actor is ADMIN:
            assert f == before[0]["financial"]
        else:
            assert SECRET not in response.text
            assert "snapshot_digest" not in response.text and "tariff_rule" not in response.text
            assert ("courier_remuneration_bani" in f) == (actor is DRIVER)
        if index == 5 and actor is not ADMIN:
            assert response.json()["read_contract_version"] == 1
    for collection in (server[1].users, server[1].drivers, server[1].orders):
        assert collection.closed == len(collection.calls)


@pytest.mark.parametrize("index", range(8))
@pytest.mark.parametrize("kind", ["missing", "bad", "expired", "no-exp", "cookie-precedence"])
def test_auth_errors_inside_no_store_wrapper(server, index, kind):
    headers, cookies = {}, {}
    if kind == "bad": headers["Authorization"] = "Bearer invalid"
    if kind == "expired": headers["Authorization"] = "Bearer " + token(ADMIN, exp=time.time() - 60)
    if kind == "no-exp":
        headers["Authorization"] = "Bearer " + jwt.encode({"user_id": "admin", "role": "admin", "type": "access"}, KEY, algorithm="HS256")
    if kind == "cookie-precedence":
        headers["Authorization"] = "Bearer " + token(ADMIN); cookies["access_token"] = "invalid-cookie"
    response = get(server, PATHS[index], None, headers=headers, cookies=cookies)
    assert response.status_code == 401, response.text
    assert response.headers["cache-control"] == "no-store" and SECRET not in response.text


@pytest.mark.parametrize("index", range(8))
def test_stale_signed_role_rejected_on_all_routes(server, index):
    server[1].users.values[0]["role"] = "restaurant"
    response = get(server, PATHS[index])
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("index", [0, 1, 3, 4, 5, 7])
def test_signed_driver_mapping_cannot_be_missing(server, index):
    response = get(server, PATHS[index], None, headers={"Authorization": "Bearer " + token(DRIVER, driver_id=None)})
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("index", [0, 2, 3, 4, 5, 6])
def test_corrupt_hidden_snapshot_never_exposed(server, index):
    server[1].orders.values[0]["financial"]["courier_remuneration_bani"] = 999
    response = get(server, PATHS[index], RESTAURANT)
    assert response.status_code == 200, response.text
    value = recent(response, index)[0]
    assert value["financial"] is None and value["read_financial_invalid"] and value["read_actions_unavailable"]
    assert SECRET not in response.text


@pytest.mark.parametrize("index", range(8))
def test_db_failure_has_constant_error_and_no_store(server, index):
    server[1].users.fault = RuntimeError(SECRET)
    response = get(server, PATHS[index])
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    assert SECRET not in response.text


def test_cookie_actor_priority_expected_actor_and_query_validation(server):
    response = get(server, PATHS[0], ADMIN, cookies={"access_token": token(RESTAURANT)})
    assert response.status_code == 200 and recent(response, 0)[0]["financial_read_visibility"] == "restaurant"
    for path, headers in ((PATHS[4] + "?limit=0", {}), (PATHS[4] + "?limit=1&limit=2", {}),
            (PATHS[0], [("X-Expected-Actor-ID", "admin"), ("X-Expected-Actor-ID", "admin"), ("Authorization", "Bearer " + token(ADMIN))])):
        response = get(server, path, None if isinstance(headers, list) else ADMIN, headers=headers)
        assert response.status_code == 422 and response.headers["cache-control"] == "no-store"
    response = get(server, PATHS[0], headers={"X-Expected-Actor-ID": "other"})
    assert response.status_code == 403


def test_legacy_detail_public_envelope_compat_absence_and_bounded_outer(server):
    server[1].orders.values[:] = [legacy_order()]
    detail = get(server, PATHS[5], RESTAURANT)
    assert detail.status_code == 200 and detail.json()["read_visibility"] == "restaurant"
    assert "financial" not in detail.json()["order"]
    compat = get(server, PATHS[2], RESTAURANT)
    assert compat.status_code == 200
    assert "read_actions_unavailable" not in compat.json()[0] and "order_version" not in compat.json()[0]
    response = get(server, PATHS[6], RESTAURANT)
    assert response.status_code == 200 and SECRET not in response.text
    assert "financial" not in response.json()["recent_orders"][0]
    assert "read_financial_invalid" not in response.json()["recent_orders"][0]
    assert all(key in response.json()["recent_orders"][0] for key in ("preparation_actual_minutes", "preparation_delay_minutes", "delivery_minutes"))


def test_late_context_change_after_orders_read_refuses_response(server):
    server[1].orders.on_read = lambda: server[1].users.values[1].update(restaurant_id="r2")
    response = get(server, PATHS[6], RESTAURANT)
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("index", range(8))
@pytest.mark.parametrize("role", ["restaurant", "driver"])
def test_other_tenant_and_other_driver_never_read_target(server, index, role):
    actor = {"id": "other-" + role, "role": role, role + "_id": "r2" if role == "restaurant" else "d2"}
    server[1].users.values.append(deepcopy(actor))
    if role == "driver": server[1].drivers.values.append({"id": "d2", "user_id": actor["id"]})
    response = get(server, PATHS[index], actor)
    assert response.status_code == (200 if index in (0, 4) else 404 if index in (3, 5) else 403), response.text
    assert response.headers["cache-control"] == "no-store" and SECRET not in response.text
    if index in (0, 4): assert recent(response, index) == []


@pytest.mark.parametrize("case", ["duplicate-user", "duplicate-driver", "large-user-role", "large-driver-id", "invalid-user-role"])
def test_authoritative_identity_corruption_is_bounded(server, case):
    db = server[1]
    if case == "duplicate-user": db.users.values.append(deepcopy(db.users.values[2]))
    elif case == "duplicate-driver": db.drivers.values.append(deepcopy(db.drivers.values[0]))
    elif case == "large-user-role": db.users.values[2]["role"] = "x" * 5000
    elif case == "large-driver-id": db.drivers.values[0]["id"] = "x" * 5000
    else: db.users.values[2]["role"] = ["driver"]
    response = get(server, PATHS[7], DRIVER)
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"


def test_response_size_and_serialization_errors_are_private_unavailable(server, monkeypatch):
    from utils.order_reads import OrderReadService
    for value in ([{"value": "x" * (8 * 1024 * 1024)}], [{"value": float("nan")} ]):
        async def oversized(*args, **kwargs): return value
        monkeypatch.setattr(OrderReadService, "compatibility", oversized)
        response = get(server, PATHS[0])
        assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
        assert len(response.content) < 250
