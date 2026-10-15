"""Independent S2-05A contract oracles on the parent's owned 27941 fixture.

Use run-tests.py --creation. No server lifecycle, settings, env, or live DB.
The existing creation fixture retains a unique synthetic database for each case.
"""

import asyncio
from dataclasses import is_dataclass
from datetime import datetime, timezone
import json
import re
import time

from bson.decimal128 import Decimal128
from bson.int64 import Int64
from pydantic import ValidationError
import pytest
from pymongo.errors import AutoReconnect, OperationFailure

from models.order_mutation import (
    MAX_ORDER_VERSION, MutationResult, StatusOrderCommand, build_mutation_intent,
)
from test_order_creation_recovery import (
    ASYNC_CALLS, WRITES, Faults, SimulatedCrash, await_thread_event,
    db, mongo_case, snapshot,
)
from test_order_assignment_recovery import (
    ADMIN, OTHER, ORDER, SECOND_ORDER, DRIVER, OLD_DRIVER, VERSION, PII,
    AssignmentCollectionProxy, DatabaseProxy, private_free, seed as assignment_seed,
)
from test_order_editing_recovery import ObservedCleanupSession
from utils.order_status import OrderStatusService, StatusError, operation_key
import utils.order_status as status_module


SETTINGS_ID = "order-status-v1"
OP = "qa_s205_status_operation_0001"
RESTAURANT = {"id": "qa-status-restaurant", "role": "restaurant", "restaurant_id": "qa-restaurant"}
FOREIGN_RESTAURANT = {"id": "qa-status-foreign", "role": "restaurant", "restaurant_id": "qa-foreign"}
DRIVER_ACTOR = {"id": DRIVER + "-user", "role": "driver", "driver_id": DRIVER}
FOREIGN_DRIVER = {"id": OLD_DRIVER + "-user", "role": "driver", "driver_id": OLD_DRIVER}
T0 = "2020-01-01T00:00:00+00:00"
T1 = "2020-01-01T00:01:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
MULTI_FIELDS = (
    "current_order_ids", "active_order_ids", "assigned_order_ids", "reserved_order_ids",
    "current_orders", "active_orders", "assigned_orders", "reserved_orders", "pending_order_ids",
    "order_ids", "driver_ids", "assignments", "assignment_ids", "active_assignment_ids",
    "reserved_assignment_ids", "active_assignments", "reserved_assignments", "pending_assignments",
    "current_assignment_id", "assignment_id", "assignment_version", "dispatch_version", "route_version",
    "active_count", "reserved_count",
)


def command(op=OP, version=VERSION, target="ACCEPTED", reason=None):
    return StatusOrderCommand(
        client_operation_id=op, expected_order_version=version,
        status=target, cancellation_reason=reason,
    )


async def seed(database, state="ASSIGNED", preparation="READY", **changes):
    assigned = state in {"ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED"}
    original = await assignment_seed(
        database, status=state, preparation_status=preparation,
        driver_id=DRIVER if assigned else None,
        driver_name="QA Synthetic " + DRIVER if assigned else None,
        created_at=T0, updated_at=T3, assigned_at=T3 if assigned else None,
        accepted_at=T4 if state in {"ACCEPTED", "PICKED_UP", "DELIVERED"} else None,
        picked_up_at=T5 if state in {"PICKED_UP", "DELIVERED"} else None,
        delivered_at="2020-01-01T00:06:00+00:00" if state == "DELIVERED" else None,
        cancelled_at="2020-01-01T00:06:00+00:00" if state == "CANCELLED" else None,
        preparation_time=10 if preparation != "NEW" else None,
        preparation_estimated_seconds=600 if preparation != "NEW" else None,
        preparation_started_at=T1 if preparation != "NEW" else None,
        preparation_due_at="2020-01-01T00:11:00+00:00" if preparation != "NEW" else None,
        preparation_ready_at=T2 if preparation == "READY" else None,
        preparation_actual_seconds=60 if preparation == "READY" else None,
        preparation_delay_seconds=0 if preparation == "READY" else None,
        **changes,
    )
    await database.drivers.update_one({"id": DRIVER}, {"$set": {
        "current_order_id": ORDER if assigned and state != "DELIVERED" else None,
        "driver_status": "delivery" if assigned and state != "DELIVERED" else "active",
    }})
    await database.users.insert_many([
        {**RESTAURANT, "account_disabled": False},
        {**FOREIGN_RESTAURANT, "account_disabled": False},
    ])
    await database.restaurants.insert_one({"id": "qa-foreign", "name": "QA Foreign Restaurant"})
    await database.order_operation_settings.insert_one({"_id": SETTINGS_ID, "enabled": True})
    return original


def receipt(outcome, state, status=200, *, op=OP, version=None):
    assert is_dataclass(outcome)
    assert type(outcome.result) is MutationResult
    assert outcome.status_code == status
    result = outcome.result
    assert result.state == state and result.client_operation_id == op
    data = result.model_dump(mode="json")
    assert set(data) == {
        "client_operation_id", "state", "order_id", "order_version",
        "error_code", "retry_after_seconds",
    }
    private_free(data)
    if state in {"applied", "replayed"}:
        assert result.order_id == ORDER and result.order_version == version
        assert result.error_code is None and result.retry_after_seconds is None
    elif state == "pending":
        assert result.order_id is None and result.order_version is None
        assert result.error_code is None and 1 <= result.retry_after_seconds <= 60
    else:
        assert result.order_id is None and result.order_version is None
        assert result.retry_after_seconds is None
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", result.error_code)
    return result


async def raises_status(awaitable, status, code=None):
    with pytest.raises(StatusError) as caught:
        await awaitable
    error = caught.value
    assert error.status_code == status
    if code is not None:
        assert error.code == code
    assert re.fullmatch(r"[A-Z][A-Z0-9_]*", error.code)
    assert isinstance(error.message, str) and error.message
    private_free(str(error))
    return error


async def business_snapshot(database):
    state = await snapshot(database)
    return {name: docs for name, docs in state.items() if name != "order_operations"}


async def unchanged_business(database, before, *, fenced_actor=None):
    expected = before
    if fenced_actor is not None:
        # Durable business refusal may commit the actor fence, not any business data.
        expected = {**before, "users": [
            {**user, "order_admission_revision": user.get("order_admission_revision", 0) + 1}
            if user.get("id") == fenced_actor["id"] else user
            for user in before["users"]
        ]}
    assert await business_snapshot(database) == expected


async def settle(database, outcome, *, cmd=None, actor=ADMIN):
    cmd = cmd or command()
    for _ in range(4):
        if outcome.result.state != "pending":
            return outcome
        outcome = await OrderStatusService(database).resume(ORDER, cmd.client_operation_id, actor)
    pytest.fail("Same admitted status intent remained pending after four bounded recoveries")


