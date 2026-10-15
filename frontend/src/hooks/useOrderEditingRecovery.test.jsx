/** @jest-environment jsdom */
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { useOrderEditingRecovery } from './useOrderEditingRecovery';

jest.mock('axios', () => ({ create: jest.fn() }));
const ID = '123e4567-e89b-42d3-a456-426614174000';
const KEY = 'prodelivery:order-edit:v1:admin';
const record = { actor_id: 'admin', order_id: 'qa-order', client_operation_id: ID, expected_order_version: 4, receipt: null };
const order = { id: 'qa-order', restaurant_id: 'qa-restaurant', order_version: 4, status: 'NEW', customer_name: 'Old Name' };
const done = { status: 200, data: { state: 'applied', order_id: 'qa-order', order_version: 5, client_operation_id: ID } };
const pending = { status: 202, headers: { 'retry-after': '1' }, data: { state: 'pending', client_operation_id: ID, retry_after_seconds: 1 } };
let container, root, result, transport;
function Harness({ actor = 'admin', token = 'token-a', online = true }) { result = useOrderEditingRecovery(actor, 'https://qa.invalid', online, token); return null; }
const render = async (props = {}) => act(async () => root.render(<StrictMode><Harness {...props} /></StrictMode>));
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear(); jest.clearAllMocks();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_key, _opts, cb) => cb({}) } });
  Object.defineProperty(window, 'crypto', { configurable: true, value: { randomUUID: () => ID } });
  transport = { get: jest.fn(async () => ({ status: 200, data: { edit_recovery_enabled: true } })), post: jest.fn(async () => done) };
  axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); await Promise.resolve(); container.remove(); });
