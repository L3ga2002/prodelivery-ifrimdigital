import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { useOrderRemakeRecovery } from './useOrderRemakeRecovery';
import { useOrderRemakeFinancePreview } from './useOrderRemakeFinancePreview';
jest.mock('axios', () => ({ create: jest.fn() }));
const actor = { id: 'owner', role: 'restaurant', restaurant_id: 'r1' }, ID = 'operation_remake_0001', KEY = 'prodelivery:order-remake:v2:owner';
const receipt = (state = 'pending') => ({ client_operation_id: ID, state, order_id: null, order_version: null, parent_order_id: null, parent_order_version: null,
  error_code: state === 'rejected' ? 'FINANCIAL_INTENT_CLOSED' : null, retry_after_seconds: state === 'pending' ? 2 : null });
const response = (state = 'pending') => ({ headers: { "retry-after": "2" }, status: state === 'pending' ? 202 : 409, data: receipt(state) });
const metadata = () => ({ version: 2, protocol: 'financial_remake_v1', api_base: 'https://synthetic.invalid', actor_id: 'owner', actor_role: 'restaurant',
  actor_restaurant_id: 'r1', restaurant_id: 'r1', parent_id: 'parent', expected_order_version: 4, client_operation_id: ID, created_at: 1000,
  quote_confirmation: { contract_version: 1, quote_fingerprint: 'a'.repeat(64) }, receipt: receipt() });
const capability = () => ({ status: 200, data: { contract_version: 1, actor_id: 'owner', restaurant_id: 'r1', finance_enabled: true,
  create_quote_enabled: false, remake_quote_enabled: true, quote_informational: true, supported_basis: ['zone'] } });
const parent = () => ({ status: 200, data: { contract_version: 1, kind: 'remake_parent', actor_id: 'owner', actor_role: 'restaurant', restaurant_id: 'r1',
  parent: { order_id: 'parent', order_version: 4, status: 'DELIVERED', source: 'S', customer_name: 'Private Customer', customer_phone: '0700011223',
    customer_address: 'Private Street 123', customer_latitude: 1, customer_longitude: 1, has_problem_followup: false, problem_followup_order_id: null,
    delivery_zone_id: 'z1', delivery_zone_name: 'Zone', delivery_sector: null, delivery_zone_level: 1 }, eligibility: { can_preview: true, blocking_code: null } } });
const quote = () => ({ status: 200, data: { contract_version: 1, currency: 'RON', tariff_version: 'v1', products_bani: 1305, collection_mode: 'cash', client_collection_bani: 1305,
  restaurant_transport_bani: 1600, advance_required_bani: 1305, advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null,
  basis: 'zone', zone_id: 'z1', zone_name: 'Zone', zone_sector: null, zone_level: 1, kind: 'remake', informational: true, fingerprint_scope: 'server_key_v1',
  quote_fingerprint: 'a'.repeat(64), actor_id: 'owner', restaurant_id: 'r1', parent_order_id: 'parent', parent_order_version: 4 } });
let root, container, result, transport, props;
function Harness() { result = props.preview ? useOrderRemakeFinancePreview(props) : useOrderRemakeRecovery(props.actor, props.apiUrl, props.isOnline, props.token, props.refreshList); return null; }
const render = (patch = {}) => act(async () => { props = { ...props, ...patch }; root.render(<Harness />); });
const event = (name, persisted) => act(async () => { const e = new Event(name); if (persisted !== undefined) Object.defineProperty(e, 'persisted', { value: persisted }); window.dispatchEvent(e); });
const reads = () => transport.get.mock.calls.filter(([url]) => url.includes(`/finance/remake/parent/${ID}`));
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear(); jest.clearAllMocks(); localStorage.setItem(KEY, JSON.stringify(metadata()));
  props = { actor, apiUrl: 'https://synthetic.invalid', isOnline: true, token: 'token', refreshList: jest.fn(async () => true), parentId: 'parent', parentVersion: 4, enabled: true,
    form: { problem_type: 'missing_product', item_name: 'Replacement', quantity: '1', unit_price: '13.05', description: 'Description A', payment_type: 'CASH' } };
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_k, _o, cb) => cb({}) } });
  transport = { get: jest.fn(async (url) => url.includes('/capabilities?') ? capability() : url.includes('/remake-parent/') ? parent()
    : url.includes('/tariffs?') ? { status: 200, data: { contract_version: 1, actor_id: 'owner', restaurant_id: 'r1', tariffs: [{ version: 'v1', currency: 'RON', zone_ids: ['z1'] }] } } : response()), post: jest.fn(async () => quote()) };
  axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); await Promise.resolve(); container.remove(); });
