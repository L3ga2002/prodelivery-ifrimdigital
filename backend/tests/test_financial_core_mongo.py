"""Financial operation integration on the verified owned MongoRS fixture only."""

import asyncio
from copy import deepcopy

from fastapi import HTTPException
import pytest
from pymongo.errors import OperationFailure

from models.order import Order
from models.order_mutation import AssignOrderCommand, StatusOrderCommand, EditOrderCommand
from models.order_preparation_operations import PreparingOperationCommand, ReadyOperationCommand
from test_order_creation_recovery import db, mongo_case, ACTOR, Faults, SimulatedCrash, DatabaseProxy
from test_order_assignment_recovery import DatabaseProxy as AssignmentDatabaseProxy
from test_financial_core import command, grid
from utils.order_creation import CreationError, OrderCreationService, operation_key
from utils.order_assignment import OrderAssignmentService
from utils.order_preparation_operations import OrderPreparationService
from utils.order_reads import OrderReadService
from utils.order_status import OrderStatusService, StatusError
from utils.order_editing import OrderEditingService
from utils.order_finance import validate_snapshot


ADMIN = {"id": "qa-financial-admin", "role": "admin"}
DRIVER = {"id": "qa-financial-driver-user", "role": "driver", "driver_id": "qa-financial-driver"}


async def seed(db):
    await db.create_collection("restaurant_tariff_versions")
    await db.restaurant_tariff_versions.insert_one(grid())
    await db.users.insert_many([ADMIN, DRIVER])
    await db.drivers.insert_one({
        "id": DRIVER["driver_id"], "user_id": DRIVER["id"], "name": "Synthetic Driver", "phone": "0700000001",
        "driver_status": "active", "current_order_id": None, "is_active": True, "account_disabled": False,
        "total_deliveries": 8, "total_earnings": 42.005,
    })
    await db.delivery_zones.insert_one({"id": "zone-one", "restaurant_id": "qa-restaurant", "is_active": True,
        "name": "Synthetic Zone", "sector": "Synthetic Sector", "zone_level": 1, "fee": 999,
        "polygon": [{"lat": 0, "lng": 0}, {"lat": 0, "lng": 2}, {"lat": 2, "lng": 2}, {"lat": 2, "lng": 0}]})
    await db.order_operation_settings.insert_many([
        {"_id": name, "enabled": True} for name in ("order-finance-v1", "order-assign-v1", "order-status-v1", "order-preparation-v1", "order-edit-v1")])


async def create(db, cmd=None):
    result = await OrderCreationService(db).create(cmd or command(), ADMIN)
    assert result.result.state == "applied"
    return await db.orders.find_one({"id": result.result.order_id})


async def picked_up(db, payment="CASH"):
    original = await create(db, command(payment))
    order_id = original["id"]
    prepared = await OrderPreparationService(db, "preparing").submit(order_id,
        PreparingOperationCommand(client_operation_id="financial_prepare_0001", expected_order_version=0, preparation_time=20), ACTOR)
    assert prepared.result.state == "applied"
    assigned = await OrderAssignmentService(db).assign(order_id,
        AssignOrderCommand(client_operation_id="financial_assign_0001", expected_order_version=1, driver_id=DRIVER["driver_id"]), ADMIN)
    assert assigned.result.state == "applied"
    accepted = await OrderStatusService(db).status(order_id,
        StatusOrderCommand(client_operation_id="financial_accept_0001", expected_order_version=2, status="ACCEPTED"), DRIVER)
    assert accepted.result.state == "applied"
    ready = await OrderPreparationService(db, "ready").submit(order_id,
        ReadyOperationCommand(client_operation_id="financial_ready_0001", expected_order_version=3), ACTOR)
    assert ready.result.state == "applied"
    pickup = await OrderStatusService(db).status(order_id,
        StatusOrderCommand(client_operation_id="financial_pickup_0001", expected_order_version=4, status="PICKED_UP"), DRIVER)
    assert pickup.result.state == "applied"
    current = await db.orders.find_one({"id": order_id})
    assert current["financial"] == original["financial"]
    return current


