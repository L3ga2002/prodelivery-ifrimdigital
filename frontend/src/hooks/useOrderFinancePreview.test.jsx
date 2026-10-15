import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { useOrderFinancePreview } from './useOrderFinancePreview';
import { normalizeCreateOrder } from '../lib/orderCreationRecovery';
jest.mock('axios', () => ({ create: jest.fn() }));
const form = { restaurant_id: 'r', customer_name: 'Synthetic', customer_phone: '0700000000', customer_address: 'Street',
  customer_latitude: 0, customer_longitude: 1, delivery_zone_id: 'z', items: [], payment_type: 'CASH', notes: 'A' };
const capability = (enabled = true) => ({ status: 200, data: { contract_version: 1, actor_id: 'actor', restaurant_id: 'r', finance_enabled: enabled,
  create_quote_enabled: enabled, remake_quote_enabled: enabled, quote_informational: true, supported_basis: ['zone'] } });
const tariffs = { status: 200, data: { contract_version: 1, actor_id: 'actor', restaurant_id: 'r', tariffs: [{ version: 'v1', currency: 'RON', zone_ids: ['z'] }] } };
const quote = { status: 200, data: { contract_version: 1, kind: 'create', informational: true, fingerprint_scope: 'server_key_v1', quote_fingerprint: 'a'.repeat(64),
  actor_id: 'actor', restaurant_id: 'r', parent_order_id: null, parent_order_version: null, currency: 'RON', tariff_version: 'v1', products_bani: 1234,
  collection_mode: 'cash', client_collection_bani: 1234, restaurant_transport_bani: 1600, courier_remuneration_bani: 975, advance_required_bani: 1234,
  advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null, basis: 'zone', zone_id: 'z', zone_name: 'Zone', zone_sector: null, zone_level: null } };
let root, container, result, transport, props;
function Harness() { result = useOrderFinancePreview(props); return null; }
const render = (patch = {}) => act(async () => { props = { ...props, ...patch }; root.render(<Harness />); });
const confirm = async () => { await act(async () => result.setTariffVersion('v1')); await act(async () => result.requestQuote()); await act(async () => result.confirm(true)); expect(result.readyToSubmit).toBe(true); };
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; jest.clearAllMocks();
  props = { actorId: 'actor', apiUrl: 'https://synthetic.invalid', token: 'token', role: 'admin', form: { ...form }, rawProducts: '12,34', normalizeOrder: normalizeCreateOrder };
  transport = { get: jest.fn(async (url) => url.includes('/capabilities?') ? capability() : tariffs), post: jest.fn(async () => quote) };
  axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
test('discovery does not choose a tariff or quote and manual confirmation sends canonical contact draft', async () => {
  await render(); expect(result.mode).toBe('financial'); expect(result.tariffVersion).toBe(''); expect(result.readyToSubmit).toBe(false); expect(transport.post).not.toHaveBeenCalled();
  await confirm(); expect(result.submission.order.items).toEqual([]); expect(result.submission.order.customer_latitude).toBe(0); expect(result.submission.order.delivery_fee).toBeUndefined();
  expect(transport.post.mock.calls[0][1].financial).toEqual({ contract_version: 1, tariff_version: 'v1', products_bani: 1234, basis: 'zone', zone_id: 'z' });
});
test('note edit then revert never revives confirmation', async () => {
  await render(); await confirm(); await render({ form: { ...form, notes: 'B' } }); expect(result.confirmed).toBe(false);
  await render({ form: { ...form } }); expect(result.quote).toBeNull(); expect(result.readyToSubmit).toBe(false);
});
test('same-coordinate zone detection start and finish invalidates existing confirmation', async () => {
  await render(); await confirm(); await render({ zonePending: true }); expect(result.quote).toBeNull(); await render({ zonePending: false }); expect(result.confirmed).toBe(false);
});
test('external intent then external ACK cannot revive quote when enabled returns', async () => {
  await render(); await confirm(); await render({ enabled: false }); await render({ enabled: true }); expect(result.quote).toBeNull(); expect(result.confirmed).toBe(false);
});
test('pre-detection quote response cannot land after unchanged zone refresh', async () => {
  await render(); await act(async () => result.setTariffVersion('v1')); let resolve, flight;
  transport.post.mockImplementation(() => new Promise((done) => { resolve = done; })); await act(async () => { flight = result.requestQuote(); });
  await render({ zonePending: true }); await render({ zonePending: false }); await act(async () => { resolve(quote); await flight; }); expect(result.quote).toBeNull();
});
test('token changes invalidate confirmed quote and explicit tariff selection', async () => {
  await render(); await confirm(); await render({ token: 'new-token' }); expect(result.quote).toBeNull(); expect(result.tariffVersion).toBe(''); expect(result.readyToSubmit).toBe(false);
});
test('explicit marker false permits legacy before engagement', async () => {
  transport.get.mockResolvedValue(capability(false)); await render(); expect(result.mode).toBe('legacy'); expect(result.readyToSubmit).toBe(false);
});
test('discovery failure is not marker false', async () => {
  transport.get.mockRejectedValue(new Error('synthetic unavailable')); await render(); expect(result.mode).toBe('unknown'); expect(result.error).toBeTruthy();
});
test('marker false after financial engagement never falls back', async () => {
  await render(); transport.get.mockResolvedValue(capability(false)); await act(async () => result.refresh()); expect(result.mode).toBe('financial'); expect(result.readyToSubmit).toBe(false);
});
test('empty raw money cannot silently quote zero', async () => {
  await render({ rawProducts: '' }); await act(async () => result.setTariffVersion('v1')); await act(async () => result.requestQuote()); expect(transport.post).not.toHaveBeenCalled(); expect(result.readyToSubmit).toBe(false);
});
test('inactive financial form creates no transport or requests', async () => {
  await render({ enabled: false }); expect(axios.create).not.toHaveBeenCalled(); expect(transport.get).not.toHaveBeenCalled(); expect(transport.post).not.toHaveBeenCalled();
});
