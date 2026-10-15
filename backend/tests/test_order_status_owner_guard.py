"""Real cookie-first auth with synthetic JWT/DB only, no dependency overrides."""
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import sys
from types import MappingProxyType, ModuleType, SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from test_order_creation_recovery import db, mongo_case, snapshot
from test_order_assignment_owner_guard import load_module, ForbiddenBusinessDatabase
from models.order_mutation import StatusOrderCommand
from utils.order_status import OrderStatusService

REAL = Path(r"C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend")
SOURCE = Path(__file__).resolve().parents[1]
KEY = "synthetic-status-guard-not-a-live-secret-20261007"
ACTIONS = ("capability", "status", "lookup", "resume", "legacy")
OP = "qa_status_real_owner_guard_0001"


@pytest.fixture
def routes(monkeypatch):
    stub = ModuleType("database")
    stub.db = ForbiddenBusinessDatabase()
    monkeypatch.setitem(sys.modules, "database", stub)
    auth = load_module(monkeypatch, "auth", REAL / "auth.py")
    monkeypatch.setattr(auth, "os", SimpleNamespace(environ=MappingProxyType({"JWT_SECRET": KEY})))
    operations = load_module(monkeypatch, "_pd_status_owner_operations", SOURCE / "routers/order_operations.py")
    legacy = load_module(monkeypatch, "_pd_status_owner_legacy", SOURCE / "routers/orders.py")
    assert operations.get_current_user is legacy.get_current_user is auth.get_current_user
    assert Path(inspect.getsourcefile(auth.get_current_user)).resolve() == REAL / "auth.py"
    app = FastAPI()
    app.include_router(operations.router, prefix="/api")
    app.include_router(legacy.router, prefix="/api")
    assert not app.dependency_overrides
    return SimpleNamespace(auth=auth, operations=operations, legacy=legacy, app=app)


async def seed(database, role):
    for label in ("a", "b"):
        user = {"id": label, "role": role, "name": "Synthetic " + label,
                "email": label + "@qa.invalid", "restaurant_id": "r-" + label, "account_disabled": False}
        await database.users.insert_one(user)
        # Production driver users do not need a denormalized driver_id field.
        driver_user_id = label if role == "driver" else "custody-" + label
        if role != "driver":
            await database.users.insert_one({"id": driver_user_id, "role": "driver", "name": "Custody " + label,
                "email": driver_user_id + "@qa.invalid", "account_disabled": False})
        await database.drivers.insert_one({"id": "d-" + label, "user_id": driver_user_id, "name": "Driver " + label,
            "driver_status": "delivery" if label == "a" else "active", "is_active": True,
            "current_order_id": "q" if label == "a" else None, "account_disabled": False,
            "total_deliveries": 0, "total_earnings": 0})
        await database.restaurants.insert_one({"id": "r-" + label, "name": "Restaurant " + label})
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    await database.orders.insert_one({"id": "q", "order_version": 7, "status": "ASSIGNED",
        "restaurant_id": "r-a", "driver_id": "d-a", "driver_name": "Driver a", "assigned_at": now.isoformat(),
        "preparation_status": "READY", "total_amount": 30, "audit_trail": []})
    await database.order_operation_settings.insert_one({"_id": "order-status-v1", "enabled": True})
    tokens = {}
    for label in ("a", "b"):
        user = await database.users.find_one({"id": label})
        tokens[label] = user
    return tokens