async def reject(database, code, *, cmd=None, actor=ADMIN, http=409):
    cmd = cmd or command()
    before = await business_snapshot(database)
    out = await settle(database, await OrderStatusService(database).status(ORDER, cmd, actor), cmd=cmd, actor=actor)
    result = receipt(out, "rejected", http, op=cmd.client_operation_id)
    assert result.error_code == code
    await unchanged_business(database, before, fenced_actor=actor)
    operation = await database.order_operations.find_one({"_id": operation_key(actor["id"], cmd.client_operation_id)})
    assert operation["state"] == "rejected" and operation["error_code"] == code
    assert operation["error_status"] == http
    terminal = await snapshot(database)
    receipt(await OrderStatusService(database).resume(ORDER, cmd.client_operation_id, actor), "rejected", http, op=cmd.client_operation_id)
    assert await snapshot(database) == terminal
    return result


async def admit_pending(database, cmd=None, actor=ADMIN):
    cmd = cmd or command()
    before = await business_snapshot(database)
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderStatusService(DatabaseProxy(database, faults)).status(ORDER, cmd, actor)
    assert faults.injections == 1
    operation = await database.order_operations.find_one({"_id": operation_key(actor["id"], cmd.client_operation_id)})
    assert operation["state"] == "pending"
    assert operation["command"] == cmd.model_dump(mode="json")
    assert operation["payload_digest"] == build_mutation_intent(actor["id"], "status", ORDER, cmd).payload_digest
    await unchanged_business(database, before)
    return operation


async def assert_effect(database, original, cmd=None, actor=ADMIN, driver_before=None):
    cmd = cmd or command()
    stored = await database.orders.find_one({"id": ORDER})
    assert type(stored["order_version"]) in (int, Int64)
    assert stored["order_version"] == cmd.expected_order_version + 1
    assert stored["status"] == cmd.status
    timestamp_field = {
        "ACCEPTED": "accepted_at", "PICKED_UP": "picked_up_at",
        "DELIVERED": "delivered_at", "CANCELLED": "cancelled_at",
    }[cmd.status]
    stamp = datetime.fromisoformat(stored[timestamp_field].replace("Z", "+00:00"))
    assert stamp.tzinfo is not None and stamp <= datetime.now(timezone.utc)
    assert stored["updated_at"] == stored[timestamp_field]
    mutable = {"order_version", "status", "updated_at", "audit_trail", timestamp_field}
    if cmd.status == "CANCELLED":
        mutable |= {"cancellation_reason", "cancelled_by"}
        assert stored["cancellation_reason"] == cmd.cancellation_reason
        assert stored["cancelled_by"] == actor["role"]
    assert {k: v for k, v in stored.items() if k not in mutable} == {
        k: v for k, v in original.items() if k not in mutable
    }, "Status mutation changed preparation, assignment history, contact, tenant or money"
    assert len(stored["audit_trail"]) == len(original["audit_trail"]) + 1
    key = operation_key(actor["id"], cmd.client_operation_id)
    audits = await database.audit_logs.find({"operation_ref": key}).to_list(10)
    assert len(audits) == 1
    audit = audits[0]
    assert audit["entity_id"] == ORDER and audit["entity_type"] == "order"
    assert audit["performed_by"] == actor["id"] and audit["performed_by_role"] == actor["role"]
    assert audit["action"].startswith("order.")
    assert audit["changes"]["from_status"] == original["status"]
    assert audit["changes"]["to_status"] == cmd.status
    assert audit["from_order_version"] == cmd.expected_order_version
    assert audit["to_order_version"] == stored["order_version"]
    assert audit["created_at"] and audit["request_id"]
    assert {k: v for k, v in audit.items() if k not in {"_id", "entity_type", "entity_id"}} == stored["audit_trail"][-1]
    private_free(audit)
    operation = await database.order_operations.find_one({"_id": key})
    assert operation["state"] == "applied" and operation["order_id"] == ORDER
    assert operation["order_version"] == cmd.expected_order_version + 1
    assert operation["command"] == cmd.model_dump(mode="json")
    driver = await database.drivers.find_one({"id": DRIVER})
    if original.get("driver_id") and cmd.status in {"CANCELLED", "DELIVERED"}:
        assert driver["current_order_id"] is None
        if driver_before and driver_before["driver_status"] != "delivery":
            assert driver["driver_status"] == driver_before["driver_status"]
        elif driver_before and (driver_before["account_disabled"] or not driver_before["is_active"]):
            assert driver["driver_status"] != "active"
        else:
            assert driver["driver_status"] == "active"
    elif original.get("driver_id"):
        assert driver["current_order_id"] == ORDER and driver["driver_status"] == "delivery"
    if driver_before:
        assert driver["total_deliveries"] == driver_before["total_deliveries"] + (cmd.status == "DELIVERED")
        expected = driver_before["total_earnings"] + (original["total_amount"] * 0.1 if cmd.status == "DELIVERED" else 0)
        assert driver["total_earnings"] == pytest.approx(expected)
        allowed = {"current_order_id", "driver_status", "total_deliveries", "total_earnings"}
        if cmd.status in {"ACCEPTED", "PICKED_UP"}:
            allowed.add("order_custody_revision")
            assert driver["order_custody_revision"] == driver_before.get("order_custody_revision", 0) + 1
        assert {k: v for k, v in driver.items() if k not in allowed} == {
            k: v for k, v in driver_before.items() if k not in allowed
        }
    assert (await database.counters.find_one({"_id": "orders.global"}))["seq"] == 100
    return stored


def test_contract_status_identity_binds_target_revision_status_and_reason():
    base = build_mutation_intent(ADMIN["id"], "status", ORDER, command())
    assert base.identity == (ADMIN["id"], "status", OP)
    for order, cmd in (
        (SECOND_ORDER, command()), (ORDER, command(version=VERSION + 1)),
        (ORDER, command(target="PICKED_UP")),
        (ORDER, command(target="CANCELLED", reason="QA reason")),
    ):
        candidate = build_mutation_intent(ADMIN["id"], "status", order, cmd)
        assert candidate.identity == base.identity and candidate.payload_digest != base.payload_digest
    from utils.order_assignment import operation_key as assign_key
    assert operation_key(ADMIN["id"], OP) != assign_key(ADMIN["id"], OP)
    assert operation_key(ADMIN["id"], OP) != operation_key(OTHER["id"], OP)
    a = command(target="CANCELLED", reason="  QA reason  ")
    b = command(target="CANCELLED", reason="QA reason")
    assert build_mutation_intent(ADMIN["id"], "status", ORDER, a) == build_mutation_intent(ADMIN["id"], "status", ORDER, b)


@pytest.mark.parametrize("version", [None, True, False, 7.0, [7], "7", -1, MAX_ORDER_VERSION + 1])
def test_contract_revision_never_coerces(version):
    with pytest.raises(ValidationError):
        command(version=version)


@pytest.mark.parametrize("target,reason", [
    ("NEW", None), ("READY", None), ("assigned", None), ("DELIVERED", "QA reason"),
    ("CANCELLED", None), ("CANCELLED", ""), ("CANCELLED", " \t "), ("CANCELLED", "x" * 501),
])
def test_contract_invalid_transition_payload_or_cancellation_reason(target, reason):
    with pytest.raises(ValidationError):
        command(target=target, reason=reason)


