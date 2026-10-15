"""F3A controlled fence races and real ASGI router with synthetic signed auth."""
import asyncio
from copy import deepcopy
import json

from httpx import ASGITransport, AsyncClient
import pytest

from models.order_remakes import RemakeCommand
from utils.order_creation import CreationError
from utils.order_remakes import OrderRemakeService, operation_key
from test_order_finance_preview import ADMIN, RESTAURANT, DRIVER, KEY, PII
from test_order_finance_preview_http import application as f1_application, token
from test_order_remake_confirmation import Database, OP, context, run, failure, confirmed, close_body, pending_service


@pytest.fixture
def application(f1_application, monkeypatch):
    app, _, auth, routes = f1_application
    db = Database()
    monkeypatch.setattr(routes, "db", db); monkeypatch.setattr(auth, "db", db)
    return app, db, auth, routes


def http(application, path, method="GET", body=None, actor=ADMIN, headers=None, content=None, legacy=False):
    app, db, auth, routes = application
    async def legacy_actor(): return actor
    app.dependency_overrides[auth.get_current_user] = legacy_actor
    values = {"Authorization": "Bearer " + token(actor), "X-Expected-Actor-ID": actor["id"]}
    values.update(headers or {})
    async def perform():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.invalid") as client:
            response = await client.request(method, "/api/orders/operations" + ("" if legacy else "/finance") + path,
                json=body, content=content, headers=values)
            assert response.headers.get("cache-control") == "no-store"
            if not path.startswith("/remake-parent/") or response.status_code != 200:
                assert all(value not in response.text for value in PII)
            return response
    return run(perform())


@pytest.mark.parametrize("actor", [ADMIN, RESTAURANT])
def test_close_draft_free_and_available_with_removed_parent_restaurant_markers_key(actor):
    db = Database(); command = run(confirmed(db, actor)); service = pending_service(db)
    for collection in [db.orders, db.restaurants, db.order_operation_settings, db.restaurant_tariff_versions]:
        collection.documents.clear()
    result = run(service.close_financial("parent", OP, close_body(command), actor, financial_context=context(actor)))
    assert result.result.error_code == "FINANCIAL_INTENT_CLOSED"
    stored = deepcopy(db.order_operations.documents[0])
    assert run(service.submit("parent", command, actor, financial_context=context(actor))).result == result.result
    assert run(service.resume("parent", OP, actor, financial_context=context(actor))).result == result.result
    assert db.order_operations.documents == [stored] and service.executions == []
    assert db.audit_logs.documents == [] and db.counters.documents[0]["seq"] == 100
    options = next(options for name, options in db.collection_options if name == "order_operations" and options)
    assert options["write_concern"].document == {"w": "majority", "wtimeout": 3000}
    assert options["read_concern"].document == {"level": "majority"}


@pytest.mark.parametrize("winner", ["close", "admission"])
def test_unique_id_linearizes_close_against_admission(winner):
    async def race():
        db = Database(); command = await confirmed(db); service = pending_service(db)
        reached, release = asyncio.Event(), asyncio.Event()
        async def barrier(name, row):
            if name == "order_operations" and row["state"] == "pending":
                reached.set(); await release.wait()
        if winner == "close":
            db.before_insert = barrier
            task = asyncio.create_task(service.submit("parent", command, ADMIN, financial_context=context(), signing_key=KEY))
            await asyncio.wait_for(reached.wait(), 1)
            closed = await service.close_financial("parent", OP, close_body(command), ADMIN, financial_context=context())
            release.set(); submitted = await task
            assert submitted.result == closed.result and submitted.result.state == "rejected"
            assert service.executions == []
        else:
            await service.submit("parent", command, ADMIN, financial_context=context(), signing_key=KEY)
            before = deepcopy(db.order_operations.documents[0])
            closed = await service.close_financial("parent", OP, close_body(command), ADMIN, financial_context=context())
            assert closed.result.state == "pending" and db.order_operations.documents == [before]
        assert len(db.order_operations.documents) == 1 and len(db.orders.documents) == 1
        assert db.audit_logs.documents == [] and db.counters.documents[0]["seq"] == 100
    run(race())


