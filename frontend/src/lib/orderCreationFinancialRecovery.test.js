import { createOrderRecovery } from './orderCreationRecovery';

const A = 'operation_finance_0001', B = 'operation_finance_0002', KEY = 'prodelivery:order-create:v1:actor';
const input = () => ({ order: { restaurant_id: 'r', customer_name: 'Private Customer', customer_phone: '0700000000', customer_address: 'Private Street',
  customer_latitude: 1, customer_longitude: 1, items: [], total_amount: 12.34, subtotal_amount: 12.34, payment_type: 'CASH', source: 'S', notes: 'private note' },
  financial: { contract_version: 1, tariff_version: 'v1', products_bani: 1234, basis: 'zone', zone_id: 'z' },
  quote_confirmation: { contract_version: 1, quote_fingerprint: 'a'.repeat(64) },
  preview: { contract_version: 1, kind: 'create', informational: true, fingerprint_scope: 'server_key_v1', quote_fingerprint: 'a'.repeat(64),
    actor_id: 'actor', restaurant_id: 'r', parent_order_id: null, parent_order_version: null, currency: 'RON', tariff_version: 'v1', products_bani: 1234,
    collection_mode: 'cash', client_collection_bani: 1234, restaurant_transport_bani: 1600, courier_remuneration_bani: 975, advance_required_bani: 1234,
    advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null, basis: 'zone', zone_id: 'z', zone_name: 'Zone', zone_sector: null, zone_level: null } });
const receipt = (state = 'pending', id = A) => ({ client_operation_id: id, state, order_id: ['applied', 'replayed'].includes(state) ? 'order' : null,
  order_version: ['applied', 'replayed'].includes(state) ? 0 : null, error_code: state === 'rejected' ? 'FINANCIAL_INTENT_CLOSED' : null,
  retry_after_seconds: state === 'pending' ? 2 : null });
const response = (state, id) => ({ status: { pending: 202, applied: 201, replayed: 200, rejected: 409 }[state], data: receipt(state, id) });
const error404 = () => Object.assign(new Error('synthetic missing'), { response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } });
let api, controller;
const make = (changes = {}) => createOrderRecovery({ actorId: 'actor', actorRole: 'admin', actorRestaurantId: null, apiBase: 'https://synthetic.invalid', api,
  durableStorage: localStorage, draftStorage: sessionStorage, locks: { request: async (_k, _o, cb) => cb({}) },
  crypto: { randomUUID: () => A }, ...changes });
