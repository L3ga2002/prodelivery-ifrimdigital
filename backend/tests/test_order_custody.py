"""L5B owner tests on an explicitly verified isolated Mongo replica set."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import uuid
import pytest
from pydantic import ValidationError
from motor.motor_asyncio import AsyncIOMotorClient
from models.order import Order
from models.order_custody import CustodyCommand
from models.order_mutation import StatusOrderCommand
from models.operational_reporting import IncidentCommand
from utils.order_custody import OrderCustodyService, operation_key
import utils.order_custody as custody_module
from utils.custody_activity import inspect_custody, validate_custody_ledger, read_custody_failures, public_custody_read, CustodyError
from utils.financial_activity import inspect_activity, read_activity_failures
from utils.order_status import OrderStatusService, StatusError
from utils.order_reads import OrderReadService
from utils.operational_reporting import OperationalReportingService
from utils.order_revision import ensure_legacy_order
from test_order_creation_recovery import mongo_case, ACTOR, COLLECTIONS, Faults, SimulatedCrash, DatabaseProxy
from test_order_financial_events import accepted, declare, approve, pickup
from test_financial_core_mongo import ADMIN, DRIVER

@pytest.fixture
def db():
    def run(scenario):
        async def isolated():
            import runtime
            assert runtime.PORT == 27951 and runtime.SET == 'pd_l5b_20261014'
            state = json.loads(runtime.STATE.read_text())
            with runtime.direct() as c: runtime.verify_owned(c, state)
            client = AsyncIOMotorClient(runtime.URI, serverSelectionTimeoutMS=2000, socketTimeoutMS=4000)
            database = client['pd_l5b_owner_' + uuid.uuid4().hex]
            try:
                for name in dict.fromkeys((*COLLECTIONS, 'drivers', 'order_incidents', 'order_financial_events', 'order_custody_events')):
                    await database.create_collection(name)
                await database.users.insert_one({**ACTOR, 'account_disabled': False})
                await database.restaurants.insert_one({'id': ACTOR['restaurant_id'], 'name': 'Synthetic Restaurant', 'accepting_orders': True, 'closed_today': False})
                await database.counters.insert_one({'_id': 'orders.global', 'seq': 100})
                await database.order_operation_settings.insert_one({'_id': 'order-create-v1', 'enabled': True})
                await asyncio.wait_for(scenario(database), 60)
            finally: client.close()
        return asyncio.run(isolated())
    return run


def cmd(order, event_type, **kw):
    return CustodyCommand(client_operation_id=str(uuid.uuid4()), expected_order_version=order['order_version'],
        event_type=event_type, incident_id=order.get('custody_activity', {}).get('incident_id', order.get('_incident')), **kw)


def clock(monkeypatch, at):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None): return at.astimezone(tz) if tz else at.replace(tzinfo=None)
    monkeypatch.setattr(custody_module, 'datetime', Frozen)
    monkeypatch.setattr(custody_module, '_timestamp', lambda: at.isoformat())


async def start(db, debt=False):
    order = await accepted(db, ready=True)
    if debt:
        order = await approve(db, await declare(db, order))
    result = await OrderStatusService(db).status(order['id'], pickup(order), DRIVER)
    assert result.result.state == 'applied'
    order = await db.orders.find_one({'id': order['id']})
    await db.order_operation_settings.insert_many([{'_id': x, 'enabled': True} for x in ('order-custody-v1', 'order-incident-v1')])
    incident = await OperationalReportingService(db, 'incident').submit(order['id'], IncidentCommand(
        client_operation_id=str(uuid.uuid4()), expected_order_version=order['order_version'], incident_type='delivery_blocked', description='Synthetic client unavailable'), DRIVER)
    assert incident.result['state'] == 'applied', incident.result
    order = await db.orders.find_one({'id': order['id']})
    order['_incident'] = incident.result['incident_id']
    return order


async def apply(db, order, event_type, actor, **kw):
    command = cmd(order, event_type, **kw)
    result = await OrderCustodyService(db).submit(order['id'], command, actor)
    assert result.result.state == 'applied', result.result
    return await db.orders.find_one({'id': order['id']}), command


async def reviewed(db, monkeypatch, debt=False):
    order = await start(db, debt)
    order, _ = await apply(db, order, 'delivery_wait_started', DRIVER, reason='absent')
    clock(monkeypatch, datetime.fromisoformat(order['custody_activity']['wait_started_at']) + timedelta(seconds=600))
    order, _ = await apply(db, order, 'delivery_failure_reviewed', ADMIN, predecessor_id=order['custody_activity']['wait_event_id'],
        customer_contact_attempted=True, restaurant_contacted=True, coordination_confirmed=True)
    return order


@pytest.mark.parametrize('decision,debt', [('return',False),('keep',False),('return',True),('keep',True)])
@mongo_case
async def test_complete_paths_atomic_preserve_money_reads_and_replay(db, monkeypatch, decision, debt):
    order = await reviewed(db, monkeypatch, debt)
    quote = deepcopy(order['financial'])
    driver_before = await db.drivers.find_one({'id': DRIVER['driver_id']})
    order, _ = await apply(db, order, 'products_disposition_decided', ACTOR, predecessor_id=order['custody_activity']['review_id'], decision=decision)
    assert (await db.drivers.find_one({'id': DRIVER['driver_id']}))['current_order_id'] == order['id']
    event = 'products_return_received' if decision == 'return' else 'products_keep_acknowledged'
    actor = ACTOR if decision == 'return' else DRIVER
    order, command = await apply(db, order, event, actor, predecessor_id=order['custody_activity']['decision_id'])
    assert order['status'] == 'CANCELLED' and order.get('delivered_at') is None
    assert order['financial'] == quote and all(quote[k] is None for k in ('advance_paid_bani','refund_due_bani','refund_paid_bani'))
    after = await db.drivers.find_one({'id': DRIVER['driver_id']})
    assert after['current_order_id'] is None
    for key in ('total_deliveries', 'total_earnings', 'financial_earned_bani'): assert after.get(key) == driver_before.get(key)
    activity = inspect_custody(order)
    await validate_custody_ledger(db, order, activity)
    assert not await read_custody_failures(db, [order])
    assert Order(**order).model_dump(mode='json')['custody_activity'] == order['custody_activity']
    if debt:
        assert inspect_activity(order).outstanding_bani == 3250
        assert not await read_activity_failures(db, [order])
    detail = await OrderReadService(db).detail(ADMIN, order['id'])
    assert detail['order']['custody_activity'] == activity.public(), detail
    assert not detail['order'].get('read_custody_invalid'), detail
    page = await OrderReadService(db).page(ADMIN, view="history")
    assert page['items'][0]['custody_activity'] == activity.public()
    assert 'binding' not in json.dumps(detail['order']['custody_activity'])
    await db.drivers.update_one({'id': DRIVER['driver_id']}, {'$set': {'current_order_id': 'new-task'}})
    replay = await OrderCustodyService(db).submit(order['id'], command, actor)
    assert replay.result.state == 'replayed'
    assert (await db.drivers.find_one({'id': DRIVER['driver_id']}))['current_order_id'] == 'new-task'
    assert await db.order_custody_events.count_documents({}) == 4


@pytest.mark.parametrize('reason', ['absent','refused'])
@mongo_case
async def test_wait_below_and_exact_boundary(db, monkeypatch, reason):
    order = await start(db)
    order, _ = await apply(db, order, 'delivery_wait_started', DRIVER, reason=reason)
    at = datetime.fromisoformat(order['custody_activity']['wait_started_at'])
    clock(monkeypatch, at + timedelta(seconds=599, microseconds=999999))
    result = await OrderCustodyService(db).submit(order['id'], cmd(order, 'delivery_failure_reviewed', predecessor_id=order['custody_activity']['wait_event_id'],
        customer_contact_attempted=True, restaurant_contacted=True, coordination_confirmed=True), ADMIN)
    assert result.result.error_code == 'CUSTODY_WAIT_REQUIRED'
    clock(monkeypatch, at + timedelta(seconds=600))
    order, _ = await apply(db, order, 'delivery_failure_reviewed', ADMIN, predecessor_id=order['custody_activity']['wait_event_id'],
        customer_contact_attempted=True, restaurant_contacted=True, coordination_confirmed=True)
    assert order['custody_activity']['status'] == 'reviewed'


@mongo_case
async def test_pending_recovers_disable_restart_changed_intent(db):
    order = await start(db)
    command = cmd(order, 'delivery_wait_started', reason='refused')
    faults = Faults(); faults.after_admission_crash = True
    with pytest.raises(SimulatedCrash):
        await OrderCustodyService(DatabaseProxy(db, faults)).submit(order['id'], command, DRIVER)
    await db.order_operation_settings.update_one({'_id':'order-custody-v1'}, {'$set':{'enabled':False}})
    service = OrderCustodyService(db)
    assert (await service.lookup(order['id'], command.client_operation_id, DRIVER)).result.state == 'pending'
    assert (await service.resume(order['id'], command.client_operation_id, DRIVER)).result.state == 'applied'
    assert (await service.resume(order['id'], command.client_operation_id, DRIVER)).result.state == 'replayed'
    altered = command.model_dump(); altered['reason'] = 'absent'
    with pytest.raises(StatusError) as e: await service.submit(order['id'], CustodyCommand(**altered), DRIVER)
    assert e.value.code == 'INTENT_CONFLICT'


@pytest.mark.parametrize('delivery_first', [True,False])
@mongo_case
async def test_decision_versus_delivery_both_commit_orders(db, monkeypatch, delivery_first):
    order = await reviewed(db, monkeypatch)
    import utils.order_status as statuses
    monkeypatch.setattr(statuses, '_timestamp', custody_module._timestamp)
    decision = cmd(order, 'products_disposition_decided', predecessor_id=order['custody_activity']['review_id'], decision='return')
    delivery = StatusOrderCommand(client_operation_id=str(uuid.uuid4()), expected_order_version=order['order_version'], status='DELIVERED')
    if delivery_first:
        assert (await OrderStatusService(db).status(order['id'], delivery, DRIVER)).result.state == 'applied'
        with pytest.raises(StatusError) as e: await OrderCustodyService(db).submit(order['id'], decision, ACTOR)
        assert e.value.code == 'CUSTODY_REQUIRES_PICKUP'
    else:
        assert (await OrderCustodyService(db).submit(order['id'], decision, ACTOR)).result.state == 'applied'
        result = await OrderStatusService(db).status(order['id'], delivery, DRIVER)
        assert result.result.state == 'rejected'
    final = await db.orders.find_one({'id':order['id']})
    assert inspect_custody(final)
    assert not await read_custody_failures(db,[final])


@mongo_case
async def test_concurrent_opposite_decisions_one_wins(db, monkeypatch):
    order = await reviewed(db, monkeypatch)
    result = await asyncio.gather(*[OrderCustodyService(db).submit(order['id'], cmd(order,'products_disposition_decided',
        predecessor_id=order['custody_activity']['review_id'], decision=v), ACTOR) for v in ('return','keep')])
    assert sorted(r.result.state for r in result) == ['applied','rejected']
    assert await db.order_custody_events.count_documents({}) == 3


@pytest.mark.parametrize('corruption', ['absent_ledger','altered_ledger','false_terminal','wrong_items','wrong_incident','null_marker'])
@mongo_case
async def test_corruption_blocks_reads_status_and_legacy(db, monkeypatch, corruption):
    order = await reviewed(db, monkeypatch, debt=True)
    if corruption == 'absent_ledger': await db.order_custody_events.delete_one({'_id':order['custody_activity']['wait_event_id']})
    elif corruption == 'altered_ledger': await db.order_custody_events.update_one({'_id':order['custody_activity']['review_id']},{'$set':{'actor_role':'driver'}})
    elif corruption == 'false_terminal': await db.orders.update_one({'id':order['id']},{'$set':{'status':'CANCELLED','cancelled_at':custody_module._timestamp()}})
    elif corruption == 'wrong_items': await db.orders.update_one({'id':order['id']},{'$set':{'items':[{'name':'Changed synthetic item','quantity':1,'price':1.0}]}})
    elif corruption == 'wrong_incident': await db.order_incidents.update_one({'_id':order['custody_activity']['incident_id']},{'$set':{'driver_id_at_report':'foreign'}})
    else: await db.orders.update_one({'id':order['id']},{'$set':{'custody_activity':None}})
    current = await db.orders.find_one({'id':order['id']})
    assert await read_custody_failures(db,[current]) == {0}
    detail = await OrderReadService(db).detail(ADMIN, order['id'])
    assert detail['order']['read_custody_invalid'] and detail['order']['read_actions_unavailable']
    with pytest.raises(Exception): ensure_legacy_order({'custody_activity':None})
    result = await OrderStatusService(db).status(order['id'], StatusOrderCommand(client_operation_id=str(uuid.uuid4()),
        expected_order_version=current['order_version'], status='DELIVERED'), DRIVER)
    assert result.result.state == 'rejected'


def test_strict_command_no_money_time_or_unconfirmed_facts():
    base={'client_operation_id':str(uuid.uuid4()),'expected_order_version':1,'event_type':'delivery_wait_started','incident_id':str(uuid.uuid4()),'reason':'absent'}
    for patch in ({'amount_bani':0},{'arrived_at':'x'},{'reason':None},{'expected_order_version':True},{'predecessor_id':None}):
        with pytest.raises(ValidationError): CustodyCommand(**{**base,**patch})