test('isolated transport, separate capability, bearer snapshot and 15s timeout', async () => {
  await render(); expect(result.capability).toEqual({ ready: true, enabled: true });
  await act(async () => result.submit({ order, changes: { customer_name: 'New Private Name' } }));
  expect(axios.create).toHaveBeenCalledWith({ withCredentials: true });
  expect(transport.get.mock.calls[0][0]).toBe('https://qa.invalid/api/orders/operations/edit/capabilities');
  expect(transport.post.mock.calls[0][2]).toEqual({ timeout: 15000, headers: { Authorization: 'Bearer token-a' } });
  expect(localStorage.getItem(KEY)).not.toContain('Private');
});
test('reload lookup -> bodyless resume independent of capability false', async () => {
  localStorage.setItem(KEY, JSON.stringify(record));
  transport.get.mockImplementation(async (path) => path.endsWith('capabilities') ? { status: 200, data: { edit_recovery_enabled: false } } : pending);
  await render(); expect(result.record.receipt.state).toBe('applied');
  expect(result.capability.enabled).toBe(false);
  expect(transport.post.mock.calls[0]).toEqual([`https://qa.invalid/api/orders/operations/edit/qa-order/${ID}/resume`, undefined, { timeout: 15000, headers: { Authorization: 'Bearer token-a' } }]);
});
test.each([{ actor: 'other', token: 'token-a' }, { actor: 'admin', token: 'token-b' }])('late submit blocked after session switch %j; no auth retry', async (next) => {
  let release;
  transport.post.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
  await render(); let flight;
  await act(async () => { flight = result.submit({ order, changes: { customer_name: 'Secret Draft' } }); await Promise.resolve(); });
  const oldTransport = transport;
  transport = { get: jest.fn(async () => { throw new Error('offline'); }), post: jest.fn() }; axios.create.mockReturnValue(transport);
  await render(next);
  if (next.actor === 'admin') {
    expect(sessionStorage.length).toBe(1);
    expect(result.draft.changes).toEqual({ customer_name: 'Secret Draft' });
  } else {
    expect(sessionStorage.length).toBe(0); expect(result.draft).toBeFalsy();
  }
  await act(async () => { release(done); await flight; });
  expect(JSON.parse(localStorage.getItem(KEY)).receipt).toBeNull();
  expect(oldTransport.post).toHaveBeenCalledTimes(1); expect(transport.post).not.toHaveBeenCalled();
});
test('same-actor token rotation transfers exact pre-admission draft; old outcome cannot overwrite recovery', async () => {
  let release;
  transport.post.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
  await render(); let flight;
  await act(async () => { flight = result.submit({ order, changes: { customer_name: 'Secret Immutable Draft' } }); await Promise.resolve(); });
  const retired = transport;
  const missing = { response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } };
  transport = { get: jest.fn(async (path) => {
    if (path.endsWith('capabilities')) return { status: 200, data: { edit_recovery_enabled: false } };
    throw missing;
  }), post: jest.fn(async () => ({ ...done, data: { ...done.data, state: 'replayed' } })) };
  axios.create.mockReturnValue(transport);
  await render({ actor: 'admin', token: 'rotated-token' });
  expect(transport.get.mock.calls.some(([path]) => path.endsWith(`/qa-order/${ID}`))).toBe(true);
  expect(transport.post.mock.calls[0]).toEqual(['https://qa.invalid/api/orders/operations/edit/qa-order',
    { client_operation_id: ID, expected_order_version: 4, changes: { customer_name: 'Secret Immutable Draft' } },
    { timeout: 15000, headers: { Authorization: 'Bearer rotated-token' } }]);
  expect(result.record.receipt.state).toBe('replayed'); expect(result.capability.enabled).toBe(false);
  await act(async () => { release(done); await flight; });
  expect(JSON.parse(localStorage.getItem(KEY)).receipt.state).toBe('replayed');
  expect(retired.post).toHaveBeenCalledTimes(1); expect(sessionStorage.length).toBe(0);
});
test('unmount clears customer draft only; late response cannot write', async () => {
  let release; transport.post.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
  await render(); let flight;
  await act(async () => { flight = result.submit({ order, changes: { customer_name: 'Secret Draft' } }); await Promise.resolve(); });
  await act(async () => root.unmount()); await Promise.resolve();
  expect(sessionStorage.length).toBe(0); release(done); await flight;
  expect(JSON.parse(localStorage.getItem(KEY)).receipt).toBeNull();
});
test('storage changes reveal another-tab intent and prevent new submit', async () => {
  await render(); localStorage.setItem(KEY, JSON.stringify(record));
  await act(async () => window.dispatchEvent(new Event('storage')));
  expect(result.record.client_operation_id).toBe(ID);
  await act(async () => result.submit({ order, changes: { customer_name: 'Duplicate' } }));
  expect(transport.post).not.toHaveBeenCalled(); expect(result.error).toContain('operatia existenta');
});
test('storage failure remains visibly fail-closed after successful metadata read', async () => {
  await render();
  const original = Storage.prototype.setItem;
  const spy = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (key, value) {
    if (key === KEY) throw new Error('durable storage denied');
    return original.call(this, key, value);
  });
  try {
    await act(async () => result.submit({ order, changes: { customer_name: 'Secret Draft' } }));
    expect(result.storageInvalid).toBe(true); expect(result.record).toBeNull(); expect(sessionStorage.length).toBe(0);
    expect(transport.post).not.toHaveBeenCalled();
  } finally { spy.mockRestore(); }
});
test.each(['applied', 'replayed'])('real storage event observes %s and purges originating-tab payload', async (state) => {
  transport.post.mockRejectedValue(new Error('lost ACK'));
  transport.get.mockImplementation(async (path) => {
    if (path.endsWith('capabilities')) return { status: 200, data: { edit_recovery_enabled: true } };
    throw new Error('lookup unavailable');
  });
  await render();
  await act(async () => result.submit({ order, changes: { customer_name: 'Private Origin Draft' } }));
  expect(sessionStorage.length).toBe(1);
  const oldValue = localStorage.getItem(KEY), newValue = JSON.stringify({ ...record, receipt: { ...done.data, state } });
  localStorage.setItem(KEY, newValue);
  await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: KEY, oldValue, newValue, storageArea: localStorage })));
  expect(result.record.receipt.state).toBe(state); expect(result.draft).toBeNull(); expect(sessionStorage.length).toBe(0);
  expect(localStorage.getItem(KEY)).toBe(newValue);
});
test('queued acknowledgement storage event cleans draft even when current metadata is gone', async () => {
  transport.post.mockRejectedValue(new Error('lost ACK'));
  transport.get.mockImplementation(async (path) => {
    if (path.endsWith('capabilities')) return { status: 200, data: { edit_recovery_enabled: true } };
    throw new Error('lookup unavailable');
  });
  await render(); await act(async () => result.submit({ order, changes: { customer_name: 'Private Origin Draft' } }));
  expect(sessionStorage.length).toBe(1);
  const terminal = JSON.stringify({ ...record, receipt: done.data });
  localStorage.removeItem(KEY);
  await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: KEY, oldValue: terminal, newValue: null, storageArea: localStorage })));
  expect(result.record).toBeNull(); expect(result.draft).toBeNull(); expect(sessionStorage.length).toBe(0);
});

