import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { useOrderCreationRecovery } from './useOrderCreationRecovery';
jest.mock('axios', () => ({ create: jest.fn() }));
const ID = 'operation_finance_0001', KEY = 'prodelivery:order-create:v1:actor';
const receipt = (state = 'pending') => ({ client_operation_id: ID, state, order_id: null, order_version: null,
  error_code: state === 'rejected' ? 'FINANCIAL_INTENT_CLOSED' : null, retry_after_seconds: state === 'pending' ? 2 : null });
const response = (state = 'pending') => ({ status: state === 'pending' ? 202 : 409, data: receipt(state) });
const metadata = () => ({ version: 2, protocol: 'financial_create_v1', api_base: 'https://synthetic.invalid', actor_id: 'actor', actor_role: 'admin',
  actor_restaurant_id: null, restaurant_id: 'r', client_operation_id: ID, created_at: 1000, quote_confirmation: { contract_version: 1, quote_fingerprint: 'a'.repeat(64) }, receipt: receipt() });
let root, container, result, transport, props;
function Harness() { result = useOrderCreationRecovery('actor', props.api, props.online, props.token, { role: props.role, restaurant_id: props.tenant }); return null; }
const render = (patch = {}) => act(async () => { props = { ...props, ...patch }; root.render(<Harness />); });
const event = (name, persisted) => act(async () => { const e = new Event(name); if (persisted !== undefined) Object.defineProperty(e, 'persisted', { value: persisted }); window.dispatchEvent(e); });
const reads = () => transport.get.mock.calls.filter(([url]) => url.includes(`/finance/create/${ID}`));
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear(); jest.clearAllMocks(); localStorage.setItem(KEY, JSON.stringify(metadata()));
  props = { api: 'https://synthetic.invalid', online: true, token: 'token', role: 'admin', tenant: null };
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_k, _o, cb) => cb({}) } });
  transport = { get: jest.fn(async (url) => url.endsWith('/capabilities') ? { status: 200, data: { create_recovery_enabled: false } } : response()), post: jest.fn() };
  axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); await Promise.resolve(); container.remove(); });
test('mount and focus automatically GET pending without resume POST', async () => {
  await render(); expect(reads().length).toBeGreaterThan(0); transport.get.mockClear(); await event('focus'); expect(reads()).toHaveLength(1); expect(transport.post).not.toHaveBeenCalled();
});
test('reconnect refreshes authoritative terminal even when admission marker is disabled', async () => {
  await render({ online: false }); expect(reads()).toHaveLength(0);
  transport.get.mockImplementation(async (url) => url.endsWith('/capabilities') ? { status: 200, data: { create_recovery_enabled: false } } : response('rejected'));
  await render({ online: true }); expect(result.record.receipt.state).toBe('rejected'); expect(result.capability.enabled).toBe(false); expect(localStorage.getItem(KEY)).not.toBeNull();
});
test('local terminal on mount remains a hint when server returns 404', async () => {
  localStorage.setItem(KEY, JSON.stringify({ ...metadata(), receipt: receipt('rejected') }));
  transport.get.mockRejectedValue({ response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } });
  await render(); expect(reads().length).toBeGreaterThan(0); expect(localStorage.getItem(KEY)).not.toBeNull(); expect(transport.post).not.toHaveBeenCalled();
});
test('storage hint coalesces while one lookup is in flight and never mutates remotely', async () => {
  await render(); let resolve; transport.get.mockImplementation((url) => url.endsWith('/capabilities') ? Promise.resolve({ status: 200, data: { create_recovery_enabled: false } }) : new Promise((done) => { resolve = done; }));
  transport.get.mockClear(); await event('focus'); const settled = resolve;
  await act(async () => { for (let n = 0; n < 8; n++) window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: localStorage.getItem(KEY) })); });
  expect(reads()).toHaveLength(1); transport.get.mockImplementation(async () => response()); await act(async () => settled(response())); expect(reads()).toHaveLength(2); expect(transport.post).not.toHaveBeenCalled();
});
test('BFCache restore publishes fresh terminal through read-only recovery', async () => {
  await render(); await event('pagehide', true); expect(result.sessionSuspended).toBe(true);
  transport.get.mockImplementation(async (url) => url.endsWith('/capabilities') ? { status: 200, data: { create_recovery_enabled: false } } : response('rejected'));
  await event('pageshow', true); expect(result.sessionSuspended).toBe(false); expect(result.record.receipt.state).toBe('rejected'); expect(transport.post).not.toHaveBeenCalled();
});
test('same actor token replacement retires old read callback', async () => {
  await render(); let resolve; transport.get.mockImplementation((url) => url.endsWith('/capabilities') ? Promise.resolve({ status: 200, data: { create_recovery_enabled: false } }) : new Promise((done) => { resolve = done; }));
  await event('focus'); const old = resolve; transport.get.mockImplementation(async (url) => url.endsWith('/capabilities') ? { status: 200, data: { create_recovery_enabled: false } } : response());
  await render({ token: 'replacement' }); await act(async () => old(response('rejected'))); expect(result.record.receipt.state).toBe('pending'); expect(transport.post).not.toHaveBeenCalled();
});
test('foreign API base preserves metadata and sends no operation lookup', async () => {
  await render({ api: 'https://different.invalid' }); expect(reads()).toHaveLength(0); expect(result.errorCode).toBe('FINANCIAL_CONTEXT_CHANGED'); expect(localStorage.getItem(KEY)).not.toBeNull();
});
