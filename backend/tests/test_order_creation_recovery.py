"""Independent service QA: owned loopback Mongo only, no app/env imports.

The parent runner supplies backend import paths. No async pytest plugin needed.
Synthetic databases are unique per case and retained as evidence.
"""

import asyncio
from dataclasses import is_dataclass
from functools import wraps
import gc
import json
import re
import threading
import time
import uuid

from bson.int64 import Int64
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
from pydantic import ValidationError
from pymongo.errors import AutoReconnect, OperationFailure

from models.order_mutation import CreateOrderCommand, MutationResult, build_mutation_intent
from utils.order_creation import (
    CreationError, CreationOutcome, OrderCreationService, operation_key,
)
import utils.order_creation as creation_module


URI = "mongodb://127.0.0.1:27941/?replicaSet=pd_stage1_probe"
OP = "qa_s202_operation_0001"
ACTOR = {"id": "qa-owner", "role": "restaurant", "restaurant_id": "qa-restaurant"}
PII = ("QA Customer Sentinel", "0700000099", "QA Private Address 123", "QA secret note")
COLLECTIONS = (
    "users", "restaurants", "counters", "order_operation_settings",
    "order_operations", "orders", "audit_logs", "delivery_zones",
)
WRITES = {
    "insert_one", "insert_many", "update_one", "update_many", "replace_one",
    "find_one_and_update", "find_one_and_replace", "find_one_and_delete",
    "delete_one", "delete_many", "bulk_write", "create_index", "create_indexes",
    "drop", "drop_index", "drop_indexes",
}
ASYNC_CALLS = WRITES | {"find_one", "count_documents", "index_information"}


def command(op=OP, **changes):
    order = {
        "restaurant_id": ACTOR["restaurant_id"], "customer_name": PII[0],
        "customer_phone": PII[1], "customer_address": PII[2], "notes": PII[3],
        "total_amount": 32.5, "payment_type": "CASH", "source": "qa",
    }
    order.update(changes)
    return CreateOrderCommand(client_operation_id=op, order=order)


def assert_private_free(value):
    rendered = json.dumps(value, default=str)
    for sentinel in PII:
        assert sentinel not in rendered


def receipt(outcome, state, status):
    assert type(outcome) is CreationOutcome and is_dataclass(outcome)
    assert type(outcome.result) is MutationResult
    assert outcome.status_code == status
    assert outcome.result.state == state
    data = outcome.result.model_dump(mode="json")
    assert set(data) == {
        "client_operation_id", "state", "order_id", "order_version",
        "error_code", "retry_after_seconds",
    }
    assert_private_free(data)
    if state in {"applied", "replayed"}:
        assert outcome.result.order_id
        assert outcome.result.order_version == 0
    if state == "pending":
        assert outcome.result.order_id is None
        assert outcome.result.order_version is None
        assert 1 <= outcome.result.retry_after_seconds <= 60
    return outcome.result


async def raises_creation(awaitable, status, code):
    with pytest.raises(CreationError) as error:
        await awaitable
    assert error.value.status_code == status
    assert error.value.code == code
    assert re.fullmatch(r"[A-Z][A-Z0-9_]*", error.value.code)
    assert isinstance(error.value.message, str) and error.value.message
    assert_private_free(str(error.value))


@pytest.fixture
def db():
    """Return a sync runner; all Motor use stays inside one asyncio.run loop."""
    def run(scenario):
        async def isolated():
            import runtime

            assert runtime.PORT == 27941 and runtime.SET == "pd_stage1_probe"
            assert runtime.URI == URI
            state = json.loads(runtime.STATE.read_text(encoding="utf-8"))
            with runtime.direct() as verifier:
                runtime.verify_owned(verifier, state)
                hello = verifier.admin.command("hello")
                assert hello.get("isWritablePrimary") is True
                assert hello.get("setName") == "pd_stage1_probe"
            client = AsyncIOMotorClient(
                URI, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000,
                socketTimeoutMS=4000,
            )
            database = client["pd_s202_qa_" + uuid.uuid4().hex]
            try:
                for name in COLLECTIONS:
                    await database.create_collection(name)
                await database.users.insert_one({**ACTOR, "account_disabled": False})
                await database.restaurants.insert_one({
                    "id": ACTOR["restaurant_id"], "name": "QA Synthetic Restaurant",
                    "accepting_orders": True, "closed_today": False,
                })
                await database.counters.insert_one({"_id": "orders.global", "seq": 100})
                await database.order_operation_settings.insert_one({"_id": "order-create-v1", "enabled": True})
                await asyncio.wait_for(scenario(database), timeout=35)
            finally:
                client.close()
        return asyncio.run(isolated())
    return run


def mongo_case(fn):
    @wraps(fn)
    def wrapped(db, *args, **kwargs):
        return db(lambda database: fn(database, *args, **kwargs))
    return wrapped


class SimulatedCrash(BaseException):
    """Application process stopped after durable admission, before execution."""


class Faults:
    def __init__(self):
        self.after_admission_crash = False
        self.audit_failure = None
        self.after_read = None
        self.ack_losses = 0
        self.commits = 0
        self.sessions = 0
        self.audit_attempts = 0
        self.injections = 0
        self.read_only = False
        self.standalone = False
        self.delay = None
        self.session_factory = SessionProxy
        self.worker_boundary = None
        self.delay_release = None
        self.delay_active = False
        self.delay_done = threading.Event()
        self.cleanup_overlap = []
        self.cleanup_finished = threading.Event()


