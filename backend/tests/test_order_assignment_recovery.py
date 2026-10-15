"""Independent S2-04 assertions, only through the parent's owned Mongo runner.

Reuse the verified 27941 fixture; never start/stop a process, load app settings,
or connect to live data. Missing staged implementation is RED, never a skip.
"""

import asyncio
from dataclasses import FrozenInstanceError, is_dataclass
import json
import re
import time

from bson.int64 import Int64
from bson.decimal128 import Decimal128
from pydantic import ValidationError
import pytest
from pymongo.errors import AutoReconnect, OperationFailure

from models.order_mutation import (
    AssignOrderCommand, MAX_ORDER_VERSION, MutationResult, build_mutation_intent,
)
from test_order_creation_recovery import (
    ASYNC_CALLS, WRITES, CollectionProxy, DatabaseProxy as CreationDatabaseProxy,
    Faults, SimulatedCrash, await_thread_event, db, mongo_case, snapshot,
)
from test_order_editing_recovery import ObservedCleanupSession
from utils.order_assignment import (
    AssignmentError, AssignmentOutcome, BUSINESS_ERRORS, OrderAssignmentService, SETTINGS_ID,
    operation_key,
)
import utils.order_assignment as assignment_module


ADMIN = {"id": "qa-assign-admin", "role": "admin"}
OTHER = {"id": "qa-assign-other-admin", "role": "admin"}
ORDER = "qa-assign-order"
SECOND_ORDER = "qa-assign-second-order"
DRIVER = "qa-assign-driver"
OLD_DRIVER = "qa-assign-old-driver"
OP = "qa_s204_assignment_operation_0001"
VERSION = 7
PII = (
    "QA Assignment Private Customer", "0701234567",
    "QA Assignment Private Address 123", "QA Assignment Private Note",
    "44.123456", "26.654321",
)
CONTACT = {
    "customer_name": PII[0], "customer_phone": PII[1],
    "customer_address": PII[2], "notes": PII[3],
    "customer_latitude": 44.123456, "customer_longitude": 26.654321,
}


class SnapshotCursor:
    def __init__(self, real, faults, name):
        self.real, self.faults, self.name = real, faults, name

    def limit(self, count):
        self.real = self.real.limit(count)
        return self

    async def to_list(self, length=None):
        result = await self.real.to_list(length)
        if self.faults.after_read:
            for document in result:
                await self.faults.after_read(self.name, document)
        return result

    def __getattr__(self, name):
        return getattr(self.real, name)


class AssignmentCollectionProxy(CollectionProxy):
    def __getattr__(self, method):
        delegate = super().__getattr__(method)
        if method != "find":
            return delegate

        def call(*args, **kwargs):
            cursor = delegate(*args, **kwargs)
            return (SnapshotCursor(cursor, self.faults, self.real.name)
                    if kwargs.get("session") is not None else cursor)
        return call


class DatabaseProxy(CreationDatabaseProxy):
    def get_collection(self, name, *args, **kwargs):
        return AssignmentCollectionProxy(self.real.get_collection(name, *args, **kwargs), self.faults)

    def __getattr__(self, name):
        if name == "drivers":
            return self.get_collection(name)
        return super().__getattr__(name)


def command(op=OP, version=VERSION, driver=DRIVER):
    return AssignOrderCommand(
        client_operation_id=op, expected_order_version=version, driver_id=driver,
    )


def private_free(value):
    rendered = json.dumps(value, default=str)
    for sentinel in PII:
        assert sentinel not in rendered, "Customer value leaked from assignment diagnostics"


def receipt(outcome, state, status, *, order=ORDER, version=None, op=OP):
    assert type(outcome) is AssignmentOutcome and is_dataclass(outcome)
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
        assert result.order_id == order and result.order_version == version
        assert result.error_code is None and result.retry_after_seconds is None
    elif state == "pending":
        assert result.order_id is None and result.order_version is None
        assert result.error_code is None and 1 <= result.retry_after_seconds <= 60
    else:
        assert result.order_id is None and result.order_version is None
        assert result.retry_after_seconds is None
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", result.error_code)
    return result


async def raises_assignment(awaitable, status, code=None):
    with pytest.raises(AssignmentError) as error:
        await awaitable
    assert error.value.status_code == status
    if code is not None:
        assert error.value.code == code
    assert re.fullmatch(r"[A-Z][A-Z0-9_]*", error.value.code)
    assert isinstance(error.value.message, str) and error.value.message
    private_free(str(error.value))
    return error.value


async def seed(database, **overrides):
    await database.create_collection("drivers")
    await database.users.insert_many([
        {**ADMIN, "account_disabled": False}, {**OTHER, "account_disabled": False},
        {"id": DRIVER + "-user", "role": "driver", "driver_id": DRIVER, "account_disabled": False},
        {"id": OLD_DRIVER + "-user", "role": "driver", "driver_id": OLD_DRIVER, "account_disabled": False},
    ])
    await database.drivers.insert_many([
        {"id": driver, "user_id": driver + "-user", "name": "QA Synthetic " + driver,
         "phone": "0709999999", "is_active": True, "driver_status": "active",
         "account_disabled": False, "current_order_id": None,
         "break_started_at": None, "break_until": None,
         "total_deliveries": 8, "total_earnings": 42.0}
        for driver in (DRIVER, OLD_DRIVER)
    ])
    await database.order_operation_settings.insert_one({"_id": SETTINGS_ID, "enabled": True})
    await database.orders.insert_one({
        "id": ORDER, "order_number": "QA.204", "restaurant_id": "qa-restaurant",
        "restaurant_name": "QA Synthetic Restaurant", "source": "qa",
        "status": "NEW", "preparation_status": "NEW", "driver_id": None,
        "driver_name": None, "assigned_at": None, "accepted_at": None,
        "picked_up_at": None, "delivered_at": None, "cancelled_at": None,
        "order_version": VERSION, "audit_trail": [],
        "subtotal_amount": 20.0, "delivery_fee": 5.0, "total_amount": 25.0,
        "payment_type": "CASH", "items": [{"name": "QA Item", "quantity": 1, "price": 20.0}],
        "delivery_zone_id": "qa-fixed-zone", "zone": "QA Fixed Zone",
        "created_at": "2026-10-07T00:00:00+00:00", "updated_at": "2026-10-07T00:00:00+00:00",
        **CONTACT, **overrides,
    })
    return await database.orders.find_one({"id": ORDER})


