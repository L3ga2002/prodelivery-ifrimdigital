import { createOrderRemakeRecovery } from './orderRemakeRecovery';
import { buildRemakeDraft } from './orderRemakeFinance';

const actor = { id: 'owner', role: 'restaurant', restaurant_id: 'r1' }, ID = 'operation_remake_0001';
const storage = () => { const map = new Map(); return { getItem: jest.fn((key) => map.get(key) ?? null), setItem: jest.fn((key, value) => map.set(key, value)), removeItem: jest.fn((key) => map.delete(key)) }; };
const defer = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const input = () => {
  const parent_context = { contract_version: 1, kind: 'remake_parent', actor_id: 'owner', actor_role: 'restaurant', restaurant_id: 'r1',
    parent: { order_id: 'parent', order_version: 4, status: 'DELIVERED', source: 'S', customer_name: 'Private Customer', customer_phone: '0700011223',
      customer_address: 'Private Street 123', customer_latitude: 1, customer_longitude: 1, has_problem_followup: false, problem_followup_order_id: null,
      delivery_zone_id: 'z1', delivery_zone_name: 'Zone', delivery_sector: null, delivery_zone_level: 1 }, eligibility: { can_preview: true, blocking_code: null } };
  const draft = buildRemakeDraft(parent_context, { problem_type: 'missing_product', item_name: 'Private Product', quantity: '1', unit_price: '13,05', description: 'Private Description', payment_type: 'CASH' }, 'v1');
  const preview = { contract_version: 1, currency: 'RON', tariff_version: 'v1', products_bani: 1305, collection_mode: 'cash', client_collection_bani: 1305,
    restaurant_transport_bani: 1600, advance_required_bani: 1305, advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null,
    basis: 'zone', zone_id: 'z1', zone_name: 'Zone', zone_sector: null, zone_level: 1, kind: 'remake', informational: true, fingerprint_scope: 'server_key_v1',
    quote_fingerprint: 'a'.repeat(64), actor_id: 'owner', restaurant_id: 'r1', parent_order_id: 'parent', parent_order_version: 4 };
  return { parent_context, draft, preview, quote_confirmation: { contract_version: 1, quote_fingerprint: preview.quote_fingerprint } };
};
const receipt = (state = 'pending', id = ID) => ({ client_operation_id: id, state, order_id: ['applied', 'replayed'].includes(state) ? 'child' : null,
  order_version: ['applied', 'replayed'].includes(state) ? 0 : null, parent_order_id: ['applied', 'replayed'].includes(state) ? 'parent' : null,
  parent_order_version: ['applied', 'replayed'].includes(state) ? 5 : null, error_code: state === 'rejected' ? 'FINANCIAL_INTENT_CLOSED' : null, retry_after_seconds: state === 'pending' ? 2 : null });
const response = (state = 'pending', id = ID) => ({ headers: { 'retry-after': '2' }, status: { pending: 202, applied: 201, replayed: 200, rejected: 409 }[state], data: receipt(state, id) });
const readback = (id = ID) => { const value = input(); const { kind, informational, fingerprint_scope, quote_fingerprint, actor_id, restaurant_id, parent_order_id, parent_order_version, ...financial } = value.preview;
  return { status: 200, data: { contract_version: 1, kind: 'remake_readback', actor_id: 'owner', actor_role: 'restaurant', restaurant_id: 'r1', client_operation_id: id,
    quote_confirmation: value.quote_confirmation, receipt: receipt('replayed', id), parent: { order_id: 'parent', order_version: 8, status: 'DELIVERED', has_problem_followup: true, problem_followup_order_id: 'child' },
    child: { order_id: 'child', order_version: 2, status: 'DELIVERED', linked_problem_order_id: 'parent', creation_kind: 'remake', source: 'S', payment_type: 'CASH' }, financial } }; };
const setup = (overrides = {}) => {
  const options = { actor, apiBase: 'https://synthetic.invalid/base', api: { get: jest.fn(async () => response()), post: jest.fn(async () => response()) },
    durableStorage: storage(), draftStorage: storage(), locks: { request: async (_key, _options, callback) => callback({}) },
    crypto: { randomUUID: jest.fn(() => ID) }, refreshList: jest.fn(async ({ isCurrent }) => isCurrent()), ...overrides };
  return { ...options, controller: createOrderRemakeRecovery(options), options };
};