class CollectionProxy:
    def __init__(self, real, faults):
        self.real, self.faults = real, faults

    def __getattr__(self, method):
        target = getattr(self.real, method)
        if method not in ASYNC_CALLS and method != "find":
            return target

        def kwargs_for_real(kwargs):
            session = kwargs.get("session")
            if isinstance(session, SessionProxy):
                kwargs = {**kwargs, "session": session.real}
            return kwargs

        if method == "find":
            return lambda *args, **kwargs: target(*args, **kwargs_for_real(kwargs))

        async def call(*args, **kwargs):
            faults = self.faults
            if faults.read_only and method in WRITES:
                raise AssertionError(f"Read-only lookup attempted {self.real.name}.{method}")
            if faults.delay == (self.real.name, method, kwargs.get("session") is not None):
                faults.injections += 1
                if faults.delay_release is None:
                    await asyncio.sleep(60)
                else:
                    faults.delay_active = True
                    try:
                        await faults.delay_release.wait()
                    finally:
                        faults.delay_active = False
                        faults.delay_done.set()
                    raise AutoReconnect("QA stalled delegate completed with timeout")
            if self.real.name == "audit_logs" and method == "insert_one":
                faults.audit_attempts += 1
                if faults.audit_failure:
                    faults.injections += 1
                    raise faults.audit_failure
            result = await target(*args, **kwargs_for_real(kwargs))
            if faults.worker_boundary == (self.real.name, method) and kwargs.get("session") is not None:
                await noncancellable_executor_pause(faults)
            if self.real.name == "order_operations" and method == "insert_one" and faults.after_admission_crash:
                assert kwargs.get("session") is None, "Admission must be durable outside business tx"
                faults.injections += 1
                raise SimulatedCrash()
            if method == "find_one" and kwargs.get("session") is not None and faults.after_read:
                await faults.after_read(self.real.name, result)
            return result
        return call


class SessionProxy:
    def __init__(self, real, faults):
        self.real, self.faults = real, faults

    def __getattr__(self, name):
        return getattr(self.real, name)

    async def __aenter__(self):
        await self.real.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.real.__aexit__(*args)

    async def commit_transaction(self):
        self.faults.commits += 1
        await self.real.commit_transaction()
        if self.faults.ack_losses > 0:
            self.faults.ack_losses -= 1
            self.faults.injections += 1
            raise OperationFailure("QA lost ACK", code=91, details={
                "errorLabels": ["UnknownTransactionCommitResult"],
            })


class ClientProxy:
    def __init__(self, real, faults):
        self.real, self.faults = real, faults

    async def start_session(self, *args, **kwargs):
        assert not self.faults.read_only, "Lookup must not open a write transaction"
        self.faults.sessions += 1
        return self.faults.session_factory(await self.real.start_session(*args, **kwargs), self.faults)

    def __getattr__(self, name):
        return getattr(self.real, name)


class DatabaseProxy:
    def __init__(self, real, faults):
        self.real, self.faults = real, faults
        self.client = ClientProxy(real.client, faults)

    def get_collection(self, name, *args, **kwargs):
        return CollectionProxy(self.real.get_collection(name, *args, **kwargs), self.faults)

    def __getitem__(self, name):
        return self.get_collection(name)

    def __getattr__(self, name):
        if name in COLLECTIONS:
            return self.get_collection(name)
        return getattr(self.real, name)

    async def command(self, name, *args, **kwargs):
        if self.faults.standalone and name == "hello":
            self.faults.injections += 1
            return {"isWritablePrimary": True, "maxWireVersion": 25}
        assert not self.faults.read_only or name in {"hello", "ping"}
        return await self.real.command(name, *args, **kwargs)


async def snapshot(db):
    return {
        name: await db[name].find({}).sort("_id", 1).to_list(10000)
        for name in await db.list_collection_names()
    }


async def assert_business(db, count, base=100):
    assert await db.orders.count_documents({}) == count
    assert await db.audit_logs.count_documents({}) == count
    counter = await db.counters.find_one({"_id": "orders.global"})
    assert counter["seq"] == base + count
    orders = await db.orders.find({}).to_list(1000)
    assert len({doc["order_number"] for doc in orders}) == count
    for doc in orders:
        assert "order_version" not in doc, "Receipt v0 must not activate order revision/CAS"
        assert len(doc["audit_trail"]) == 1
        audit = await db.audit_logs.find_one({"entity_id": doc["id"]})
        assert audit["action"] == "order.created"
        assert audit["operation_ref"] == doc["creation_operation_ref"]
        assert_private_free(audit)


async def admit_pending(db, cmd=None):
    cmd = cmd or command()
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderCreationService(DatabaseProxy(db, faults)).create(cmd, ACTOR)
    assert faults.injections == 1
    pending = await db.order_operations.find_one({"_id": operation_key(ACTOR["id"], cmd.client_operation_id)})
    assert pending["state"] == "pending"
    assert pending["command"] == cmd.model_dump(mode="json")
    assert pending["payload_digest"] == build_mutation_intent(ACTOR["id"], "create", None, cmd).payload_digest
    await assert_business(db, 0)
    return pending


@mongo_case
async def test_atomic_create_replay_private_receipt_and_immutable_intent(db, caplog):
    caplog.set_level("INFO", logger="utils.order_creation")
    service = OrderCreationService(db)
    cmd = command()
    first = receipt(await service.create(cmd, ACTOR), "applied", 201)
    before = await snapshot(db)
    replay = receipt(await service.create(cmd, ACTOR), "replayed", 200)
    assert replay.order_id == first.order_id
    assert await snapshot(db) == before
    operation = await db.order_operations.find_one({"_id": operation_key(ACTOR["id"], OP)})
    assert operation["command"] == cmd.model_dump(mode="json")
    assert operation["payload_digest"] == build_mutation_intent(ACTOR["id"], "create", None, cmd).payload_digest
    assert operation["actor_id"] == ACTOR["id"]
    assert operation["actor_role"] == ACTOR["role"]
    assert operation["created_at"]
    assert first.order_id == str(uuid.uuid5(uuid.NAMESPACE_URL, operation["_id"]))
    await assert_business(db, 1)
    await db.orders.update_one({"id": first.order_id}, {"$set": {"status": "DELIVERED", "order_version": 99}})
    assert receipt(await service.lookup(OP, ACTOR), "replayed", 200).order_version == 0
    assert_private_free(caplog.text)