async def business_snapshot(database):
    state = await snapshot(database)
    return {name: value for name, value in state.items() if name != "order_operations"}


async def unchanged_business(database, original, *, admission_fence=False):
    expected = original
    if admission_fence:
        # A durable refusal commits exactly one actor fence, never a driver fence.
        expected = {**original, "users": [
            {**user, "order_admission_revision": user.get("order_admission_revision", 0) + 1}
            if user.get("id") == ADMIN["id"] else user
            for user in original["users"]
        ]}
    assert await business_snapshot(database) == expected


async def assert_effect(database, original, *, order=ORDER, driver=DRIVER, op=OP, actor=ADMIN):
    stored = await database.orders.find_one({"id": order})
    assert type(stored["order_version"]) in (int, Int64)
    assert stored["order_version"] == original["order_version"] + 1
    assert stored["driver_id"] == driver and stored["status"] == "ASSIGNED"
    target = await database.drivers.find_one({"id": driver})
    assert stored["driver_name"] == target["name"]
    assert stored["assigned_at"] and stored["updated_at"]
    assert target["current_order_id"] == order and target["driver_status"] == "delivery"
    assert target["is_active"] is True and target["account_disabled"] is False
    mutable = {"order_version", "driver_id", "driver_name", "status", "assigned_at", "updated_at", "audit_trail"}
    assert {k: v for k, v in stored.items() if k not in mutable} == {
        k: v for k, v in original.items() if k not in mutable
    }, "Assignment changed preparation, custody, contact, financial, or tenant data"
    assert len(stored["audit_trail"]) == len(original["audit_trail"]) + 1
    audit = await database.audit_logs.find_one({"operation_ref": operation_key(actor["id"], op)})
    assert audit and audit["action"] == "order.assigned" and audit["entity_id"] == order
    assert audit["performed_by"] == actor["id"] and audit["performed_by_role"] == "admin"
    assert audit["from_order_version"] == original["order_version"]
    assert audit["to_order_version"] == stored["order_version"]
    assert audit["changes"] == {
        "from_status": original["status"], "to_status": "ASSIGNED",
        "old_driver_id": original.get("driver_id"), "new_driver_id": driver,
    }
    assert audit["created_at"] and audit["request_id"]
    assert {k: v for k, v in audit.items() if k not in {"_id", "entity_type", "entity_id"}} == stored["audit_trail"][-1]
    private_free(audit)
    private_free(stored["audit_trail"])
    operation = await database.order_operations.find_one({"_id": operation_key(actor["id"], op)})
    assert operation["state"] == "applied" and operation["order_id"] == order
    assert operation["order_version"] == stored["order_version"]
    assert (await database.counters.find_one({"_id": "orders.global"}))["seq"] == 100
    return stored, audit, operation


async def admit_pending(database, cmd=None, *, order=ORDER, actor=ADMIN):
    cmd = cmd or command()
    before = await business_snapshot(database)
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderAssignmentService(DatabaseProxy(database, faults)).assign(order, cmd, actor)
    assert faults.injections == 1
    pending = await database.order_operations.find_one({"_id": operation_key(actor["id"], cmd.client_operation_id)})
    assert pending["state"] == "pending" and pending["command"] == cmd.model_dump(mode="json")
    assert pending["payload_digest"] == build_mutation_intent(actor["id"], "assign", order, cmd).payload_digest
    await unchanged_business(database, before)
    return pending


async def settle(database, outcome, *, order=ORDER, op=OP, actor=ADMIN):
    for _ in range(4):
        if outcome.result.state != "pending":
            return outcome
        outcome = await OrderAssignmentService(database).resume(order, op, actor)
    pytest.fail("Same-identity assignment remained pending after four bounded retries")


async def rejected_unchanged(database, before, cmd=None, *, order=ORDER, code=None, status=409):
    cmd = cmd or command()
    outcome = await settle(database, await OrderAssignmentService(database).assign(order, cmd, ADMIN), order=order, op=cmd.client_operation_id)
    result = receipt(outcome, "rejected", status, op=cmd.client_operation_id)
    if code:
        assert result.error_code == code
    await unchanged_business(database, before, admission_fence=True)
    operation = await database.order_operations.find_one({"_id": operation_key(ADMIN["id"], cmd.client_operation_id)})
    assert operation["state"] == "rejected" and operation["error_code"] == result.error_code
    assert operation["error_status"] == BUSINESS_ERRORS[result.error_code] == status
    terminal = await snapshot(database)
    receipt(await OrderAssignmentService(database).resume(order, cmd.client_operation_id, ADMIN), "rejected", status, op=cmd.client_operation_id)
    assert await snapshot(database) == terminal
    return result


def test_contract_identity_is_actor_type_scoped_and_payload_binds_driver_revision_target():
    assert SETTINGS_ID == "order-assign-v1"
    base = build_mutation_intent(ADMIN["id"], "assign", ORDER, command())
    assert base.identity == (ADMIN["id"], "assign", OP)
    for target, cmd in ((SECOND_ORDER, command()), (ORDER, command(driver=OLD_DRIVER)),
                        (ORDER, command(version=VERSION + 1))):
        candidate = build_mutation_intent(ADMIN["id"], "assign", target, cmd)
        assert candidate.identity == base.identity and candidate.payload_digest != base.payload_digest
    assert operation_key(ADMIN["id"], OP) != operation_key(OTHER["id"], OP)
    from utils.order_editing import operation_key as edit_key
    assert operation_key(ADMIN["id"], OP) != edit_key(ADMIN["id"], OP)