@pytest.mark.parametrize("state,target", [
    ("ASSIGNED", "ACCEPTED"), ("ACCEPTED", "PICKED_UP"), ("PICKED_UP", "DELIVERED"),
])
@pytest.mark.parametrize("role", ["admin", "driver"])
@mongo_case
async def test_atomic_custody_each_role_preserves_preparation_money_and_driver_history(db, state, target, role, caplog):
    original = await seed(db, state)
    actor = ADMIN if role == "admin" else DRIVER_ACTOR
    driver = await db.drivers.find_one({"id": DRIVER})
    cmd = command(target=target)
    caplog.set_level("INFO", logger="utils.order_status")
    receipt(await OrderStatusService(db).status(ORDER, cmd, actor), "applied", version=VERSION + 1)
    await assert_effect(db, original, cmd, actor, driver)
    before = await snapshot(db)
    receipt(await OrderStatusService(db).status(ORDER, cmd, actor), "replayed", version=VERSION + 1)
    assert await snapshot(db) == before
    private_free(caplog.text)


@mongo_case
async def test_sequential_advancement_replays_original_receipt_without_rewinding_or_second_credit(db):
    original = await seed(db)
    service = OrderStatusService(db)
    cmds = [command(op=OP + str(i), version=VERSION + i, target=target)
            for i, target in enumerate(("ACCEPTED", "PICKED_UP", "DELIVERED"))]
    for i, cmd in enumerate(cmds):
        before_order = await db.orders.find_one({"id": ORDER})
        driver = await db.drivers.find_one({"id": DRIVER})
        receipt(await service.status(ORDER, cmd, DRIVER_ACTOR), "applied", op=cmd.client_operation_id, version=VERSION + i + 1)
        await assert_effect(db, before_order, cmd, DRIVER_ACTOR, driver)
    before = await snapshot(db)
    for i, cmd in enumerate(cmds):
        for out in (await service.status(ORDER, cmd, DRIVER_ACTOR),
                    await service.lookup(ORDER, cmd.client_operation_id, DRIVER_ACTOR),
                    await service.resume(ORDER, cmd.client_operation_id, DRIVER_ACTOR)):
            receipt(out, "replayed", op=cmd.client_operation_id, version=VERSION + i + 1)
    assert await snapshot(db) == before
    driver = await db.drivers.find_one({"id": DRIVER})
    assert driver["total_deliveries"] == 9
    assert driver["total_earnings"] == pytest.approx(42 + original["total_amount"] * 0.1)
    assert await db.audit_logs.count_documents({}) == 3


@pytest.mark.parametrize("state", ["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED"])
@mongo_case
async def test_admin_cancel_prepickup_has_reason_history_matching_release_and_no_credit(db, state):
    original = await seed(db, state, preparation=state if state in {"NEW", "PREPARING", "READY"} else "READY")
    driver = await db.drivers.find_one({"id": DRIVER})
    cmd = command(target="CANCELLED", reason="QA customer cancellation")
    receipt(await OrderStatusService(db).status(ORDER, cmd, ADMIN), "applied", version=VERSION + 1)
    await assert_effect(db, original, cmd, ADMIN, driver)


@pytest.mark.parametrize("actor", [RESTAURANT, DRIVER_ACTOR])
@mongo_case
async def test_own_restaurant_and_driver_cancellation_allowed(db, actor):
    original = await seed(db)
    cmd = command(target="CANCELLED", reason="QA own cancellation")
    driver = await db.drivers.find_one({"id": DRIVER})
    receipt(await OrderStatusService(db).status(ORDER, cmd, actor), "applied", version=VERSION + 1)
    await assert_effect(db, original, cmd, actor, driver)


@mongo_case
async def test_real_driver_user_without_driver_id_uses_unique_driver_user_link(db):
    original = await seed(db)
    await db.users.update_one({"id": DRIVER_ACTOR["id"]}, {"$unset": {"driver_id": ""}})
    assert "driver_id" not in await db.users.find_one({"id": DRIVER_ACTOR["id"]})
    driver = await db.drivers.find_one({"id": DRIVER})
    receipt(await OrderStatusService(db).status(ORDER, command(), DRIVER_ACTOR), "applied", version=VERSION + 1)
    await assert_effect(db, original, command(), DRIVER_ACTOR, driver)


@pytest.mark.parametrize("role", [None, [], {}, 7, "unknown"])
@mongo_case
async def test_malformed_persisted_actor_role_is_403_not_typeerror_or_effect(db, role):
    await seed(db)
    await db.users.update_one({"id": ADMIN["id"]}, {"$set": {"role": role}})
    before = await snapshot(db)
    service = OrderStatusService(db)
    for action in (lambda: service.capabilities(ADMIN), lambda: service.status(ORDER, command(), ADMIN),
                   lambda: service.lookup(ORDER, OP, ADMIN), lambda: service.resume(ORDER, OP, ADMIN)):
        await raises_status(action(), 403, "NOT_AUTHORIZED")
        assert await snapshot(db) == before


@pytest.mark.parametrize("defect", ["changed_optional_id", "changed_link", "duplicate_link"])
@mongo_case
async def test_driver_identity_optional_id_and_unique_link_rechecked_after_admission(db, defect):
    await seed(db)
    await db.users.update_one({"id": DRIVER_ACTOR["id"]}, {"$unset": {"driver_id": ""}})
    await admit_pending(db, actor=DRIVER_ACTOR)
    if defect == "changed_optional_id":
        await db.users.update_one({"id": DRIVER_ACTOR["id"]}, {"$set": {"driver_id": OLD_DRIVER}})
    elif defect == "changed_link":
        await db.drivers.update_one({"id": DRIVER}, {"$set": {"user_id": FOREIGN_DRIVER["id"]}})
    else:
        await db.drivers.update_one({"id": OLD_DRIVER}, {"$set": {"user_id": DRIVER_ACTOR["id"]}})
    before = await snapshot(db)
    service = OrderStatusService(db)
    for action in (lambda: service.status(ORDER, command(), DRIVER_ACTOR),
                   lambda: service.lookup(ORDER, OP, DRIVER_ACTOR), lambda: service.resume(ORDER, OP, DRIVER_ACTOR)):
        await raises_status(action(), 403, "AUTH_CONTEXT_CHANGED")
        assert await snapshot(db) == before