@pytest.mark.parametrize("phase", ["before_admission", "after_admission", "lookup"])
@mongo_case
async def test_deadline_cancels_stalled_io_with_truthful_finite_outcome(db, phase, monkeypatch, caplog):
    assert creation_module.DEADLINE_SECONDS == 10
    assert creation_module.MAX_ATTEMPTS == 3 and creation_module.MAX_COMMIT_ATTEMPTS == 3
    caplog.set_level("INFO", logger="utils.order_creation")
    faults = Faults()
    faults.delay = ("order_operations", "find_one", phase == "after_admission")
    service = OrderCreationService(DatabaseProxy(db, faults))
    before = await snapshot(db)
    monkeypatch.setattr(creation_module, "DEADLINE_SECONDS", 0.1)
    started = time.monotonic()
    if phase == "after_admission":
        receipt(await service.create(command(), ACTOR), "pending", 202)
        assert (await db.order_operations.find_one({}))["state"] == "pending"
        await assert_business(db, 0)
    elif phase == "lookup":
        await raises_creation(service.lookup(OP, ACTOR), 503, "RECOVERY_UNAVAILABLE")
        assert await snapshot(db) == before
    else:
        await raises_creation(service.create(command(), ACTOR), 503, "CREATION_UNAVAILABLE")
        assert await snapshot(db) == before
    assert time.monotonic() - started < 2
    assert faults.injections == 1
    assert_private_free(caplog.text)


@mongo_case
async def test_pending_lookup_read_only_then_recovery_even_after_activation_disabled(db):
    pending = await admit_pending(db)
    await db.order_operation_settings.update_one({"_id": "order-create-v1"}, {"$set": {"enabled": False}})
    before = await snapshot(db)
    faults = Faults()
    faults.read_only = True
    receipt(await OrderCreationService(DatabaseProxy(db, faults)).lookup(OP, ACTOR), "pending", 202)
    assert await snapshot(db) == before
    service = OrderCreationService(db)
    receipt(await service.create(command(), ACTOR), "applied", 201)
    after = await db.order_operations.find_one({"_id": pending["_id"]})
    for field in ("_id", "command", "payload_digest", "created_at", "actor_id", "actor_role", "restaurant_id"):
        assert after[field] == pending[field]
    await assert_business(db, 1)
    await raises_creation(service.create(command("qa_new_disabled_0001"), ACTOR), 503, "CREATION_NOT_ENABLED")
    await assert_business(db, 1)


@pytest.mark.parametrize("marker", [None, False, 1, "true"])
@mongo_case
async def test_missing_or_invalid_activation_has_no_writes_or_provisioning(db, marker):
    if marker is None:
        await db.order_operation_settings.delete_one({"_id": "order-create-v1"})
    else:
        await db.order_operation_settings.update_one({"_id": "order-create-v1"}, {"$set": {"enabled": marker}})
    before = await snapshot(db)
    indexes = {name: await db[name].index_information() for name in COLLECTIONS}
    await raises_creation(OrderCreationService(db).create(command(), ACTOR), 503, "CREATION_NOT_ENABLED")
    assert await snapshot(db) == before
    assert {name: await db[name].index_information() for name in COLLECTIONS} == indexes


@mongo_case
async def test_unsupported_topology_fails_before_admission_without_writes(db):
    faults = Faults()
    faults.standalone = True
    before = await snapshot(db)
    await raises_creation(OrderCreationService(DatabaseProxy(db, faults)).create(command(), ACTOR), 503, "TRANSACTIONS_REQUIRED")
    assert faults.injections == 1
    assert await snapshot(db) == before


@pytest.mark.parametrize("committed", [False, True])
@mongo_case
async def test_different_payload_conflict_cannot_replace_pending_or_applied_intent(db, committed):
    service = OrderCreationService(db)
    if committed:
        receipt(await service.create(command(), ACTOR), "applied", 201)
    else:
        await admit_pending(db)
    before = await snapshot(db)
    await raises_creation(service.create(command(total_amount=99.5), ACTOR), 409, "INTENT_CONFLICT")
    assert await snapshot(db) == before


@mongo_case
async def test_normalized_equivalent_payload_replays(db):
    service = OrderCreationService(db)
    first = receipt(await service.create(command(), ACTOR), "applied", 201)
    padded = command(customer_name=" " + PII[0] + " ", customer_address=" " + PII[2] + " ")
    assert receipt(await service.create(padded, ACTOR), "replayed", 200).order_id == first.order_id
    await assert_business(db, 1)


async def settle(service, cmd, actor, outcome):
    for _ in range(4):
        if outcome.result.state != "pending":
            return outcome
        outcome = await service.create(cmd, actor)
    pytest.fail("Operation did not resolve after bounded recovery")


@mongo_case
async def test_real_mongo_same_identity_concurrent_callers_exactly_once(db):
    ready = asyncio.Event()
    async def caller():
        await ready.wait()
        return await OrderCreationService(db).create(command(), ACTOR)
    tasks = [asyncio.create_task(caller()) for _ in range(12)]
    ready.set()
    outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 20)
    assert all(item.result.state in {"applied", "replayed", "pending"} for item in outcomes)
    resolved = [await settle(OrderCreationService(db), command(), ACTOR, item) for item in outcomes]
    assert len({item.result.order_id for item in resolved}) == 1
    assert await db.order_operations.count_documents({}) == 1
    await assert_business(db, 1)


@mongo_case
async def test_real_mongo_concurrent_payload_collision_one_winner(db):
    ready = asyncio.Event()
    async def caller(cmd):
        await ready.wait()
        return await OrderCreationService(db).create(cmd, ACTOR)
    commands = [command(total_amount=amount) for amount in (11.5, 22.5)]
    tasks = [asyncio.create_task(caller(cmd)) for cmd in commands]
    ready.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 20)
    errors = [result for result in results if isinstance(result, BaseException)]
    assert len(errors) == 1 and isinstance(errors[0], CreationError)
    assert (errors[0].status_code, errors[0].code) == (409, "INTENT_CONFLICT")
    winner = next(index for index, result in enumerate(results) if not isinstance(result, BaseException))
    await settle(OrderCreationService(db), commands[winner], ACTOR, results[winner])
    await assert_business(db, 1)
    stored = await db.orders.find_one({})
    assert stored["subtotal_amount"] == commands[winner].order.total_amount