@pytest.mark.parametrize("version", [None, True, False, 7.0, [7], "7", -1, MAX_ORDER_VERSION + 1])
def test_contract_invalid_revision_never_coerces(version):
    with pytest.raises(ValidationError):
        command(version=version)


@pytest.mark.parametrize("driver", [None, True, [], {}, "", " ", " padded", "padded ", "x" * 121])
def test_contract_driver_is_required_strict_nonblank_unpadded(driver):
    with pytest.raises(ValidationError):
        command(driver=driver)


def test_contract_missing_revision_driver_and_force_override_are_invalid():
    for payload in ({"client_operation_id": OP, "driver_id": DRIVER},
                    {"client_operation_id": OP, "expected_order_version": VERSION},
                    {**command().model_dump(mode="json"), "force": True}):
        with pytest.raises(ValidationError):
            AssignOrderCommand.model_validate(payload)


@mongo_case
async def test_atomic_assignment_immutable_private_receipt_historical_replay(db, caplog):
    original = await seed(db)
    caplog.set_level("INFO", logger="utils.order_assignment")
    service = OrderAssignmentService(db)
    outcome = await service.assign(ORDER, command(), ADMIN)
    receipt(outcome, "applied", 200, version=VERSION + 1)
    with pytest.raises(FrozenInstanceError):
        outcome.status_code = 201
    _, _, operation = await assert_effect(db, original)
    assert operation["command"] == command().model_dump(mode="json")
    assert operation["payload_digest"] == build_mutation_intent(ADMIN["id"], "assign", ORDER, command()).payload_digest
    assert operation["actor_id"] == ADMIN["id"] and operation["actor_role"] == "admin"
    assert operation["target_order_id"] == ORDER and operation["operation_type"] == "assign"
    before = await snapshot(db)
    receipt(await service.assign(ORDER, command(), ADMIN), "replayed", 200, version=VERSION + 1)
    assert await snapshot(db) == before
    await db.orders.update_one({"id": ORDER}, {"$set": {"order_version": 25, "status": "DELIVERED"}})
    before = await snapshot(db)
    for action in (service.lookup, service.resume):
        receipt(await action(ORDER, OP, ADMIN), "replayed", 200, version=VERSION + 1)
    assert await snapshot(db) == before
    assert await db.audit_logs.count_documents({}) == 1
    private_free(caplog.text)


