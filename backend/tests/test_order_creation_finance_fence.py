"""F2A fence/race/actual-router probes, entirely synthetic and socket-guarded."""
import asyncio
from copy import deepcopy
import json

from httpx import ASGITransport, AsyncClient
import pytest

from models.order_mutation import CreateOrderCommand, build_mutation_intent
from utils.order_creation import CreationError, OrderCreationService, _validated_operation, operation_key
from test_order_finance_preview import ADMIN, KEY, PII, RESTAURANT, DRIVER
from test_order_finance_preview_http import application as f1_application, token
from test_order_finance_confirmation import Database, CONTEXT, OP, run, confirmed, close_body, pending_service, failure


@pytest.fixture
def application(f1_application, monkeypatch):
    app, _, auth, routes = f1_application
    db = Database()
    monkeypatch.setattr(routes, "db", db)
    monkeypatch.setattr(auth, "db", db)
    return app, db, auth, routes


def http(application, path, method="GET", body=None, actor=ADMIN, headers=None, content=None, legacy=False):
    app, db, auth, routes = application
    async def legacy_actor(): return actor
    app.dependency_overrides[auth.get_current_user] = legacy_actor
    values = {"Authorization": "Bearer " + token(actor), "X-Expected-Actor-ID": actor["id"]}
    values.update(headers or {})
    async def perform():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
            result = await client.request(method, "/api/orders/operations" + ("" if legacy else "/finance") + path,
                json=body, content=content, headers=values)
            assert result.headers.get("cache-control") == "no-store"
            assert all(value not in result.text for value in PII)
            return result
    return run(perform())


def test_close_without_quote_key_grid_marker_or_open_restaurant_and_replay():
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    db.order_operation_settings.documents.clear(); db.restaurant_tariff_versions.documents.clear()
    db.restaurants.documents.clear()
    outcome = run(service.close_financial(OP, close_body(command), ADMIN, financial_context=CONTEXT))
    assert outcome.result.state == "rejected" and outcome.result.error_code == "FINANCIAL_INTENT_CLOSED"
    row = deepcopy(db.order_operations.documents[0])
    assert run(service.close_financial(OP, close_body(command), ADMIN, financial_context=CONTEXT)).result == outcome.result
    assert run(service.create(command, ADMIN, financial_context=CONTEXT)).result == outcome.result
    assert db.order_operations.documents == [row] and service.executions == []
    assert db.orders.documents == db.audit_logs.documents == []
    assert db.counters.documents[0]["seq"] == 100
    options = next(options for name, options in db.collection_options if name == "order_operations" and options)
    assert options["write_concern"].document == {"w": "majority", "wtimeout": 3000}
    assert options["read_concern"].document == {"level": "majority"}


@pytest.mark.parametrize("state", ["pending", "applied", "rejected"])
def test_close_returns_existing_admitted_outcome_without_changing_it(state):
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    run(service.create(command, ADMIN, financial_context=CONTEXT, signing_key=KEY))
    row = db.order_operations.documents[0]
    if state == "applied": row.update(state=state, order_id="synthetic-result")
    if state == "rejected": row.update(state=state, error_code="RESTAURANT_PAUSED", error_status=409)
    before = deepcopy(row); event = len(db.events)
    result = run(service.close_financial(OP, close_body(command), ADMIN, financial_context=CONTEXT))
    assert result.result.state == ("replayed" if state == "applied" else state)
    assert db.order_operations.documents == [before]
    assert not any(method in {"insert_one", "update_one"} for _, method, _ in db.events[event:])


@pytest.mark.parametrize("winner", ["close", "admission"])
def test_controlled_unique_insert_linearization(winner):
    async def race():
        db = Database(); command = await confirmed(db); service = pending_service(db)
        reached, release = asyncio.Event(), asyncio.Event()
        async def barrier(name, row):
            if name == "order_operations" and row["state"] == "pending":
                reached.set(); await release.wait()
        if winner == "close":
            db.before_insert = barrier
            submitting = asyncio.create_task(service.create(command, ADMIN, financial_context=CONTEXT, signing_key=KEY))
            await asyncio.wait_for(reached.wait(), 1)
            closing = await service.close_financial(OP, close_body(command), ADMIN, financial_context=CONTEXT)
            release.set(); submitted = await submitting
            assert submitted.result == closing.result and submitted.result.state == "rejected"
            assert service.executions == []
        else:
            await service.create(command, ADMIN, financial_context=CONTEXT, signing_key=KEY)
            closing = await service.close_financial(OP, close_body(command), ADMIN, financial_context=CONTEXT)
            assert closing.result.state == "pending"
            assert len(service.executions) == 1
        assert len(db.order_operations.documents) == 1
        assert db.orders.documents == db.audit_logs.documents == [] and db.counters.documents[0]["seq"] == 100
    run(race())


