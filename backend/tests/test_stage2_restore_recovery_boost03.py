"""Two operational restore scenarios with real service-generated ledgers.
Actual JWT/auth.router/recovery HTTP routes, OTHER owned DB, no real config.
"""
import asyncio
from contextlib import contextmanager, asynccontextmanager
import importlib.util
from pathlib import Path
import uuid
from bson.int64 import Int64
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
import bootstrap as qa

HERE = qa.HERE
spec = importlib.util.spec_from_file_location("_auth03_restore_copy", HERE / "restore-copy.py")
copy_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(copy_helper)
REVISED = "QA RESTORE03 private revised note"
REASON = "QA RESTORE03 private cancellation reason"

def private_receipt(response):
    qa.assert_private_free(response)
    for value in (REVISED, REASON):
        assert value not in response.text

@pytest.fixture
def restore_case(request):
    def run(scenario):
        async def isolated():
            runtime, state = qa.verified_runtime()
            client = AsyncIOMotorClient(runtime.URI, serverSelectionTimeoutMS=2000,
                                        connectTimeoutMS=2000, socketTimeoutMS=4000)
            source = client["pd_boost03_restore_src_" + uuid.uuid4().hex]
            lane = qa.build_app(source)
            proof = {"case": request.node.name, "source_db": source.name, "mongo_pid": state["pid"],
                     "source_hashes": qa.source_hashes(), "events": lane.events,
                     "pass": False, "retained": True}
            try:
                await qa.seed(lane)
                # Login is not required by this restore scenario. Never export even synthetic password material.
                await source.users.update_many({}, {"$unset": {"password_hash": ""}})
                await asyncio.wait_for(scenario(lane, client, proof, qa.RUN_TAG + "-" + request.node.name), timeout=35)
                proof["pass"] = True
            finally:
                proof["source_final_hash"] = qa.digest(await qa.snapshot(source))
                qa.exclusive_json(HERE / (qa.RUN_TAG + "-" + request.node.name + ".json"), proof)
                client.close()
        return asyncio.run(isolated())
    return run

@contextmanager
def pause_service(service, expected_command):
    original = service._execute
    async def pause(instance, key, actor, operation_id):
        retained = await instance.operations.find_one({"_id": key})
        assert retained and retained["state"] == "pending"
        assert retained["command"] == expected_command
        return service._pending(operation_id)
    service._execute = pause
    try:
        yield
    finally:
        service._execute = original

async def versioned_order(database, identifier):
    from models.order import Order
    values = qa.command(str(uuid.uuid4()))["order"]
    values.update(subtotal_amount=20, delivery_fee=0)
    document = Order(**values, id=identifier, order_number="QA.RESTORE03",
                     restaurant_name="Synthetic AUTH03 restaurant", preparation_status="NEW").model_dump(mode="json")
    document.update(_id=identifier, order_version=Int64(7))
    await database.orders.insert_one(document)
    return document

@asynccontextmanager
async def authenticated_http(lane, actor_id):
    async with qa.client(lane) as http:
        qa.set_session(http, await qa.sign_tokens(lane, actor_id))
        me = await qa.request(lane, http, "GET", "/api/auth/me", expected=actor_id)
        assert me.status_code == 200 and me.json()["id"] == actor_id
        yield http

