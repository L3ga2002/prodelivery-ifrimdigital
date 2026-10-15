import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { toast } from 'sonner';
import { useOrderCreationRecovery } from '../hooks/useOrderCreationRecovery';
jest.mock('axios', () => ({ get: jest.fn(), post: jest.fn(), create: jest.fn(), defaults: {}, interceptors: { response: { use: jest.fn() } } }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() } }));
jest.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: { id: 'actor', role: 'admin' }, token: 'synthetic-token' }) }));
jest.mock('../context/ThemeContext', () => ({ useTheme: () => ({ isDark: false }) }));
jest.mock('../hooks/useNetworkStatus', () => ({ useNetworkStatus: () => ({ isOnline: true }) }));
jest.mock('../hooks/useOrderCreationRecovery', () => ({ useOrderCreationRecovery: jest.fn() }));
jest.mock('../hooks/useOrderEditingRecovery', () => ({ useOrderEditingRecovery: () => ({ capability: { ready: true, enabled: false } }) }));
jest.mock('../hooks/useOrderAssignmentRecovery', () => ({ useOrderAssignmentRecovery: () => ({ capability: { ready: true, enabled: false } }) }));
jest.mock('../hooks/useOrderStatusRecovery', () => ({ useOrderStatusRecovery: () => ({ capability: { ready: true, enabled: false } }), OrderStatusRecoveryPanel: () => null }));
jest.mock('../hooks/useOrderCustodyRecovery', () => ({ useOrderCustodyRecovery: () => ({}) }));
jest.mock('../components/OrderCustody', () => ({ CustodyRecoveryPanel: () => null }));
jest.mock('../components/admin/OrderCorrectionDialog', () => ({ OrderCorrectionDialog: () => null }));
jest.mock('../components/admin/OrdersTab', () => ({ OrdersTab: () => null }));
jest.mock('../components/admin/AdminCommandCenter', () => ({ AdminCommandCenter: ({ onNewOrder }) => <button data-testid="open-create" onClick={onNewOrder}>Comandă nouă</button> }));
jest.mock('../components/admin/LiveMapPanel', () => ({ LiveMapPanel: () => null }));
jest.mock('../components/admin/RestaurantsTab', () => ({ RestaurantsTab: () => null }));
jest.mock('../components/admin/SettingsTab', () => ({ SettingsTab: () => null }));
jest.mock('../components/admin/DriverManagementDialog', () => ({ DriverManagementDialog: () => null }));
jest.mock('../components/admin/MapMarkerIcons', () => ({ restaurantIcon: {} }));
jest.mock('../components/AdminScheduleView', () => ({ AdminScheduleView: () => null }));
jest.mock('../components/DriverAvatar', () => ({ DriverAvatar: () => null }));
jest.mock('../components/LocationAutocomplete', () => ({ LocationAutocomplete: () => null }));
jest.mock('react-leaflet', () => ({ MapContainer: ({ children }) => <div>{children}</div>, TileLayer: () => null,
  Marker: ({ position }) => <span data-testid="selected-marker">{position.join(',')}</span>, Popup: () => null,
  useMap: () => ({ setView: jest.fn() }), useMapEvents: jest.fn() }));
jest.mock('leaflet/dist/leaflet.css', () => ({}));
jest.mock('recharts', () => ({ BarChart: () => null, Bar: () => null, XAxis: () => null, YAxis: () => null, CartesianGrid: () => null, Tooltip: () => null, ResponsiveContainer: () => null }));
jest.mock('../components/ui/tabs', () => ({ Tabs: ({ children }) => <div>{children}</div>, TabsList: () => null, TabsTrigger: () => null,
  TabsContent: ({ value, children }) => value === 'orders' ? <div>{children}</div> : null }));
jest.mock('../components/ui/dialog', () => {
  const Part = ({ children }) => <div>{children}</div>;
  return { Dialog: ({ open, children }) => open ? <div>{children}</div> : null, DialogContent: Part, DialogDescription: Part, DialogHeader: Part, DialogTitle: Part, DialogFooter: Part };
});
process.env.REACT_APP_BACKEND_URL = 'https://synthetic.invalid';
const AdminDashboard = jest.requireActual('./AdminDashboard').default;
const { useMapEvents } = jest.requireMock('react-leaflet');
const quote = { contract_version: 1, kind: 'create', informational: true, fingerprint_scope: 'server_key_v1', quote_fingerprint: 'a'.repeat(64), actor_id: 'actor', restaurant_id: 'r',
  parent_order_id: null, parent_order_version: null, currency: 'RON', tariff_version: 'v1', products_bani: 1234, collection_mode: 'cash', client_collection_bani: 1234,
  restaurant_transport_bani: 1600, courier_remuneration_bani: 975, advance_required_bani: 1234, advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null,
  basis: 'zone', zone_id: 'z', zone_name: 'Zone', zone_sector: null, zone_level: null };
