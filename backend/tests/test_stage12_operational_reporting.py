"""Finite real-auth/real-Mongo operational closure and incident acceptance."""
import asyncio
from functools import wraps
from hashlib import sha256
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import uuid
from unittest.mock import patch
import pytest
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import AutoReconnect

APP = Path(__file__).resolve().parents[2]
Q = APP / ".ifrim/QA_RUNS/2026-10-10-stage12-closure"
spec = importlib.util.spec_from_file_location("_stage12_owner_qa", Q / "bootstrap.py")
qa = importlib.util.module_from_spec(spec); spec.loader.exec_module(qa)
TAG = getattr(sys.modules.get("stage12_owner_bootstrap"), "RUN_TAG", "standalone")

def case(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        async def main():
            runtime, state = qa.runtime()
            assert sha256((Q / "runtime.py").read_bytes()).hexdigest().upper() == "9D2FC2C19F96561A37F8F868AEE8C220EFB7DB1E0572D022EE02AA982095B45B"
            client = AsyncIOMotorClient(runtime.URI, serverSelectionTimeoutMS=2500, connectTimeoutMS=2500, socketTimeoutMS=5000)
            db = client[qa.PREFIX + "owner_" + uuid.uuid4().hex]
            lane = qa.build(db)
            lane.proof = {"test": fn.__name__, "database": db.name, "mongo_pid": state["pid"], "events": []}
            try:
                await qa.seed(lane)
                await fn(lane, *args, **kwargs)
                lane.proof["passed"] = True
            except BaseException as error:
                lane.proof.update(passed=False, error_type=type(error).__name__)
                raise
            finally:
                evidence = Q / "backend-owner" / (TAG + "-" + fn.__name__ + "-" + uuid.uuid4().hex + ".json")
                qa.write_json(evidence, lane.proof)
                client.close()
        return asyncio.run(main())
    run.__signature__ = inspect.signature(fn).replace(parameters=list(inspect.signature(fn).parameters.values())[1:])
    return run

async def request(lane, method, path, role="restaurant1", body=None, *, actor_header=None, query=None):
    actor = qa.ACTORS[role][1]
    tokens = await qa.tokens(lane, actor)
    async with AsyncClient(transport=ASGITransport(app=lane.app), base_url="http://qa.invalid", timeout=15) as http:
        http.cookies.set("access_token", tokens["access"])
        headers = {"X-Expected-Actor-ID": actor if actor_header is None else actor_header}
        kwargs = {"headers": headers}
        if body is not None: kwargs["json"] = body
        if query is not None: kwargs["params"] = query
        response = await http.request(method, path, **kwargs)
    lane.proof["events"].append({"method": method, "path": path, "actor": actor, "status": response.status_code})
    return response

def uid(): return str(uuid.uuid4())
def incident(operation_id=None, revision=7, kind="other", description="Synthetic operational fact"):
    return {"client_operation_id": operation_id or uid(), "expected_order_version": revision,
            "incident_type": kind, "description": description}

def check(response, status=200, state="applied"):
    assert response.status_code == status, (response.status_code, response.json())
    assert response.json()["state"] == state
    assert response.headers["cache-control"] == "no-store"
    return response.json()

async def snap(lane):
    names = ("users", "restaurants", "drivers", "orders", "operational_operations", "order_incidents", "audit_logs", "counters")
    return {n: await lane.db[n].find({}).sort("_id", 1).to_list(1000) for n in names}

@case
async def test_close_day_preserves_active_and_paused_state_replays_one_audit(lane):
    from models.order_mutation import CreateOrderCommand
    from utils.order_creation import OrderCreationService
    await qa.order(lane, "active", status="PICKED_UP", driver="s12-d1")
    business_before = (await snap(lane))
    op = uid(); path = "/api/restaurants/s12-r1/close-day"
    first = check(await request(lane, "PATCH", path, body={"client_operation_id": op}))
    assert first["accepting_orders"] is True and first["pause_until"] is None
    assert first["close_day_operation_id"] == op
    check(await request(lane, "PATCH", path, body={"client_operation_id": op}), state="replayed")
    check(await request(lane, "GET", path + "/operations/" + op), state="replayed")
    check(await request(lane, "POST", path + "/operations/" + op + "/resume"), state="replayed")
    after = await snap(lane)
    for name in ("orders", "drivers", "counters", "order_incidents"):
        assert after[name] == business_before[name]
    assert await lane.db.audit_logs.count_documents({"action": "restaurant.closed_day"}) == 1
    # Actual recoverable admission after closure, not merely a flag assertion.
    actor = await lane.auth.resolve_user_context("s12-restaurant1")
    command = CreateOrderCommand(client_operation_id=uid(), order={"restaurant_id":"s12-r1", "customer_name":"Synthetic client",
        "customer_phone":"0700000012", "customer_address":"Synthetic address", "total_amount":46.0, "payment_type":"CASH"})
    assert (await OrderCreationService(lane.db).create(command, actor)).result.state == "applied"
    paused = await request(lane, "PATCH", "/api/restaurants/s12-r1/status", "admin1", {"accepting_orders":False, "pause_minutes":37})
    assert paused.status_code == 200
    exact = (await lane.db.restaurants.find_one({"id":"s12-r1"}))["pause_until"]
    second = check(await request(lane, "PATCH", path, body={"client_operation_id":uid()}))
    assert second["accepting_orders"] is False and second["pause_until"] == exact
    assert await lane.db.orders.count_documents({"id":"active", "status":"PICKED_UP"}) == 1

@case
async def test_self_pause_resume_foreign_actor_and_bad_uuid_have_no_writes(lane):
    before = await snap(lane)
    for payload in ({"accepting_orders":False,"pause_minutes":15}, {"accepting_orders":True}, {"accepting_orders":False,"closed_today":True}):
        response = await request(lane,"PATCH","/api/restaurants/s12-r1/status",body=payload)
        assert response.status_code == 403
    assert (await request(lane,"PATCH","/api/restaurants/s12-r1/close-day","restaurant2",{"client_operation_id":uid()})).status_code == 403
    assert (await request(lane,"PATCH","/api/restaurants/s12-r1/close-day",body={"client_operation_id":uid()},actor_header="s12-admin1")).status_code == 403
    invalid = await request(lane,"PATCH","/api/restaurants/s12-r1/close-day",body={"client_operation_id":"invalid", "description":"private sentinel"})
    assert invalid.status_code == 422 and "private sentinel" not in invalid.text
    assert await snap(lane) == before

@case
async def test_closure_concurrent_admin_pause_preserves_exact_deadline_both_orders(lane):
    from models.operational_reporting import CloseDayCommand
    from utils.operational_reporting import OperationalReportingService
    actor = await lane.auth.resolve_user_context("s12-restaurant1")
    for closure_first in (False, True):
        await request(lane,"PATCH","/api/restaurants/s12-r1/status","admin1",{"accepting_orders":True})
        service = OperationalReportingService(lane.db,"close_day"); command = CloseDayCommand(client_operation_id=uid())
        if closure_first:
            assert (await service.submit("s12-r1",command,actor)).status_code == 200
            pause = await request(lane,"PATCH","/api/restaurants/s12-r1/status","admin1",{"accepting_orders":False,"pause_minutes":23})
            assert pause.status_code == 200
        else:
            reached, release = asyncio.Event(), asyncio.Event()
            original = service._apply; calls = 0
            async def barrier(*args):
                nonlocal calls
                calls += 1
                if calls == 1:
                    reached.set(); await asyncio.wait_for(release.wait(),5)
                return await original(*args)
            service._apply = barrier
            task=asyncio.create_task(service.submit("s12-r1",command,actor))
            await asyncio.wait_for(reached.wait(),5)
            pause=await request(lane,"PATCH","/api/restaurants/s12-r1/status","admin1",{"accepting_orders":False,"pause_minutes":23})
            assert pause.status_code==200
            release.set(); assert (await asyncio.wait_for(task,10)).status_code==200
        target=await lane.db.restaurants.find_one({"id":"s12-r1"})
        assert target["accepting_orders"] is False and target["pause_until"]==pause.json()["pause_until"]
        assert target["close_day_operation_id"]==command.client_operation_id
    assert await lane.db.audit_logs.count_documents({"action":"restaurant.closed_day"})==2

@case
async def test_close_day_rollback_and_disabled_admission_bodyless_resume(lane):
    from models.operational_reporting import CloseDayCommand
    from utils.operational_reporting import OperationalReportingService
    actor=await lane.auth.resolve_user_context("s12-restaurant1")
    service=OperationalReportingService(lane.db,"close_day"); command=CloseDayCommand(client_operation_id=uid())
    original=service._apply
    async def fail_after_writes(*args):
        await original(*args)
        raise AutoReconnect("Synthetic post-write failure")
    service._apply=fail_after_writes
    before=await lane.db.restaurants.find_one({"id":"s12-r1"})
    assert (await service.submit("s12-r1",command,actor)).status_code==202
    assert await lane.db.restaurants.find_one({"id":"s12-r1"})==before
    assert await lane.db.audit_logs.count_documents({})==0
    await lane.db.order_operation_settings.update_one({"_id":"restaurant-close-day-v1"},{"$set":{"enabled":False}})
    path="/api/restaurants/s12-r1/close-day"
    assert (await request(lane,"PATCH",path,body={"client_operation_id":uid()})).status_code==503
    check(await request(lane,"GET",path+"/operations/"+command.client_operation_id),202,"pending")
    bad=await request(lane,"POST",path+"/operations/"+command.client_operation_id+"/resume",body={"bad":"private sentinel"})
    assert bad.status_code==422 and "private sentinel" not in bad.text
    check(await request(lane,"POST",path+"/operations/"+command.client_operation_id+"/resume"))
    assert await lane.db.audit_logs.count_documents({})==1

@pytest.mark.parametrize("role,version",[("admin1",7),("restaurant1",7),("driver1",7),("admin1",None),("restaurant1",None),("driver1",None)])
@case
async def test_incident_allowed_roles_and_legacy_preserve_all_business_fields(lane,role,version):
    original=await qa.order(lane,"incident-target",status="PICKED_UP",revision=version,driver="s12-d1")
    stored=await lane.db.orders.find_one({"id":"incident-target"})
    driver=await lane.db.drivers.find_one({"id":"s12-d1"})
    body=incident(revision=version,kind="damaged_product",description="  Synthetic observed damage  ")
    path="/api/orders/operations/incident/incident-target"
    first=check(await request(lane,"POST",path,role,body))
    assert first["order_version"]==(version+1 if version is not None else None)
    check(await request(lane,"POST",path,role,body),state="replayed")
    check(await request(lane,"GET",path+"/"+body["client_operation_id"],role),state="replayed")
    now=await lane.db.orders.find_one({"id":"incident-target"})
    for key,value in stored.items():
        if key not in ("order_version","audit_trail"): assert now[key]==value
    assert ("order_version" in now)==(version is not None)
    assert now["incident_summary"][0]["id"]==first["incident_id"]
    assert "description" not in now["incident_summary"][0]
    current_driver=await lane.db.drivers.find_one({"id":"s12-d1"})
    assert {k:v for k,v in current_driver.items() if k!="operational_admission_revision"}==driver
    assert await lane.db.order_incidents.count_documents({})==1
    assert await lane.db.audit_logs.count_documents({})==1
    fact=await lane.db.order_incidents.find_one({})
    assert fact["description"]=="Synthetic observed damage"
    assert now["audit_trail"][-1]["id"]==(await lane.db.audit_logs.find_one({}))["id"]
    assert fact["operation_ref"]==now["audit_trail"][-1]["operation_ref"]

@case
async def test_incident_strict_intent_conflicts_unauthorized_and_stale_version(lane):
    await qa.order(lane,"scope-target",driver="s12-d1",status="ACCEPTED")
    body=incident(); path="/api/orders/operations/incident/scope-target"
    before=await snap(lane)
    for role in ("restaurant2","driver2"):
        assert (await request(lane,"POST",path,role,body)).status_code==403
    assert (await request(lane,"POST",path,"restaurant1",body,actor_header="s12-admin1")).status_code==403
    assert await snap(lane)==before
    check(await request(lane,"POST",path,"restaurant1",body))
    baseline=await snap(lane)
    for changed in ({**body,"description":"Different fact"},{**body,"incident_type":"missing_product"},{**body,"expected_order_version":8}):
        r=await request(lane,"POST",path,"restaurant1",changed); assert r.status_code==409 and r.json()["detail"]["code"]=="INTENT_CONFLICT"
    await qa.order(lane,"other-target")
    assert (await request(lane,"POST","/api/orders/operations/incident/other-target","restaurant1",body)).status_code==409
    assert await lane.db.order_incidents.count_documents({})==1
    stale=check(await request(lane,"POST",path,"admin1",incident(revision=7)),409,"rejected")
    assert stale["error_code"]=="ORDER_VERSION_CONFLICT"
    assert await lane.db.order_incidents.count_documents({})==1

@case
async def test_incident_rollback_pending_disable_resume_lineage_and_private_pagination(lane):
    from models.operational_reporting import IncidentCommand
    from utils.operational_reporting import OperationalReportingService
    await qa.order(lane,"private-target",status="PICKED_UP",driver="s12-d1")
    actor=await lane.auth.resolve_user_context("s12-restaurant1")
    service=OperationalReportingService(lane.db,"incident"); body=incident(description="Private incident sentinel")
    original=service._apply
    async def failure(*args):
        await original(*args); raise AutoReconnect("Synthetic audit/ledger rollback fault")
    service._apply=failure
    old=await lane.db.orders.find_one({"id":"private-target"})
    assert (await service.submit("private-target",IncidentCommand(**body),actor)).status_code==202
    assert await lane.db.orders.find_one({"id":"private-target"})==old
    assert await lane.db.order_incidents.count_documents({})==0 and await lane.db.audit_logs.count_documents({})==0
    await lane.db.order_operation_settings.update_one({"_id":"order-incident-v1"},{"$set":{"enabled":False}})
    path="/api/orders/operations/incident/private-target/"+body["client_operation_id"]
    check(await request(lane,"GET",path),202,"pending")
    check(await request(lane,"POST",path+"/resume"))
    assert (await request(lane,"POST","/api/orders/operations/incident/private-target",body=incident(revision=8))).status_code==503
    detail=await request(lane,"GET","/api/orders/private-target/incidents",query={"limit":1})
    assert detail.status_code==200 and detail.headers["cache-control"]=="no-store"
    assert detail.json()["incidents"][0]["description"]=="Private incident sentinel"
    assert (await request(lane,"GET","/api/orders/private-target/incidents","restaurant2")).status_code==403
    assert (await request(lane,"GET","/api/orders/private-target/incidents",query={"cursor":"invalid"})).status_code==422
    await lane.db.order_operation_settings.update_one({"_id":"order-incident-v1"},{"$set":{"enabled":True}})
    check(await request(lane,"POST","/api/orders/operations/incident/private-target",body=incident(revision=8)))
    page1=(await request(lane,"GET","/api/orders/private-target/incidents",query={"limit":1})).json()
    assert page1["next_cursor"] and len(page1["incidents"])==1
    page2=(await request(lane,"GET","/api/orders/private-target/incidents",query={"limit":1,"cursor":page1["next_cursor"]})).json()
    assert page2["next_cursor"] is None and page1["incidents"][0]["id"]!=page2["incidents"][0]["id"]

@pytest.mark.parametrize("incident_first",[False,True])
@case
async def test_incident_vs_delivery_claim_and_revision_are_fenced(lane,incident_first):
    from models.operational_reporting import IncidentCommand
    from models.order_mutation import StatusOrderCommand
    from utils.operational_reporting import OperationalReportingService,ReportingError
    from utils.order_status import OrderStatusService
    await qa.order(lane,"delivery-target",status="PICKED_UP",driver="s12-d1")
    actor=await lane.auth.resolve_user_context("s12-driver1")
    report=OperationalReportingService(lane.db,"incident"); command=IncidentCommand(**incident())
    delivered=StatusOrderCommand(client_operation_id=uid(),expected_order_version=7,status="DELIVERED")
    if incident_first:
        assert (await report.submit("delivery-target",command,actor)).status_code==200
        result=await OrderStatusService(lane.db).status("delivery-target",delivered,actor)
        assert result.status_code==409 and result.result.error_code=="ORDER_VERSION_CONFLICT"
        assert (await lane.db.drivers.find_one({"id":"s12-d1"}))["current_order_id"]=="delivery-target"
    else:
        reached,release=asyncio.Event(),asyncio.Event(); original=report._actor;calls=0
        async def barrier(who, session=None):
            nonlocal calls
            user = await original(who, session)
            if session is not None:
                calls += 1
                if calls == 1:
                    captured = await lane.db.orders.find_one({"id":"delivery-target"}, session=session)
                    assert captured["order_version"] == 7 and captured["status"] == "PICKED_UP"
                    reached.set(); await asyncio.wait_for(release.wait(),5)
            return user
        report._actor=barrier
        task=asyncio.create_task(report.submit("delivery-target",command,actor))
        await asyncio.wait_for(reached.wait(),5)
        assert (await OrderStatusService(lane.db).status("delivery-target",delivered,actor)).status_code==200
        release.set()
        with pytest.raises(ReportingError) as err: await asyncio.wait_for(task,10)
        assert err.value.status_code==403
        assert await lane.db.order_incidents.count_documents({})==0
        assert (await lane.db.drivers.find_one({"id":"s12-d1"}))["current_order_id"] is None
    assert (await lane.db.orders.find_one({"id":"delivery-target"}))["order_version"]==8

@case
async def test_preparing_ready_projection_has_same_committed_event_identity(lane):
    await qa.order(lane,"audit-target")
    for method,path,body,action in (("PUT","/api/orders/audit-target/preparing",{"preparation_time":20},"order.preparing_started"),
                                  ("PUT","/api/orders/audit-target/ready",None,"order.ready")):
        response=await request(lane,method,path,body=body); assert response.status_code==200
        order=await lane.db.orders.find_one({"id":"audit-target"})
        event=order["audit_trail"][-1]
        projected=await lane.db.audit_logs.find_one({"entity_id":"audit-target","action":action})
        assert projected["id"]==event["id"]
        for key in ("request_id","operation_ref","from_order_version","to_order_version","created_at"):
            assert projected[key]==event[key]
        assert str(uuid.UUID(event["request_id"]))==event["request_id"]
        count=await lane.db.audit_logs.count_documents({"entity_id":"audit-target"})
        assert (await request(lane,method,path,body=body)).status_code==200
        assert await lane.db.audit_logs.count_documents({"entity_id":"audit-target"})==count


@case
async def test_concurrent_same_closure_uuid_has_one_receipt_and_effect(lane):
    from models.operational_reporting import CloseDayCommand
    from utils.operational_reporting import OperationalReportingService
    actor=await lane.auth.resolve_user_context("s12-restaurant1")
    service=OperationalReportingService(lane.db,"close_day"); command=CloseDayCommand(client_operation_id=uid())
    outcomes=await asyncio.gather(service.submit("s12-r1",command,actor),service.submit("s12-r1",command,actor))
    assert all(o.status_code==200 for o in outcomes)
    assert outcomes[0].result["closed_at"]==outcomes[1].result["closed_at"]
    assert await lane.db.operational_operations.count_documents({})==1
    assert await lane.db.audit_logs.count_documents({"action":"restaurant.closed_day"})==1
    assert len((await lane.db.restaurants.find_one({"id":"s12-r1"}))["closure_audit_trail"])==1

@pytest.mark.parametrize("incident_first",[False,True])
@case
async def test_incident_vs_reassignment_revalidates_actual_current_driver(lane,incident_first):
    from models.operational_reporting import IncidentCommand
    from models.order_mutation import AssignOrderCommand
    from utils.operational_reporting import OperationalReportingService,ReportingError
    from utils.order_assignment import OrderAssignmentService
    await qa.order(lane,"reassign-target",status="ASSIGNED",driver="s12-d1")
    driver=await lane.auth.resolve_user_context("s12-driver1"); admin=await lane.auth.resolve_user_context("s12-admin1")
    report=OperationalReportingService(lane.db,"incident"); command=IncidentCommand(**incident())
    assignment=AssignOrderCommand(client_operation_id=uid(),expected_order_version=7,driver_id="s12-d2")
    if incident_first:
        assert (await report.submit("reassign-target",command,driver)).status_code==200
        outcome=await OrderAssignmentService(lane.db).assign("reassign-target",assignment,admin)
        assert outcome.status_code==409 and outcome.result.error_code=="ORDER_VERSION_CONFLICT"
        assert (await lane.db.orders.find_one({"id":"reassign-target"}))["driver_id"]=="s12-d1"
        assert (await lane.db.drivers.find_one({"id":"s12-d1"}))["current_order_id"]=="reassign-target"
        assert (await lane.db.drivers.find_one({"id":"s12-d2"}))["current_order_id"] is None
    else:
        reached,release=asyncio.Event(),asyncio.Event(); original=report._actor; calls=0
        async def barrier(actor,session=None):
            nonlocal calls
            user=await original(actor,session)
            if session is not None:
                calls+=1
                if calls==1:
                    snapshot=await lane.db.orders.find_one({"id":"reassign-target"},session=session)
                    assert snapshot["order_version"]==7 and snapshot["driver_id"]=="s12-d1"
                    reached.set(); await asyncio.wait_for(release.wait(),5)
            return user
        report._actor=barrier
        task=asyncio.create_task(report.submit("reassign-target",command,driver))
        await asyncio.wait_for(reached.wait(),5)
        assert (await OrderAssignmentService(lane.db).assign("reassign-target",assignment,admin)).status_code==200
        release.set()
        with pytest.raises(ReportingError) as error: await asyncio.wait_for(task,10)
        assert error.value.status_code==403
        assert await lane.db.order_incidents.count_documents({})==0
        assert (await lane.db.drivers.find_one({"id":"s12-d1"}))["current_order_id"] is None
        assert (await lane.db.drivers.find_one({"id":"s12-d2"}))["current_order_id"]=="reassign-target"
    assert (await lane.db.orders.find_one({"id":"reassign-target"}))["order_version"]==8

@case
async def test_preparation_projection_failure_repaired_by_duplicate_without_new_event(lane):
    await qa.order(lane,"projection-fault")
    actual=lane.modules["orders"].db
    class FailingAudit:
        async def find_one(self,*args,**kwargs): return None
        async def insert_one(self,*args,**kwargs): raise AutoReconnect("Synthetic projection unavailable")
    class Wrapper:
        audit_logs=FailingAudit()
        def __getattr__(self,name): return getattr(actual,name)
    lane.modules["orders"].db=Wrapper()
    try:
        response=await request(lane,"PUT","/api/orders/projection-fault/preparing",body={"preparation_time":20})
        assert response.status_code==200
    finally: lane.modules["orders"].db=actual
    order=await lane.db.orders.find_one({"id":"projection-fault"})
    assert order["order_version"]==8 and len(order["audit_trail"])==1
    assert await lane.db.audit_logs.count_documents({})==0
    retry=await request(lane,"PUT","/api/orders/projection-fault/preparing",body={"preparation_time":20})
    assert retry.status_code==200 and retry.json()["idempotent"] is True
    assert await lane.db.orders.find_one({"id":"projection-fault"})==order
    projected=await lane.db.audit_logs.find_one({})
    assert projected["id"]==order["audit_trail"][0]["id"]
    assert projected["request_id"]==order["audit_trail"][0]["request_id"]
    assert await lane.db.audit_logs.count_documents({})==1

@case
async def test_terminal_incident_receipt_strict_integer_corruption_is_read_only(lane):
    await qa.order(lane,"receipt-corruption",revision=0)
    body=incident(revision=0);path="/api/orders/operations/incident/receipt-corruption"
    valid=check(await request(lane,"POST",path,body=body));assert valid["order_version"]==1
    ledger=await lane.db.operational_operations.find_one({"client_operation_id":body["client_operation_id"]})
    for invalid in (True,1.0):
        await lane.db.operational_operations.update_one({"_id":ledger["_id"]},{"$set":{"receipt.order_version":invalid}})
        before=await snap(lane)
        for method,suffix in (("GET",""),("POST","/resume")):
            response=await request(lane,method,path+"/"+body["client_operation_id"]+suffix)
            assert response.status_code==503 and response.json()["detail"]["code"]=="OPERATION_INVALID"
            assert await snap(lane)==before
    await lane.db.operational_operations.update_one({"_id":ledger["_id"]},{"$set":{"receipt.order_version":1}})
    check(await request(lane,"GET",path+"/"+body["client_operation_id"]),state="replayed")
    assert await lane.db.order_incidents.count_documents({})==1 and await lane.db.audit_logs.count_documents({})==1

@case
async def test_source_audit_uses_original_legacy_database_value_never_spoofed_input_or_log(lane,caplog):
    import logging
    caplog.set_level(logging.INFO)
    await qa.order(lane,"source-original",revision=None)
    source="manual_restaurant"  # Legacy Order accepts strings beyond new admission's length bound.
    await lane.db.orders.update_one({"id":"source-original"},{"$set":{"source":source}})
    spoof="Private source spoof sentinel"
    before=await snap(lane)
    denied=await request(lane,"POST","/api/orders/operations/incident/source-original",body={**incident(revision=None),"source":spoof})
    assert denied.status_code==422 and spoof not in denied.text and await snap(lane)==before
    assert (await request(lane,"PUT","/api/orders/source-original/preparing",body={"preparation_time":20,"source":spoof})).status_code==422
    assert await snap(lane)==before
    assert (await request(lane,"PUT","/api/orders/source-original/preparing",body={"preparation_time":20})).status_code==200
    assert (await request(lane,"PUT","/api/orders/source-original/ready")).status_code==200
    body=incident(revision=None,description="Private incident description sentinel")
    check(await request(lane,"POST","/api/orders/operations/incident/source-original",body=body))
    order=await lane.db.orders.find_one({"id":"source-original"});assert order["source"]==source and "order_version" not in order
    assert len(order["audit_trail"])==3
    for event in order["audit_trail"]:
        projected=await lane.db.audit_logs.find_one({"_id":event["id"]})
        assert event["source"]==source and projected["source"]==source and projected["id"]==event["id"]
    assert spoof not in caplog.text and source not in caplog.text and body["description"] not in caplog.text

@case
async def test_existing_four_service_audits_join_authoritative_immutable_order_source(lane):
    from models.order_mutation import OrderCorrections
    from pydantic import ValidationError
    with pytest.raises(ValidationError):OrderCorrections(source="spoof")
    body={"client_operation_id":uid(),"order":{"restaurant_id":"s12-r1","customer_name":"Synthetic source client","customer_phone":"0700000012","customer_address":"Synthetic source address","total_amount":46.0,"payment_type":"CASH","source":"R_WEB"}}
    created=check(await request(lane,"POST","/api/orders/operations/create",body=body),status=201);created_id=created["order_id"]
    # Creation deliberately preserves current legacy consumers; no lazy promotion.
    assert "order_version" not in await lane.db.orders.find_one({"id":created_id})
    oid="versioned-source-join";await qa.order(lane,oid,revision=7)
    await lane.db.orders.update_one({"id":oid},{"$set":{"source":"R_WEB"}})
    edit={"client_operation_id":uid(),"expected_order_version":7,"changes":{"notes":"Synthetic correction"}}
    check(await request(lane,"POST","/api/orders/operations/edit/"+oid,"admin1",edit))
    assign={"client_operation_id":uid(),"expected_order_version":8,"driver_id":"s12-d1"}
    check(await request(lane,"POST","/api/orders/operations/assign/"+oid,"admin1",assign))
    status={"client_operation_id":uid(),"expected_order_version":9,"status":"ACCEPTED"}
    check(await request(lane,"POST","/api/orders/operations/status/"+oid,"driver1",status))
    target=await lane.db.orders.find_one({"id":oid});assert target["source"]=="R_WEB" and target["order_version"]==10
    created_target=await lane.db.orders.find_one({"id":created_id})
    assert len(target["audit_trail"])==3 and len(created_target["audit_trail"])==1
    for event in created_target["audit_trail"]+target["audit_trail"]:
        projected=await lane.db.audit_logs.find_one({"_id":event["id"]})
        operation=await lane.db.order_operations.find_one({"_id":event["operation_ref"]})
        assert projected["id"]==event["id"] and projected["entity_id"] in {oid,created_id}
        assert operation["order_id"]==projected["entity_id"] and operation["state"]=="applied"
        assert (await lane.db.orders.find_one({"id":projected["entity_id"]}))["source"]=="R_WEB"
        if event["action"]=="order.created":assert operation["command"]["order"]["source"]=="R_WEB"
        else:assert "source" not in operation["command"] and "source" not in operation["command"].get("changes",{})

@case
async def test_historical_preparation_projection_has_no_second_row_or_implicit_migration(lane):
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc).isoformat()
    for suffix,action,status in (("preparing","order.preparing_started","PREPARING"),("ready","order.ready","READY")):
        oid="historic-"+suffix;await qa.order(lane,oid,status=status,revision=None)
        event={"id":uid(),"action":action,"changes":{},"performed_by":"s12-restaurant1","performed_by_role":"restaurant","created_at":now}
        old={**event,"id":uid(),"entity_type":"order","entity_id":oid}
        await lane.db.audit_logs.insert_one(old)
        await lane.db.orders.update_one({"id":oid},{"$set":{"preparation_status":status,"preparation_time":20,"preparation_started_at":now,"preparation_ready_at":now if status=="READY" else None,"audit_trail":[event]}})
    before=await snap(lane)
    for suffix,body in (("preparing",{"preparation_time":20}),("ready",None)):
        response=await request(lane,"PUT","/api/orders/historic-"+suffix+"/"+suffix,body=body)
        assert response.status_code==200 and response.json()["idempotent"] is True
        assert await snap(lane)==before
    assert await lane.db.audit_logs.count_documents({})==2

