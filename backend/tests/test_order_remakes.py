"""Bounded atomic remake contract, HTTP and owned-Mongo acceptance."""

import asyncio
from copy import deepcopy

from fastapi import FastAPI
import httpx
from pydantic import ValidationError
from pymongo.errors import OperationFailure
import pytest

from models.order import Order, OrderCreate
from models.order_mutation import AssignOrderCommand, StatusOrderCommand, CreateOrderCommand
from models.order_preparation_operations import PreparingOperationCommand, ReadyOperationCommand
from models.order_remakes import RemakeCommand
from test_order_creation_recovery import db, mongo_case, ACTOR, Faults, SimulatedCrash, DatabaseProxy
from test_order_assignment_recovery import DatabaseProxy as AssignmentDatabaseProxy
from test_financial_core import command as finance_command
from test_financial_core_mongo import seed, picked_up, ADMIN, DRIVER
from utils.order_creation import CreationError, OrderCreationService
from utils.order_remakes import OrderRemakeService, operation_key
from utils.order_reads import OrderReadService, safe_order
from utils.order_assignment import OrderAssignmentService
from utils.order_preparation_operations import OrderPreparationService
from utils.order_status import OrderStatusService


def command(payment="CASH", amount=0, **changes):
    values = {"client_operation_id": "remake_synthetic_0001", "expected_order_version": 6,
        "problem_type": "missing_product", "description": "Synthetic explicit restaurant receipt decision",
        "items": [{"name": "Replacement synthetic product", "quantity": 1, "unit_price_bani": amount}],
        "payment_type": payment, "collection_basis": "new_receipt" if payment == "CASH" else "prepaid_new_order",
        "client_collection_bani": amount if payment == "CASH" else 0,
        "advance_required_bani": amount if payment == "CASH" else 0,
        "financial": {**finance_command().financial.model_dump(mode="json"), "products_bani": amount}}
    values.update(changes)
    return RemakeCommand.model_validate(values)


async def delivered(db):
    await seed(db)
    order = await picked_up(db)
    result = await OrderStatusService(db).status(order["id"], StatusOrderCommand(
        client_operation_id="remake_parent_deliver_0001", expected_order_version=5, status="DELIVERED"), DRIVER)
    assert result.result.state == "applied"
    await db.order_operation_settings.insert_one({"_id": "order-remake-v1", "enabled": True})
    return await db.orders.find_one({"id": order["id"]})


@pytest.mark.parametrize("field", ["payment_type", "collection_basis", "client_collection_bani", "advance_required_bani", "financial"])
@pytest.mark.parametrize("invalid", ["absent", None, True])
def test_money_and_decisions_are_required_not_defaulted(field, invalid):
    value = command().model_dump(mode="json")
    if invalid == "absent":
        del value[field]
    else:
        value[field] = invalid
    with pytest.raises(ValidationError):
        RemakeCommand.model_validate(value)


@pytest.mark.parametrize("value", [1.1, "100", -1, True, None, 10_000_001])
def test_item_money_is_exact_bounded_integer(value):
    data = command().model_dump(mode="json")
    data["items"][0]["unit_price_bani"] = value
    with pytest.raises(ValidationError):
        RemakeCommand.model_validate(data)


