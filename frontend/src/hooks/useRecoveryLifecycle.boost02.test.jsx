import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { useOrderCreationRecovery } from './useOrderCreationRecovery';
import { useOrderEditingRecovery } from './useOrderEditingRecovery';
import { useOrderAssignmentRecovery } from './useOrderAssignmentRecovery';
import { useOrderStatusRecovery } from './useOrderStatusRecovery';
jest.mock('axios', () => ({ create: jest.fn() }));
const ID = '123e4567-e89b-42d3-a456-426614174000';
const order = { id: 'order', restaurant_id: 'restaurant', order_version: 4, status: 'NEW', customer_name: 'Test Client', customer_phone: '0700000000', customer_address: 'Synthetic address', total_amount: 26 };
const create = { restaurant_id: 'restaurant', customer_name: 'Test Client', customer_phone: '0700000000', customer_address: 'Synthetic address', total_amount: 26, notes: 'Exact private draft' };
const commands = { create, edit: { order, changes: { notes: 'Exact private draft' } }, assign: { order, driverId: 'driver', driver: { id: 'driver', is_active: true, driver_status: 'active', operational_status: 'active' } } };
const keys = (kind) => `prodelivery:order-${kind}:v1:admin`;
const receipt = (kind) => ({ status: kind === 'create' ? 201 : 200, data: { client_operation_id: ID, state: 'applied', order_id: 'order', order_version: kind === 'create' ? 0 : 5 } });
let root, container, result, transport;
const wrappers = {
 create: (online) => useOrderCreationRecovery('admin', 'https://qa.invalid', online, null),
 edit: (online) => useOrderEditingRecovery('admin', 'https://qa.invalid', online, null),
 assign: (online) => useOrderAssignmentRecovery('admin', 'https://qa.invalid', online, null),
};
function Harness({ kind, online = true }) { result = wrappers[kind](online); return null; }
const render = (kind, props = {}) => act(async () => root.render(<StrictMode><Harness kind={kind} {...props} /></StrictMode>));
const transition = (name, persisted = true) => act(async () => { const e = new Event(name); Object.defineProperty(e, 'persisted', { value: persisted }); window.dispatchEvent(e); });
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const finite = async (promise) => { let timer; try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('finite barrier timed out')), 1000); })]); } finally { clearTimeout(timer); } };
beforeEach(() => {
 globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear(); jest.clearAllMocks();
 Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_k, _o, cb) => cb({}) } });
 Object.defineProperty(window, 'crypto', { configurable: true, value: { randomUUID: jest.fn(() => ID) } });
 transport = { get: jest.fn(async (path) => path.endsWith('/api/auth/me') ? { status: 200, data: { id: 'admin', role: 'admin' } } : { status: 200, data: { create_recovery_enabled: true, edit_recovery_enabled: true, assign_recovery_enabled: true, status_recovery_enabled: true } }), post: jest.fn(), put: jest.fn() };
 axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); await Promise.resolve(); container.remove(); });

describe.each(['create', 'edit', 'assign'])('%s persisted lifecycle', (kind) => {
 test('foreign cookie actor cannot acknowledge a terminal identity', async () => {
  transport.post.mockResolvedValue(receipt(kind)); await render(kind); await act(async () => result.submit(commands[kind]));
  const raw = localStorage.getItem(keys(kind)); expect(raw).not.toBeNull(); transport.get.mockResolvedValue({ status: 200, data: { id: 'foreign', role: 'admin' } });
  await transition('pagehide'); await transition('pageshow'); await act(async () => result.acknowledge());
  expect(localStorage.getItem(keys(kind))).toBe(raw); expect(result.sessionSuspended).toBe(true);
  expect(transport.get.mock.calls.filter(([p]) => p.endsWith('/api/auth/me'))).toHaveLength(1);
 });
 test('delayed revalidation gates ACK and deduplicates repeated pageshow', async () => {
  transport.post.mockResolvedValue(receipt(kind)); await render(kind); await act(async () => result.submit(commands[kind]));
  const raw = localStorage.getItem(keys(kind)); const auth = deferred(); transport.get.mockImplementation((p) => p.endsWith('/api/auth/me') ? auth.promise : Promise.resolve({ status: 200, data: { create_recovery_enabled: true, edit_recovery_enabled: true, assign_recovery_enabled: true } }));
  await transition('pagehide'); await transition('pageshow'); await transition('pageshow'); await act(async () => result.acknowledge());
  expect(localStorage.getItem(keys(kind))).toBe(raw); expect(result.checkingSession).toBe(true);
  await act(async () => auth.resolve({ status: 200, data: { id: 'admin', role: 'admin' } }));
  expect(result.sessionSuspended).toBe(false); await act(async () => result.acknowledge()); expect(localStorage.getItem(keys(kind))).toBeNull();
 });
 test('POST from before suspension stays fenced AFTER matching actor restores', async () => {
  const old = deferred(), started = deferred(); transport.post.mockImplementation(() => { started.resolve(); return old.promise; }); await render(kind); let flight;
  await act(async () => { flight = result.submit(commands[kind]); await finite(started.promise); });
  const raw = localStorage.getItem(keys(kind)), drafts = { ...sessionStorage }; expect(JSON.parse(raw).receipt).toBeNull();
  await transition('pagehide'); await transition('pageshow');
  await act(async () => { old.resolve(receipt(kind)); expect(await flight).toBeNull(); });
  expect(localStorage.getItem(keys(kind))).toBe(raw); expect({ ...sessionStorage }).toEqual(drafts); expect(result.record.receipt).toBeNull(); expect(transport.post).toHaveBeenCalledTimes(1);
 });
});

