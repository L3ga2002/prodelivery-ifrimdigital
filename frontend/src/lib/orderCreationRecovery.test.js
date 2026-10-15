import {
  createOrderRecovery, validateCreationReceipt, normalizeCreateOrder,
  MAX_RECOVERY_READS, CREATE_REQUEST_TIMEOUT_MS,
} from './orderCreationRecovery';

const CREATE = '/api/orders/operations/create';
const ACTOR = 'qa-admin-01';
const OPERATION = '123e4567-e89b-42d3-a456-426614174000';
const NEXT_OPERATION = '123e4567-e89b-42d3-a456-426614174001';
const OTHER_OPERATION = '123e4567-e89b-42d3-a456-426614174099';
const PRIVATE_VALUES = [
  'QA Customer Sentinel', '0712345678', 'QA Private Street 42',
  'QA Private Note Sentinel', 'QA Private Item Sentinel',
];
const clone = (value) => JSON.parse(JSON.stringify(value));

function validOrder(overrides = {}) {
  return {
    restaurant_id: 'qa-restaurant-01',
    customer_name: PRIVATE_VALUES[0],
    customer_phone: PRIVATE_VALUES[1],
    customer_address: PRIVATE_VALUES[2],
    customer_latitude: 46.57,
    customer_longitude: 26.91,
    items: [{ name: PRIVATE_VALUES[4], quantity: 2, price: 25 }],
    subtotal_amount: 50,
    delivery_fee: 5,
    total_amount: 55,
    payment_type: 'CASH',
    source: 'S',
    delivery_zone_id: 'qa-zone-01',
    delivery_zone_name: 'QA Zone',
    delivery_sector: 'QA Sector',
    delivery_zone_level: 1,
    notes: PRIVATE_VALUES[3],
    ...overrides,
  };
}

function receipt(state = 'applied', overrides = {}) {
  const result = {
    client_operation_id: OPERATION,
    state,
    order_id: null,
    order_version: null,
    error_code: null,
    retry_after_seconds: null,
  };
  if (state === 'applied' || state === 'replayed') {
    result.order_id = 'qa-created-order-01';
    result.order_version = 0;
  } else if (state === 'pending') {
    result.retry_after_seconds = 1;
  } else if (state === 'rejected') {
    result.error_code = 'RESTAURANT_PAUSED';
  }
  return { ...result, ...overrides };
}

function response(status, data) {
  return { status, data, headers: { 'cache-control': 'no-store' } };
}

