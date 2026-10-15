"""Independent S2-03 QA. Run only through the parent's isolated runner.

The imported fixture verifies the owned 27941 replica set before creating a
unique synthetic database. No dotenv, live DB, processes, or cleanup here.
Missing implementation is an intentional collection error, never a skip.
"""

import asyncio
from dataclasses import FrozenInstanceError, is_dataclass
import json
import re
import threading
import time

from bson.int64 import Int64
from pydantic import ValidationError
import pytest
from pymongo.errors import AutoReconnect, OperationFailure

from models.order_mutation import (
    EditOrderCommand, MAX_ORDER_VERSION, MutationResult, build_mutation_intent,
)
from test_order_creation_recovery import (
    ASYNC_CALLS, WRITES, ClientProxy, CollectionProxy, DatabaseProxy as CreationDatabaseProxy, Faults, SessionProxy,
    SimulatedCrash, await_thread_event, db, mongo_case, snapshot,
)
from utils.order_editing import (
    EditingError, EditingOutcome, OrderEditingService, operation_key,
)
import utils.order_editing as editing_module


ADMIN = {"id": "qa-edit-admin", "role": "admin"}
OTHER = {"id": "qa-edit-other-admin", "role": "admin"}
ORDER = "qa-edit-order"
OP = "qa_s203_edit_operation_0001"
VERSION = 7
PII = (
    "QA Edit Original Customer", "0701234567", "QA Edit Original Address 123",
    "QA Edit Original Private Note", "QA Edit Revised Customer", "0707654321",
    "QA Edit Revised Address 456", "QA Edit Revised Private Note",
    "44.123456", "26.654321", "45.876543", "27.345678",
)
CONTACT = {
    "customer_name": PII[0], "customer_phone": PII[1],
    "customer_address": PII[2], "notes": PII[3],
    "customer_latitude": 44.123456, "customer_longitude": 26.654321,
}
REVISED = {
    "customer_name": PII[4], "customer_phone": PII[5],
    "customer_address": PII[6], "notes": PII[7],
    "customer_latitude": 45.876543, "customer_longitude": 27.345678,
}


class SnapshotCursor:
    """Inject after a real transaction cursor read, not an in-memory substitute."""
    def __init__(self, real, faults):
        self.real, self.faults = real, faults

    def limit(self, count):
        self.real = self.real.limit(count)
        return self

    async def to_list(self, length=None):
        result = await self.real.to_list(length)
        if self.faults.after_read:
            for document in result:
                await self.faults.after_read("orders", document)
        return result

    def __getattr__(self, name):
        return getattr(self.real, name)


class EditingCollectionProxy(CollectionProxy):
    def __getattr__(self, method):
        delegate = super().__getattr__(method)
        if method != "find" or self.real.name != "orders":
            return delegate
        def call(*args, **kwargs):
            cursor = delegate(*args, **kwargs)
            return SnapshotCursor(cursor, self.faults) if kwargs.get("session") is not None else cursor
        return call


class DatabaseProxy(CreationDatabaseProxy):
    def get_collection(self, name, *args, **kwargs):
        return EditingCollectionProxy(self.real.get_collection(name, *args, **kwargs), self.faults)


def command(op=OP, version=VERSION, **changes):
    if not changes:
        changes = {"customer_name": REVISED["customer_name"]}
    return EditOrderCommand(
        client_operation_id=op, expected_order_version=version, changes=changes,
    )


def private_free(value):
    rendered = json.dumps(value, default=str)
    for sentinel in PII:
        assert sentinel not in rendered, "Customer value leaked from private payload"


def receipt(outcome, state, status, *, version=None, op=OP):
    assert type(outcome) is EditingOutcome and is_dataclass(outcome)
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
    elif state == "pending":
        assert result.order_id is None and result.order_version is None
        assert result.error_code is None and 1 <= result.retry_after_seconds <= 60
    else:
        assert result.order_id is None and result.order_version is None
        assert result.retry_after_seconds is None
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", result.error_code)
    return result


async def raises_edit(awaitable, status, code=None):
    with pytest.raises(EditingError) as error:
        await awaitable
    assert error.value.status_code == status
    if code is not None:
        assert error.value.code == code
    assert re.fullmatch(r"[A-Z][A-Z0-9_]*", error.value.code)
    assert isinstance(error.value.message, str) and error.value.message
    private_free(str(error.value))
    return error.value


async def seed(db, **overrides):
    await db.users.insert_many([
        {**ADMIN, "account_disabled": False}, {**OTHER, "account_disabled": False},
    ])
    await db.order_operation_settings.insert_one({"_id": "order-edit-v1", "enabled": True})
    order = {
        "id": ORDER, "order_number": "QA.203", "restaurant_id": "qa-restaurant",
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
    }
    await db.orders.insert_one(order)
    return await db.orders.find_one({"id": ORDER})


async def unchanged_business(db, original):
    assert await db.orders.find_one({"id": ORDER}) == original
    assert await db.audit_logs.count_documents({}) == 0
    assert (await db.counters.find_one({"_id": "orders.global"}))["seq"] == 100


async def assert_effect(db, *, changes=None, version=VERSION + 1, op=OP, actor=ADMIN):
    stored = await db.orders.find_one({"id": ORDER})
    assert type(stored["order_version"]) in (int, Int64)
    assert stored["order_version"] == version
    for key, value in (changes or {"customer_name": REVISED["customer_name"]}).items():
        assert stored[key] == value
    assert await db.orders.count_documents({}) == 1
    assert len(stored["audit_trail"]) == 1
    assert await db.audit_logs.count_documents({}) == 1
    audit = await db.audit_logs.find_one({})
    assert audit["action"] == "order.corrected" and audit["entity_id"] == ORDER
    assert audit["operation_ref"] == operation_key(actor["id"], op)
    assert audit["performed_by"] == actor["id"] and audit["performed_by_role"] == "admin"
    assert audit["from_order_version"] == version - 1 and audit["to_order_version"] == version
    assert audit["changes"] == {"fields": sorted((changes or {"customer_name": PII[4]}).keys())}
    assert audit["created_at"] and audit["request_id"]
    embedded = stored["audit_trail"][0]
    assert {key: value for key, value in audit.items() if key not in {"_id", "entity_type", "entity_id"}} == embedded
    private_free(audit)
    private_free(stored["audit_trail"])
    operation = await db.order_operations.find_one({"_id": operation_key(actor["id"], op)})
    assert operation["state"] == "applied"
    assert operation["order_id"] == ORDER and operation["order_version"] == version
    assert (await db.counters.find_one({"_id": "orders.global"}))["seq"] == 100
    return stored, audit, operation


