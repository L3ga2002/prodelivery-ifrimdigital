"""Preparation contract and transaction oracles on the owned synthetic fixture.

The QA runner supplies runtime ownership verification. No app settings, env file,
production connection, server lifecycle, or database cleanup is used here.
"""

import asyncio
from datetime import datetime, timezone

from bson.int64 import Int64
from pydantic import ValidationError
import pytest
from pymongo.errors import AutoReconnect

from models.order_mutation import AssignOrderCommand, StatusOrderCommand
from models.order_preparation_operations import (
    PreparingOperationCommand, ReadyOperationCommand, PreparationResult,
    RECEIPT_FIELDS, preparation_digest,
)
from test_order_creation_recovery import db, mongo_case, snapshot, Faults, SimulatedCrash
from test_order_assignment_recovery import (
    ADMIN, ORDER, DRIVER, VERSION, DatabaseProxy,
    AssignmentCollectionProxy, seed as assignment_seed,
)
from utils.order_assignment import OrderAssignmentService
from utils.order_preparation_operations import (
    OrderPreparationService, PreparationError, SETTINGS_ID, MAX_ORDER_VERSION, operation_key,
)
from utils.order_status import OrderStatusService


OP = "qa_preparation_operation_0001"
RESTAURANT = {"id": "qa-preparation-restaurant", "role": "restaurant", "restaurant_id": "qa-restaurant"}


def command(kind="preparing", *, op=OP, version=VERSION, minutes=5):
    values = {"client_operation_id": op, "expected_order_version": version}
    return (PreparingOperationCommand(**values, preparation_time=minutes) if kind == "preparing"
            else ReadyOperationCommand(**values))


async def seed(database, *, legacy=False, status="NEW", **changes):
    defaults = {"status": status, "preparation_status": "NEW", "driver_id": None,
                "driver_name": None, "assigned_at": None}
    defaults.update(changes)
    await assignment_seed(database, **defaults)
    await database.users.insert_one({**RESTAURANT, "account_disabled": False})
    await database.order_operation_settings.insert_one({"_id": SETTINGS_ID, "enabled": True})
    await database.order_operation_settings.insert_one({"_id": "order-status-v1", "enabled": True})
    if legacy:
        await database.orders.update_one({"id": ORDER}, {"$unset": {"order_version": ""}})
    return await database.orders.find_one({"id": ORDER})


async def settle(database, outcome, cmd, *, kind="preparing", actor=ADMIN):
    for _ in range(4):
        if outcome.result.state != "pending":
            return outcome
        outcome = await OrderPreparationService(database, kind).resume(ORDER, cmd.client_operation_id, actor)
    pytest.fail("Preparation remained pending after four explicit bounded recoveries")


async def apply(database, cmd=None, *, kind="preparing", actor=ADMIN):
    cmd = cmd or command(kind)
    return await settle(database, await OrderPreparationService(database, kind).submit(ORDER, cmd, actor),
                        cmd, kind=kind, actor=actor)


async def raises(awaitable, code, status):
    with pytest.raises(PreparationError) as caught:
        await awaitable
    assert (caught.value.code, caught.value.status_code) == (code, status)


async def admit(database, cmd=None, *, kind="preparing", actor=ADMIN):
    cmd = cmd or command(kind)
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderPreparationService(DatabaseProxy(database, faults), kind).submit(ORDER, cmd, actor)
    assert faults.injections == 1
    return await database.order_operations.find_one({"_id": operation_key(actor["id"], kind, cmd.client_operation_id)})


def terminal(outcome, *, kind="preparing", version=VERSION + 1, minutes=5, state="applied"):
    assert outcome.status_code == 200 and type(outcome.result) is PreparationResult
    result = outcome.result
    assert result.state == state and result.order_id == ORDER and result.order_version == version
    assert result.preparation_status == kind.upper()
    assert result.error_code is None and result.retry_after_seconds is None
    if kind == "preparing":
        assert result.preparation_time == minutes and result.preparation_estimated_seconds == minutes * 60
        started, due = map(datetime.fromisoformat, (result.preparation_started_at, result.preparation_due_at))
        assert (due - started).total_seconds() == minutes * 60
    return result.model_dump(mode="json")