@pytest.mark.parametrize("payment,amount,collection", [("CASH", 0, 0), ("CASH", 1305, 1305), ("CARD", 1305, 0)])
@mongo_case
async def test_atomic_creation_roundtrip_new_payment_and_parent_history(db, payment, amount, collection):
    parent = await delivered(db)
    before_driver = await db.drivers.find_one({"id": DRIVER["driver_id"]})
    result = await OrderRemakeService(db).submit(parent["id"], command(payment, amount), ACTOR)
    assert result.status_code == 201 and result.result.state == "applied"
    child = await db.orders.find_one({"id": result.result.order_id})
    current = await db.orders.find_one({"id": parent["id"]})
    assert current["status"] == "DELIVERED" and current["order_version"] == 7
    assert current["financial"] == parent["financial"] and current["items"] == parent["items"]
    assert current["has_problem_followup"] is True and current["problem_followup_order_id"] == child["id"]
    assert child["linked_problem_order_id"] == parent["id"] and child["remake_operation_ref"] == current["problem_followup_operation_ref"]
    assert child["status"] == child["preparation_status"] == "NEW" and child["order_version"] == 0
    assert child["driver_id"] is None and child["order_number"].endswith("P")
    assert child["financial"]["products_bani"] == amount and child["financial"]["client_collection_bani"] == collection
    assert child["financial"]["restaurant_transport_bani"] == 1600 and child["financial"]["courier_remuneration_bani"] == 975
    assert child["financial"]["advance_paid_bani"] is None and child["payment_type"] == payment
    assert await db.drivers.find_one({"id": DRIVER["driver_id"]}) == before_driver
    assert Order(**child).model_dump(mode="json")["remake_operation_ref"] == child["remake_operation_ref"]
    assert Order(**current).model_dump(mode="json")["problem_followup_order_id"] == child["id"]
    read_parent = (await OrderReadService(db).detail(ACTOR, parent["id"]))["order"]
    read_child = (await OrderReadService(db).detail(ACTOR, child["id"]))["order"]
    assert read_parent["has_problem_followup"] is True and read_parent["problem_followup_order_id"] == child["id"]
    assert read_child["remake_operation_ref"] == child["remake_operation_ref"] and read_child["financial"] == child["financial"]


@pytest.mark.parametrize("changes", [
    {"client_collection_bani": 10}, {"advance_required_bani": 10}, {"collection_basis": "prepaid_new_order"},
    {"payment_type": "CARD", "collection_basis": "prepaid_new_order", "client_collection_bani": 1},
    {"items": [{"name": "Positive nominal value", "quantity": 1, "unit_price_bani": 1000}]},
    {"financial": {**finance_command().financial.model_dump(mode="json"), "products_bani": 1300},
     "client_collection_bani": 1300, "advance_required_bani": 1300},
])
@mongo_case
async def test_unrepresentable_money_refused_before_admission(db, changes):
    parent = await delivered(db)
    with pytest.raises(CreationError) as caught:
        await OrderRemakeService(db).submit(parent["id"], command(**changes), ACTOR)
    assert caught.value.code == "FINANCIAL_REMAKE_POLICY_REQUIRED"
    assert await db.order_operations.count_documents({"operation_type": "remake"}) == 0
    assert await db.orders.count_documents({}) == 1


@mongo_case
async def test_default_off_is_not_permission_for_live_activation(db):
    parent = await delivered(db)
    await db.order_operation_settings.update_one({"_id": "order-remake-v1"}, {"$set": {"enabled": False}})
    service = OrderRemakeService(db)
    assert (await service.capabilities(ACTOR))["remake_recovery_enabled"] is False
    with pytest.raises(CreationError) as caught:
        await service.submit(parent["id"], command(), ACTOR)
    assert caught.value.code == "REMAKE_NOT_ENABLED"
    assert await db.orders.count_documents({}) == 1


@mongo_case
async def test_admitted_snapshot_survives_disable_tariff_and_zone_reconfiguration(db):
    parent = await delivered(db)
    faults = Faults()
    faults.after_admission_crash = True
    cmd = command()
    with pytest.raises(SimulatedCrash):
        await OrderRemakeService(DatabaseProxy(db, faults)).submit(parent["id"], cmd, ACTOR)
    op = await db.order_operations.find_one({"_id": operation_key(ACTOR["id"], cmd.client_operation_id)})
    assert op["state"] == "pending" and await db.orders.count_documents({}) == 1
    await db.order_operation_settings.update_many({"_id": {"$in": ["order-remake-v1", "order-finance-v1"]}}, {"$set": {"enabled": False}})
    await db.restaurant_tariff_versions.update_one({}, {"$set": {"zones": {}}})
    await db.delivery_zones.update_one({}, {"$set": {"name": "Changed after admission"}})
    result = await OrderRemakeService(db).resume(parent["id"], cmd.client_operation_id, ACTOR)
    assert result.result.state == "applied"
    child = await db.orders.find_one({"id": result.result.order_id})
    assert child["financial"] == op["financial_snapshot"] and child["delivery_zone_name"] == "Synthetic Zone"
    assert (await OrderRemakeService(db).submit(parent["id"], cmd, ACTOR)).result.state == "replayed"