@pytest.mark.parametrize("condition", ["driver_disabled", "user_disabled", "wrong_role", "break", "offline", "inactive"])
@mongo_case
async def test_admin_cancel_disabled_driver_clears_only_matching_claim_never_reactivates(db, condition):
    original = await seed(db)
    if condition == "driver_disabled":
        await db.drivers.update_one({"id": DRIVER}, {"$set": {"account_disabled": True}})
    elif condition == "user_disabled":
        await db.users.update_one({"id": DRIVER_ACTOR["id"]}, {"$set": {"account_disabled": True}})
    elif condition == "wrong_role":
        await db.users.update_one({"id": DRIVER_ACTOR["id"]}, {"$set": {"role": "restaurant"}})
    elif condition == "inactive":
        await db.drivers.update_one({"id": DRIVER}, {"$set": {"is_active": False}})
    else:
        await db.drivers.update_one({"id": DRIVER}, {"$set": {
            "driver_status": condition, "break_started_at": T3 if condition == "break" else None,
            "break_until": "2099-01-01T00:00:00+00:00" if condition == "break" else None,
        }})
    driver = await db.drivers.find_one({"id": DRIVER})
    other = await db.drivers.find_one({"id": OLD_DRIVER})
    cmd = command(target="CANCELLED", reason="QA administrator release")
    receipt(await OrderStatusService(db).status(ORDER, cmd, ADMIN), "applied", version=VERSION + 1)
    released = await db.drivers.find_one({"id": DRIVER})
    assert released["current_order_id"] is None
    assert released["driver_status"] != "active"
    assert released["is_active"] == driver["is_active"] and released["account_disabled"] == driver["account_disabled"]
    assert released["total_deliveries"] == driver["total_deliveries"] and released["total_earnings"] == driver["total_earnings"]
    assert await db.drivers.find_one({"id": OLD_DRIVER}) == other
    assert (await db.orders.find_one({"id": ORDER}))["driver_id"] == original["driver_id"]
    assert await db.audit_logs.count_documents({}) == 1


@pytest.mark.parametrize("state,target", [
    ("NEW", "ACCEPTED"), ("READY", "PICKED_UP"), ("ASSIGNED", "PICKED_UP"),
    ("ASSIGNED", "DELIVERED"), ("ACCEPTED", "DELIVERED"), ("ACCEPTED", "ACCEPTED"),
    ("PICKED_UP", "ACCEPTED"), ("DELIVERED", "ACCEPTED"), ("CANCELLED", "ACCEPTED"),
])
@mongo_case
async def test_invalid_jump_terminal_or_new_operation_same_status_is_durable_refusal(db, state, target):
    await seed(db, state)
    await reject(db, "STATUS_TRANSITION_INVALID", cmd=command(target=target))


@pytest.mark.parametrize("state", ["PICKED_UP", "DELIVERED"])
@mongo_case
async def test_postpickup_cancel_requires_explicit_custody_resolution_not_release(db, state):
    await seed(db, state)
    await reject(db, "CUSTODY_RESOLUTION_REQUIRED", cmd=command(target="CANCELLED", reason="QA late cancellation"))


@pytest.mark.parametrize("preparation", ["NEW", "PREPARING"])
@mongo_case
async def test_pickup_requires_ready_even_when_timer_elapsed(db, preparation):
    await seed(db, "ACCEPTED", preparation)
    await reject(db, "ORDER_NOT_READY", cmd=command(target="PICKED_UP"))


@pytest.mark.parametrize("actor,target", [
    (RESTAURANT, "ACCEPTED"), (RESTAURANT, "PICKED_UP"), (RESTAURANT, "DELIVERED"),
    (FOREIGN_RESTAURANT, "CANCELLED"), (FOREIGN_DRIVER, "ACCEPTED"),
    (FOREIGN_DRIVER, "CANCELLED"),
])
@mongo_case
async def test_crossowner_or_restaurant_non_cancel_403_before_any_new_ledger(db, actor, target):
    await seed(db)
    before = await snapshot(db)
    cmd = command(target=target, reason="QA reason" if target == "CANCELLED" else None)
    await raises_status(OrderStatusService(db).status(ORDER, cmd, actor), 403, "NOT_AUTHORIZED")
    assert await snapshot(db) == before


@pytest.mark.parametrize("context", ["role", "restaurant_tenant", "driver_link", "deleted", "disabled"])
@pytest.mark.parametrize("terminal", [False, True])
@mongo_case
async def test_actor_context_change_blocks_durable_recovery_and_replay_without_effect(db, context, terminal):
    await seed(db)
    actor = RESTAURANT if context == "restaurant_tenant" else DRIVER_ACTOR if context == "driver_link" else ADMIN
    cmd = command(target="CANCELLED", reason="QA actor cancellation") if actor == RESTAURANT else command()
    if terminal:
        receipt(await OrderStatusService(db).status(ORDER, cmd, actor), "applied", version=VERSION + 1)
    else:
        await admit_pending(db, cmd, actor)
    if context == "deleted":
        await db.users.delete_one({"id": actor["id"]})
    else:
        change = {"role": "restaurant"} if context == "role" else {
            "restaurant_id": "qa-foreign"} if context == "restaurant_tenant" else {
            "driver_id": OLD_DRIVER} if context == "driver_link" else {"account_disabled": True}
        await db.users.update_one({"id": actor["id"]}, {"$set": change})
    before = await snapshot(db)
    service = OrderStatusService(db)
    for action in (lambda: service.status(ORDER, cmd, actor), lambda: service.lookup(ORDER, OP, actor),
                   lambda: service.resume(ORDER, OP, actor)):
        await raises_status(action(), 401 if context == "deleted" else 403)
        assert await snapshot(db) == before


@pytest.mark.parametrize("role", ["restaurant", "driver"])
@mongo_case
async def test_order_ownership_change_after_admission_denies_recovery(db, role):
    await seed(db)
    actor = RESTAURANT if role == "restaurant" else DRIVER_ACTOR
    cmd = command(target="CANCELLED", reason="QA owned cancellation") if role == "restaurant" else command()
    await admit_pending(db, cmd, actor)
    await db.orders.update_one({"id": ORDER}, {"$set": {
        "restaurant_id": "qa-foreign"} if role == "restaurant" else {"driver_id": OLD_DRIVER}})
    before = await snapshot(db)
    for action in ("lookup", "resume"):
        await raises_status(getattr(OrderStatusService(db), action)(ORDER, OP, actor), 403, "NOT_AUTHORIZED")
        assert await snapshot(db) == before


@pytest.mark.parametrize("change", [{"role": "restaurant"}, {"account_disabled": True}])
@mongo_case
async def test_actor_revocation_after_transaction_snapshot_cannot_commit(db, change):
    await seed(db)
    faults = Faults()

    async def revoke(name, result):
        if name == "users" and result and result.get("id") == ADMIN["id"] and not faults.injections:
            faults.injections += 1
            await db.users.update_one({"id": ADMIN["id"]}, {"$set": change})
    faults.after_read = revoke
    original = await db.orders.find_one({"id": ORDER})
    driver = await db.drivers.find_one({"id": DRIVER})
    await raises_status(OrderStatusService(DatabaseProxy(db, faults)).status(ORDER, command(), ADMIN), 403)
    assert faults.injections == 1
    assert await db.orders.find_one({"id": ORDER}) == original
    assert await db.drivers.find_one({"id": DRIVER}) == driver
    assert await db.audit_logs.count_documents({}) == 0
    assert (await db.order_operations.find_one({}))["state"] == "pending"