let root, container, recovery, transport, zoneResolve;
const node = (id) => container.querySelector(`[data-testid="${id}"]`);
const render = () => act(async () => root.render(<AdminDashboard />));
const click = (id) => act(async () => { expect(node(id)).not.toBeNull(); node(id).click(); });
const input = (id, value) => act(async () => { const el = node(id); Object.getOwnPropertyDescriptor(el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value').set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); });
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; jest.clearAllMocks();
  recovery = { record: null, capability: { ready: true, enabled: false }, submit: jest.fn(async () => null), acknowledge: jest.fn(async () => true),
    captureIntent: jest.fn(() => ({ client_operation_id: 'operation_finance_0001' })), isCurrentIntent: jest.fn(() => true), recover: jest.fn(), retrySubmission: jest.fn(), resume: jest.fn(), closeIntent: jest.fn() };
  useOrderCreationRecovery.mockImplementation(() => recovery);
  axios.get.mockImplementation(async (url) => ({ data: url.endsWith('/restaurants') ? [{ id: 'r', name: 'Synthetic Restaurant', address: 'Street' }] : url.endsWith('/orders') || url.endsWith('/drivers') ? [] : {} }));
  axios.post.mockImplementation(() => new Promise((done) => { zoneResolve = done; }));
  transport = { get: jest.fn(async (url) => ({ status: 200, data: url.includes('/capabilities?') ? { contract_version: 1, actor_id: 'actor', restaurant_id: 'r', finance_enabled: true,
    create_quote_enabled: true, remake_quote_enabled: true, quote_informational: true, supported_basis: ['zone'] } : { contract_version: 1, actor_id: 'actor', restaurant_id: 'r', tariffs: [{ version: 'v1', currency: 'RON', zone_ids: ['z'] }] } })),
    post: jest.fn(async () => ({ status: 200, data: quote })) };
  axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
const filled = async () => {
  await render(); await click('open-create'); await click('new-order-restaurant-select'); await click('new-order-restaurant-option-r');
  await input('new-order-customer-name-input', 'Synthetic Customer'); await input('new-order-customer-phone-input', '0700000000');
  await input('new-order-address-input', 'Synthetic Street'); await input('new-order-notes-input', 'Private note'); await input('new-order-subtotal-input', '12,34');
  await act(async () => useMapEvents.mock.calls.at(-1)[0].click({ latlng: { lat: 0, lng: 1 } }));
  await act(async () => zoneResolve({ data: { zone_id: 'z', zone_name: 'Zone', fee: 999, zone_level: null } }));
};
const quoted = async () => {
  await filled(); await act(async () => { node('finance-tariff-select').value = 'v1'; node('finance-tariff-select').dispatchEvent(new Event('change', { bubbles: true })); });
  await click('finance-request-quote');
};
test('financial manual form keeps contact/notes/source and empty items, explicit money; no editable fee or auto tariff', async () => {
  await filled(); expect(node('new-order-subtotal-input').type).toBe('text'); expect(node('new-order-delivery-fee')).toBeNull(); expect(node('new-order-total-amount')).toBeNull();
  expect(node('finance-tariff-select').value).toBe(''); expect(node('new-order-submit-button').disabled).toBe(true); expect(node('selected-marker').textContent).toBe('0,1'); expect(transport.post).not.toHaveBeenCalled();
});
test('quote is preview with null payments; submit only after explicit confirmation sends exact manual capabilities', async () => {
  await quoted(); expect(node('finance-quote-values').textContent).toContain('Neconsemnat'); expect(node('new-order-submit-button').disabled).toBe(true);
  await click('finance-confirm-quote'); await click('new-order-submit-button'); expect(recovery.submit).toHaveBeenCalledTimes(1);
  expect(recovery.submit.mock.calls[0][0]).toMatchObject({ order: { restaurant_id: 'r', customer_name: 'Synthetic Customer', customer_phone: '0700000000', customer_address: 'Synthetic Street', notes: 'Private note', source: 'S', items: [], total_amount: 12.34, subtotal_amount: 12.34 },
    financial: { products_bani: 1234, tariff_version: 'v1', zone_id: 'z' }, quote_confirmation: { contract_version: 1, quote_fingerprint: 'a'.repeat(64) } });
  expect(recovery.submit.mock.calls[0][0].order.delivery_fee).toBeUndefined(); expect(toast.success).not.toHaveBeenCalledWith('Comandă creată!');
});
test('editing notes invalidates displayed confirmation and stops submit', async () => {
  await quoted(); await click('finance-confirm-quote'); await input('new-order-notes-input', 'Changed'); expect(node('finance-confirm-quote')).toBeNull(); expect(node('new-order-submit-button').disabled).toBe(true);
});
test('financial terminal list failure preserves identity by withholding ACK', async () => {
  await render(); recovery.record = { version: 2, client_operation_id: 'operation_finance_0001', receipt: { state: 'applied' } }; await render(); await click('open-create');
  axios.get.mockRejectedValue({ response: { status: 400 } }); await click('new-order-another-button'); expect(recovery.acknowledge).not.toHaveBeenCalled(); expect(toast.warning).toHaveBeenCalled();
});
test('successful refresh precedes financial ACK and changed intent prevents UI reset', async () => {
  await filled(); recovery.record = { version: 2, client_operation_id: 'operation_finance_0001', receipt: { state: 'applied' } }; await render();
  recovery.acknowledge.mockImplementation(async () => { expect(axios.get).toHaveBeenCalledWith('https://synthetic.invalid/api/orders'); return true; });
  recovery.isCurrentIntent.mockImplementation((_proof, acknowledged) => !acknowledged); await click('new-order-another-button'); expect(recovery.acknowledge).toHaveBeenCalledTimes(1);
  expect(node('new-order-customer-name-input').value).toBe('Synthetic Customer'); expect(toast.success).not.toHaveBeenCalledWith('Comanda salvată a fost verificată.');
});