async def assert_resumed_mutation(lane, http, *, kind, order_id, operation_id, actor_id, expected_command):
    path = "/api/orders/operations/" + kind + "/" + order_id + "/" + operation_id
    before = await qa.snapshot(lane.database)
    lookup = await qa.request(lane, http, "GET", path, expected=actor_id)
    assert lookup.status_code == 202 and lookup.json()["state"] == "pending"
    private_receipt(lookup)
    assert await qa.snapshot(lane.database) == before
    result = await qa.request(lane, http, "POST", path + "/resume", expected=actor_id)
    assert result.status_code == 200 and result.json()["state"] == "applied"
    assert result.json()["order_id"] == order_id and result.json()["order_version"] == 8
    private_receipt(result)
    operation = await lane.database.order_operations.find_one({"client_operation_id": operation_id})
    assert operation["state"] == "applied" and operation["command"] == expected_command
    assert operation["actor_id"] == actor_id and operation["order_id"] == order_id
    assert operation["order_version"] == 8
    order = await lane.database.orders.find_one({"id": order_id})
    audits = await lane.database.audit_logs.find({"operation_ref": operation["_id"]}).to_list(None)
    assert order["order_version"] == 8
    assert len(order["audit_trail"]) == len(audits) == 1
    assert audits[0]["request_id"] == operation["request_id"]
    assert audits[0]["performed_by"] == actor_id
    assert audits[0]["from_order_version"] == 7 and audits[0]["to_order_version"] == 8
    if kind == "edit":
        assert order["notes"] == REVISED and order["status"] == "NEW"
        assert audits[0]["action"] == "order.corrected"
    else:
        assert order["status"] == "CANCELLED" and order["cancellation_reason"] == REASON
        assert audits[0]["action"] == "order.status_changed"
        assert audits[0]["changes"]["cancellation_reason"] == REASON
    after = await qa.snapshot(lane.database)
    for method, route, payload in (("GET", path, None), ("POST", path + "/resume", None),
                                   ("POST", "/api/orders/operations/" + kind + "/" + order_id, expected_command)):
        replay = await qa.request(lane, http, method, route, expected=actor_id, payload=payload)
        assert replay.status_code == 200 and replay.json()["state"] == "replayed"
        assert replay.json()["order_id"] == order_id and replay.json()["order_version"] == 8
        private_receipt(replay)
        assert await qa.snapshot(lane.database) == after
    return {"kind": kind, "operation_id": operation_id, "order_id": order_id,
            "request_id": operation["request_id"], "order_version": 8, "effects": 1, "audits": 1}

def test_restored_pending_edit_and_status_resume_with_new_admission_disabled(restore_case):
    async def scenario(lane, client, proof, artifact_prefix):
        from models.order_mutation import EditOrderCommand, StatusOrderCommand
        database = lane.database
        await database.order_operation_settings.insert_many([
            {"_id": "order-edit-v1", "enabled": True}, {"_id": "order-status-v1", "enabled": True}])
        edit_order, cancel_order = "restore03-edit-" + uuid.uuid4().hex, "restore03-cancel-" + uuid.uuid4().hex
        await versioned_order(database, edit_order)
        await versioned_order(database, cancel_order)
        edit_id, cancel_id = str(uuid.uuid4()), str(uuid.uuid4())
        edit_command = EditOrderCommand(client_operation_id=edit_id, expected_order_version=7,
                                        changes={"notes": REVISED}).model_dump(mode="json")
        status_command = StatusOrderCommand(client_operation_id=cancel_id, expected_order_version=7,
                                            status="CANCELLED", cancellation_reason=REASON).model_dump(mode="json")
        for kind, service, actor, order, command in (
            ("edit", lane.operations.OrderEditingService, qa.ADMIN, edit_order, edit_command),
            ("status", lane.operations.OrderStatusService, qa.OWNER, cancel_order, status_command)):
            async with authenticated_http(lane, actor) as http:
                with pause_service(service, command):
                    pending = await qa.request(lane, http, "POST", "/api/orders/operations/" + kind + "/" + order,
                                               expected=actor, payload=command)
                assert pending.status_code == 202 and pending.json()["state"] == "pending"
                private_receipt(pending)
        assert await database.order_operations.count_documents({"state": "pending"}) == 2
        assert await database.audit_logs.count_documents({}) == 0
        assert all(order["order_version"] == 7 for order in await database.orders.find({}).to_list(None))
        destination, manifest = await copy_helper.copy_to_other(database, client, artifact_prefix)
        proof.update(manifest)
        restored = qa.build_app(destination)
        proof["restore_events"] = restored.events
        assert all(type(order["order_version"]) is Int64 for order in await destination.orders.find({}).to_list(None))
        # Only OTHER restore is changed; source remains byte-canonically identical.
        await destination.order_operation_settings.update_many({}, {"$set": {"enabled": False}})
        proof["effects"] = []
        for kind, actor, order, operation_id, command in (
            ("edit", qa.ADMIN, edit_order, edit_id, edit_command),
            ("status", qa.OWNER, cancel_order, cancel_id, status_command)):
            async with authenticated_http(restored, actor) as http:
                capability = await qa.request(restored, http, "GET", "/api/orders/operations/" + kind + "/capabilities",
                                              expected=actor)
                assert capability.status_code == 200
                assert capability.json()[kind + "_recovery_enabled"] is False
                proof["effects"].append(await assert_resumed_mutation(
                    restored, http, kind=kind, order_id=order, operation_id=operation_id,
                    actor_id=actor, expected_command=command))
                # A fresh UUID cannot admit through the disabled marker.
                fresh = {**command, "client_operation_id": str(uuid.uuid4()), "expected_order_version": 8}
                before = await qa.snapshot(destination)
                denied = await qa.request(restored, http, "POST", "/api/orders/operations/" + kind + "/" + order,
                                          expected=actor, payload=fresh)
                assert denied.status_code == 503 and denied.json()["detail"]["code"] == (
                    "EDITING_NOT_ENABLED" if kind == "edit" else "STATUS_NOT_ENABLED")
                private_receipt(denied)
                assert await qa.snapshot(destination) == before
        assert await destination.order_operations.count_documents({}) == 2
        assert await destination.audit_logs.count_documents({}) == 2
        assert qa.digest(await qa.snapshot(database)) == proof["source_hash"]
        proof["restore_final_hash"] = qa.digest(await qa.snapshot(destination))
        proof["source_unchanged_after_recovery"] = True
    restore_case(scenario)