@pytest.mark.parametrize("kind", ["preparing", "ready"])
@pytest.mark.parametrize("version", [None, 0, 1, Int64(7), MAX_ORDER_VERSION])
def test_contract_explicit_revision_strict_range(kind, version):
    assert command(kind, version=version).expected_order_version == version


@pytest.mark.parametrize("value", [True, False, "1", 1.0, -1, MAX_ORDER_VERSION + 1, [], {}])
def test_contract_invalid_revisions(value):
    for model in (PreparingOperationCommand, ReadyOperationCommand):
        values = {"client_operation_id": OP, "expected_order_version": value}
        if model is PreparingOperationCommand:
            values["preparation_time"] = 5
        with pytest.raises(ValidationError):
            model(**values)


@pytest.mark.parametrize("value", [True, False, "5", 5.0, 0, 241, None, [], {}])
def test_contract_invalid_minutes(value):
    with pytest.raises(ValidationError):
        command(minutes=value)


def test_contract_missing_revision_extra_fields_and_action_are_distinct():
    with pytest.raises(ValidationError):
        PreparingOperationCommand(client_operation_id=OP, preparation_time=5)
    with pytest.raises(ValidationError):
        ReadyOperationCommand(client_operation_id=OP, expected_order_version=None, preparation_time=5)
    assert operation_key("actor", "preparing", OP) == operation_key("actor", "ready", OP)
    assert preparation_digest("preparing", ORDER, command()) != preparation_digest("preparing", ORDER, command(minutes=15))
    assert preparation_digest("preparing", ORDER, command()) != preparation_digest("ready", ORDER, command("ready"))


@pytest.mark.parametrize("state", ["pending", "rejected"])
@pytest.mark.parametrize("field", RECEIPT_FIELDS)
def test_contract_uncommitted_cannot_claim_any_receipt(state, field):
    values = {"client_operation_id": OP, "state": state}
    values.update(retry_after_seconds=2) if state == "pending" else values.update(error_code="ORDER_DATA_INVALID")
    values[field] = {"order_id": ORDER, "order_version": 0, "preparation_status": "READY",
                     "preparation_time": 5, "preparation_estimated_seconds": 300,
                     "preparation_actual_seconds": 1, "preparation_delay_seconds": 0}.get(field, "2020-01-01T00:00:00+00:00")
    with pytest.raises(ValidationError):
        PreparationResult(**values)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("actor", [ADMIN, RESTAURANT])
@mongo_case
async def test_apply_ready_replay_original_receipt_and_no_reservations(db, legacy, actor):
    original = await seed(db, legacy=legacy)
    before_drivers = await db.drivers.find({}).sort("id", 1).to_list(10)
    start = command(version=None if legacy else VERSION)
    first = terminal(await apply(db, start, actor=actor), version=None if legacy else VERSION + 1)
    ready = command("ready", op=OP + "_ready", version=None if legacy else VERSION + 1)
    terminal(await apply(db, ready, kind="ready", actor=actor), kind="ready", version=None if legacy else VERSION + 2)
    current = await db.orders.find_one({"id": ORDER})
    assert current["status"] == "READY" and len(current["audit_trail"]) == len(original.get("audit_trail", [])) + 2
    assert await db.audit_logs.count_documents({"entity_id": ORDER}) == 2
    assert ("order_version" not in current) if legacy else current["order_version"] == VERSION + 2
    before = await snapshot(db)
    for outcome in (await OrderPreparationService(db).lookup(ORDER, OP, actor),
                    await OrderPreparationService(db).resume(ORDER, OP, actor),
                    await OrderPreparationService(db).submit(ORDER, start, actor)):
        recovered = terminal(outcome, version=None if legacy else VERSION + 1, state="replayed")
        assert {**recovered, "state": "applied"} == first
    assert await snapshot(db) == before
    drivers = await db.drivers.find({}).sort("id", 1).to_list(10)
    assert [{k: v for k, v in row.items() if k != "order_preparation_revision"} for row in drivers] == before_drivers
    for event in await db.audit_logs.find({"entity_id": ORDER}).to_list(5):
        embedded = next(item for item in current["audit_trail"] if item["id"] == event["id"])
        assert event == {"_id": embedded["id"], **embedded, "entity_type": "order", "entity_id": ORDER}


