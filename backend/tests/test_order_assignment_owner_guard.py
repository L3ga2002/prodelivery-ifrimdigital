"""R2 owner guard through real cookie-first authentication and synthetic JWTs.

Parent runner only: owned Mongo27941 fixture, no app environment or secret access.
Real auth function bodies/dependencies stay intact; only module configuration and
DB bindings point to isolated synthetic values. No dependency overrides.
"""

from datetime import datetime, timedelta, timezone
import importlib.util
import inspect
from pathlib import Path
import sys
from types import MappingProxyType, ModuleType, SimpleNamespace

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from models.order import AssignOrder
from test_order_creation_recovery import db, mongo_case, snapshot
from test_order_assignment_recovery import (
    ADMIN, OTHER, ORDER, DRIVER, OP, VERSION, admit_pending, assert_effect,
    command, operation_key, private_free, seed,
)


REAL_BACKEND = Path(r"C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend")
STAGED_BACKEND = Path(__file__).resolve().parents[1]
SYNTHETIC_JWT_KEY = "qa-owner-guard-synthetic-only-not-a-live-key-20261007"
HEADER = "X-Expected-Actor-ID"
LEGACY_ORDER = "qa-owner-guard-legacy-order"
HEADER_SENTINEL = "QA_OWNER_GUARD_PRIVATE_HEADER"
ACTIONS = ("capability", "assign", "lookup", "resume", "legacy")


class ForbiddenBusinessDatabase:
    def __getattr__(self, name):
        raise AssertionError("Owner guard reached business DB before rejecting: " + name)