async def admit_pending(db, cmd=None):
    cmd = cmd or command()
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderEditingService(DatabaseProxy(db, faults)).edit(ORDER, cmd, ADMIN)
    assert faults.injections == 1
    pending = await db.order_operations.find_one({"_id": operation_key(ADMIN["id"], cmd.client_operation_id)})
    assert pending["state"] == "pending"
    assert pending["command"] == cmd.model_dump(mode="json")
    assert pending["payload_digest"] == build_mutation_intent(ADMIN["id"], "edit", ORDER, cmd).payload_digest
    return pending


async def settle(db, outcome, *, op=OP, actor=ADMIN):
    for _ in range(4):
        if outcome.result.state != "pending":
            return outcome
        outcome = await OrderEditingService(db).resume(ORDER, op, actor)
    pytest.fail("Same-identity edit recovery remained pending after four retries")


def test_contract_omission_is_not_materialized_and_explicit_null_is_preserved():
    assert command(notes=None).model_dump(mode="json")["changes"] == {"notes": None}
    assert command(customer_name=PII[4]).model_dump(mode="json")["changes"] == {"customer_name": PII[4]}
    cleared = command(customer_latitude=None, customer_longitude=None)
    assert cleared.model_dump(mode="json")["changes"] == {
        "customer_latitude": None, "customer_longitude": None,
    }


@pytest.mark.parametrize("version", [None, True, False, 7.0, [7], "7", -1, MAX_ORDER_VERSION + 1])
def test_contract_invalid_expected_revision_is_not_coerced(version):
    with pytest.raises(ValidationError):
        command(version=version)


def test_contract_missing_expected_revision_and_partial_coordinate_pair_are_invalid():
    with pytest.raises(ValidationError):
        EditOrderCommand(client_operation_id=OP, changes={"notes": None})
    for changes in ({"customer_latitude": 1.0}, {"customer_longitude": None},
                    {"customer_latitude": None, "customer_longitude": 1.0}):
        with pytest.raises(ValidationError):
            command(**changes)


def test_contract_financial_status_and_tenant_fields_are_not_editable():
    for key, value in {"total_amount": 1.0, "status": "READY", "restaurant_id": "qa-other", "items": []}.items():
        with pytest.raises(ValidationError):
            command(**{key: value})


def test_edit_identity_excludes_target_but_digest_binds_target_payload_and_expected_revision():
    base = build_mutation_intent(ADMIN["id"], "edit", ORDER, command())
    for target, cmd in (("qa-other-order", command()), (ORDER, command(notes=None)),
                        (ORDER, command(version=VERSION + 1))):
        candidate = build_mutation_intent(ADMIN["id"], "edit", target, cmd)
        assert candidate.identity == base.identity
        assert candidate.payload_digest != base.payload_digest
    assert operation_key(ADMIN["id"], OP).startswith("edit:")
    assert operation_key(ADMIN["id"], OP) != operation_key(OTHER["id"], OP)
    from utils.order_creation import operation_key as creation_key
    assert operation_key(ADMIN["id"], OP) != creation_key(ADMIN["id"], OP)


@mongo_case
async def test_atomic_patch_private_audits_ledger_and_historical_replay(db, caplog):
    original = await seed(db)
    caplog.set_level("INFO", logger="utils.order_editing")
    cmd = command(**REVISED)
    service = OrderEditingService(db)
    assert service.operations.write_concern.document["w"] == "majority"
    assert service.operations.read_concern.level == "majority"
    from pymongo.read_preferences import ReadPreference
    assert service.operations.read_preference == ReadPreference.PRIMARY
    outcome = await service.edit(ORDER, cmd, ADMIN)
    receipt(outcome, "applied", 200, version=VERSION + 1)
    with pytest.raises(FrozenInstanceError):
        outcome.status_code = 201
    stored, audit, operation = await assert_effect(db, changes=REVISED)
    assert operation["command"] == cmd.model_dump(mode="json")
    assert operation["payload_digest"] == build_mutation_intent(ADMIN["id"], "edit", ORDER, cmd).payload_digest
    assert operation["actor_id"] == ADMIN["id"] and operation["actor_role"] == "admin"
    assert operation["restaurant_id"] == original["restaurant_id"]
    for key in ("items", "total_amount", "subtotal_amount", "delivery_fee", "payment_type",
                "restaurant_id", "source", "delivery_zone_id", "zone", "status", "created_at"):
        assert stored[key] == original[key]
    before = await snapshot(db)
    receipt(await service.edit(ORDER, cmd, ADMIN), "replayed", 200, version=VERSION + 1)
    receipt(await service.resume(ORDER, OP, ADMIN), "replayed", 200, version=VERSION + 1)
    assert await snapshot(db) == before
    await db.orders.update_one({"id": ORDER}, {"$set": {"status": "DELIVERED", "order_version": 99}})
    before = await snapshot(db)
    receipt(await service.lookup(ORDER, OP, ADMIN), "replayed", 200, version=VERSION + 1)
    receipt(await service.edit(ORDER, cmd, ADMIN), "replayed", 200, version=VERSION + 1)
    assert await snapshot(db) == before
    private_free(caplog.text)


@mongo_case
async def test_only_present_fields_change_and_notes_explicit_null_clears(db):
    original = await seed(db)
    receipt(await OrderEditingService(db).edit(ORDER, command(notes=None), ADMIN), "applied", 200, version=VERSION + 1)
    stored, _, _ = await assert_effect(db, changes={"notes": None})
    for key in CONTACT.keys() - {"notes"}:
        assert stored[key] == original[key]


@pytest.mark.parametrize("status", ["NEW", "PREPARING", "READY"])
@mongo_case
async def test_unassigned_pre_pickup_statuses_are_editable(db, status):
    await seed(db, status=status, preparation_status=status)
    receipt(await OrderEditingService(db).edit(ORDER, command(), ADMIN), "applied", 200, version=VERSION + 1)
    stored, _, _ = await assert_effect(db)
    assert stored["status"] == status and stored["preparation_status"] == status


@mongo_case
async def test_absent_preparation_status_is_not_invented_by_operational_edit(db):
    await seed(db)
    await db.orders.update_one({"id": ORDER}, {"$unset": {"preparation_status": ""}})
    receipt(await OrderEditingService(db).edit(ORDER, command(), ADMIN), "applied", 200, version=VERSION + 1)
    stored, _, _ = await assert_effect(db)
    assert "preparation_status" not in stored


