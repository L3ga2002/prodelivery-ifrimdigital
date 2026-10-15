"""Real Mongo interleaving for the adjacent driver availability writer."""
from copy import deepcopy

from fastapi import HTTPException
from models.driver import DriverStatusUpdate
from routers import drivers
from pymongo.errors import AutoReconnect
import pytest

from test_order_assignment_recovery import (
    ADMIN, DRIVER, OLD_DRIVER, ORDER, OP, VERSION, command, seed,
    OrderAssignmentService,
)
from test_order_creation_recovery import db, mongo_case


@pytest.mark.parametrize("status", ["active", "break", "offline", "delivery"])
@mongo_case
async def test_stale_driver_status_cannot_overwrite_new_committed_claim(db, monkeypatch, status):
    await seed(db)
    original_reader = drivers._ensure_admin_or_self

    async def interleave(driver_id, actor):
        snapshot = await original_reader(driver_id, actor)
        result = await OrderAssignmentService(db).assign(ORDER, command(), ADMIN)
        assert result.result.state == "applied"
        return snapshot

    monkeypatch.setattr(drivers, "db", db)
    monkeypatch.setattr(drivers, "_ensure_admin_or_self", interleave)
    with pytest.raises(HTTPException) as exc:
        await drivers.update_driver_status(DRIVER, DriverStatusUpdate(status=status), None, ADMIN)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "DRIVER_STATE_CONFLICT"
    driver = await db.drivers.find_one({"id": DRIVER})
    assert driver["current_order_id"] == ORDER
    assert driver["driver_status"] == "delivery" and driver["is_active"] is True
    order = await db.orders.find_one({"id": ORDER})
    assert order["driver_id"] == DRIVER and order["order_version"] == VERSION + 1
    assert await db.audit_logs.count_documents({}) == 1


@mongo_case
async def test_stale_active_status_cannot_resurrect_old_reassigned_claim(db, monkeypatch):
    await seed(db)
    first = await OrderAssignmentService(db).assign(ORDER, command(driver=OLD_DRIVER), ADMIN)
    assert first.result.state == "applied"
    original_reader = drivers._ensure_admin_or_self

    async def interleave(driver_id, actor):
        snapshot = await original_reader(driver_id, actor)
        result = await OrderAssignmentService(db).assign(
            ORDER, command(op=OP + "_reassign", version=VERSION + 1), ADMIN)
        assert result.result.state == "applied"
        return snapshot

    monkeypatch.setattr(drivers, "db", db)
    monkeypatch.setattr(drivers, "_ensure_admin_or_self", interleave)
    with pytest.raises(HTTPException) as exc:
        await drivers.update_driver_status(OLD_DRIVER, DriverStatusUpdate(status="active"), None, ADMIN)
    assert exc.value.status_code == 409
    old = await db.drivers.find_one({"id": OLD_DRIVER})
    new = await db.drivers.find_one({"id": DRIVER})
    assert old["current_order_id"] is None and old["driver_status"] == "active"
    assert new["current_order_id"] == ORDER
    order = await db.orders.find_one({"id": ORDER})
    assert order["driver_id"] == DRIVER and order["order_version"] == VERSION + 2
    assert await db.audit_logs.count_documents({}) == 2


@pytest.mark.parametrize("status", ["active", "break", "offline"])
@mongo_case
async def test_fresh_driver_status_keeps_existing_behavior_without_assignment_write(db, monkeypatch, status):
    await seed(db)
    monkeypatch.setattr(drivers, "db", db)
    before = deepcopy(await db.orders.find_one({"id": ORDER}))
    result = await drivers.update_driver_status(DRIVER, DriverStatusUpdate(status=status), None, ADMIN)
    assert result["operational_status"] == status
    driver = await db.drivers.find_one({"id": DRIVER})
    assert driver["current_order_id"] is None and driver["driver_status"] == status
    assert await db.orders.find_one({"id": ORDER}) == before
    assert await db.order_operations.count_documents({}) == 0


