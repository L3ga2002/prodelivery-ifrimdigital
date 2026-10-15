"""BOOST02 finite mixed-service races on an owned real Mongo replica set.

No database mocks, dotenv, server lifecycle, real credentials, or app database.
The runner injects a verified BOOST02 runtime module. Every database is retained.
QA-only subclasses add a read + finite barrier before the first transaction write.
"""
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import uuid

from bson import json_util
from motor.motor_asyncio import AsyncIOMotorClient
import pytest

from models.order_mutation import AssignOrderCommand, EditOrderCommand, StatusOrderCommand
from utils.order_assignment import OrderAssignmentService, AssignmentError
from utils.order_editing import OrderEditingService, EditingError
from utils.order_status import OrderStatusService, StatusError

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / '.ifrim/QA_RUNS/2026-10-10-stage2-boost-02/backend-mixed'
ADMIN_A = {'id': 'boost02-admin-a', 'role': 'admin'}
ADMIN_B = {'id': 'boost02-admin-b', 'role': 'admin'}
DRIVER = 'boost02-driver'
DRIVER_NEW = 'boost02-driver-new'
DRIVER_ACTOR = {'id': DRIVER + '-user', 'role': 'driver', 'driver_id': DRIVER}
ORDER_A = 'boost02-order-a'
ORDER_B = 'boost02-order-b'
VERSION = 7
COLLECTIONS = ('users', 'restaurants', 'drivers', 'orders', 'order_operation_settings',
               'order_operations', 'audit_logs', 'counters')
SOURCE_FILES = ('backend/utils/order_editing.py', 'backend/utils/order_assignment.py',
                'backend/utils/order_status.py', 'backend/utils/order_operation_runtime.py')


def normalize(value):
    return json.loads(json_util.dumps(value, json_options=json_util.CANONICAL_JSON_OPTIONS))


async def snapshot(database):
    return {name: await database[name].find({}).sort('_id', 1).to_list(None)
            for name in COLLECTIONS}


@pytest.fixture
def boost_mongo():
    def run(scenario):
        async def isolated():
            import boost02_runtime as runtime
            state = json.loads(runtime.STATE.read_text(encoding='utf-8'))
            fixture_root = ROOT / '.ifrim/QA_RUNS/2026-10-10-stage2-boost-02'
            assert Path(state['dbpath']).resolve().is_relative_to(fixture_root.resolve())
            assert runtime.URI.startswith('mongodb://127.0.0.1:')
            with runtime.direct() as verifier:
                runtime.verify_owned(verifier, state)
                hello = verifier.admin.command('hello')
                assert hello['isWritablePrimary'] and hello['setName'] == runtime.SET
            client = AsyncIOMotorClient(runtime.URI, serverSelectionTimeoutMS=2000,
                                        connectTimeoutMS=2000, socketTimeoutMS=4000)
            database = client['pd_boost02_mixed_' + uuid.uuid4().hex]
            try:
                for name in COLLECTIONS:
                    await database.create_collection(name)
                return await asyncio.wait_for(scenario(database, state), timeout=28)
            finally:
                client.close()
        return asyncio.run(isolated())
    return run


def base_order(identifier, state='NEW'):
    assigned = state in {'ASSIGNED', 'PICKED_UP'}
    prep = 'READY' if state == 'PICKED_UP' else 'NEW'
    return {
        'id': identifier, 'order_number': 'QA.BOOST02', 'restaurant_id': 'boost02-restaurant',
        'restaurant_name': 'Synthetic BOOST02 Restaurant', 'status': state,
        'preparation_status': prep, 'driver_id': DRIVER if assigned else None,
        'driver_name': 'Synthetic BOOST02 Driver' if assigned else None,
        'assigned_at': '2020-01-01T00:03:00+00:00' if assigned else None,
        'accepted_at': '2020-01-01T00:04:00+00:00' if state == 'PICKED_UP' else None,
        'picked_up_at': '2020-01-01T00:05:00+00:00' if state == 'PICKED_UP' else None,
        'delivered_at': None, 'cancelled_at': None, 'cancelled_by': None,
        'cancellation_reason': None, 'order_version': VERSION, 'audit_trail': [],
        'created_at': '2020-01-01T00:00:00+00:00', 'updated_at': '2020-01-01T00:05:00+00:00',
        'customer_name': 'Synthetic BOOST02 Customer', 'customer_phone': '0700000022',
        'customer_address': 'Synthetic BOOST02 Address', 'notes': 'Synthetic BOOST02 Note',
        'customer_latitude': None, 'customer_longitude': None,
        'subtotal_amount': 20.0, 'delivery_fee': 5.0, 'total_amount': 25.0,
        'payment_type': 'CASH', 'source': 'qa', 'items': [],
        'preparation_time': 10 if prep == 'READY' else None,
        'preparation_estimated_seconds': 600 if prep == 'READY' else None,
        'preparation_started_at': '2020-01-01T00:01:00+00:00' if prep == 'READY' else None,
        'preparation_due_at': '2020-01-01T00:11:00+00:00' if prep == 'READY' else None,
        'preparation_ready_at': '2020-01-01T00:02:00+00:00' if prep == 'READY' else None,
        'preparation_actual_seconds': 60 if prep == 'READY' else None,
        'preparation_delay_seconds': 0 if prep == 'READY' else None,
    }