@mongo_case
async def test_same_identity_minutes_revision_action_target_conflict(db):
    await seed(db)
    await admit(db)
    before = await snapshot(db)
    for other in (command(minutes=15), command(version=VERSION + 1)):
        await raises(OrderPreparationService(db).submit(ORDER, other, ADMIN), "INTENT_CONFLICT", 409)
    await raises(OrderPreparationService(db, "ready").submit(ORDER, command("ready"), ADMIN), "INTENT_CONFLICT", 409)
    await raises(OrderPreparationService(db).submit("other-order", command(), ADMIN), "INTENT_CONFLICT", 409)
    for method in ("lookup", "resume"):
        await raises(getattr(OrderPreparationService(db, "ready"), method)(ORDER, OP, ADMIN), "OPERATION_NOT_FOUND", 404)
    assert await snapshot(db) == before


@mongo_case
async def test_same_intent_concurrency_and_distinct_five_vs_fifteen(db):
    await seed(db)
    results = await asyncio.gather(*(OrderPreparationService(db).submit(ORDER, command(), ADMIN) for _ in range(5)))
    for result in results:
        resolved = await settle(db, result, command())
        assert resolved.result.state in {"applied", "replayed"}
    assert await db.audit_logs.count_documents({"entity_id": ORDER}) == 1
    assert (await db.orders.find_one({"id": ORDER}))["preparation_time"] == 5
    rejected = await apply(db, command(op=OP + "new", version=VERSION + 1, minutes=15))
    assert rejected.result.state == "rejected" and rejected.result.error_code == "PREPARATION_ALREADY_STARTED"
    assert await db.audit_logs.count_documents({"entity_id": ORDER}) == 1


@mongo_case
async def test_lost_ack_restart_capability_disabled_recovery_and_read_only_lookup(db):
    await seed(db)
    faults = Faults()
    faults.ack_losses = 3
    uncertain = await OrderPreparationService(DatabaseProxy(db, faults)).submit(ORDER, command(), ADMIN)
    assert uncertain.result.state == "pending" and faults.injections == 3
    assert await db.audit_logs.count_documents({"entity_id": ORDER}) == 1
    await db.order_operation_settings.update_one({"_id": SETTINGS_ID}, {"$set": {"enabled": False}})
    readonly = Faults()
    readonly.read_only = True
    terminal(await OrderPreparationService(DatabaseProxy(db, readonly)).lookup(ORDER, OP, ADMIN), state="replayed")
    terminal(await OrderPreparationService(db).resume(ORDER, OP, ADMIN), state="replayed")
    await raises(OrderPreparationService(db).submit(ORDER, command(op=OP + "new"), ADMIN), "PREPARATION_NOT_ENABLED", 503)


@mongo_case
async def test_pending_restart_resumes_when_feature_disabled(db):
    await seed(db)
    await admit(db)
    await db.order_operation_settings.update_one({"_id": SETTINGS_ID}, {"$set": {"enabled": False}})
    result = await OrderPreparationService(db).resume(ORDER, OP, ADMIN)
    terminal(await settle(db, result, command()))


@pytest.mark.parametrize("persisted,expected,code", [
    (None, None, "ORDER_VERSION_INVALID"), (True, 1, "ORDER_VERSION_INVALID"),
    (False, 0, "ORDER_VERSION_INVALID"), (1.0, 1, "ORDER_VERSION_INVALID"),
    ("7", VERSION, "ORDER_VERSION_INVALID"), (Int64(7), None, "ORDER_VERSION_CONFLICT"),
    (Int64(8), VERSION, "ORDER_VERSION_CONFLICT"),
    (Int64(MAX_ORDER_VERSION), MAX_ORDER_VERSION, "ORDER_VERSION_EXHAUSTED"),
])
@mongo_case
async def test_revision_invalid_conflict_exhaustion_no_business_effect(db, persisted, expected, code):
    await seed(db, order_version=persisted)
    original = await db.orders.find_one({"id": ORDER})
    result = await apply(db, command(version=expected))
    assert result.result.state == "rejected" and result.result.error_code == code
    assert await db.orders.find_one({"id": ORDER}) == original
    assert await db.audit_logs.count_documents({}) == 0


