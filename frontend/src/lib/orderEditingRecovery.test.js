import { createOrderEditingRecovery, isOrderEditable, normalizeOrderCorrections,
  validateEditingReceipt, EDIT_REQUEST_TIMEOUT_MS, MAX_EDIT_RECOVERY_READS } from './orderEditingRecovery';

const ID = '123e4567-e89b-42d3-a456-426614174000';
const NEXT = '123e4567-e89b-42d3-a456-426614174001';
const KEY = 'prodelivery:order-edit:v1:qa-admin';
const BASE = '/api/orders/operations/edit/qa-order';
const CAP = '/api/orders/operations/edit/capabilities';
const PII = 'Private Customer Sentinel';
const order = (extra = {}) => ({ id: 'qa-order', restaurant_id: 'qa-restaurant', order_version: 4,
  status: 'NEW', preparation_status: 'NEW', driver_id: null, customer_name: 'Old Customer',
  customer_phone: '0712345678', customer_address: 'Private Street 12', notes: 'Old notes',
  customer_latitude: 46, customer_longitude: 26, ...extra });
const rec = (receipt = null) => ({ actor_id: 'qa-admin', order_id: 'qa-order', client_operation_id: ID, expected_order_version: 4, receipt });
const receipt = (state = 'applied', extra = {}) => ({ client_operation_id: ID, state,
  order_id: ['applied', 'replayed'].includes(state) ? 'qa-order' : null,
  order_version: ['applied', 'replayed'].includes(state) ? 5 : null,
  error_code: state === 'rejected' ? 'ORDER_VERSION_CONFLICT' : null,
  retry_after_seconds: state === 'pending' ? 1 : null, ...extra });
const response = (r = receipt()) => ({ status: r.state === 'pending' ? 202 : r.state === 'rejected' ? 409 : 200,
  data: r, headers: r.state === 'pending' ? { 'retry-after': '1' } : {} });
const missing = () => Object.assign(new Error('not found'), { response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } });
const storage = () => {
  const map = new Map();
  return { getItem: jest.fn((k) => map.get(k) ?? null), setItem: jest.fn((k, v) => map.set(k, v)),
    removeItem: jest.fn((k) => map.delete(k)), text: () => JSON.stringify([...map]) };
};
function harness(extra = {}) {
  const durableStorage = storage(), draftStorage = storage();
  const api = { get: jest.fn(async (path) => path === CAP ? { status: 200, data: { edit_recovery_enabled: true } } : response(receipt('replayed'))),
    post: jest.fn(async () => response()) };
  const options = { actorId: 'qa-admin', api, durableStorage, draftStorage,
    locks: { request: jest.fn(async (_key, _options, action) => action({})) },
    crypto: { randomUUID: jest.fn().mockReturnValueOnce(ID).mockReturnValue(NEXT) }, wait: jest.fn(async () => {}), ...extra };
  return { ...options, controller: createOrderEditingRecovery(options) };
}
const command = (extra = {}) => ({ order: order(), changes: { customer_name: PII }, ...extra });
async function unresolved(h) {
  h.api.post.mockRejectedValue(new Error('timeout'));
  h.api.get.mockImplementation(async (path) => { if (path === CAP) return { status: 200, data: { edit_recovery_enabled: true } }; throw new Error('offline'); });
  await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'RECOVERY_UNAVAILABLE' });
}