@mongo_case
async def test_admission_freezes_snapshot_before_crash_and_recovers_after_grid_change_and_disable(db):
    await seed(db)
    cmd = command()
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderCreationService(DatabaseProxy(db, faults)).create(cmd, ADMIN)
    pending = await db.order_operations.find_one({"_id": operation_key(ADMIN["id"], cmd.client_operation_id)})
    snap = deepcopy(pending["financial_snapshot"])
    assert pending["state"] == "pending" and await db.orders.count_documents({}) == 0
    await db.restaurant_tariff_versions.update_one({"version": "synthetic-v1"}, {"$set": {
        "zones.zone-one.courier_remuneration_bani": 9950}})
    await db.order_operation_settings.update_one({"_id": "order-finance-v1"}, {"$set": {"enabled": False}})
    await db.delivery_zones.update_one({"id": "zone-one"}, {"$set": {"name": "Renamed after admission", "sector": "Changed"}})
    outcome = await OrderCreationService(db).resume(cmd.client_operation_id, ADMIN)
    assert outcome.result.state == "applied"
    doc = await db.orders.find_one({"id": outcome.result.order_id})
    assert doc["financial"] == snap and doc["financial"]["courier_remuneration_bani"] == 975
    assert doc["financial"]["advance_paid_bani"] is None
    assert doc["zone"] == doc["delivery_zone_name"] == "Synthetic Zone"
    assert doc["delivery_sector"] == "Synthetic Sector" and doc["delivery_zone_level"] == 1
    replay = await OrderCreationService(db).create(cmd, ADMIN)
    assert replay.result.state == "replayed" and await db.orders.count_documents({}) == 1


@mongo_case
async def test_missing_grid_and_disabled_protocol_never_admit_or_apply_financial_fallback(db):
    await seed(db)
    await db.order_operation_settings.update_one({"_id": "order-finance-v1"}, {"$set": {"enabled": False}})
    with pytest.raises(CreationError) as caught:
        await OrderCreationService(db).create(command(), ADMIN)
    assert caught.value.code == "FINANCIAL_NOT_ENABLED"
    await db.order_operation_settings.update_one({"_id": "order-finance-v1"}, {"$set": {"enabled": True}})
    # Retain fixture evidence; no drop/delete is needed to simulate missing config.
    cmd = command(tariff_version="synthetic-missing")
    with pytest.raises(CreationError) as caught:
        await OrderCreationService(db).create(cmd, ADMIN)
    assert caught.value.code == "FINANCIAL_GRID_MISSING"
    assert await db.order_operations.count_documents({}) == 0
    assert await db.orders.count_documents({}) == 0
    assert (await db.counters.find_one({"_id": "orders.global"}))["seq"] == 100


@mongo_case
async def test_concurrent_duplicate_creation_and_lost_commit_ack_keep_one_financial_snapshot(db):
    await seed(db)
    faults = Faults()
    faults.ack_losses = 1
    cmd = command()
    results = await asyncio.gather(OrderCreationService(DatabaseProxy(db, faults)).create(cmd, ADMIN),
                                   OrderCreationService(db).create(cmd, ADMIN))
    final = await OrderCreationService(db).resume(cmd.client_operation_id, ADMIN)
    assert final.result.state in ("applied", "replayed")
    assert await db.orders.count_documents({}) == await db.audit_logs.count_documents({}) == 1
    assert (await db.counters.find_one({"_id": "orders.global"}))["seq"] == 101
    stored = await db.orders.find_one({})
    assert stored["delivery_fee"] == 16.0 and stored["total_amount"] == 32.5
    assert validate_snapshot(stored["financial"]).courier_remuneration_bani == 975