describe.each(['admin', 'restaurant'])('eligible %s cancellation BFCache', (role) => {
 test('exact reason survives; old POST fenced; pre-admission retry uses same UUID/body', async () => {
  const actor = { id: 'admin', role, ...(role === 'restaurant' ? { restaurant_id: 'restaurant' } : {}) };
  function CancelHarness() { result = useOrderStatusRecovery(actor, 'https://qa.invalid', true, null, false); return null; }
  transport.get.mockImplementation(async (p) => p.endsWith('/api/auth/me') ? { status: 200, data: actor } : { status: 200, data: { status_recovery_enabled: true } });
  const old = deferred(), started = deferred(); transport.post.mockImplementationOnce(() => { started.resolve(); return old.promise; }).mockResolvedValue(receipt('status'));
  await act(async () => root.render(<StrictMode><CancelHarness /></StrictMode>)); let flight;
  await act(async () => { flight = result.submit({ order, status: 'CANCELLED', cancellationReason: 'Exact private reason' }); await finite(started.promise); });
  const key = 'prodelivery:order-status:v1:admin', raw = localStorage.getItem(key), draft = sessionStorage.getItem(`${key}:draft:${ID}`);
  expect(draft).toContain('Exact private reason'); expect(raw).not.toContain('private'); await transition('pagehide'); await transition('pageshow');
  await act(async () => { old.resolve(receipt('status')); expect(await flight).toBeNull(); }); expect(localStorage.getItem(key)).toBe(raw); expect(sessionStorage.getItem(`${key}:draft:${ID}`)).toBe(draft);
  transport.get.mockRejectedValue({ response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } });
  await act(async () => result.recover()); expect(transport.post).toHaveBeenCalledTimes(2); expect(transport.post.mock.calls[1][1]).toEqual(transport.post.mock.calls[0][1]); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1); expect(sessionStorage.length).toBe(0);
 });
});


