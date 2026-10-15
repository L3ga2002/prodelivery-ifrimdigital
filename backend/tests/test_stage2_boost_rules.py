"""Current-rule regressions, synthetic JWT/Mongo only; original tests untouched."""
from datetime import datetime, timedelta, timezone
import logging
from httpx import ASGITransport, AsyncClient
import pytest
from models.order_mutation import StatusOrderCommand
from test_order_creation_recovery import db, mongo_case, snapshot
from test_order_assignment_owner_guard import ForbiddenBusinessDatabase
from test_order_status_owner_guard import routes, seed as auth_seed, KEY
from utils.order_creation import OrderCreationService
from utils.order_status import OrderStatusService, StatusError

OP = "qa_boost_actor_operation_0001"
ORDER_BODY = {"restaurant_id": "r-a", "customer_name": "QA synthetic", "customer_phone": "0700000099", "customer_address": "QA address", "total_amount": 30, "source": "qa"}
ACTOR_ACTIONS = [
    ("GET", "/api/orders/operations/capabilities", None),
    ("POST", "/api/orders/operations/create", {"client_operation_id": OP, "order": ORDER_BODY}),
    ("GET", f"/api/orders/operations/create/{OP}", None),
    ("POST", f"/api/orders/operations/create/{OP}/resume", None),
    ("GET", "/api/orders/operations/edit/capabilities", None),
    ("POST", "/api/orders/operations/edit/q", {"client_operation_id": OP, "expected_order_version": 7, "changes": {"customer_name": "QA revised"}}),
    ("GET", f"/api/orders/operations/edit/q/{OP}", None),
    ("POST", f"/api/orders/operations/edit/q/{OP}/resume", None),
    ("POST", "/api/orders", ORDER_BODY),
    ("PUT", "/api/orders/q/preparing", {"preparation_time": 20}),
    ("PUT", "/api/orders/q/ready", None),
]


async def req(routes, database, users, method, path, body=None, *, cookie="a", bearer="a", expected="a", blocked=False):
    routes.auth.db = database
    routes.operations.db = routes.legacy.db = ForbiddenBusinessDatabase() if blocked else database
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
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    async with AsyncClient(transport=ASGITransport(app=routes.app), base_url="http://qa.invalid") as client:
        response = await client.request(method, path, **kwargs)
    assert not routes.app.dependency_overrides
    assert all(token not in response.text for token in tokens.values())
    return response


@pytest.mark.parametrize("method,path,body", ACTOR_ACTIONS)
@pytest.mark.parametrize("expected,code", [("a", 403), (" padded ", 422), ("bad\x7f", 422)])
@mongo_case
async def test_actor_cookie_substitution_and_malformed_header_block_business_db(db, routes, method, path, body, expected, code):
    users = await auth_seed(db, "admin")
    before = await snapshot(db)
    response = await req(routes, db, users, method, path, body, cookie="b", bearer="a", expected=expected, blocked=True)
    assert response.status_code == code
    if code == 403:
        assert response.json()["detail"]["code"] == "AUTH_CONTEXT_CHANGED"
    assert await snapshot(db) == before


@pytest.mark.parametrize("path,key,value", [("/api/orders/operations/capabilities", "create_recovery_enabled", True), ("/api/orders/operations/edit/capabilities", "edit_recovery_enabled", False)])
@pytest.mark.parametrize("expected", ["a", None])
@mongo_case
async def test_actor_header_matching_or_absent_compatible(db, routes, path, key, value, expected):
    users = await auth_seed(db, "admin")
    before = await snapshot(db)
    response = await req(routes, db, users, "GET", path, expected=expected)
    assert response.status_code == 200 and response.json()[key] is value
    assert await snapshot(db) == before


@mongo_case
async def test_driver_cannot_cancel_versioned_order_no_effect(db):
    users = await auth_seed(db, "driver")
    actor = {**users["a"], "driver_id": "d-a"}
    before = await snapshot(db)
    with pytest.raises(StatusError) as caught:
        await OrderStatusService(db).status("q", StatusOrderCommand(client_operation_id=OP, expected_order_version=7, status="CANCELLED", cancellation_reason="Synthetic reason"), actor)
    assert caught.value.status_code == 403
    assert await snapshot(db) == before


@mongo_case
async def test_driver_cannot_cancel_legacy_order_no_effect(db, routes):
    users = await auth_seed(db, "driver")
    await db.orders.update_one({"id": "q"}, {"$unset": {"order_version": ""}})
    before = await snapshot(db)
    response = await req(routes, db, users, "PUT", "/api/orders/q/status", {"status": "CANCELLED", "cancellation_reason": "Synthetic reason"})
    assert response.status_code == 403
    assert await snapshot(db) == before