@pytest.mark.parametrize("revision", [None, True, False, 7.0, [7], "7", -1, Decimal128(str(MAX_ORDER_VERSION + 1))])
@mongo_case
async def test_malformed_stored_revision_never_promoted(db, revision):
    await seed(db)
    await db.orders.update_one({"id": ORDER}, {"$set": {"order_version": revision}})
    await reject(db, "ORDER_VERSION_INVALID")


@mongo_case
async def test_missing_revision_is_legacy_not_receipt_zero(db):
    await seed(db)
    await db.orders.update_one({"id": ORDER}, {"$unset": {"order_version": ""}})
    await reject(db, "ORDER_VERSION_REQUIRED", cmd=command(version=0))
    assert "order_version" not in await db.orders.find_one({"id": ORDER})


@mongo_case
async def test_last_int64_revision_advances_once_then_exhausts(db):
    await seed(db)
    await db.orders.update_one({"id": ORDER}, {"$set": {"order_version": Int64(MAX_ORDER_VERSION - 1)}})
    cmd = command(version=MAX_ORDER_VERSION - 1)
    receipt(await OrderStatusService(db).status(ORDER, cmd, ADMIN), "applied", version=MAX_ORDER_VERSION)
    await reject(db, "ORDER_VERSION_EXHAUSTED", cmd=command(op=OP + "last", version=MAX_ORDER_VERSION, target="PICKED_UP"))


@mongo_case
async def test_order_not_found_is_durable_404_not_made_up_order(db):
    await seed(db)
    await db.orders.delete_one({"id": ORDER})
    await reject(db, "ORDER_NOT_FOUND", http=404)


@mongo_case
async def test_stale_version_is_durable_even_after_external_restore(db):
    await seed(db)
    cmd = command(version=VERSION - 1)
    await reject(db, "ORDER_VERSION_CONFLICT", cmd=cmd)
    await db.orders.update_one({"id": ORDER}, {"$set": {"order_version": VERSION - 1}})
    before = await snapshot(db)
    receipt(await OrderStatusService(db).status(ORDER, cmd, ADMIN), "rejected", 409)
    assert await snapshot(db) == before


@pytest.mark.parametrize("change", [
    {"status": None}, {"status": ["ASSIGNED"]}, {"status": "unknown"},
    {"preparation_status": True}, {"preparation_status": "unknown"},
    {"audit_trail": {}}, {"audit_trail": [None]}, {"restaurant_id": None},
    {"assigned_at": "2020-01-01"}, {"assigned_at": "2020-01-01T00:03:00"},
    {"assigned_at": True}, {"assigned_at": "2099-01-01T00:03:00+00:00"},
    {"accepted_at": T4}, {"picked_up_at": T5}, {"delivered_at": T5}, {"cancelled_at": T5},
    {"preparation_time": True}, {"preparation_due_at": "not-a-date"},
])
@mongo_case
async def test_malformed_order_state_preparation_or_residual_custody_is_refused(db, change):
    await seed(db)
    await db.orders.update_one({"id": ORDER}, {"$set": change})
    await reject(db, "ORDER_DATA_INVALID")


@pytest.mark.parametrize("change", [
    {"accepted_at": None}, {"accepted_at": T2}, {"accepted_at": "2020-01-01T00:04:00"},
    {"accepted_at": "2099-01-01T00:04:00+00:00"},
    {"picked_up_at": T3}, {"picked_up_at": None}, {"picked_up_at": "2020-01-01T00:05:00"},
    {"picked_up_at": "2099-01-01T00:05:00+00:00"},
])
@mongo_case
async def test_delivery_custody_timestamps_must_be_aware_sequential_nonfuture(db, change):
    await seed(db, "PICKED_UP")
    await db.orders.update_one({"id": ORDER}, {"$set": change})
    await reject(db, "ORDER_DATA_INVALID", cmd=command(target="DELIVERED"))


@pytest.mark.parametrize("field", ["total_amount", "subtotal_amount", "delivery_fee"])
@pytest.mark.parametrize("value", [None, True, -1, "25.00", [], float("inf"), float("nan")])
@mongo_case
async def test_delivery_refuses_malformed_finances_without_credit_or_release(db, field, value):
    await seed(db, "PICKED_UP")
    await db.orders.update_one({"id": ORDER}, {"$set": {field: value}})
    # NaN is compared through canonical BSON bytes in this one assertion path.
    from bson import BSON
    before_order = BSON.encode(await db.orders.find_one({"id": ORDER}))
    before_driver = await db.drivers.find_one({"id": DRIVER})
    out = await settle(db, await OrderStatusService(db).status(ORDER, command(target="DELIVERED"), ADMIN), cmd=command(target="DELIVERED"))
    assert receipt(out, "rejected", 409).error_code == "ORDER_DATA_INVALID"
    assert BSON.encode(await db.orders.find_one({"id": ORDER})) == before_order
    assert await db.drivers.find_one({"id": DRIVER}) == before_driver
    assert await db.audit_logs.count_documents({}) == 0


@pytest.mark.parametrize("missing", ["subtotal_amount", "delivery_fee", "both"])
@mongo_case
async def test_absent_optional_financial_fields_keep_real_schema_formula_compatibility(db, missing):
    await seed(db, "PICKED_UP")
    fields = ("subtotal_amount", "delivery_fee") if missing == "both" else (missing,)
    await db.orders.update_one({"id": ORDER}, {"$unset": {field: "" for field in fields}})
    original = await db.orders.find_one({"id": ORDER})
    driver = await db.drivers.find_one({"id": DRIVER})
    cmd = command(target="DELIVERED")
    receipt(await OrderStatusService(db).status(ORDER, cmd, ADMIN), "applied", version=VERSION + 1)
    await assert_effect(db, original, cmd, ADMIN, driver)


@mongo_case
async def test_missing_required_total_amount_refused_without_default_zero_credit(db):
    await seed(db, "PICKED_UP")
    await db.orders.update_one({"id": ORDER}, {"$unset": {"total_amount": ""}})
    await reject(db, "ORDER_DATA_INVALID", cmd=command(target="DELIVERED"))


@pytest.mark.parametrize("field", ["total_deliveries", "total_earnings"])
@pytest.mark.parametrize("value", [None, True, -1, "8", [], float("inf"), float("nan")])
@mongo_case
async def test_delivery_refuses_malformed_driver_accounting(db, field, value):
    await seed(db, "PICKED_UP")
    await db.drivers.update_one({"id": DRIVER}, {"$set": {field: value}})
    from bson import BSON
    before_driver = BSON.encode(await db.drivers.find_one({"id": DRIVER}))
    before_order = await db.orders.find_one({"id": ORDER})
    out = await settle(db, await OrderStatusService(db).status(ORDER, command(target="DELIVERED"), ADMIN), cmd=command(target="DELIVERED"))
    assert receipt(out, "rejected", 409).error_code == "DRIVER_DATA_INVALID"
    assert BSON.encode(await db.drivers.find_one({"id": DRIVER})) == before_driver
    assert await db.orders.find_one({"id": ORDER}) == before_order
    assert await db.audit_logs.count_documents({}) == 0