def test_two_closes_and_changed_intent_cannot_replace_winner():
    async def race():
        db = Database(); command = await confirmed(db); service = pending_service(db)
        first, second = await asyncio.gather(*(service.close_financial(OP, close_body(command), ADMIN,
            financial_context=CONTEXT) for _ in range(2)))
        assert first.result == second.result and len(db.order_operations.documents) == 1
        data = command.model_dump(mode="python"); data["quote_confirmation"]["quote_fingerprint"] = "a"*64
        changed = CreateOrderCommand.model_validate(data)
        with pytest.raises(CreationError, match="Identitatea"):
            await service.create(changed, ADMIN, financial_context=CONTEXT, signing_key=KEY)
        assert len(db.order_operations.documents) == 1
    run(race())


def test_cancelled_waiter_cannot_claim_closed_before_insert_winner():
    async def race():
        db = Database(); command = await confirmed(db); service = pending_service(db)
        reached, release = asyncio.Event(), asyncio.Event()
        async def barrier(name, row):
            if name == "order_operations":
                reached.set(); await release.wait()
        db.before_insert = barrier
        closing = asyncio.create_task(service.close_financial(OP, close_body(command), ADMIN, financial_context=CONTEXT))
        await asyncio.wait_for(reached.wait(), 1)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError): await closing
        assert db.order_operations.documents == []
        db.before_insert = None
        result = await service.create(command, ADMIN, financial_context=CONTEXT, signing_key=KEY)
        assert result.result.state == "pending" and len(db.order_operations.documents) == 1
    run(race())


@pytest.mark.parametrize("operation", ["create", "close"])
@pytest.mark.parametrize("write_happened", [False, True])
def test_unknown_insert_is_pending_never_fabricated_rejection(operation, write_happened):
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    db.fail_after_insert = write_happened; db.fail_before_insert = not write_happened
    result = run(service.create(command, ADMIN, financial_context=CONTEXT, signing_key=KEY) if operation == "create"
        else service.close_financial(OP, close_body(command), ADMIN, financial_context=CONTEXT))
    assert result.result.state == "pending" and result.result.error_code is None
    assert len(db.order_operations.documents) == int(write_happened)
    db.fail_after_insert = db.fail_before_insert = False
    if write_happened:
        result = run(service.lookup(OP, ADMIN, financial_context=CONTEXT))
        assert result.result.state == ("pending" if operation == "create" else "rejected")


@pytest.mark.parametrize("kind", ["confirmed", "terminal"])
@pytest.mark.parametrize("entry", ["lookup", "resume", "create"])
def test_old_service_entries_cannot_hydrate_into_new_protocol(kind, entry):
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    if kind == "confirmed": run(service.create(command, ADMIN, financial_context=CONTEXT, signing_key=KEY))
    else: run(service.close_financial(OP, close_body(command), ADMIN, financial_context=CONTEXT))
    awaitable = service.create(command, ADMIN) if entry == "create" else getattr(service, entry)(OP, ADMIN)
    failure(awaitable, "FINANCIAL_CONTEXT_REQUIRED")


@pytest.mark.parametrize("change", ["marker_type", "marker_version", "kind", "key", "actor", "role", "op", "restaurant", "time", "resolved", "code", "status", "snapshot", "command", "extra", "order"])
def test_terminal_malformed_never_falls_through_snapshot_validator(change):
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    run(service.close_financial(OP, close_body(command), ADMIN, financial_context=CONTEXT))
    row = db.order_operations.documents[0]
    values = {"marker_type": ("creation_terminal_contract_version", True), "marker_version": ("creation_terminal_contract_version", 2),
        "kind": ("terminal_kind", "other"), "key": ("_id", "wrong"), "actor": ("actor_id", "foreign"),
        "role": ("actor_role", "restaurant"), "op": ("client_operation_id", "other_operation_0001"),
        "restaurant": ("restaurant_id", " r1 "), "time": ("created_at", "2026-01-01T00:00:00"),
        "resolved": ("resolved_at", "2026-01-01T00:00:00+00:00"), "code": ("error_code", "INVENTED"),
        "status": ("error_status", 404), "snapshot": ("financial_snapshot", {}), "command": ("command", {}),
        "extra": ("extra", None), "order": ("order_id", "invented")}
    key, value = values[change]; row[key] = value
    with pytest.raises(CreationError) as caught:
        _validated_operation(row, operation_key(ADMIN["id"], OP), ADMIN, CONTEXT)
    assert caught.value.code == "OPERATION_INVALID"
    assert service.executions == []