@mongo_case
async def test_separate_actor_same_operation_id_is_separate_and_lookup_is_actor_scoped(db):
    other = {**ACTOR, "id": "qa-other-owner"}
    await db.users.insert_one({**other, "account_disabled": False})
    service = OrderCreationService(db)
    first = receipt(await service.create(command(), ACTOR), "applied", 201)
    await raises_creation(service.lookup(OP, other), 404, "OPERATION_NOT_FOUND")
    second = receipt(await service.create(command(), other), "applied", 201)
    assert first.order_id != second.order_id
    assert operation_key(ACTOR["id"], OP) != operation_key(other["id"], OP)
    assert await db.order_operations.count_documents({}) == 2
    await assert_business(db, 2)


@mongo_case
async def test_real_mongo_distinct_operations_counter_reconciliation(db):
    service = OrderCreationService(db)
    commands = [command(f"qa_parallel_order_{index:04d}") for index in range(8)]
    outcomes = await asyncio.wait_for(asyncio.gather(*(service.create(cmd, ACTOR) for cmd in commands)), 20)
    resolved = [await settle(service, cmd, ACTOR, out) for cmd, out in zip(commands, outcomes)]
    assert len({out.result.order_id for out in resolved}) == len(commands)
    await assert_business(db, len(commands))
    orders = await db.orders.find({}).to_list(100)
    assert sorted(int(doc["order_number"].split(".")[1]) for doc in orders) == list(range(101, 109))


@pytest.mark.parametrize("change,status,code", [
    ({"account_disabled": True}, 403, "ACCOUNT_DISABLED"),
    ({"role": "driver"}, 403, "NOT_AUTHORIZED"),
    ({"restaurant_id": "qa-foreign"}, 403, "NOT_AUTHORIZED"),
    ({"role": "admin"}, 403, "AUTH_CONTEXT_CHANGED"),
])
@mongo_case
async def test_current_actor_rejects_stale_claims_without_writes(db, change, status, code):
    await db.users.update_one({"id": ACTOR["id"]}, {"$set": change})
    before = await snapshot(db)
    await raises_creation(OrderCreationService(db).create(command(), ACTOR), status, code)
    assert await snapshot(db) == before


@mongo_case
async def test_missing_actor_and_missing_identity_fail_without_writes(db):
    await db.users.delete_one({"id": ACTOR["id"]})
    before = await snapshot(db)
    service = OrderCreationService(db)
    await raises_creation(service.create(command(), ACTOR), 401, "AUTH_REQUIRED")
    await raises_creation(service.create(command(), {"role": "admin"}), 401, "AUTH_REQUIRED")
    assert await snapshot(db) == before


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("change", [{"account_disabled": True}, {"role": "admin"}, {"restaurant_id": "qa-foreign"}])
@mongo_case
async def test_current_binding_blocks_pending_recovery_replay_and_lookup(db, committed, change):
    service = OrderCreationService(db)
    if committed:
        receipt(await service.create(command(), ACTOR), "applied", 201)
    else:
        await admit_pending(db)
    await db.users.update_one({"id": ACTOR["id"]}, {"$set": change})
    before = await snapshot(db)
    refreshed = {**ACTOR, **change}
    for actor in (ACTOR, refreshed):
        for awaitable in (service.create(command(), actor), service.lookup(OP, actor)):
            with pytest.raises(CreationError) as exc:
                await awaitable
            assert exc.value.status_code == 403
    assert await snapshot(db) == before


@pytest.mark.parametrize("change,status,code", [
    (None, 404, "RESTAURANT_NOT_FOUND"),
    ({"accepting_orders": False}, 409, "RESTAURANT_PAUSED"),
    ({"closed_today": True}, 409, "RESTAURANT_CLOSED"),
    ({"is_active": False}, 409, "RESTAURANT_UNAVAILABLE"),
    ({"account_disabled": True}, 409, "RESTAURANT_UNAVAILABLE"),
])
@mongo_case
async def test_unavailable_restaurant_rejection_is_durable_and_no_business_effect(db, change, status, code):
    if change is None:
        await db.restaurants.delete_one({"id": ACTOR["restaurant_id"]})
    else:
        await db.restaurants.update_one({"id": ACTOR["restaurant_id"]}, {"$set": change})
    service = OrderCreationService(db)
    rejected = receipt(await service.create(command(), ACTOR), "rejected", status)
    assert rejected.error_code == code
    before = await snapshot(db)
    receipt(await service.create(command(), ACTOR), "rejected", status)
    receipt(await service.lookup(OP, ACTOR), "rejected", status)
    assert await snapshot(db) == before
    await assert_business(db, 0)


@pytest.mark.parametrize("collection,change", [
    ("users", {"account_disabled": True}),
    ("users", {"role": "driver"}),
    ("users", {"restaurant_id": "qa-foreign"}),
    ("restaurants", {"accepting_orders": False}),
    ("restaurants", {"closed_today": True}),
])
@mongo_case
async def test_real_transaction_snapshot_invalidation_prevents_stale_commit(db, collection, change):
    faults = Faults()
    async def change_after_snapshot(name, result):
        if name == collection and faults.injections == 0:
            assert result is not None
            faults.injections += 1
            await asyncio.wait_for(db[name].update_one({"_id": result["_id"]}, {"$set": change}), 5)
    faults.after_read = change_after_snapshot
    try:
        outcome = await OrderCreationService(DatabaseProxy(db, faults)).create(command(), ACTOR)
    except CreationError as error:
        assert collection == "users" and error.status_code == 403
    else:
        assert collection == "restaurants"
        receipt(outcome, "rejected", 409)
    assert faults.injections == 1, "Race injection must execute after a transactional snapshot read"
    await assert_business(db, 0)