@mongo_case
async def test_int64_revision_accepted_and_legacy_not_promoted(db):
    await seed(db, order_version=Int64(VERSION))
    terminal(await apply(db))


@pytest.mark.parametrize("assigned", [False, True])
@mongo_case
async def test_short_preparation_policy_and_owned_assigned_exception(db, assigned):
    changes = {"status": "ACCEPTED", "driver_id": DRIVER, "driver_name": "QA Driver", "preparation_status": "NEW"} if assigned else {}
    await seed(db, **changes)
    await db.drivers.update_many({}, {"$set": {"driver_status": "offline", "is_active": False}})
    if assigned:
        await db.drivers.update_one({"id": DRIVER}, {"$set": {"driver_status": "delivery", "is_active": True, "current_order_id": ORDER}})
        terminal(await apply(db))
        assert (await db.orders.find_one({"id": ORDER}))["status"] == "ACCEPTED"
    else:
        denied = await apply(db)
        assert denied.result.error_code == "PREPARATION_DRIVER_REQUIRED"
        terminal(await apply(db, command(op=OP + "20", minutes=20)), minutes=20)


@pytest.mark.parametrize("phase", ["PREPARING", "READY"])
@mongo_case
async def test_fresh_phase_already_applied_never_claims_receipt(db, phase):
    await seed(db, status=phase, preparation_status=phase)
    kind = "preparing" if phase == "PREPARING" else "ready"
    result = await apply(db, command(kind), kind=kind)
    assert result.result.state == "rejected"
    assert result.result.error_code == ("PREPARATION_ALREADY_STARTED" if phase == "PREPARING" else "PREPARATION_ALREADY_READY")
    assert all(getattr(result.result, name) is None for name in RECEIPT_FIELDS)


@pytest.mark.parametrize("value", ["2020-01-01 00:00:00", "2020-01-01T00:00:00Z", datetime(2020, 1, 1), datetime(2020, 1, 1, tzinfo=timezone.utc)])
@mongo_case
async def test_public_phase_precedence_and_legacy_dates(db, value):
    await seed(db, legacy=True, status="PREPARING", preparation_status="NEW", preparation_started_at=value,
               preparation_time=5, preparation_estimated_seconds=300)
    result = terminal(await apply(db, command("ready", version=None), kind="ready"), kind="ready", version=None)
    assert result["preparation_started_at"] == "2020-01-01T00:00:00+00:00"
    assert result["preparation_actual_seconds"] > 0 and result["preparation_delay_seconds"] > 0


@pytest.mark.parametrize("field,value", [("preparation_estimated_seconds", True), ("preparation_time", True),
    ("preparation_started_at", "invalid"), ("preparation_due_at", "invalid"), ("audit_trail", {})])
@mongo_case
async def test_ready_malformed_data_durable_refusal(db, field, value):
    await seed(db, status="PREPARING", preparation_status="PREPARING", **{field: value})
    original = await db.orders.find_one({"id": ORDER})
    result = await apply(db, command("ready"), kind="ready")
    assert result.result.state == "rejected" and result.result.error_code == "ORDER_DATA_INVALID"
    assert await db.orders.find_one({"id": ORDER}) == original


@pytest.mark.parametrize("field,value", [("account_disabled", True), ("restaurant_id", "different-tenant"), ("role", "driver")])
@mongo_case
async def test_actor_disabled_or_rebound_before_resume(db, field, value):
    await seed(db)
    await admit(db, actor=RESTAURANT)
    await db.users.update_one({"id": RESTAURANT["id"]}, {"$set": {field: value}})
    before = await snapshot(db)
    with pytest.raises(PreparationError) as caught:
        await OrderPreparationService(db).resume(ORDER, OP, RESTAURANT)
    assert caught.value.status_code == 403
    assert await snapshot(db) == before