def load_module(monkeypatch, name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def real_routes(monkeypatch):
    database = ModuleType("database")
    database.db = ForbiddenBusinessDatabase()
    monkeypatch.setitem(sys.modules, "database", database)
    auth = load_module(monkeypatch, "auth", REAL_BACKEND / "auth.py")
    # get_jwt_secret reads auth.os, not the process environment. Do not patch it.
    monkeypatch.setattr(auth, "os", SimpleNamespace(environ=MappingProxyType({
        "JWT_SECRET": SYNTHETIC_JWT_KEY,
    })))
    operations = load_module(monkeypatch, "_pd_owner_guard_operations", STAGED_BACKEND / "routers/order_operations.py")
    legacy = load_module(monkeypatch, "_pd_owner_guard_legacy", STAGED_BACKEND / "routers/orders.py")
    assert operations.get_current_user is auth.get_current_user
    assert legacy.get_current_user is auth.get_current_user
    assert Path(inspect.getsourcefile(auth.get_current_user)).resolve() == (REAL_BACKEND / "auth.py").resolve()
    app = FastAPI()
    app.include_router(operations.router, prefix="/api")
    app.include_router(legacy.router, prefix="/api")

    @app.get("/qa/authenticated-actor")
    async def authenticated_actor(actor=Depends(auth.get_current_user)):
        return {"id": actor["user_id"]}

    assert app.dependency_overrides == {}
    return SimpleNamespace(auth=auth, operations=operations, legacy=legacy, app=app)


async def seed_users(database, *, legacy=False):
    original = await seed(database)
    for actor, label in ((ADMIN, "A"), (OTHER, "B")):
        await database.users.update_one({"id": actor["id"]}, {"$set": {
            "name": "QA Synthetic Owner " + label,
            "email": "qa-owner-guard-" + label.lower() + "@example.invalid",
            "email_verified": True,
        }})
    if legacy:
        document = {k: v for k, v in original.items() if k not in {"_id", "order_version"}}
        document.update(id=LEGACY_ORDER, order_number="QA.OWNER.LEGACY")
        await database.orders.insert_one(document)
    return original


async def tokens(routes, database, *, rotation="initial"):
    result = {}
    for actor in (ADMIN, OTHER):
        user = await database.users.find_one({"id": actor["id"]})
        # Token construction is fixture data, not a substitute auth dependency.
        payload = routes.auth._build_access_payload(user)
        payload.update(jti="qa-owner-guard-" + rotation + "-" + actor["id"],
                       exp=datetime.now(timezone.utc) + timedelta(minutes=5))
        result[actor["id"]] = routes.auth.jwt.encode(
            payload, SYNTHETIC_JWT_KEY, algorithm=routes.auth.JWT_ALGORITHM,
        )
    return result


async def request(routes, database, action, token_set, *, cookie=ADMIN, bearer=ADMIN,
                  expected=ADMIN["id"], business_db=None, bearer_tokens=None):
    routes.auth.db = database
    routes.operations.db = database if business_db is None else business_db
    routes.legacy.db = database if business_db is None else business_db
    headers = {}
    if cookie is not None:
        headers["Cookie"] = routes.auth.ACCESS_TOKEN_COOKIE + "=" + token_set[cookie["id"]]
    if bearer is not None:
        headers["Authorization"] = "Bearer " + (bearer_tokens or token_set)[bearer["id"]]
    if expected is not None:
        headers[HEADER] = expected
    prefix = "/api/orders/operations/assign"
    method, path, payload = {
        "capability": ("GET", prefix + "/capabilities", None),
        "assign": ("POST", prefix + "/" + ORDER, command().model_dump(mode="json")),
        "lookup": ("GET", prefix + "/" + ORDER + "/" + OP, None),
        "resume": ("POST", prefix + "/" + ORDER + "/" + OP + "/resume", None),
        "legacy": ("PUT", "/api/orders/" + LEGACY_ORDER + "/assign", {"driver_id": DRIVER}),
        "actor": ("GET", "/qa/authenticated-actor", None),
    }[action]
    kwargs = {"headers": headers}
    if payload is not None:
        kwargs["json"] = payload
    assert routes.app.dependency_overrides == {}
    async with AsyncClient(transport=ASGITransport(app=routes.app), base_url="http://qa.invalid") as client:
        response = await client.request(method, path, **kwargs)
    if action not in {"legacy", "actor"}:
        assert response.headers.get("cache-control") == "no-store"
    private_free(response.text)
    for token in set(token_set.values()) | set((bearer_tokens or {}).values()):
        assert token not in response.text, "Synthetic token leaked in response"
    assert HEADER_SENTINEL not in response.text, "Invalid owner header was echoed"
    return response


def changed_session(response):
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert isinstance(detail, dict) and detail["code"] == "AUTH_CONTEXT_CHANGED"
    assert set(detail) == {"code", "message"} and isinstance(detail["message"], str)


async def no_b_admission(database):
    assert await database.order_operations.count_documents({"actor_id": OTHER["id"]}) == 0
    assert await database.order_operations.find_one({"_id": operation_key(OTHER["id"], OP)}) is None


@pytest.mark.parametrize("bearer", [ADMIN, None], ids=["cookieB-bearerA", "cookie-only-B"])
@mongo_case
async def test_real_auth_cookie_precedes_bearer_and_cookie_only_resolves_b(db, real_routes, bearer):
    await seed_users(db)
    token_set = await tokens(real_routes, db)
    before = await snapshot(db)
    response = await request(real_routes, db, "actor", token_set, cookie=OTHER, bearer=bearer, expected=None)
    assert response.status_code == 200 and response.json() == {"id": OTHER["id"]}
    assert await snapshot(db) == before


@pytest.mark.parametrize("action", ["capability", "assign", "lookup", "resume"])
@pytest.mark.parametrize("original_state", ["pending", "committed"])
@pytest.mark.parametrize("bearer", [ADMIN, None], ids=["cookieB-bearerA", "cookie-only-staleA"])
@mongo_case
async def test_switched_cookie_refuses_every_recoverable_action_preserves_a_and_restores_recovery(
    db, real_routes, action, original_state, bearer,
):
    original = await seed_users(db)
    token_set = await tokens(real_routes, db)
    before_capability = await snapshot(db)
    capability = await request(real_routes, db, "capability", token_set)
    assert capability.status_code == 200 and capability.json() == {"assign_recovery_enabled": True}
    assert await snapshot(db) == before_capability
    if original_state == "pending":
        await admit_pending(db)
    else:
        first = await request(real_routes, db, "assign", token_set)
        assert first.status_code == 200 and first.json()["state"] == "applied"
    a_before = await db.order_operations.find_one({"_id": operation_key(ADMIN["id"], OP)})
    before = await snapshot(db)
    changed_session(await request(real_routes, db, action, token_set, cookie=OTHER, bearer=bearer))
    assert await snapshot(db) == before, "Cookie switch changed ledger, order, claims, users or audits"
    await no_b_admission(db)
    lookup = await request(real_routes, db, "lookup", token_set, cookie=ADMIN, bearer=bearer)
    expected_state = "pending" if original_state == "pending" else "replayed"
    assert lookup.status_code == (202 if original_state == "pending" else 200)
    assert lookup.json()["state"] == expected_state and lookup.json()["client_operation_id"] == OP
    assert await snapshot(db) == before, "Lookup must be read-only after restoring the cookie"
    recovered = await request(real_routes, db, "resume", token_set, cookie=ADMIN, bearer=bearer)
    assert recovered.status_code == 200 and recovered.json()["state"] == ("applied" if original_state == "pending" else "replayed")
    assert recovered.json()["order_id"] == ORDER and recovered.json()["order_version"] == VERSION + 1
    _, _, a_after = await assert_effect(db, original)
    for field in ("_id", "actor_id", "actor_role", "target_order_id", "client_operation_id",
                  "command", "payload_digest", "admission_digest", "created_at", "request_id"):
        assert a_after[field] == a_before[field]
    assert await db.order_operations.count_documents({}) == 1
    assert await db.audit_logs.count_documents({}) == 1
    await no_b_admission(db)
    final = await snapshot(db)
    replay = await request(real_routes, db, "assign", token_set, cookie=ADMIN, bearer=bearer)
    assert replay.status_code == 200 and replay.json()["state"] == "replayed"
    assert await snapshot(db) == final


@pytest.mark.parametrize("bearer", [ADMIN, None], ids=["cookieB-bearerA", "cookie-only-staleA"])
@mongo_case
async def test_cookie_changes_after_a_capability_cannot_admit_new_b_operation(db, real_routes, bearer):
    original = await seed_users(db)
    token_set = await tokens(real_routes, db)
    capability = await request(real_routes, db, "capability", token_set)
    assert capability.status_code == 200 and capability.json() == {"assign_recovery_enabled": True}
    before = await snapshot(db)
    changed_session(await request(real_routes, db, "assign", token_set, cookie=OTHER, bearer=bearer))
    assert await snapshot(db) == before
    assert await db.order_operations.count_documents({}) == 0
    await no_b_admission(db)
    restored = await request(real_routes, db, "assign", token_set, cookie=ADMIN, bearer=bearer)
    assert restored.status_code == 200 and restored.json()["state"] == "applied"
    await assert_effect(db, original)
    await no_b_admission(db)


@pytest.mark.parametrize("bearer", [ADMIN, None], ids=["cookieB-bearerA", "cookie-only-staleA"])
@mongo_case
async def test_legacy_put_cookie_switch_refused_before_any_b_effect_then_a_can_assign(db, real_routes, bearer):
    await seed_users(db, legacy=True)
    token_set = await tokens(real_routes, db)
    capability = await request(real_routes, db, "capability", token_set)
    assert capability.status_code == 200 and capability.json()["assign_recovery_enabled"] is True
    before = await snapshot(db)
    changed_session(await request(real_routes, db, "legacy", token_set, cookie=OTHER, bearer=bearer))
    assert await snapshot(db) == before and await db.order_operations.count_documents({}) == 0
    await no_b_admission(db)
    restored = await request(real_routes, db, "legacy", token_set, cookie=ADMIN, bearer=bearer)
    assert restored.status_code == 200 and restored.json() == {"message": "Order assigned"}
    order = await db.orders.find_one({"id": LEGACY_ORDER})
    assert order["status"] == "ASSIGNED" and order["driver_id"] == DRIVER
    assert "order_version" not in order
    assert (await db.drivers.find_one({"id": DRIVER}))["current_order_id"] == LEGACY_ORDER
    assert await db.order_operations.count_documents({}) == 0
    audit = await db.audit_logs.find_one({"entity_id": LEGACY_ORDER})
    assert audit["performed_by"] == ADMIN["id"] and audit["action"] == "order.assigned"


@pytest.mark.parametrize("action", ACTIONS)
@mongo_case
async def test_owner_mismatch_rejected_before_business_database_access(db, real_routes, action):
    await seed_users(db, legacy=True)
    token_set = await tokens(real_routes, db)
    before = await snapshot(db)
    changed_session(await request(real_routes, db, action, token_set, cookie=OTHER,
                                  business_db=ForbiddenBusinessDatabase()))
    assert await snapshot(db) == before
    await no_b_admission(db)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("malformed", [
    "", " ", " " + HEADER_SENTINEL, HEADER_SENTINEL + " ",
    HEADER_SENTINEL + "x" * 121, HEADER_SENTINEL + "\x01", HEADER_SENTINEL + "\x7f",
], ids=["empty", "blank", "leading", "trailing", "overflow", "control", "delete-control"])
@mongo_case
async def test_malformed_owner_header_private_422_before_business_database_access(db, real_routes, action, malformed):
    await seed_users(db, legacy=True)
    token_set = await tokens(real_routes, db)
    before = await snapshot(db)
    response = await request(real_routes, db, action, token_set, expected=malformed,
                             business_db=ForbiddenBusinessDatabase())
    assert response.status_code == 422
    detail = response.json()["detail"]
    expected_code = "INVALID_ACTOR_ID" if action == "legacy" else "INVALID_EXPECTED_ACTOR_ID"
    assert isinstance(detail, dict) and detail["code"] == expected_code
    assert set(detail) == {"code", "message"}
    assert await snapshot(db) == before and await db.order_operations.count_documents({}) == 0


@mongo_case
async def test_missing_header_preserves_existing_cookie_first_api_contract(db, real_routes):
    original = await seed_users(db)
    token_set = await tokens(real_routes, db)
    capability = await request(real_routes, db, "capability", token_set, cookie=OTHER, expected=None)
    assert capability.status_code == 200 and capability.json() == {"assign_recovery_enabled": True}
    applied = await request(real_routes, db, "assign", token_set, cookie=OTHER, expected=None)
    assert applied.status_code == 200 and applied.json()["state"] == "applied"
    await assert_effect(db, original, actor=OTHER)
    assert await db.order_operations.count_documents({"actor_id": OTHER["id"]}) == 1
    assert await db.order_operations.count_documents({"actor_id": ADMIN["id"]}) == 0
    before = await snapshot(db)
    for action in ("lookup", "resume"):
        replay = await request(real_routes, db, action, token_set, cookie=OTHER, expected=None)
        assert replay.status_code == 200 and replay.json()["state"] == "replayed"
    assert await snapshot(db) == before


@mongo_case
async def test_missing_header_legacy_http_client_remains_compatible(db, real_routes):
    await seed_users(db, legacy=True)
    token_set = await tokens(real_routes, db)
    result = await request(real_routes, db, "legacy", token_set, cookie=OTHER, expected=None)
    assert result.status_code == 200 and result.json() == {"message": "Order assigned"}
    order = await db.orders.find_one({"id": LEGACY_ORDER})
    assert order["driver_id"] == DRIVER and order["status"] == "ASSIGNED"
    audit = await db.audit_logs.find_one({"entity_id": LEGACY_ORDER})
    assert audit["performed_by"] == OTHER["id"]
    assert await db.order_operations.count_documents({}) == 0


@mongo_case
async def test_rotated_tokens_same_actor_do_not_trigger_session_changed(db, real_routes):
    original = await seed_users(db)
    old_tokens = await tokens(real_routes, db, rotation="old")
    new_tokens = await tokens(real_routes, db, rotation="new")
    assert old_tokens[ADMIN["id"]] != new_tokens[ADMIN["id"]]
    capability = await request(real_routes, db, "capability", new_tokens, bearer_tokens=old_tokens)
    assert capability.status_code == 200
    applied = await request(real_routes, db, "assign", new_tokens, bearer_tokens=old_tokens)
    assert applied.status_code == 200 and applied.json()["state"] == "applied"
    await assert_effect(db, original)
    before = await snapshot(db)
    for action in ("lookup", "resume"):
        replay = await request(real_routes, db, action, old_tokens)
        assert replay.status_code == 200 and replay.json()["state"] == "replayed"
    assert await snapshot(db) == before


@mongo_case
async def test_matching_b_header_uses_real_cookie_b_not_stale_a_bearer(db, real_routes):
    original = await seed_users(db)
    token_set = await tokens(real_routes, db)
    capability = await request(real_routes, db, "capability", token_set, cookie=OTHER, expected=OTHER["id"])
    assert capability.status_code == 200 and capability.json() == {"assign_recovery_enabled": True}
    applied = await request(real_routes, db, "assign", token_set, cookie=OTHER, expected=OTHER["id"])
    assert applied.status_code == 200 and applied.json()["state"] == "applied"
    await assert_effect(db, original, actor=OTHER)
    assert await db.order_operations.count_documents({"actor_id": ADMIN["id"]}) == 0
    before = await snapshot(db)
    for action in ("lookup", "resume"):
        replay = await request(real_routes, db, action, token_set, cookie=OTHER, expected=OTHER["id"])
        assert replay.status_code == 200 and replay.json()["state"] == "replayed"
    assert await snapshot(db) == before


@pytest.mark.parametrize("action", ACTIONS)
@mongo_case
async def test_expected_actor_header_never_grants_authentication(db, real_routes, action):
    await seed_users(db, legacy=True)
    token_set = await tokens(real_routes, db)
    before = await snapshot(db)
    response = await request(real_routes, db, action, token_set, cookie=None, bearer=None,
                             business_db=ForbiddenBusinessDatabase())
    assert response.status_code == 401 and response.json()["detail"] == "Not authenticated"
    assert await snapshot(db) == before and await db.order_operations.count_documents({}) == 0


@mongo_case
async def test_direct_legacy_function_default_none_does_not_create_header_object(db, real_routes):
    await seed_users(db, legacy=True)
    real_routes.legacy.db = db
    result = await real_routes.legacy.assign_order(LEGACY_ORDER, AssignOrder(driver_id=DRIVER), ADMIN)
    assert result == {"message": "Order assigned"}
    assert (await db.orders.find_one({"id": LEGACY_ORDER}))["driver_id"] == DRIVER


def test_expected_actor_header_optional_annotated_default_none_for_http_and_direct_compatibility(real_routes):
    endpoints = (
        real_routes.operations.order_assignment_capabilities,
        real_routes.operations.assign_recoverable_order,
        real_routes.operations.lookup_order_assignment,
        real_routes.operations.resume_order_assignment,
        real_routes.legacy.assign_order,
    )
    for endpoint in endpoints:
        parameter = inspect.signature(endpoint).parameters["expected_actor_id"]
        assert parameter.default is None
        assert getattr(parameter.annotation, "__metadata__", None), "Header must be Annotated, not a default Header object"
    paths = real_routes.app.openapi()["paths"]
    for path, method in (
        ("/api/orders/operations/assign/capabilities", "get"),
        ("/api/orders/operations/assign/{order_id}", "post"),
        ("/api/orders/operations/assign/{order_id}/{client_operation_id}", "get"),
        ("/api/orders/operations/assign/{order_id}/{client_operation_id}/resume", "post"),
        ("/api/orders/{order_id}/assign", "put"),
    ):
        headers = [p for p in paths[path][method]["parameters"] if p["in"] == "header" and p["name"] == HEADER]
        assert len(headers) == 1 and headers[0]["required"] is False
