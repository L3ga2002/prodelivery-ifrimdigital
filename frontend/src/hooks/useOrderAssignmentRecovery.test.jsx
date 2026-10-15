import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { useOrderAssignmentRecovery } from './useOrderAssignmentRecovery';

jest.mock('axios', () => ({ create: jest.fn() }));
const ID = '123e4567-e89b-42d3-a456-426614174000';
const KEY = 'prodelivery:order-assign:v1:admin';
const record = { actor_id: 'admin', order_id: 'order', client_operation_id: ID, expected_order_version: 4, driver_id: 'driver', receipt: null };
const command = { order: { id: 'order', restaurant_id: 'restaurant', order_version: 4, status: 'NEW', customer_name: 'Private Sentinel' },
  driverId: 'driver', driver: { id: 'driver', is_active: true, driver_status: 'active', operational_status: 'active' } };
const done = { status: 200, data: { client_operation_id: ID, state: 'applied', order_id: 'order', order_version: 5 } };
const pending = { status: 202, headers: { 'retry-after': '1' }, data: { client_operation_id: ID, state: 'pending', retry_after_seconds: 1 } };
let root, container, result, transport;
function Harness({ actor = 'admin', token = 'token-a', online = true }) {
  result = useOrderAssignmentRecovery(actor, 'https://qa.invalid', online, token); return null;
}
const render = (props = {}) => act(async () => root.render(<StrictMode><Harness {...props} /></StrictMode>));
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear(); jest.clearAllMocks();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_k, _o, cb) => cb({}) } });
  Object.defineProperty(window, 'crypto', { configurable: true, value: { randomUUID: jest.fn(() => ID) } });
  transport = { get: jest.fn(async (path) => path.endsWith('/api/auth/me') ? { status: 200, data: { id: 'admin', role: 'admin' } } :
    { status: 200, data: { assign_recovery_enabled: true } }), post: jest.fn(async () => done), put: jest.fn(async () => ({ status: 200 })) };
  axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); await Promise.resolve(); container.remove(); });

