import { createOrderStatusRecovery, validateStatusReceipt, canChangeOrderStatus, hasStatusRevision,
  statusApplied, statusTerminal, MAX_STATUS_RECOVERY_READS } from './orderStatusRecovery';

const ID = '123e4567-e89b-42d3-a456-426614174000';
const KEY = 'prodelivery:order-status:v1:actor';
const actor = { id: 'actor', role: 'driver', driver_id: 'driver' };
const order = { id: 'order', restaurant_id: 'restaurant', driver_id: 'driver', order_version: 4,
  status: 'ASSIGNED', preparation_status: 'READY', customer_name: 'Private Sentinel', total_amount: 100 };
const record = { actor_id: 'actor', actor_role: 'driver', actor_resource_id: 'driver', order_id: 'order',
  expected_order_version: 4, status: 'ACCEPTED', client_operation_id: ID, receipt: null };
const done = { status: 200, data: { client_operation_id: ID, state: 'applied', order_id: 'order', order_version: 5 } };
const pending = { status: 202, headers: { 'retry-after': '1' }, data: { client_operation_id: ID, state: 'pending', retry_after_seconds: 1 } };
const missing = { response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } };
const store = () => { const map = new Map(); return { getItem: jest.fn((k) => map.get(k) ?? null),
  setItem: jest.fn((k, v) => map.set(k, v)), removeItem: jest.fn((k) => map.delete(k)) }; };
let durable, draft, api, locks, crypto, wait, recovery;
const make = (overrides = {}) => createOrderStatusRecovery({ actor, api, durableStorage: durable, draftStorage: draft, locks, crypto, wait, ...overrides });
beforeEach(() => {
  durable = store(); draft = store(); wait = jest.fn(async () => {}); crypto = { randomUUID: jest.fn(() => ID) };
  locks = { request: jest.fn(async (_k, _o, callback) => callback({})) };
  api = { get: jest.fn(async (path) => path.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: true } } :
    path.endsWith('/api/auth/me') ? { status: 200, data: actor } : done),
    post: jest.fn(async () => done), put: jest.fn(async () => ({ status: 200 })) };
  recovery = make();
});
const submit = (changes = {}) => recovery.submit({ order, status: 'ACCEPTED', ...changes });