@pytest.mark.parametrize("payment,collection", [("CASH", 3250), ("CARD", 0)])
@mongo_case
async def test_complete_lifecycle_keeps_snapshot_and_credits_fixed_remuneration_once(db, payment, collection):
    await seed(db)
    order = await picked_up(db, payment)
    cmd = StatusOrderCommand(client_operation_id="financial_deliver_0001", expected_order_version=5, status="DELIVERED")
    faults = Faults()
    faults.ack_losses = 1
    result = await OrderStatusService(AssignmentDatabaseProxy(db, faults)).status(order["id"], cmd, DRIVER)
    assert result.result.state in ("applied", "pending", "replayed")
    result = await OrderStatusService(db).resume(order["id"], cmd.client_operation_id, DRIVER)
    assert result.result.state == "replayed"
    delivered = await db.orders.find_one({"id": order["id"]})
    driver = await db.drivers.find_one({"id": DRIVER["driver_id"]})
    assert delivered["financial"] == order["financial"]
    assert delivered["financial"]["client_collection_bani"] == collection
    assert driver["financial_earned_bani"] == 975 and driver["total_deliveries"] == 9
    assert driver["total_earnings"] == 42.005 + 9.75
    assert await db.order_operations.count_documents({"operation_type": "status", "command.status": "DELIVERED"}) == 1
    operation = await db.order_operations.find_one({"operation_type": "status", "command.status": "DELIVERED"})
    assert operation["financial_snapshot"] == order["financial"]
    await OrderStatusService(db).status(order["id"], cmd, DRIVER)
    assert (await db.drivers.find_one({"id": DRIVER["driver_id"]}))["financial_earned_bani"] == 975


@mongo_case
async def test_financial_read_projection_roundtrip_and_tenant_isolation(db):
    await seed(db)
    created = await create(db)
    serialized = Order(**created).model_dump(mode="json")
    assert serialized["financial"] == created["financial"] and serialized["order_version"] == 0
    page = await OrderReadService(db).page(ACTOR)
    assert len(page["items"]) == 1 and page["items"][0]["financial"] == created["financial"]
    detail = await OrderReadService(db).detail(ACTOR, created["id"])
    assert detail["order"]["financial"] == created["financial"]
    foreign = {"id": "qa-financial-foreign", "role": "restaurant", "restaurant_id": "qa-foreign"}
    await db.users.insert_one(foreign)
    with pytest.raises(HTTPException) as caught:
        await OrderReadService(db).detail(foreign, created["id"])
    assert caught.value.status_code in (403, 404)
    assert (await OrderReadService(db).page(foreign))["items"] == []
    await db.orders.update_one({"id": created["id"]}, {"$set": {"financial.courier_remuneration_bani": 976}})
    detail = await OrderReadService(db).detail(ACTOR, created["id"])
    assert detail["order"]["financial"] is None and detail["order"]["read_actions_unavailable"]
    assert detail["order"]["read_financial_invalid"] is True


@mongo_case
async def test_financial_address_change_is_durable_refusal_while_contact_edit_recovers_safely(db):
    await seed(db)
    original = await create(db)
    address = EditOrderCommand(client_operation_id="financial_address_0001", expected_order_version=0,
        changes={"customer_address": "Synthetic new zone address", "customer_latitude": 4.0, "customer_longitude": 4.0})
    contact = EditOrderCommand(client_operation_id="financial_contact_0001", expected_order_version=0,
        changes={"customer_name": "Updated Synthetic Customer", "customer_phone": "0700000099", "notes": "Synthetic note"})
    rejected, applied = await asyncio.gather(OrderEditingService(db).edit(original["id"], address, ADMIN),
                                            OrderEditingService(db).edit(original["id"], contact, ADMIN))
    assert rejected.result.state == "rejected" and rejected.result.error_code == "FINANCIAL_ADDRESS_OPERATION_REQUIRED"
    assert applied.result.state == "applied"
    assert (await OrderEditingService(db).edit(original["id"], address, ADMIN)).result.error_code == "FINANCIAL_ADDRESS_OPERATION_REQUIRED"
    assert (await OrderEditingService(db).resume(original["id"], contact.client_operation_id, ADMIN)).result.state == "replayed"
    changed = await db.orders.find_one({"id": original["id"]})
    assert changed["financial"] == original["financial"] and changed["customer_address"] == original["customer_address"]
    assert changed["customer_name"] == "Updated Synthetic Customer" and changed["order_version"] == 1