@pytest.mark.parametrize("status", ["NEW", "PREPARING", "READY"])
@mongo_case
async def test_preparation_fields_timer_contact_and_financials_preserved(db, status):
    preparation = {"preparation_status": status}
    if status != "NEW":
        preparation.update(preparation_time=30, preparation_started_at="2026-10-07T00:01:00+00:00",
                           preparation_due_at="2026-10-07T00:31:00+00:00", preparation_estimated_seconds=1800)
    if status == "READY":
        preparation.update(preparation_ready_at="2026-10-07T00:25:00+00:00",
                           preparation_actual_seconds=1440, preparation_delay_seconds=0)
    original = await seed(db, status=status, **preparation)
    receipt(await OrderAssignmentService(db).assign(ORDER, command(), ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db, original)


@pytest.mark.parametrize("committed", [False, True])
@mongo_case
async def test_same_actor_same_id_changed_driver_revision_target_is_read_only_conflict(db, committed):
    await seed(db)
    if committed:
        receipt(await OrderAssignmentService(db).assign(ORDER, command(), ADMIN), "applied", 200, version=VERSION + 1)
    else:
        await admit_pending(db)
    before = await snapshot(db)
    for target, cmd in ((SECOND_ORDER, command()), (ORDER, command(driver=OLD_DRIVER)),
                        (ORDER, command(version=VERSION + 1))):
        await raises_assignment(OrderAssignmentService(db).assign(target, cmd, ADMIN), 409, "INTENT_CONFLICT")
        assert await snapshot(db) == before


@mongo_case
async def test_lookup_actor_target_scoped_read_only_and_resume_never_admits(db):
    await seed(db)
    await admit_pending(db)
    faults = Faults()
    faults.read_only = True
    service = OrderAssignmentService(DatabaseProxy(db, faults))
    before = await snapshot(db)
    receipt(await service.lookup(ORDER, OP, ADMIN), "pending", 202)
    for target, actor in ((SECOND_ORDER, ADMIN), (ORDER, OTHER)):
        await raises_assignment(service.lookup(target, OP, actor), 404, "OPERATION_NOT_FOUND")
        await raises_assignment(OrderAssignmentService(db).resume(target, OP, actor), 404, "OPERATION_NOT_FOUND")
    await raises_assignment(OrderAssignmentService(db).resume(ORDER, "qa_s204_never_admitted_01", ADMIN), 404, "OPERATION_NOT_FOUND")
    assert faults.sessions == 0 and await snapshot(db) == before


@mongo_case
async def test_default_deny_separate_marker_capability_does_not_provision(db):
    await seed(db)
    await db.order_operation_settings.insert_one({"_id": "order-edit-v1", "enabled": True})
    await db.order_operation_settings.delete_one({"_id": SETTINGS_ID})
    before = await snapshot(db)
    indexes = {name: await db[name].index_information() for name in before}
    faults = Faults()
    faults.read_only = True
    assert await OrderAssignmentService(DatabaseProxy(db, faults)).capabilities(ADMIN) == {"assign_recovery_enabled": False}
    await raises_assignment(OrderAssignmentService(db).assign(ORDER, command(), ADMIN), 503)
    assert await snapshot(db) == before
    assert {name: await db[name].index_information() for name in before} == indexes


@pytest.mark.parametrize("enabled", [False, 1, "true", None])
@mongo_case
async def test_nonboolean_or_disabled_marker_blocks_new_intent(db, enabled):
    await seed(db)
    await db.order_operation_settings.update_one({"_id": SETTINGS_ID}, {"$set": {"enabled": enabled}})
    before = await snapshot(db)
    await raises_assignment(OrderAssignmentService(db).assign(ORDER, command(), ADMIN), 503)
    if type(enabled) is bool:
        assert await OrderAssignmentService(db).capabilities(ADMIN) == {"assign_recovery_enabled": False}
    else:
        await raises_assignment(OrderAssignmentService(db).capabilities(ADMIN), 503, "CAPABILITIES_INVALID")
    assert await snapshot(db) == before


@mongo_case
async def test_pending_recovery_after_disable_restart_preserves_admission_and_new_gate(db):
    original = await seed(db)
    pending = await admit_pending(db)
    await db.order_operation_settings.update_one({"_id": SETTINGS_ID}, {"$set": {"enabled": False}})
    receipt(await OrderAssignmentService(db).lookup(ORDER, OP, ADMIN), "pending", 202)
    receipt(await OrderAssignmentService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    _, _, applied = await assert_effect(db, original)
    for field in ("_id", "command", "payload_digest", "admission_digest", "created_at", "request_id",
                  "actor_id", "actor_role", "restaurant_id", "target_order_id"):
        assert applied[field] == pending[field]
    before = await snapshot(db)
    receipt(await OrderAssignmentService(db).assign(ORDER, command(), ADMIN), "replayed", 200, version=VERSION + 1)
    await raises_assignment(OrderAssignmentService(db).assign(ORDER, command("qa_s204_disabled_new_01", VERSION + 1, OLD_DRIVER), ADMIN), 503)
    assert await snapshot(db) == before


@pytest.mark.parametrize("change", [{"account_disabled": True}, {"role": "driver"}, {"role": "restaurant"}])
@mongo_case
async def test_current_admin_role_disable_rechecked_for_all_actions(db, change):
    await seed(db)
    await admit_pending(db)
    await db.users.update_one({"id": ADMIN["id"]}, {"$set": change})
    before = await snapshot(db)
    service = OrderAssignmentService(db)
    for action in (lambda: service.assign(ORDER, command(), ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN), lambda: service.capabilities(ADMIN)):
        await raises_assignment(action(), 403)
    assert await snapshot(db) == before


@mongo_case
async def test_missing_account_and_stale_actor_role_do_not_write(db):
    await seed(db)
    before = await snapshot(db)
    await raises_assignment(OrderAssignmentService(db).assign(ORDER, command(), {"role": "admin"}), 401, "AUTH_REQUIRED")
    await raises_assignment(OrderAssignmentService(db).assign(ORDER, command(), {**ADMIN, "role": "driver"}), 403, "NOT_AUTHORIZED")
    assert await snapshot(db) == before
    await db.users.delete_one({"id": ADMIN["id"]})
    before = await snapshot(db)
    await raises_assignment(OrderAssignmentService(db).resume(ORDER, OP, ADMIN), 401, "AUTH_REQUIRED")
    assert await snapshot(db) == before


@pytest.mark.parametrize("change", [{"account_disabled": True}, {"role": "restaurant"}])
@mongo_case
async def test_admin_revocation_after_transaction_read_cannot_commit(db, change):
    await seed(db)
    before = await business_snapshot(db)
    faults = Faults()

    async def revoke(name, result):
        if name == "users" and result and result.get("id") == ADMIN["id"] and not faults.injections:
            faults.injections += 1
            await db.users.update_one({"id": ADMIN["id"]}, {"$set": change})
    faults.after_read = revoke
    await raises_assignment(OrderAssignmentService(DatabaseProxy(db, faults)).assign(ORDER, command(), ADMIN), 403)
    assert faults.injections == 1
    after = await business_snapshot(db)
    assert {k: v for k, v in after.items() if k != "users"} == {k: v for k, v in before.items() if k != "users"}
    assert (await db.order_operations.find_one({}))["state"] == "pending"


@pytest.mark.parametrize("revision", [None, True, False, 7.0, [7], "7", -1, Decimal128(str(MAX_ORDER_VERSION + 1))])
@mongo_case
async def test_stored_malformed_revision_fail_closed_no_promotion(db, revision):
    await seed(db, order_version=revision)
    await rejected_unchanged(db, await business_snapshot(db), code="ORDER_VERSION_INVALID")


@mongo_case
async def test_missing_revision_is_not_create_receipt_zero(db):
    await seed(db, creation_operation_ref="create:qa-old-receipt")
    await db.orders.update_one({"id": ORDER}, {"$unset": {"order_version": ""}})
    await rejected_unchanged(db, await business_snapshot(db), command(version=0), code="ORDER_VERSION_REQUIRED")


@mongo_case
async def test_stale_revision_rejection_is_durable_even_after_external_restore(db):
    await seed(db)
    await rejected_unchanged(db, await business_snapshot(db), command(version=VERSION - 1), code="ORDER_VERSION_CONFLICT")
    await db.orders.update_one({"id": ORDER}, {"$set": {"order_version": VERSION - 1}})
    before = await snapshot(db)
    receipt(await OrderAssignmentService(db).resume(ORDER, OP, ADMIN), "rejected", 409)
    assert await snapshot(db) == before


@mongo_case
async def test_bson_int64_last_revision_increment_then_exhaustion(db):
    original = await seed(db, order_version=Int64(MAX_ORDER_VERSION - 1))
    receipt(await OrderAssignmentService(db).assign(ORDER, command(version=MAX_ORDER_VERSION - 1), ADMIN), "applied", 200, version=MAX_ORDER_VERSION)
    await assert_effect(db, original)
    await rejected_unchanged(db, await business_snapshot(db), command("qa_s204_exhausted_0001", MAX_ORDER_VERSION, OLD_DRIVER), code="ORDER_VERSION_EXHAUSTED")


@pytest.mark.parametrize("unsafe", [
    {"status": "ACCEPTED"}, {"status": "PICKED_UP"}, {"status": "DELIVERED"},
    {"status": "CANCELLED"}, {"status": "PROBLEM"}, {"status": []}, {"status": {}},
    {"accepted_at": "2026-10-07T00:01:00+00:00"}, {"picked_up_at": "2026-10-07T00:02:00+00:00"},
    {"delivered_at": "2026-10-07T00:03:00+00:00"}, {"cancelled_at": "2026-10-07T00:03:00+00:00"},
    {"cancellation_reason": "QA cancellation residual"}, {"cancelled_by": OTHER["id"]},
    {"driver_id": OLD_DRIVER}, {"assigned_at": "2026-10-07T00:01:00+00:00"},
    {"preparation_status": "READY"}, {"preparation_status": []}, {"preparation_status": False},
])
@mongo_case
async def test_custody_terminal_or_inconsistent_order_evidence_refuses_assignment(db, unsafe):
    await seed(db, **unsafe)
    await rejected_unchanged(db, await business_snapshot(db))


@pytest.mark.parametrize("change", [
    {"account_disabled": True}, {"is_active": False}, {"is_active": 1},
    {"driver_status": "break"}, {"driver_status": "offline"}, {"driver_status": "delivery"},
    {"driver_status": []}, {"current_order_id": SECOND_ORDER}, {"current_order_id": []},
    {"name": None}, {"name": " "}, {"user_id": None},
    {"current_order_ids": [SECOND_ORDER]}, {"active_order_ids": [SECOND_ORDER]},
])
@mongo_case
async def test_unavailable_malformed_or_unknown_multislot_driver_data_not_cleared(db, change):
    await seed(db)
    await db.drivers.update_one({"id": DRIVER}, {"$set": change})
    await rejected_unchanged(db, await business_snapshot(db))


@pytest.mark.parametrize("change", [{"account_disabled": True}, {"role": "restaurant"}])
@mongo_case
async def test_target_driver_user_disabled_or_wrong_role_cannot_be_claimed(db, change):
    await seed(db)
    await db.users.update_one({"id": DRIVER + "-user"}, {"$set": change})
    await rejected_unchanged(db, await business_snapshot(db))


@pytest.mark.parametrize("duplicate", ["driver", "order", "driver_user"])
@mongo_case
async def test_duplicate_driver_order_or_linked_account_identities_fail_closed(db, duplicate):
    await seed(db)
    collection, query = {
        "driver": (db.drivers, {"id": DRIVER}), "order": (db.orders, {"id": ORDER}),
        "driver_user": (db.users, {"id": DRIVER + "-user"}),
    }[duplicate]
    forged = await collection.find_one(query)
    forged.pop("_id")
    await collection.insert_one(forged)
    await rejected_unchanged(db, await business_snapshot(db))


@pytest.mark.parametrize("status", ["ASSIGNED", "ACCEPTED", "PICKED_UP"])
@mongo_case
async def test_orphan_active_order_with_driver_but_empty_claim_blocks_new_slot(db, status):
    original = await seed(db)
    other = {k: v for k, v in original.items() if k != "_id"}
    other.update(id=SECOND_ORDER, status=status, driver_id=DRIVER, driver_name="QA Synthetic Driver")
    await db.orders.insert_one(other)
    await rejected_unchanged(db, await business_snapshot(db))


@pytest.mark.parametrize("old_state", ["delivery", "break", "offline", "disabled"])
@mongo_case
async def test_reassignment_releases_only_matching_old_claim_preserves_availability(db, old_state):
    original = await seed(db, status="ASSIGNED", driver_id=OLD_DRIVER,
                          driver_name="QA Synthetic " + OLD_DRIVER, assigned_at="2026-10-07T00:01:00+00:00")
    changes = {"current_order_id": ORDER, "driver_status": old_state if old_state != "disabled" else "offline"}
    if old_state in {"offline", "disabled"}:
        changes["is_active"] = False
    if old_state == "disabled":
        changes["account_disabled"] = True
    if old_state == "break":
        changes.update(break_started_at="2026-10-07T00:02:00+00:00", break_until="2026-10-07T01:02:00+00:00")
    await db.drivers.update_one({"id": OLD_DRIVER}, {"$set": changes})
    before = await db.drivers.find_one({"id": OLD_DRIVER})
    receipt(await OrderAssignmentService(db).assign(ORDER, command(), ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db, original)
    released = await db.drivers.find_one({"id": OLD_DRIVER})
    expected = {**before, "current_order_id": None}
    if old_state == "delivery":
        expected["driver_status"] = "active"
    assert released == expected, "Old release altered unrelated availability or account data"


@pytest.mark.parametrize("old_claim", [None, SECOND_ORDER])
@mongo_case
async def test_inconsistent_old_claim_refuses_transfer_and_never_releases_other_order(db, old_claim):
    await seed(db, status="ASSIGNED", driver_id=OLD_DRIVER, driver_name="QA Old Driver",
               assigned_at="2026-10-07T00:01:00+00:00")
    await db.drivers.update_one({"id": OLD_DRIVER}, {"$set": {"current_order_id": old_claim, "driver_status": "delivery"}})
    await rejected_unchanged(db, await business_snapshot(db))


@mongo_case
async def test_two_admins_one_order_have_exactly_one_commit_and_loser_keeps_slot(db):
    original = await seed(db)
    gate, readers, faults = asyncio.Event(), set(), Faults()

    async def barrier(name, result):
        task = asyncio.current_task()
        if name == "orders" and result and result.get("id") == ORDER and len(readers) < 2 and task not in readers:
            readers.add(task)
            if len(readers) == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), 5)
    faults.after_read = barrier
    drivers = (DRIVER, OLD_DRIVER)
    outcomes = await asyncio.wait_for(asyncio.gather(*(
        OrderAssignmentService(DatabaseProxy(db, faults)).assign(ORDER, command(driver=driver), actor)
        for driver, actor in zip(drivers, (ADMIN, OTHER))
    )), 15)
    outcomes = [await settle(db, outcome, actor=actor) for outcome, actor in zip(outcomes, (ADMIN, OTHER))]
    assert len(readers) == 2, "Both real transactions must read the competing snapshot"
    assert sorted(out.result.state for out in outcomes) == ["applied", "rejected"]
    winner = next(i for i, out in enumerate(outcomes) if out.result.state == "applied")
    await assert_effect(db, original, driver=drivers[winner], actor=(ADMIN, OTHER)[winner])
    assert outcomes[1 - winner].status_code == 409
    assert (await db.drivers.find_one({"id": drivers[1 - winner]}))["current_order_id"] is None
    assert await db.audit_logs.count_documents({}) == 1 and await db.order_operations.count_documents({}) == 2


@mongo_case
async def test_two_orders_one_slot_have_one_commit_no_orphan_order(db):
    original = await seed(db)
    second = {k: v for k, v in original.items() if k != "_id"}
    second.update(id=SECOND_ORDER, order_number="QA.204.2")
    await db.orders.insert_one(second)
    second = await db.orders.find_one({"id": SECOND_ORDER})
    gate, readers, faults = asyncio.Event(), set(), Faults()

    async def barrier(name, result):
        task = asyncio.current_task()
        if name == "drivers" and result and result.get("id") == DRIVER and len(readers) < 2 and task not in readers:
            readers.add(task)
            if len(readers) == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), 5)
    faults.after_read = barrier
    orders, actors = (ORDER, SECOND_ORDER), (ADMIN, OTHER)
    outcomes = await asyncio.wait_for(asyncio.gather(*(
        OrderAssignmentService(DatabaseProxy(db, faults)).assign(order, command(), actor)
        for order, actor in zip(orders, actors)
    )), 15)
    outcomes = [await settle(db, out, order=order, actor=actor) for out, order, actor in zip(outcomes, orders, actors)]
    assert len(readers) == 2, "Both real transactions must compete for the last driver slot"
    assert sorted(out.result.state for out in outcomes) == ["applied", "rejected"]
    winner = next(i for i, out in enumerate(outcomes) if out.result.state == "applied")
    await assert_effect(db, (original, second)[winner], order=orders[winner], actor=actors[winner])
    assert await db.orders.find_one({"id": orders[1 - winner]}) == (original, second)[1 - winner]
    assert outcomes[1 - winner].status_code == 409
    assert await db.audit_logs.count_documents({}) == 1 and await db.order_operations.count_documents({}) == 2