@pytest.mark.parametrize("operation", ["submit", "close"])
@pytest.mark.parametrize("written", [False, True])
def test_uncertain_write_is_pending_and_preserves_identity(operation, written):
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    db.fail_after_insert = written; db.fail_before_insert = not written
    result = run(service.submit("parent", command, ADMIN, financial_context=context(), signing_key=KEY) if operation == "submit"
        else service.close_financial("parent", OP, close_body(command), ADMIN, financial_context=context()))
    assert result.result.state == "pending" and result.result.error_code is None
    assert len(db.order_operations.documents) == int(written)
    db.fail_after_insert = db.fail_before_insert = False
    if written:
        assert run(service.lookup("parent", OP, ADMIN, financial_context=context())).result.state == ("pending" if operation == "submit" else "rejected")


@pytest.mark.parametrize("kind", ["confirmed", "terminal"])
@pytest.mark.parametrize("entry", ["submit", "lookup", "resume"])
def test_all_legacy_entries_require_verified_context_for_new_records(kind, entry):
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    if kind == "confirmed": run(service.submit("parent", command, ADMIN, financial_context=context(), signing_key=KEY))
    else: run(service.close_financial("parent", OP, close_body(command), ADMIN, financial_context=context()))
    action = service.submit("parent", command, ADMIN) if entry == "submit" else getattr(service, entry)("parent", OP, ADMIN)
    failure(action, "FINANCIAL_CONTEXT_REQUIRED")
    legacy = RemakeCommand.model_validate(command.model_dump(mode="python", exclude={"quote_confirmation"}))
    failure(service.submit("parent", legacy, ADMIN), "FINANCIAL_CONTEXT_REQUIRED")


@pytest.mark.parametrize("field,value", [("remake_terminal_contract_version", True), ("terminal_kind", "other"),
    ("actor_id", "foreign"), ("actor_role", "driver"), ("expected_order_version", True), ("error_status", True),
    ("error_code", "UNKNOWN"), ("created_at", "2026-01-01T00:00:00"), ("resolved_at", "2026-01-01T00:00:00Z"),
    ("financial_snapshot", {}), ("command", {}), ("child_order_id", "invented"), ("extra", None)])
def test_terminal_strict_dispatch_fails_closed(field, value):
    db = Database(); command = run(confirmed(db)); service = pending_service(db)
    run(service.close_financial("parent", OP, close_body(command), ADMIN, financial_context=context()))
    row = db.order_operations.documents[0]; row[field] = value
    failure(service.lookup("parent", OP, ADMIN, financial_context=context()), "OPERATION_INVALID")
    assert service.executions == []


@pytest.mark.parametrize("actor", [ADMIN, RESTAURANT])
def test_six_actual_routes_and_legacy_context_guard(application, actor):
    db = application[1]; command = run(confirmed(db, actor)); body = command.model_dump(mode="json")
    parent = http(application, "/remake-parent/parent", actor=actor)
    assert parent.status_code == 200 and parent.json()["eligibility"]["can_preview"] is True
    assert http(application, "/remake/parent", "POST", body, actor).status_code == 201
    assert http(application, f"/remake/parent/{OP}", actor=actor).json()["state"] == "replayed"
    assert http(application, f"/remake/parent/{OP}/resume", "POST", actor=actor).json()["state"] == "replayed"
    assert http(application, f"/remake/parent/{OP}/close", "POST", close_body(command).model_dump(mode="json"), actor).json()["state"] == "replayed"
    readback = http(application, f"/remake/parent/{OP}/readback", actor=actor)
    assert readback.status_code == 200 and readback.json()["kind"] == "remake_readback"
    for path, method, value in [(f"/remake/parent/{OP}", "GET", None), (f"/remake/parent/{OP}/resume", "POST", None), ("/remake/parent", "POST", body)]:
        response = http(application, path, method, value, actor, legacy=True)
        assert response.status_code == 403 and response.json()["detail"]["code"] == "FINANCIAL_CONTEXT_REQUIRED"


