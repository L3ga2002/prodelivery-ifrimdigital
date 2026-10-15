import { createOrderEditingRecovery, OrderEditingError } from './orderEditingRecovery';

const ACTOR = 'review-s203-admin';
const ORDER_ID = 'review-s203-order';
const OP = '123e4567-e89b-42d3-a456-426614174090';
const KEY = `prodelivery:order-edit:v1:${ACTOR}`;
const DRAFT_KEY = `${KEY}:draft:${OP}`;
const CAP = '/api/orders/operations/edit/capabilities';
const LOOKUP = `/api/orders/operations/edit/${ORDER_ID}/${OP}`;
const PII = 'Independent Review Private Draft Sentinel';
const ORDER = {
  id: ORDER_ID, restaurant_id: 'review-s203-restaurant', order_version: 12,
  status: 'NEW', preparation_status: 'NEW', driver_id: null,
  customer_name: 'Original Review Customer', customer_phone: '0711111111',
  customer_address: 'Synthetic Review Address 12', notes: null,
  customer_latitude: null, customer_longitude: null,
};
const CHANGES = { notes: PII };
const record = (receipt = null) => ({
  actor_id: ACTOR, order_id: ORDER_ID, client_operation_id: OP,
  expected_order_version: 12, receipt,
});
const draft = () => ({
  actor_id: ACTOR, order_id: ORDER_ID, client_operation_id: OP,
  expected_order_version: 12, changes: { ...CHANGES },
});
const receipt = (state, errorCode = 'ORDER_VERSION_CONFLICT') => ({
  client_operation_id: OP, state,
  order_id: ['applied', 'replayed'].includes(state) ? ORDER_ID : null,
  order_version: ['applied', 'replayed'].includes(state) ? 13 : null,
  error_code: state === 'rejected' ? errorCode : null,
  retry_after_seconds: state === 'pending' ? 1 : null,
});
const response = (value) => ({
  status: value.state === 'pending' ? 202 : value.state === 'rejected'
    ? value.error_code === 'ORDER_NOT_FOUND' ? 404 : 409 : 200,
  data: value, headers: value.state === 'pending' ? { 'retry-after': '1' } : {},
});
const storage = () => {
  const entries = new Map();
  return {
    getItem: jest.fn((key) => entries.get(key) ?? null),
    setItem: jest.fn((key, value) => entries.set(key, value)),
    removeItem: jest.fn((key) => entries.delete(key)),
    text: () => JSON.stringify([...entries]),
  };
};
const sharedLocks = () => {
  const held = new Set();
  return { request: jest.fn(async (key, options, action) => {
    expect(options).toEqual({ ifAvailable: true });
    if (held.has(key)) return action(null);
    held.add(key);
    try { return await action({ name: key }); }
    finally { held.delete(key); }
  }) };
};
const harness = ({ durableStorage = storage(), draftStorage = storage(), locks = sharedLocks() } = {}) => {
  const api = {
    get: jest.fn(async (path) => {
      if (path === CAP) return { status: 200, data: { edit_recovery_enabled: true } };
      throw new Error('Review lookup unavailable');
    }),
    post: jest.fn(async () => { throw new Error('Review admission acknowledgement lost'); }),
  };
  const crypto = { randomUUID: jest.fn(() => OP) };
  return { api, crypto, durableStorage, draftStorage, locks,
    controller: createOrderEditingRecovery({ actorId: ACTOR, api, crypto, locks,
      durableStorage, draftStorage, wait: jest.fn(async () => {}) }),
  };
};
async function uncertainPair() {
  const durableStorage = storage(), locks = sharedLocks();
  const a = harness({ durableStorage, locks });
  await expect(a.controller.submit({ order: ORDER, changes: CHANGES }))
    .rejects.toMatchObject({ code: 'RECOVERY_UNAVAILABLE' });
  expect(a.draftStorage.getItem(DRAFT_KEY)).toContain(PII);
  expect(a.controller.savedDraft()).toEqual(draft());
  const b = harness({ durableStorage, locks });
  expect(b.draftStorage).not.toBe(a.draftStorage);
  expect(b.controller.savedDraft()).toBeNull();
  return { a, b, durableStorage };
}