describe.each(['create', 'edit', 'assign'])('%s return failure boundaries', (kind) => {
 const terminal = async () => { transport.post.mockResolvedValue(receipt(kind)); await render(kind); await act(async () => result.submit(commands[kind])); return localStorage.getItem(keys(kind)); };
 test.each([[401, 'ERR_BAD_REQUEST', 'AUTH_REQUIRED'], [403, 'ERR_BAD_REQUEST', 'SESSION_CHANGED'], [503, 'ERR_BAD_RESPONSE', 'RECOVERY_UNAVAILABLE'], [null, 'ECONNABORTED', 'RECOVERY_UNAVAILABLE']])('Axios %s/%s preserves identity and maps domain error', async (status, code, expected) => {
  const raw = await terminal(); transport.get.mockRejectedValue({ code, response: status ? { status } : undefined });
  await transition('pagehide'); await transition('pageshow'); expect(result.sessionSuspended).toBe(true); expect(result.errorCode).toBe(expected); expect(result.storageInvalid).toBe(false);
  await act(async () => { await result.acknowledge(); await result.recover(); await result.submit(commands[kind]); }); expect(localStorage.getItem(keys(kind))).toBe(raw); expect(transport.post).toHaveBeenCalledTimes(1);
 });
 test.each([null, { id: 'admin', role: 'driver' }, { id: 'admin', role: 'admin', is_disabled: true }, { id: 'admin', role: 'admin', account_disabled: null }])('malformed/disabled actor %j stays blocked', async (actual) => {
  const raw = await terminal(); transport.get.mockResolvedValue({ status: 200, data: actual }); await transition('pagehide'); await transition('pageshow');
  expect(result.errorCode).toBe('SESSION_CHANGED'); expect(result.sessionSuspended).toBe(true); await act(async () => result.acknowledge()); expect(localStorage.getItem(keys(kind))).toBe(raw);
 });
 test('internal15sec deadline cannot be undone by late auth transport success', async () => {
  const raw = await terminal(), auth = deferred(); transport.get.mockReturnValue(auth.promise); jest.useFakeTimers();
  try {
   await transition('pagehide'); await transition('pageshow'); expect(result.checkingSession).toBe(true);
   await act(async () => { jest.advanceTimersByTime(15000); await Promise.resolve(); }); expect(result.checkingSession).toBe(false); expect(result.sessionSuspended).toBe(true); expect(result.errorCode).toBe('RECOVERY_UNAVAILABLE');
   await act(async () => auth.resolve({ status: 200, data: { id: 'admin', role: 'admin' } })); await act(async () => result.acknowledge()); expect(localStorage.getItem(keys(kind))).toBe(raw); expect(result.sessionSuspended).toBe(true);
  } finally { jest.useRealTimers(); }
 });
 test('another pagehide permanently retires previous auth read', async () => {
  const raw = await terminal(), auth = deferred(); transport.get.mockImplementationOnce(() => auth.promise);
  await transition('pagehide'); await transition('pageshow'); await transition('pagehide'); await act(async () => auth.resolve({ status: 200, data: { id: 'admin', role: 'admin' } }));
  expect(result.sessionSuspended).toBe(true); expect(result.checkingSession).toBe(false); expect(localStorage.getItem(keys(kind))).toBe(raw);
  await transition('pageshow'); expect(result.sessionSuspended).toBe(false);
 });
 test('offline return remains suspended until explicit successful online reverification', async () => {
  const raw = await terminal(); await render(kind, { online: false }); transport.get.mockClear(); await transition('pagehide'); await transition('pageshow');
  expect(result.errorCode).toBe('OFFLINE'); expect(transport.get).not.toHaveBeenCalled(); await render(kind, { online: true }); expect(result.sessionSuspended).toBe(true);
  await act(async () => result.revalidateSession()); expect(result.sessionSuspended).toBe(false); expect(localStorage.getItem(keys(kind))).toBe(raw);
 });
 test('pre-admission lookup404 after return resends exact draft and UUID', async () => {
  const old = deferred(), started = deferred(); transport.post.mockImplementationOnce(() => { started.resolve(); return old.promise; }).mockResolvedValue(receipt(kind)); await render(kind); let flight;
  await act(async () => { flight = result.submit(commands[kind]); await finite(started.promise); }); const raw = localStorage.getItem(keys(kind)), drafts = { ...sessionStorage };
  await transition('pagehide'); await transition('pageshow'); await act(async () => { old.resolve(receipt(kind)); await flight; }); expect(localStorage.getItem(keys(kind))).toBe(raw); expect({ ...sessionStorage }).toEqual(drafts);
  transport.get.mockRejectedValue({ response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } }); await act(async () => result.recover());
  expect(transport.post).toHaveBeenCalledTimes(2); expect(transport.post.mock.calls[1][1]).toEqual(transport.post.mock.calls[0][1]); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1); expect(result.record.receipt.state).toBe('applied'); expect(sessionStorage.length).toBe(0);
 });
 test('admitted pending survives return with disabled admission and bodyless resume', async () => {
  const old = deferred(), started = deferred(); transport.post.mockImplementationOnce(() => { started.resolve(); return old.promise; }).mockResolvedValue(receipt(kind)); await render(kind); let flight;
  await act(async () => { flight = result.submit(commands[kind]); await finite(started.promise); });
  const pending = { status: 202, headers: { 'retry-after': '1' }, data: { client_operation_id: ID, state: 'pending', retry_after_seconds: 1 } };
  const stored = JSON.parse(localStorage.getItem(keys(kind))); localStorage.setItem(keys(kind), JSON.stringify({ ...stored, receipt: pending.data }));
  transport.get.mockImplementation(async (path) => path.endsWith('/api/auth/me') ? { status: 200, data: { id: 'admin', role: 'admin' } } : path.endsWith('capabilities') ? { status: 200, data: { create_recovery_enabled: false, edit_recovery_enabled: false, assign_recovery_enabled: false } } : pending);
  await transition('pagehide'); await transition('pageshow'); await act(async () => { old.resolve(receipt(kind)); await flight; }); expect(result.capability.enabled).toBe(false);
  await act(async () => result.recover()); expect(transport.post).toHaveBeenCalledTimes(2); expect(transport.post.mock.calls[1][0]).toMatch(/\/resume$/); expect(transport.post.mock.calls[1][1]).toBeUndefined(); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1);
 });
 test('nonpersisted retirement cannot be revived by unsolicited pageshow', async () => {
  const raw = await terminal(); transport.get.mockClear(); await transition('pagehide', false); await transition('pageshow'); await act(async () => result.revalidateSession());
  expect(result.sessionSuspended).toBe(true); expect(transport.get).not.toHaveBeenCalled(); expect(localStorage.getItem(keys(kind))).toBe(raw);
 });
});