describe('strict operational corrections', () => {
  test.each([undefined, null, true, false, '4', 4.5, -1, Infinity, NaN, Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER + 1])('unsafe revision %s fails closed', (v) => {
    expect(isOrderEditable(order({ order_version: v }))).toBe(false);
  });
  test.each(['NEW', 'PREPARING', 'READY'])('eligible %s', (status) => expect(isOrderEditable(order({ status, preparation_status: status }))).toBe(true));
  test.each([{ status: 'DELIVERED' }, { driver_id: '' }, { assigned_at: '' }, { picked_up_at: 'x' },
    { preparation_status: null }, { customer_latitude: true }, { customer_longitude: null }, { customer_latitude: 91 },
    { cancelled_by: '' }, { cancellation_reason: '' }, { cancelled_by: false }, { cancellation_reason: 'cancelled' }])('custody/malformed data %j', (extra) => expect(isOrderEditable(order(extra))).toBe(false));
  test.each(['total_amount', 'delivery_fee', 'items', 'status', 'restaurant_id'])('forbidden %s', (key) => {
    expect(() => normalizeOrderCorrections(order(), { [key]: 'x' })).toThrow();
  });
  test.each([{ customer_name: ' ' }, { customer_phone: '123' }, { customer_address: 'abc' }, { notes: 'a'.repeat(1001) },
    { customer_latitude: null }, { customer_latitude: NaN, customer_longitude: 26 }, { customer_phone: undefined }, {}])('invalid %j', (changes) => {
    expect(() => normalizeOrderCorrections(order(), changes)).toThrow();
  });
  test('address change requires DIFFERENT pair or explicit clear', () => {
    for (const changes of [{ customer_address: 'New Street 15' }, { customer_address: 'New Street 15', customer_latitude: 46, customer_longitude: 26 }]) {
      expect(() => normalizeOrderCorrections(order(), changes)).toThrow(/pereche diferita/);
    }
    expect(normalizeOrderCorrections(order(), { customer_address: 'New Street 15', customer_latitude: null, customer_longitude: null })).toEqual({ customer_address: 'New Street 15', customer_latitude: null, customer_longitude: null });
    expect(normalizeOrderCorrections(order(), { customer_address: 'New Street 15', customer_latitude: 0, customer_longitude: 0 }).customer_latitude).toBe(0);
  });
  test.each([{ client_operation_id: NEXT }, { order_id: 'other' }, { order_version: 6 }, { order_version: Number.MAX_SAFE_INTEGER + 1 }, { customer_name: PII }, { error_code: 'X' }])('invalid receipt %j', (extra) => {
    expect(() => validateEditingReceipt(response(receipt('applied', extra)), rec())).toThrow();
  });
  test('strict status, Retry-After and known rejection codes', () => {
    expect(() => validateEditingReceipt({ ...response(), status: 201 }, rec())).toThrow();
    expect(() => validateEditingReceipt({ ...response(receipt('pending')), headers: {} }, rec())).toThrow();
    expect(() => validateEditingReceipt(response(receipt('rejected', { error_code: 'UNKNOWN' })), rec())).toThrow();
    expect(validateEditingReceipt(response(receipt('rejected')), rec()).state).toBe('rejected');
    expect(validateEditingReceipt({ status: 404, data: receipt('rejected', { error_code: 'ORDER_NOT_FOUND' }) }, rec()).error_code).toBe('ORDER_NOT_FOUND');
  });
  test.each([undefined, null, '', 'UNKNOWN', 'toString', '__proto__', 'constructor'])('cached rejected code %s is independently invalid', (code) => {
    const r = receipt('rejected', { error_code: code });
    expect(() => validateEditingReceipt({ status: undefined, data: r }, rec())).toThrow();
    const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify(rec(r)));
    const original = h.durableStorage.getItem(KEY);
    expect(() => h.controller.snapshot()).toThrow(); expect(h.controller.storageBlocked()).toBe(true);
    expect(h.durableStorage.getItem(KEY)).toBe(original);
    expect(h.durableStorage.removeItem).not.toHaveBeenCalled();
  });
  test('highest safe receipt revision is accepted only from a safe predecessor', () => {
    const r = { ...rec(), expected_order_version: Number.MAX_SAFE_INTEGER - 1 };
    expect(validateEditingReceipt(response(receipt('applied', { order_version: Number.MAX_SAFE_INTEGER })), r).order_version).toBe(Number.MAX_SAFE_INTEGER);
    expect(isOrderEditable(order({ order_version: Number.MAX_SAFE_INTEGER - 1 }))).toBe(true);
  });
});