@mongo_case
async def test_financial_contact_edit_refuses_snapshot_corruption_after_admission(db):
    await seed(db)
    original = await create(db)
    cmd = EditOrderCommand(client_operation_id="financial_contact_0002", expected_order_version=0,
                           changes={"notes": "Synthetic correction"})
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderEditingService(DatabaseProxy(db, faults)).edit(original["id"], cmd, ADMIN)
    await db.orders.update_one({"id": original["id"]}, {"$set": {"financial": None}})
    result = await OrderEditingService(db).resume(original["id"], cmd.client_operation_id, ADMIN)
    assert result.result.state == "rejected" and result.result.error_code == "FINANCIAL_SNAPSHOT_INVALID"
    assert (await db.orders.find_one({"id": original["id"]}))["notes"] == original["notes"]


@mongo_case
async def test_status_crash_recovery_uses_admission_snapshot_after_configuration_change(db):
    await seed(db)
    order = await picked_up(db)
    cmd = StatusOrderCommand(client_operation_id="financial_deliver_0002", expected_order_version=5, status="DELIVERED")
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderStatusService(AssignmentDatabaseProxy(db, faults)).status(order["id"], cmd, DRIVER)
    await db.restaurant_tariff_versions.update_one({"version": "synthetic-v1"}, {"$set": {"approved": False}})
    await db.order_operation_settings.update_one({"_id": "order-finance-v1"}, {"$set": {"enabled": False}})
    result = await OrderStatusService(db).resume(order["id"], cmd.client_operation_id, DRIVER)
    assert result.result.state == "applied"
    assert (await db.drivers.find_one({"id": DRIVER["driver_id"]}))["financial_earned_bani"] == 975


@mongo_case
async def test_status_snapshot_corruption_after_admission_rejects_without_financial_effect(db):
    await seed(db)
    order = await picked_up(db)
    cmd = StatusOrderCommand(client_operation_id="financial_deliver_0003", expected_order_version=5, status="DELIVERED")
    faults = Faults()
    faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderStatusService(AssignmentDatabaseProxy(db, faults)).status(order["id"], cmd, DRIVER)
    await db.orders.update_one({"id": order["id"]}, {"$set": {"financial": None}})
    result = await OrderStatusService(db).resume(order["id"], cmd.client_operation_id, DRIVER)
    assert result.result.state == "rejected" and result.result.error_code == "FINANCIAL_SNAPSHOT_INVALID"
    driver = await db.drivers.find_one({"id": DRIVER["driver_id"]})
    assert driver["total_earnings"] == 42.005 and "financial_earned_bani" not in driver
    assert (await db.orders.find_one({"id": order["id"]}))["status"] == "PICKED_UP"


@mongo_case
async def test_financial_delivery_audit_failure_rolls_back_counters_and_order(db):
    await seed(db)
    order = await picked_up(db)
    faults = Faults()
    faults.audit_failure = OperationFailure("synthetic audit outage")
    cmd = StatusOrderCommand(client_operation_id="financial_deliver_0004", expected_order_version=5, status="DELIVERED")
    result = await OrderStatusService(AssignmentDatabaseProxy(db, faults)).status(order["id"], cmd, DRIVER)
    assert result.result.state == "pending"
    driver = await db.drivers.find_one({"id": DRIVER["driver_id"]})
    assert driver["total_earnings"] == 42.005 and "financial_earned_bani" not in driver
    assert (await db.orders.find_one({"id": order["id"]}))["status"] == "PICKED_UP"
    result = await OrderStatusService(db).resume(order["id"], cmd.client_operation_id, DRIVER)
    assert result.result.state == "applied"
    assert (await db.drivers.find_one({"id": DRIVER["driver_id"]}))["financial_earned_bani"] == 975