@mongo_case
async def test_same_identity_six_concurrent_retries_one_effect_one_ledger(db):
    original = await seed(db)
    gate = asyncio.Event()

    async def caller():
        await gate.wait()
        return await OrderAssignmentService(db).assign(ORDER, command(), ADMIN)
    tasks = [asyncio.create_task(caller()) for _ in range(6)]
    gate.set()
    outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 15)
    for outcome in outcomes:
        resolved = await settle(db, outcome)
        assert resolved.result.state in {"applied", "replayed"}
        assert resolved.status_code == 200 and resolved.result.order_version == VERSION + 1
    await assert_effect(db, original)
    assert await db.order_operations.count_documents({}) == 1 and await db.audit_logs.count_documents({}) == 1


@mongo_case
async def test_preparing_route_wins_after_assignment_snapshot_without_lost_preparation(db, monkeypatch):
    await seed(db)
    import routers.orders as orders_router
    from models.order import PreparationTime
    monkeypatch.setattr(orders_router, "db", db)

    async def available():
        return 1
    monkeypatch.setattr(orders_router, "get_available_driver_count", available)
    faults = Faults()

    async def prepare(name, result):
        if name == "orders" and result and result.get("id") == ORDER and not faults.injections:
            faults.injections += 1
            await orders_router.set_preparing(ORDER, PreparationTime(preparation_time=30), ADMIN)
    faults.after_read = prepare
    outcome = await OrderAssignmentService(DatabaseProxy(db, faults)).assign(ORDER, command(), ADMIN)
    receipt(await settle(db, outcome), "rejected", 409)
    assert faults.injections == 1
    stored = await db.orders.find_one({"id": ORDER})
    assert stored["status"] == "PREPARING" and stored["preparation_status"] == "PREPARING"
    assert stored["preparation_time"] == 30 and stored["order_version"] == VERSION + 1
    assert stored["driver_id"] is None and len(stored["audit_trail"]) == 1
    assert (await db.drivers.find_one({"id": DRIVER}))["current_order_id"] is None
    assert not await db.audit_logs.find_one({"action": "order.assigned"})