test('isolated bearer snapshot, same intent, no customer/sessionStorage payload', async () => {
  await render(); expect(result.capability).toEqual({ ready: true, enabled: true });
  await act(async () => result.submit(command));
  expect(axios.create).toHaveBeenCalledWith({ withCredentials: true });
  expect(transport.post.mock.calls[0]).toEqual(['https://qa.invalid/api/orders/operations/assign/order',
    { client_operation_id: ID, expected_order_version: 4, driver_id: 'driver' }, { timeout: 15000, headers: { Authorization: 'Bearer token-a', 'X-Expected-Actor-ID': 'admin' } }]);
  expect(transport.get.mock.calls[0][1].headers['X-Expected-Actor-ID']).toBe('admin');
  expect(localStorage.getItem(KEY)).not.toContain('Private'); expect(sessionStorage.length).toBe(0);
});
test('reload immediately surfaces pending, auto lookup/bodyless resume even when disabled', async () => {
  localStorage.setItem(KEY, JSON.stringify(record));
  transport.get.mockImplementation(async (path) => path.endsWith('capabilities') ? { status: 200, data: { assign_recovery_enabled: false } } : pending);
  await render(); expect(result.record.receipt.state).toBe('applied'); expect(result.capability.enabled).toBe(false);
  expect(transport.post.mock.calls[0]).toEqual([`https://qa.invalid/api/orders/operations/assign/order/${ID}/resume`, undefined,
    { timeout: 15000, headers: { Authorization: 'Bearer token-a', 'X-Expected-Actor-ID': 'admin' } }]);
  expect(transport.get.mock.calls.find(([path]) => path.endsWith(`/${ID}`))[1].headers['X-Expected-Actor-ID']).toBe('admin');
});
test('pre-admission metadata survives same-actor token rotation; retired receipt cannot overwrite recovery', async () => {
  let release; transport.post.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
  await render(); let flight;
  await act(async () => { flight = result.submit(command); await Promise.resolve(); });
  const retired = transport;
  transport = { get: jest.fn(async (path) => {
    if (path.endsWith('capabilities')) return { status: 200, data: { assign_recovery_enabled: false } };
    throw { response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } };
  }), post: jest.fn(async () => ({ ...done, data: { ...done.data, state: 'replayed' } })), put: jest.fn() };
  axios.create.mockReturnValue(transport); await render({ token: 'rotated-token' });
  expect(result.record.receipt.state).toBe('replayed');
  expect(transport.post.mock.calls[0][1]).toEqual({ client_operation_id: ID, expected_order_version: 4, driver_id: 'driver' });
  expect(transport.post.mock.calls[0][2].headers.Authorization).toBe('Bearer rotated-token');
  expect(transport.post.mock.calls[0][2].headers['X-Expected-Actor-ID']).toBe('admin');
  await act(async () => { release(done); await flight; });
  expect(JSON.parse(localStorage.getItem(KEY)).receipt.state).toBe('replayed'); expect(retired.post).toHaveBeenCalledTimes(1);
});
test('actor switch cannot adopt previous pending result or late POST', async () => {
  let release; transport.post.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
  await render(); let flight;
  await act(async () => { flight = result.submit(command); await Promise.resolve(); });
  const old = transport;
  transport = { get: jest.fn(async () => ({ status: 200, data: { assign_recovery_enabled: true } })), post: jest.fn(), put: jest.fn() };
  axios.create.mockReturnValue(transport); await render({ actor: 'other' });
  expect(result.record).toBeNull(); await act(async () => { release(done); await flight; });
  expect(JSON.parse(localStorage.getItem(KEY)).receipt).toBeNull(); expect(transport.post).not.toHaveBeenCalled(); expect(old.post).toHaveBeenCalledTimes(1);
});
test('logout/unmount fence late writes without deleting durable identity', async () => {
  let release; transport.post.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
  await render(); let flight;
  await act(async () => { flight = result.submit(command); await Promise.resolve(); });
  await act(async () => root.unmount()); await Promise.resolve(); release(done); await flight;
  expect(JSON.parse(localStorage.getItem(KEY)).receipt).toBeNull(); expect(sessionStorage.length).toBe(0);
});
test.each([401, 403])('HTTP%s never invokes shared refresh or auth replay', async (status) => {
  transport.post.mockRejectedValue({ response: { status } }); await render(); await act(async () => result.submit(command));
  expect(transport.post).toHaveBeenCalledTimes(1); expect(result.record.receipt).toBeNull();
  expect(result.errorCode).toBe(status === 401 ? 'AUTH_REQUIRED' : 'NOT_AUTHORIZED');
});
test('offline reload reveals pending without network, then explicit online recovery', async () => {
  localStorage.setItem(KEY, JSON.stringify(record)); await render({ online: false });
  expect(result.record.client_operation_id).toBe(ID); expect(transport.get).not.toHaveBeenCalled();
  await act(async () => result.recover()); expect(transport.post).not.toHaveBeenCalled(); expect(result.errorCode).toBe('OFFLINE');
  transport.get.mockImplementation(async (path) => path.endsWith('capabilities') ? { status: 200, data: { assign_recovery_enabled: false } } : done);
  await render({ online: true }); await act(async () => result.recover()); expect(result.record.receipt.state).toBe('applied');
});
test('another-tab storage event surfaces intent and freezes legacy', async () => {
  await render(); localStorage.setItem(KEY, JSON.stringify(record));
  await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: JSON.stringify(record) })));
  expect(result.record.driver_id).toBe('driver'); const legacy = { ...command.order }; delete legacy.order_version;
  await act(async () => result.submitLegacy({ ...command, order: legacy })); expect(transport.put).not.toHaveBeenCalled();
  expect(result.errorCode).toBe('INTENT_PENDING');
});
test('missing Web Locks is visible and never sends legacy or recoverable requests', async () => {
  Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined }); await render();
  expect(result.available).toBe(false); await act(async () => result.submit(command)); expect(result.errorCode).toBe('LOCK_UNAVAILABLE');
  expect(transport.post).not.toHaveBeenCalled();
});
test('corrupt metadata is retained, visible and cannot acknowledge', async () => {
  localStorage.setItem(KEY, '{corrupt'); await render(); expect(result.storageInvalid).toBe(true);
  await act(async () => result.acknowledge()); expect(localStorage.getItem(KEY)).toBe('{corrupt'); expect(transport.post).not.toHaveBeenCalled();
});
test('latest capability probe wins when an older enabled response arrives late', async () => {
  await render(); let release;
  transport.get.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; })).mockResolvedValue({ status: 200, data: { assign_recovery_enabled: false } });
  let old; await act(async () => { old = result.verifyCapability(); await Promise.resolve(); });
  await act(async () => result.verifyCapability()); expect(result.capability.enabled).toBe(false);
  await act(async () => { release({ status: 200, data: { assign_recovery_enabled: true } }); await old; }); expect(result.capability.enabled).toBe(false);
});
test.each([{}, [], null, '', ' ', ' admin', 'admin ', 'a'.repeat(121), 'ad\u0000min', 'ad\u007fmin', 'ad\ud800min'])('malformed actor %j creates no transport', async (actor) => {
  await render({ actor }); await act(async () => result.submit(command));
  expect(result.available).toBe(false); expect(axios.create).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test.each([{}, [], '', ' ', ' token', 'token ', 'token\n', 'a'.repeat(16385), 'token\u0100', 'token\ud800'])('malformed token %j creates no transport', async (token) => {
  await render({ token }); await act(async () => result.submit(command));
  expect(result.available).toBe(false); expect(axios.create).not.toHaveBeenCalled(); expect(transport.post).not.toHaveBeenCalled();
});
test.each(['token-a', null])('server owner guard refuses shared-cookie substitution for bearer/cookie-only token %j', async (token) => {
  let cookieActor = 'admin';
  const guard = (options) => {
    if (options.headers['X-Expected-Actor-ID'] !== cookieActor) throw { response: { status: 403, data: { detail: { code: 'AUTH_CONTEXT_CHANGED' } } } };
  };
  transport.get.mockImplementation(async (path, options) => {
    guard(options);
    if (path.endsWith('capabilities')) return { status: 200, data: { assign_recovery_enabled: true } };
    return pending;
  });
  transport.post.mockImplementation(async (path, _body, options) => { guard(options); return path.endsWith('/resume') ? done : pending; });
  await render({ token }); cookieActor = 'other-admin';
  await act(async () => result.submit(command)); expect(transport.post).not.toHaveBeenCalled(); expect(localStorage.getItem(KEY)).toBeNull();
  cookieActor = 'admin'; await act(async () => result.verifyCapability());
  transport.post.mockImplementationOnce(async (_path, _body, options) => { cookieActor = 'other-admin'; guard(options); return done; });
  await act(async () => result.submit(command)); expect(result.record.receipt).toBeNull(); expect(result.errorCode).toBe('SESSION_CHANGED');
  await act(async () => result.recover()); expect(transport.post).toHaveBeenCalledTimes(1); expect(transport.put).not.toHaveBeenCalled();
  expect(JSON.parse(localStorage.getItem(KEY)).actor_id).toBe('admin'); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1);
  cookieActor = 'admin'; await act(async () => result.recover()); expect(result.record.receipt.state).toBe('applied');
  for (const [, options] of transport.get.mock.calls) expect(options.headers['X-Expected-Actor-ID']).toBe('admin');
  for (const [, , options] of transport.post.mock.calls) expect(options.headers['X-Expected-Actor-ID']).toBe('admin');
});
test('legacy actor preflight and guarded PUT both retain the expected actor, including a cookie race after the read', async () => {
  const legacy = { ...command.order }; delete legacy.order_version;
  let cookieActor = 'admin'; await render();
  transport.get.mockImplementation(async (path, options) => {
    expect(options.headers['X-Expected-Actor-ID']).toBe('admin');
    if (path.endsWith('/api/auth/me')) { cookieActor = 'other-admin'; return { status: 200, data: { id: 'admin', role: 'admin' } }; }
    return { status: 200, data: { assign_recovery_enabled: true } };
  });
  transport.put.mockImplementation(async (_path, _body, options) => {
    expect(options.headers['X-Expected-Actor-ID']).toBe('admin');
    if (cookieActor !== options.headers['X-Expected-Actor-ID']) throw { response: { status: 403, data: { detail: { code: 'AUTH_CONTEXT_CHANGED' } } } };
    return { status: 200 };
  });
  await act(async () => result.submitLegacy({ ...command, order: legacy }));
  expect(transport.get.mock.calls.some(([path]) => path.endsWith('/api/auth/me'))).toBe(true); expect(transport.put).toHaveBeenCalledTimes(1);
  expect(result.errorCode).toBe('SESSION_CHANGED'); expect(transport.post).not.toHaveBeenCalled(); expect(localStorage.getItem(KEY)).toBeNull();
  expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