@mongo_case
async def test_admin_cannot_cancel_picked_up_legacy_order_no_effect(db, routes):
    users = await auth_seed(db, "admin")
    await db.orders.update_one({"id": "q"}, {"$unset": {"order_version": ""}, "$set": {"status": "PICKED_UP"}})
    before = await snapshot(db)
    response = await req(routes, db, users, "PUT", "/api/orders/q/status", {"status": "CANCELLED", "cancellation_reason": "Synthetic reason"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CUSTODY_RESOLUTION_REQUIRED"
    assert await snapshot(db) == before


def test_accounting_close_alone_does_not_deny_new_orders(routes):
    restaurant = {"name": "Synthetic", "closed_today": True, "accepting_orders": True}
    assert OrderCreationService._restaurant_rejection(restaurant) is None
    routes.legacy._ensure_restaurant_accepts_new_orders(restaurant)


@pytest.mark.parametrize("closed", [False, True])
def test_operational_pause_still_denies_new_orders(routes, closed):
    from fastapi import HTTPException
    restaurant = {"name": "Synthetic", "closed_today": closed, "accepting_orders": False}
    assert OrderCreationService._restaurant_rejection(restaurant) is not None
    with pytest.raises(HTTPException):
        routes.legacy._ensure_restaurant_accepts_new_orders(restaurant)


def test_legacy_diagnostics_do_not_log_free_text(routes, caplog):
    sentinel = "PRIVATE_SENTINEL_ADDRESS_PHONE_TOKEN"
    with caplog.at_level(logging.INFO, logger=routes.legacy.logger.name):
        routes.legacy._log_order_action("order.status_changed", "synthetic-q", {"id": "synthetic-a", "role": "admin"}, {"status": "CANCELLED", "cancellation_reason": sentinel, "driver_name": sentinel})
    assert sentinel not in caplog.text
    assert "CANCELLED" in caplog.text


@mongo_case
async def test_legacy_audit_failure_does_not_log_raw_exception(db, routes, caplog):
    sentinel = "PRIVATE_SENTINEL_DATABASE_EXCEPTION"
    class Audit:
        async def insert_one(self, _document):
            raise RuntimeError(sentinel)
    class Database:
        audit_logs = Audit()
    routes.legacy.db = Database()
    with caplog.at_level(logging.ERROR, logger=routes.legacy.logger.name):
        await routes.legacy._record_order_audit_log("synthetic-q", "synthetic-action", {"id": "synthetic-a", "role": "admin"})
    assert sentinel not in caplog.text
    assert "RuntimeError" in caplog.text

# Historic receipts are preserved; an admitted pending command uses current policy.
import uuid
import utils.order_status as status_module
from utils.order_status import operation_key as status_key
from test_order_status_recovery import DRIVER_ACTOR, ORDER, VERSION, OP as STATUS_OP, command as status_command, seed as status_seed, receipt as status_receipt
from models.order_mutation import build_mutation_intent
from test_order_creation_recovery import ACTOR, command as create_command, receipt as create_receipt


async def historical_cancel(database, state):
    await status_seed(database)
    cmd = status_command(target="CANCELLED", reason="Synthetic old cancellation")
    operation = {"_id": status_key(DRIVER_ACTOR["id"], cmd.client_operation_id), "operation_type": "status", "contract_version": 1,
        "actor_id": DRIVER_ACTOR["id"], "actor_role": "driver", "target_order_id": ORDER,
        "actor_driver_id": DRIVER_ACTOR["driver_id"], "actor_restaurant_id": None,
        "restaurant_id": "qa-restaurant", "client_operation_id": cmd.client_operation_id,
        "payload_digest": build_mutation_intent(DRIVER_ACTOR["id"], "status", ORDER, cmd).payload_digest,
        "command": cmd.model_dump(mode="json"), "request_id": str(uuid.uuid4()), "state": state, "created_at": "2020-01-01T00:07:00+00:00"}
    operation["admission_digest"] = status_module._admission_digest(operation)
    if state == "applied":
        operation.update(order_id=ORDER, order_version=VERSION + 1, resolved_at="2020-01-01T00:08:00+00:00")
    await database.order_operations.insert_one(operation)
    return cmd


@pytest.mark.parametrize("action", ["lookup", "resume", "status"])
@mongo_case
async def test_historical_pending_cancel_current_role_denial_retains_intent(db, action):
    cmd = await historical_cancel(db, "pending")
    before = await snapshot(db)
    service = OrderStatusService(db)
    call = service.status(ORDER, cmd, DRIVER_ACTOR) if action == "status" else getattr(service, action)(ORDER, STATUS_OP, DRIVER_ACTOR)
    with pytest.raises(StatusError) as caught:
        await call
    assert caught.value.status_code == 403 and caught.value.code == "NOT_AUTHORIZED"
    assert await snapshot(db) == before


@pytest.mark.parametrize("action", ["lookup", "resume", "status"])
@mongo_case
async def test_historical_terminal_cancel_receipt_stays_readable_without_write(db, action):
    cmd = await historical_cancel(db, "applied")
    before = await snapshot(db)
    service = OrderStatusService(db)
    call = service.status(ORDER, cmd, DRIVER_ACTOR) if action == "status" else getattr(service, action)(ORDER, STATUS_OP, DRIVER_ACTOR)
    status_receipt(await call, "replayed", version=VERSION + 1)
    assert await snapshot(db) == before


@mongo_case
async def test_closed_accounting_only_real_create_and_replay(db):
    await db.restaurants.update_one({"id": ACTOR["restaurant_id"]}, {"$set": {"closed_today": True, "accepting_orders": True}})
    service = OrderCreationService(db)
    result = create_receipt(await service.create(create_command(), ACTOR), "applied", 201)
    before = await snapshot(db)
    assert (await service.lookup(create_command().client_operation_id, ACTOR)).result.order_id == result.order_id
    assert await snapshot(db) == before


@mongo_case
async def test_legacy_cancel_reason_kept_in_audit_but_absent_logs(db, routes, caplog):
    sentinel = "PRIVATE_CANCEL_SENTINEL_SYNTHETIC"
    users = await auth_seed(db, "admin")
    await db.orders.update_one({"id": "q"}, {"$unset": {"order_version": ""}})
    with caplog.at_level(logging.INFO, logger=routes.legacy.logger.name):
        response = await req(routes, db, users, "PUT", "/api/orders/q/status", {"status": "CANCELLED", "cancellation_reason": sentinel})
    assert response.status_code == 200
    order = await db.orders.find_one({"id": "q"})
    audit = await db.audit_logs.find_one({"entity_id": "q", "action": "order.status_changed"})
    assert order["cancellation_reason"] == sentinel
    assert order["audit_trail"][-1]["changes"]["cancellation_reason"] == sentinel
    assert audit["changes"]["cancellation_reason"] == sentinel
    assert sentinel not in caplog.text

@pytest.mark.parametrize('history', [False, True])
@mongo_case
async def test_creation_request_correlation_replay_and_historical_pending(db, history):
    from test_order_creation_recovery import admit_pending
    from utils.order_creation import operation_key
    cmd = create_command()
    if history:
        pending = await admit_pending(db, cmd)
        await db.order_operations.update_one({'_id': pending['_id']}, {'$unset': {'request_id': ''}})
    service = OrderCreationService(db)
    result = create_receipt(await service.create(cmd, ACTOR), 'applied', 201)
    operation = await db.order_operations.find_one({'_id': operation_key(ACTOR['id'], cmd.client_operation_id)})
    document = await db.orders.find_one({'id': result.order_id})
    audit = await db.audit_logs.find_one({'entity_id': result.order_id})
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, operation['_id'] + ':request')) if history else operation['request_id']
    assert str(uuid.UUID(expected)) == expected
    assert audit['request_id'] == document['audit_trail'][0]['request_id'] == expected
    assert audit['operation_ref'] == operation['_id'] == document['creation_operation_ref']
    assert audit['performed_by'] == operation['actor_id']
    assert audit['from_order_version'] is None and audit['to_order_version'] == result.order_version == 0
    assert audit['created_at'] == operation['resolved_at']
    before = await snapshot(db)
    create_receipt(await service.create(cmd, ACTOR), 'replayed', 200)
    assert await snapshot(db) == before

@mongo_case
async def test_creation_invalid_request_correlation_blocks_pending_without_write(db):
    from test_order_creation_recovery import admit_pending
    from utils.order_creation import CreationError
    pending = await admit_pending(db)
    await db.order_operations.update_one({'_id': pending['_id']}, {'$set': {'request_id': 'SYNTHETIC_PRIVATE_INVALID_REQUEST'}})
    before = await snapshot(db)
    with pytest.raises(CreationError) as caught:
        await OrderCreationService(db).resume(create_command().client_operation_id, ACTOR)
    assert caught.value.code == 'OPERATION_INVALID'
    assert await snapshot(db) == before