def test_all_aliases_actual_router_and_legacy_guard(application):
    db = application[1]; command = run(confirmed(db)); body = command.model_dump(mode="json")
    assert http(application, "/create", "POST", body).status_code == 201
    assert http(application, f"/create/{OP}").json()["state"] == "replayed"
    assert http(application, f"/create/{OP}/resume", "POST").json()["state"] == "replayed"
    assert http(application, f"/create/{OP}/close", "POST", close_body(command).model_dump(mode="json")).json()["state"] == "replayed"
    for path, method, value in [(f"/create/{OP}", "GET", None), (f"/create/{OP}/resume", "POST", None), ("/create", "POST", body)]:
        result = http(application, path, method, value, legacy=True)
        assert result.status_code == 403 and result.json()["detail"]["code"] == "FINANCIAL_CONTEXT_REQUIRED"


def test_http_close_then_delayed_create_no_effect(application):
    db = application[1]; command = run(confirmed(db))
    result = http(application, f"/create/{OP}/close", "POST", close_body(command).model_dump(mode="json"))
    assert result.status_code == 409 and result.json()["error_code"] == "FINANCIAL_INTENT_CLOSED"
    assert http(application, "/create", "POST", command.model_dump(mode="json")).json() == result.json()
    assert db.orders.documents == db.audit_logs.documents == []


@pytest.mark.parametrize("actor", [RESTAURANT, DRIVER])
@pytest.mark.parametrize("path,method", [("/create", "POST"), (f"/create/{OP}", "GET"), (f"/create/{OP}/resume", "POST"), (f"/create/{OP}/close", "POST")])
def test_aliases_admin_only(application, actor, path, method):
    assert http(application, path, method, actor=actor).status_code == 403
    assert application[1].order_operations.documents == []


@pytest.mark.parametrize("case", ["bad_json", "duplicate", "too_large", "wrong_type", "no_confirmation", "query", "header", "stale_role", "disabled"])
def test_http_invalid_or_stale_has_no_terminal(application, case):
    db = application[1]; command = run(confirmed(db)); body = command.model_dump(mode="json")
    path, headers, content = "/create", {}, None
    if case == "bad_json": body, content, headers = None, "{", {"Content-Type": "application/json"}
    if case == "duplicate": body, content, headers = None, '{"x":1,"x":2}', {"Content-Type": "application/json"}
    if case == "too_large": body, content, headers = None, "x"*65537, {"Content-Type": "application/json"}
    if case == "wrong_type": headers = {"Content-Type": "text/plain"}
    if case == "no_confirmation": body.pop("quote_confirmation")
    if case == "query": path += "?unexpected=1"
    if case == "header": headers = {"X-Expected-Actor-ID": "foreign"}
    if case == "stale_role": db.users.documents[0]["role"] = "restaurant"
    if case == "disabled": db.users.documents[0]["account_disabled"] = True
    result = http(application, path, "POST", body, headers=headers, content=content)
    assert result.status_code in {403, 413, 415, 422}
    assert db.order_operations.documents == []


def test_financial_aliases_reject_historical_row_old_lookup_unchanged(application):
    db = application[1]; command = run(confirmed(db))
    data = command.model_dump(mode="python"); data.pop("quote_confirmation"); data.pop("financial")
    old = CreateOrderCommand.model_validate(data)
    row = {"_id": operation_key(ADMIN["id"], OP), "actor_id": ADMIN["id"], "actor_role": "admin",
        "restaurant_id": "r1", "client_operation_id": OP, "command": old.model_dump(mode="json"),
        "payload_digest": build_mutation_intent(ADMIN["id"], "create", None, old).payload_digest,
        "state": "applied", "order_id": "historical-order"}
    db.order_operations.documents.append(row)
    assert http(application, f"/create/{OP}", legacy=True).json()["state"] == "replayed"
    for path, method in [(f"/create/{OP}", "GET"), (f"/create/{OP}/resume", "POST")]:
        response = http(application, path, method)
        assert response.status_code == 409 and response.json()["detail"]["code"] == "FINANCIAL_PROTOCOL_REQUIRED"
