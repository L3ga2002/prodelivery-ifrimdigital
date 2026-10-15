"""Actual FastAPI router, isolated auth/database stubs installed before import."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest
import jwt

from test_order_finance_preview import ADMIN, RESTAURANT, DRIVER, KEY, PII, Database, create_request, remake_request


@pytest.fixture
def application(monkeypatch):
    database = ModuleType("database"); database.db = Database()
    monkeypatch.setitem(sys.modules, "database", database)
    backend = Path(__file__).resolve().parents[1]
    # Real signature verification, with database stub installed BEFORE auth is
    # loaded and a module-local synthetic environ before any secret lookup.
    auth_spec = importlib.util.spec_from_file_location("auth", backend / "auth.py")
    auth = importlib.util.module_from_spec(auth_spec)
    monkeypatch.setitem(sys.modules, "auth", auth)
    auth_spec.loader.exec_module(auth)
    auth.os = SimpleNamespace(environ={"JWT_SECRET": KEY.decode()})
    path = backend / "routers/order_operations.py"
    spec = importlib.util.spec_from_file_location("_isolated_f1_router", path)
    routes = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, routes)
    spec.loader.exec_module(routes)
    app = FastAPI(); app.include_router(routes.router, prefix="/api")
    return app, database.db, auth, routes


def token(actor, **changes):
    return jwt.encode({"user_id": actor["id"], "role": actor["role"], "restaurant_id": actor.get("restaurant_id"),
        "type": "access", "exp": int(time.time()) + 300, **changes}, KEY, algorithm="HS256")


def request(application, path, method="GET", actor=ADMIN, header=True, body=None, content=None, extra_headers=None):
    app, _, auth, _ = application
    async def current():
        if actor is None:
            raise HTTPException(401, detail="Private authentication detail sentinel")
        return actor.copy()
    app.dependency_overrides[auth.get_current_user] = current
    headers = {"X-Expected-Actor-ID": actor["id"] if actor else "missing"} if header else {}
    if actor is not None:
        headers["Authorization"] = "Bearer " + token(actor)
    headers.update(extra_headers or {})
    async def perform():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
            response = await client.request(method, "/api/orders/operations/finance" + path,
                headers=headers, json=body, content=content)
            assert response.headers.get("cache-control") == "no-store"
            assert all(value not in response.text for value in PII)
            assert "Private authentication detail sentinel" not in response.text
            return response
    return asyncio.run(perform())


def test_all_four_routes_success_and_no_writes(application):
    _, db, _, _ = application
    before = json.dumps(db.rows, sort_keys=True)
    assert request(application, "/capabilities?restaurant_id=r1").json()["create_quote_enabled"] is True
    assert request(application, "/tariffs?restaurant_id=r1", actor=RESTAURANT).status_code == 200
    quote = request(application, "/quote/create", "POST", body=create_request().model_dump(mode="json"))
    assert quote.status_code == 200 and quote.json()["restaurant_transport_bani"] == 1600
    remake = request(application, "/quote/remake/parent", "POST", actor=RESTAURANT, body=remake_request().model_dump(mode="json"))
    assert remake.status_code == 200 and "courier_remuneration_bani" not in remake.json()
    assert before == json.dumps(db.rows, sort_keys=True)


@pytest.mark.parametrize("path,method", [("/capabilities?restaurant_id=r1", "GET"), ("/tariffs?restaurant_id=r1", "GET"),
    ("/quote/create", "POST"), ("/quote/remake/parent", "POST")])
@pytest.mark.parametrize("case,status,code", [("auth", 401, "AUTH_REQUIRED"), ("missing", 409, "EXPECTED_ACTOR_REQUIRED"),
    ("mismatch", 403, "AUTH_CONTEXT_CHANGED"), ("driver", 403, "NOT_AUTHORIZED")])
def test_auth_and_expected_actor_errors_private(application, path, method, case, status, code):
    body = (remake_request() if "remake" in path else create_request()).model_dump(mode="json") if method == "POST" else None
    result = request(application, path, method, actor=None if case == "auth" else DRIVER if case == "driver" else ADMIN,
        header=case != "missing", body=body, extra_headers={"X-Expected-Actor-ID": "other"} if case == "mismatch" else {})
    assert result.status_code == status and result.json()["detail"]["code"] == code


@pytest.mark.parametrize("path", ["/tariffs", "/tariffs?restaurant_id=r1&restaurant_id=foreign",
    "/tariffs?restaurant_id=r1&approved=true", "/capabilities?restaurant_id=%20", "/capabilities?restaurant_id=" + "x" * 1025])
def test_invalid_lookup_query_finite_private(application, path):
    assert request(application, path).status_code == 422


@pytest.mark.parametrize("change", ["unknown", "null_finance", "operation_id", "amount", "json", "large"])
def test_invalid_payload_does_not_echo_input(application, change):
    body = create_request().model_dump(mode="json"); content = None
    if change == "unknown": body["private"] = PII[0]
    if change == "null_finance": body["financial"] = None
    if change == "operation_id": body["client_operation_id"] = "must_not_admit_intent"
    if change == "amount": body["financial"]["products_bani"] = True
    if change == "json": body, content = None, '{"bad": "' + PII[0]
    if change == "large": body, content = None, "x" * 65537
    response = request(application, "/quote/create", "POST", body=body, content=content)
    assert response.status_code == (413 if change == "large" else 422)


def test_key_unavailable_failclosed_without_environment_read(application):
    keys = iter([KEY.decode(), ""])
    application[2].get_jwt_secret = lambda: next(keys)
    response = request(application, "/quote/create", "POST", body=create_request().model_dump(mode="json"))
    assert response.status_code == 503 and response.json()["detail"]["code"] == "FINANCIAL_PREVIEW_KEY_UNAVAILABLE"


def test_unexpected_error_and_wrong_method_are_private(application, monkeypatch):
    async def broken(*args, **kwargs): raise RuntimeError(PII[0])
    monkeypatch.setattr(application[3].OrderFinancePreviewService, "capabilities", broken)
    assert request(application, "/capabilities?restaurant_id=r1").status_code == 503
    assert request(application, "/tariffs?restaurant_id=r1", "POST").status_code == 405
    assert request(application, "/unknown").status_code == 404
    assert request(application, "").status_code == 404
    assert request(application, "/").status_code == 404


def test_body_collection_is_under_route_deadline(application):
    app, _, _, _ = application
    async def streaming():
        yield b'{"order":'
        raise RuntimeError(PII[0])
    async def perform():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
            result = await client.post("/api/orders/operations/finance/quote/create", content=streaming(),
                headers={"X-Expected-Actor-ID": ADMIN["id"], "Authorization": "Bearer " + token(ADMIN)})
            assert result.status_code == 503 and result.headers["cache-control"] == "no-store"
            assert PII[0] not in result.text
    asyncio.run(perform())


def test_legacy_create_capability_is_unchanged_admin_only(application):
    from utils.order_finance_preview import _ReadDatabase
    app, db, auth, routes = application
    routes.db = _ReadDatabase(db)
    async def perform():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
            for actor, status in ((ADMIN, 200), (RESTAURANT, 403)):
                async def current(): return actor.copy()
                app.dependency_overrides[auth.get_current_user] = current
                response = await client.get("/api/orders/operations/capabilities",
                    headers={"X-Expected-Actor-ID": actor["id"]})
                assert response.status_code == status and response.headers["cache-control"] == "no-store"
                if status == 200:
                    assert response.json() == {"create_recovery_enabled": True}
    asyncio.run(perform())


@pytest.mark.parametrize("case", ["tenant", "role", "disabled", "deleted", "duplicate", "oversize"])
def test_real_signed_session_never_inherits_changed_database_context(application, case):
    db = application[1]
    user = db.rows["users"][1]
    if case == "tenant": user["restaurant_id"] = "r2"
    if case == "role": user["role"] = "admin"
    if case == "disabled": user["account_disabled"] = True
    if case == "deleted": db.rows["users"].remove(user)
    if case == "duplicate": db.rows["users"].append(dict(user))
    if case == "oversize": user["unexpected"] = "x" * 8192
    result = request(application, "/tariffs?restaurant_id=" + ("r2" if case == "tenant" else "r1"), actor=RESTAURANT)
    assert result.status_code in {401, 403, 503}
    assert not any(name == "restaurant_tariff_versions" for name, *_ in db.reads)


@pytest.mark.parametrize("bad", ["expired", "refresh", "wrong_signature", "malformed", "long"])
def test_actual_token_verification_rejects_before_reads(application, bad):
    bearer = token(ADMIN, exp=1) if bad == "expired" else token(ADMIN, type="refresh") if bad == "refresh" else "bad"
    if bad == "wrong_signature": bearer = jwt.encode({"user_id": ADMIN["id"], "role": "admin", "type": "access"}, b"wrong-synthetic-signing-key-long-enough", algorithm="HS256")
    if bad == "long": bearer = "x" * 8193
    result = request(application, "/tariffs?restaurant_id=r1", extra_headers={"Authorization": "Bearer " + bearer})
    assert result.status_code == 401
    assert application[1].reads == []


def test_cookie_precedence_uses_signed_scope_and_does_not_hydrate(application):
    application[1].rows["users"][1]["restaurant_id"] = "r2"
    response = request(application, "/tariffs?restaurant_id=r2", actor=RESTAURANT,
        extra_headers={"Cookie": "access_token=" + token(RESTAURANT), "Authorization": "Bearer " + token(ADMIN)})
    assert response.status_code == 403


@pytest.mark.parametrize("content", ['{"order":{},"order":{}}', '{"financial":{"products_bani":NaN}}', "[" * 5000])
def test_ambiguous_or_nonfinite_json_rejected(application, content):
    assert request(application, "/quote/create", "POST", content=content).status_code == 422