test('persist and reread before a single POST with no private durable fields', async () => {
  const s = setup(); s.api.post.mockImplementation(async (_path, body) => {
    expect(s.durableStorage.getItem(s.controller.key)).not.toBeNull(); expect(s.draftStorage.getItem(`${s.controller.key}:draft:${ID}`)).not.toBeNull();
    expect(body.items[0].unit_price_bani).toBe(1305); return response();
  });
  await s.controller.submit(input()); expect(s.api.post).toHaveBeenCalledTimes(1);
  const raw = s.durableStorage.getItem(s.controller.key);
  for (const privateValue of ['Private', '0700011223', 'products_bani', 'unit_price', 'description', 'token']) expect(raw).not.toContain(privateValue);
  expect(s.controller.savedDraft().command.client_operation_id).toBe(ID);
});
test('lost response plus lookup404 keeps identity, never automatic POST or fabricated receipt', async () => {
  const s = setup(); s.api.post.mockRejectedValue(new Error('lost')); s.api.get.mockRejectedValue({ response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } });
  await expect(s.controller.submit(input())).rejects.toMatchObject({ code: 'RECOVERY_UNAVAILABLE' });
  await expect(s.controller.recover()).rejects.toMatchObject({ code: 'OPERATION_NOT_FOUND' });
  expect(s.controller.snapshot().receipt).toBeNull(); expect(s.api.post).toHaveBeenCalledTimes(1);
  await expect(s.controller.acknowledge()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' });
});
test('retry exact bytes and explicit resume/close preserve operation id', async () => {
  const s = setup(); await s.controller.submit(input()); const body = JSON.stringify(s.api.post.mock.calls[0][1]);
  await s.controller.retrySubmission(); expect(JSON.stringify(s.api.post.mock.calls[1][1])).toBe(body);
  await s.controller.resume(); expect(s.api.post.mock.calls[2][0]).toBe(`/api/orders/operations/finance/remake/parent/${ID}/resume`);
  expect(s.api.post.mock.calls[2][1]).toBeUndefined();
  await s.controller.closeIntent(); expect(s.api.post.mock.calls[3][1]).toEqual({ restaurant_id: 'r1', expected_order_version: 4, quote_confirmation: input().quote_confirmation });
  expect(s.controller.snapshot().receipt.state).toBe('pending');
});
test.each([false, true])('ACK success uses fresh receipt/readback/list; missing draft=%s', async (missing) => {
  const s = setup(); s.api.post.mockResolvedValue(response('applied')); await s.controller.submit(input());
  if (missing) s.draftStorage.removeItem(`${s.controller.key}:draft:${ID}`);
  s.api.get.mockImplementation(async (path) => path.endsWith('/readback') ? readback() : response('replayed'));
  s.refreshList.mockImplementation(async ({ isCurrent }) => { expect(isCurrent()).toBe(true); expect(s.controller.snapshot()).not.toBeNull(); return true; });
  expect(await s.controller.acknowledge()).toBe(true); expect(s.api.get.mock.calls.map(([path]) => path)).toEqual([
    `/api/orders/operations/finance/remake/parent/${ID}`, `/api/orders/operations/finance/remake/parent/${ID}/readback`]);
  expect(s.controller.snapshot()).toBeNull(); expect(s.refreshList).toHaveBeenCalledTimes(1);
});
test('ACK rejected requires only fresh terminal and published list, no success readback', async () => {
  const s = setup(); s.api.post.mockRejectedValue({ response: response('rejected') }); await s.controller.submit(input()); s.api.get.mockResolvedValue(response('rejected'));
  expect(await s.controller.acknowledge()).toBe(true); expect(s.api.get).toHaveBeenCalledTimes(1); expect(s.refreshList).toHaveBeenCalledTimes(1);
});
test.each([false, undefined, null])('unsuccessful list publication %p cannot clear metadata or draft', async (published) => {
  const s = setup(); s.api.post.mockResolvedValue(response('rejected')); await s.controller.submit(input()); s.api.get.mockResolvedValue(response('rejected')); s.refreshList.mockResolvedValue(published);
  await expect(s.controller.acknowledge()).rejects.toMatchObject({ code: 'REFRESH_UNCONFIRMED' }); expect(s.controller.snapshot()).not.toBeNull(); expect(s.controller.savedDraft()).not.toBeNull();
});
test('external ACK(A)+B fences delayed A request and its retirement cleanup', async () => {
  const s = setup(); await s.controller.submit(input()); const later = defer(); s.api.get.mockReturnValue(later.promise);
  const old = s.controller.recover(); await Promise.resolve();
  const b = { ...s.controller.snapshot(), client_operation_id: 'operation_remake_0002', receipt: null };
  s.durableStorage.setItem(s.controller.key, JSON.stringify(b)); s.draftStorage.setItem(`${s.controller.key}:draft:${b.client_operation_id}`, 'private-B');
  later.resolve(response('rejected')); await expect(old).rejects.toMatchObject({ code: 'INTENT_CHANGED' });
  s.controller.deactivate(); expect(s.durableStorage.getItem(s.controller.key)).toBe(JSON.stringify(b)); expect(s.draftStorage.getItem(`${s.controller.key}:draft:${b.client_operation_id}`)).toBe('private-B');
});
test('late ACK list callback cannot clear a newer record', async () => {
  const later = defer(), s = setup({ refreshList: jest.fn(() => later.promise) });
  s.api.post.mockResolvedValue(response('rejected')); await s.controller.submit(input()); s.api.get.mockResolvedValue(response('rejected'));
  const ack = s.controller.acknowledge(); for (let n = 0; n < 20 && !s.refreshList.mock.calls.length; n++) await Promise.resolve();
  expect(s.refreshList).toHaveBeenCalledTimes(1);
  const b = { ...s.controller.snapshot(), client_operation_id: 'operation_remake_0002', receipt: null }; s.durableStorage.setItem(s.controller.key, JSON.stringify(b));
  later.resolve(true); await expect(ack).rejects.toMatchObject({ code: 'INTENT_CHANGED' }); expect(s.controller.snapshot().client_operation_id).toBe(b.client_operation_id);
});
test.each(['api', 'role', 'tenant'])('reload in changed %s cannot recover/resend/close/ACK another context', async (change) => {
  const s = setup(); await s.controller.submit(input());
  const options = { ...s.options, api: { get: jest.fn(), post: jest.fn() } };
  if (change === 'api') options.apiBase = 'https://other.invalid';
  if (change === 'tenant') options.actor = { ...actor, restaurant_id: 'r2' };
  if (change === 'role') { options.actor = { ...actor, role: 'admin' }; expect(() => createOrderRemakeRecovery(options)).toThrow(); return; }
  const controller = createOrderRemakeRecovery(options);
  for (const method of ['recover', 'retrySubmission', 'resume', 'closeIntent']) await expect(controller[method]()).rejects.toMatchObject({ code: 'FINANCIAL_CONTEXT_CHANGED' });
  expect(options.api.get).not.toHaveBeenCalled(); expect(options.api.post).not.toHaveBeenCalled();
});
test('missing draft permits explicit close and prohibits retry', async () => {
  const s = setup(); await s.controller.submit(input()); s.draftStorage.removeItem(`${s.controller.key}:draft:${ID}`);
  await expect(s.controller.retrySubmission()).rejects.toMatchObject({ code: 'DRAFT_UNAVAILABLE' }); s.api.post.mockResolvedValue(response('rejected'));
  expect((await s.controller.closeIntent()).state).toBe('rejected');
});
test.each(['malformed', 'oversized'])('invalid durable %s never becomes absent', async (kind) => {
  const s = setup(); s.durableStorage.setItem(s.controller.key, kind === 'malformed' ? '{' : 'x'.repeat(8193));
  expect(() => s.controller.snapshot()).toThrow(); await expect(s.controller.submit(input())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' }); expect(s.api.post).not.toHaveBeenCalled();
});
test('new original financial intent written without storage event blocks submission', async () => {
  const s = setup(); const key = 'prodelivery:order-financial-event:v1:owner:restaurant:r1'; s.durableStorage.setItem(key, '{');
  await expect(s.controller.submit(input())).rejects.toMatchObject({ code: 'ORIGINAL_FINANCE_STORAGE_INVALID' }); expect(s.api.post).not.toHaveBeenCalled(); expect(s.controller.snapshot()).toBeNull();
});
test('lock refusal and storage write failure happen before POST', async () => {
  const s = setup({ locks: { request: async (_key, _options, callback) => callback(null) } });
  await expect(s.controller.submit(input())).rejects.toMatchObject({ code: 'BUSY' }); expect(s.api.post).not.toHaveBeenCalled();
  const t = setup(); t.durableStorage.setItem.mockImplementation(() => { throw new Error('denied'); });
  await expect(t.controller.submit(input())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' }); expect(t.api.post).not.toHaveBeenCalled();
});
