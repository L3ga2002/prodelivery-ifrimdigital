import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { useOrderStatusRecovery, OrderStatusRecoveryPanel } from './useOrderStatusRecovery';
jest.mock('axios', () => ({ create: jest.fn() }));
const ID = '123e4567-e89b-42d3-a456-426614174000';
const KEY = 'prodelivery:order-status:v1:actor';
const actor = { id: 'actor', role: 'driver', driver_id: 'driver' };
const order = { id: 'order', restaurant_id: 'restaurant', driver_id: 'driver', status: 'ASSIGNED', order_version: 4, preparation_status: 'READY' };
const record = { actor_id: 'actor', actor_role: 'driver', actor_resource_id: 'driver', order_id: 'order',
  expected_order_version: 4, status: 'ACCEPTED', client_operation_id: ID, receipt: null };
const done = { status: 200, data: { client_operation_id: ID, state: 'applied', order_id: 'order', order_version: 5 } };
const pending = { status: 202, headers: { 'retry-after': '1' }, data: { client_operation_id: ID, state: 'pending', retry_after_seconds: 1 } };
let root, container, result, transport;
function Harness({ user = actor, token = 'token-a', online = true, probe = true, panel = false }) {
  result = useOrderStatusRecovery(user, 'https://qa.invalid', online, token, probe);
  return panel ? <OrderStatusRecoveryPanel recovery={result} isOnline={online} /> : null;
}
const render = (props = {}) => act(async () => root.render(<StrictMode><Harness {...props} /></StrictMode>));
const pageTransition = (type, persisted = true) => act(async () => {
  const event = new Event(type); Object.defineProperty(event, 'persisted', { value: persisted }); window.dispatchEvent(event);
});
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear(); jest.clearAllMocks();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_k, _o, cb) => cb({}) } });
  Object.defineProperty(window, 'crypto', { configurable: true, value: { randomUUID: jest.fn(() => ID) } });
  transport = { get: jest.fn(async (path) => path.endsWith('/api/auth/me') ? { status: 200, data: actor } :
    { status: 200, data: { status_recovery_enabled: true } }), post: jest.fn(async () => done), put: jest.fn(async () => ({ status: 200 })) };
  axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); await Promise.resolve(); container.remove(); });