@pytest.mark.parametrize("change", [{"account_disabled": True}, {"is_active": False},
                                    {"driver_status": "break"}, {"driver_status": "offline"}])
@mongo_case
async def test_driver_availability_change_after_snapshot_cannot_commit_stale_claim(db, change):
    original = await seed(db)
    faults = Faults()

    async def change_driver(name, result):
        if name == "drivers" and result and result.get("id") == DRIVER and not faults.injections:
            faults.injections += 1
            await db.drivers.update_one({"id": DRIVER}, {"$set": change})
    faults.after_read = change_driver
    outcome = await OrderAssignmentService(DatabaseProxy(db, faults)).assign(ORDER, command(), ADMIN)
    receipt(await settle(db, outcome), "rejected", 409)
    assert faults.injections == 1
    assert await db.orders.find_one({"id": ORDER}) == original
    stored = await db.drivers.find_one({"id": DRIVER})
    assert stored["current_order_id"] is None
    assert all(stored[k] == v for k, v in change.items())
    assert await db.audit_logs.count_documents({}) == 0


@mongo_case
async def test_audit_failure_rolls_back_order_new_claim_old_release_and_outcome(db, caplog):
    original = await seed(db, status="ASSIGNED", driver_id=OLD_DRIVER, driver_name="QA Synthetic " + OLD_DRIVER,
                          assigned_at="2026-10-07T00:01:00+00:00")
    await db.drivers.update_one({"id": OLD_DRIVER}, {"$set": {"current_order_id": ORDER, "driver_status": "delivery"}})
    before = await business_snapshot(db)
    faults = Faults()
    faults.audit_failure = OperationFailure("QA private failure " + PII[3], code=121)
    caplog.set_level("INFO", logger="utils.order_assignment")
    receipt(await OrderAssignmentService(DatabaseProxy(db, faults)).assign(ORDER, command(), ADMIN), "pending", 202)
    assert faults.audit_attempts >= 1 and faults.injections >= 1
    await unchanged_business(db, before)
    assert (await db.order_operations.find_one({}))["state"] == "pending"
    private_free(caplog.text)
    receipt(await OrderAssignmentService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db, original)
    assert (await db.drivers.find_one({"id": OLD_DRIVER}))["current_order_id"] is None