@mongo_case
async def test_atomic_audit_failure_rolls_back_counter_order_and_outcome_then_recovers(db):
    faults = Faults()
    faults.audit_failure = AutoReconnect("QA audit unavailable")
    service = OrderCreationService(DatabaseProxy(db, faults))
    receipt(await service.create(command(), ACTOR), "pending", 202)
    assert faults.audit_attempts == 1 and faults.injections == 1
    await assert_business(db, 0)
    assert (await db.order_operations.find_one({}))["state"] == "pending"
    assert "order_admission_revision" not in await db.users.find_one({"id": ACTOR["id"]})
    assert "order_admission_revision" not in await db.restaurants.find_one({"id": ACTOR["restaurant_id"]})
    faults.audit_failure = None
    receipt(await service.create(command(), ACTOR), "applied", 201)
    await assert_business(db, 1)


@mongo_case
async def test_transient_transaction_retries_are_finite_and_atomic(db):
    faults = Faults()
    faults.audit_failure = OperationFailure("QA transient", code=112, details={
        "errorLabels": ["TransientTransactionError"],
    })
    receipt(await OrderCreationService(DatabaseProxy(db, faults)).create(command(), ACTOR), "pending", 202)
    assert faults.audit_attempts == 3 and faults.sessions == 3
    assert faults.commits == 0
    await assert_business(db, 0)


@pytest.mark.parametrize("lost_acks", [1, 3])
@mongo_case
async def test_real_commit_lost_ack_finite_retries_and_no_duplicate_on_replay(db, lost_acks):
    faults = Faults()
    faults.ack_losses = lost_acks
    outcome = await OrderCreationService(DatabaseProxy(db, faults)).create(command(), ACTOR)
    receipt(outcome, "applied" if lost_acks == 1 else "pending", 201 if lost_acks == 1 else 202)
    assert faults.commits == (2 if lost_acks == 1 else 3)
    assert faults.sessions == 1 and faults.injections == lost_acks
    await assert_business(db, 1)
    service = OrderCreationService(db)
    receipt(await service.lookup(OP, ACTOR), "replayed", 200)
    receipt(await service.create(command(), ACTOR), "replayed", 200)
    await assert_business(db, 1)


@pytest.mark.parametrize("seq", [None, True, -1, "100", 100.0, 9223372036854775807])
@mongo_case
async def test_invalid_counter_no_scan_seed_or_partial_writes(db, seq):
    if seq is None:
        await db.counters.delete_one({"_id": "orders.global"})
    else:
        await db.counters.update_one({"_id": "orders.global"}, {"$set": {"seq": seq}})
    legacy = {"_id": "qa-legacy", "id": "qa-legacy", "order_number": "S.9999", "status": "DELIVERED"}
    await db.orders.insert_one(legacy)
    before_counter = await db.counters.find_one({"_id": "orders.global"})
    await raises_creation(OrderCreationService(db).create(command(), ACTOR), 503, "COUNTER_NOT_READY")
    assert await db.counters.find_one({"_id": "orders.global"}) == before_counter
    assert await db.orders.find_one({"_id": "qa-legacy"}) == legacy
    assert await db.orders.count_documents({}) == 1
    assert await db.audit_logs.count_documents({}) == 0
    assert (await db.order_operations.find_one({}))["state"] == "pending"


@pytest.mark.parametrize("changes,subtotal,fee,total", [
    ({}, 32.5, 0, 32.5),
    ({"delivery_fee": 5.0}, 32.5, 5.0, 37.5),
    ({"subtotal_amount": 20.0, "delivery_fee": 5.0}, 20.0, 5.0, 25.0),
    ({"subtotal_amount": 0.0, "delivery_fee": 0.0}, 0.0, 0.0, 0.0),
    ({"subtotal_amount": 20.125, "delivery_fee": 2.0}, 20.125, 2.0, 22.12),
])
@mongo_case
async def test_legacy_financial_semantics(db, changes, subtotal, fee, total):
    receipt(await OrderCreationService(db).create(command(**changes), ACTOR), "applied", 201)
    order = await db.orders.find_one({})
    assert (order["subtotal_amount"], order["delivery_fee"], order["total_amount"]) == (subtotal, fee, total)
    await assert_business(db, 1)


def zone(identity, low, high, **changes):
    value = {
        "id": identity, "restaurant_id": ACTOR["restaurant_id"], "is_active": True,
        "name": "QA Zone " + identity, "fee": 7.0, "sector": "QA", "zone_level": 2,
        "polygon": [
            {"lng": low, "lat": low}, {"lng": high, "lat": low},
            {"lng": high, "lat": high}, {"lng": low, "lat": high},
        ],
    }
    value.update(changes)
    return value


@mongo_case
async def test_server_smallest_active_tenant_zone_overrides_client_financial_and_zone_claims(db):
    await db.delivery_zones.insert_many([
        zone("large", 0, 10, fee=30.0), zone("small", 4, 6),
        zone("inactive", 4.5, 5.5, is_active=False, fee=100.0),
        zone("foreign", 4.5, 5.5, restaurant_id="qa-foreign", fee=100.0),
    ])
    cmd = command(customer_latitude=5.0, customer_longitude=5.0,
                  subtotal_amount=20.0, delivery_fee=999.0,
                  delivery_zone_id="client-spoof", delivery_zone_name="client-spoof",
                  delivery_sector="client-spoof", delivery_zone_level=49)
    receipt(await OrderCreationService(db).create(cmd, ACTOR), "applied", 201)
    order = await db.orders.find_one({})
    assert (order["delivery_fee"], order["total_amount"]) == (7.0, 27.0)
    assert (order["delivery_zone_id"], order["delivery_zone_name"], order["delivery_sector"], order["delivery_zone_level"]) == (
        "small", "QA Zone small", "QA", 2,
    )
    await assert_business(db, 1)