test('mount and focus GET pending only', async () => { await render(); expect(reads().length).toBeGreaterThan(0); transport.get.mockClear(); await event('focus'); expect(reads()).toHaveLength(1); expect(transport.post).not.toHaveBeenCalled(); });
test('local terminal is a hint and automatic 404 never sends or clears', async () => {
  localStorage.setItem(KEY, JSON.stringify({ ...metadata(), receipt: receipt('rejected') }));
  transport.get.mockRejectedValue({ response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } });
  await render(); expect(reads().length).toBeGreaterThan(0); expect(localStorage.getItem(KEY)).not.toBeNull(); expect(transport.post).not.toHaveBeenCalled();
});
test('reconnect refreshes terminal despite disabled marker', async () => {
  await render({ isOnline: false }); expect(reads()).toHaveLength(0);
  transport.get.mockImplementation(async (url) => url.includes('/capabilities?') ? { ...capability(), data: { ...capability().data, finance_enabled: false, remake_quote_enabled: false } } : response('rejected'));
  await render({ isOnline: true }); expect(result.record.receipt.state).toBe('rejected'); expect(result.capability.enabled).toBe(false); expect(transport.post).not.toHaveBeenCalled();
});
test('BFCache simulated lifecycle revalidates via GET', async () => {
  await render(); await event('pagehide', true); expect(result.sessionSuspended).toBe(true);
  transport.get.mockImplementation(async (url) => url.includes('/capabilities?') ? capability() : response('rejected'));
  await event('pageshow', true); expect(result.sessionSuspended).toBe(false); expect(result.record.receipt.state).toBe('rejected'); expect(transport.post).not.toHaveBeenCalled();
});
test('token replacement retires old reply without changing saved identity', async () => {
  await render(); let resolve; transport.get.mockImplementation((url) => url.includes('/capabilities?') ? Promise.resolve(capability()) : new Promise((done) => { resolve = done; }));
  await event('focus'); const old = resolve;
  transport.get.mockImplementation(async (url) => url.includes('/capabilities?') ? capability() : response());
  await render({ token: 'replacement' }); await act(async () => old(response('rejected')));
  expect(result.record.receipt.state).toBe('pending'); expect(transport.post).not.toHaveBeenCalled();
});
test('storage event coalesces and stale lookup never overwrites', async () => {
  await render(); let resolve; transport.get.mockImplementation((url) => url.includes('/capabilities?') ? Promise.resolve(capability()) : new Promise((done) => { resolve = done; }));
  transport.get.mockClear(); await event('focus'); const old = resolve;
  await act(async () => { for (let n = 0; n < 5; n++) window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: localStorage.getItem(KEY) })); });
  expect(reads()).toHaveLength(1); transport.get.mockImplementation(async () => response()); await act(async () => old(response('rejected')));
  expect(reads()).toHaveLength(2); expect(result.record.receipt.state).toBe('pending');
});
test('foreign origin blocks operation requests and keeps metadata', async () => { await render({ apiUrl: 'https://other.invalid' }); expect(reads()).toHaveLength(0); expect(localStorage.getItem(KEY)).not.toBeNull(); expect(result.errorCode).toBe('FINANCIAL_CONTEXT_CHANGED'); });
const prepareQuote = async () => {
  localStorage.clear(); await render({ preview: true }); expect(result.tariffVersion).toBe('');
  await act(async () => result.setTariffVersion('v1')); await act(async () => result.requestQuote()); await act(async () => result.confirm(true)); expect(result.confirmed).toBe(true);
};
test('notes A-B-A invalidates confirmation monotonically', async () => {
  await prepareQuote(); const first = props.form;
  await render({ form: { ...first, description: 'Description B' } }); await render({ form: first }); expect(result.confirmed).toBe(false); expect(result.submission).toBeNull();
});
test('external intent ACK re-enables unchanged form without reviving quote', async () => { await prepareQuote(); await render({ enabled: false }); await render({ enabled: true }); expect(result.confirmed).toBe(false); expect(result.submission).toBeNull(); });
test('parent refresh and version changes require a fresh quote', async () => { await prepareQuote(); await act(async () => result.refresh()); expect(result.confirmed).toBe(false); await render({ parentVersion: 5 }); expect(result.confirmed).toBe(false); });
test('inflight quote is ignored after edit ABA', async () => {
  localStorage.clear(); await render({ preview: true }); await act(async () => result.setTariffVersion('v1'));
  let resolve; transport.post.mockImplementation(() => new Promise((done) => { resolve = done; })); let pending;
  await act(async () => { pending = result.requestQuote(); }); const first = props.form;
  await render({ form: { ...first, description: 'Description B' } }); await render({ form: first });
  await act(async () => { resolve(quote()); await pending; }); expect(result.quote).toBeNull();
});

test.each(['account_disabled', 'is_disabled'])('same actor/token becoming disabled via %s retires transport', async (field) => {
  await render(); const before = axios.create.mock.calls.length; transport.get.mockClear();
  await render({ actor: { ...actor, [field]: true } }); await event('focus'); expect(axios.create.mock.calls.length).toBe(before); expect(transport.get).not.toHaveBeenCalled(); expect(result.available).toBe(false);
});
test.each([true, null, 'false', 0])('disabled marker %p prevents quote transport', async (value) => {
  localStorage.clear(); await render({ preview: true, actor: { ...actor, account_disabled: value } }); expect(axios.create).not.toHaveBeenCalled(); expect(result.readyToQuote).toBe(false);
});
test('original financial intent arriving during quote prevents publication without storage event', async () => {
  localStorage.clear(); await render({ preview: true }); await act(async () => result.setTariffVersion('v1')); let resolve, pending;
  transport.post.mockImplementation(() => new Promise((done) => { resolve = done; })); await act(async () => { pending = result.requestQuote(); });
  localStorage.setItem('prodelivery:order-financial-event:v1:owner:restaurant:r1', '{');
  await act(async () => { resolve(quote()); await pending; }); expect(result.quote).toBeNull(); expect(result.confirmed).toBe(false); expect(result.error).not.toBe('');
});