@case
async def test_preparation_projection_requires_canonical_new_event_lineage(lane):
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc).isoformat()
    for index,kind in enumerate(("invalid_event_id","uppercase_request","missing_request","wrong_ref")):
        oid="invalid-lineage-"+str(index);await qa.order(lane,oid,status="PREPARING",revision=None)
        event_id=uid();event={"id":event_id,"action":"order.preparing_started","changes":{},"performed_by":"s12-restaurant1","performed_by_role":"restaurant","created_at":now,"request_id":uid(),"operation_ref":"order-audit:"+event_id}
        if kind=="invalid_event_id":event["id"]="not-a-uuid";event["operation_ref"]="order-audit:not-a-uuid"
        elif kind=="uppercase_request":event["request_id"]=uid().upper()
        elif kind=="missing_request":event.pop("request_id")
        else:event["operation_ref"]="order-audit:"+uid()
        await lane.db.orders.update_one({"id":oid},{"$set":{"preparation_status":"PREPARING","preparation_time":20,"preparation_started_at":now,"audit_trail":[event]}})
        before=await snap(lane)
        response=await request(lane,"PUT","/api/orders/"+oid+"/preparing",body={"preparation_time":20})
        assert response.status_code==200 and response.json()["idempotent"] is True
        assert await snap(lane)==before
    assert await lane.db.audit_logs.count_documents({})==0