@pytest.mark.parametrize("location", ["orders", "drivers"])
@pytest.mark.parametrize("field", MULTI_FIELDS)
@mongo_case
async def test_presence_of_any_multiclaim_representation_is_refused_even_empty(db, location, field):
    await seed(db)
    await db[location].update_one({"id": ORDER if location == "orders" else DRIVER}, {"$set": {field: []}})
    await reject(db, "ASSIGNMENT_REPRESENTATION_UNSUPPORTED")


@pytest.mark.parametrize("defect", ["missing_driver", "missing_user", "wrong_user_role", "claim_empty", "claim_foreign", "second_claim", "second_order"])
@mongo_case
async def test_assignment_must_be_singular_bidirectional_and_linked(db, defect):
    original = await seed(db)
    if defect == "missing_driver":
        await db.drivers.delete_one({"id": DRIVER})
    elif defect == "missing_user":
        await db.users.delete_one({"id": DRIVER_ACTOR["id"]})
    elif defect == "wrong_user_role":
        await db.users.update_one({"id": DRIVER_ACTOR["id"]}, {"$set": {"role": "restaurant"}})
    elif defect.startswith("claim_"):
        await db.drivers.update_one({"id": DRIVER}, {"$set": {"current_order_id": None if defect == "claim_empty" else SECOND_ORDER}})
    elif defect == "second_claim":
        await db.drivers.update_one({"id": OLD_DRIVER}, {"$set": {"current_order_id": ORDER, "driver_status": "delivery"}})
    else:
        second = {k: v for k, v in original.items() if k != "_id"}
        second.update(id=SECOND_ORDER, order_number="QA.205.2")
        await db.orders.insert_one(second)
    await reject(db, "DRIVER_DATA_INVALID" if defect in {"wrong_user_role", "missing_user"} else "ASSIGNMENT_INCONSISTENT")


@pytest.mark.parametrize("location", ["drivers", "users"])
@pytest.mark.parametrize("state,target", [
    ("ASSIGNED", "ACCEPTED"), ("ACCEPTED", "PICKED_UP"), ("PICKED_UP", "DELIVERED"),
])
@mongo_case
async def test_disabled_assigned_driver_cannot_accept_pickup_or_delivery(db, location, state, target):
    await seed(db, state)
    await db[location].update_one({"id": DRIVER if location == "drivers" else DRIVER_ACTOR["id"]}, {"$set": {"account_disabled": True}})
    await reject(db, "DRIVER_DISABLED", cmd=command(target=target))


@pytest.mark.parametrize("terminal", [False, True])
@mongo_case
async def test_same_id_changed_status_reason_revision_or_target_conflicts_without_writes(db, terminal):
    await seed(db)
    if terminal:
        receipt(await OrderStatusService(db).status(ORDER, command(), ADMIN), "applied", version=VERSION + 1)
    else:
        await admit_pending(db)
    before = await snapshot(db)
    service = OrderStatusService(db)
    for order, cmd in ((ORDER, command(target="PICKED_UP")), (ORDER, command(version=VERSION + 1)),
                       (ORDER, command(target="CANCELLED", reason="QA changed reason")), (SECOND_ORDER, command())):
        await raises_status(service.status(order, cmd, ADMIN), 409, "INTENT_CONFLICT")
        assert await snapshot(db) == before


@mongo_case
async def test_lookup_actor_target_scoped_readonly_resume_never_admits(db):
    await seed(db)
    await admit_pending(db)
    before = await snapshot(db)
    faults = Faults()
    faults.read_only = True
    receipt(await OrderStatusService(DatabaseProxy(db, faults)).lookup(ORDER, OP, ADMIN), "pending", 202)
    for method, order, op, actor in (
        ("lookup", ORDER, OP, OTHER), ("resume", ORDER, OP, OTHER),
        ("lookup", SECOND_ORDER, OP, ADMIN), ("resume", SECOND_ORDER, OP, ADMIN),
        ("resume", ORDER, OP + "absent", ADMIN),
    ):
        await raises_status(getattr(OrderStatusService(db), method)(order, op, actor), 404, "OPERATION_NOT_FOUND")
    assert await snapshot(db) == before


@pytest.mark.parametrize("enabled", [None, False, 1, "true"])
@mongo_case
async def test_default_deny_separate_marker_never_provisions_or_admits(db, enabled):
    await seed(db)
    if enabled is None:
        await db.order_operation_settings.delete_one({"_id": SETTINGS_ID})
    else:
        await db.order_operation_settings.update_one({"_id": SETTINGS_ID}, {"$set": {"enabled": enabled}})
    before = await snapshot(db)
    indexes = {name: await db[name].index_information() for name in before}
    if enabled is None or enabled is False:
        assert await OrderStatusService(db).capabilities(ADMIN) == {"status_recovery_enabled": False}
    else:
        await raises_status(OrderStatusService(db).capabilities(ADMIN), 503, "CAPABILITIES_INVALID")
    await raises_status(OrderStatusService(db).status(ORDER, command(), ADMIN), 503,
                        "STATUS_NOT_ENABLED" if enabled is None or enabled is False else "CAPABILITIES_INVALID")
    assert await snapshot(db) == before
    assert {name: await db[name].index_information() for name in before} == indexes


@mongo_case
async def test_restart_bodyless_recovery_after_disable_uses_exact_admitted_intent(db):
    original = await seed(db)
    pending = await admit_pending(db)
    await db.order_operation_settings.update_one({"_id": SETTINGS_ID}, {"$set": {"enabled": False}})
    before = await snapshot(db)
    receipt(await OrderStatusService(db).lookup(ORDER, OP, ADMIN), "pending", 202)
    assert await snapshot(db) == before
    receipt(await OrderStatusService(db).resume(ORDER, OP, ADMIN), "applied", version=VERSION + 1)
    await assert_effect(db, original)
    applied = await db.order_operations.find_one({"_id": pending["_id"]})
    for field in ("_id", "command", "payload_digest", "admission_digest", "created_at", "actor_id", "actor_role", "restaurant_id"):
        assert applied.get(field) == pending.get(field)
    await raises_status(OrderStatusService(db).status(ORDER, command(op=OP + "new", version=VERSION + 1, target="PICKED_UP"), ADMIN), 503, "STATUS_NOT_ENABLED")


@mongo_case
async def test_transaction_topology_required_without_admission_or_effect(db):
    await seed(db)
    faults = Faults()
    faults.standalone = True
    before = await snapshot(db)
    service = OrderStatusService(DatabaseProxy(db, faults))
    await raises_status(service.capabilities(ADMIN), 503, "TRANSACTIONS_REQUIRED")
    await raises_status(service.status(ORDER, command(), ADMIN), 503, "TRANSACTIONS_REQUIRED")
    assert await snapshot(db) == before and faults.sessions == 0