@pytest.mark.parametrize("unsafe", [
    {"status": "ASSIGNED"}, {"status": "ACCEPTED"}, {"status": "PICKED_UP"},
    {"status": "DELIVERED"}, {"status": "CANCELLED"}, {"status": "unknown"},
    {"driver_id": "qa-driver"}, {"driver_id": ""}, {"driver_id": []},
    {"assigned_at": "2026-10-07T01:00:00Z"}, {"accepted_at": "2026-10-07T01:00:00Z"},
    {"picked_up_at": "2026-10-07T01:00:00Z"}, {"delivered_at": "2026-10-07T01:00:00Z"},
    {"cancelled_at": "2026-10-07T01:00:00Z"},
])
@mongo_case
async def test_custody_terminal_and_inconsistent_evidence_fail_closed(db, unsafe):
    original = await seed(db, **unsafe)
    service = OrderEditingService(db)
    result = receipt(await service.edit(ORDER, command(), ADMIN), "rejected", 409)
    await unchanged_business(db, original)
    before = await snapshot(db)
    assert receipt(await service.lookup(ORDER, OP, ADMIN), "rejected", 409) == result
    assert receipt(await service.resume(ORDER, OP, ADMIN), "rejected", 409) == result
    assert await snapshot(db) == before


@pytest.mark.parametrize("preparation", [None, "READY", "unknown", [], False])
@mongo_case
async def test_present_preparation_status_must_match_operational_status(db, preparation):
    original = await seed(db, preparation_status=preparation)
    receipt(await OrderEditingService(db).edit(ORDER, command(), ADMIN), "rejected", 409)
    await unchanged_business(db, original)


@pytest.mark.parametrize("coordinates", [
    {"customer_latitude": None}, {"customer_longitude": None},
    {"customer_latitude": True}, {"customer_latitude": [44.123456]},
    {"customer_latitude": 91.0}, {"customer_longitude": float("nan")},
])
@mongo_case
async def test_existing_malformed_coordinate_pair_not_silently_overwritten(db, coordinates):
    await seed(db, **coordinates)
    original = await db.orders.find_one({"id": ORDER})
    receipt(await OrderEditingService(db).edit(ORDER, command(**REVISED), ADMIN), "rejected", 409)
    stored = await db.orders.find_one({"id": ORDER})
    # NaN is not self-equal; compare BSON bytes for an exact no-write check.
    from bson import BSON
    assert BSON.encode(stored) == BSON.encode(original)
    assert await db.audit_logs.count_documents({}) == 0 and stored["audit_trail"] == []


@pytest.mark.parametrize("malformed", [None, True, False, 7.0, [7], "7", -1])
@mongo_case
async def test_stored_revision_malformed_never_becomes_expected_revision(db, malformed):
    original = await seed(db, order_version=malformed)
    result = receipt(await OrderEditingService(db).edit(ORDER, command(), ADMIN), "rejected", 409)
    assert result.error_code == "ORDER_VERSION_INVALID"
    await unchanged_business(db, original)


@mongo_case
async def test_missing_business_revision_is_not_receipt_zero_or_lazy_promotion(db):
    await seed(db, creation_operation_ref="create:qa-receipt-zero")
    await db.orders.update_one({"id": ORDER}, {"$unset": {"order_version": ""}})
    original = await db.orders.find_one({"id": ORDER})
    result = receipt(await OrderEditingService(db).edit(ORDER, command(version=0), ADMIN), "rejected", 409)
    assert result.error_code == "ORDER_VERSION_REQUIRED"
    await unchanged_business(db, original)
    assert "order_version" not in (await db.orders.find_one({"id": ORDER}))


@mongo_case
async def test_bson_int64_revision_and_last_increment_are_valid_then_exhausted(db):
    await seed(db, order_version=Int64(MAX_ORDER_VERSION - 1))
    cmd = command(version=MAX_ORDER_VERSION - 1)
    receipt(await OrderEditingService(db).edit(ORDER, cmd, ADMIN), "applied", 200, version=MAX_ORDER_VERSION)
    await assert_effect(db, version=MAX_ORDER_VERSION)
    before = await db.orders.find_one({"id": ORDER})
    next_op = "qa_s203_exhausted_0001"
    result = receipt(await OrderEditingService(db).edit(ORDER, command(next_op, MAX_ORDER_VERSION, notes=None), ADMIN),
                     "rejected", 409, op=next_op)
    assert result.error_code == "ORDER_VERSION_EXHAUSTED"
    assert await db.orders.find_one({"id": ORDER}) == before
    assert await db.audit_logs.count_documents({}) == 1


@mongo_case
async def test_stale_revision_stable_even_if_order_later_returns_to_expected(db):
    original = await seed(db, order_version=VERSION + 1)
    service = OrderEditingService(db)
    rejected = receipt(await service.edit(ORDER, command(), ADMIN), "rejected", 409)
    await unchanged_business(db, original)
    await db.orders.update_one({"id": ORDER}, {"$set": {"order_version": VERSION}})
    before = await snapshot(db)
    assert receipt(await service.edit(ORDER, command(), ADMIN), "rejected", 409) == rejected
    assert receipt(await service.resume(ORDER, OP, ADMIN), "rejected", 409) == rejected
    assert await snapshot(db) == before


@mongo_case
async def test_noop_is_durable_rejection_not_revision_or_audit_increment(db):
    original = await seed(db)
    service = OrderEditingService(db)
    cmd = command(customer_name=CONTACT["customer_name"])
    result = receipt(await service.edit(ORDER, cmd, ADMIN), "rejected", 409)
    assert result.error_code == "NO_CHANGES"
    await unchanged_business(db, original)
    await db.orders.update_one({"id": ORDER}, {"$set": {"customer_name": PII[4]}})
    before = await snapshot(db)
    assert receipt(await service.edit(ORDER, cmd, ADMIN), "rejected", 409) == result
    assert receipt(await service.lookup(ORDER, OP, ADMIN), "rejected", 409) == result
    assert await snapshot(db) == before


@mongo_case
async def test_missing_order_rejection_remains_stable_after_target_appears(db):
    await seed(db)
    original = await db.orders.find_one({"id": ORDER})
    await db.orders.delete_one({"id": ORDER})  # Only this case's fresh synthetic seed.
    service = OrderEditingService(db)
    receipt(await service.edit(ORDER, command(), ADMIN), "rejected", 404)
    assert await db.audit_logs.count_documents({}) == 0
    await db.orders.insert_one(original)
    before = await snapshot(db)
    receipt(await service.edit(ORDER, command(), ADMIN), "rejected", 404)
    receipt(await service.resume(ORDER, OP, ADMIN), "rejected", 404)
    assert await snapshot(db) == before