@mongo_case
async def test_no_detected_zone_discards_spoofed_metadata_without_losing_legacy_fee(db):
    cmd = command(delivery_fee=3.0, delivery_zone_id="spoof", delivery_zone_name="spoof")
    receipt(await OrderCreationService(db).create(cmd, ACTOR), "applied", 201)
    order = await db.orders.find_one({})
    assert order["delivery_fee"] == 3.0
    assert order["delivery_zone_id"] is None and order["delivery_zone_name"] is None


@pytest.mark.parametrize("fee", [-1, True, "7", float("inf")])
@mongo_case
async def test_invalid_server_zone_fee_rolls_back_increment_and_business(db, fee):
    await db.delivery_zones.insert_one(zone("invalid", 0, 10, fee=fee))
    await raises_creation(OrderCreationService(db).create(command(customer_latitude=5.0, customer_longitude=5.0), ACTOR),
                          503, "ZONE_CONFIGURATION_INVALID")
    await assert_business(db, 0)


@mongo_case
async def test_missing_and_applied_lookup_are_read_only_without_pii(db):
    faults = Faults()
    faults.read_only = True
    lookup = OrderCreationService(DatabaseProxy(db, faults))
    before = await snapshot(db)
    await raises_creation(lookup.lookup(OP, ACTOR), 404, "OPERATION_NOT_FOUND")
    assert await snapshot(db) == before
    first = receipt(await OrderCreationService(db).create(command(), ACTOR), "applied", 201)
    before = await snapshot(db)
    assert receipt(await lookup.lookup(OP, ACTOR), "replayed", 200).order_id == first.order_id
    assert await snapshot(db) == before


@pytest.mark.parametrize("field,value", [
    ("total_amount", "32"), ("total_amount", True), ("total_amount", float("nan")),
    ("customer_name", " "), ("customer_latitude", 91.0),
    ("customer_latitude", 5.0), ("unknown", "unsafe"),
])
def test_strict_creation_command_validation_without_db(field, value):
    payload = command().model_dump(mode="python")
    payload["order"][field] = value
    with pytest.raises(ValidationError):
        CreateOrderCommand.model_validate(payload)


@mongo_case
async def test_service_revalidates_constructed_command_before_any_admission(db):
    unsafe = command()
    unsafe.order.total_amount = "32"
    before = await snapshot(db)
    with pytest.raises(ValidationError):
        await OrderCreationService(db).create(unsafe, ACTOR)
    assert await snapshot(db) == before


def test_operation_key_deterministic_actor_scoped_and_separator_safe():
    assert operation_key("a", OP) == operation_key("a", OP)
    assert operation_key("a", OP) != operation_key("b", OP)
    assert operation_key("a:b", "c") != operation_key("a", "b:c")
    assert_private_free(operation_key(ACTOR["id"], OP))


@pytest.mark.parametrize("corruption", [
    "command_tenant", "command_digest", "actor_id", "metadata_identity",
    "command_identity", "stored_digest",
])
@pytest.mark.parametrize("action", ["create", "lookup"])
@mongo_case
async def test_review_f1_corrupt_admission_binding_fails_closed_without_any_writes(db, corruption, action):
    pending = await admit_pending(db)
    changes = {
        "command_tenant": {"command.order.restaurant_id": "qa-foreign"},
        "command_digest": {"command.order.total_amount": 99.5},
        "actor_id": {"actor_id": "qa-foreign-actor"},
        "metadata_identity": {"client_operation_id": "qa_forged_identity_0001", "command.client_operation_id": "qa_forged_identity_0001"},
        "command_identity": {"command.client_operation_id": "qa_forged_identity_0001"},
        "stored_digest": {"payload_digest": "0" * 64},
    }[corruption]
    await db.order_operations.update_one({"_id": pending["_id"]}, {"$set": changes})
    before = await snapshot(db)
    service = OrderCreationService(db)
    await raises_creation(service.create(command(), ACTOR) if action == "create" else service.lookup(OP, ACTOR),
                          503, "OPERATION_INVALID")
    assert await snapshot(db) == before
    await assert_business(db, 0)


class HungCleanupSession(SessionProxy):
    async def abort_transaction(self):
        if self.faults.delay_active:
            self.faults.cleanup_overlap.append("abort before delay_done")
        if self.faults.cleanup_mode == "abort_delay":
            self.faults.cleanup_injections += 1
            await asyncio.sleep(1.5)
        if self.faults.cleanup_mode == "abort_error":
            self.faults.cleanup_injections += 1
            raise RuntimeError("QA cleanup failure must not replace original cause")
        return await self.real.abort_transaction()

    async def end_session(self):
        if self.faults.delay_active:
            self.faults.cleanup_overlap.append("end before delay_done")
        if self.faults.cleanup_mode == "session_delay":
            self.faults.cleanup_injections += 1
            await asyncio.sleep(1.5)
        try:
            return await self.real.end_session()
        finally:
            self.faults.cleanup_finished.set()

    async def __aexit__(self, *args):
        if self.faults.cleanup_mode == "session_delay":
            self.faults.cleanup_injections += 1
            await asyncio.sleep(1.5)
        return await super().__aexit__(*args)