async def compete(database, cmds, actors):
    start_gate, snapshot_gate, readers, faults = asyncio.Event(), asyncio.Event(), set(), Faults()
    require_competing_snapshot = actors[0]["id"] != actors[1]["id"]

    async def barrier(name, result):
        task = asyncio.current_task()
        if name == "orders" and result and result.get("id") == ORDER and len(readers) < 2 and task not in readers:
            readers.add(task)
            if len(readers) == 2:
                snapshot_gate.set()
            await asyncio.wait_for(snapshot_gate.wait(), 5)
    if require_competing_snapshot:
        faults.after_read = barrier

    async def call(cmd, actor):
        await start_gate.wait()
        return await OrderStatusService(DatabaseProxy(database, faults)).status(ORDER, cmd, actor)
    tasks = [asyncio.create_task(call(cmd, actor)) for cmd, actor in zip(cmds, actors)]
    # Same-actor operations may serialize at their admission fence before order read.
    start_gate.set()
    outs = await asyncio.wait_for(asyncio.gather(*tasks), 15)
    if require_competing_snapshot:
        assert len(readers) == 2, "Both real transactions must observe the competing revision"
    outs = [await settle(database, out, cmd=cmd, actor=actor) for out, cmd, actor in zip(outs, cmds, actors)]
    assert sorted(out.result.state for out in outs) == ["applied", "rejected"]
    loser = next(out for out in outs if out.result.state == "rejected")
    assert loser.status_code == 409 and loser.result.error_code == "ORDER_VERSION_CONFLICT"
    assert await database.audit_logs.count_documents({}) == 1
    assert await database.order_operations.count_documents({}) == 2
    return next(i for i, out in enumerate(outs) if out.result.state == "applied")


@pytest.mark.parametrize("two_admins", [False, True])
@mongo_case
async def test_two_operations_or_two_admins_delivery_credits_once(db, two_admins):
    original = await seed(db, "PICKED_UP")
    driver = await db.drivers.find_one({"id": DRIVER})
    cmds = [command(op=OP + str(i), target="DELIVERED") for i in range(2)]
    actors = (ADMIN, OTHER if two_admins else ADMIN)
    winner = await compete(db, cmds, actors)
    await assert_effect(db, original, cmds[winner], actors[winner], driver)


@mongo_case
async def test_cancel_versus_pickup_cannot_lose_custody_or_clear_winning_pickup_claim(db):
    original = await seed(db, "ACCEPTED")
    driver = await db.drivers.find_one({"id": DRIVER})
    cmds = [command(op=OP + "cancel", target="CANCELLED", reason="QA racing cancellation"),
            command(op=OP + "pickup", target="PICKED_UP")]
    actors = (RESTAURANT, DRIVER_ACTOR)
    winner = await compete(db, cmds, actors)
    await assert_effect(db, original, cmds[winner], actors[winner], driver)


@mongo_case
async def test_six_duplicate_delivery_calls_share_one_receipt_audit_and_credit(db):
    original = await seed(db, "PICKED_UP")
    driver = await db.drivers.find_one({"id": DRIVER})
    cmd = command(target="DELIVERED")
    gate = asyncio.Event()

    async def call():
        await gate.wait()
        return await OrderStatusService(db).status(ORDER, cmd, DRIVER_ACTOR)
    tasks = [asyncio.create_task(call()) for _ in range(6)]
    gate.set()
    outs = await asyncio.wait_for(asyncio.gather(*tasks), 15)
    for out in outs:
        resolved = await settle(db, out, cmd=cmd, actor=DRIVER_ACTOR)
        assert resolved.result.state in {"applied", "replayed"}
        assert resolved.status_code == 200 and resolved.result.order_version == VERSION + 1
    await assert_effect(db, original, cmd, DRIVER_ACTOR, driver)
    assert await db.order_operations.count_documents({}) == 1


class BoundaryCollection(AssignmentCollectionProxy):
    def __getattr__(self, method):
        delegate = super().__getattr__(method)
        if method not in ASYNC_CALLS:
            return delegate

        async def call(*args, **kwargs):
            in_tx = kwargs.get("session") is not None
            boundary = getattr(self.faults, "boundary", None)
            if boundary == "ledger" and self.real.name == "order_operations" and method in WRITES and in_tx:
                self.faults.injections += 1
                raise OperationFailure("QA ledger refusal " + PII[3], code=121)
            result = await delegate(*args, **kwargs)
            hit = in_tx and method in WRITES and (
                boundary == "driver" and self.real.name == "drivers"
                or boundary == "order" and self.real.name == "orders"
            )
            if hit and not self.faults.injections:
                self.faults.injections += 1
                raise StatusError(409, "ASSIGNMENT_INCONSISTENT", "QA refusal after a real partial write")
            return result
        return call


class BoundaryDatabase(DatabaseProxy):
    def get_collection(self, name, *args, **kwargs):
        return BoundaryCollection(self.real.get_collection(name, *args, **kwargs), self.faults)


@pytest.mark.parametrize("boundary", ["audit", "ledger", "driver", "order"])
@mongo_case
async def test_partial_failure_rolls_back_order_audit_release_credit_and_terminal_receipt(db, boundary, caplog):
    original = await seed(db, "PICKED_UP")
    driver = await db.drivers.find_one({"id": DRIVER})
    before = await business_snapshot(db)
    faults = Faults()
    faults.boundary = boundary
    if boundary == "audit":
        faults.audit_failure = OperationFailure("QA audit refusal " + PII[3], code=121)
    caplog.set_level("INFO", logger="utils.order_status")
    cmd = command(target="DELIVERED")
    service = OrderStatusService(BoundaryDatabase(db, faults))
    if boundary in {"driver", "order"}:
        await raises_status(service.status(ORDER, cmd, ADMIN), 409, "ASSIGNMENT_INCONSISTENT")
    else:
        receipt(await service.status(ORDER, cmd, ADMIN), "pending", 202)
    assert faults.injections >= 1, "Fault injection must reach the real transaction write"
    await unchanged_business(db, before)
    assert (await db.order_operations.find_one({}))["state"] == "pending"
    private_free(caplog.text)
    receipt(await OrderStatusService(db).resume(ORDER, OP, ADMIN), "applied", version=VERSION + 1)
    await assert_effect(db, original, cmd, ADMIN, driver)