describe('independent review: cached rejection integrity', () => {
  test.each([
    ['missing', undefined], ['null', null], ['empty', ''], ['unknown', 'UNKNOWN_REVIEW_CODE'],
    ['prototype method', 'toString'], ['prototype object', '__proto__'],
    ['constructor', 'constructor'], ['inherited method', 'hasOwnProperty'],
    ['padded known code', 'ORDER_VERSION_CONFLICT '], ['private string', PII],
  ])('%s cannot become terminal or release the original identity', async (_name, code) => {
    const h = harness();
    const bad = { client_operation_id: OP, state: 'rejected' };
    if (code !== undefined) bad.error_code = code;
    const rawRecord = JSON.stringify(record(bad)), rawDraft = JSON.stringify(draft());
    h.durableStorage.setItem(KEY, rawRecord);
    h.draftStorage.setItem(DRAFT_KEY, rawDraft);
    expect(() => h.controller.snapshot()).toThrow(OrderEditingError);
    await expect(h.controller.recover()).rejects.toBeInstanceOf(OrderEditingError);
    await expect(h.controller.refreshForNewAttempt()).rejects.toBeInstanceOf(OrderEditingError);
    await expect(h.controller.acknowledge()).rejects.toBeInstanceOf(OrderEditingError);
    await expect(h.controller.submit({ order: ORDER, changes: CHANGES })).rejects.toBeInstanceOf(OrderEditingError);
    expect(h.api.get).not.toHaveBeenCalled();
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    expect(h.durableStorage.getItem(KEY)).toBe(rawRecord);
    expect(h.draftStorage.getItem(DRAFT_KEY)).toBe(rawDraft);
  });

  test.each(['ORDER_VERSION_CONFLICT', 'ORDER_NOT_FOUND'])('known %s stays terminal and keeps the rejected draft', async (code) => {
    const h = harness(), value = receipt('rejected', code);
    h.durableStorage.setItem(KEY, JSON.stringify(record(value)));
    h.draftStorage.setItem(DRAFT_KEY, JSON.stringify(draft()));
    expect(h.controller.snapshot().receipt).toEqual(value);
    await expect(h.controller.recover()).resolves.toEqual(value);
    expect(h.controller.savedDraft()).toEqual(draft());
    expect(h.draftStorage.getItem(DRAFT_KEY)).toContain(PII);
    expect(h.api.get).not.toHaveBeenCalled();
    expect(h.api.post).not.toHaveBeenCalled();
  });
});