function httpError(status, data = { detail: { code: 'QA_HTTP_ERROR' } }) {
  const error = new Error('QA transport failure');
  error.response = response(status, data);
  return error;
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function memoryStorage(trace = [], label = 'storage') {
  const values = new Map();
  return {
    get length() { return values.size; },
    key: jest.fn((index) => Array.from(values.keys())[index] ?? null),
    getItem: jest.fn((key) => values.get(String(key)) ?? null),
    setItem: jest.fn((key, value) => {
      trace.push(`${label}:write`);
      values.set(String(key), String(value));
    }),
    removeItem: jest.fn((key) => values.delete(String(key))),
    clear: jest.fn(() => values.clear()),
    entries: () => Array.from(values.entries()),
    text: () => JSON.stringify(Array.from(values.entries())),
    seed: (key, value) => values.set(String(key), String(value)),
  };
}

function webLocks(trace = []) {
  const held = new Set();
  return {
    held,
    request: jest.fn(async (name, options, callback) => {
      expect(typeof name).toBe('string');
      expect(name.length).toBeGreaterThan(0);
      expect(options).toEqual(expect.objectContaining({ ifAvailable: true }));
      if (held.has(name)) return callback(null);
      held.add(name);
      trace.push('lock:acquired');
      try {
        return await callback({ name, mode: 'exclusive' });
      } finally {
        trace.push('lock:released');
        held.delete(name);
      }
    }),
  };
}

function harness(overrides = {}) {
  const trace = [];
  const durableStorage = memoryStorage(trace, 'durable');
  const draftStorage = memoryStorage(trace, 'draft');
  const locks = webLocks(trace);
  const crypto = { randomUUID: jest.fn().mockReturnValueOnce(OPERATION).mockReturnValue(NEXT_OPERATION) };
  const wait = jest.fn(async () => {});
  const api = {
    get: jest.fn().mockRejectedValue(httpError(503)),
    post: jest.fn().mockImplementation(async () => {
      trace.push('http:post');
      return response(201, receipt());
    }),
  };
  const options = {
    actorId: ACTOR, api, durableStorage, draftStorage, locks, crypto,
    isOnline: () => true, wait, ...overrides,
  };
  const controller = createOrderRecovery(options);
  return {
    controller, options, trace, ...options,
    reload: (changes = {}) => createOrderRecovery({ ...options, ...changes }),
  };
}

// The public methods may return state or reject. Safety is asserted on effects.
async function invoke(callback) {
  try { return { value: await callback() }; }
  catch (error) { return { error }; }
}

async function flush() {
  for (let turn = 0; turn < 20; turn += 1) await Promise.resolve();
}

function expectNoPII(value) {
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  for (const sentinel of PRIVATE_VALUES) expect(text || '').not.toContain(sentinel);
}

function expectActive(h, id = OPERATION) {
  expect(h.durableStorage.text()).toContain(id);
  expectNoPII(h.durableStorage.text());
}

async function expectUnresolved(h, controller = h.controller) {
  expectActive(h);
  const snapshot = JSON.stringify(controller.snapshot());
  expect(snapshot).not.toMatch(/"(?:applied|replayed|rejected)"/);
  await invoke(() => controller.acknowledge());
  expectActive(h);
}

function expectOnlyRecoverableRoutes(api) {
  for (const [url] of api.post.mock.calls) {
    expect(url === CREATE || url === `${CREATE}/${OPERATION}/resume`).toBe(true);
  }
  for (const [url] of api.get.mock.calls) expect(url).toBe(`${CREATE}/${OPERATION}`);
}

describe('S2-02D independent controller contract', () => {
  afterEach(() => jest.restoreAllMocks());

  test('starts idle with no automatic network or persistent draft', async () => {
    const h = harness();
    await flush();
    expect(h.controller.snapshot()).toBeNull();
    expect(h.api.get).not.toHaveBeenCalled();
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    expect(h.durableStorage.setItem).not.toHaveBeenCalled();
    expect(h.draftStorage.setItem).not.toHaveBeenCalled();
  });

  test.each([
    ['blank restaurant', { restaurant_id: '   ' }],
    ['blank name', { customer_name: ' \t ' }],
    ['too short name', { customer_name: 'Q' }],
    ['missing phone', { customer_phone: '' }],
    ['short phone', { customer_phone: '123' }],
    ['blank address', { customer_address: '  ' }],
    ['latitude outside range', { customer_latitude: 91 }],
    ['longitude outside range', { customer_longitude: -181 }],
    ['unpaired coordinates', { customer_longitude: null }],
    ['nonfinite coordinates', { customer_latitude: NaN }],
    ['negative total', { total_amount: -1 }],
    ['nonfinite total', { total_amount: Infinity }],
    ['invalid payment', { payment_type: 'OTHER' }],
    ['blank item', { items: [{ name: ' ', quantity: 1, price: 5 }] }],
    ['zero quantity', { items: [{ name: 'QA Item', quantity: 0, price: 5 }] }],
    ['noninteger quantity', { items: [{ name: 'QA Item', quantity: 1.5, price: 5 }] }],
    ['negative item price', { items: [{ name: 'QA Item', quantity: 1, price: -5 }] }],
    ['too long notes', { notes: 'x'.repeat(1001) }],
  ])('validates %s before durable/draft writes or network', async (_label, invalid) => {
    const h = harness();
    const result = await invoke(() => h.controller.submit(validOrder(invalid)));
    expect(h.api.get).not.toHaveBeenCalled();
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.durableStorage.setItem).not.toHaveBeenCalled();
    expect(h.draftStorage.setItem).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    expectNoPII(result.error?.message);
    expectNoPII(h.controller.snapshot());
  });

  test('persists pending metadata and exact session draft under lock before the sole create POST', async () => {
    const h = harness();
    const order = validOrder();
    h.api.post.mockImplementation(async (url, command) => {
      expect(url).toBe(CREATE);
      expect(command).toEqual({ client_operation_id: OPERATION, order });
      expect(h.locks.held.size).toBe(1);
      expectActive(h);
      expect(h.controller.snapshot().receipt).toBeNull();
      for (const value of PRIVATE_VALUES) expect(h.draftStorage.text()).toContain(value);
      h.trace.push('http:post');
      return response(201, receipt());
    });
    await h.controller.submit(order);
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    expect(h.trace.indexOf('lock:acquired')).toBeLessThan(h.trace.indexOf('durable:write'));
    expect(h.trace.indexOf('durable:write')).toBeLessThan(h.trace.indexOf('http:post'));
    expect(h.trace.indexOf('draft:write')).toBeLessThan(h.trace.indexOf('http:post'));
    expect(h.trace.indexOf('http:post')).toBeLessThan(h.trace.indexOf('lock:released'));
    expectOnlyRecoverableRoutes(h.api);
  });

  test('zero coordinates are valid numeric values, not missing fields', async () => {
    const h = harness();
    await h.controller.submit(validOrder({ customer_latitude: 0, customer_longitude: 0 }));
    expect(h.api.post).toHaveBeenCalledTimes(1);
  });

  test('double click stays locked across an unresolved async POST and sends only once', async () => {
    const h = harness();
    const gate = deferred();
    h.api.post.mockReturnValue(gate.promise);
    const first = invoke(() => h.controller.submit(validOrder()));
    await flush();
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.locks.held.size).toBe(1);
    await invoke(() => h.controller.submit(validOrder()));
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    gate.resolve(response(201, receipt()));
    await first;
    expect(h.locks.held.size).toBe(0);
  });

  test('a second controller in the same tab cannot race the active async create', async () => {
    const h = harness();
    const other = h.reload();
    const gate = deferred();
    h.api.post.mockReturnValue(gate.promise);
    const first = invoke(() => h.controller.submit(validOrder()));
    await flush();
    await invoke(() => other.submit(validOrder({ customer_address: 'QA Changed Address 99' })));
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    gate.resolve(response(201, receipt()));
    await first;
  });

  test('another tab with separate session storage cannot admit a second intent while lock is held', async () => {
    const h = harness();
    const otherDraft = memoryStorage();
    const other = h.reload({ draftStorage: otherDraft });
    const gate = deferred();
    h.api.post.mockReturnValue(gate.promise);
    const first = invoke(() => h.controller.submit(validOrder()));
    await flush();
    await invoke(() => other.submit(validOrder()));
    await invoke(() => other.recover());
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.api.get).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    expectNoPII(otherDraft.text());
    gate.resolve(response(201, receipt()));
    await first;
  });

  test('caller mutation after submit cannot alter the frozen admitted payload', async () => {
    const h = harness();
    const order = validOrder();
    const expected = clone(order);
    const gate = deferred();
    let command;
    h.api.post.mockImplementation((_url, body) => { command = body; return gate.promise; });
    const first = invoke(() => h.controller.submit(order));
    await flush();
    order.customer_name = 'QA Mutated Name';
    order.items[0].quantity = 99;
    expect(command.order).toEqual(expected);
    gate.reject(new Error('QA timeout'));
    await first;
    h.api.get.mockRejectedValue(httpError(404));
    h.api.post.mockResolvedValue(response(201, receipt()));
    await h.controller.recover();
    expect(h.api.post.mock.calls[1][1]).toEqual({ client_operation_id: OPERATION, order: expected });
  });

  test('changed fields on an unresolved intent cannot create or overwrite a new command', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA timeout'));
    await invoke(() => h.controller.submit(validOrder()));
    const draft = h.draftStorage.text();
    const posts = h.api.post.mock.calls.length;
    await invoke(() => h.controller.submit(validOrder({ total_amount: 900, notes: 'QA Changed Intent' })));
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    expect(h.api.post).toHaveBeenCalledTimes(posts);
    expect(h.draftStorage.text()).toBe(draft);
    await expectUnresolved(h);
  });

  test('transport cannot mutate the internal frozen intent used by same-ID recovery', async () => {
    const h = harness();
    let original;
    h.api.post.mockImplementationOnce(async (_path, body) => {
      original = clone(body);
      // An interceptor receives this reference; it must not own the canonical draft.
      try { body.order.customer_name = 'QA Transport Mutation'; } catch { /* Frozen is safe. */ }
      try { body.order.items[0].quantity = 99; } catch { /* Frozen is safe. */ }
      throw new Error('QA response lost after interceptor');
    });
    await invoke(() => h.controller.submit(validOrder()));
    h.api.get.mockRejectedValue(httpError(404));
    h.api.post.mockResolvedValue(response(200, receipt('replayed')));
    await h.controller.recover();
    expect(h.api.post.mock.calls[1][1]).toEqual(original);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
  });

  test('recover retains the cross-tab lock while lookup is awaiting a response', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA response lost'));
    await invoke(() => h.controller.submit(validOrder()));
    h.api.get.mockClear();
    const gate = deferred();
    h.api.get.mockReturnValue(gate.promise);
    const recovery = invoke(() => h.controller.recover());
    await flush();
    expect(h.locks.held.size).toBe(1);
    const otherTab = h.reload({ draftStorage: memoryStorage() });
    await invoke(() => otherTab.recover());
    await invoke(() => otherTab.submit(validOrder()));
    await invoke(() => otherTab.acknowledge());
    expect(h.api.get).toHaveBeenCalledTimes(1);
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expectActive(h);
    gate.resolve(response(200, receipt('replayed')));
    await recovery;
    expect(h.locks.held.size).toBe(0);
    expectActive(h);
  });

  test('refresh/new controller looks up the same ID and does not create another intent', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA response lost'));
    await invoke(() => h.controller.submit(validOrder()));
    const reloaded = h.reload();
    h.api.get.mockResolvedValue(response(200, receipt('replayed')));
    await reloaded.recover();
    expect(h.api.get).toHaveBeenCalledWith(`${CREATE}/${OPERATION}`, expect.anything());
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(reloaded.snapshot())).toContain('replayed');
    expectActive(h);
  });

  test('pending lookup resumes server-owned payload using the same ID without a session draft', async () => {
    const h = harness();
    h.api.post.mockRejectedValueOnce(new Error('QA response lost'));
    await invoke(() => h.controller.submit(validOrder()));
    const freshDraft = memoryStorage();
    const otherTab = h.reload({ draftStorage: freshDraft });
    h.api.get.mockResolvedValue(response(202, receipt('pending')));
    h.api.post.mockResolvedValue(response(200, receipt('replayed')));
    await otherTab.recover();
    expect(h.api.get.mock.calls[0][0]).toBe(`${CREATE}/${OPERATION}`);
    expect(h.api.post).toHaveBeenCalledTimes(2);
    expect(h.api.post.mock.calls[1][0]).toBe(`${CREATE}/${OPERATION}/resume`);
    expectNoPII(h.api.post.mock.calls[1].slice(1));
    expect(freshDraft.setItem).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(otherTab.snapshot())).toContain('replayed');
    expectOnlyRecoverableRoutes(h.api);
  });

  test('GET 404 with exact session draft may resubmit only the original ID/payload', async () => {
    const h = harness();
    h.api.post.mockRejectedValueOnce(new Error('QA response lost'));
    await invoke(() => h.controller.submit(validOrder()));
    const original = clone(h.api.post.mock.calls[0][1]);
    h.api.get.mockRejectedValue(httpError(404));
    h.api.post.mockResolvedValue(response(200, receipt('replayed')));
    await h.reload().recover();
    expect(h.api.get.mock.calls[0][0]).toBe(`${CREATE}/${OPERATION}`);
    expect(h.api.post).toHaveBeenCalledTimes(2);
    expect(h.api.post.mock.calls[1][0]).toBe(CREATE);
    expect(h.api.post.mock.calls[1][1]).toEqual(original);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    expectOnlyRecoverableRoutes(h.api);
  });

  test('GET 404 in a fresh tab without draft remains unresolved and does not permit a new intent', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA response lost'));
    await invoke(() => h.controller.submit(validOrder()));
    const otherTab = h.reload({ draftStorage: memoryStorage() });
    h.api.get.mockRejectedValue(httpError(404));
    await invoke(() => otherTab.recover());
    await invoke(() => otherTab.submit(validOrder({ customer_name: 'QA Different Customer' })));
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    await expectUnresolved(h, otherTab);
  });

  test('clearDraft removes session PII but cannot release pending durable identity', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA timeout'));
    await invoke(() => h.controller.submit(validOrder()));
    await invoke(() => h.controller.clearDraft());
    expectNoPII(h.draftStorage.text());
    expectActive(h);
    h.api.get.mockRejectedValue(httpError(404));
    await invoke(() => h.reload().recover());
    expect(h.api.post).toHaveBeenCalledTimes(1);
    await expectUnresolved(h);
  });

  test('actor B cannot read, recover, acknowledge or clear actor A intent/draft', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA timeout'));
    await invoke(() => h.controller.submit(validOrder()));
    h.api.get.mockClear();
    const before = h.durableStorage.text();
    const draftBefore = h.draftStorage.text();
    const other = h.reload({ actorId: 'qa-admin-02' });
    expect(JSON.stringify(other.snapshot())).not.toContain(OPERATION);
    expectNoPII(other.snapshot());
    await invoke(() => other.recover());
    await invoke(() => other.acknowledge());
    await invoke(() => other.clearDraft());
    expect(h.api.get).not.toHaveBeenCalled();
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.durableStorage.text()).toBe(before);
    expect(h.draftStorage.text()).toBe(draftBefore);
  });

  test.each([
    ['applied', 201], ['replayed', 200], ['rejected', 409],
  ])('%s is persisted across reload until explicit acknowledge, blocking another submit', async (state, status) => {
    const h = harness();
    const data = receipt(state);
    h.api.post.mockImplementation(async () => {
      if (state === 'rejected') throw httpError(status, data);
      return response(status, data);
    });
    await invoke(() => h.controller.submit(validOrder()));
    expectActive(h);
    expect(JSON.stringify(h.controller.snapshot())).toContain(state);
    const reloaded = h.reload();
    expect(JSON.stringify(reloaded.snapshot())).toContain(state);
    await invoke(() => reloaded.submit(validOrder({ total_amount: 100 })));
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    await reloaded.acknowledge();
    expect(h.durableStorage.text()).not.toContain(OPERATION);
    expectNoPII(h.draftStorage.text());
    h.api.post.mockResolvedValue(response(201, receipt('applied', { client_operation_id: NEXT_OPERATION })));
    await reloaded.submit(validOrder());
    expect(h.api.post).toHaveBeenCalledTimes(2);
    expect(h.api.post.mock.calls[1][1].client_operation_id).toBe(NEXT_OPERATION);
  });

  test.each([
    ['success on 202', 202, receipt()],
    ['applied on 200', 200, receipt()],
    ['replayed on 201', 201, receipt('replayed')],
    ['rejected on 200', 200, receipt('rejected')],
    ['pending on 201', 201, receipt('pending')],
    ['wrong ID', 201, receipt('applied', { client_operation_id: OTHER_OPERATION })],
    ['missing ID', 201, receipt('applied', { client_operation_id: undefined })],
    ['missing order ID', 201, receipt('applied', { order_id: null })],
    ['blank order ID', 201, receipt('applied', { order_id: '  ' })],
    ['noncanonical padded order ID', 201, receipt('applied', { order_id: ' qa-created-order-01 ' })],
    ['missing version', 201, receipt('applied', { order_version: null })],
    ['nonzero creation version', 201, receipt('applied', { order_version: 1 })],
    ['string version', 201, receipt('applied', { order_version: '0' })],
    ['boolean version', 201, receipt('applied', { order_version: false })],
    ['success plus error', 201, receipt('applied', { error_code: 'RESTAURANT_PAUSED' })],
    ['success plus retry', 201, receipt('applied', { retry_after_seconds: 1 })],
    ['unknown state', 201, receipt('success')],
    ['legacy order body', 201, { id: 'qa-order', customer_name: PRIVATE_VALUES[0] }],
    ['null body', 201, null],
    ['array body', 201, [receipt()]],
  ])('malformed receipt %s cannot release the active intent', async (_label, status, data) => {
    const h = harness();
    h.api.post.mockResolvedValue(response(status, data));
    await invoke(() => h.controller.submit(validOrder()));
    await expectUnresolved(h);
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expectOnlyRecoverableRoutes(h.api);
  });

  test.each([
    ['wrong ID', receipt('rejected', { client_operation_id: OTHER_OPERATION })],
    ['missing error', receipt('rejected', { error_code: null })],
    ['non-code error', receipt('rejected', { error_code: PRIVATE_VALUES[3] })],
    ['claims order', receipt('rejected', { order_id: 'qa-order', order_version: 0 })],
    ['claims retry', receipt('rejected', { retry_after_seconds: 1 })],
  ])('malformed rejected receipt %s on 409 cannot be acknowledged', async (_label, data) => {
    const h = harness();
    h.api.post.mockRejectedValue(httpError(409, data));
    await invoke(() => h.controller.submit(validOrder()));
    await expectUnresolved(h);
    expectNoPII(h.controller.snapshot());
  });

  test('matching committed lookup is validated just as strictly as a create response', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA timeout'));
    await invoke(() => h.controller.submit(validOrder()));
    h.api.get.mockResolvedValue(response(200, receipt('replayed', { order_version: 7 })));
    await invoke(() => h.controller.recover());
    expect(h.api.post).toHaveBeenCalledTimes(1);
    await expectUnresolved(h);
  });

  test.each([401, 403, 409, 422, 500, 503])('HTTP %s nonreceipt keeps identity, no legacy fallback or new ID', async (status) => {
    const h = harness();
    h.api.post.mockRejectedValue(httpError(status));
    await invoke(() => h.controller.submit(validOrder()));
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    await expectUnresolved(h);
    expectOnlyRecoverableRoutes(h.api);
  });

  test.each([401, 403, 409, 503])('lookup HTTP %s stays unresolved and cannot replay the create POST', async (status) => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA timeout'));
    await invoke(() => h.controller.submit(validOrder()));
    h.api.get.mockRejectedValue(httpError(status));
    await invoke(() => h.controller.recover());
    expect(h.api.post).toHaveBeenCalledTimes(1);
    await expectUnresolved(h);
  });

  test('network timeout does not copy axios request payload or raw PII into metadata/errors/logs', async () => {
    const h = harness();
    const logs = ['error', 'warn', 'log', 'info', 'debug'].map((name) => jest.spyOn(console, name).mockImplementation(() => {}));
    const error = new Error(PRIVATE_VALUES.join(' '));
    error.code = 'ECONNABORTED';
    error.config = { data: JSON.stringify(validOrder()), url: CREATE };
    error.response = response(503, { detail: { message: PRIVATE_VALUES[2] } });
    h.api.post.mockRejectedValue(error);
    const result = await invoke(() => h.controller.submit(validOrder()));
    expectNoPII(h.controller.snapshot());
    expectNoPII(h.durableStorage.text());
    expectNoPII(result.error?.message);
    for (const spy of logs) expectNoPII(spy.mock.calls);
    await expectUnresolved(h);
  });

  test('framework 422 INVALID_REQUEST may be known rejected but still needs acknowledgement', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(httpError(422, {
      detail: { code: 'INVALID_REQUEST', message: 'Datele cererii sunt invalide.' },
    }));
    await invoke(() => h.controller.submit(validOrder()));
    expectActive(h);
    expect(JSON.stringify(h.controller.snapshot())).toContain('rejected');
    await h.reload().acknowledge();
    expect(h.durableStorage.text()).not.toContain(OPERATION);
  });

  test.each([401, 409, 500, 503])('INVALID_REQUEST code outside 422 (%s) is not known rejection', async (status) => {
    const h = harness();
    h.api.post.mockRejectedValue(httpError(status, { detail: { code: 'INVALID_REQUEST' } }));
    await invoke(() => h.controller.submit(validOrder()));
    await expectUnresolved(h);
  });

  test('offline initial submit does not persist/send; reconnection admits only once', async () => {
    let online = false;
    const h = harness({ isOnline: () => online });
    await invoke(() => h.controller.submit(validOrder()));
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.durableStorage.setItem).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    online = true;
    await h.controller.submit(validOrder());
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
  });

  test('offline recovery preserves existing intent; explicit reconnect recovery uses same ID', async () => {
    let online = true;
    const h = harness({ isOnline: () => online });
    h.api.post.mockRejectedValue(new Error('QA timeout'));
    await invoke(() => h.controller.submit(validOrder()));
    online = false;
    h.api.get.mockClear();
    await invoke(() => h.controller.recover());
    expect(h.api.get).not.toHaveBeenCalled();
    await expectUnresolved(h);
    online = true;
    h.api.get.mockResolvedValue(response(200, receipt('replayed')));
    await h.controller.recover();
    expect(h.api.get.mock.calls[0][0]).toBe(`${CREATE}/${OPERATION}`);
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
  });

  test('pending recovery is bounded and no background poll continues after it settles', async () => {
    const h = harness();
    h.api.post.mockResolvedValue(response(202, receipt('pending')));
    h.api.get.mockImplementation(async () => {
      if (h.api.get.mock.calls.length > 6) throw new Error('QA bounded-recovery guard');
      return response(202, receipt('pending'));
    });
    await h.controller.submit(validOrder());
    const beforeReads = h.api.get.mock.calls.length;
    const beforeResumes = h.api.post.mock.calls.filter(([url]) => url.endsWith('/resume')).length;
    await invoke(() => h.controller.recover());
    expect(h.api.get.mock.calls.length - beforeReads).toBeGreaterThanOrEqual(1);
    expect(h.api.get.mock.calls.length - beforeReads).toBeLessThanOrEqual(3);
    expect(h.api.post.mock.calls.filter(([url]) => url === CREATE)).toHaveLength(1);
    expect(h.api.post.mock.calls.filter(([url]) => url.endsWith('/resume')).length - beforeResumes).toBeLessThanOrEqual(1);
    const counts = [h.api.get.mock.calls.length, h.api.post.mock.calls.length];
    await flush();
    expect([h.api.get.mock.calls.length, h.api.post.mock.calls.length]).toEqual(counts);
    await expectUnresolved(h);
    expectOnlyRecoverableRoutes(h.api);
  });

  test.each(['durableStorage', 'draftStorage'])('%s read failure fails closed before create POST', async (option) => {
    const storage = memoryStorage();
    const api = { get: jest.fn(), post: jest.fn() };
    storage.getItem.mockImplementation(() => { throw new Error('QA storage denied'); });
    await invoke(async () => {
      const h = harness({ [option]: storage, api });
      await h.controller.submit(validOrder());
    });
    expect(api.post).not.toHaveBeenCalled();
    expect(api.get).not.toHaveBeenCalled();
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  test.each(['durableStorage', 'draftStorage'])('%s write failure fails closed before create POST', async (option) => {
    const storage = memoryStorage();
    storage.setItem.mockImplementation(() => { throw new Error('QA quota exceeded'); });
    const h = harness({ [option]: storage });
    await invoke(() => h.controller.submit(validOrder()));
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.api.get).not.toHaveBeenCalled();
  });

  test.each([
    ['missing durable storage', { durableStorage: null }],
    ['missing draft storage', { draftStorage: null }],
    ['missing locks', { locks: null }],
    ['missing crypto', { crypto: null }],
    ['missing UUID generator', { crypto: {} }],
    ['invalid UUID output', { crypto: { randomUUID: () => 'unsafe/../id' } }],
    ['empty actor', { actorId: '' }],
  ])('%s fails closed and does not use Math.random as an ID fallback', async (_label, options) => {
    const api = { get: jest.fn(), post: jest.fn() };
    const random = jest.spyOn(Math, 'random').mockImplementation(() => { throw new Error('QA forbidden RNG'); });
    await invoke(async () => {
      const h = harness({ ...options, api });
      await h.controller.submit(validOrder());
    });
    expect(api.post).not.toHaveBeenCalled();
    expect(api.get).not.toHaveBeenCalled();
    expect(random).not.toHaveBeenCalled();
  });

  test('UUID generator throw fails closed before persistence or network', async () => {
    const h = harness({ crypto: { randomUUID: jest.fn(() => { throw new Error('QA crypto failure'); }) } });
    await invoke(() => h.controller.submit(validOrder()));
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.durableStorage.setItem).not.toHaveBeenCalled();
    expect(h.draftStorage.setItem).not.toHaveBeenCalled();
  });

  test('recovery constants are explicit and every HTTP request carries the finite timeout', async () => {
    expect(MAX_RECOVERY_READS).toBe(3);
    expect(CREATE_REQUEST_TIMEOUT_MS).toBe(15000);
    const h = harness();
    h.api.post.mockRejectedValueOnce(new Error('QA response lost'));
    await invoke(() => h.controller.submit(validOrder()));
    h.api.get.mockResolvedValue(response(202, receipt('pending')));
    h.api.post.mockResolvedValue(response(200, receipt('replayed')));
    await h.controller.recover();
    for (const [, config] of h.api.get.mock.calls) expect(config).toEqual(expect.objectContaining({ timeout: 15000 }));
    for (const [, , config] of h.api.post.mock.calls) expect(config).toEqual(expect.objectContaining({ timeout: 15000 }));
  });

  test('framework 422 from resume after server confirmed pending cannot reject the existing intent', async () => {
    const h = harness();
    h.api.get.mockResolvedValue(response(202, receipt('pending')));
    h.api.post.mockImplementation(async (path) => {
      if (path === CREATE) return response(202, receipt('pending'));
      throw httpError(422, { detail: { code: 'INVALID_REQUEST' } });
    });
    await invoke(() => h.controller.submit(validOrder()));
    expect(h.api.post.mock.calls.map(([path]) => path)).toEqual([CREATE, `${CREATE}/${OPERATION}/resume`]);
    await expectUnresolved(h);
  });

  test('framework 422 from lookup after a pending create cannot reject the existing intent', async () => {
    const h = harness();
    h.api.post.mockResolvedValue(response(202, receipt('pending')));
    h.api.get.mockRejectedValue(httpError(422, { detail: { code: 'INVALID_REQUEST' } }));
    await invoke(() => h.controller.submit(validOrder()));
    await expectUnresolved(h);
  });

  test('snapshot returns an isolated record; UI mutation cannot alter stored recovery identity', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA response lost'));
    await invoke(() => h.controller.submit(validOrder()));
    const snapshot = h.controller.snapshot();
    snapshot.client_operation_id = OTHER_OPERATION;
    snapshot.receipt = receipt('replayed', { client_operation_id: OTHER_OPERATION });
    expectActive(h);
    expect(h.controller.snapshot().client_operation_id).toBe(OPERATION);
    await expectUnresolved(h);
  });

  test.each([
    ['invalid JSON', '{'],
    ['missing version', { actor_id: ACTOR, client_operation_id: OPERATION, created_at: 1, receipt: null }],
    ['wrong actor', { version: 1, actor_id: 'qa-admin-other', client_operation_id: OPERATION, created_at: 1, receipt: null }],
    ['invalid ID', { version: 1, actor_id: ACTOR, client_operation_id: '../unsafe', created_at: 1, receipt: null }],
    ['malformed terminal', { version: 1, actor_id: ACTOR, client_operation_id: OPERATION, created_at: 1, receipt: receipt('replayed', { order_version: 3 }) }],
    ['unexpected PII field', { version: 1, actor_id: ACTOR, client_operation_id: OPERATION, created_at: 1, receipt: null, customer_name: PRIVATE_VALUES[0] }],
  ])('corrupt durable metadata (%s) fails closed and cannot be overwritten', async (_label, data) => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA timeout'));
    await invoke(() => h.controller.submit(validOrder()));
    const key = h.durableStorage.entries()[0][0];
    const raw = typeof data === 'string' ? data : JSON.stringify(data);
    h.durableStorage.seed(key, raw);
    h.api.get.mockClear();
    const posts = h.api.post.mock.calls.length;
    const reloaded = h.reload();
    const result = await invoke(() => reloaded.recover());
    await invoke(() => reloaded.submit(validOrder()));
    await invoke(() => reloaded.acknowledge());
    expect(h.api.get).not.toHaveBeenCalled();
    expect(h.api.post).toHaveBeenCalledTimes(posts);
    expect(h.durableStorage.getItem(key)).toBe(raw);
    expectNoPII(result.error?.message);
  });

  test('stored receipt mismatch never replaces the active ID or unlocks acknowledgement', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA timeout'));
    await invoke(() => h.controller.submit(validOrder()));
    const [key, raw] = h.durableStorage.entries()[0];
    const record = JSON.parse(raw);
    record.receipt = receipt('replayed', { client_operation_id: OTHER_OPERATION });
    h.durableStorage.seed(key, JSON.stringify(record));
    const result = await invoke(() => h.reload().recover());
    expect(result.error).toBeDefined();
    await invoke(() => h.reload().acknowledge());
    expect(h.durableStorage.getItem(key)).toBe(JSON.stringify(record));
  });

  test('normalization creates a deep copy and accepts only the precise unused product placeholder', () => {
    const order = validOrder();
    const normalized = normalizeCreateOrder(order);
    normalized.items[0].quantity = 7;
    expect(order.items[0].quantity).toBe(2);
    expect(normalizeCreateOrder(validOrder({ items: [{ name: '', quantity: 1, price: 0 }] })).items).toEqual([]);
    expect(() => normalizeCreateOrder(validOrder({ items: [{ name: '', quantity: 2, price: 0 }] }))).toThrow();
  });

  test.each([
    ['pending without delay', 202, receipt('pending', { retry_after_seconds: null })],
    ['pending string delay', 202, receipt('pending', { retry_after_seconds: '1' })],
    ['pending excessive delay', 202, receipt('pending', { retry_after_seconds: 61 })],
    ['pending zero delay', 202, receipt('pending', { retry_after_seconds: 0 })],
    ['pending with order', 202, receipt('pending', { order_id: 'qa-order', order_version: 0 })],
    ['pending with error', 202, receipt('pending', { error_code: 'QA_ERROR' })],
    ['control character in order', 201, receipt('applied', { order_id: 'qa\norder' })],
    ['padded noncanonical order ID', 201, receipt('applied', { order_id: ' qa-created-order-01 ' })],
    ['unexpected receipt field', 201, receipt('applied', { customer_name: PRIVATE_VALUES[0] })],
    ['string HTTP status', '201', receipt('applied')],
    ['rejected wrong HTTP status', 503, receipt('rejected')],
  ])('strict exported receipt validation refuses %s', (_label, status, data) => {
    expect(() => validateCreationReceipt(response(status, data), OPERATION)).toThrow();
  });

  test('a genuine 404 rejected receipt is terminal, not lookup-not-found resubmission', async () => {
    const h = harness();
    h.api.post.mockRejectedValue(new Error('QA timeout'));
    await invoke(() => h.controller.submit(validOrder()));
    h.api.get.mockRejectedValue(httpError(404, receipt('rejected', { error_code: 'RESTAURANT_NOT_FOUND' })));
    await h.controller.recover();
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(h.controller.snapshot())).toContain('rejected');
    expectActive(h);
  });

  test('Web Locks failure fails closed before persistence or network', async () => {
    const locks = { request: jest.fn().mockRejectedValue(new Error('QA locks denied')) };
    const h = harness({ locks });
    await invoke(() => h.controller.submit(validOrder()));
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.durableStorage.setItem).not.toHaveBeenCalled();
    expect(h.draftStorage.setItem).not.toHaveBeenCalled();
  });

  test('ifAvailable null lock cannot run any submit or recover network', async () => {
    const locks = { request: jest.fn(async (_name, _options, callback) => callback(null)) };
    const h = harness({ locks });
    await invoke(() => h.controller.submit(validOrder()));
    await invoke(() => h.controller.recover());
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.api.get).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    expect(h.durableStorage.setItem).not.toHaveBeenCalled();
  });
});