describe.each(['admin', 'restaurant'])('eligible %s cancellation additional boundaries', (role) => {
 test('double click plus admitted return resumes bodyless, same reason/UUID, no payload durable', async () => {
  const actor = { id: 'admin', role, ...(role === 'restaurant' ? { restaurant_id: 'restaurant' } : {}) };
  function CancelHarness() { result = useOrderStatusRecovery(actor, 'https://qa.invalid', true, null, false); return null; }
  const pending = { status: 202, headers: { 'retry-after': '1' }, data: { client_operation_id: ID, state: 'pending', retry_after_seconds: 1 } };
  transport.get.mockImplementation(async (p) => p.endsWith('/api/auth/me') ? { status: 200, data: actor } : p.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: true } } : pending);
  const old = deferred(), started = deferred(); transport.post.mockImplementationOnce(() => { started.resolve(); return old.promise; }).mockResolvedValue(receipt('status'));
  await act(async () => root.render(<StrictMode><CancelHarness /></StrictMode>)); let flight;
  const command = { order, status: 'CANCELLED', cancellationReason: 'Exact private admitted reason' };
  await act(async () => { flight = result.submit(command); await finite(started.promise); expect(await result.submit(command)).toBeNull(); });
  const key = 'prodelivery:order-status:v1:admin', stored = JSON.parse(localStorage.getItem(key)); localStorage.setItem(key, JSON.stringify({ ...stored, receipt: pending.data }));
  expect(localStorage.getItem(key)).not.toContain('private'); await transition('pagehide'); await transition('pageshow'); await act(async () => { old.resolve(receipt('status')); expect(await flight).toBeNull(); });
  await act(async () => result.recover()); expect(transport.post).toHaveBeenCalledTimes(2); expect(transport.post.mock.calls[1][0]).toMatch(/\/resume$/); expect(transport.post.mock.calls[1][1]).toBeUndefined(); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1); expect(sessionStorage.length).toBe(0);
  await act(async () => result.acknowledge()); expect(localStorage.getItem(key)).toBeNull();
 });
});

test.each([
 [{ id: 'foreign', role: 'restaurant', restaurant_id: 'foreign-restaurant' }, order, 'STATUS_TRANSITION_INVALID'],
 [{ id: 'driver-actor', role: 'driver', driver_id: 'driver' }, { ...order, status: 'ASSIGNED', driver_id: 'driver' }, 'STATUS_TRANSITION_INVALID'],
 [{ id: 'admin', role: 'admin' }, { ...order, status: 'PICKED_UP', driver_id: 'driver' }, 'CUSTODY_RESOLUTION_REQUIRED'],
])('cancel remains refused for actor/status boundary %j', async (actor, target, expected) => {
 function ForbiddenHarness() { result = useOrderStatusRecovery(actor, 'https://qa.invalid', true, null, false); return null; }
 await act(async () => root.render(<StrictMode><ForbiddenHarness /></StrictMode>)); await act(async () => result.submit({ order: target, status: 'CANCELLED', cancellationReason: 'Exact reason' }));
 expect(result.errorCode).toBe(expected); expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled(); expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
});