async def request(routes, database, users, role, action, *, cookie="a", bearer="a", expected="a", blocked=False):
    routes.auth.db = database
    target = ForbiddenBusinessDatabase() if blocked else database
    routes.operations.db = routes.legacy.db = target
    tokens = {}
    for label, user in users.items():
        payload = routes.auth._build_access_payload(user)
        payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=5)
        tokens[label] = routes.auth.jwt.encode(payload, KEY, algorithm=routes.auth.JWT_ALGORITHM)
    headers = {"Cookie": "access_token=" + tokens[cookie]}
    if bearer:
        headers["Authorization"] = "Bearer " + tokens[bearer]
    if expected is not None:
        headers["X-Expected-Actor-ID"] = expected
    status = "CANCELLED" if role == "restaurant" else "ACCEPTED"
    payload = {"client_operation_id": OP, "expected_order_version": 7, "status": status}
    if status == "CANCELLED":
        payload["cancellation_reason"] = "Synthetic operational reason"
    root = "/api/orders/operations/status"
    method, path, body = {
        "capability": ("GET", root + "/capabilities", None),
        "status": ("POST", root + "/q", payload),
        "lookup": ("GET", root + "/q/" + OP, None),
        "resume": ("POST", root + "/q/" + OP + "/resume", None),
        "legacy": ("PUT", "/api/orders/q/status", {"status": status, **({"cancellation_reason": payload["cancellation_reason"]} if status == "CANCELLED" else {})}),
    }[action]
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    async with AsyncClient(transport=ASGITransport(app=routes.app), base_url="http://qa.invalid") as client:
        response = await client.request(method, path, **kwargs)
    assert not routes.app.dependency_overrides
    assert all(token not in response.text for token in tokens.values())
    if action != "legacy":
        assert response.headers["cache-control"] == "no-store"
    return response


@pytest.mark.parametrize("role", ["admin", "restaurant", "driver"])
@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("bearer", ["a", None])
@mongo_case
async def test_cookie_substitution_refused_before_business_access(db, routes, role, action, bearer):
    users = await seed(db, role)
    before = await snapshot(db)
    response = await request(routes, db, users, role, action, cookie="b", bearer=bearer, blocked=True)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "AUTH_CONTEXT_CHANGED"
    assert await snapshot(db) == before


@pytest.mark.parametrize("role", ["admin", "restaurant", "driver"])
@mongo_case
async def test_real_context_applies_and_restores_same_receipt(db, routes, role):
    users = await seed(db, role)
    capability = await request(routes, db, users, role, "capability")
    assert capability.status_code == 200 and capability.json() == {"status_recovery_enabled": True}
    response = await request(routes, db, users, role, "status")
    assert response.status_code == 200 and response.json()["state"] == "applied"
    assert response.json()["order_version"] == 8
    before = await snapshot(db)
    for action in ("lookup", "resume", "status"):
        recovered = await request(routes, db, users, role, action)
        assert recovered.status_code == 200 and recovered.json()["state"] == "replayed"
        assert recovered.json()["client_operation_id"] == OP
    assert await snapshot(db) == before


@pytest.mark.parametrize("role", ["restaurant", "driver"])
@mongo_case
async def test_terminal_own_receipt_is_not_a_current_foreign_order_snapshot(db, role):
    users = await seed(db, role)
    actor = {**users["a"], **({"driver_id": "d-a"} if role == "driver" else {})}
    cmd = StatusOrderCommand(client_operation_id=OP, expected_order_version=7,
        status="CANCELLED" if role == "restaurant" else "ACCEPTED",
        **({"cancellation_reason": "Synthetic completed cancellation"} if role == "restaurant" else {}))
    service = OrderStatusService(db)
    applied = await service.status("q", cmd, actor)
    assert applied.status_code == 200 and applied.result.state == "applied"
    await db.orders.update_one({"id": "q"}, {"$set": {
        "restaurant_id": "r-b"} if role == "restaurant" else {"driver_id": "d-b"}})
    before = await snapshot(db)
    for action in (lambda: service.lookup("q", OP, actor), lambda: service.resume("q", OP, actor),
                   lambda: service.status("q", cmd, actor)):
        result = await action()
        assert result.status_code == 200 and result.result.state == "replayed"
        assert result.result.order_id == "q" and result.result.order_version == 8
        assert set(result.result.model_dump(exclude_none=True)) == {
            "client_operation_id", "state", "order_id", "order_version"}
        assert await snapshot(db) == before


@pytest.mark.parametrize("expected", ["", " ", " a", "a ", "a" * 121, "a\x7f"])
@pytest.mark.parametrize("action", ACTIONS)
@mongo_case
async def test_malformed_header_refused_without_echo_or_business_access(db, routes, expected, action):
    users = await seed(db, "admin")
    before = await snapshot(db)
    response = await request(routes, db, users, "admin", action, expected=expected, blocked=True)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == ("INVALID_ACTOR_ID" if action == "legacy" else "INVALID_EXPECTED_ACTOR_ID")
    assert await snapshot(db) == before