@mongo_case
async def test_address_change_cannot_retain_stale_coordinates(db):
    original = await seed(db)
    result = receipt(await OrderEditingService(db).edit(ORDER, command(customer_address=PII[6]), ADMIN), "rejected", 409)
    assert result.error_code
    await unchanged_business(db, original)


@pytest.mark.parametrize("pair", [(None, None), (45.876543, 27.345678)])
@mongo_case
async def test_address_change_explicit_clear_or_replacement_pair_without_repricing(db, pair):
    original = await seed(db)
    changes = {"customer_address": PII[6], "customer_latitude": pair[0], "customer_longitude": pair[1]}
    receipt(await OrderEditingService(db).edit(ORDER, command(**changes), ADMIN), "applied", 200, version=VERSION + 1)
    stored, _, _ = await assert_effect(db, changes=changes)
    for key in ("delivery_fee", "subtotal_amount", "total_amount", "delivery_zone_id", "zone", "payment_type"):
        assert stored[key] == original[key]


@mongo_case
async def test_address_with_no_prior_coordinates_can_change_without_pair(db):
    await seed(db, customer_latitude=None, customer_longitude=None)
    changes = {"customer_address": PII[6]}
    receipt(await OrderEditingService(db).edit(ORDER, command(**changes), ADMIN), "applied", 200, version=VERSION + 1)
    stored, _, _ = await assert_effect(db, changes=changes)
    assert stored["customer_latitude"] is None and stored["customer_longitude"] is None


@pytest.mark.parametrize("committed", [False, True])
@mongo_case
async def test_existing_identity_cannot_change_target_payload_revision_or_omission(db, committed):
    await seed(db)
    cmd = command(notes=None)
    service = OrderEditingService(db)
    if committed:
        receipt(await service.edit(ORDER, cmd, ADMIN), "applied", 200, version=VERSION + 1)
    else:
        await admit_pending(db, cmd)
    before = await snapshot(db)
    for target, candidate in (("qa-other-target", cmd), (ORDER, command(notes=PII[7])),
                              (ORDER, command(version=VERSION + 1, notes=None)),
                              (ORDER, command(customer_name=PII[4]))):
        await raises_edit(service.edit(target, candidate, ADMIN), 409, "INTENT_CONFLICT")
        assert await snapshot(db) == before


@mongo_case
async def test_lookup_is_read_only_actor_and_target_bound_resume_cannot_admit(db):
    await seed(db)
    await admit_pending(db)
    faults = Faults()
    faults.read_only = True
    service = OrderEditingService(DatabaseProxy(db, faults))
    before = await snapshot(db)
    receipt(await service.lookup(ORDER, OP, ADMIN), "pending", 202)
    for target, actor in (("qa-other-target", ADMIN), (ORDER, OTHER)):
        await raises_edit(service.lookup(target, OP, actor), 404, "OPERATION_NOT_FOUND")
    await raises_edit(OrderEditingService(db).resume(ORDER, "qa_s203_never_admitted_01", ADMIN), 404, "OPERATION_NOT_FOUND")
    assert await snapshot(db) == before
    assert faults.sessions == 0


@pytest.mark.parametrize("change", [{"account_disabled": True}, {"role": "driver"}, {"role": "restaurant"}])
@mongo_case
async def test_admin_revalidated_for_pending_edit_lookup_resume_and_capabilities(db, change):
    await seed(db)
    await admit_pending(db)
    await db.users.update_one({"id": ADMIN["id"]}, {"$set": change})
    before = await snapshot(db)
    service = OrderEditingService(db)
    for action in (lambda: service.edit(ORDER, command(), ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN), lambda: service.capabilities(ADMIN)):
        await raises_edit(action(), 403)
    assert await snapshot(db) == before


@mongo_case
async def test_missing_identity_missing_account_and_stale_auth_context_have_no_writes(db):
    await seed(db)
    service = OrderEditingService(db)
    before = await snapshot(db)
    await raises_edit(service.edit(ORDER, command(), {"role": "admin"}), 401, "AUTH_REQUIRED")
    await raises_edit(service.edit(ORDER, command(), {**ADMIN, "role": "restaurant"}), 403, "NOT_AUTHORIZED")
    assert await snapshot(db) == before
    await db.users.delete_one({"id": ADMIN["id"]})
    before = await snapshot(db)
    await raises_edit(service.edit(ORDER, command(), ADMIN), 401, "AUTH_REQUIRED")
    assert await snapshot(db) == before


@mongo_case
async def test_create_marker_does_not_authorize_edit_and_capabilities_do_not_provision(db):
    await seed(db)
    await db.order_operation_settings.delete_one({"_id": "order-edit-v1"})
    before = await snapshot(db)
    indexes = {name: await db[name].index_information() for name in before}
    faults = Faults()
    faults.read_only = True
    assert await OrderEditingService(DatabaseProxy(db, faults)).capabilities(ADMIN) == {"edit_recovery_enabled": False}
    await raises_edit(OrderEditingService(db).edit(ORDER, command(), ADMIN), 503)
    assert await snapshot(db) == before
    assert {name: await db[name].index_information() for name in before} == indexes


@pytest.mark.parametrize("marker", [False, 1, "true", None])
@mongo_case
async def test_disabled_and_nonboolean_marker_cannot_admit_or_provision(db, marker):
    await seed(db)
    await db.order_operation_settings.update_one({"_id": "order-edit-v1"}, {"$set": {"enabled": marker}})
    before = await snapshot(db)
    await raises_edit(OrderEditingService(db).edit(ORDER, command(), ADMIN), 503)
    assert await snapshot(db) == before
    if type(marker) is bool:
        assert await OrderEditingService(db).capabilities(ADMIN) == {"edit_recovery_enabled": False}
    else:
        await raises_edit(OrderEditingService(db).capabilities(ADMIN), 503, "CAPABILITIES_INVALID")
    assert await snapshot(db) == before


@mongo_case
async def test_enabled_capabilities_validate_transaction_topology_without_writes(db):
    await seed(db)
    faults = Faults()
    faults.read_only = True
    before = await snapshot(db)
    service = OrderEditingService(DatabaseProxy(db, faults))
    assert await service.capabilities(ADMIN) == {"edit_recovery_enabled": True}
    faults.standalone = True
    await raises_edit(service.capabilities(ADMIN), 503, "TRANSACTIONS_REQUIRED")
    assert faults.injections == 1 and faults.sessions == 0
    assert await snapshot(db) == before