test('exact command, CAS receipt, timeout and non-PII metadata', async () => {
  expect(await submit()).toEqual(done.data);
  expect(api.post.mock.calls[0]).toEqual(['/api/orders/operations/status/order',
    { client_operation_id: ID, expected_order_version: 4, status: 'ACCEPTED' }, { timeout: 15000 }]);
  expect(recovery.snapshot()).toEqual({ ...record, receipt: done.data });
  expect(durable.getItem(KEY)).not.toContain('Private'); expect(draft.setItem).not.toHaveBeenCalled();
  await expect(submit()).rejects.toMatchObject({ code: 'INTENT_PENDING' });
  await recovery.acknowledge(); expect(recovery.snapshot()).toBeNull();
});
test.each(['ACCEPTED', 'PICKED_UP', 'DELIVERED', 'CANCELLED'])('status %s sends only allowed fields', async (status) => {
  const source = { ...order, status: { ACCEPTED: 'ASSIGNED', PICKED_UP: 'ACCEPTED', DELIVERED: 'PICKED_UP', CANCELLED: 'ACCEPTED' }[status] };
  await submit({ order: source, status, ...(status === 'CANCELLED' ? { cancellationReason: ' Exact private reason ' } : {}) });
  const body = api.post.mock.calls[0][1]; expect(body.status).toBe(status);
  expect(Object.hasOwn(body, 'cancellation_reason')).toBe(status === 'CANCELLED');
  expect(durable.getItem(KEY)).not.toContain('private'); expect(recovery.snapshot().status).toBe(status);
  if (status === 'CANCELLED') { expect(body.cancellation_reason).toBe('Exact private reason'); expect(draft.getItem(`${KEY}:draft:${ID}`)).toBeNull(); }
});
test.each([null, true, false, '4', 1.2, -1, Number.MAX_SAFE_INTEGER, [], {}])('present invalid revision %j never uses legacy', async (value) => {
  const source = { ...order, order_version: value }; expect(hasStatusRevision(source)).toBe(true);
  await expect(submit({ order: source })).rejects.toMatchObject({ code: 'ORDER_VERSION_INVALID' });
  await expect(recovery.submitLegacy({ order: source, status: 'ACCEPTED' })).rejects.toMatchObject({ code: 'ORDER_VERSION_INVALID' });
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
});
test.each(['NEW', 'PREPARING', null, 'INVALID'])('pickup requires actual READY, not %s', async (prep) => {
  await expect(submit({ order: { ...order, status: 'ACCEPTED', preparation_status: prep }, status: 'PICKED_UP' })).rejects.toMatchObject({ code: 'STATUS_TRANSITION_INVALID' });
});
test.each(['offline', 'break'])('availability %s does not restrict enabled driver custody', async (operational_status) => {
  recovery = make({ actor: { ...actor, operational_status } }); await submit(); expect(api.post).toHaveBeenCalledTimes(1);
});
test.each([{}, { id: 'actor', role: 'driver' }, { ...actor, id: ' ' }, { ...actor, is_disabled: true }, { ...actor, account_disabled: null }, { ...actor, role: 'dispatcher' }])('invalid actor %j is fail closed', (a) => {
  expect(() => make({ actor: a })).toThrow();
});
test.each(['driver', 'restaurant'])('%s cannot mutate another resource', async (role) => {
  const a = { id: 'actor', role, [`${role}_id`]: 'other' }; recovery = make({ actor: a });
  await expect(submit({ status: role === 'driver' ? 'ACCEPTED' : 'CANCELLED', ...(role === 'restaurant' ? { cancellationReason: 'reason' } : {}) })).rejects.toMatchObject({ code: 'STATUS_TRANSITION_INVALID' });
  expect(api.post).not.toHaveBeenCalled();
});
test('restaurant only own cancellation; admin all allowed transitions', async () => {
  const restaurantActor = { id: 'actor', role: 'restaurant', restaurant_id: 'restaurant' };
  expect(canChangeOrderStatus(order, 'ACCEPTED', restaurantActor)).toBe(false);
  recovery = make({ actor: restaurantActor }); await submit({ status: 'CANCELLED', cancellationReason: 'reason' });
  expect(JSON.parse(durable.getItem(KEY)).actor_resource_id).toBe('restaurant');
  expect(canChangeOrderStatus(order, 'ACCEPTED', { id: 'actor', role: 'admin' })).toBe(true);
});
test('versioned post-pickup cancel refused even when disabled', async () => {
  const source = { ...order, status: 'PICKED_UP' }; api.get.mockResolvedValue({ status: 200, data: { status_recovery_enabled: false } });
  await expect(submit({ order: source, status: 'CANCELLED', cancellationReason: 'reason' })).rejects.toMatchObject({ code: 'CUSTODY_RESOLUTION_REQUIRED' });
  await expect(recovery.submitLegacy({ order: source, status: 'CANCELLED', cancellationReason: 'reason' })).rejects.toMatchObject({ code: 'CUSTODY_RESOLUTION_REQUIRED' });
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
});
test.each(['', ' ', 'x'.repeat(501), null, {}])('invalid cancel reason %j never admits', async (reason) => {
  await expect(submit({ status: 'CANCELLED', cancellationReason: reason })).rejects.toMatchObject({ code: 'INVALID_COMMAND' });
  expect(crypto.randomUUID).not.toHaveBeenCalled();
});
test('reason prohibited for non-cancel command', async () => { await expect(submit({ cancellationReason: 'reason' })).rejects.toMatchObject({ code: 'INVALID_COMMAND' }); });
test('disabled versioned marker permits zero legacy requests even when explicitly requested', async () => {
  api.get.mockImplementation(async (p) => p.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: false } } : { status: 200, data: actor });
  await expect(submit()).rejects.toMatchObject({ code: 'STATUS_NOT_ENABLED' }); expect(api.put).not.toHaveBeenCalled();
  await expect(recovery.submitLegacy({ order, status: 'ACCEPTED' })).rejects.toMatchObject({ code: 'ORDER_VERSION_REQUIRED' }); expect(api.put).not.toHaveBeenCalled();
  expect(crypto.randomUUID).not.toHaveBeenCalled();
});
test('missing version explicitly uses legacy without capability query', async () => {
  const source = { ...order }; delete source.order_version;
  await recovery.submitLegacy({ order: source, status: 'ACCEPTED' });
  expect(api.get.mock.calls.map(([p]) => p)).toEqual(['/api/auth/me']); expect(api.post).not.toHaveBeenCalled();
});
test.each([{}, { status_recovery_enabled: 'false' }, null])('unknown capability %j cannot authorize versioned legacy', async (data) => {
  api.get.mockResolvedValue({ status: 200, data });
  await expect(recovery.submitLegacy({ order, status: 'ACCEPTED' })).rejects.toMatchObject({ code: 'ORDER_VERSION_REQUIRED' });
  expect(api.put).not.toHaveBeenCalled();
});
test('ACK lost reconciles same intent with no new POST', async () => {
  api.post.mockRejectedValueOnce(new Error('timeout')); expect(await submit()).toEqual(done.data);
  expect(api.post).toHaveBeenCalledTimes(1); expect(crypto.randomUUID).toHaveBeenCalledTimes(1); expect(api.put).not.toHaveBeenCalled();
});
test('marker disabled race after capability preserves identity and exposes code without fallback', async () => {
  api.post.mockRejectedValue({ response: { status: 503, data: { detail: { code: 'STATUS_NOT_ENABLED' } } } });
  await expect(submit()).rejects.toMatchObject({ code: 'STATUS_NOT_ENABLED' }); expect(recovery.snapshot().receipt).toBeNull();
  expect(api.put).not.toHaveBeenCalled(); expect(api.post).toHaveBeenCalledTimes(1);
});
test.each([['NOT_AUTHORIZED', 403], ['SESSION_CHANGED', 403], ['STATUS_NOT_ENABLED', 503]])('FE-03 RED: impossible durable rejection %s cannot clear uncertain identity', async (code, status) => {
  const response = { status, data: { client_operation_id: ID, state: 'rejected', error_code: code } };
  expect(() => validateStatusReceipt(response, record)).toThrow(expect.objectContaining({ code: 'INVALID_RESPONSE' }));
  api.post.mockRejectedValue({ response }); api.get.mockImplementation(async (path) => {
    if (path.endsWith('capabilities')) return { status: 200, data: { status_recovery_enabled: true } };
    return response;
  });
  await expect(submit()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  expect(recovery.snapshot()).toEqual(record);
  await expect(recovery.acknowledge()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' });
  expect(api.get.mock.calls.filter(([p]) => !p.endsWith('capabilities')).map(([p]) => p)).toEqual([`/api/orders/operations/status/order/${ID}`]);
  expect(api.post).toHaveBeenCalledTimes(1); expect(crypto.randomUUID).toHaveBeenCalledTimes(1); expect(api.put).not.toHaveBeenCalled();
  const forged = JSON.stringify({ ...record, receipt: response.data }); durable.setItem(KEY, forged);
  expect(() => recovery.snapshot()).toThrow(expect.objectContaining({ code: 'STORAGE_UNAVAILABLE' }));
  await expect(recovery.acknowledge()).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' }); expect(durable.getItem(KEY)).toBe(forged);
});
test('bounded pending reads/resume and no false terminal', async () => {
  api.post.mockResolvedValue(pending); api.get.mockImplementation(async (p) => p.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: true } } : pending);
  expect((await submit()).state).toBe('pending'); expect(statusTerminal(recovery.snapshot().receipt)).toBe(false);
  expect(api.get.mock.calls.filter(([p]) => !p.endsWith('capabilities'))).toHaveLength(MAX_STATUS_RECOVERY_READS);
  expect(api.post.mock.calls.filter(([p]) => p.endsWith('/resume'))).toHaveLength(1);
  expect(api.post.mock.calls[1][1]).toBeUndefined(); expect(wait).toHaveBeenCalledTimes(2);
  await expect(recovery.acknowledge()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' });
});
test('cancel draft exact retry pre-admission; no reason in durable metadata', async () => {
  api.post.mockRejectedValueOnce(new Error('timeout')).mockResolvedValueOnce(done);
  api.get.mockImplementation(async (p) => { if (p.endsWith('capabilities')) return { status: 200, data: { status_recovery_enabled: true } }; throw missing; });
  await submit({ status: 'CANCELLED', cancellationReason: 'Exact PII Sentinel' });
  expect(api.post.mock.calls[0][1]).toEqual(api.post.mock.calls[1][1]); expect(api.post.mock.calls[1][1].cancellation_reason).toBe('Exact PII Sentinel');
  expect(durable.getItem(KEY)).not.toContain('Sentinel'); expect(draft.getItem(`${KEY}:draft:${ID}`)).toBeNull();
});
test('orphan cancel reload/another tab GET404 stays uncertain without guessing reason', async () => {
  durable.setItem(KEY, JSON.stringify({ ...record, status: 'CANCELLED' })); api.get.mockRejectedValue(missing);
  await expect(recovery.recover()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' });
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled(); expect(recovery.snapshot()).not.toBeNull();
});
test('admitted cancel resume bodyless despite disabled capability and absent draft', async () => {
  durable.setItem(KEY, JSON.stringify({ ...record, status: 'CANCELLED', receipt: pending.data })); api.get.mockResolvedValue(pending);
  expect(await recovery.recover()).toEqual(done.data); expect(api.post.mock.calls[0][1]).toBeUndefined();
  expect(api.get.mock.calls[0][0]).toContain(`/${ID}`); expect(api.get.mock.calls.some(([p]) => p.endsWith('capabilities'))).toBe(false);
});
test('admitted lookup404 never resends command', async () => {
  durable.setItem(KEY, JSON.stringify({ ...record, receipt: pending.data })); api.get.mockRejectedValue(missing);
  await expect(recovery.recover()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' }); expect(api.post).not.toHaveBeenCalled();
});
test.each(['ORDER_NOT_FOUND', 'DRIVER_NOT_FOUND', 'ORDER_TARGET_CHANGED', 'ORDER_DATA_INVALID', 'ORDER_VERSION_REQUIRED',
  'ORDER_VERSION_INVALID', 'ORDER_VERSION_CONFLICT', 'ORDER_VERSION_EXHAUSTED', 'STATUS_TRANSITION_INVALID', 'ORDER_NOT_READY',
  'CUSTODY_RESOLUTION_REQUIRED', 'DRIVER_DATA_INVALID', 'DRIVER_DISABLED', 'ASSIGNMENT_INCONSISTENT', 'ASSIGNMENT_REPRESENTATION_UNSUPPORTED'])('typed durable business rejection %s remains terminal', async (code) => {
  const response = { status: ['ORDER_NOT_FOUND', 'DRIVER_NOT_FOUND'].includes(code) ? 404 : 409,
    data: { client_operation_id: ID, state: 'rejected', error_code: code } };
  api.post.mockRejectedValue({ response }); expect(await submit()).toEqual(response.data);
  expect(statusApplied(response.data)).toBe(false); expect(statusTerminal(response.data)).toBe(true); expect(api.put).not.toHaveBeenCalled();
  await recovery.acknowledge(); expect(durable.getItem(KEY)).toBeNull();
});
test.each([['AUTH_CONTEXT_CHANGED', 403, 'SESSION_CHANGED'], ['NOT_AUTHORIZED', 403, 'NOT_AUTHORIZED'],
  ['STATUS_NOT_ENABLED', 503, 'STATUS_NOT_ENABLED']])('real detail.%s remains nonterminal transport refusal', async (detailCode, status, errorCode) => {
  api.post.mockRejectedValue({ response: { status, data: { detail: { code: detailCode } } } });
  await expect(submit()).rejects.toMatchObject({ code: errorCode }); expect(recovery.snapshot()).toEqual(record);
  await expect(recovery.acknowledge()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' });
  expect(api.post).toHaveBeenCalledTimes(1); expect(api.put).not.toHaveBeenCalled(); expect(crypto.randomUUID).toHaveBeenCalledTimes(1);
});
test.each([
  { ...done, status: 202 }, { ...done, data: { ...done.data, order_id: 'other' } },
  { ...done, data: { ...done.data, order_version: 4 } }, { ...done, data: { ...done.data, extra: true } },
  { ...done, data: { ...done.data, client_operation_id: '123e4567-e89b-42d3-a456-426614174001' } },
  { ...pending, headers: {} }, { ...pending, data: { ...pending.data, order_id: 'order' } },
  { status: 409, data: { client_operation_id: ID, state: 'rejected', error_code: 'UNKNOWN' } },
])('malformed receipt %j cannot claim result', (r) => { expect(() => validateStatusReceipt(r, record)).toThrow(); });
test.each(['get', 'set'])('durable storage %s failure sends nothing', async (method) => {
  durable[`${method}Item`].mockImplementation(() => { throw new Error('denied'); });
  await expect(submit()).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' }); expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
});
test('cancel session storage failure sends nothing and cannot retry new intent', async () => {
  draft.setItem.mockImplementation(() => { throw new Error('denied'); });
  await expect(submit({ status: 'CANCELLED', cancellationReason: 'reason' })).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
  await expect(submit()).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' }); expect(api.post).not.toHaveBeenCalled();
});
test.each(['{corrupt', JSON.stringify({ ...record, actor_id: 'other' }), JSON.stringify({ ...record, actor_resource_id: 'other' }), JSON.stringify({ ...record, cancellation_reason: 'PII' })])('corrupt or wrong-scope metadata stays retained', async (raw) => {
  durable.setItem(KEY, raw); await expect(recovery.recover()).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
  expect(durable.getItem(KEY)).toBe(raw); expect(api.post).not.toHaveBeenCalled();
});
test('no lock/contended tab/offline fail closed', async () => {
  recovery = make({ locks: null }); await expect(submit()).rejects.toMatchObject({ code: 'LOCK_UNAVAILABLE' });
  locks.request.mockImplementation(async (_k, _o, cb) => cb(null)); recovery = make(); await expect(submit()).rejects.toMatchObject({ code: 'BUSY' });
  recovery = make({ locks: { request: async (_k, _o, cb) => cb({}) }, isOnline: () => false }); await expect(submit()).rejects.toMatchObject({ code: 'OFFLINE' });
  expect(api.post).not.toHaveBeenCalled();
});
test('double-click never creates two intents', async () => {
  let release; api.post.mockImplementation(() => new Promise((r) => { release = r; })); const flight = submit();
  while (!release) await Promise.resolve(); await expect(submit()).rejects.toMatchObject({ code: 'BUSY' });
  release(done); await flight; expect(crypto.randomUUID).toHaveBeenCalledTimes(1);
});
test('deactivated session cannot store a late receipt', async () => {
  let release; api.post.mockImplementation(() => new Promise((r) => { release = r; })); const flight = submit();
  const rejected = expect(flight).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  while (!release) await Promise.resolve(); recovery.deactivate(); release(done);
  await rejected; expect(JSON.parse(durable.getItem(KEY)).receipt).toBeNull();
});
test('rejected refresh requires fresh target/version/transition before clearing identity', async () => {
  durable.setItem(KEY, JSON.stringify({ ...record, receipt: { client_operation_id: ID, state: 'rejected', error_code: 'ORDER_VERSION_CONFLICT' } }));
  api.get.mockResolvedValue({ status: 200, data: { ...order, id: 'other', order_version: 7 } });
  await expect(recovery.refreshForNewAttempt()).rejects.toMatchObject({ code: 'STATUS_TRANSITION_INVALID' }); expect(recovery.snapshot()).not.toBeNull();
  api.get.mockResolvedValue({ status: 200, data: { ...order, order_version: 7 } }); expect((await recovery.refreshForNewAttempt()).order_version).toBe(7); expect(recovery.snapshot()).toBeNull();
});
test('legacy auth preflight rejects role/resource substitution', async () => {
  const source = { ...order }; delete source.order_version; api.get.mockResolvedValue({ status: 200, data: { ...actor, driver_id: 'other' } });
  await expect(recovery.submitLegacy({ order: source, status: 'ACCEPTED' })).rejects.toMatchObject({ code: 'SESSION_CHANGED' }); expect(api.put).not.toHaveBeenCalled();
});