@pytest.mark.parametrize("case", ["bad_json", "duplicate", "size", "content_type", "confirmation", "query", "header", "role", "tenant", "disabled", "resume_body"])
def test_invalid_actual_requests_have_no_admission(application, case):
    db = application[1]; command = run(confirmed(db)); body = command.model_dump(mode="json")
    path, headers, content, actor = "/remake/parent", {}, None, ADMIN
    if case == "bad_json": body, content, headers = None, "{", {"Content-Type": "application/json"}
    if case == "duplicate": body, content, headers = None, '{"x":1,"x":2}', {"Content-Type": "application/json"}
    if case == "size": body, content, headers = None, "x"*65537, {"Content-Type": "application/json"}
    if case == "content_type": headers = {"Content-Type": "text/plain"}
    if case == "confirmation": body.pop("quote_confirmation")
    if case == "query": path += "?x=1"
    if case == "header": headers = {"X-Expected-Actor-ID": "foreign"}
    if case == "role": db.users.documents[0]["role"] = "driver"
    if case == "tenant": actor = RESTAURANT; db.users.documents[1]["restaurant_id"] = "r2"
    if case == "disabled": db.users.documents[0]["account_disabled"] = True
    if case == "resume_body": path, body = f"/remake/parent/{OP}/resume", {}
    response = http(application, path, "POST", body, actor, headers, content)
    assert response.status_code in (401, 403, 413, 415, 422)
    assert db.order_operations.documents == [] and len(db.orders.documents) == 1


@pytest.mark.parametrize("path,method", [("/remake-parent/parent", "GET"), ("/remake/parent", "POST"),
    (f"/remake/parent/{OP}", "GET"), (f"/remake/parent/{OP}/resume", "POST"),
    (f"/remake/parent/{OP}/close", "POST"), (f"/remake/parent/{OP}/readback", "GET")])
def test_driver_has_no_financial_remake_alias(application, path, method):
    assert http(application, path, method, actor=DRIVER).status_code == 403


@pytest.mark.parametrize("field", ["is_active", "account_disabled", "accepting_orders"])
@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_corrupt_restaurant_flags_are_errors(field, value):
    db = Database(); db.restaurants.documents[0][field] = value
    failure(OrderRemakeService(db).parent_context("parent", ADMIN, financial_context=context()), "RESTAURANT_INVALID")


def test_foreign_parent_is_queried_in_tenant_scope():
    db = Database(); db.orders.documents[0]["restaurant_id"] = "r2"
    failure(OrderRemakeService(db).parent_context("parent", RESTAURANT, financial_context=context(RESTAURANT)), "ORDER_NOT_FOUND")
    reads = [query for name, query, _, _, _ in db.bounds if name == "orders"]
    assert reads == [{"id": "parent", "restaurant_id": "r1"}]


def test_complete_operation_size_is_bounded_before_insert():
    db = Database(); command = run(confirmed(db)); data = command.model_dump(mode="python")
    data["items"] = [{"name": "x"*140, "quantity": 1, "unit_price_bani": 0} for _ in range(199)] + [data["items"][0]]
    command = RemakeCommand.model_validate(data)
    from models.order_finance_preview import RemakeFinancePreview
    request = RemakeFinancePreview.model_validate(command.model_dump(mode="python", exclude={"client_operation_id", "quote_confirmation"}))
    quote = run(OrderRemakeService(db).parent_context("parent", ADMIN, financial_context=context()))
    from utils.order_finance_preview import OrderFinancePreviewService
    value = run(OrderFinancePreviewService(db, signing_key=KEY).quote_remake("parent", request, ADMIN))
    command.quote_confirmation.quote_fingerprint = value["quote_fingerprint"]
    assert len(json.dumps(command.model_dump(mode="json")).encode()) < 65536
    failure(OrderRemakeService(db).submit("parent", command, ADMIN, financial_context=context(), signing_key=KEY), "REQUEST_TOO_LARGE")
    assert db.order_operations.documents == []