describe('durable same-identity controller', () => {
  test('persists identity and immutable draft before send; privacy and timeout', async () => {
    const h = harness();
    h.api.post.mockImplementation(async (_path, body, config) => {
      expect(JSON.parse(h.durableStorage.getItem(KEY))).toEqual(rec());
      expect(JSON.parse(h.draftStorage.getItem(`${KEY}:draft:${ID}`)).changes).toEqual(body.changes);
      expect(config.timeout).toBe(EDIT_REQUEST_TIMEOUT_MS);
      expect(h.durableStorage.text()).not.toContain(PII);
      return response();
    });
    await expect(h.controller.submit(command())).resolves.toMatchObject({ state: 'applied', order_version: 5 });
    expect(h.api.post.mock.calls[0][0]).toBe(BASE);
    expect(h.draftStorage.text()).not.toContain(PII);
    expect(h.durableStorage.text()).not.toContain(PII);
  });
  test('disabled capability, offline, missing locks never send/fallback', async () => {
    for (const extra of [{ locks: null }, { isOnline: () => false }]) {
      const h = harness(extra); await expect(h.controller.submit(command())).rejects.toThrow(); expect(h.api.post).not.toHaveBeenCalled();
    }
    const h = harness(); h.api.get.mockResolvedValue({ status: 200, data: { edit_recovery_enabled: false } });
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'EDITING_DISABLED' });
    expect(h.api.post).not.toHaveBeenCalled(); expect(h.durableStorage.getItem(KEY)).toBeNull();
  });
  test('synchronous double click and cross-tab lock fail closed', async () => {
    let release;
    const h = harness(); h.api.post.mockImplementation(() => new Promise((r) => { release = r; }));
    const pending = h.controller.submit(command());
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'BUSY' });
    await Promise.resolve(); await Promise.resolve(); release(response()); await pending;
    const h2 = harness({ locks: { request: async (_k, _o, cb) => cb(null) } });
    await expect(h2.controller.submit(command())).rejects.toMatchObject({ code: 'BUSY' }); expect(h2.api.post).not.toHaveBeenCalled();
  });
  test.each(['durableStorage', 'draftStorage'])('%s failure blocks sends and poisons new intent', async (name) => {
    const h = harness(); h[name].setItem.mockImplementation(() => { throw new Error('quota'); });
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.controller.storageBlocked()).toBe(true);
    expect(h.draftStorage.text()).not.toContain(PII);
    h[name].setItem.mockImplementation(() => {});
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
  });
  test('timeout -> lookup, never new intent; pending -> bodyless resume; bounded reads', async () => {
    const h = harness(); h.api.post.mockRejectedValueOnce(new Error('timeout')).mockResolvedValue(response(receipt('pending')));
    h.api.get.mockImplementation(async (p) => p === CAP ? { status: 200, data: { edit_recovery_enabled: true } } : response(receipt('pending')));
    await expect(h.controller.submit(command())).resolves.toMatchObject({ state: 'pending' });
    expect(h.api.get.mock.calls.filter(([p]) => p !== CAP)).toHaveLength(MAX_EDIT_RECOVERY_READS);
    expect(h.api.post).toHaveBeenCalledTimes(2);
    expect(h.api.post.mock.calls[1]).toEqual([`${BASE}/${ID}/resume`, undefined, { timeout: 15000 }]);
    expect(h.wait.mock.calls).toEqual([[1000], [1000]]);
    await expect(h.controller.submit(command({ changes: { notes: 'other' } }))).rejects.toMatchObject({ code: 'INTENT_PENDING' });
  });
  test('reload unresolved recovers while capability disabled and live data absent', async () => {
    const h = harness(); await unresolved(h);
    const fresh = harness({ durableStorage: h.durableStorage, draftStorage: storage() });
    fresh.api.get.mockResolvedValue(response(receipt('pending')));
    fresh.api.post.mockResolvedValue(response(receipt('replayed')));
    await expect(fresh.controller.recover()).resolves.toMatchObject({ state: 'replayed' });
    expect(fresh.api.get.mock.calls[0][0]).toBe(`${BASE}/${ID}`);
    expect(fresh.api.get.mock.calls.some(([p]) => p === CAP)).toBe(false);
    expect(fresh.api.post.mock.calls[0][1]).toBeUndefined();
  });
  test('lookup 404 resends only saved exact draft and ID, never changed live form', async () => {
    const h = harness(); await unresolved(h);
    const fresh = harness({ durableStorage: h.durableStorage, draftStorage: h.draftStorage });
    fresh.api.get.mockRejectedValue(missing());
    await fresh.controller.recover();
    expect(fresh.api.post.mock.calls[0]).toEqual([BASE, { client_operation_id: ID, expected_order_version: 4, changes: { customer_name: PII } }, { timeout: 15000 }]);
    expect(fresh.crypto.randomUUID).not.toHaveBeenCalled();
  });
  test('exposed draft copies cannot mutate immutable resend payload', async () => {
    const h = harness(); await unresolved(h);
    const exposed = h.controller.savedDraft(); exposed.changes.customer_name = 'Changed after uncertainty';
    h.api.get.mockRejectedValue(missing()); h.api.post.mockResolvedValue(response());
    await h.controller.recover();
    expect(h.api.post.mock.calls[1][1].changes).toEqual({ customer_name: PII });
  });
  test('401 does not refresh, retry or discard the intent', async () => {
    const h = harness(); h.api.post.mockRejectedValue({ response: { status: 401 } });
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
    expect(h.api.post).toHaveBeenCalledTimes(1); expect(h.api.get).toHaveBeenCalledTimes(1);
    expect(h.controller.snapshot().client_operation_id).toBe(ID);
  });
  test('failed terminal persistence blocks acknowledge and new intent', async () => {
    const h = harness(); h.api.post.mockImplementation(async () => {
      h.durableStorage.setItem.mockImplementation(() => { throw new Error('quota after send'); }); return response();
    });
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
    expect(h.controller.storageBlocked()).toBe(true); expect(h.controller.snapshot().receipt).toBeNull();
    await expect(h.controller.acknowledge()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' });
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
    expect(h.api.post).toHaveBeenCalledTimes(1);
  });
  test('404 with missing draft or unrecognized code never sends', async () => {
    for (const missingError of [missing(), Object.assign(new Error(), { response: { status: 404, data: {} } })]) {
      const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify(rec())); h.api.get.mockRejectedValue(missingError);
      await expect(h.controller.recover()).rejects.toThrow(); expect(h.api.post).not.toHaveBeenCalled();
      expect(h.durableStorage.getItem(KEY)).not.toBeNull();
    }
  });
  test('conflict keeps draft; explicit refresh obtains version before a NEW operation', async () => {
    const h = harness(); h.api.post.mockResolvedValue(response(receipt('rejected')));
    await h.controller.submit(command()); expect(h.draftStorage.text()).toContain(PII);
    await expect(h.controller.acknowledge()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' });
    h.api.get.mockResolvedValueOnce({ status: 200, data: order({ order_version: 8 }) });
    const updated = await h.controller.refreshForNewAttempt(); expect(updated.order_version).toBe(8);
    h.api.get.mockResolvedValue({ status: 200, data: { edit_recovery_enabled: true } });
    h.api.post.mockResolvedValue(response(receipt('applied', { client_operation_id: NEXT, order_version: 9 })));
    await h.controller.submit(command({ order: updated }));
    expect(h.api.post.mock.calls[1][1].expected_order_version).toBe(8);
    expect(h.api.post.mock.calls[1][1].client_operation_id).toBe(NEXT);
  });
  test('refresh invalid/ineligible target cannot acknowledge conflict', async () => {
    const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify(rec(receipt('rejected'))));
    h.api.get.mockResolvedValue({ status: 200, data: order({ id: 'other' }) });
    await expect(h.controller.refreshForNewAttempt()).rejects.toMatchObject({ code: 'ORDER_NOT_EDITABLE' });
    expect(h.controller.snapshot().receipt.state).toBe('rejected');
  });
  test('actor switch prevents late outcome writes and clears PII but preserves identity', async () => {
    let active = true, resolve;
    const h = harness({ isOwnerActive: () => active });
    h.api.post.mockImplementation(() => new Promise((r) => { resolve = r; }));
    const pending = h.controller.submit(command()); await Promise.resolve(); await Promise.resolve();
    active = false; h.controller.deactivate(); resolve(response());
    await expect(pending).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
    expect(h.controller.snapshot().receipt).toBeNull(); expect(h.draftStorage.text()).not.toContain(PII);
  });
  test('corrupt metadata, unexpected PII fields and mismatched draft fail closed', async () => {
    const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify({ ...rec(), notes: PII }));
    expect(() => h.controller.snapshot()).toThrow();
    h.durableStorage.setItem(KEY, JSON.stringify(rec()));
    h.draftStorage.setItem(`${KEY}:draft:${ID}`, JSON.stringify({ ...rec(), actor_id: 'other', changes: { customer_name: PII } }));
    h.api.get.mockRejectedValue(missing());
    await expect(h.controller.recover()).rejects.toThrow(); expect(h.api.post).not.toHaveBeenCalled();
  });
  test.each(['applied', 'replayed'])('observing cross-tab %s purges own memory/session payload but keeps identity', async (state) => {
    const h = harness(); await unresolved(h);
    expect(h.controller.savedDraft().changes.customer_name).toBe(PII);
    h.durableStorage.setItem(KEY, JSON.stringify(rec(receipt(state))));
    const terminal = h.durableStorage.getItem(KEY);
    expect(h.controller.snapshot().receipt.state).toBe(state);
    expect(h.draftStorage.text()).not.toContain(PII); expect(h.controller.savedDraft()).toBeNull();
    expect(h.durableStorage.getItem(KEY)).toBe(terminal); expect(h.durableStorage.removeItem).not.toHaveBeenCalled();
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'INTENT_PENDING' });
  });
  test.each(['pending', 'rejected'])('observing %s keeps own draft', async (state) => {
    const h = harness(); await unresolved(h); h.durableStorage.setItem(KEY, JSON.stringify(rec(receipt(state))));
    expect(h.controller.snapshot().receipt.state).toBe(state);
    expect(h.controller.savedDraft().changes.customer_name).toBe(PII); expect(h.draftStorage.text()).toContain(PII);
  });
  test('observer payload purge storage failure blocks new intents without deleting identity', async () => {
    const h = harness(); await unresolved(h); h.durableStorage.setItem(KEY, JSON.stringify(rec(receipt('replayed'))));
    const terminal = h.durableStorage.getItem(KEY);
    h.draftStorage.removeItem.mockImplementation(() => {});
    expect(() => h.controller.snapshot()).toThrow(); expect(h.controller.storageBlocked()).toBe(true);
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
    expect(h.durableStorage.getItem(KEY)).toBe(terminal); expect(h.durableStorage.removeItem).not.toHaveBeenCalled();
  });
});
