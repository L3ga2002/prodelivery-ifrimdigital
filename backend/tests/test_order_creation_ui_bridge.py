"""Staged bridge QA with in-memory doubles, no app/env imports or DB access.

The runner supplies the existing backend model/dependency import path. Service
and router are loaded from this staging tree; auth/database imports are stubbed.
These doubles do not prove real Mongo transaction or cancellation behavior.
"""

import asyncio
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest
from pymongo.errors import AutoReconnect, DuplicateKeyError

from models.order_mutation import CreateOrderCommand, build_mutation_intent


BACKEND = Path(__file__).resolve().parents[1]
OP = "bridge_operation_0001"
ADMIN = {"id": "bridge-admin", "role": "admin"}
RESTAURANT = {"id": "bridge-restaurant-user", "role": "restaurant", "restaurant_id": "bridge-restaurant"}
PII = ("Bridge Customer Sentinel", "0700000077", "Bridge Private Address 123", "Bridge secret note")
RECEIPT_FIELDS = {"client_operation_id", "state", "order_id", "order_version", "error_code", "retry_after_seconds"}


def load_module(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def creation(monkeypatch):
    return load_module("_pd_bridge_creation", BACKEND / "utils/order_creation.py", monkeypatch)


@pytest.fixture
def routes(creation, monkeypatch):
    auth = ModuleType("auth")

    async def unauthenticated():
        raise HTTPException(status_code=401, detail="Authentication required")

    auth.get_current_user = unauthenticated
    database = ModuleType("database")
    database.db = None
    monkeypatch.setitem(sys.modules, "auth", auth)
    monkeypatch.setitem(sys.modules, "database", database)
    monkeypatch.setitem(sys.modules, "utils.order_creation", creation)
    return load_module("_pd_bridge_routes", BACKEND / "routers/order_operations.py", monkeypatch)


def command():
    return CreateOrderCommand(client_operation_id=OP, order={
        "restaurant_id": RESTAURANT["restaurant_id"], "customer_name": PII[0],
        "customer_phone": PII[1], "customer_address": PII[2], "notes": PII[3],
        "total_amount": 32.5, "payment_type": "CASH", "source": "bridge",
    })


def stored_operation(creation, actor=ADMIN, state="pending"):
    intent = command()
    operation = {
        "_id": creation.operation_key(actor["id"], OP), "actor_id": actor["id"],
        "actor_role": actor["role"], "restaurant_id": intent.order.restaurant_id,
        "client_operation_id": OP, "command": intent.model_dump(mode="json"),
        "payload_digest": build_mutation_intent(actor["id"], "create", None, intent).payload_digest,
        "state": state,
    }
    if state == "applied":
        operation["order_id"] = "bridge-existing-order"
    if state == "rejected":
        operation.update(error_code="RESTAURANT_PAUSED", error_status=409)
    return operation


def assert_private(value):
    for sentinel in PII:
        assert sentinel not in str(value)


def matches(document, query):
    return all(
        document.get(field) != value["$ne"] if isinstance(value, dict) and "$ne" in value
        else document.get(field) == value
        for field, value in query.items()
    )


class Collection:
    def __init__(self, db, name, documents=()):
        self.db, self.name = db, name
        self.documents = deepcopy(list(documents))
        self.failure = None
        self.delay = 0

    def event(self, method, session=None):
        self.db.events.append((self.name, method, session is not None))

    async def find_one(self, query, projection=None, session=None):
        self.event("find_one", session)
        self.db.reads.append((self.name, deepcopy(query), deepcopy(projection)))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure:
            raise self.failure
        result = next((deepcopy(doc) for doc in self.documents if matches(doc, query)), None)
        if result is not None and projection:
            fields = {name for name, include in projection.items() if include}
            if projection.get("_id", 1):
                fields.add("_id")
            result = {name: value for name, value in result.items() if name in fields}
        return result

    async def insert_one(self, document, session=None):
        self.event("insert_one", session)
        if any(doc.get("_id") == document.get("_id") for doc in self.documents):
            raise DuplicateKeyError("Synthetic duplicate")
        self.documents.append(deepcopy(document))

    async def update_one(self, query, update, session=None):
        self.event("update_one", session)
        for document in self.documents:
            if matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                for field, amount in update.get("$inc", {}).items():
                    document[field] = document.get(field, 0) + amount
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    async def find_one_and_update(self, query, update, session=None, **kwargs):
        await self.update_one(query, update, session)
        return await self.find_one(query, session=session)


class Session:
    def __init__(self, db):
        self.db = db
        self.in_transaction = False

    def start_transaction(self, **kwargs):
        self.db.events.append(("session", "start_transaction", True))
        self.snapshot = {name: deepcopy(collection.documents) for name, collection in self.db.collections.items()}
        self.in_transaction = True

    async def commit_transaction(self):
        self.db.events.append(("session", "commit_transaction", True))
        self.in_transaction = False

    async def abort_transaction(self):
        self.db.events.append(("session", "abort_transaction", True))
        for name, documents in self.snapshot.items():
            self.db.collections[name].documents = documents
        self.in_transaction = False

    async def end_session(self):
        self.db.events.append(("session", "end_session", False))


class Database:
    def __init__(self, operation=None, marker=None, actor=ADMIN):
        self.events, self.reads = [], []
        self.collections = {}
        documents = {
            "users": [{"_id": "bridge-user-document", **actor, "account_disabled": False}],
            "restaurants": [{"_id": "bridge-restaurant-document", "id": RESTAURANT["restaurant_id"],
                             "name": "Bridge Restaurant", "accepting_orders": True}],
            "order_operation_settings": [] if marker is None else [marker],
            "order_operations": [] if operation is None else [operation],
            "counters": [{"_id": "orders.global", "seq": 100}],
            "orders": [], "audit_logs": [],
        }
        for name, docs in documents.items():
            collection = self.collections[name] = Collection(self, name, docs)
            setattr(self, name, collection)
        self.client = SimpleNamespace(start_session=self.start_session)
        self.command_failure = None

    def get_collection(self, name, **kwargs):
        return self.collections[name]

    async def command(self, name, **kwargs):
        self.events.append(("database", name, False))
        if self.command_failure:
            raise self.command_failure
        assert name == "hello"
        return {"setName": "bridge_mock_only"}

    async def start_session(self):
        self.events.append(("session", "start_session", False))
        return Session(self)


def assert_read_only(db):
    assert all(method == "find_one" for _, method, _ in db.events)


def assert_error(creation, awaitable, status, code):
    with pytest.raises(creation.CreationError) as error:
        asyncio.run(awaitable)
    assert (error.value.status_code, error.value.code) == (status, code)
    assert_private(error.value.message)
    return error.value


@pytest.mark.parametrize("marker,enabled", [
    (None, False), ({"_id": "order-create-v1", "enabled": False}, False),
    ({"_id": "order-create-v1", "enabled": True}, True),
])
def test_capabilities_reads_only_authorized_actor_and_exact_marker(creation, marker, enabled):
    db = Database(marker=marker)
    result = asyncio.run(creation.OrderCreationService(db).capabilities(ADMIN))
    assert result == {"create_recovery_enabled": enabled}
    assert type(result["create_recovery_enabled"]) is bool
    assert db.reads == [
        ("users", {"id": ADMIN["id"]}, {"id": 1, "role": 1, "restaurant_id": 1, "account_disabled": 1}),
        ("order_operation_settings", {"_id": "order-create-v1"}, {"enabled": 1, "_id": 0}),
    ]
    assert_read_only(db)


@pytest.mark.parametrize("enabled", [None, 0, 1, "true", "false", {}, []])
def test_capabilities_malformed_marker_never_downgrades_to_disabled(creation, enabled):
    db = Database(marker={"_id": "order-create-v1", "enabled": enabled})
    assert_error(creation, creation.OrderCreationService(db).capabilities(ADMIN), 503, "CAPABILITIES_INVALID")
    assert_read_only(db)


def test_capabilities_missing_enabled_is_invalid(creation):
    db = Database(marker={"_id": "order-create-v1"})
    assert_error(creation, creation.OrderCreationService(db).capabilities(ADMIN), 503, "CAPABILITIES_INVALID")
    assert_read_only(db)


@pytest.mark.parametrize("collection", ["users", "order_operation_settings"])
def test_capabilities_db_failure_is_sanitized_503_not_false(creation, collection, caplog):
    db = Database()
    db.collections[collection].failure = AutoReconnect(" ".join(PII))
    assert_error(creation, creation.OrderCreationService(db).capabilities(ADMIN), 503, "CAPABILITIES_UNAVAILABLE")
    assert_private(caplog.text)
    assert_read_only(db)


@pytest.mark.parametrize("api", ["capabilities", "resume"])
@pytest.mark.parametrize("change,status,code", [
    ({"account_disabled": True}, 403, "ACCOUNT_DISABLED"),
    ({"role": "driver"}, 403, "NOT_AUTHORIZED"),
    ({"role": "restaurant", "restaurant_id": "other"}, 403, "NOT_AUTHORIZED"),
    ({"id": "deleted-admin"}, 401, "AUTH_REQUIRED"),
])
def test_bridge_rereads_authoritative_actor_before_other_reads(creation, api, change, status, code):
    db = Database(operation=stored_operation(creation))
    db.users.documents[0].update(change)
    service = creation.OrderCreationService(db)
    awaitable = service.capabilities(ADMIN) if api == "capabilities" else service.resume(OP, ADMIN)
    assert_error(creation, awaitable, status, code)
    assert {name for name, _, _ in db.events} == {"users"}
    assert_read_only(db)


def test_capabilities_rejects_authorized_restaurant_and_missing_identity(creation):
    db = Database(actor=RESTAURANT)
    service = creation.OrderCreationService(db)
    assert_error(creation, service.capabilities(RESTAURANT), 403, "NOT_AUTHORIZED")
    assert_error(creation, service.capabilities({"role": "admin"}), 401, "AUTH_REQUIRED")
    assert all(name == "users" for name, _, _ in db.events)


@pytest.mark.parametrize("api", ["capabilities", "resume"])
def test_bridge_reads_use_bounded_request_deadline(creation, monkeypatch, api, caplog):
    monkeypatch.setattr(creation, "DEADLINE_SECONDS", 0.01)
    db = Database(operation=stored_operation(creation))
    collection = db.order_operation_settings if api == "capabilities" else db.order_operations
    collection.delay = 0.1
    service = creation.OrderCreationService(db)
    awaitable = service.capabilities(ADMIN) if api == "capabilities" else service.resume(OP, ADMIN)
    code = "CAPABILITIES_UNAVAILABLE" if api == "capabilities" else "RECOVERY_UNAVAILABLE"
    assert_error(creation, awaitable, 503, code)
    assert_read_only(db)
    assert_private(caplog.text)


@pytest.mark.parametrize("marker", [None, {"_id": "order-create-v1", "enabled": False}])
@pytest.mark.parametrize("actor", [ADMIN, RESTAURANT])
def test_resume_pending_executes_original_command_once_without_new_admission(creation, marker, actor, caplog):
    caplog.set_level("INFO", logger=creation.logger.name)
    operation = stored_operation(creation, actor)
    original_command = deepcopy(operation["command"])
    db = Database(operation=operation, marker=marker, actor=actor)
    service = creation.OrderCreationService(db)

    async def scenario():
        applied = await service.resume(OP, actor)
        replayed = await service.resume(OP, actor)
        looked_up = await service.lookup(OP, actor)
        return applied, replayed, looked_up

    applied, replayed, looked_up = asyncio.run(scenario())
    assert (applied.status_code, applied.result.state) == (201, "applied")
    assert (replayed.status_code, replayed.result.state) == (200, "replayed")
    assert looked_up.result == replayed.result
    assert applied.result.order_id == replayed.result.order_id
    assert applied.result.order_version == 0
    assert len(db.orders.documents) == len(db.audit_logs.documents) == 1
    assert db.counters.documents[0]["seq"] == 101
    assert db.order_operations.documents[0]["command"] == original_command
    assert db.orders.documents[0]["customer_name"] == original_command["order"]["customer_name"]
    assert not any(name == "order_operation_settings" for name, _, _ in db.events)
    assert not any(name == "order_operations" and method == "insert_one" for name, method, _ in db.events)
    assert all(in_session for _, method, in_session in db.events if method in {"insert_one", "update_one"})
    assert_private(applied.result.model_dump())
    assert_private(replayed.result.model_dump())
    assert_private(db.audit_logs.documents)
    assert_private(caplog.text)


@pytest.mark.parametrize("state,status", [("applied", 200), ("rejected", 409)])
def test_resume_terminal_returns_existing_receipt_without_writes_or_preflight(creation, state, status):
    db = Database(operation=stored_operation(creation, state=state))
    outcome = asyncio.run(creation.OrderCreationService(db).resume(OP, ADMIN))
    assert outcome.status_code == status
    assert outcome.result.state == ("replayed" if state == "applied" else "rejected")
    assert_private(outcome.result.model_dump())
    assert_read_only(db)
    assert {name for name, _, _ in db.events} == {"users", "order_operations"}


def test_resume_pending_rejection_stays_terminal_when_restaurant_reopens(creation):
    db = Database(operation=stored_operation(creation))
    db.restaurants.documents[0]["accepting_orders"] = False
    service = creation.OrderCreationService(db)

    async def scenario():
        first = await service.resume(OP, ADMIN)
        db.restaurants.documents[0]["accepting_orders"] = True
        second = await service.resume(OP, ADMIN)
        return first, second

    first, second = asyncio.run(scenario())
    assert first.result == second.result
    assert first.status_code == second.status_code == 409
    assert first.result.error_code == "RESTAURANT_PAUSED"
    assert db.counters.documents[0]["seq"] == 100
    assert not db.orders.documents and not db.audit_logs.documents


def test_resume_missing_or_foreign_identity_does_not_admit_or_leak(creation):
    foreign = {"id": "other-admin", "role": "admin"}
    db = Database(operation=stored_operation(creation, foreign))
    before = deepcopy(db.order_operations.documents)
    assert_error(creation, creation.OrderCreationService(db).resume(OP, ADMIN), 404, "OPERATION_NOT_FOUND")
    assert db.order_operations.documents == before
    assert_read_only(db)
    assert {name for name, _, _ in db.events} == {"users", "order_operations"}


@pytest.mark.parametrize("change", [
    {"command": None}, {"command": {"client_operation_id": OP}},
    {"payload_digest": "tampered"}, {"actor_id": "other-admin"},
    {"client_operation_id": "different_operation_0001"}, {"restaurant_id": "other"},
    {"actor_role": "driver"}, {"state": "unknown"},
    {"state": "applied", "order_id": None}, {"state": "applied", "order_id": {"customer": PII[0]}},
    {"state": "rejected", "error_status": True, "error_code": "RESTAURANT_PAUSED"},
    {"state": "rejected", "error_status": 409, "error_code": PII[0]},
])
def test_resume_malformed_persisted_intent_is_sanitized_and_read_only(creation, change, caplog):
    operation = stored_operation(creation)
    operation.update(change)
    db = Database(operation=operation)
    assert_error(creation, creation.OrderCreationService(db).resume(OP, ADMIN), 503, "OPERATION_INVALID")
    assert_read_only(db)
    assert_private(caplog.text)


def test_resume_mutated_valid_customer_command_fails_digest_validation(creation):
    operation = stored_operation(creation)
    operation["command"]["order"]["customer_name"] = "Different Customer"
    db = Database(operation=operation)
    assert_error(creation, creation.OrderCreationService(db).resume(OP, ADMIN), 503, "OPERATION_INVALID")
    assert_read_only(db)


@pytest.mark.parametrize("state", ["pending", "applied", "rejected"])
def test_resume_role_change_since_original_admission_denied_even_with_fresh_context(creation, state):
    operation = stored_operation(creation, state=state)
    operation["actor_role"] = "restaurant"
    db = Database(operation=operation)
    assert_error(creation, creation.OrderCreationService(db).resume(OP, ADMIN), 403, "AUTH_CONTEXT_CHANGED")
    assert_read_only(db)


def test_resume_changed_restaurant_binding_is_denied(creation):
    db = Database(operation=stored_operation(creation, RESTAURANT), actor=RESTAURANT)
    db.users.documents[0]["restaurant_id"] = "different-restaurant"
    assert_error(creation, creation.OrderCreationService(db).resume(OP, RESTAURANT), 403, "NOT_AUTHORIZED")
    assert_read_only(db)


@pytest.mark.parametrize("change,status,code", [
    ("command", 503, "OPERATION_INVALID"), ("actor", 403, "ACCOUNT_DISABLED"),
])
def test_resume_revalidates_intent_and_actor_inside_execution(creation, monkeypatch, change, status, code):
    db = Database(operation=stored_operation(creation))
    service = creation.OrderCreationService(db)
    execute = service._execute

    async def changed_after_preflight(*args):
        if change == "command":
            db.order_operations.documents[0]["command"]["order"]["customer_name"] = "Different Customer"
        else:
            db.users.documents[0]["account_disabled"] = True
        return await execute(*args)

    monkeypatch.setattr(service, "_execute", changed_after_preflight)
    assert_error(creation, service.resume(OP, ADMIN), status, code)
    assert db.counters.documents[0]["seq"] == 100
    assert not db.orders.documents and not db.audit_logs.documents
    assert not any(method in {"insert_one", "update_one"} for _, method, _ in db.events)
    assert any(method == "end_session" for _, method, _ in db.events)


@pytest.mark.parametrize("phase", ["read", "preflight", "execute"])
def test_resume_db_failures_preserve_uncertainty_without_raw_error(creation, phase, caplog):
    db = Database(operation=stored_operation(creation))
    if phase == "preflight":
        db.command_failure = AutoReconnect(" ".join(PII))
    else:
        collection = db.order_operations if phase == "read" else db.counters
        collection.failure = AutoReconnect(" ".join(PII))
    service = creation.OrderCreationService(db)
    if phase == "execute":
        outcome = asyncio.run(service.resume(OP, ADMIN))
        assert (outcome.status_code, outcome.result.state) == (202, "pending")
        assert_private(outcome.result.model_dump())
    else:
        assert_error(creation, service.resume(OP, ADMIN), 503, "RECOVERY_UNAVAILABLE")
    assert db.order_operations.documents[0]["state"] == "pending"
    assert db.counters.documents[0]["seq"] == 100
    assert not db.orders.documents and not db.audit_logs.documents
    assert_private(caplog.text)


def test_resume_and_create_keep_counter_validation_despite_enabled_marker(creation):
    db = Database(operation=stored_operation(creation), marker={"_id": "order-create-v1", "enabled": True})
    db.counters.documents.clear()
    service = creation.OrderCreationService(db)
    assert asyncio.run(service.capabilities(ADMIN)) == {"create_recovery_enabled": True}
    assert_error(creation, service.resume(OP, ADMIN), 503, "COUNTER_NOT_READY")
    db.order_operations.documents.clear()
    assert_error(creation, service.create(command(), ADMIN), 503, "COUNTER_NOT_READY")
    assert not db.orders.documents and not db.audit_logs.documents


def test_enabled_capability_does_not_bypass_create_topology_validation(creation, monkeypatch):
    db = Database(marker={"_id": "order-create-v1", "enabled": True})
    service = creation.OrderCreationService(db)

    async def unsupported_topology(*args, **kwargs):
        return {"isWritablePrimary": True}

    monkeypatch.setattr(db, "command", unsupported_topology)
    assert asyncio.run(service.capabilities(ADMIN)) == {"create_recovery_enabled": True}
    assert_error(creation, service.create(command(), ADMIN), 503, "TRANSACTIONS_REQUIRED")
    assert not db.order_operations.documents
    assert_read_only(db)


def test_resume_has_one_deadline_including_execution(creation, monkeypatch):
    from contextlib import asynccontextmanager

    entered = []
    original_deadline = creation._request_deadline

    @asynccontextmanager
    async def observe_deadline():
        entered.append("entered")
        async with original_deadline():
            yield

    monkeypatch.setattr(creation, "_request_deadline", observe_deadline)
    db = Database(operation=stored_operation(creation))
    outcome = asyncio.run(creation.OrderCreationService(db).resume(OP, ADMIN))
    assert outcome.status_code == 201
    assert entered == ["entered"]


def request(routes, db, method, path, actor=ADMIN, **kwargs):
    routes.db = db
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    if actor is not None:
        app.dependency_overrides[routes.get_current_user] = lambda: actor

    async def scenario():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://bridge.invalid") as client:
            return await client.request(method, "/api/orders/operations" + path, **kwargs)

    response = asyncio.run(scenario())
    assert response.headers["cache-control"] == "no-store"
    assert_private(response.text)
    return response


def test_capabilities_route_and_auth_errors_are_no_store(routes, creation):
    db = Database(marker={"_id": "order-create-v1", "enabled": True})
    response = request(routes, db, "GET", "/capabilities")
    assert response.status_code == 200 and response.json() == {"create_recovery_enabled": True}
    db.events.clear()
    response = request(routes, db, "GET", "/capabilities", actor=None)
    assert response.status_code == 401 and not db.events


@pytest.mark.parametrize("phase", ["disabled", "db_failure", "restaurant", "malformed"])
def test_capabilities_route_never_returns_false_for_auth_db_or_corruption(routes, phase):
    db = Database()
    if phase == "disabled":
        db.users.documents[0]["account_disabled"] = True
    elif phase == "db_failure":
        db.order_operation_settings.failure = AutoReconnect(" ".join(PII))
    elif phase == "malformed":
        db.order_operation_settings.documents = [{"_id": "order-create-v1", "enabled": "true"}]
    else:
        db.users.documents[0].update(RESTAURANT)
    response = request(routes, db, "GET", "/capabilities", actor=RESTAURANT if phase == "restaurant" else ADMIN)
    assert response.status_code == (503 if phase in {"db_failure", "malformed"} else 403)
    assert "create_recovery_enabled" not in response.json()
    assert_read_only(db)


@pytest.mark.parametrize("state,status,result_state", [
    ("pending", 201, "applied"), ("applied", 200, "replayed"), ("rejected", 409, "rejected"),
    (None, 404, None), ("malformed", 503, None),
])
def test_resume_route_uses_existing_private_receipt_contract(routes, creation, state, status, result_state):
    operation = None if state is None else stored_operation(creation, state=state)
    db = Database(operation=operation)
    response = request(routes, db, "POST", f"/create/{OP}/resume")
    assert response.status_code == status
    if result_state:
        assert response.json()["state"] == result_state
        assert set(response.json()) == RECEIPT_FIELDS


def test_resume_route_pending_retry_after_and_unauthenticated_no_store(routes, creation):
    db = Database(operation=stored_operation(creation))
    db.counters.failure = AutoReconnect(" ".join(PII))
    response = request(routes, db, "POST", f"/create/{OP}/resume")
    assert response.status_code == 202 and response.json()["state"] == "pending"
    assert response.headers["retry-after"] == str(response.json()["retry_after_seconds"])
    db.events.clear()
    response = request(routes, db, "POST", f"/create/{OP}/resume", actor=None)
    assert response.status_code == 401 and not db.events


@pytest.mark.parametrize("body", [b"{}", b"null", b" ", PII[0].encode(), b"x" * 10000])
def test_resume_route_rejects_every_nonempty_body_without_db_access(routes, body):
    db = Database()
    response = request(routes, db, "POST", f"/create/{OP}/resume", content=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert not db.events


def test_resume_route_rejects_full_customer_command_and_invalid_id_without_echo(routes):
    db = Database()
    response = request(routes, db, "POST", f"/create/{OP}/resume", json=command().model_dump(mode="json"))
    assert response.status_code == 422 and not db.events
    response = request(routes, db, "POST", "/create/short/resume")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_OPERATION_ID" and not db.events


def test_resume_openapi_has_no_customer_body_and_preserves_existing_routes(routes):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    paths = app.openapi()["paths"]
    assert "requestBody" not in paths["/api/orders/operations/create/{client_operation_id}/resume"]["post"]
    assert "requestBody" in paths["/api/orders/operations/create"]["post"]
    assert "get" in paths["/api/orders/operations/create/{client_operation_id}"]