@pytest.mark.parametrize("field,value", [("payload_digest", "broken"), ("command.preparation_time", 15),
    ("actor_role", "driver"), ("target_order_id", "other"), ("contract_version", True),
    ("state", "other"), ("request_id", "not-uuid"), ("receipt.order_id", ORDER)])
@mongo_case
async def test_corrupt_pending_ledger_refuses_all_recovery(db, field, value):
    await seed(db)
    operation = await admit(db)
    await db.order_operations.update_one({"_id": operation["_id"]}, {"$set": {field: value}})
    before = await snapshot(db)
    for method in ("lookup", "resume"):
        await raises(getattr(OrderPreparationService(db), method)(ORDER, OP, ADMIN), "OPERATION_INVALID", 503)
    assert await snapshot(db) == before


@mongo_case
async def test_corrupt_committed_receipt_is_never_reported_as_success(db):
    await seed(db)
    await apply(db)
    key = operation_key(ADMIN["id"], "preparing", OP)
    await db.order_operations.update_one({"_id": key}, {"$set": {"receipt.preparation_time": 15}})
    await raises(OrderPreparationService(db).lookup(ORDER, OP, ADMIN), "OPERATION_INVALID", 503)


class AfterWriteProxy(AssignmentCollectionProxy):
    def __getattr__(self, name):
        delegate = super().__getattr__(name)
        if name not in {"update_one", "find_one_and_update", "insert_one"}:
            return delegate
        async def invoke(*args, **kwargs):
            result = await delegate(*args, **kwargs)
            if kwargs.get("session") is not None and (self.real.name, name) == self.faults.after_write:
                self.faults.injections += 1
                raise AutoReconnect("QA failure after transactional write")
            return result
        return invoke


class AfterWriteDatabase(DatabaseProxy):
    def get_collection(self, name, *args, **kwargs):
        return AfterWriteProxy(self.real.get_collection(name, *args, **kwargs), self.faults)


@pytest.mark.parametrize("point", [("users", "update_one"), ("drivers", "update_one"),
    ("orders", "find_one_and_update"), ("audit_logs", "insert_one"), ("order_operations", "update_one")])
@mongo_case
async def test_fault_after_every_transaction_write_rolls_back_all_effects(db, point):
    await seed(db)
    before = await snapshot(db)
    faults = Faults()
    faults.after_write = point
    outcome = await OrderPreparationService(AfterWriteDatabase(db, faults)).submit(ORDER, command(), ADMIN)
    assert outcome.result.state == "pending" and faults.injections == 1
    after = await snapshot(db)
    assert {name: docs for name, docs in after.items() if name != "order_operations"} == {
        name: docs for name, docs in before.items() if name != "order_operations"}
    assert after["order_operations"][0]["state"] == "pending"
    terminal(await OrderPreparationService(db).resume(ORDER, OP, ADMIN))


@mongo_case
async def test_assignment_and_preparation_compete_on_revision_without_losing_assignment(db):
    await seed(db)
    prep = command()
    assignment = AssignOrderCommand(client_operation_id=OP + "assign", expected_order_version=VERSION, driver_id=DRIVER)
    result, assigned = await asyncio.gather(OrderPreparationService(db).submit(ORDER, prep, ADMIN),
        OrderAssignmentService(db).assign(ORDER, assignment, ADMIN))
    result = await settle(db, result, prep)
    for _ in range(4):
        if assigned.result.state != "pending":
            break
        assigned = await OrderAssignmentService(db).resume(ORDER, assignment.client_operation_id, ADMIN)
    assert {result.result.state, assigned.result.state} == {"applied", "rejected"}
    order = await db.orders.find_one({"id": ORDER})
    assert order["order_version"] == VERSION + 1
    assert await db.audit_logs.count_documents({"entity_id": ORDER}) == 1
    if assigned.result.state == "applied":
        assert order["driver_id"] == DRIVER and order["status"] == "ASSIGNED"
        assert (await db.drivers.find_one({"id": DRIVER}))["current_order_id"] == ORDER
    else:
        assert order["status"] == "PREPARING" and order["driver_id"] is None