@mongo_case
async def test_lookup_and_resume_wrong_target_are_read_only_not_conflict_or_admission(db):
    await seed(db)
    await admit_pending(db)
    before = await snapshot(db)
    service = OrderEditingService(db)
    await raises_edit(service.lookup("qa-wrong-target", OP, ADMIN), 404, "OPERATION_NOT_FOUND")
    await raises_edit(service.resume("qa-wrong-target", OP, ADMIN), 404, "OPERATION_NOT_FOUND")
    assert await snapshot(db) == before


@mongo_case
async def test_disable_pending_survives_restart_and_preserves_admission_identity(db):
    await seed(db)
    pending = await admit_pending(db)
    await db.order_operation_settings.update_one({"_id": "order-edit-v1"}, {"$set": {"enabled": False}})
    receipt(await OrderEditingService(db).lookup(ORDER, OP, ADMIN), "pending", 202)
    receipt(await OrderEditingService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    _, _, applied = await assert_effect(db)
    for field in ("_id", "command", "payload_digest", "created_at", "actor_id", "actor_role", "restaurant_id"):
        assert applied[field] == pending[field]
    before = await snapshot(db)
    receipt(await OrderEditingService(db).edit(ORDER, command(), ADMIN), "replayed", 200, version=VERSION + 1)
    await raises_edit(OrderEditingService(db).edit(ORDER, command("qa_s203_disabled_new_01", VERSION + 1, notes=None), ADMIN), 503)
    assert await snapshot(db) == before


@mongo_case
async def test_admin_disabled_after_transaction_snapshot_cannot_commit(db):
    original = await seed(db)
    faults = Faults()
    async def disable(name, result):
        if name == "users" and result and result.get("id") == ADMIN["id"] and not faults.injections:
            faults.injections += 1
            await db.users.update_one({"id": ADMIN["id"]}, {"$set": {"account_disabled": True}})
    faults.after_read = disable
    await raises_edit(OrderEditingService(DatabaseProxy(db, faults)).edit(ORDER, command(), ADMIN), 403)
    assert faults.injections == 1
    await unchanged_business(db, original)
    pending = await db.order_operations.find_one({"_id": operation_key(ADMIN["id"], OP)})
    assert pending["state"] == "pending", "Auth loss must not turn uncertainty into business rejection"


@mongo_case
async def test_two_admins_compete_on_one_real_revision_exactly_one_edit(db):
    await seed(db)
    gate = asyncio.Event()
    readers = set()
    faults = Faults()
    async def barrier(name, result):
        task = asyncio.current_task()
        if name == "orders" and result and len(readers) < 2 and task not in readers:
            readers.add(task)
            if len(readers) == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), 5)
    faults.after_read = barrier
    cmds = [command(), command(customer_name="QA Second Admin Candidate")]
    services = [OrderEditingService(DatabaseProxy(db, faults)), OrderEditingService(DatabaseProxy(db, faults))]
    outcomes = await asyncio.wait_for(asyncio.gather(*(
        service.edit(ORDER, cmd, actor) for service, cmd, actor in zip(services, cmds, (ADMIN, OTHER))
    )), 15)
    outcomes = [await settle(db, out, actor=actor) for out, actor in zip(outcomes, (ADMIN, OTHER))]
    assert len(readers) == 2, "Both transactions must have read the competing order snapshot"
    assert sorted(out.result.state for out in outcomes) == ["applied", "rejected"]
    winner = next(i for i, out in enumerate(outcomes) if out.result.state == "applied")
    await assert_effect(db, changes=cmds[winner].changes.model_dump(exclude_unset=True), actor=(ADMIN, OTHER)[winner])
    assert await db.order_operations.count_documents({}) == 2
    assert next(out for out in outcomes if out.result.state == "rejected").status_code == 409


@mongo_case
async def test_same_identity_concurrent_requests_one_revision_one_audit_one_ledger(db):
    await seed(db)
    gate = asyncio.Event()
    async def caller():
        await gate.wait()
        return await OrderEditingService(db).edit(ORDER, command(), ADMIN)
    tasks = [asyncio.create_task(caller()) for _ in range(6)]
    gate.set()
    outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 15)
    for outcome in outcomes:
        resolved = await settle(db, outcome)
        assert resolved.result.state in {"applied", "replayed"}
        assert resolved.status_code == 200 and resolved.result.order_version == VERSION + 1
    assert await db.order_operations.count_documents({}) == 1
    await assert_effect(db)


@mongo_case
async def test_preparing_route_wins_after_edit_snapshot_no_lost_preparation(db, monkeypatch):
    await seed(db)
    import routers.orders as orders_router
    monkeypatch.setattr(orders_router, "db", db)
    async def available():
        return 1
    monkeypatch.setattr(orders_router, "get_available_driver_count", available)
    faults = Faults()
    async def prepare(name, result):
        if name == "orders" and result and not faults.injections:
            faults.injections += 1
            from models.order import PreparationTime
            await orders_router.set_preparing(ORDER, PreparationTime(preparation_time=30), ADMIN)
    faults.after_read = prepare
    outcome = await OrderEditingService(DatabaseProxy(db, faults)).edit(ORDER, command(), ADMIN)
    outcome = await settle(db, outcome)
    receipt(outcome, "rejected", 409)
    assert faults.injections == 1
    stored = await db.orders.find_one({"id": ORDER})
    assert stored["order_version"] == VERSION + 1
    assert stored["status"] == "PREPARING" and stored["preparation_time"] == 30
    assert stored["customer_name"] == CONTACT["customer_name"]
    assert len(stored["audit_trail"]) == 1
    assert not await db.audit_logs.find_one({"action": "order.corrected"})


@pytest.mark.parametrize("replacement", [None, True, 7.0, [7]])
@mongo_case
async def test_revision_type_change_after_snapshot_is_not_numeric_equal_cas(db, replacement):
    await seed(db)
    faults = Faults()
    async def corrupt(name, result):
        if name == "orders" and result and not faults.injections:
            faults.injections += 1
            await db.orders.update_one({"id": ORDER}, {"$set": {"order_version": replacement}})
    faults.after_read = corrupt
    outcome = await OrderEditingService(DatabaseProxy(db, faults)).edit(ORDER, command(), ADMIN)
    receipt(await settle(db, outcome), "rejected", 409)
    assert faults.injections == 1
    stored = await db.orders.find_one({"id": ORDER})
    assert stored["customer_name"] == CONTACT["customer_name"]
    assert stored["order_version"] == replacement and type(stored["order_version"]) is type(replacement)
    assert stored["audit_trail"] == [] and await db.audit_logs.count_documents({}) == 0