async def seed(database, scenario):
    await database.users.insert_many([
        {**ADMIN_A, 'account_disabled': False}, {**ADMIN_B, 'account_disabled': False},
        {**DRIVER_ACTOR, 'account_disabled': False},
        {'id': DRIVER_NEW + '-user', 'role': 'driver', 'driver_id': DRIVER_NEW,
         'account_disabled': False},
    ])
    assigned = scenario != 'edit_assign'
    await database.drivers.insert_many([
        {'id': identifier, 'user_id': identifier + '-user',
         'name': 'Synthetic BOOST02 Driver' if identifier == DRIVER else 'Synthetic BOOST02 New Driver',
         'is_active': True, 'account_disabled': False,
         'driver_status': 'delivery' if identifier == DRIVER and assigned else 'active',
         'current_order_id': ORDER_A if identifier == DRIVER and assigned else None,
         'break_started_at': None, 'break_until': None,
         'total_deliveries': 8, 'total_earnings': 42.0}
        for identifier in (DRIVER, DRIVER_NEW)
    ])
    await database.restaurants.insert_one({'id': 'boost02-restaurant', 'name': 'Synthetic BOOST02 Restaurant'})
    await database.order_operation_settings.insert_many([
        {'_id': marker, 'enabled': True}
        for marker in ('order-edit-v1', 'order-assign-v1', 'order-status-v1')
    ])
    await database.counters.insert_one({'_id': 'orders.global', 'seq': 100})
    state = {'edit_assign': 'NEW', 'reassign_accept': 'ASSIGNED', 'deliver_assign': 'PICKED_UP'}[scenario]
    await database.orders.insert_one(base_order(ORDER_A, state))
    if scenario == 'deliver_assign':
        await database.orders.insert_one(base_order(ORDER_B))


class FiniteSnapshotGate:
    def __init__(self):
        self.ready = {name: asyncio.Event() for name in ('left', 'right')}
        self.release = {name: asyncio.Event() for name in ('left', 'right')}
        self.snapshots = {}

    async def arrive(self, name, order):
        self.snapshots[name] = {'order_id': order['id'], 'version': int(order['order_version']),
                                'status': order['status'], 'driver_id': order.get('driver_id')}
        self.ready[name].set()
        await asyncio.wait_for(self.release[name].wait(), timeout=6)

    async def both(self):
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in self.ready.values())), timeout=4)

    def open_all(self):
        for event in self.release.values():
            event.set()


class SnapshotBarrierMixin:
    def __init__(self, database, gate, name, target):
        super().__init__(database)
        self.qa_gate, self.qa_name, self.qa_target = gate, name, target
        self.qa_entered = False

    async def _actor(self, actor, session=None):
        user = await super()._actor(actor, session)
        if session is not None and not self.qa_entered:
            self.qa_entered = True
            # This actual Mongo read pins the transaction snapshot before any fence/write.
            order = await super()._load_order(self.qa_target, session)
            assert order is not None
            await self.qa_gate.arrive(self.qa_name, order)
        return user


class GatedEdit(SnapshotBarrierMixin, OrderEditingService):
    pass


class GatedAssign(SnapshotBarrierMixin, OrderAssignmentService):
    pass


class GatedStatus(SnapshotBarrierMixin, OrderStatusService):
    pass