@mongo_case
async def test_duplicate_concurrent_intent_and_unknown_commit_never_duplicate(db):
    parent = await delivered(db)
    faults = Faults()
    faults.ack_losses = 1
    cmd = command()
    results = await asyncio.gather(OrderRemakeService(AssignmentDatabaseProxy(db, faults)).submit(parent["id"], cmd, ACTOR),
                                   OrderRemakeService(db).submit(parent["id"], cmd, ACTOR))
    assert all(result.result.state in ("applied", "replayed", "pending") for result in results)
    final = await OrderRemakeService(db).resume(parent["id"], cmd.client_operation_id, ACTOR)
    assert final.result.state == "replayed"
    assert await db.orders.count_documents({"linked_problem_order_id": parent["id"]}) == 1
    assert await db.audit_logs.count_documents({"action": {"$in": ["order.remake_linked", "order.remake_created"]}}) == 2
    assert (await db.counters.find_one({"_id": "orders.global"}))["seq"] == 102
    with pytest.raises(CreationError) as caught:
        await OrderRemakeService(db).submit(parent["id"], command(description="Different intent uses same key"), ACTOR)
    assert caught.value.code == "INTENT_CONFLICT"


@mongo_case
async def test_two_operators_with_distinct_intents_admitted_before_race_create_one_child(db):
    parent = await delivered(db)
    commands = [command(client_operation_id=f"remake_competing_{i:04d}") for i in range(2)]
    for actor, cmd in zip((ACTOR, ADMIN), commands):
        faults = Faults()
        faults.after_admission_crash = True
        with pytest.raises(SimulatedCrash):
            await OrderRemakeService(DatabaseProxy(db, faults)).submit(parent["id"], cmd, actor)
    results = await asyncio.gather(*[OrderRemakeService(db).resume(parent["id"], cmd.client_operation_id, actor)
                                    for actor, cmd in zip((ACTOR, ADMIN), commands)])
    assert sorted(result.result.state for result in results) == ["applied", "rejected"]
    assert await db.orders.count_documents({"linked_problem_order_id": parent["id"]}) == 1
    assert (await db.orders.find_one({"id": parent["id"]}))["order_version"] == 7
    assert (await db.counters.find_one({"_id": "orders.global"}))["seq"] == 102


class WriteFailureCollection:
    def __init__(self, collection, target, counter):
        self.real, self.target, self.counter = collection, target, counter

    def __getattr__(self, name):
        method = getattr(self.real, name)
        if (self.real.name, name) != self.target[:2]:
            return method

        async def call(*args, **kwargs):
            result = await method(*args, **kwargs)
            if kwargs.get("session") is not None:
                self.counter[0] += 1
                if self.counter[0] == self.target[2]:
                    raise OperationFailure("Synthetic rollback after completed transactional write", code=12345)
            return result
        return call


class WriteFailureDB:
    def __init__(self, database, target):
        self.real, self.target, self.counter = database, target, [0]

    @property
    def client(self):
        return self.real.client

    async def command(self, *args, **kwargs):
        return await self.real.command(*args, **kwargs)

    def get_collection(self, *args, **kwargs):
        return WriteFailureCollection(self.real.get_collection(*args, **kwargs), self.target, self.counter)

    def __getattr__(self, name):
        return WriteFailureCollection(getattr(self.real, name), self.target, self.counter)


@pytest.mark.parametrize("target", [("orders", "update_one", 1), ("counters", "find_one_and_update", 1),
    ("orders", "insert_one", 1), ("audit_logs", "insert_one", 1), ("audit_logs", "insert_one", 2),
    ("order_operations", "update_one", 1)])
@mongo_case
async def test_each_transactional_write_rolls_back_with_pending_operation_and_resumes(db, target):
    parent = await delivered(db)
    before_audits = await db.audit_logs.count_documents({})
    cmd = command()
    result = await OrderRemakeService(WriteFailureDB(db, target)).submit(parent["id"], cmd, ACTOR)
    assert result.result.state == "pending"
    assert await db.orders.find_one({"id": parent["id"]}) == parent
    assert await db.orders.count_documents({}) == 1 and await db.audit_logs.count_documents({}) == before_audits
    assert (await db.counters.find_one({"_id": "orders.global"}))["seq"] == 101
    op = await db.order_operations.find_one({"operation_type": "remake"})
    assert op["state"] == "pending"
    resumed = await OrderRemakeService(db).resume(parent["id"], cmd.client_operation_id, ACTOR)
    assert resumed.result.state == "applied" and await db.orders.count_documents({}) == 2