@mongo_case
async def test_critical_audit_failure_rolls_back_order_embedded_audit_and_ledger(db, caplog):
    original = await seed(db)
    faults = Faults()
    faults.audit_failure = OperationFailure("QA private audit failure " + PII[7], code=121)
    caplog.set_level("INFO", logger="utils.order_editing")
    receipt(await OrderEditingService(DatabaseProxy(db, faults)).edit(ORDER, command(), ADMIN), "pending", 202)
    assert faults.audit_attempts >= 1 and faults.injections >= 1
    await unchanged_business(db, original)
    assert (await db.order_operations.find_one({}))["state"] == "pending"
    private_free(caplog.text)
    receipt(await OrderEditingService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db)


class LedgerFailureCollection(CollectionProxy):
    def __getattr__(self, method):
        delegate = super().__getattr__(method)
        if method not in ASYNC_CALLS:
            return delegate
        async def call(*args, **kwargs):
            if self.real.name == "order_operations" and method in WRITES and kwargs.get("session") is not None:
                self.faults.injections += 1
                raise OperationFailure("QA ledger completion failure", code=121)
            return await delegate(*args, **kwargs)
        return call


class LedgerFailureDatabase(DatabaseProxy):
    def get_collection(self, name, *args, **kwargs):
        return LedgerFailureCollection(self.real.get_collection(name, *args, **kwargs), self.faults)


@mongo_case
async def test_terminal_ledger_write_failure_cannot_publish_order_or_audits(db):
    original = await seed(db)
    faults = Faults()
    receipt(await OrderEditingService(LedgerFailureDatabase(db, faults)).edit(ORDER, command(), ADMIN), "pending", 202)
    assert faults.injections >= 1
    await unchanged_business(db, original)
    assert (await db.order_operations.find_one({}))["state"] == "pending"
    receipt(await OrderEditingService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db)


@mongo_case
async def test_transient_body_retry_is_finite_and_not_terminal_rejection(db):
    original = await seed(db)
    faults = Faults()
    faults.audit_failure = OperationFailure("QA transient write conflict", code=112, details={
        "errorLabels": ["TransientTransactionError"],
    })
    receipt(await OrderEditingService(DatabaseProxy(db, faults)).edit(ORDER, command(), ADMIN), "pending", 202)
    assert faults.sessions == 3 and faults.audit_attempts == 3
    await unchanged_business(db, original)
    assert (await db.order_operations.find_one({}))["state"] == "pending"
    receipt(await OrderEditingService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db)


@pytest.mark.parametrize("losses", [1, 3])
@mongo_case
async def test_lost_commit_ack_retries_same_transaction_and_restart_replays_once(db, losses):
    await seed(db)
    faults = Faults()
    faults.ack_losses = losses
    outcome = await OrderEditingService(DatabaseProxy(db, faults)).edit(ORDER, command(), ADMIN)
    assert faults.injections == losses
    assert faults.commits == (2 if losses == 1 else 3)
    assert faults.sessions == 1, "Unknown commit must not reexecute the transaction body"
    assert outcome.result.state in {"applied", "pending"}
    replay = await OrderEditingService(db).lookup(ORDER, OP, ADMIN)
    receipt(replay, "replayed", 200, version=VERSION + 1)
    receipt(await OrderEditingService(db).resume(ORDER, OP, ADMIN), "replayed", 200, version=VERSION + 1)
    await assert_effect(db)


class AdmissionAckCollection(CollectionProxy):
    def __getattr__(self, method):
        delegate = super().__getattr__(method)
        if method != "insert_one" or self.real.name != "order_operations":
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
async def test_lost_admission_ack_is_not_rejected_and_same_intent_can_resume(db, caplog):
    await seed(db)
    faults = Faults()
    caplog.set_level("INFO", logger="utils.order_editing")
    outcome = await OrderEditingService(AdmissionAckDatabase(db, faults)).edit(ORDER, command(), ADMIN)
    assert faults.injections == 1
    assert outcome.result.state in {"pending", "applied"}
    stored = await db.order_operations.find_one({"_id": operation_key(ADMIN["id"], OP)})
    assert stored["state"] in {"pending", "applied"}
    outcome = await settle(db, outcome)
    assert outcome.result.state in {"applied", "replayed"}
    await assert_effect(db)
    private_free(caplog.text)


class ObservedCleanupSession(SessionProxy):
    async def abort_transaction(self):
        if self.faults.delay_active:
            self.faults.cleanup_overlap.append("abort while delegate active")
        return await self.real.abort_transaction()

    async def end_session(self):
        if self.faults.delay_active:
            self.faults.cleanup_overlap.append("end while delegate active")
        try:
            return await self.real.end_session()
        finally:
            self.faults.cleanup_finished.set()


@mongo_case
async def test_deadline_after_admission_is_finite_pending_then_recoverable(db, monkeypatch):
    original = await seed(db)
    await admit_pending(db)
    faults = Faults()
    faults.session_factory = ObservedCleanupSession
    faults.delay = ("order_operations", "find_one", True)
    faults.delay_release = asyncio.Event()
    assert editing_module.DEADLINE_SECONDS == 10
    monkeypatch.setattr(editing_module, "DEADLINE_SECONDS", 0.05)
    started = time.monotonic()
    try:
        outcome = await asyncio.wait_for(OrderEditingService(DatabaseProxy(db, faults)).resume(ORDER, OP, ADMIN), 1)
        receipt(outcome, "pending", 202)
        assert time.monotonic() - started < 1
        assert faults.injections == 1 and faults.delay_active
        await unchanged_business(db, original)
    finally:
        faults.delay_release.set()
        if faults.injections:
            await await_thread_event(faults.delay_done)
            await await_thread_event(faults.cleanup_finished)
        assert not faults.cleanup_overlap
    monkeypatch.setattr(editing_module, "DEADLINE_SECONDS", 10)
    receipt(await OrderEditingService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db)