async def observe(awaitable):
    try:
        return await awaitable
    except (EditingError, AssignmentError, StatusError) as exc:
        return exc


def receipt_data(outcome):
    if isinstance(outcome, (EditingError, AssignmentError, StatusError)):
        return {'exception': type(outcome).__name__, 'http': outcome.status_code,
                'error_code': outcome.code}
    return {'http': outcome.status_code, **outcome.result.model_dump(mode='json')}


def applied(outcome):
    assert not isinstance(outcome, Exception), receipt_data(outcome)
    assert outcome.status_code == 200 and outcome.result.state == 'applied', receipt_data(outcome)
    assert outcome.result.order_version == VERSION + 1


def rejected(outcome, code):
    assert not isinstance(outcome, Exception), receipt_data(outcome)
    assert outcome.status_code == 409 and outcome.result.state == 'rejected', receipt_data(outcome)
    assert outcome.result.error_code == code


async def race(gate, left, right, winner):
    tasks = {'left': asyncio.create_task(observe(left)), 'right': asyncio.create_task(observe(right))}
    try:
        await gate.both()
        assert gate.snapshots['left']['version'] == gate.snapshots['right']['version'] == VERSION
        gate.release[winner].set()
        first = await asyncio.wait_for(tasks[winner], timeout=5)
        loser = 'right' if winner == 'left' else 'left'
        gate.release[loser].set()
        second = await asyncio.wait_for(tasks[loser], timeout=5)
        return {winner: first, loser: second}
    finally:
        gate.open_all()
        await asyncio.gather(*tasks.values(), return_exceptions=True)


async def verify_audits(database, expected, operation_count=2):
    audits = await database.audit_logs.find({}).to_list(None)
    assert len(audits) == len(expected)
    operations = await database.order_operations.find({}).to_list(None)
    assert len(operations) == operation_count
    for order_id, action in expected:
        audit = next(item for item in audits if item['entity_id'] == order_id and item['action'] == action)
        order = await database.orders.find_one({'id': order_id})
        assert len(order['audit_trail']) == 1
        assert {k: v for k, v in audit.items() if k not in {'_id', 'entity_type', 'entity_id'}} == order['audit_trail'][0]
        assert audit['from_order_version'] == VERSION and audit['to_order_version'] == VERSION + 1
        operation = next(item for item in operations if item['_id'] == audit['operation_ref'])
        assert operation['state'] == 'applied'
        assert operation['order_version'] == VERSION + 1 and operation['order_id'] == order_id
        assert operation['request_id'] == audit['request_id']
        uuid.UUID(operation['request_id'])
        assert len(operation['payload_digest']) == len(operation['admission_digest']) == 64
        assert 'Synthetic BOOST02 Customer' not in json.dumps(audit)
        assert 'Synthetic BOOST02 Address' not in json.dumps(audit)
    assert (await database.counters.find_one({'_id': 'orders.global'}))['seq'] == 100


async def check_replays(database, calls, observed):
    before = normalize(await snapshot(database))
    replayed = {}
    for name, lookup, resume, submit in calls:
        replayed[name] = []
        for call in (lookup, resume, submit):
            result = await observe(call())
            data = receipt_data(result)
            replayed[name].append(data)
            original = receipt_data(observed[name])
            if 'exception' in original:
                assert data['http'] == original['http'] and data['error_code'] == original['error_code']
            else:
                assert data['http'] == original['http']
                assert data['state'] == ('replayed' if original['state'] == 'applied' else original['state'])
                for field in ('client_operation_id', 'order_id', 'order_version', 'error_code'):
                    assert data[field] == original[field]
    assert normalize(await snapshot(database)) == before, 'Replay/lookup/resume altered persistent business or ledger'
    return replayed