@pytest.mark.parametrize("change,code", [({"status": "PICKED_UP"}, "REMAKE_REQUIRES_DELIVERED"),
    ({"order_version": 7}, "ORDER_VERSION_CONFLICT"), ({"customer_address": "Another address after admission"}, "REMAKE_PARENT_CHANGED"),
    ({"financial.courier_remuneration_bani": 1}, "FINANCIAL_SNAPSHOT_INVALID")])
@mongo_case
async def test_parent_change_after_admission_is_durable_refusal_without_child(db, change, code):
    parent = await delivered(db)
    faults = Faults()
    faults.after_admission_crash = True
    cmd = command()
    with pytest.raises(SimulatedCrash):
        await OrderRemakeService(DatabaseProxy(db, faults)).submit(parent["id"], cmd, ACTOR)
    await db.orders.update_one({"id": parent["id"]}, {"$set": change})
    result = await OrderRemakeService(db).resume(parent["id"], cmd.client_operation_id, ACTOR)
    assert result.result.state == "rejected" and result.result.error_code == code
    assert (await OrderRemakeService(db).lookup(parent["id"], cmd.client_operation_id, ACTOR)).result.error_code == code
    assert await db.orders.count_documents({}) == 1


@mongo_case
async def test_actor_scope_corrupt_receipt_and_custody_fail_closed(db):
    parent = await delivered(db)
    foreign = {"id": "remake_foreign_actor", "role": "restaurant", "restaurant_id": "other-restaurant"}
    await db.users.insert_one(foreign)
    for actor in (foreign, DRIVER):
        with pytest.raises(CreationError) as caught:
            await OrderRemakeService(db).submit(parent["id"], command(), actor)
        assert caught.value.status_code == 403
    faults = Faults()
    faults.after_admission_crash = True
    cmd = command()
    with pytest.raises(SimulatedCrash):
        await OrderRemakeService(DatabaseProxy(db, faults)).submit(parent["id"], cmd, ACTOR)
    for method in ("lookup", "resume"):
        with pytest.raises(CreationError) as caught:
            await getattr(OrderRemakeService(db), method)(parent["id"], cmd.client_operation_id, foreign)
        assert caught.value.code == "OPERATION_NOT_FOUND"
    await db.drivers.update_one({"id": DRIVER["driver_id"]}, {"$set": {"current_order_id": parent["id"]}})
    rejected = await OrderRemakeService(db).resume(parent["id"], cmd.client_operation_id, ACTOR)
    assert rejected.result.error_code == "CUSTODY_RESOLUTION_REQUIRED"
    assert (await db.drivers.find_one({"id": DRIVER["driver_id"]}))["current_order_id"] == parent["id"]
    await db.order_operations.update_one({"operation_type": "remake"}, {"$set": {"child_order_id": "corrupt"}})
    with pytest.raises(CreationError) as caught:
        await OrderRemakeService(db).lookup(parent["id"], cmd.client_operation_id, ACTOR)
    assert caught.value.code == "OPERATION_INVALID"


@mongo_case
async def test_no_charge_child_delivered_once_pays_normal_grid_and_never_recredits_parent(db):
    parent = await delivered(db)
    out = await OrderRemakeService(db).submit(parent["id"], command(), ACTOR)
    child_id = out.result.order_id
    await OrderPreparationService(db, "preparing").submit(child_id,
        PreparingOperationCommand(client_operation_id="remake_child_prepare", expected_order_version=0, preparation_time=20), ACTOR)
    await OrderAssignmentService(db).assign(child_id,
        AssignOrderCommand(client_operation_id="remake_child_assign", expected_order_version=1, driver_id=DRIVER["driver_id"]), ADMIN)
    await OrderStatusService(db).status(child_id,
        StatusOrderCommand(client_operation_id="remake_child_accept", expected_order_version=2, status="ACCEPTED"), DRIVER)
    await OrderPreparationService(db, "ready").submit(child_id,
        ReadyOperationCommand(client_operation_id="remake_child_ready", expected_order_version=3), ACTOR)
    await OrderStatusService(db).status(child_id,
        StatusOrderCommand(client_operation_id="remake_child_pickup", expected_order_version=4, status="PICKED_UP"), DRIVER)
    final = StatusOrderCommand(client_operation_id="remake_child_deliver", expected_order_version=5, status="DELIVERED")
    assert (await OrderStatusService(db).status(child_id, final, DRIVER)).result.state == "applied"
    assert (await OrderStatusService(db).status(child_id, final, DRIVER)).result.state == "replayed"
    driver = await db.drivers.find_one({"id": DRIVER["driver_id"]})
    assert driver["financial_earned_bani"] == 1950 and driver["total_deliveries"] == 10
    assert driver["current_order_id"] is None
    child = await db.orders.find_one({"id": child_id})
    current = await db.orders.find_one({"id": parent["id"]})
    assert child["total_amount"] == 0 and child["delivery_fee"] == 16
    assert current["financial"] == parent["financial"] and current["status"] == "DELIVERED"