@mongo_case
async def test_cancel_and_preparation_compete_without_double_effect(db):
    await seed(db)
    cancel = StatusOrderCommand(client_operation_id=OP + "cancel", expected_order_version=VERSION,
                                status="CANCELLED", cancellation_reason="QA synthetic cancellation")
    result, cancelled = await asyncio.gather(OrderPreparationService(db).submit(ORDER, command(), ADMIN),
        OrderStatusService(db).status(ORDER, cancel, ADMIN))
    result = await settle(db, result, command())
    for _ in range(4):
        if cancelled.result.state != "pending":
            break
        cancelled = await OrderStatusService(db).resume(ORDER, cancel.client_operation_id, ADMIN)
    assert {result.result.state, cancelled.result.state} == {"applied", "rejected"}
    assert (await db.orders.find_one({"id": ORDER}))["order_version"] == VERSION + 1
    assert await db.audit_logs.count_documents({"entity_id": ORDER}) == 1


@pytest.mark.parametrize("field,value", [("preparation_due_at", "2020-01-01T00:04:00+00:00"),
    ("preparation_due_at", "2019-12-31T23:59:00+00:00"), ("preparation_estimated_seconds", 301),
    ("preparation_started_at", "2020-01-01T00:00:00"), ("preparation_started_at", "2020-01-01T01:00:00+01:00")])
def test_contract_preparing_schedule_and_canonical_timestamps(field, value):
    values = {"client_operation_id": OP, "state": "applied", "order_id": ORDER, "order_version": None,
        "preparation_status": "PREPARING", "preparation_time": 5, "preparation_estimated_seconds": 300,
        "preparation_started_at": "2020-01-01T00:00:00+00:00", "preparation_due_at": "2020-01-01T00:05:00+00:00"}
    values[field] = value
    with pytest.raises(ValidationError):
        PreparationResult(**values)


@mongo_case
async def test_preparing_retains_historical_ready_metadata_under_public_new_precedence(db):
    historical = "2020-01-01T00:03:00+00:00"
    await seed(db, legacy=True, status="NEW", preparation_status="READY", preparation_ready_at=historical,
        preparation_started_at="2020-01-01T00:00:00+00:00", preparation_time=5,
        preparation_due_at="2020-01-01T00:05:00+00:00", preparation_estimated_seconds=300,
        preparation_actual_seconds=180, preparation_delay_seconds=0)
    result = terminal(await apply(db, command(version=None)), version=None)
    assert result["preparation_ready_at"] == historical and result["preparation_actual_seconds"] == 180
    order = await db.orders.find_one({"id": ORDER})
    assert order["status"] == order["preparation_status"] == "PREPARING"
    assert order["preparation_ready_at"] == historical and order["preparation_actual_seconds"] == 180


@mongo_case
async def test_legacy_ready_without_start_preserves_unknown_actual_duration(db):
    await seed(db, legacy=True, status="PREPARING", preparation_status="NEW")
    result = terminal(await apply(db, command("ready", version=None), kind="ready"), kind="ready", version=None)
    assert result["preparation_started_at"] is None and result["preparation_actual_seconds"] is None
    assert result["preparation_delay_seconds"] == 0
    assert "order_version" not in await db.orders.find_one({"id": ORDER})


@mongo_case
async def test_distinct_concurrent_five_and_fifteen_have_only_one_winner(db):
    await seed(db)
    commands = [command(op=OP + "5", minutes=5), command(op=OP + "15", minutes=15)]
    outcomes = await asyncio.gather(*(OrderPreparationService(db).submit(ORDER, cmd, ADMIN) for cmd in commands))
    outcomes = [await settle(db, outcome, cmd) for outcome, cmd in zip(outcomes, commands)]
    assert sorted(outcome.result.state for outcome in outcomes) == ["applied", "rejected"]
    winner = next(outcome.result for outcome in outcomes if outcome.result.state == "applied")
    stored = await db.orders.find_one({"id": ORDER})
    assert stored["preparation_time"] == winner.preparation_time
    assert len(stored["audit_trail"]) == 1 and await db.audit_logs.count_documents({"entity_id": ORDER}) == 1