describe('independent review: originating tab draft privacy', () => {
  test.each([
    ['applied', 'snapshot'], ['applied', 'savedDraft'],
    ['replayed', 'snapshot'], ['replayed', 'savedDraft'],
  ])('%s observed through %s clears only A own PII, not durable identity', async (state, observer) => {
    const { a, b, durableStorage } = await uncertainPair();
    b.api.get.mockImplementation(async (path) => {
      expect(path).toBe(LOOKUP);
      return response(receipt('pending'));
    });
    b.api.post.mockImplementation(async (path, body) => {
      expect(path).toBe(`${LOOKUP}/resume`);
      expect(body).toBeUndefined();
      return response(receipt(state));
    });
    await expect(b.controller.recover()).resolves.toEqual(receipt(state));
    expect(b.api.post).toHaveBeenCalledTimes(1);
    expect(b.crypto.randomUUID).not.toHaveBeenCalled();
    const committedRecord = durableStorage.getItem(KEY);
    expect(JSON.parse(committedRecord)).toEqual(record(receipt(state)));
    expect(durableStorage.text()).not.toContain(PII);

    // The hook's storage listener reads these public methods; no A HTTP action.
    const observed = a.controller[observer]();
    if (observer === 'snapshot') expect(observed.receipt.state).toBe(state);
    else expect(observed).toBeNull();
    expect(a.draftStorage.getItem(DRAFT_KEY)).toBeNull();
    expect(a.controller.savedDraft()).toBeNull();
    expect(durableStorage.getItem(KEY)).toBe(committedRecord);
    expect(b.draftStorage.text()).not.toContain(PII);
    expect(a.api.post).toHaveBeenCalledTimes(1);
    await b.controller.acknowledge();
    expect(durableStorage.getItem(KEY)).toBeNull();
    const reloadedA = harness({ durableStorage, draftStorage: a.draftStorage });
    expect(reloadedA.controller.snapshot()).toBeNull();
    expect(reloadedA.draftStorage.text()).not.toContain(PII);
  });

  test.each(['pending', 'rejected'])('%s from B preserves A submitted draft and durable identity', async (state) => {
    const { a, b, durableStorage } = await uncertainPair();
    const rawDraft = a.draftStorage.getItem(DRAFT_KEY);
    const value = receipt(state);
    b.api.get.mockImplementation(async (path) => {
      expect(path).toBe(LOOKUP);
      if (state === 'rejected') throw Object.assign(new Error('Review business rejection'), { response: response(value) });
      return response(value);
    });
    b.api.post.mockResolvedValue(response(value));
    await expect(b.controller.recover()).resolves.toEqual(value);
    const rawRecord = durableStorage.getItem(KEY);
    expect(a.controller.snapshot().receipt).toEqual(value);
    expect(a.controller.savedDraft()).toEqual(draft());
    expect(a.draftStorage.getItem(DRAFT_KEY)).toBe(rawDraft);
    expect(durableStorage.getItem(KEY)).toBe(rawRecord);
    expect(durableStorage.text()).not.toContain(PII);
    expect(b.draftStorage.getItem(DRAFT_KEY)).toBeNull();
    expect(b.crypto.randomUUID).not.toHaveBeenCalled();
    expect(a.api.post).toHaveBeenCalledTimes(1);
  });

  test.each([
    ['applied', 'newValue'], ['applied', 'oldValue'],
    ['replayed', 'newValue'], ['replayed', 'oldValue'],
  ])('%s queued in %s clears A after B already acknowledged, then stays clear on reload', async (state, proofField) => {
    const { a, b, durableStorage } = await uncertainPair();
    const uncertainRecord = durableStorage.getItem(KEY);
    b.api.get.mockResolvedValue(response(receipt('pending')));
    b.api.post.mockResolvedValue(response(receipt(state)));
    await expect(b.controller.recover()).resolves.toEqual(receipt(state));
    const successRecord = durableStorage.getItem(KEY);
    await b.controller.acknowledge();
    expect(durableStorage.getItem(KEY)).toBeNull();

    // No terminal read/event has reached A before B removed the shared metadata.
    expect(a.controller.snapshot()).toBeNull();
    expect(a.draftStorage.getItem(DRAFT_KEY)).toContain(PII);
    const event = proofField === 'newValue'
      ? { key: KEY, oldValue: uncertainRecord, newValue: successRecord }
      : { key: KEY, oldValue: successRecord, newValue: null };
    a.controller.observeStorage(event);
    expect(a.controller.snapshot()).toBeNull();
    expect(a.controller.savedDraft()).toBeNull();
    expect(a.draftStorage.getItem(DRAFT_KEY)).toBeNull();
    expect(durableStorage.getItem(KEY)).toBeNull();
    expect(a.api.post).toHaveBeenCalledTimes(1);
    expect(b.api.post).toHaveBeenCalledTimes(1);
    expect(b.crypto.randomUUID).not.toHaveBeenCalled();

    // Reappearance of the old nonterminal identity must not reveal a memory copy.
    durableStorage.setItem(KEY, uncertainRecord);
    expect(a.controller.savedDraft()).toBeNull();
    durableStorage.removeItem(KEY);
    const reloadedA = harness({ durableStorage, draftStorage: a.draftStorage });
    expect(reloadedA.controller.snapshot()).toBeNull();
    expect(reloadedA.draftStorage.text()).not.toContain(PII);
  });

  test.each([null, 'pending', 'rejected'])('missing identity with %s old receipt is not success proof and retains A draft on reload', async (state) => {
    const { a, durableStorage } = await uncertainPair();
    const rawDraft = a.draftStorage.getItem(DRAFT_KEY);
    const oldValue = JSON.stringify(record(state ? receipt(state) : null));
    durableStorage.removeItem(KEY);
    a.controller.observeStorage({ key: KEY, oldValue, newValue: null });
    expect(a.controller.snapshot()).toBeNull();
    expect(a.draftStorage.getItem(DRAFT_KEY)).toBe(rawDraft);
    const reloadedA = harness({ durableStorage, draftStorage: a.draftStorage });
    expect(reloadedA.controller.snapshot()).toBeNull();
    expect(reloadedA.draftStorage.getItem(DRAFT_KEY)).toBe(rawDraft);
    durableStorage.setItem(KEY, oldValue);
    expect(a.controller.savedDraft()).toEqual(draft());
    expect(reloadedA.controller.savedDraft()).toEqual(draft());
  });

  test.each(['newValue', 'oldValue'])('invalid terminal proof in %s cannot erase A draft after metadata removal', async (proofField) => {
    const { a, durableStorage } = await uncertainPair();
    const rawDraft = a.draftStorage.getItem(DRAFT_KEY);
    const invalid = JSON.stringify(record({ ...receipt('applied'), order_version: 99 }));
    durableStorage.removeItem(KEY);
    const event = { key: KEY, oldValue: null, newValue: null, [proofField]: invalid };
    expect(() => a.controller.observeStorage(event)).toThrow(OrderEditingError);
    expect(a.controller.storageBlocked()).toBe(true);
    expect(a.draftStorage.getItem(DRAFT_KEY)).toBe(rawDraft);
    expect(durableStorage.getItem(KEY)).toBeNull();
    expect(a.api.post).toHaveBeenCalledTimes(1);
  });
});