class LedgerFailureCollection(AssignmentCollectionProxy):
    def __getattr__(self, method):
        delegate = super().__getattr__(method)
        if method not in ASYNC_CALLS:
            return delegate

        async def call(*args, **kwargs):
            if self.real.name == "order_operations" and method in WRITES and kwargs.get("session") is not None:
                self.faults.injections += 1
                raise OperationFailure("QA assignment ledger write failure", code=121)
            return await delegate(*args, **kwargs)
        return call


class LedgerFailureDatabase(DatabaseProxy):
    def get_collection(self, name, *args, **kwargs):
        return LedgerFailureCollection(self.real.get_collection(name, *args, **kwargs), self.faults)


@mongo_case
async def test_terminal_ledger_write_failure_rolls_back_all_business_effects(db):
    original = await seed(db)
    before = await business_snapshot(db)
    faults = Faults()
    receipt(await OrderAssignmentService(LedgerFailureDatabase(db, faults)).assign(ORDER, command(), ADMIN), "pending", 202)
    assert faults.injections >= 1
    await unchanged_business(db, before)
    assert (await db.order_operations.find_one({}))["state"] == "pending"
    receipt(await OrderAssignmentService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db, original)


class PartialBusinessFailureCollection(AssignmentCollectionProxy):
    def __getattr__(self, method):
        delegate = super().__getattr__(method)
        if method not in ASYNC_CALLS:
            return delegate

        async def call(*args, **kwargs):
            result = await delegate(*args, **kwargs)
            boundary = self.faults.business_boundary
            query = args[0] if args else kwargs.get("filter", {})
            matched = (
                self.real.name == "drivers" and method == "update_one"
                and query.get("id") == (DRIVER if boundary == "new_claim" else OLD_DRIVER)
                and boundary in {"new_claim", "old_release"}
            ) or (self.real.name == "orders" and method == "find_one_and_update" and boundary == "order_cas")
            if kwargs.get("session") is not None and matched and not self.faults.injections:
                self.faults.injections += 1
                raise AssignmentError(409, "DRIVER_BUSY", "QA business refusal after partial assignment write")
            return result
        return call


class PartialBusinessFailureDatabase(DatabaseProxy):
    def get_collection(self, name, *args, **kwargs):
        return PartialBusinessFailureCollection(self.real.get_collection(name, *args, **kwargs), self.faults)


@pytest.mark.parametrize("boundary", ["new_claim", "old_release", "order_cas"])
@mongo_case
async def test_business_error_after_partial_writes_cannot_commit_terminal_refusal(db, boundary):
    original = await seed(db, status="ASSIGNED", driver_id=OLD_DRIVER,
                          driver_name="QA Synthetic " + OLD_DRIVER, assigned_at="2026-10-07T00:01:00+00:00")
    await db.drivers.update_one({"id": OLD_DRIVER}, {"$set": {"current_order_id": ORDER, "driver_status": "delivery"}})
    before = await business_snapshot(db)
    faults = Faults()
    faults.business_boundary = boundary
    await raises_assignment(OrderAssignmentService(PartialBusinessFailureDatabase(db, faults)).assign(ORDER, command(), ADMIN), 409, "DRIVER_BUSY")
    assert faults.injections == 1, "Fault must follow a real transaction business write"
    await unchanged_business(db, before)
    pending = await db.order_operations.find_one({"_id": operation_key(ADMIN["id"], OP)})
    assert pending["state"] == "pending" and pending.get("error_code") is None
    assert pending.get("order_id") is None and pending.get("resolved_at") is None
    receipt(await OrderAssignmentService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db, original)
    assert (await db.drivers.find_one({"id": OLD_DRIVER}))["current_order_id"] is None


@pytest.mark.parametrize("losses", [1, 3])
@mongo_case
async def test_lost_commit_ack_retries_same_tx_restart_replays_once(db, losses):
    original = await seed(db)
    faults = Faults()
    faults.ack_losses = losses
    outcome = await OrderAssignmentService(DatabaseProxy(db, faults)).assign(ORDER, command(), ADMIN)
    assert faults.injections == losses and faults.commits == (2 if losses == 1 else 3)
    assert faults.sessions == 1, "Unknown commit ACK must not reexecute the transaction body"
    assert outcome.result.state in {"applied", "pending"}
    receipt(await OrderAssignmentService(db).lookup(ORDER, OP, ADMIN), "replayed", 200, version=VERSION + 1)
    receipt(await OrderAssignmentService(db).resume(ORDER, OP, ADMIN), "replayed", 200, version=VERSION + 1)
    await assert_effect(db, original)
    assert await db.audit_logs.count_documents({}) == 1