def test_restored_applied_creation_receipt_replay_keeps_order_counter_audit(restore_case):
    async def scenario(lane, client, proof, artifact_prefix):
        operation_id = str(uuid.uuid4())
        async with authenticated_http(lane, qa.OWNER) as http:
            created = await qa.request(lane, http, "POST", "/api/orders/operations/create",
                                       payload=qa.command(operation_id))
            assert created.status_code == 201 and created.json()["state"] == "applied"
            ledger = await qa.assert_effect(lane, operation_id)
        source = lane.database
        assert (await source.counters.find_one({"_id": "orders.global"}))["seq"] == 101
        destination, manifest = await copy_helper.copy_to_other(source, client, artifact_prefix)
        proof.update(manifest)
        restored = qa.build_app(destination)
        proof["restore_events"] = restored.events
        await destination.order_operation_settings.update_one({"_id": "order-create-v1"}, {"$set": {"enabled": False}})
        before = await qa.snapshot(destination)
        async with authenticated_http(restored, qa.OWNER) as http:
            path = "/api/orders/operations/create/" + operation_id
            for method, route, payload in (("GET", path, None), ("POST", path + "/resume", None),
                                           ("POST", "/api/orders/operations/create", qa.command(operation_id))):
                replay = await qa.request(restored, http, method, route, payload=payload)
                assert replay.status_code == 200 and replay.json()["state"] == "replayed"
                assert replay.json()["order_id"] == ledger["order_id"] and replay.json()["order_version"] == 0
                private_receipt(replay)
                assert await qa.snapshot(destination) == before
            fresh = await qa.request(restored, http, "POST", "/api/orders/operations/create",
                                     payload=qa.command(str(uuid.uuid4())))
            assert fresh.status_code == 503 and fresh.json()["detail"]["code"] == "CREATION_NOT_ENABLED"
            assert await qa.snapshot(destination) == before
        await qa.assert_effect(restored, operation_id)
        assert await destination.orders.count_documents({}) == 1
        assert await destination.order_operations.count_documents({}) == 1
        assert await destination.audit_logs.count_documents({}) == 1
        assert (await destination.counters.find_one({"_id": "orders.global"}))["seq"] == 101
        assert qa.digest(await qa.snapshot(source)) == proof["source_hash"]
        proof.update(source_unchanged_after_recovery=True, restore_final_hash=qa.digest(await qa.snapshot(destination)),
                     operation_id=operation_id, order_id=ledger["order_id"], effects=1, audits=1, counter=101)
    restore_case(scenario)