@pytest.mark.parametrize("status", ["break", "offline"])
@mongo_case
async def test_fresh_claim_refuses_pause_offline_without_side_effect(db, monkeypatch, status):
    await seed(db)
    await OrderAssignmentService(db).assign(ORDER, command(), ADMIN)
    monkeypatch.setattr(drivers, "db", db)
    before = await db.drivers.find_one({"id": DRIVER})
    with pytest.raises(HTTPException) as exc:
        await drivers.update_driver_status(DRIVER, DriverStatusUpdate(status=status), None, ADMIN)
    assert exc.value.status_code == 409
    assert await db.drivers.find_one({"id": DRIVER}) == before


@mongo_case
async def test_disable_count_snapshot_cannot_disable_new_assignment(db, monkeypatch):
    await seed(db)

    class Orders:
        async def count_documents(self, *args, **kwargs):
            count = await db.orders.count_documents(*args, **kwargs)
            result = await OrderAssignmentService(db).assign(ORDER, command(), ADMIN)
            assert result.result.state == "applied"
            return count

    class Overlay:
        orders = Orders()
        def __getattr__(self, name):
            return getattr(db, name)

    monkeypatch.setattr(drivers, "db", Overlay())
    with pytest.raises(HTTPException) as exc:
        await drivers.disable_driver_account(DRIVER, None, ADMIN)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "DRIVER_STATE_CONFLICT"
    driver = await db.drivers.find_one({"id": DRIVER})
    assert driver["current_order_id"] == ORDER and driver["account_disabled"] is False
    user = await db.users.find_one({"id": DRIVER + "-user"})
    assert user["account_disabled"] is False
    assert await db.audit_logs.count_documents({}) == 1


@mongo_case
async def test_prior_disable_blocks_assignment_and_linked_user_failure_is_retryable(db, monkeypatch):
    await seed(db)

    class Users:
        async def update_one(self, *args, **kwargs):
            raise AutoReconnect("Synthetic linked account failure")

    class Overlay:
        users = Users()
        def __getattr__(self, name):
            return getattr(db, name)

    monkeypatch.setattr(drivers, "db", Overlay())
    with pytest.raises(HTTPException) as exc:
        await drivers.disable_driver_account(DRIVER, None, ADMIN)
    assert exc.value.status_code == 503 and exc.value.detail["code"] == "DRIVER_DISABLE_INCOMPLETE"
    driver = await db.drivers.find_one({"id": DRIVER})
    assert driver["account_disabled"] is True and driver["current_order_id"] is None
    user = await db.users.find_one({"id": DRIVER + "-user"})
    assert user["account_disabled"] is False
    result = await OrderAssignmentService(db).assign(ORDER, command(), ADMIN)
    assert result.result.state == "rejected" and result.result.error_code == "DRIVER_DISABLED"
    assert (await db.orders.find_one({"id": ORDER}))["driver_id"] is None
    monkeypatch.setattr(drivers, "db", db)
    await drivers.disable_driver_account(DRIVER, None, ADMIN)
    assert (await db.users.find_one({"id": DRIVER + "-user"}))["account_disabled"] is True


@mongo_case
async def test_valid_retained_future_break_does_not_strand_released_delivery_driver(db):
    await seed(db)
    await db.drivers.update_one({"id": OLD_DRIVER}, {"$set": {
        "driver_status": "active", "break_started_at": "2099-01-01T00:00:00+00:00",
        "break_until": "2099-01-01T01:00:00+00:00",
    }})
    first = await OrderAssignmentService(db).assign(ORDER, command(driver=OLD_DRIVER), ADMIN)
    assert first.result.state == "applied"
    second = await OrderAssignmentService(db).assign(
        ORDER, command(op=OP + "_reassign", version=VERSION + 1), ADMIN)
    assert second.result.state == "applied"
    old = await db.drivers.find_one({"id": OLD_DRIVER})
    assert old["current_order_id"] is None and old["driver_status"] == "active"
    assert old["break_until"] == "2099-01-01T01:00:00+00:00"