@mongo_case
async def test_http_contract_actor_header_private_errors_bodyless_recovery_and_readback(db, monkeypatch):
    import routers.order_operations as route
    parent = await delivered(db)
    monkeypatch.setattr(route, "db", db)
    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    app.dependency_overrides[route.get_current_user] = lambda: ACTOR
    headers = {"X-Expected-Actor-ID": ACTOR["id"]}
    base = f"/api/orders/operations/remake/{parent['id']}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test") as client:
        no_header = await client.post(base, json=command().model_dump(mode="json"))
        assert no_header.status_code == 409 and no_header.headers["cache-control"] == "no-store"
        invalid = command().model_dump(mode="json")
        invalid["client_collection_bani"] = "PRIVATE_INVALID_INPUT"
        response = await client.post(base, json=invalid, headers=headers)
        assert response.status_code == 422 and "PRIVATE_INVALID_INPUT" not in response.text
        created = await client.post(base, json=command().model_dump(mode="json"), headers=headers)
        assert created.status_code == 201 and created.json()["parent_order_id"] == parent["id"]
        path = base + "/" + command().client_operation_id
        looked = await client.get(path, headers=headers)
        assert looked.status_code == 200 and looked.json()["state"] == "replayed"
        bad_resume = await client.post(path + "/resume", json={}, headers=headers)
        assert bad_resume.status_code == 422
        resumed = await client.post(path + "/resume", headers=headers)
        assert resumed.status_code == 200 and resumed.json()["order_id"] == created.json()["order_id"]
        assert resumed.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("entrypoint", ["legacy", "recoverable"])
@mongo_case
async def test_generic_create_cannot_link_versioned_parent_and_foreign_is_missing(db, monkeypatch, entrypoint):
    import routers.orders as legacy
    parent = await delivered(db)
    monkeypatch.setattr(legacy, "db", db)
    request = {"restaurant_id": ACTOR["restaurant_id"], "customer_name": "Synthetic Client",
        "customer_phone": "0700000000", "customer_address": "Synthetic address 123",
        "total_amount": 0.0, "payment_type": "CASH", "linked_problem_order_id": parent["id"],
        "problem_type": "missing_product", "problem_description": "Synthetic linked request"}

    async def call(values):
        if entrypoint == "legacy":
            return await legacy.create_order(OrderCreate(**values), ACTOR, ACTOR["id"])
        return await OrderCreationService(db).create(CreateOrderCommand(
            client_operation_id="generic_remake_bypass_0001", order=values), ACTOR)

    from fastapi import HTTPException
    with pytest.raises((CreationError, HTTPException)) as caught:
        await call(request)
    code = caught.value.code if isinstance(caught.value, CreationError) else caught.value.detail["code"]
    assert code == "FINANCIAL_REMAKE_PROTOCOL_REQUIRED"
    outcomes = []
    foreign_parent = {**parent, "_id": "foreign-parent", "id": "foreign-parent", "restaurant_id": "foreign-restaurant"}
    await db.orders.insert_one(foreign_parent)
    for target in ("foreign-parent", "missing-parent"):
        with pytest.raises((CreationError, HTTPException)) as denied:
            await call({**request, "linked_problem_order_id": target})
        err = denied.value
        outcomes.append((err.status_code, err.code if isinstance(err, CreationError) else err.detail["code"]))
    assert outcomes == [(404, "PROBLEM_PARENT_NOT_AVAILABLE")] * 2
    assert await db.orders.count_documents({"restaurant_id": ACTOR["restaurant_id"]}) == 1
    assert (await db.counters.find_one({"_id": "orders.global"}))["seq"] == 101