@pytest.mark.parametrize("mode", ["abort_delay", "session_delay"])
@mongo_case
async def test_review_f3_cancelled_transaction_cleanup_has_bounded_total_response(db, mode, monkeypatch):
    faults = Faults()
    faults.cleanup_mode, faults.cleanup_injections = mode, 0
    sessions = []
    def factory(real, config):
        sessions.append(real)
        return HungCleanupSession(real, config)
    faults.session_factory = factory
    faults.delay = ("order_operations", "find_one", True)
    faults.delay_release = asyncio.Event()
    monkeypatch.setattr(creation_module, "DEADLINE_SECONDS", 0.05)
    task = asyncio.create_task(OrderCreationService(DatabaseProxy(db, faults)).create(command(), ACTOR))
    completed_in_budget = False
    outcome = None
    try:
        done, _ = await asyncio.wait({task}, timeout=1.0)
        completed_in_budget = bool(done)
        if done:
            outcome = task.result()
            receipt(outcome, "pending", 202)
        assert completed_in_budget, "Deadline .05 + cleanup exceeded independent outer 1s bound"
        assert faults.injections == 1 and faults.delay_active, "Stalled delegate must remain active until release"
        assert faults.cleanup_injections == 0, "Cleanup cannot run before the original delegate completes"
        faults.delay_release.set()
        await await_thread_event(faults.delay_done)
        await await_thread_event(faults.cleanup_finished, seconds=4)
        assert faults.cleanup_injections >= 1, "Hung cleanup injection must be exercised"
        assert not faults.cleanup_overlap
    finally:
        faults.delay_release.set()
        if not task.done():
            task.cancel()
        # Observe with wait, then explicitly clean only our real synthetic sessions.
        done, _ = await asyncio.wait({task}, timeout=3.0)
        assert done, "QA test teardown itself exceeded its safety bound"
        if not task.cancelled():
            task.exception()
        if faults.delay_active:
            await await_thread_event(faults.delay_done)
        if faults.cleanup_injections:
            await await_thread_event(faults.cleanup_finished, seconds=4)
        for session in sessions:
            await asyncio.wait_for(session.end_session(), timeout=2)
    assert completed_in_budget, "Deadline .05 + cleanup exceeded independent outer 1s bound"
    assert faults.cleanup_injections >= 1, "Hung cleanup injection must be exercised"
    receipt(outcome, "pending", 202)
    await assert_business(db, 0)


@mongo_case
async def test_review_f3_abort_error_preserves_original_transient_retry_classification(db):
    faults = Faults()
    faults.cleanup_mode, faults.cleanup_injections = "abort_error", 0
    faults.session_factory = HungCleanupSession
    faults.audit_failure = OperationFailure("QA original transient", code=112, details={
        "errorLabels": ["TransientTransactionError"],
    })
    receipt(await OrderCreationService(DatabaseProxy(db, faults)).create(command(), ACTOR), "pending", 202)
    assert faults.audit_attempts == 3 and faults.sessions == 3
    assert faults.cleanup_injections == 3
    await assert_business(db, 0)


@pytest.mark.parametrize("value", [100, 2**31, 2**63 - 2])
@mongo_case
async def test_review_f4_valid_bson_int64_counter_creates_without_counter_rewrite(db, value):
    await db.counters.update_one({"_id": "orders.global"}, {"$set": {"seq": Int64(value)}})
    assert isinstance((await db.counters.find_one({}))["seq"], Int64)
    receipt(await OrderCreationService(db).create(command(), ACTOR), "applied", 201)
    await assert_business(db, 1, base=value)


@mongo_case
async def test_review_f4_valid_bson_int64_zone_fee_is_authoritative(db):
    await db.delivery_zones.insert_one(zone("bson-long", 0, 10, fee=Int64(7)))
    assert isinstance((await db.delivery_zones.find_one({}))["fee"], Int64)
    receipt(await OrderCreationService(db).create(command(customer_latitude=5.0, customer_longitude=5.0,
                                                         subtotal_amount=20.0, delivery_fee=999.0), ACTOR), "applied", 201)
    stored = await db.orders.find_one({})
    assert (stored["delivery_fee"], stored["total_amount"]) == (7.0, 27.0)
    await assert_business(db, 1)


@pytest.mark.parametrize("malformation", [
    {"state": "applied"},
    {"state": "applied", "order_id": {"unsafe": PII[0]}},
    {"state": "rejected", "error_status": 409},
    {"state": "rejected", "error_code": "RESTAURANT_PAUSED", "error_status": 200},
    {"state": "rejected", "error_code": "RESTAURANT_PAUSED", "error_status": "409"},
    {"state": "pending", "command.order.customer_phone": "bad"},
])
@pytest.mark.parametrize("action", ["create", "lookup"])
@mongo_case
async def test_review_f5_malformed_persisted_command_or_receipt_is_sanitized_server_error(db, malformation, action, caplog):
    pending = await admit_pending(db)
    await db.order_operations.update_one({"_id": pending["_id"]}, {"$set": malformation})
    before = await snapshot(db)
    caplog.set_level("INFO", logger="utils.order_creation")
    service = OrderCreationService(db)
    await raises_creation(service.create(command(), ACTOR) if action == "create" else service.lookup(OP, ACTOR),
                          503, "OPERATION_INVALID")
    assert await snapshot(db) == before
    assert_private_free(caplog.text)


@pytest.mark.parametrize("malformation", [
    {"polygon": None}, {"polygon": 5}, {"polygon": {"unsafe": PII[2]}},
    {"id": {"unsafe": PII[0]}}, {"name": {"unsafe": PII[0]}},
    {"sector": {"unsafe": PII[2]}}, {"zone_level": {"unsafe": PII[3]}},
])
@mongo_case
async def test_review_f5_malformed_zone_configuration_is_sanitized_and_atomic(db, malformation, caplog):
    await db.delivery_zones.insert_one(zone("broken-zone", 0, 10, **malformation))
    caplog.set_level("INFO", logger="utils.order_creation")
    await raises_creation(OrderCreationService(db).create(command(customer_latitude=5.0, customer_longitude=5.0), ACTOR),
                          503, "ZONE_CONFIGURATION_INVALID")
    await assert_business(db, 0)
    assert (await db.order_operations.find_one({}))["state"] == "pending"
    assert_private_free(caplog.text)


async def noncancellable_executor_pause(faults):
    """The running thread, unlike its asyncio waiter, survives cancellation."""
    def worker():
        faults.worker_active.set()
        faults.worker_started.set()
        try:
            time.sleep(0.35)
        finally:
            faults.worker_active.clear()
            faults.worker_done.set()
    await asyncio.get_running_loop().run_in_executor(None, worker)


async def await_thread_event(event, seconds=3):
    async with asyncio.timeout(seconds):
        while not event.is_set():
            await asyncio.sleep(0.01)