test.each([null, pending.data])('STRICTMODE RED: preloaded nonterminal receipt %j exposes bounded lookup503 error', async (receipt) => {
  const retained = JSON.stringify({ ...record, receipt }); localStorage.setItem(KEY, retained);
  transport.get.mockRejectedValue({ response: { status: 503, data: { detail: { code: 'RECOVERY_UNAVAILABLE' } } } });
  await render({ probe: false, panel: true });
  expect(result.errorCode).toBe('RECOVERY_UNAVAILABLE'); expect(result.busy).toBe(false); expect(result.storageInvalid).toBe(false);
  expect(container.querySelector('[data-testid="status-recovery-error"]')).not.toBeNull();
  expect(container.querySelector('[data-testid="status-recover-button"]').disabled).toBe(false);
  expect(transport.get).toHaveBeenCalledTimes(2);
  for (const [path, options] of transport.get.mock.calls) {
    expect(path).toBe(`https://qa.invalid/api/orders/operations/status/order/${ID}`);
    expect(options).toEqual({ timeout: 15000, headers: { Authorization: 'Bearer token-a', 'X-Expected-Actor-ID': 'actor' } });
  }
  expect(localStorage.getItem(KEY)).toBe(retained); expect(transport.post).not.toHaveBeenCalled();
  expect(transport.put).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test('STRICTMODE delayed initial flight settles before one fresh lifecycle recovery, with no render retry loop', async () => {
  const retained = JSON.stringify(record); localStorage.setItem(KEY, retained); let reject;
  transport.get.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }))
    .mockRejectedValue({ response: { status: 503 } });
  await render({ probe: false, panel: true }); expect(result.busy).toBe(true); expect(transport.get).toHaveBeenCalledTimes(1);
  await render({ probe: false, panel: true }); expect(transport.get).toHaveBeenCalledTimes(1);
  await act(async () => reject({ response: { status: 503 } }));
  expect(result.errorCode).toBe('RECOVERY_UNAVAILABLE'); expect(result.busy).toBe(false); expect(transport.get).toHaveBeenCalledTimes(2);
  await render({ probe: false, panel: true }); await act(async () => Promise.resolve()); expect(transport.get).toHaveBeenCalledTimes(2);
  expect(localStorage.getItem(KEY)).toBe(retained); expect(transport.post).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test('STRICTMODE delayed valid terminal lookup suppresses queued recovery and remains acknowledgeable', async () => {
  localStorage.setItem(KEY, JSON.stringify({ ...record, receipt: pending.data })); let release;
  transport.get.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  await render({ probe: false, panel: true }); expect(result.busy).toBe(true);
  await act(async () => release(done)); expect(result.record.receipt).toEqual(done.data); expect(result.busy).toBe(false);
  expect(container.querySelector('[data-testid="status-acknowledge-button"]').disabled).toBe(false);
  expect(transport.get).toHaveBeenCalledTimes(1); expect(transport.post).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test('STRICTMODE actual unmount cancels queued initialization and late error cannot issue another lookup', async () => {
  const retained = JSON.stringify(record); localStorage.setItem(KEY, retained); let reject;
  transport.get.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  await render({ probe: false, panel: true }); await act(async () => root.render(null));
  await act(async () => reject({ response: { status: 503 } }));
  expect(container.childElementCount).toBe(0); expect(transport.get).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(KEY)).toBe(retained); expect(transport.post).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test('STRICTMODE real remount gets its own bounded error while retired successful lookup cannot erase it', async () => {
  const retained = JSON.stringify(record); localStorage.setItem(KEY, retained); let release;
  transport.get.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; })).mockRejectedValue({ response: { status: 503 } });
  await render({ probe: false, panel: true }); await act(async () => root.render(null)); await render({ probe: false, panel: true });
  expect(result.errorCode).toBe('RECOVERY_UNAVAILABLE'); expect(transport.get).toHaveBeenCalledTimes(3);
  await act(async () => release(done)); expect(result.errorCode).toBe('RECOVERY_UNAVAILABLE'); expect(result.record.receipt).toBeNull();
  expect(transport.get).toHaveBeenCalledTimes(3); expect(localStorage.getItem(KEY)).toBe(retained);
  expect(transport.post).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test('STRICTMODE account switch during delayed initialization discards the old queued recovery and error', async () => {
  const retained = JSON.stringify(record); localStorage.setItem(KEY, retained); let reject;
  transport.get.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  await render({ probe: false, panel: true }); await render({ user: { ...actor, id: 'other', driver_id: 'other-driver' }, probe: false, panel: true });
  await act(async () => reject({ response: { status: 503 } }));
  expect(result.record).toBeNull(); expect(result.error).toBe(''); expect(result.busy).toBe(false); expect(transport.get).toHaveBeenCalledTimes(1);
  expect(container.querySelector('[data-testid="status-recovery-error"]')).toBeNull(); expect(localStorage.getItem(KEY)).toBe(retained);
  expect(transport.post).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test('STRICTMODE same-actor token rotation keeps cancel ID/draft and current error, rejecting retired receipt', async () => {
  const retained = JSON.stringify({ ...record, status: 'CANCELLED' }); localStorage.setItem(KEY, retained);
  const d = { ...record, status: 'CANCELLED', cancellation_reason: 'Exact session-only StrictMode draft' }; delete d.receipt;
  const retainedDraft = JSON.stringify(d); sessionStorage.setItem(`${KEY}:draft:${ID}`, retainedDraft); let release;
  transport.get.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; })).mockRejectedValue({ response: { status: 503 } });
  await render({ probe: false, panel: true }); await render({ token: 'rotated', probe: false, panel: true });
  expect(result.errorCode).toBe('RECOVERY_UNAVAILABLE'); expect(transport.get).toHaveBeenCalledTimes(2);
  expect(transport.get.mock.calls[1][1].headers.Authorization).toBe('Bearer rotated');
  await act(async () => release(done)); expect(result.errorCode).toBe('RECOVERY_UNAVAILABLE'); expect(result.record.receipt).toBeNull();
  expect(localStorage.getItem(KEY)).toBe(retained); expect(sessionStorage.getItem(`${KEY}:draft:${ID}`)).toBe(retainedDraft);
  expect(transport.get).toHaveBeenCalledTimes(2); expect(transport.post).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test.each([true, false])('STRICTMODE queued initialization cannot cross BFCache suspension; actual session match=%s', async (matches) => {
  const retained = JSON.stringify(record); localStorage.setItem(KEY, retained); let reject;
  transport.get.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  transport.get.mockImplementation(async (path) => {
    if (path.endsWith('/api/auth/me')) return { status: 200, data: matches ? actor : { ...actor, id: 'other' } };
    throw { response: { status: 503 } };
  });
  await render({ probe: false, panel: true }); await pageTransition('pagehide'); await act(async () => reject({ response: { status: 503 } }));
  expect(transport.get).toHaveBeenCalledTimes(1); expect(result.sessionSuspended).toBe(true);
  await pageTransition('pageshow'); expect(transport.get).toHaveBeenCalledTimes(2);
  expect(result.sessionSuspended).toBe(!matches); await act(async () => result.recover());
  expect(transport.get).toHaveBeenCalledTimes(matches ? 3 : 2); expect(result.errorCode).toBe(matches ? 'RECOVERY_UNAVAILABLE' : 'SESSION_CHANGED');
  expect(result.storageInvalid).toBe(false); expect(localStorage.getItem(KEY)).toBe(retained);
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test('STRICTMODE queued recovery never starts offline and remains manually recoverable after reconnect', async () => {
  const retained = JSON.stringify(record); localStorage.setItem(KEY, retained); let reject;
  transport.get.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; })).mockRejectedValue({ response: { status: 503 } });
  await render({ probe: false, panel: true }); await render({ online: false, probe: false, panel: true });
  await act(async () => reject({ response: { status: 503 } })); expect(transport.get).toHaveBeenCalledTimes(1);
  expect(result.busy).toBe(false); expect(container.querySelector('[data-testid="status-recover-button"]').disabled).toBe(true);
  await render({ probe: false, panel: true }); expect(transport.get).toHaveBeenCalledTimes(1);
  await act(async () => result.recover()); expect(result.errorCode).toBe('RECOVERY_UNAVAILABLE'); expect(transport.get).toHaveBeenCalledTimes(2);
  expect(localStorage.getItem(KEY)).toBe(retained); expect(transport.post).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test('STRICTMODE fix preserves production initialization with exactly one failed lookup', async () => {
  localStorage.setItem(KEY, JSON.stringify(record)); transport.get.mockRejectedValue({ response: { status: 503 } });
  await act(async () => root.render(<Harness probe={false} panel />));
  expect(result.errorCode).toBe('RECOVERY_UNAVAILABLE'); expect(result.busy).toBe(false); expect(transport.get).toHaveBeenCalledTimes(1);
  expect(transport.post).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});

test.each([
  { id: 'actor', role: 'admin' }, actor, { id: 'actor', role: 'restaurant', restaurant_id: 'restaurant' },
])('real %s actor owns isolated bearer/header/metadata', async (user) => {
  await render({ user }); const status = user.role === 'restaurant' ? 'CANCELLED' : 'ACCEPTED';
  await act(async () => result.submit({ order, status, ...(status === 'CANCELLED' ? { cancellationReason: 'Private Sentinel' } : {}) }));
  expect(axios.create).toHaveBeenCalledWith({ withCredentials: true });
  expect(transport.post.mock.calls[0][2]).toEqual({ timeout: 15000, headers: { Authorization: 'Bearer token-a', 'X-Expected-Actor-ID': 'actor' } });
  for (const [, options] of transport.get.mock.calls) expect(options.headers['X-Expected-Actor-ID']).toBe('actor');
  expect(JSON.parse(localStorage.getItem(KEY)).actor_role).toBe(user.role); expect(localStorage.getItem(KEY)).not.toContain('Private');
  expect(sessionStorage.length).toBe(0);
});
test('unused feature does not probe capabilities or cause API stub noise', async () => {
  await render({ probe: false }); expect(transport.get).not.toHaveBeenCalled(); expect(result.capability.ready).toBe(false);
  await act(async () => result.verifyCapability()); expect(result.capability.enabled).toBe(true);
});
test('FE-01 RED: persisted BFCache return revalidates real session before terminal acknowledgement', async () => {
  localStorage.setItem(KEY, JSON.stringify({ ...record, receipt: done.data })); await render({ probe: false });
  await pageTransition('pagehide'); await pageTransition('pageshow');
  expect(transport.get).toHaveBeenCalledWith('https://qa.invalid/api/auth/me',
    { timeout: 15000, headers: { Authorization: 'Bearer token-a', 'X-Expected-Actor-ID': 'actor' } });
  expect(result.storageInvalid).toBe(false); expect(result.record.client_operation_id).toBe(ID);
  await act(async () => result.acknowledge()); expect(localStorage.getItem(KEY)).toBeNull();
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('BFCache pending recovery revalidates cookie actor, then keeps ID and bodyless admitted resume', async () => {
  localStorage.setItem(KEY, JSON.stringify({ ...record, receipt: pending.data }));
  transport.get.mockRejectedValue(new Error('unavailable')); await render({ token: null, probe: false });
  transport.get.mockImplementation(async (path) => path.endsWith('/api/auth/me') ? { status: 200, data: actor } :
    path.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: false } } : pending);
  await pageTransition('pagehide'); const retained = localStorage.getItem(KEY);
  await act(async () => result.recover()); expect(localStorage.getItem(KEY)).toBe(retained);
  await pageTransition('pageshow'); expect(result.sessionSuspended).toBe(false); expect(result.storageInvalid).toBe(false);
  await act(async () => result.verifyCapability()); expect(result.capability).toEqual({ ready: true, enabled: false });
  await act(async () => result.recover()); expect(result.record.receipt).toEqual(done.data);
  expect(transport.post.mock.calls[0]).toEqual([`https://qa.invalid/api/orders/operations/status/order/${ID}/resume`, undefined,
    { timeout: 15000, headers: { Authorization: null, 'X-Expected-Actor-ID': 'actor' } }]);
  expect(window.crypto.randomUUID).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('BFCache preserves exact cancel draft and permanently fences POST from before suspension', async () => {
  let release; transport.post.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  await render({ probe: false }); let flight;
  await act(async () => { flight = result.submit({ order, status: 'CANCELLED', cancellationReason: 'Exact private BFCache reason' }); while (!release) await Promise.resolve(); });
  const retained = localStorage.getItem(KEY), retainedDraft = sessionStorage.getItem(`${KEY}:draft:${ID}`);
  await pageTransition('pagehide'); await pageTransition('pageshow');
  await act(async () => { release(done); expect(await flight).toBeNull(); });
  expect(localStorage.getItem(KEY)).toBe(retained); expect(sessionStorage.getItem(`${KEY}:draft:${ID}`)).toBe(retainedDraft);
  expect(result.storageInvalid).toBe(false); expect(result.errorCode).toBe('');
  transport.get.mockRejectedValue({ response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } });
  await act(async () => result.recover()); expect(transport.post).toHaveBeenCalledTimes(2);
  expect(transport.post.mock.calls[1][1]).toEqual(transport.post.mock.calls[0][1]);
  expect(result.record.receipt).toEqual(done.data); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(KEY)).not.toContain('private'); expect(sessionStorage.length).toBe(0); expect(transport.put).not.toHaveBeenCalled();
});
test.each([{ ...actor, id: 'other' }, { id: 'actor', role: 'admin' }, { ...actor, driver_id: 'other-driver' },
  { ...actor, is_disabled: true }, { ...actor, account_disabled: true }, null])('BFCache actual actor mismatch %j cannot acknowledge or mutate', async (actual) => {
  const retained = JSON.stringify({ ...record, receipt: done.data }); localStorage.setItem(KEY, retained);
  await render({ probe: false }); transport.get.mockResolvedValue({ status: 200, data: actual });
  await pageTransition('pagehide'); await pageTransition('pageshow');
  expect(result.sessionSuspended).toBe(true); expect(result.errorCode).toBe('SESSION_CHANGED'); expect(result.storageInvalid).toBe(false);
  await act(async () => { await result.acknowledge(); await result.recover(); await result.submit({ order, status: 'ACCEPTED' }); await result.verifyCapability(); });
  expect(localStorage.getItem(KEY)).toBe(retained); expect(result.canSubmit(order)).toBe(false);
  expect(transport.get).toHaveBeenCalledTimes(1); expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test.each([[401, 'AUTH_REQUIRED'], [403, 'SESSION_CHANGED'], [503, 'RECOVERY_UNAVAILABLE']])('BFCache auth HTTP%s stays suspended without storage corruption', async (status, errorCode) => {
  localStorage.setItem(KEY, JSON.stringify({ ...record, receipt: done.data })); await render({ probe: false });
  transport.get.mockRejectedValue({ response: { status, data: { detail: { code: 'AUTH_CONTEXT_CHANGED' } } } });
  await pageTransition('pagehide'); await pageTransition('pageshow');
  expect(result.errorCode).toBe(errorCode); expect(result.sessionSuspended).toBe(true); expect(result.storageInvalid).toBe(false);
  await act(async () => result.acknowledge()); expect(localStorage.getItem(KEY)).not.toBeNull();
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('BFCache delayed session validation gates acknowledgement and deduplicates pageshow', async () => {
  localStorage.setItem(KEY, JSON.stringify({ ...record, receipt: done.data })); await render({ probe: false });
  let release; transport.get.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
  await pageTransition('pagehide'); await pageTransition('pageshow'); await pageTransition('pageshow');
  expect(result.checkingSession).toBe(true); expect(transport.get).toHaveBeenCalledTimes(1);
  await act(async () => result.acknowledge()); expect(localStorage.getItem(KEY)).not.toBeNull();
  await act(async () => release({ status: 200, data: actor })); expect(result.sessionSuspended).toBe(false);
  await act(async () => result.acknowledge()); expect(localStorage.getItem(KEY)).toBeNull();
});
test('BFCache actor switch during actual validation cannot revive retired controller or old record', async () => {
  const retained = JSON.stringify({ ...record, receipt: done.data }); localStorage.setItem(KEY, retained); await render({ probe: false });
  let release; transport.get.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  await pageTransition('pagehide'); await pageTransition('pageshow');
  await render({ user: { ...actor, id: 'other', driver_id: 'other-driver' }, token: 'other-token', probe: false });
  await act(async () => release({ status: 200, data: actor }));
  expect(result.record).toBeNull(); expect(result.errorCode).toBeUndefined(); expect(localStorage.getItem(KEY)).toBe(retained);
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('BFCache repeated suspension fences an older revalidation response', async () => {
  await render({ probe: false }); let release;
  transport.get.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  await pageTransition('pagehide'); await pageTransition('pageshow'); await pageTransition('pagehide');
  await act(async () => release({ status: 200, data: actor })); expect(result.sessionSuspended).toBe(true);
  expect(result.checkingSession).toBe(false); expect(result.canSubmit(order)).toBe(false);
  await pageTransition('pageshow'); expect(result.sessionSuspended).toBe(false);
});
test('BFCache offline return requires explicit online session revalidation, without unused feature probe', async () => {
  await render({ online: false, probe: false }); await pageTransition('pagehide'); await pageTransition('pageshow');
  expect(result.errorCode).toBe('OFFLINE'); expect(result.sessionSuspended).toBe(true); expect(transport.get).not.toHaveBeenCalled();
  await render({ online: true, probe: false }); expect(result.sessionSuspended).toBe(true);
  await act(async () => result.revalidateSession()); expect(result.sessionSuspended).toBe(false);
  expect(transport.get.mock.calls.map(([p]) => p)).toEqual(['https://qa.invalid/api/auth/me']);
});
test('nonpersisted pagehide and unsolicited pageshow cannot reactivate without matching suspension', async () => {
  await render({ probe: false }); await pageTransition('pageshow'); expect(transport.get).not.toHaveBeenCalled();
  await pageTransition('pagehide', false); await pageTransition('pageshow'); await act(async () => result.revalidateSession());
  expect(result.sessionSuspended).toBe(true); expect(transport.get).not.toHaveBeenCalled(); expect(result.canSubmit(order)).toBe(false);
});
test('BFCache rechecks demanded capability and ignores pre-suspension capability response', async () => {
  await render(); let release; transport.get.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  let old; await act(async () => { old = result.verifyCapability(); await Promise.resolve(); });
  transport.get.mockImplementation(async (path) => path.endsWith('/api/auth/me') ? { status: 200, data: actor } :
    { status: 200, data: { status_recovery_enabled: false } });
  await pageTransition('pagehide'); await pageTransition('pageshow');
  await act(async () => { release({ status: 200, data: { status_recovery_enabled: true } }); await old; });
  expect(result.capability).toEqual({ ready: true, enabled: false }); expect(result.canSubmit(order)).toBe(false);
  expect(result.storageInvalid).toBe(false); expect(result.errorCode).toBe('');
});
test('reload with no active order still recovers admitted intent even when capability disabled', async () => {
  localStorage.setItem(KEY, JSON.stringify({ ...record, status: 'DELIVERED', receipt: pending.data }));
  transport.get.mockImplementation(async (p) => p.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: false } } : pending);
  await render(); expect(result.record.status).toBe('DELIVERED'); expect(result.record.receipt.state).toBe('applied');
  expect(transport.post.mock.calls[0]).toEqual([`https://qa.invalid/api/orders/operations/status/order/${ID}/resume`, undefined,
    { timeout: 15000, headers: { Authorization: 'Bearer token-a', 'X-Expected-Actor-ID': 'actor' } }]);
  expect(transport.put).not.toHaveBeenCalled();
});
test('actor/session switch fences late receipts and leaves original identity', async () => {
  let release; transport.post.mockImplementation(() => new Promise((r) => { release = r; }));
  await render(); let flight; await act(async () => { flight = result.submit({ order, status: 'ACCEPTED' }); await Promise.resolve(); });
  const old = transport; transport = { get: jest.fn(async () => ({ status: 200, data: { status_recovery_enabled: true } })), post: jest.fn(), put: jest.fn() };
  axios.create.mockReturnValue(transport); await render({ user: { ...actor, id: 'other', driver_id: 'other-driver' } });
  expect(result.record).toBeNull(); await act(async () => { release(done); await flight; });
  expect(JSON.parse(localStorage.getItem(KEY)).receipt).toBeNull(); expect(old.post).toHaveBeenCalledTimes(1); expect(transport.post).not.toHaveBeenCalled();
});
test('same actor token rotation keeps session-only exact cancel draft but fences retired receipt', async () => {
  let release; transport.post.mockImplementation(() => new Promise((r) => { release = r; })); await render(); let flight;
  await act(async () => { flight = result.submit({ order, status: 'CANCELLED', cancellationReason: 'Exact PII Sentinel' }); await Promise.resolve(); });
  expect(sessionStorage.length).toBe(1); const old = transport;
  transport = { get: jest.fn(async (p) => { if (p.endsWith('capabilities')) return { status: 200, data: { status_recovery_enabled: false } };
    throw { response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } }; }),
    post: jest.fn(async () => ({ ...done, data: { ...done.data, state: 'replayed' } })), put: jest.fn() };
  axios.create.mockReturnValue(transport); await render({ token: 'rotated' });
  expect(transport.post.mock.calls[0][1].cancellation_reason).toBe('Exact PII Sentinel');
  expect(transport.post.mock.calls[0][2].headers.Authorization).toBe('Bearer rotated'); expect(sessionStorage.length).toBe(0);
  await act(async () => { release(done); await flight; }); expect(JSON.parse(localStorage.getItem(KEY)).receipt.state).toBe('replayed');
  expect(old.post).toHaveBeenCalledTimes(1);
});
test('logout clears session draft but not durable pending identity', async () => {
  transport.post.mockRejectedValue(new Error('offline')); transport.get.mockImplementation(async (p) => {
    if (p.endsWith('capabilities')) return { status: 200, data: { status_recovery_enabled: true } }; throw new Error('offline');
  });
  await render(); await act(async () => result.submit({ order, status: 'CANCELLED', cancellationReason: 'PII Sentinel' }));
  expect(sessionStorage.length).toBe(1); await render({ user: null });
  expect(sessionStorage.length).toBe(0); expect(localStorage.getItem(KEY)).not.toBeNull(); expect(result.available).toBe(false);
});
test.each([401, 403])('HTTP%s never refreshes/replays or invokes legacy', async (status) => {
  transport.post.mockRejectedValue({ response: { status } }); await render(); await act(async () => result.submit({ order, status: 'ACCEPTED' }));
  expect(transport.post).toHaveBeenCalledTimes(1); expect(transport.put).not.toHaveBeenCalled(); expect(result.record.receipt).toBeNull();
});
test.each(['token-a', null])('expected actor guard covers every route with token %j', async (token) => {
  let cookieActor = 'actor'; const guard = (options) => {
    if (options.headers['X-Expected-Actor-ID'] !== cookieActor) throw { response: { status: 403, data: { detail: { code: 'AUTH_CONTEXT_CHANGED' } } } };
  };
  transport.get.mockImplementation(async (p, options) => { guard(options); return p.endsWith('/api/auth/me') ? { status: 200, data: actor } :
    p.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: true } } : pending; });
  transport.post.mockImplementation(async (_p, _b, options) => { cookieActor = 'other'; guard(options); return done; });
  await render({ token }); await act(async () => result.submit({ order, status: 'ACCEPTED' })); expect(result.errorCode).toBe('SESSION_CHANGED');
  await act(async () => result.recover()); expect(result.errorCode).toBe('SESSION_CHANGED'); expect(transport.post).toHaveBeenCalledTimes(1);
  expect(transport.put).not.toHaveBeenCalled(); cookieActor = 'actor'; transport.post.mockImplementation(async (_p, _b, options) => { guard(options); return done; });
  await act(async () => result.recover()); expect(result.record.receipt.state).toBe('applied'); await act(async () => result.acknowledge());
  const legacy = { ...order }; delete legacy.order_version;
  transport.put.mockImplementation(async (_p, _b, options) => { expect(options.headers['X-Expected-Actor-ID']).toBe('actor'); cookieActor = 'other'; guard(options); return { status: 200 }; });
  await act(async () => result.submitLegacy({ order: legacy, status: 'ACCEPTED' })); expect(result.errorCode).toBe('SESSION_CHANGED');
});
test('another tab storage event freezes initial legacy; offline reload sends nothing', async () => {
  await render({ online: false, probe: false }); localStorage.setItem(KEY, JSON.stringify(record));
  await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: KEY })));
  expect(result.record.client_operation_id).toBe(ID); expect(result.blocked).toBe(true);
  const legacy = { ...order }; delete legacy.order_version;
  await act(async () => result.submitLegacy({ order: legacy, status: 'ACCEPTED' })); expect(result.errorCode).toBe('INTENT_PENDING');
  expect(transport.get).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('corrupt durable metadata retained and missing locks block both paths', async () => {
  localStorage.setItem(KEY, '{corrupt'); await render(); expect(result.storageInvalid).toBe(true);
  await act(async () => result.acknowledge()); expect(localStorage.getItem(KEY)).toBe('{corrupt'); expect(transport.post).not.toHaveBeenCalled();
  localStorage.clear(); Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined }); await render({ token: 'new' });
  expect(result.available).toBe(false); await act(async () => result.submit({ order, status: 'ACCEPTED' })); expect(result.errorCode).toBe('LOCK_UNAVAILABLE');
});
test('latest capability result wins; no enabled inference on malformed response', async () => {
  await render(); let release; transport.get.mockImplementationOnce(() => new Promise((r) => { release = r; })).mockResolvedValue({ status: 200, data: { status_recovery_enabled: false } });
  let old; await act(async () => { old = result.verifyCapability(); await Promise.resolve(); });
  await act(async () => result.verifyCapability()); await act(async () => { release({ status: 200, data: { status_recovery_enabled: true } }); await old; });
  expect(result.capability.enabled).toBe(false); transport.get.mockResolvedValue({ status: 200, data: {} }); await act(async () => result.verifyCapability());
  expect(result.capability.ready).toBe(false); expect(result.canSubmit(order)).toBe(false);
});
test.each([{}, null, { ...actor, id: ' bad' }, { ...actor, driver_id: null }, { ...actor, role: 'admin', is_disabled: true }])('malformed actor %j never constructs transport', async (user) => {
  await render({ user }); expect(axios.create).not.toHaveBeenCalled(); expect(result.available).toBe(false);
});