@pytest.mark.parametrize('scenario', ('edit_assign', 'reassign_accept', 'deliver_assign'))
@pytest.mark.parametrize('winner', ('left', 'right'))
def test_mixed_service_serial_schedules(boost_mongo, scenario, winner):
    async def case(database, runtime_state):
        await seed(database, scenario)
        gate = FiniteSnapshotGate()
        edit_cmd = EditOrderCommand(client_operation_id='boost02_mixed_edit_intent_0001',
                    expected_order_version=VERSION, changes={'notes': 'Synthetic BOOST02 corrected note'})
        assign_target = ORDER_B if scenario == 'deliver_assign' else ORDER_A
        assign_cmd = AssignOrderCommand(client_operation_id='boost02_mixed_assign_intent_0001',
                    expected_order_version=VERSION, driver_id=DRIVER_NEW if scenario == 'reassign_accept' else DRIVER)
        status_cmd = StatusOrderCommand(client_operation_id='boost02_mixed_status_intent_0001',
                    expected_order_version=VERSION, status='DELIVERED' if scenario == 'deliver_assign' else 'ACCEPTED')
        assignment = GatedAssign(database, gate, 'right' if scenario != 'reassign_accept' else 'left', assign_target)
        if scenario == 'edit_assign':
            other = GatedEdit(database, gate, 'left', ORDER_A)
            left = other.edit(ORDER_A, edit_cmd, ADMIN_A)
            right = assignment.assign(ORDER_A, assign_cmd, ADMIN_B)
            services = {'left': (other, edit_cmd, ADMIN_A, ORDER_A, 'edit'),
                        'right': (assignment, assign_cmd, ADMIN_B, ORDER_A, 'assign')}
        else:
            other = GatedStatus(database, gate, 'right' if scenario == 'reassign_accept' else 'left', ORDER_A)
            status_call = other.status(ORDER_A, status_cmd, DRIVER_ACTOR)
            assign_call = assignment.assign(assign_target, assign_cmd, ADMIN_B)
            left, right = (assign_call, status_call) if scenario == 'reassign_accept' else (status_call, assign_call)
            services = {'left' if scenario == 'reassign_accept' else 'right': (assignment, assign_cmd, ADMIN_B, assign_target, 'assign'),
                        'right' if scenario == 'reassign_accept' else 'left': (other, status_cmd, DRIVER_ACTOR, ORDER_A, 'status')}
        observed = await race(gate, left, right, winner)
        a = await database.orders.find_one({'id': ORDER_A})
        driver = await database.drivers.find_one({'id': DRIVER})
        new_driver = await database.drivers.find_one({'id': DRIVER_NEW})
        if scenario == 'edit_assign':
            applied(observed[winner])
            rejected(observed['right' if winner == 'left' else 'left'], 'ORDER_VERSION_CONFLICT')
            assert a['order_version'] == VERSION + 1
            if winner == 'left':
                assert a['status'] == 'NEW' and a['notes'] == edit_cmd.changes.notes
                assert driver['current_order_id'] is None
                expected = [(ORDER_A, 'order.corrected')]
            else:
                assert a['status'] == 'ASSIGNED' and a['notes'] == 'Synthetic BOOST02 Note'
                assert driver['current_order_id'] == ORDER_A
                expected = [(ORDER_A, 'order.assigned')]
        elif scenario == 'reassign_accept':
            applied(observed[winner])
            assert a['order_version'] == VERSION + 1
            if winner == 'left':
                # Custody changed; foreign pending driver's receipt stays inaccessible.
                lost = observed['right']
                assert isinstance(lost, StatusError) and lost.status_code == 403 and lost.code == 'NOT_AUTHORIZED'
                assert a['driver_id'] == DRIVER_NEW and a['status'] == 'ASSIGNED' and a['accepted_at'] is None
                assert driver['current_order_id'] is None and new_driver['current_order_id'] == ORDER_A
                pending = await database.order_operations.find_one({'actor_id': DRIVER_ACTOR['id']})
                assert pending['state'] == 'pending' and pending['command'] == status_cmd.model_dump(mode='json')
                expected = [(ORDER_A, 'order.assigned')]
            else:
                rejected(observed['left'], 'ORDER_VERSION_CONFLICT')
                assert a['driver_id'] == DRIVER and a['status'] == 'ACCEPTED' and a['accepted_at']
                assert driver['current_order_id'] == ORDER_A and new_driver['current_order_id'] is None
                expected = [(ORDER_A, 'order.status_changed')]
        else:
            applied(observed['left'])
            assert a['status'] == 'DELIVERED' and a['order_version'] == VERSION + 1
            b = await database.orders.find_one({'id': ORDER_B})
            assert driver['total_deliveries'] == 9 and driver['total_earnings'] == 44.5
            # Both transactions pinned the initially busy driver's snapshot. Refusal is
            # serially valid regardless of response order, and must remain durable.
            rejected(observed['right'], 'DRIVER_BUSY')
            assert b['status'] == 'NEW' and b['order_version'] == VERSION and not b['audit_trail']
            assert driver['current_order_id'] is None and driver['driver_status'] == 'active'
            expected = [(ORDER_A, 'order.status_changed')]
        assert driver['total_deliveries'] == (9 if scenario == 'deliver_assign' else 8)
        assert driver['total_earnings'] == (44.5 if scenario == 'deliver_assign' else 42.0)
        assert new_driver['total_deliveries'] == 8 and new_driver['total_earnings'] == 42.0
        await verify_audits(database, expected)
        calls = []
        for name, (service, cmd, actor, target, method) in services.items():
            calls.append((name,
                lambda s=service, t=target, c=cmd, a=actor: s.lookup(t, c.client_operation_id, a),
                lambda s=service, t=target, c=cmd, a=actor: s.resume(t, c.client_operation_id, a),
                lambda s=service, t=target, c=cmd, a=actor, m=method: getattr(s, m)(t, c, a)))
        replays = await check_replays(database, calls, observed)
        fresh_after_delivery = None
        if scenario == 'deliver_assign' and winner == 'left':
            # Explicit caller action after a fresh read, never automatic retry/new UUID.
            fresh_order = await database.orders.find_one({'id': ORDER_B})
            fresh_driver = await database.drivers.find_one({'id': DRIVER})
            assert fresh_driver['current_order_id'] is None and fresh_order['order_version'] == VERSION
            fresh_cmd = AssignOrderCommand(client_operation_id='boost02_fresh_assign_after_delivery_0002',
                        expected_order_version=int(fresh_order['order_version']), driver_id=DRIVER)
            fresh_service = OrderAssignmentService(database)
            fresh = await fresh_service.assign(ORDER_B, fresh_cmd, ADMIN_B)
            applied(fresh)
            reserved = await database.drivers.find_one({'id': DRIVER})
            assert reserved['current_order_id'] == ORDER_B and reserved['driver_status'] == 'delivery'
            assert reserved['total_deliveries'] == 9 and reserved['total_earnings'] == 44.5
            await verify_audits(database, [(ORDER_A, 'order.status_changed'), (ORDER_B, 'order.assigned')], operation_count=3)
            replay_after_b = await check_replays(database, calls, observed)
            before_fresh_replay = normalize(await snapshot(database))
            for action in (lambda: fresh_service.lookup(ORDER_B, fresh_cmd.client_operation_id, ADMIN_B),
                           lambda: fresh_service.resume(ORDER_B, fresh_cmd.client_operation_id, ADMIN_B),
                           lambda: fresh_service.assign(ORDER_B, fresh_cmd, ADMIN_B)):
                reply = await action()
                assert reply.status_code == 200 and reply.result.state == 'replayed'
                assert reply.result.client_operation_id == fresh_cmd.client_operation_id
            assert normalize(await snapshot(database)) == before_fresh_replay
            assert (await database.drivers.find_one({'id': DRIVER}))['current_order_id'] == ORDER_B
            fresh_after_delivery = {'receipt': receipt_data(fresh), 'replay_after_b': replay_after_b,
                                    'explicit_fresh_attempt': True, 'driver_claim_preserved': ORDER_B}
        durable = await snapshot(database)
        output = {'scenario': scenario, 'released_first': winner, 'database': database.name,
            'runtime_pid': runtime_state['pid'], 'snapshots': gate.snapshots,
            'responses': {name: receipt_data(value) for name, value in observed.items()},
            'replays': replays, 'fresh_after_delivery': fresh_after_delivery, 'audit_count': len(durable['audit_logs']),
            'operation_states': [{'actor_id': item['actor_id'], 'operation_type': item['operation_type'],
                'state': item['state'], 'client_operation_id': item['client_operation_id'],
                'payload_digest': item['payload_digest'], 'request_id': item['request_id']}
                for item in durable['order_operations']],
            'source_sha256': {path: sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_FILES},
            'result': 'PASS', 'data_retained': True,
            'legacy_delivery_credit': 'Existing amount*0.1 behavior checked once; no approved financial policy introduced'}
        destination = RUN / (scenario + '-' + winner + '-' + uuid.uuid4().hex + '.json')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(output, indent=2), encoding='utf-8')
    boost_mongo(case)