class WorkerLifecycleSession(SessionProxy):
    @property
    def in_transaction(self):
        if self.faults.worker_active.is_set():
            self.faults.overlap.append("in_transaction read before worker_done")
        return self.real.in_transaction

    async def abort_transaction(self):
        if self.faults.worker_active.is_set():
            self.faults.overlap.append("abort before worker_done")
        self.faults.cleanup_entries.append("abort")
        return await self.real.abort_transaction()

    async def end_session(self):
        if self.faults.worker_active.is_set():
            self.faults.overlap.append("end before worker_done")
        self.faults.cleanup_entries.append("end")
        try:
            return await self.real.end_session()
        finally:
            self.faults.cleanup_observed.set()

    async def commit_transaction(self):
        if self.faults.worker_boundary == "commit":
            # Preserve real STARTED state until the worker actually completes.
            assert self.real.in_transaction is True
            await noncancellable_executor_pause(self.faults)
        return await super().commit_transaction()


@pytest.mark.parametrize("boundary", [
    ("order_operations", "find_one"), ("users", "update_one"),
    ("orders", "insert_one"), "commit",
])
@mongo_case
async def test_review_final_f3_executor_worker_completes_before_session_cleanup(db, boundary, monkeypatch):
    await admit_pending(db)
    faults = Faults()
    faults.worker_boundary = boundary
    faults.worker_active = threading.Event()
    faults.worker_started = threading.Event()
    faults.worker_done = threading.Event()
    faults.cleanup_observed = threading.Event()
    faults.overlap, faults.cleanup_entries = [], []
    sessions = []
    def factory(real, config):
        sessions.append(real)
        return WorkerLifecycleSession(real, config)
    faults.session_factory = factory
    monkeypatch.setattr(creation_module, "DEADLINE_SECONDS", 0.05)
    service = OrderCreationService(DatabaseProxy(db, faults))
    started = time.monotonic()
    try:
        outcome = await asyncio.wait_for(service.create(command(), ACTOR), timeout=1)
        elapsed = time.monotonic() - started
        receipt(outcome, "pending", 202)
        assert elapsed < 1
        assert faults.worker_started.is_set(), "Executor fault boundary must actually execute"
        await await_thread_event(faults.worker_done)
        await await_thread_event(faults.cleanup_observed)
        # Keep the loop alive through original worker AND deferred cleanup.
        await asyncio.sleep(0.03)
        assert not faults.overlap, f"Concurrent session lifecycle: {faults.overlap}"
        assert faults.cleanup_entries.count("end") == 1
        if boundary == "commit":
            assert faults.cleanup_entries == ["end"], "Commit success must not be followed by abort"
        else:
            assert faults.cleanup_entries == ["abort", "end"]
    finally:
        if faults.worker_started.is_set():
            await await_thread_event(faults.worker_done)
        for session in sessions:
            await asyncio.wait_for(session.end_session(), timeout=2)
    # Recovery after the lifecycle barrier remains same-identity/exactly once.
    monkeypatch.setattr(creation_module, "DEADLINE_SECONDS", 10)
    resolved = await OrderCreationService(db).create(command(), ACTOR)
    assert resolved.result.state in {"applied", "replayed"}
    await assert_business(db, 1)


class DeferredEndFailureSession(SessionProxy):
    async def abort_transaction(self):
        if self.faults.delay_active:
            self.faults.cleanup_overlap.append("abort before delay_done")
        def worker():
            time.sleep(0.35)
        await asyncio.get_running_loop().run_in_executor(None, worker)
        result = await self.real.abort_transaction()
        self.faults.abort_finished.set()
        return result

    async def end_session(self):
        if self.faults.delay_active:
            self.faults.cleanup_overlap.append("end before delay_done")
        self.faults.end_entered.set()
        def worker():
            try:
                time.sleep(0.35)
                raise RuntimeError("QA deferred private exception " + PII[3])
            finally:
                self.faults.end_worker_finished.set()
        return await asyncio.get_running_loop().run_in_executor(None, worker)


@mongo_case
async def test_review_final_n1_deferred_end_exception_is_observed_without_pii(db, monkeypatch, caplog):
    await admit_pending(db)
    faults = Faults()
    faults.delay = ("order_operations", "find_one", True)
    faults.delay_release = asyncio.Event()
    faults.abort_finished = threading.Event()
    faults.end_entered = threading.Event()
    faults.end_worker_finished = threading.Event()
    sessions = []
    def factory(real, config):
        sessions.append(real)
        return DeferredEndFailureSession(real, config)
    faults.session_factory = factory
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()
    unhandled = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    caplog.set_level("INFO", logger="utils.order_creation")
    monkeypatch.setattr(creation_module, "DEADLINE_SECONDS", 0.05)
    try:
        receipt(await asyncio.wait_for(OrderCreationService(DatabaseProxy(db, faults)).create(command(), ACTOR), 1),
                "pending", 202)
        assert faults.injections == 1 and faults.delay_active
        assert not faults.abort_finished.is_set() and not faults.end_entered.is_set()
        assert not faults.cleanup_overlap
        faults.delay_release.set()
        await await_thread_event(faults.delay_done)
        await await_thread_event(faults.abort_finished)
        await await_thread_event(faults.end_entered)
        await await_thread_event(faults.end_worker_finished)
        # Let the deferred wrapper return, then collect unreachable failed tasks
        # while this loop's exception handler is still installed.
        for _ in range(3):
            await asyncio.sleep(0.05)
            gc.collect()
        assert not unhandled, "Deferred cleanup exception reached loop exception handler: " + str(unhandled)
        assert not faults.cleanup_overlap
        assert_private_free(caplog.text)
        await assert_business(db, 0)
    finally:
        faults.delay_release.set()
        if faults.delay_active:
            await await_thread_event(faults.delay_done)
        if faults.end_entered.is_set():
            await await_thread_event(faults.end_worker_finished)
        for session in sessions:
            await asyncio.wait_for(session.end_session(), 2)
        loop.set_exception_handler(original_handler)