@mongo_case
async def test_actor_disable_after_transaction_snapshot_aborts_every_effect(db):
    await seed(db)
    original = await db.orders.find_one({"id": ORDER})
    faults = Faults()
    injected = False
    async def disable(name, document):
        nonlocal injected
        if name == "users" and document and document.get("id") == ADMIN["id"] and not injected:
            injected = True
            await db.users.update_one({"id": ADMIN["id"]}, {"$set": {"account_disabled": True}})
    faults.after_read = disable
    await raises(OrderPreparationService(DatabaseProxy(db, faults)).submit(ORDER, command(), ADMIN), "ACCOUNT_DISABLED", 403)
    assert injected and await db.orders.find_one({"id": ORDER}) == original
    assert await db.audit_logs.count_documents({}) == 0
    assert (await db.order_operations.find_one({}))["state"] == "pending"


@mongo_case
async def test_available_driver_lost_after_snapshot_rejects_short_preparation(db):
    await seed(db)
    original = await db.orders.find_one({"id": ORDER})
    faults = Faults()
    injected = False
    async def offline(name, document):
        nonlocal injected
        if name == "drivers" and document and not injected:
            injected = True
            await db.drivers.update_many({}, {"$set": {"driver_status": "offline", "is_active": False}})
    faults.after_read = offline
    result = await OrderPreparationService(DatabaseProxy(db, faults)).submit(ORDER, command(), ADMIN)
    result = await settle(db, result, command())
    assert injected and result.result.error_code == "PREPARATION_DRIVER_REQUIRED"
    assert await db.orders.find_one({"id": ORDER}) == original
    assert await db.audit_logs.count_documents({}) == 0


@mongo_case
async def test_ready_then_pickup_requires_fresh_version_and_explicit_ready(db):
    await seed(db, status="ACCEPTED", preparation_status="PREPARING", driver_id=DRIVER,
        driver_name="QA Synthetic Driver", assigned_at="2020-01-01T00:00:00+00:00",
        accepted_at="2020-01-01T00:01:00+00:00", preparation_started_at="2020-01-01T00:00:00+00:00",
        preparation_due_at="2020-01-01T00:05:00+00:00", preparation_time=5, preparation_estimated_seconds=300)
    await db.drivers.update_one({"id": DRIVER}, {"$set": {"driver_status": "delivery", "current_order_id": ORDER}})
    pickup = StatusOrderCommand(client_operation_id=OP + "pickup", expected_order_version=VERSION, status="PICKED_UP")
    ready = command("ready", op=OP + "ready")
    completed, picked = await asyncio.gather(OrderPreparationService(db, "ready").submit(ORDER, ready, ADMIN),
        OrderStatusService(db).status(ORDER, pickup, ADMIN))
    completed = await settle(db, completed, ready, kind="ready")
    for _ in range(4):
        if picked.result.state != "pending":
            break
        picked = await OrderStatusService(db).resume(ORDER, pickup.client_operation_id, ADMIN)
    assert completed.result.state == "applied" and picked.result.state == "rejected"
    assert picked.result.error_code in {"ORDER_NOT_READY", "ORDER_VERSION_CONFLICT"}
    after = await db.orders.find_one({"id": ORDER})
    assert after["status"] == "ACCEPTED" and after["preparation_status"] == "READY"
    fresh = StatusOrderCommand(client_operation_id=OP + "pickup2", expected_order_version=VERSION + 1, status="PICKED_UP")
    picked = await OrderStatusService(db).status(ORDER, fresh, ADMIN)
    for _ in range(4):
        if picked.result.state != "pending":
            break
        picked = await OrderStatusService(db).resume(ORDER, fresh.client_operation_id, ADMIN)
    assert picked.result.state == "applied"
    assert (await db.orders.find_one({"id": ORDER}))["status"] == "PICKED_UP"