@pytest.mark.parametrize("losses", [1, 3])
@mongo_case
async def test_lost_commit_ack_retries_same_transaction_restart_replays_single_delivery_credit(db, losses):
    original = await seed(db, "PICKED_UP")
    driver = await db.drivers.find_one({"id": DRIVER})
    faults = Faults()
    faults.ack_losses = losses
    cmd = command(target="DELIVERED")
    out = await OrderStatusService(DatabaseProxy(db, faults)).status(ORDER, cmd, ADMIN)
    assert out.result.state in {"applied", "pending"}
    assert faults.injections == losses and faults.commits == (2 if losses == 1 else 3)
    assert faults.sessions == 1, "Unknown ACK must not execute another transaction body"
    receipt(await OrderStatusService(db).lookup(ORDER, OP, ADMIN), "replayed", version=VERSION + 1)
    receipt(await OrderStatusService(db).resume(ORDER, OP, ADMIN), "replayed", version=VERSION + 1)
    await assert_effect(db, original, cmd, ADMIN, driver)


class AdmissionAckCollection(AssignmentCollectionProxy):
    def __getattr__(self, method):
        delegate = super().__getattr__(method)
        if self.real.name != "order_operations" or method != "insert_one":
            return delegate

        async def call(*args, **kwargs):
            result = await delegate(*args, **kwargs)
            if kwargs.get("session") is None and not self.faults.injections:
                self.faults.injections += 1
                raise AutoReconnect("QA lost admission ACK " + PII[2])
            return result
        return call


class AdmissionAckDatabase(DatabaseProxy):
    def get_collection(self, name, *args, **kwargs):
        return AdmissionAckCollection(self.real.get_collection(name, *args, **kwargs), self.faults)


@mongo_case
async def test_lost_admission_ack_preserves_one_intent_and_recovers(db):
    original = await seed(db)
    faults = Faults()
    out = await OrderStatusService(AdmissionAckDatabase(db, faults)).status(ORDER, command(), ADMIN)
    assert faults.injections == 1
    assert (await settle(db, out)).result.state in {"applied", "replayed"}
    await assert_effect(db, original)
    assert await db.order_operations.count_documents({}) == 1


@mongo_case
async def test_transient_retry_is_three_attempts_then_truthful_pending(db):
    await seed(db)
    before = await business_snapshot(db)
    faults = Faults()
    faults.audit_failure = OperationFailure("QA transient conflict", code=112, details={"errorLabels": ["TransientTransactionError"]})
    assert status_module.MAX_ATTEMPTS == 3 and status_module.MAX_COMMIT_ATTEMPTS == 3
    receipt(await OrderStatusService(DatabaseProxy(db, faults)).status(ORDER, command(), ADMIN), "pending", 202)
    assert faults.sessions == 3 and faults.audit_attempts == 3
    await unchanged_business(db, before)
    receipt(await OrderStatusService(db).resume(ORDER, OP, ADMIN), "applied", version=VERSION + 1)


@mongo_case
async def test_ten_second_contract_shortened_deadline_returns_pending_without_cleanup_overlap(db, monkeypatch):
    original = await seed(db)
    await admit_pending(db)
    before = await business_snapshot(db)
    assert status_module.DEADLINE_SECONDS == 10
    faults = Faults()
    faults.session_factory = ObservedCleanupSession
    faults.delay = ("order_operations", "find_one", True)
    faults.delay_release = asyncio.Event()
    monkeypatch.setattr(status_module, "DEADLINE_SECONDS", 0.2)
    started = time.monotonic()
    try:
        out = await asyncio.wait_for(OrderStatusService(DatabaseProxy(db, faults)).resume(ORDER, OP, ADMIN), 2)
        receipt(out, "pending", 202)
        assert time.monotonic() - started < 2 and faults.injections == 1 and faults.delay_active
        await unchanged_business(db, before)
    finally:
        faults.delay_release.set()
        if faults.injections:
            await await_thread_event(faults.delay_done)
            await await_thread_event(faults.cleanup_finished)
        assert not faults.cleanup_overlap
    monkeypatch.setattr(status_module, "DEADLINE_SECONDS", 10)
    receipt(await OrderStatusService(db).resume(ORDER, OP, ADMIN), "applied", version=VERSION + 1)
    await assert_effect(db, original)


@pytest.mark.parametrize("boundary", [
    ("order_operations", "find_one", True), ("drivers", "update_one", True),
    ("audit_logs", "insert_one", True), ("order_operations", "update_one", True),
])
@mongo_case
async def test_request_cancellation_never_commits_partial_delivery_or_overlaps_cleanup(db, boundary):
    await seed(db, "PICKED_UP")
    cmd = command(target="DELIVERED")
    await admit_pending(db, cmd)
    before = await business_snapshot(db)
    faults = Faults()
    faults.session_factory = ObservedCleanupSession
    faults.delay, faults.delay_release = boundary, asyncio.Event()
    task = asyncio.create_task(OrderStatusService(DatabaseProxy(db, faults)).resume(ORDER, OP, ADMIN))
    try:
        async with asyncio.timeout(3):
            while not faults.delay_active:
                assert not task.done(), "Required cancellation boundary was not reached"
                await asyncio.sleep(0.01)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert done, "Cancelled request exceeded independent bound"
        if not task.cancelled():
            receipt(task.result(), "pending", 202)
        await unchanged_business(db, before)
        assert (await db.order_operations.find_one({}))["state"] == "pending"
    finally:
        faults.delay_release.set()
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert done
        if not task.cancelled():
            task.exception()
        if faults.injections:
            await await_thread_event(faults.delay_done)
            await await_thread_event(faults.cleanup_finished)
        assert not faults.cleanup_overlap
    receipt(await OrderStatusService(db).resume(ORDER, OP, ADMIN), "applied", version=VERSION + 1)
    assert (await db.drivers.find_one({"id": DRIVER}))["total_deliveries"] == 9


@pytest.mark.parametrize("corruption", [
    {"actor_id": OTHER["id"]}, {"actor_role": "restaurant"}, {"restaurant_id": "qa-foreign"},
    {"payload_digest": "0" * 64}, {"admission_digest": "0" * 64},
    {"client_operation_id": OP + "forged"}, {"command.client_operation_id": OP + "forged"},
    {"command.expected_order_version": True}, {"command.status": "DELIVERED"},
    {"command.cancellation_reason": "QA hidden reason"}, {"target_order_id": SECOND_ORDER},
    {"operation_type": "assign"}, {"contract_version": True}, {"request_id": PII[3]},
    {"created_at": "2020-01-01"}, {"state": "unknown"},
    {"state": "applied", "order_version": None}, {"state": "applied", "order_id": {"private": PII[0]}},
    {"state": "rejected", "error_status": 200, "error_code": "ORDER_VERSION_CONFLICT"},
])
@mongo_case
async def test_corrupt_admitted_envelope_or_receipt_not_repaired_executed_or_leaked(db, corruption, caplog):
    await seed(db)
    pending = await admit_pending(db)
    await db.order_operations.update_one({"_id": pending["_id"]}, {"$set": corruption})
    before = await snapshot(db)
    caplog.set_level("INFO", logger="utils.order_status")
    service = OrderStatusService(db)
    for action in (lambda: service.status(ORDER, command(), ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN)):
        await raises_status(action(), 503, "OPERATION_INVALID")
        assert await snapshot(db) == before
    private_free(caplog.text)