class AdmissionAckCollection(AssignmentCollectionProxy):
    def __getattr__(self, method):
        delegate = super().__getattr__(method)
        if self.real.name != "order_operations" or method != "insert_one":
            return delegate

        async def call(*args, **kwargs):
            result = await delegate(*args, **kwargs)
            assert kwargs.get("session") is None
            if not self.faults.injections:
                self.faults.injections += 1
                raise AutoReconnect("QA admission ACK lost " + PII[2])
            return result
        return call


class AdmissionAckDatabase(DatabaseProxy):
    def get_collection(self, name, *args, **kwargs):
        return AdmissionAckCollection(self.real.get_collection(name, *args, **kwargs), self.faults)


@mongo_case
async def test_lost_admission_ack_keeps_same_intent_recoverable(db, caplog):
    original = await seed(db)
    faults = Faults()
    caplog.set_level("INFO", logger="utils.order_assignment")
    outcome = await OrderAssignmentService(AdmissionAckDatabase(db, faults)).assign(ORDER, command(), ADMIN)
    assert faults.injections == 1 and outcome.result.state in {"pending", "applied"}
    assert (await db.order_operations.find_one({}))["state"] in {"pending", "applied"}
    assert (await settle(db, outcome)).result.state in {"applied", "replayed"}
    await assert_effect(db, original)
    private_free(caplog.text)


@mongo_case
async def test_transient_transaction_retry_is_finite_pending_not_false_rejection(db):
    await seed(db)
    before = await business_snapshot(db)
    faults = Faults()
    faults.audit_failure = OperationFailure("QA transient conflict", code=112, details={
        "errorLabels": ["TransientTransactionError"],
    })
    receipt(await OrderAssignmentService(DatabaseProxy(db, faults)).assign(ORDER, command(), ADMIN), "pending", 202)
    assert faults.sessions == 3 and faults.audit_attempts == 3
    await unchanged_business(db, before)
    receipt(await OrderAssignmentService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)


@mongo_case
async def test_deadline_after_admission_is_finite_pending_then_recoverable(db, monkeypatch):
    original = await seed(db)
    await admit_pending(db)
    before = await business_snapshot(db)
    faults = Faults()
    faults.session_factory = ObservedCleanupSession
    faults.delay = ("order_operations", "find_one", True)
    faults.delay_release = asyncio.Event()
    assert assignment_module.DEADLINE_SECONDS == 10
    monkeypatch.setattr(assignment_module, "DEADLINE_SECONDS", 0.1)
    started = time.monotonic()
    try:
        outcome = await asyncio.wait_for(OrderAssignmentService(DatabaseProxy(db, faults)).resume(ORDER, OP, ADMIN), 1)
        receipt(outcome, "pending", 202)
        assert time.monotonic() - started < 1 and faults.injections == 1 and faults.delay_active
        await unchanged_business(db, before)
    finally:
        faults.delay_release.set()
        if faults.injections:
            await await_thread_event(faults.delay_done)
            await await_thread_event(faults.cleanup_finished)
        assert not faults.cleanup_overlap
    monkeypatch.setattr(assignment_module, "DEADLINE_SECONDS", 10)
    receipt(await OrderAssignmentService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db, original)


@pytest.mark.parametrize("boundary", [
    ("order_operations", "find_one", True), ("audit_logs", "insert_one", True),
    ("order_operations", "update_one", True),
])
@mongo_case
async def test_cancelled_request_after_admission_never_forges_terminal_result(db, boundary):
    original = await seed(db)
    await admit_pending(db)
    before = await business_snapshot(db)
    faults = Faults()
    faults.session_factory = ObservedCleanupSession
    faults.delay, faults.delay_release = boundary, asyncio.Event()
    task = asyncio.create_task(OrderAssignmentService(DatabaseProxy(db, faults)).resume(ORDER, OP, ADMIN))
    try:
        async with asyncio.timeout(2):
            while not faults.delay_active:
                assert not task.done(), "Independent cancellation boundary was not reached"
                await asyncio.sleep(0.01)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        assert done, "Cancelled request exceeded independent 1s bound"
        if not task.cancelled():
            receipt(task.result(), "pending", 202)
        assert (await db.order_operations.find_one({}))["state"] == "pending"
        await unchanged_business(db, before)
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
    receipt(await OrderAssignmentService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db, original)


@pytest.mark.parametrize("corruption", [
    {"actor_id": OTHER["id"]}, {"actor_role": "restaurant"}, {"restaurant_id": "qa-foreign"},
    {"payload_digest": "0" * 64}, {"admission_digest": "0" * 64},
    {"client_operation_id": "qa_s204_forged_metadata_01"},
    {"command.client_operation_id": "qa_s204_forged_command_01"},
    {"command.expected_order_version": True}, {"command.driver_id": OLD_DRIVER},
    {"target_order_id": SECOND_ORDER}, {"contract_version": True}, {"operation_type": "edit"},
    {"request_id": PII[3]}, {"created_at": "2026-10-07"}, {"state": "unknown"},
    {"state": "applied", "order_version": None},
    {"state": "applied", "order_id": {"unsafe": PII[0]}},
    {"state": "rejected", "error_status": 200, "error_code": "ORDER_VERSION_CONFLICT"},
])
@mongo_case
async def test_corrupt_admission_envelope_cannot_execute_repair_or_leak(db, corruption, caplog):
    await seed(db)
    pending = await admit_pending(db)
    await db.order_operations.update_one({"_id": pending["_id"]}, {"$set": corruption})
    before = await snapshot(db)
    caplog.set_level("INFO", logger="utils.order_assignment")
    service = OrderAssignmentService(db)
    for action in (lambda: service.assign(ORDER, command(), ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN)):
        await raises_assignment(action(), 503, "OPERATION_INVALID")
        assert await snapshot(db) == before
    private_free(caplog.text)