describe('final independent malformed actor auth guard QA', () => {
  const malformedActors = [
    ['object', { id: 'admin' }],
    ['array', ['admin']],
    ['null', null],
    ['undefined', undefined],
    ['empty', ''],
    ['blank', '   '],
    ['overlong', 'a'.repeat(121)],
    ['leading padding', ' admin'],
    ['trailing padding', 'admin '],
    ['C0 NUL', 'ad\u0000min'],
    ['C0 tab', 'ad\u0009min'],
    ['C0 unit separator', 'ad\u001fmin'],
    ['DEL', 'ad\u007fmin'],
  ];
  let guardedResult, randomUUID;
  // The existing Harness defaults undefined to admin; forward it unchanged here.
  function AuthGuardHarness({ actorId }) {
    guardedResult = useOrderEditingRecovery(actorId, 'https://qa.invalid', true, 'token-a');
    return null;
  }
  const renderActor = (actorId) => act(async () => {
    root.render(<StrictMode><AuthGuardHarness actorId={actorId} /></StrictMode>);
  });
  beforeEach(() => {
    guardedResult = undefined;
    randomUUID = jest.fn(() => ID);
    Object.defineProperty(window, 'crypto', { configurable: true, value: { randomUUID } });
  });
  const assertBlockedActions = async () => {
    expect(guardedResult.capability).toEqual({ ready: false, enabled: false });
    await act(async () => {
      expect(await guardedResult.submit({ order, changes: { customer_name: 'Blocked Draft' } })).toBeNull();
      expect(await guardedResult.recover()).toBeNull();
      expect(await guardedResult.refreshForNewAttempt()).toBeNull();
      expect(await guardedResult.acknowledge()).toBeNull();
      await guardedResult.verifyCapability();
      window.dispatchEvent(new Event('storage'));
    });
    expect(guardedResult.capability).toEqual({ ready: false, enabled: false });
    expect(axios.create).not.toHaveBeenCalled();
    expect(transport.get).not.toHaveBeenCalled();
    expect(transport.post).not.toHaveBeenCalled();
    expect(randomUUID).not.toHaveBeenCalled();
    expect(guardedResult.record).toBeFalsy();
    expect(guardedResult.draft).toBeFalsy();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  };
  test.each(malformedActors)('mount %s: no React crash, transport, HTTP or operation ID', async (_label, actorId) => {
    await expect(renderActor(actorId)).resolves.toBeUndefined();
    await assertBlockedActions();
  });
  test.each(malformedActors)('valid session -> %s: capability fails closed without new transport, HTTP or ID', async (_label, actorId) => {
    await renderActor('admin');
    expect(guardedResult.capability).toEqual({ ready: true, enabled: true });
    expect(axios.create).toHaveBeenCalled();
    expect(transport.get).toHaveBeenCalled();
    jest.clearAllMocks();
    await expect(renderActor(actorId)).resolves.toBeUndefined();
    await assertBlockedActions();
  });
});
