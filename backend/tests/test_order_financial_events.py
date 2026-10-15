"""L4A meaningful contract and owned-Mongo recovery/custody tests."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import uuid

from fastapi import FastAPI, HTTPException
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import ValidationError
import pytest

from models.order import Order
from models.order_financial_events import FinancialEventCommand
from models.order_mutation import AssignOrderCommand, StatusOrderCommand
from models.order_preparation_operations import PreparingOperationCommand, ReadyOperationCommand
from test_order_creation_recovery import mongo_case, ACTOR, Faults, SimulatedCrash, DatabaseProxy, COLLECTIONS
from test_order_assignment_recovery import DatabaseProxy as AssignmentDatabaseProxy
from test_order_remakes import WriteFailureDB
from test_financial_core import command as finance_command
from test_financial_core_mongo import seed, create, ADMIN, DRIVER
from utils.order_assignment import OrderAssignmentService
from utils.order_financial_events import OrderFinancialEventService, operation_key
from utils.order_preparation_operations import OrderPreparationService
from utils.order_status import OrderStatusService, StatusError
from utils.financial_activity import inspect_activity, public_activity_read
from utils.order_reads import OrderReadService, safe_order
from utils.order_revision import ensure_legacy_order


@pytest.fixture
def db():
    """Runner supplies verified owned runtime; all data synthetic and retained."""
    def run(scenario):
        async def isolated():
            import runtime
            assert runtime.PORT == 27947 and runtime.SET == "pd_l4a_20261014"
            state = json.loads(runtime.STATE.read_text(encoding="utf-8"))
            with runtime.direct() as verifier:
                runtime.verify_owned(verifier, state)
                assert verifier.admin.command("hello")["isWritablePrimary"] is True
            client = AsyncIOMotorClient(runtime.URI, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000, socketTimeoutMS=4000)
            db = client["pd_l4a_owner_" + uuid.uuid4().hex]
            try:
                for collection in (*COLLECTIONS, "drivers", "order_financial_events"):
                    await db.create_collection(collection)
                await db.users.insert_one({**ACTOR, "account_disabled": False})
                await db.restaurants.insert_one({"id": ACTOR["restaurant_id"], "name": "Synthetic Restaurant",
                    "accepting_orders": True, "closed_today": False})
                await db.counters.insert_one({"_id": "orders.global", "seq": 100})
                await db.order_operation_settings.insert_one({"_id": "order-create-v1", "enabled": True})
                await asyncio.wait_for(scenario(db), timeout=45)
            finally:
                client.close()
        return asyncio.run(isolated())
    return run


def command(event_type="advance_not_paid_declared", version=3, **changes):
    value = {"client_operation_id": "financial_declaration_0001", "expected_order_version": version,
        "event_type": event_type, "amount_bani": 3250, "declaration_id": None}
    value.update(changes)
    return FinancialEventCommand.model_validate(value)


async def accepted(db, payment="CASH", ready=False):
    await seed(db)
    await db.order_operation_settings.insert_one({"_id": "order-financial-events-v1", "enabled": True})
    order = await create(db, finance_command(payment))
    order_id = order["id"]
    await OrderPreparationService(db, "preparing").submit(order_id,
        PreparingOperationCommand(client_operation_id="l4a_preparing_0001", expected_order_version=0, preparation_time=20), ACTOR)
    await OrderAssignmentService(db).assign(order_id,
        AssignOrderCommand(client_operation_id="l4a_assignment_0001", expected_order_version=1, driver_id=DRIVER["driver_id"]), ADMIN)
    await OrderStatusService(db).status(order_id,
        StatusOrderCommand(client_operation_id="l4a_acceptance_0001", expected_order_version=2, status="ACCEPTED"), DRIVER)
    if ready:
        await OrderPreparationService(db, "ready").submit(order_id,
            ReadyOperationCommand(client_operation_id="l4a_readiness_0001", expected_order_version=3), ACTOR)
    return await db.orders.find_one({"id": order_id})


async def declare(db, order):
    result = await OrderFinancialEventService(db).submit(order["id"], command(version=order["order_version"]), DRIVER)
    assert result.result.state == "applied"
    return await db.orders.find_one({"id": order["id"]})


def approval(order, **changes):
    values = {"client_operation_id": "financial_approval_0001", "declaration_id": order["financial_activity"]["declaration_id"]}
    values.update(changes)
    return command("advance_shortfall_acknowledged", order["order_version"], **values)


async def approve(db, order):
    result = await OrderFinancialEventService(db).submit(order["id"], approval(order), ACTOR)
    assert result.result.state == "applied"
    return await db.orders.find_one({"id": order["id"]})


def pickup(order, operation="l4a_pickup_000001"):
    return StatusOrderCommand(client_operation_id=operation, expected_order_version=order["order_version"], status="PICKED_UP")


@pytest.mark.parametrize("field", ["event_type", "amount_bani", "declaration_id", "expected_order_version"])
def test_required_command_fields_never_default(field):
    value = command().model_dump(mode="json")
    del value[field]
    with pytest.raises(ValidationError):
        FinancialEventCommand.model_validate(value)


@pytest.mark.parametrize("invalid", [True, "3250", 3250.1, 0, -1, None, 100_000_001])
def test_exact_positive_bani(invalid):
    with pytest.raises(ValidationError):
        command(amount_bani=invalid)


def test_declaration_vs_approval_link_strict():
    with pytest.raises(ValidationError):
        command(declaration_id=str(uuid.uuid4()))
    with pytest.raises(ValidationError):
        command("advance_shortfall_acknowledged")
    with pytest.raises(ValidationError):
        command(event_type="advance_paid")


@mongo_case
async def test_declaration_approval_pickup_and_delivery_never_manufacture_payment(db):
    order = await accepted(db, ready=True)
    quote = deepcopy(order["financial"])
    declared = await declare(db, order)
    assert declared["financial_activity"]["status"] == "declared"
    assert declared["financial_activity"]["outstanding_bani"] is None
    blocked = await OrderStatusService(db).status(order["id"], pickup(declared, "l4a_blocked_pickup_01"), DRIVER)
    assert blocked.result.state == "rejected" and blocked.result.error_code == "FINANCIAL_PICKUP_APPROVAL_REQUIRED"
    assert (await db.orders.find_one({"id": order["id"]}))["status"] == "ACCEPTED"
    approved = await approve(db, declared)
    assert approved["financial_activity"]["status"] == "approved" and approved["financial_activity"]["outstanding_bani"] is None
    await db.order_operation_settings.update_one({"_id": "order-financial-events-v1"}, {"$set": {"enabled": False}})
    result = await OrderStatusService(db).status(order["id"], pickup(approved), DRIVER)
    assert result.result.state == "applied"
    current = await db.orders.find_one({"id": order["id"]})
    assert current["financial_activity"]["status"] == "outstanding" and current["financial_activity"]["outstanding_bani"] == 3250
    assert current["financial_activity"]["repayment_due_policy"] == "next_pickup_else_shift_end"
    assert current["financial"] == quote and all(quote[k] is None for k in ("advance_paid_bani", "refund_due_bani", "refund_paid_bani"))
    assert await db.order_financial_events.count_documents({}) == 3
    await OrderStatusService(db).status(order["id"], StatusOrderCommand(client_operation_id="l4a_delivery_0001",
        expected_order_version=current["order_version"], status="DELIVERED"), DRIVER)
    final = await db.orders.find_one({"id": order["id"]})
    assert inspect_activity(final).status == "outstanding"
    assert final["financial"] == quote
    assert Order(**final).model_dump(mode="json")["financial_activity"] == final["financial_activity"]


@mongo_case
async def test_default_off_unknown_scope_exact_approval_and_amount_fail_closed(db):
    order = await accepted(db)
    await db.order_operation_settings.update_one({"_id": "order-financial-events-v1"}, {"$set": {"enabled": False}})
    service = OrderFinancialEventService(db)
    assert await service.capabilities(DRIVER) == {"financial_event_recovery_enabled": False}
    with pytest.raises(StatusError) as denied:
        await service.submit(order["id"], command(), DRIVER)
    assert denied.value.code == "FINANCIAL_EVENT_NOT_ENABLED"
    await db.order_operation_settings.update_one({"_id": "order-financial-events-v1"}, {"$set": {"enabled": True}})
    for actor in (ACTOR, ADMIN):
        with pytest.raises(StatusError) as denied:
            await service.submit(order["id"], command(), actor)
        assert denied.value.status_code == 403
    bad = await service.submit(order["id"], command(amount_bani=3249, client_operation_id="l4a_bad_amount_0001"), DRIVER)
    assert bad.result.state == "rejected" and bad.result.error_code == "FINANCIAL_EVENT_AMOUNT_MISMATCH"
    declared = await declare(db, order)
    bad = await service.submit(order["id"], approval(declared, declaration_id=str(uuid.uuid4()), client_operation_id="l4a_bad_link_0001"), ACTOR)
    assert bad.result.state == "rejected" and bad.result.error_code == "FINANCIAL_DECLARATION_CHANGED"
    foreign = {"id": "foreign-restaurant-user", "role": "restaurant", "restaurant_id": "foreign-restaurant"}
    await db.users.insert_one(foreign)
    with pytest.raises(StatusError) as denied:
        await service.submit(order["id"], approval(declared), foreign)
    assert denied.value.status_code == 403
    assert await db.order_financial_events.count_documents({}) == 1


@pytest.mark.parametrize("payment", ["CASH", "CARD"])
@mongo_case
async def test_no_activity_normal_pickup_unchanged(db, payment):
    order = await accepted(db, payment, ready=True)
    result = await OrderStatusService(db).status(order["id"], pickup(order), DRIVER)
    assert result.result.state == "applied"
    current = await db.orders.find_one({"id": order["id"]})
    assert "financial_activity" not in current and await db.order_financial_events.count_documents({}) == 0


@mongo_case
async def test_pending_crash_restart_disable_and_lost_ack_replays_once(db):
    order = await accepted(db)
    faults = Faults()
    faults.after_admission_crash = True
    cmd = command()
    with pytest.raises(SimulatedCrash):
        await OrderFinancialEventService(DatabaseProxy(db, faults)).submit(order["id"], cmd, DRIVER)
    assert await db.order_financial_events.count_documents({}) == 0
    await db.order_operation_settings.update_one({"_id": "order-financial-events-v1"}, {"$set": {"enabled": False}})
    result = await OrderFinancialEventService(db).resume(order["id"], cmd.client_operation_id, DRIVER)
    assert result.result.state == "applied"
    assert (await OrderFinancialEventService(db).submit(order["id"], cmd, DRIVER)).result.state == "replayed"
    assert await db.order_financial_events.count_documents({}) == 1
    await db.order_operation_settings.update_one({"_id": "order-financial-events-v1"}, {"$set": {"enabled": True}})
    declared = await db.orders.find_one({"id": order["id"]})
    ack = approval(declared)
    faults = Faults()
    faults.ack_losses = 1
    result = await OrderFinancialEventService(AssignmentDatabaseProxy(db, faults)).submit(order["id"], ack, ACTOR)
    assert result.result.state in {"applied", "pending"}
    assert (await OrderFinancialEventService(db).resume(order["id"], ack.client_operation_id, ACTOR)).result.state == "replayed"
    assert await db.order_financial_events.count_documents({}) == 2


@pytest.mark.parametrize("target", [("users", "update_one", 1), ("drivers", "update_one", 1),
    ("restaurants", "update_one", 1), ("orders", "update_one", 1),
    ("order_financial_events", "insert_one", 1), ("audit_logs", "insert_one", 1), ("order_operations", "update_one", 1)])
@mongo_case
async def test_each_write_rolls_back_no_partial_evidence_then_resume(db, target):
    order = await accepted(db)
    before_audits = await db.audit_logs.count_documents({})
    result = await OrderFinancialEventService(WriteFailureDB(db, target)).submit(order["id"], command(), DRIVER)
    assert result.result.state == "pending"
    assert await db.orders.find_one({"id": order["id"]}) == order
    assert await db.order_financial_events.count_documents({}) == 0
    assert await db.audit_logs.count_documents({}) == before_audits
    assert (await OrderFinancialEventService(db).resume(order["id"], command().client_operation_id, DRIVER)).result.state == "applied"
    assert await db.order_financial_events.count_documents({}) == 1


@mongo_case
async def test_two_intents_create_only_one_declaration(db):
    order = await accepted(db)
    intents = [command(client_operation_id="l4a_racing_intent_" + str(i)) for i in range(2)]
    for cmd in intents:
        faults = Faults()
        faults.after_admission_crash = True
        with pytest.raises(SimulatedCrash):
            await OrderFinancialEventService(DatabaseProxy(db, faults)).submit(order["id"], cmd, DRIVER)
    results = await asyncio.gather(*[OrderFinancialEventService(db).resume(order["id"], cmd.client_operation_id, DRIVER) for cmd in intents])
    assert sorted(out.result.state for out in results) == ["applied", "rejected"]
    assert await db.order_financial_events.count_documents({}) == 1


@mongo_case
async def test_pickup_and_declaration_race_cannot_commit_both_without_approval(db):
    order = await accepted(db, ready=True)
    declaration = command(version=order["order_version"])
    take = pickup(order)
    for service, cmd, actor in ((OrderFinancialEventService, declaration, DRIVER), (OrderStatusService, take, DRIVER)):
        faults = Faults()
        faults.after_admission_crash = True
        with pytest.raises(SimulatedCrash):
            await service(DatabaseProxy(db, faults)).submit(order["id"], cmd, actor) if service is OrderFinancialEventService else await service(DatabaseProxy(db, faults)).status(order["id"], cmd, actor)
    results = await asyncio.gather(OrderFinancialEventService(db).resume(order["id"], declaration.client_operation_id, DRIVER),
        OrderStatusService(db).resume(order["id"], take.client_operation_id, DRIVER))
    assert sorted(out.result.state for out in results) == ["applied", "rejected"]
    final = await db.orders.find_one({"id": order["id"]})
    assert (final["status"] == "PICKED_UP") != ("financial_activity" in final)


@pytest.mark.parametrize("corrupt", ["null", "missing_marker", "wrong_driver", "bad_digest", "missing_approval_event", "corrupt_declaration_event", "foreign_approval_event"])
@mongo_case
async def test_corrupt_partial_or_missing_evidence_blocks_pickup_and_reads(db, corrupt):
    order = await accepted(db, ready=True)
    approved = await approve(db, await declare(db, order))
    activity = approved["financial_activity"]
    if corrupt == "null":
        await db.orders.update_one({"id": order["id"]}, {"$set": {"financial_activity": None}})
    elif corrupt == "missing_marker":
        await db.orders.update_one({"id": order["id"]}, {"$unset": {"financial_activity_contract_version": ""}})
    elif corrupt in {"wrong_driver", "bad_digest"}:
        change = {"financial_activity.driver_id": "foreign-driver"} if corrupt == "wrong_driver" else {"financial_activity.activity_digest": "0" * 64}
        await db.orders.update_one({"id": order["id"]}, {"$set": change})
    elif corrupt == "missing_approval_event":
        # Preserve evidence; move the event ID rather than delete a document.
        await db.order_financial_events.update_one({"_id": activity["approval_id"]}, {"$set": {"order_id": "missing-link"}})
    elif corrupt == "corrupt_declaration_event":
        await db.order_financial_events.update_one({"_id": activity["declaration_id"]}, {"$set": {"amount_bani": 1}})
    else:
        await db.order_financial_events.update_one({"_id": activity["approval_id"]}, {"$set": {"restaurant_id": "foreign-restaurant"}})
    before = await db.orders.find_one({"id": order["id"]})
    try:
        result = await OrderStatusService(db).status(order["id"], pickup(before), DRIVER)
        assert result.result.state == "rejected" and result.result.error_code == "FINANCIAL_ACTIVITY_INVALID"
    except StatusError as exc:
        assert exc.code == "FINANCIAL_ACTIVITY_INVALID"
    assert await db.orders.find_one({"id": order["id"]}) == before
    detail = await OrderReadService(db).detail(ACTOR, order["id"])
    assert detail["order"]["read_financial_activity_invalid"] is True and detail["order"]["read_actions_unavailable"] is True


@mongo_case
async def test_read_roundtrip_public_projection_and_legacy_writer_guard(db):
    order = await accepted(db)
    declared = await declare(db, order)
    detail = await OrderReadService(db).detail(ACTOR, order["id"])
    public = detail["order"]["financial_activity"]
    assert public == inspect_activity(declared).public()
    assert not {"activity_digest", "order_id", "restaurant_id", "pickup_event_id", "financial_snapshot_digest", "assigned_at", "accepted_at"} & public.keys()
    assert "read_financial_activity_invalid" not in detail["order"]
    page = await OrderReadService(db).page(ACTOR)
    assert page["items"][0]["financial_activity"] == public
    with pytest.raises(HTTPException):
        ensure_legacy_order({"id": "legacy", "financial_activity": None})
    raw = public_activity_read(declared)
    assert raw["financial_activity"] == public


@mongo_case
async def test_private_http_header_strict_bodyless_receipt(db, monkeypatch):
    import routers.order_operations as routes
    order = await accepted(db)
    monkeypatch.setattr(routes, "db", db)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[routes.get_current_user] = lambda: DRIVER
    path = f"/api/orders/operations/financial-event/{order['id']}"
    headers = {"X-Expected-Actor-ID": DRIVER["id"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test") as client:
        absent = await client.post(path, json=command().model_dump(mode="json"))
        assert absent.status_code == 409 and absent.headers["cache-control"] == "no-store"
        invalid = command().model_dump(mode="json")
        invalid["amount_bani"] = "PRIVATE_INVALID_INPUT"
        bad = await client.post(path, json=invalid, headers=headers)
        assert bad.status_code == 422 and "PRIVATE_INVALID_INPUT" not in bad.text
        out = await client.post(path, json=command().model_dump(mode="json"), headers=headers)
        assert out.status_code == 200 and out.json()["state"] == "applied"
        receipt_path = path + "/" + command().client_operation_id
        assert (await client.get(receipt_path, headers=headers)).json()["state"] == "replayed"
        assert (await client.post(receipt_path + "/resume", json={}, headers=headers)).status_code == 422
        assert (await client.post(receipt_path + "/resume", headers=headers)).json()["state"] == "replayed"


@mongo_case
async def test_stale_cas_intent_is_terminal_durable_and_dismissable(db):
    order = await accepted(db)
    stale = command(version=2, client_operation_id="l4a_stale_version_0001")
    service = OrderFinancialEventService(db)
    result = await service.submit(order["id"], stale, DRIVER)
    assert result.result.state == "rejected" and result.result.error_code == "ORDER_VERSION_CONFLICT"
    for followup in (service.lookup, service.resume):
        outcome = await followup(order["id"], stale.client_operation_id, DRIVER)
        assert outcome.result.state == "rejected" and outcome.result.error_code == "ORDER_VERSION_CONFLICT"
    assert (await service.submit(order["id"], stale, DRIVER)).result.error_code == "ORDER_VERSION_CONFLICT"
    assert await db.order_financial_events.count_documents({}) == 0 and await db.orders.find_one({"id": order["id"]}) == order


@mongo_case
async def test_stored_read_hint_cannot_suppress_pickup_gate(db):
    order = await accepted(db, ready=True)
    declared = await declare(db, order)
    await db.orders.update_one({"id": order["id"]}, {"$set": {"_read_has_financial_activity": False}})
    hinted = await db.orders.find_one({"id": order["id"]})
    assert inspect_activity(hinted).status == "declared"
    assert public_activity_read(hinted)["financial_activity"]["status"] == "declared"
    result = await OrderStatusService(db).status(order["id"], pickup(hinted), DRIVER)
    assert result.result.state == "rejected" and result.result.error_code == "FINANCIAL_PICKUP_APPROVAL_REQUIRED"
    detail = await OrderReadService(db).detail(ACTOR, order["id"])
    assert detail["order"]["financial_activity"]["status"] == "declared"


@pytest.mark.parametrize("event_role", ["declaration", "approval"])
@mongo_case
async def test_foreign_ledger_actor_even_rehashed_cannot_authorize_pickup(db, event_role):
    order = await accepted(db, ready=True)
    approved = await approve(db, await declare(db, order))
    activity = approved["financial_activity"]
    event_id = activity["declaration_id"] if event_role == "declaration" else activity["approval_id"]
    row = await db.order_financial_events.find_one({"_id": event_id})
    row["actor_id"] = "foreign-actor-rehashed"
    row["event_digest"] = sha256(json.dumps({k: v for k, v in row.items() if k not in {"_id", "event_digest"}},
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    await db.order_financial_events.replace_one({"_id": event_id}, row)
    result = await OrderStatusService(db).status(order["id"], pickup(approved), DRIVER)
    assert result.result.state == "rejected" and result.result.error_code == "FINANCIAL_ACTIVITY_INVALID"
    assert (await OrderReadService(db).detail(ACTOR, order["id"]))["order"]["read_actions_unavailable"] is True


@pytest.mark.parametrize("viewer", [DRIVER, ADMIN], ids=["own-driver", "admin"])
@pytest.mark.parametrize("ledger", ["valid", "missing", "foreign_actor_rehashed"])
@mongo_case
async def test_driver_dashboard_financial_activity_public_and_ledger_verified(db, monkeypatch, viewer, ledger):
    import routers.drivers as routes
    order = await accepted(db)
    approved = await approve(db, await declare(db, order))
    event_id = approved["financial_activity"]["approval_id"]
    if ledger == "missing":
        await db.order_financial_events.delete_one({"_id": event_id})
    elif ledger == "foreign_actor_rehashed":
        row = await db.order_financial_events.find_one({"_id": event_id})
        row["actor_id"] = "foreign-dashboard-restaurant-actor"
        row["event_digest"] = sha256(json.dumps({k: v for k, v in row.items() if k not in {"_id", "event_digest"}},
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        await db.order_financial_events.replace_one({"_id": event_id}, row)
    monkeypatch.setattr(routes, "db", db)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[routes.get_current_user] = lambda: viewer
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test") as client:
        response = await client.get(f"/api/drivers/{DRIVER['driver_id']}/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"driver", "schedules", "recent_orders", "avatars", "audit_logs"}
    assert payload["driver"]["id"] == DRIVER["driver_id"]
    assert len(payload["recent_orders"]) == 1
    public = payload["recent_orders"][0]
    assert public["id"] == order["id"] and public["financial"] == approved["financial"]
    # Existing immutable audit history remains compatible; private activity bindings do not.
    activity_json = json.dumps(public["financial_activity"])
    for private_key in ("declaration_actor_id", "approval_actor_id", "pickup_actor_id", "activity_digest",
            "financial_snapshot_digest", "operation_ref", "event_digest"):
        assert private_key not in activity_json
    if ledger == "valid":
        assert public["financial_activity"] == inspect_activity(approved).public()
        assert public["financial_activity_contract_version"] == 1
        assert "read_financial_activity_invalid" not in public
    else:
        assert public["financial_activity"] is None and public["financial_activity_contract_version"] is None
        assert public["read_financial_activity_invalid"] is True and public["read_actions_unavailable"] is True
    assert await db.orders.find_one({"id": order["id"]}) == approved


@mongo_case
async def test_driver_dashboard_financial_sanitization_preserves_own_admin_authority(db, monkeypatch):
    import routers.drivers as routes
    await accepted(db)
    monkeypatch.setattr(routes, "db", db)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[routes.get_current_user] = lambda: {**DRIVER, "driver_id": "foreign-dashboard-driver"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test") as client:
        response = await client.get(f"/api/drivers/{DRIVER['driver_id']}/dashboard")
    assert response.status_code == 403 and "financial_activity" not in response.text