@mongo_case
async def test_cancelled_pre_admission_read_has_no_side_effect_and_original_id_remains_usable(db):
    await seed(db)
    before = await snapshot(db)
    faults = Faults()
    faults.delay = ("order_operations", "find_one", False)
    faults.delay_release = asyncio.Event()
    task = asyncio.create_task(OrderEditingService(DatabaseProxy(db, faults)).edit(ORDER, command(), ADMIN))
    try:
        async with asyncio.timeout(2):
            while not faults.delay_active:
                assert not task.done(), "Pre-admission cancellation boundary not reached"
                await asyncio.sleep(0.01)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        assert done
        if not task.cancelled():
            with pytest.raises(EditingError) as error:
                task.result()
            assert error.value.status_code == 503
        assert await snapshot(db) == before
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
    assert await snapshot(db) == before
    receipt(await OrderEditingService(db).edit(ORDER, command(), ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db)


class PausedSessionClient(ClientProxy):
    async def start_session(self, *args, **kwargs):
        session = await super().start_session(*args, **kwargs)
        self.faults.session_started.set()
        await self.faults.session_release.wait()
        return session


class PausedSessionDatabase(DatabaseProxy):
    def __init__(self, real, faults):
        super().__init__(real, faults)
        self.client = PausedSessionClient(real.client, faults)


@mongo_case
async def test_cancelled_session_creation_observes_and_closes_session_before_restart(db):
    original = await seed(db)
    await admit_pending(db)
    faults = Faults()
    faults.session_started = threading.Event()
    faults.session_release = asyncio.Event()
    faults.session_factory = ObservedCleanupSession
    task = asyncio.create_task(OrderEditingService(PausedSessionDatabase(db, faults)).resume(ORDER, OP, ADMIN))
    try:
        await await_thread_event(faults.session_started)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        assert done
        if not task.cancelled():
            receipt(task.result(), "pending", 202)
        assert not faults.cleanup_finished.is_set(), "Session cannot close while start worker is unresolved"
        await unchanged_business(db, original)
        assert (await db.order_operations.find_one({}))["state"] == "pending"
    finally:
        faults.session_release.set()
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert done
        if not task.cancelled():
            task.exception()
        if faults.session_started.is_set():
            await await_thread_event(faults.cleanup_finished)
    receipt(await OrderEditingService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db)


@pytest.mark.parametrize("boundary", [
    ("order_operations", "find_one", True), ("users", "update_one", True),
    ("orders", "find_one_and_update", True), ("audit_logs", "insert_one", True),
    ("order_operations", "update_one", True),
])
@mongo_case
async def test_request_cancellation_after_admission_never_forges_terminal_result(db, boundary):
    original = await seed(db)
    await admit_pending(db)
    faults = Faults()
    faults.session_factory = ObservedCleanupSession
    faults.delay = boundary
    faults.delay_release = asyncio.Event()
    task = asyncio.create_task(OrderEditingService(DatabaseProxy(db, faults)).resume(ORDER, OP, ADMIN))
    try:
        async with asyncio.timeout(2):
            while not faults.delay_active:
                assert not task.done(), "Cancellation fault boundary was not reached"
                await asyncio.sleep(0.01)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        assert done, "Cancelled request exceeded independent 1s bound"
        if not task.cancelled():
            receipt(task.result(), "pending", 202)
        assert (await db.order_operations.find_one({}))["state"] == "pending"
        await unchanged_business(db, original)
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
    receipt(await OrderEditingService(db).resume(ORDER, OP, ADMIN), "applied", 200, version=VERSION + 1)
    await assert_effect(db)


class CommitWorkerSession(SessionProxy):
    async def commit_transaction(self):
        def worker():
            self.faults.worker_started.set()
            self.faults.worker_active.set()
            try:
                time.sleep(0.3)
            finally:
                self.faults.worker_active.clear()
                self.faults.worker_done.set()
        await asyncio.get_running_loop().run_in_executor(None, worker)
        return await super().commit_transaction()

    async def abort_transaction(self):
        if self.faults.worker_active.is_set():
            self.faults.overlap.append("abort while commit worker active")
        self.faults.cleanup_entries.append("abort")
        return await self.real.abort_transaction()

    async def end_session(self):
        if self.faults.worker_active.is_set():
            self.faults.overlap.append("end while commit worker active")
        self.faults.cleanup_entries.append("end")
        try:
            return await self.real.end_session()
        finally:
            self.faults.cleanup_observed.set()


@mongo_case
async def test_cancelled_commit_waiter_observes_surviving_worker_before_session_cleanup(db):
    await seed(db)
    faults = Faults()
    faults.worker_started, faults.worker_active, faults.worker_done = (threading.Event() for _ in range(3))
    faults.cleanup_observed = threading.Event()
    faults.overlap, faults.cleanup_entries = [], []
    sessions = []
    def factory(real, config):
        sessions.append(real)
        return CommitWorkerSession(real, config)
    faults.session_factory = factory
    task = asyncio.create_task(OrderEditingService(DatabaseProxy(db, faults)).edit(ORDER, command(), ADMIN))
    try:
        await await_thread_event(faults.worker_started)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        assert done
        if not task.cancelled():
            receipt(task.result(), "pending", 202)
        await await_thread_event(faults.worker_done)
        await await_thread_event(faults.cleanup_observed)
        assert not faults.overlap
        assert faults.cleanup_entries == ["end"], "Successful surviving commit must not be aborted"
        receipt(await OrderEditingService(db).lookup(ORDER, OP, ADMIN), "replayed", 200, version=VERSION + 1)
        await assert_effect(db)
    finally:
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert done
        if not task.cancelled():
            task.exception()
        if faults.worker_started.is_set():
            await await_thread_event(faults.worker_done)
            await await_thread_event(faults.cleanup_observed)
        for session in sessions:
            await asyncio.wait_for(session.end_session(), 2)


@pytest.mark.parametrize("corruption", [
    {"actor_id": "qa-foreign"}, {"actor_role": "restaurant"},
    {"restaurant_id": "qa-foreign"}, {"payload_digest": "0" * 64},
    {"client_operation_id": "qa_s203_forged_metadata_01"},
    {"command.client_operation_id": "qa_s203_forged_command_01"},
    {"command.expected_order_version": True}, {"command.changes.customer_name": PII[0]},
    {"target_order_id": "qa-corrupt-target"}, {"contract_version": True},
    {"operation_type": "create"}, {"request_id": PII[7]}, {"created_at": "2026-10-07"},
    {"state": "unknown"}, {"state": "applied", "order_version": None},
    {"state": "applied", "order_id": {"unsafe": PII[0]}},
    {"state": "rejected", "error_status": 200, "error_code": "NO_CHANGES"},
])
@mongo_case
async def test_corrupt_ledger_is_sanitized_and_cannot_be_repaired_or_executed(db, corruption, caplog):
    await seed(db)
    pending = await admit_pending(db)
    await db.order_operations.update_one({"_id": pending["_id"]}, {"$set": corruption})
    before = await snapshot(db)
    caplog.set_level("INFO", logger="utils.order_editing")
    service = OrderEditingService(db)
    for action in (lambda: service.edit(ORDER, command(), ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN)):
        await raises_edit(action(), 503, "OPERATION_INVALID")
        assert await snapshot(db) == before
    private_free(caplog.text)


@mongo_case
async def test_review_new_address_with_explicit_unchanged_coordinates_is_stable_rejection(db):
    original = await seed(db)
    cmd = command(customer_address=REVISED["customer_address"],
                  customer_latitude=CONTACT["customer_latitude"],
                  customer_longitude=CONTACT["customer_longitude"])
    result = receipt(await OrderEditingService(db).edit(ORDER, cmd, ADMIN), "rejected", 409)
    assert result.error_code == "COORDINATES_REQUIRED"
    await unchanged_business(db, original)
    ledger = await db.order_operations.find_one({"_id": operation_key(ADMIN["id"], OP)})
    assert ledger["state"] == "rejected" and ledger["error_code"] == "COORDINATES_REQUIRED"
    assert ledger["error_status"] == 409
    # Alter the coordinate snapshot so reevaluation could now accept this pair.
    # A terminal rejected intent must still replay the historical rejection.
    await db.orders.update_one({"id": ORDER}, {"$set": {
        "customer_latitude": REVISED["customer_latitude"],
        "customer_longitude": REVISED["customer_longitude"],
    }})
    before = await snapshot(db)
    service = OrderEditingService(db)
    for action in (lambda: service.edit(ORDER, cmd, ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN)):
        assert receipt(await action(), "rejected", 409) == result
        assert await snapshot(db) == before


@pytest.mark.parametrize("request_id", [Int64(7), {"private": PII[7]}])
@mongo_case
async def test_review_nonstring_request_id_is_sanitized_503_for_all_actions_without_writes(db, request_id, caplog):
    await seed(db)
    pending = await admit_pending(db)
    await db.order_operations.update_one({"_id": pending["_id"]}, {"$set": {"request_id": request_id}})
    before = await snapshot(db)
    faults = Faults()
    faults.read_only = True
    service = OrderEditingService(DatabaseProxy(db, faults))
    caplog.set_level("INFO", logger="utils.order_editing")
    for action in (lambda: service.edit(ORDER, command(), ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN)):
        await raises_edit(action(), 503, "OPERATION_INVALID")
        assert await snapshot(db) == before
    assert faults.sessions == 0
    private_free(caplog.text)


@pytest.mark.parametrize("status", [[], {}])
@mongo_case
async def test_review_nonstring_order_status_is_durable_data_invalid_not_unhandled_type_error(db, status):
    original = await seed(db, status=status)
    result = receipt(await OrderEditingService(db).edit(ORDER, command(), ADMIN), "rejected", 409)
    assert result.error_code == "ORDER_DATA_INVALID"
    await unchanged_business(db, original)
    ledger = await db.order_operations.find_one({"_id": operation_key(ADMIN["id"], OP)})
    assert ledger["state"] == "rejected" and ledger["error_code"] == "ORDER_DATA_INVALID"
    assert ledger["error_status"] == 409
    await db.orders.update_one({"id": ORDER}, {"$set": {"status": "NEW"}})
    before = await snapshot(db)
    service = OrderEditingService(db)
    for action in (lambda: service.edit(ORDER, command(), ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN)):
        assert receipt(await action(), "rejected", 409) == result
        assert await snapshot(db) == before


@pytest.mark.parametrize("residual", [
    {"cancelled_by": "qa-previous-admin"}, {"cancelled_by": ""},
    {"cancellation_reason": PII[7]}, {"cancellation_reason": ""},
])
@mongo_case
async def test_review_cancellation_residual_blocks_edit_without_customer_or_audit_effect(db, residual, caplog):
    original = await seed(db, **residual)
    caplog.set_level("INFO", logger="utils.order_editing")
    result = receipt(await OrderEditingService(db).edit(ORDER, command(), ADMIN), "rejected", 409)
    assert result.error_code == "ORDER_NOT_EDITABLE"
    await unchanged_business(db, original)
    before = await snapshot(db)
    service = OrderEditingService(db)
    for action in (lambda: service.edit(ORDER, command(), ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN)):
        assert receipt(await action(), "rejected", 409) == result
        assert await snapshot(db) == before
    private_free(caplog.text)


@pytest.mark.parametrize("terminal,changes,unset", [
    ("applied", {"error_status": 409}, None),
    ("applied", {"retry_after_seconds": 2}, None),
    ("applied", {"resolved_at": None}, None),
    ("applied", {"resolved_at": Int64(7)}, None),
    ("applied", {"resolved_at": {"private": PII[7]}}, None),
    ("applied", {"resolved_at": "2026-10-07T12:00:00"}, None),
    ("applied", {}, "resolved_at"),
    ("rejected", {"error_status": 200}, None),
    ("rejected", {"error_status": True}, None),
    ("rejected", {"error_status": "409"}, None),
    ("rejected", {"error_status": 404}, None),
    ("rejected", {"retry_after_seconds": 2}, None),
    ("rejected", {"resolved_at": None}, None),
    ("rejected", {"resolved_at": "not-a-server-timestamp"}, None),
    ("rejected", {"resolved_at": "2026-10-07T12:00:00"}, None),
    ("rejected", {}, "resolved_at"),
])
@mongo_case
async def test_review_contradictory_terminal_receipt_is_sanitized_503_read_only(db, terminal, changes, unset, caplog):
    await seed(db)
    cmd = command() if terminal == "applied" else command(customer_name=CONTACT["customer_name"])
    if terminal == "applied":
        receipt(await OrderEditingService(db).edit(ORDER, cmd, ADMIN), "applied", 200, version=VERSION + 1)
        await assert_effect(db)
    else:
        result = receipt(await OrderEditingService(db).edit(ORDER, cmd, ADMIN), "rejected", 409)
        assert result.error_code == "NO_CHANGES"
    update = {"$set": changes} if changes else {"$unset": {unset: ""}}
    await db.order_operations.update_one({"_id": operation_key(ADMIN["id"], OP)}, update)
    before = await snapshot(db)
    faults = Faults()
    faults.read_only = True
    service = OrderEditingService(DatabaseProxy(db, faults))
    caplog.set_level("INFO", logger="utils.order_editing")
    for action in (lambda: service.edit(ORDER, cmd, ADMIN), lambda: service.lookup(ORDER, OP, ADMIN),
                   lambda: service.resume(ORDER, OP, ADMIN)):
        await raises_edit(action(), 503, "OPERATION_INVALID")
        assert await snapshot(db) == before
    assert faults.sessions == 0
    private_free(caplog.text)