@mongo_case
async def test_pending_generic_link_is_rechecked_when_parent_is_versioned_after_admission(db):
    # Synthetic corruption/promotion boundary; no production migration is implied.
    parent = await delivered(db)
    legacy_parent = {"_id": "legacy-parent", "id": "legacy-parent", "restaurant_id": ACTOR["restaurant_id"]}
    await db.orders.insert_one(legacy_parent)
    cmd = CreateOrderCommand(client_operation_id="pending_legacy_link_0001", order={
        "restaurant_id": ACTOR["restaurant_id"], "customer_name": "Synthetic Client", "customer_phone": "0700000000",
        "customer_address": "Synthetic address 123", "total_amount": 0.0, "payment_type": "CASH",
        "linked_problem_order_id": "legacy-parent", "problem_type": "missing_product", "problem_description": "Synthetic problem"})
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderCreationService(DatabaseProxy(db, faults)).create(cmd, ACTOR)
    await db.orders.update_one({"id": "legacy-parent"}, {"$set": {"order_version": 0}})
    result = await OrderCreationService(db).resume(cmd.client_operation_id, ACTOR)
    assert result.result.state == "rejected" and result.result.error_code == "FINANCIAL_REMAKE_PROTOCOL_REQUIRED"
    assert await db.orders.count_documents({"linked_problem_order_id": "legacy-parent"}) == 0
    assert (await db.counters.find_one({"_id": "orders.global"}))["seq"] == 101


@mongo_case
async def test_former_driver_other_claim_unchanged_and_corrupt_link_reads_fail_closed(db):
    parent = await delivered(db)
    await db.drivers.update_one({"id": DRIVER["driver_id"]}, {"$set": {"current_order_id": "different-active-delivery"}})
    before = await db.drivers.find_one({"id": DRIVER["driver_id"]})
    result = await OrderRemakeService(db).submit(parent["id"], command(), ACTOR)
    assert result.result.state == "applied" and await db.drivers.find_one({"id": DRIVER["driver_id"]}) == before
    await db.orders.update_one({"id": result.result.order_id}, {"$set": {"remake_operation_ref": ["malformed"]}})
    read = (await OrderReadService(db).detail(ACTOR, result.result.order_id))["order"]
    assert read["read_remake_invalid"] is True and read["read_actions_unavailable"] is True


@mongo_case
async def test_malformed_parent_fields_are_safe_error_without_new_admission(db):
    parent = await delivered(db)
    await db.orders.update_one({"id": parent["id"]}, {"$unset": {"customer_phone": ""}})
    with pytest.raises(CreationError) as caught:
        await OrderRemakeService(db).submit(parent["id"], command(), ACTOR)
    assert caught.value.code == "ORDER_DATA_INVALID"
    assert await db.order_operations.count_documents({"operation_type": "remake"}) == 0


@mongo_case
async def test_pure_legacy_parent_links_and_read_shape_remain_supported(db):
    # A minimal owned legacy parent exercises the preserved generic path.
    await db.orders.insert_one({"_id": "legacy-own-parent", "id": "legacy-own-parent",
        "restaurant_id": ACTOR["restaurant_id"], "status": "DELIVERED", "has_problem_followup": True})
    cmd = CreateOrderCommand(client_operation_id="valid_legacy_link_0001", order={
        "restaurant_id": ACTOR["restaurant_id"], "customer_name": "Synthetic Client", "customer_phone": "0700000000",
        "customer_address": "Synthetic address 123", "total_amount": 0.0, "payment_type": "CASH",
        "linked_problem_order_id": "legacy-own-parent", "problem_type": "missing_product", "problem_description": "Synthetic legacy problem"})
    result = await OrderCreationService(db).create(cmd, ACTOR)
    assert result.result.state == "applied"
    child = await db.orders.find_one({"id": result.result.order_id})
    assert "financial" not in child and "order_version" not in child
    warnings = set()
    read = safe_order({"id": "legacy-own-parent", "restaurant_id": ACTOR["restaurant_id"],
        "status": "DELIVERED", "has_problem_followup": True}, warnings)
    assert read["has_problem_followup"] is True and "read_remake_invalid" not in read