beforeEach(() => { localStorage.clear(); sessionStorage.clear(); api = { post: jest.fn(async () => response('pending')), get: jest.fn(async () => response('pending')) }; controller = make(); });
test('V2 persists context without PII and exact private command before POST', async () => {
  api.post.mockImplementation(async (_url, command) => { expect(JSON.parse(localStorage.getItem(KEY)).client_operation_id).toBe(A); expect(sessionStorage.getItem(`${KEY}:draft:${A}`)).not.toBeNull(); return response('pending'); });
  await controller.submit(input()); const record = controller.snapshot();
  expect(record).toMatchObject({ version: 2, protocol: 'financial_create_v1', api_base: 'https://synthetic.invalid', actor_role: 'admin', actor_restaurant_id: null, restaurant_id: 'r' });
  for (const secret of ['Private', '0700000000', 'private note', 'products_bani']) expect(localStorage.getItem(KEY)).not.toContain(secret);
  expect(api.post.mock.calls[0][0]).toBe('/api/orders/operations/finance/create');
  expect(api.post.mock.calls[0][1]).toEqual({ client_operation_id: A, order: input().order, financial: input().financial, quote_confirmation: input().quote_confirmation });
});
test('automatic 404 recovery never POSTs or loses identity', async () => {
  await controller.submit(input()); api.post.mockClear(); api.get.mockRejectedValue(error404());
  await expect(controller.recover()).rejects.toBeDefined(); expect(api.post).not.toHaveBeenCalled(); expect(controller.snapshot().client_operation_id).toBe(A);
});
test('422 has no fabricated terminal; explicit close remains possible', async () => {
  api.post.mockRejectedValueOnce(Object.assign(new Error('bad'), { response: { status: 422, data: { detail: { code: 'INVALID_REQUEST' } } } }));
  await expect(controller.submit(input())).rejects.toBeDefined(); expect(controller.snapshot().receipt).toBeNull();
  api.post.mockResolvedValueOnce(response('rejected')); await controller.closeIntent();
  expect(controller.snapshot().receipt.error_code).toBe('FINANCIAL_INTENT_CLOSED');
});
test('local terminal is hint and draft survives fresh server 404', async () => {
  api.post.mockResolvedValueOnce(response('rejected')); await controller.submit(input()); const exact = sessionStorage.getItem(`${KEY}:draft:${A}`);
  controller.snapshot(); api.get.mockRejectedValue(error404());
  await expect(controller.acknowledge()).rejects.toBeDefined(); expect(sessionStorage.getItem(`${KEY}:draft:${A}`)).toBe(exact); expect(localStorage.getItem(KEY)).not.toBeNull();
});
test('lost private draft allows close and rejected ACK, but not resend', async () => {
  await controller.submit(input()); sessionStorage.clear(); controller = make();
  await expect(controller.retrySubmission()).rejects.toMatchObject({ code: 'DRAFT_UNAVAILABLE' });
  api.post.mockResolvedValue(response('rejected')); await controller.closeIntent(); api.get.mockResolvedValue(response('rejected'));
  const proof = controller.captureIntent(); await controller.acknowledge(); expect(controller.isCurrentIntent(proof, true)).toBe(true); expect(localStorage.getItem(KEY)).toBeNull();
});
test.each([{ apiBase: 'https://foreign.invalid' }, { actorRole: 'restaurant' }, { actorRestaurantId: 'foreign' }])('foreign runtime context cannot lookup or close %j', async (change) => {
  await controller.submit(input()); controller = make(change); api.get.mockClear(); api.post.mockClear();
  await expect(controller.recover()).rejects.toMatchObject({ code: 'FINANCIAL_CONTEXT_CHANGED' }); await expect(controller.closeIntent()).rejects.toMatchObject({ code: 'FINANCIAL_CONTEXT_CHANGED' });
  expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
});
test('resume is explicit empty body and retry sends exact saved command', async () => {
  await controller.submit(input()); const original = api.post.mock.calls[0][1]; api.post.mockClear();
  await controller.recover(); expect(api.post).not.toHaveBeenCalled();
  await controller.resume(); expect(api.post.mock.calls[0][0]).toBe(`/api/orders/operations/finance/create/${A}/resume`); expect(api.post.mock.calls[0][1]).toBeUndefined();
  await controller.retrySubmission(); expect(api.post.mock.calls[1][1]).toEqual(original);
});
test('old A response and retirement cannot overwrite or clean B', async () => {
  let resolve; api.post.mockImplementation(() => new Promise((done) => { resolve = done; }));
  const posting = controller.submit(input()); await Promise.resolve(); await Promise.resolve();
  const original = controller.snapshot(); const saved = JSON.parse(sessionStorage.getItem(`${KEY}:draft:${A}`));
  const next = { ...original, client_operation_id: B }; localStorage.setItem(KEY, JSON.stringify(next));
  sessionStorage.setItem(`${KEY}:draft:${B}`, JSON.stringify({ ...saved, client_operation_id: B, command: { ...saved.command, client_operation_id: B } }));
  const exact = sessionStorage.getItem(`${KEY}:draft:${B}`); resolve(response('pending'));
  await expect(posting).rejects.toMatchObject({ code: 'INTENT_CHANGED' }); controller.deactivate();
  expect(localStorage.getItem(KEY)).toBe(JSON.stringify(next)); expect(sessionStorage.getItem(`${KEY}:draft:${B}`)).toBe(exact);
});
test('pending response cannot downgrade a peer terminal for same ID', async () => {
  await controller.submit(input()); let resolve; api.get.mockImplementation(() => new Promise((done) => { resolve = done; }));
  const recovering = controller.recover(); await Promise.resolve();
  const record = controller.snapshot(); localStorage.setItem(KEY, JSON.stringify({ ...record, receipt: receipt('rejected') })); resolve(response('pending'));
  await expect(recovering).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' }); expect(controller.snapshot().receipt.state).toBe('rejected');
});
test('fresh contradictory terminal blocks ACK and preserves draft', async () => {
  api.post.mockResolvedValue(response('rejected')); await controller.submit(input()); api.get.mockResolvedValue(response('replayed'));
  await expect(controller.acknowledge()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' }); expect(sessionStorage.getItem(`${KEY}:draft:${A}`)).not.toBeNull();
});
test('ACK token cannot reset a later intent even with same actor/session', async () => {
  api.post.mockResolvedValue(response('rejected')); api.get.mockResolvedValue(response('rejected')); await controller.submit(input());
  const record = controller.snapshot(), proof = controller.captureIntent(); await controller.acknowledge();
  localStorage.setItem(KEY, JSON.stringify({ ...record, client_operation_id: B, receipt: null })); expect(controller.isCurrentIntent(proof, true)).toBe(false);
});
test('V2 missing null wire field is invalid and retains original identity', async () => {
  await controller.submit(input()); const incomplete = response('rejected'); delete incomplete.data.order_version; api.get.mockResolvedValue(incomplete);
  await expect(controller.recover()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' }); expect(controller.snapshot().receipt.state).toBe('pending');
});
test('oversized durable metadata fails closed without any new POST', async () => {
  localStorage.setItem(KEY, ' '.repeat(8193)); await expect(controller.submit(input())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' }); expect(api.post).not.toHaveBeenCalled(); expect(localStorage.getItem(KEY)).toHaveLength(8193);
});
test('oversized V2 private draft cannot be resent', async () => {
  await controller.submit(input()); sessionStorage.setItem(`${KEY}:draft:${A}`, ' '.repeat(98305)); api.post.mockClear();
  await expect(controller.retrySubmission()).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' }); expect(api.post).not.toHaveBeenCalled(); expect(localStorage.getItem(KEY)).not.toBeNull();
});
