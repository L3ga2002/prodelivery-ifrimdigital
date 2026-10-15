import { act, createContext as mockCreateContext, useContext as mockUseContext } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { toast } from 'sonner';
import { useAuth } from '../context/AuthContext';
import { useNetworkStatus } from '../hooks/useNetworkStatus';
jest.mock('axios', () => ({ get: jest.fn(), post: jest.fn(), put: jest.fn(), create: jest.fn(), defaults: {}, interceptors: { response: { use: jest.fn() } } }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() } }));
jest.mock('../context/AuthContext', () => ({ useAuth: jest.fn() }));
jest.mock('../context/ThemeContext', () => ({ useTheme: () => ({ isDark: false, toggleTheme: jest.fn() }) }));
jest.mock('../hooks/useNetworkStatus', () => ({ useNetworkStatus: jest.fn() }));
jest.mock('../hooks/useOrderCreationRecovery', () => ({ useOrderCreationRecovery: () => ({ capability: { ready: true, enabled: false } }) }));
jest.mock('../hooks/useOrderEditingRecovery', () => ({ useOrderEditingRecovery: () => ({ capability: { ready: true, enabled: false } }) }));
jest.mock('../components/admin/OrderCorrectionDialog', () => ({ OrderCorrectionDialog: () => null }));
jest.mock('../components/admin/OrdersTab', () => ({ OrdersTab: ({ activeOrders }) => <div data-testid="orders-list">{activeOrders.map((o) => <p key={o.id}>{o.status}</p>)}</div> }));
jest.mock('../components/admin/AdminCommandCenter', () => ({ AdminCommandCenter: () => null }));
jest.mock('../components/admin/LiveMapPanel', () => ({ LiveMapPanel: () => null }));
jest.mock('../components/admin/RestaurantsTab', () => ({ RestaurantsTab: () => null }));
jest.mock('../components/admin/SettingsTab', () => ({ SettingsTab: () => null }));
jest.mock('../components/admin/DriverManagementDialog', () => ({ DriverManagementDialog: () => null }));
jest.mock('../components/admin/MapMarkerIcons', () => ({ restaurantIcon: {} }));
jest.mock('../components/AdminScheduleView', () => ({ AdminScheduleView: () => null }));
jest.mock('../components/DriverSchedule', () => ({ DriverSchedule: () => null }));
jest.mock('../components/AvatarUploadCropper', () => ({ AvatarUploadCropper: () => null }));
jest.mock('../components/DriverAvatar', () => ({ DriverAvatar: () => null }));
jest.mock('../components/LocationAutocomplete', () => ({ LocationAutocomplete: () => null }));
jest.mock('../components/admin/RestaurantAnalyticsPanel', () => ({ RestaurantAnalyticsPanel: () => null }));
jest.mock('react-leaflet', () => ({ MapContainer: () => null, TileLayer: () => null, Marker: () => null, Popup: () => null, useMap: jest.fn(), useMapEvents: jest.fn() }));
jest.mock('leaflet/dist/leaflet.css', () => ({}));
jest.mock('recharts', () => ({ BarChart: () => null, Bar: () => null, XAxis: () => null, YAxis: () => null,
  CartesianGrid: () => null, Tooltip: () => null, ResponsiveContainer: () => null }));
jest.mock('../components/ui/tabs', () => ({ Tabs: ({ children }) => <div>{children}</div>, TabsList: () => null,
  TabsTrigger: () => null, TabsContent: ({ value, children }) => value === 'orders' ? <div>{children}</div> : null }));
jest.mock('../components/ui/dialog', () => {
  const Part = ({ children, ...props }) => <div data-testid={props['data-testid']}>{children}</div>;
  return { Dialog: ({ open, children }) => open ? <div>{children}</div> : null,
    DialogContent: Part, DialogDescription: Part, DialogHeader: Part, DialogTitle: Part, DialogFooter: Part };
});
jest.mock('../components/ui/select', () => {
  const Context = mockCreateContext({});
  const Part = ({ children, ...props }) => <div data-testid={props['data-testid']}>{children}</div>;
  return { Select: ({ children, onValueChange, disabled }) => <Context.Provider value={{ onValueChange, disabled }}>{children}</Context.Provider>,
    SelectTrigger: Part, SelectValue: () => null, SelectContent: Part,
    SelectItem: ({ value, children }) => { const c = mockUseContext(Context); return <button data-value={value} disabled={c.disabled} onClick={() => c.onValueChange?.(value)}>{children}</button>; } };
});
process.env.REACT_APP_BACKEND_URL = 'https://qa.invalid';
const DriverApp = jest.requireActual('./DriverApp').default;
const RestaurantApp = jest.requireActual('./RestaurantApp').default;
const AdminDashboard = jest.requireActual('./AdminDashboard').default;
const ID = '123e4567-e89b-42d3-a456-426614174000';
const KEY = 'prodelivery:order-status:v1:actor';
const order = { id: 'order', restaurant_id: 'restaurant', driver_id: 'driver', order_version: 4, status: 'ASSIGNED',
  preparation_status: 'READY', order_number: 'QA-1', customer_name: 'Synthetic Customer', customer_phone: '0700000000',
  customer_address: 'Synthetic Address', restaurant_name: 'Synthetic Restaurant', total_amount: 100, items: [] };
const done = { status: 200, data: { client_operation_id: ID, state: 'applied', order_id: 'order', order_version: 5 } };
const pending = { status: 202, headers: { 'retry-after': '1' }, data: { client_operation_id: ID, state: 'pending', retry_after_seconds: 1 } };
let root, container, orders, transport, user, enabled;
const node = (id) => container.querySelector(`[data-testid="${id}"]`);
const click = (id) => act(async () => { const el = node(id); expect(el).not.toBeNull(); el.click(); });
const type = (id, value) => act(async () => {
  const el = node(id); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
const typeInput = (id, value) => act(async () => {
  const el = node(id); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
const mount = async (role, source = order) => {
  user = { id: 'actor', role, name: 'Synthetic User', ...(role === 'driver' ? { driver_id: 'driver' } : role === 'restaurant' ? { restaurant_id: 'restaurant' } : {}) };
  orders = source ? [{ ...source }] : []; useAuth.mockReturnValue({ user, token: 'token-a', logout: jest.fn() });
  await act(async () => root.render(role === 'driver' ? <DriverApp /> : role === 'restaurant' ? <RestaurantApp /> : <AdminDashboard />));
};
const adminSelect = async () => { await click('status-open-button'); await act(async () => node('admin-status-dialog').querySelector('[data-value="order"]').click()); };
const dashboard = (operational_status = 'delivery', extra = {}) => ({ status: 200, data: { driver: {
  id: 'driver', name: 'Server Driver', first_name: 'Server', operational_status,
  operational_status_label: operational_status === 'delivery' ? 'In livrare' : 'Activ',
  total_deliveries: 7, total_earnings: 70, ...extra } } });
const driverAction = async (status) => {
  await click('driver-nav-delivery-button');
  if (status === 'CANCELLED') { await click('cancel-order-button'); await type('driver-cancel-reason-input', 'Exact driver reason'); await click('driver-confirm-cancel-btn'); }
  else { await click('deliver-button'); await click('confirm-action-btn'); }
};
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear(); jest.clearAllMocks(); enabled = true;
  useNetworkStatus.mockReturnValue({ isOnline: true });
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_k, _o, cb) => cb({}) } });
  Object.defineProperty(window, 'crypto', { configurable: true, value: { randomUUID: jest.fn(() => ID) } });
  axios.get.mockImplementation(async (url) => ({ status: 200, data: url.includes('/api/orders') ? orders.map((o) => ({ ...o })) :
    url.endsWith('/drivers') || url.endsWith('/restaurants') ? [] : url.endsWith('/dashboard') ? { driver: { id: 'driver', name: 'Driver', operational_status: 'offline' } } :
      url.endsWith('/prep-availability') ? { available_drivers: 1 } : {} }));
  transport = { get: jest.fn(async (url) => url.endsWith('/api/auth/me') ? { status: 200, data: user } :
    url.includes('/status/') && url.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: enabled } } :
      url.endsWith('capabilities') ? { status: 200, data: { assign_recovery_enabled: false } } : done),
    post: jest.fn(async (_url, body) => { orders = orders.map((o) => ({ ...o, status: body?.status || 'DELIVERED', order_version: 5 })); return done; }),
    put: jest.fn(async (_url, body) => { orders = orders.map((o) => ({ ...o, status: body.status })); return { status: 200 }; }) };
  axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); await Promise.resolve(); container.remove(); });

test('driver accept uses receipt/header/CAS, keeps amounts, disables another status until acknowledgment', async () => {
  await mount('driver'); await click('driver-nav-delivery-button'); await click('accept-button');
  expect(transport.post.mock.calls[0][1]).toEqual({ client_operation_id: ID, expected_order_version: 4, status: 'ACCEPTED' });
  expect(transport.post.mock.calls[0][2].headers['X-Expected-Actor-ID']).toBe('actor');
  expect(node('status-recovery-state').textContent).toContain('confirmat'); expect(node('pickup-button').disabled).toBe(true);
  expect(node('order-details-card').textContent).toContain('100 RON'); expect(transport.put).not.toHaveBeenCalled();
  await click('status-acknowledge-button'); expect(node('pickup-button').disabled).toBe(false);
});
test.each([['ACCEPTED', 'pickup-button', 'PICKED_UP'], ['PICKED_UP', 'deliver-button', 'DELIVERED']])('driver %s guarded confirmation reaches %s', async (source, button, status) => {
  await mount('driver', { ...order, status: source }); await click('driver-nav-delivery-button'); await click(button); await click('confirm-action-btn');
  expect(transport.post.mock.calls[0][1].status).toBe(status); expect(node('status-recovery-state')).not.toBeNull();
  if (status === 'DELIVERED') expect(node('action-buttons')).toBeNull();
});
test('driver not-ready pickup unavailable and postpickup versioned cancel absent', async () => {
  await mount('driver', { ...order, status: 'ACCEPTED', preparation_status: 'PREPARING' }); await click('driver-nav-delivery-button');
  expect(node('pickup-button').disabled).toBe(true); await click('pickup-button'); expect(transport.post).not.toHaveBeenCalled();
  orders = [{ ...order, status: 'PICKED_UP' }]; await click('refresh-button'); expect(node('cancel-order-button')).toBeNull();
});
test.each(['DELIVERED', 'CANCELLED'])('PROFILE RED: confirmed driver %s refreshes actual status and financial counters', async (status) => {
  let currentDashboard = dashboard(); const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation(async (url, options) => url.endsWith('/dashboard') ? currentDashboard : initialGet(url, options));
  await mount('driver', { ...order, status: status === 'DELIVERED' ? 'PICKED_UP' : 'ACCEPTED' });
  await click('driver-nav-delivery-button'); expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('In livrare');
  const callsBefore = axios.get.mock.calls.filter(([url]) => url.endsWith('/dashboard')).length;
  currentDashboard = dashboard('active', { total_deliveries: status === 'DELIVERED' ? 8 : 7, total_earnings: status === 'DELIVERED' ? 80 : 70 });
  await driverAction(status);
  expect(axios.get.mock.calls.filter(([url]) => url.endsWith('/dashboard')).length).toBeGreaterThan(callsBefore);
  expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
  expect(node('driver-no-delivery-state')).not.toBeNull(); await click('driver-nav-home-button');
  const values = node('driver-today-summary-card').querySelectorAll('.grid p');
  expect(values[0].textContent).toBe(status === 'DELIVERED' ? '8' : '7');
  expect(values[4].textContent).toBe(status === 'DELIVERED' ? '80.00' : '70.00');
  expect(transport.post).toHaveBeenCalledTimes(1); expect(transport.put).not.toHaveBeenCalled();
});
test.each(['DELIVERED', 'CANCELLED'])('driver legacy %s refreshes actual dashboard without status capability or financial guess', async (status) => {
  let currentDashboard = dashboard(); const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation(async (url, options) => url.endsWith('/dashboard') ? currentDashboard : initialGet(url, options));
  const legacy = { ...order, status: status === 'DELIVERED' ? 'PICKED_UP' : 'ACCEPTED' }; delete legacy.order_version;
  await mount('driver', legacy); currentDashboard = dashboard('active', { total_deliveries: 19, total_earnings: 123.45 });
  await driverAction(status); expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
  await click('driver-nav-home-button'); const values = node('driver-today-summary-card').querySelectorAll('.grid p');
  expect(values[0].textContent).toBe('19'); expect(values[4].textContent).toBe('123.45');
  expect(transport.put).toHaveBeenCalledTimes(1); expect(transport.post).not.toHaveBeenCalled();
  expect(transport.get.mock.calls.some(([url]) => url.endsWith('/status/capabilities'))).toBe(false);
});
test.each([['ASSIGNED', 'accept-button'], ['ACCEPTED', 'pickup-button']])('driver confirmed custody from %s refreshes server operational label', async (status, button) => {
  let currentDashboard = dashboard('active'); const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation(async (url, options) => url.endsWith('/dashboard') ? currentDashboard : initialGet(url, options));
  await mount('driver', { ...order, status }); await click('driver-nav-delivery-button');
  currentDashboard = dashboard(); await click(button); if (button === 'pickup-button') await click('confirm-action-btn');
  expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('In livrare');
  expect(axios.get.mock.calls.filter(([url]) => url.endsWith('/dashboard'))).toHaveLength(2);
});
test('driver pre-action initial dashboard cannot restore delivery label or old financial counters after release', async () => {
  let release, reads = 0; const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation((url, options) => {
    if (!url.endsWith('/dashboard')) return initialGet(url, options);
    reads++; return reads === 1 ? new Promise((resolve) => { release = resolve; }) : Promise.resolve(dashboard('active', { total_deliveries: 8, total_earnings: 80 }));
  });
  await mount('driver', { ...order, status: 'PICKED_UP' }); await driverAction('DELIVERED');
  expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
  await act(async () => release(dashboard())); expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
  await click('driver-nav-home-button'); const values = node('driver-today-summary-card').querySelectorAll('.grid p');
  expect(values[0].textContent).toBe('8'); expect(values[4].textContent).toBe('80.00');
});
test('driver out-of-order dashboard refresh cannot overwrite newer server profile and counters', async () => {
  let release, reads = 0; const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation((url, options) => {
    if (!url.endsWith('/dashboard')) return initialGet(url, options);
    reads++; return reads === 2 ? new Promise((resolve) => { release = resolve; }) : Promise.resolve(reads === 1 ? dashboard() :
      dashboard('active', { total_deliveries: 8, total_earnings: 80, first_name: 'Fresh' }));
  });
  await mount('driver', { ...order, status: 'PICKED_UP' }); await driverAction('DELIVERED');
  await click('driver-status-update-button'); expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
  await act(async () => release(dashboard())); expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
  await click('driver-nav-profile-button'); expect(node('driver-profile-first-name-input').value).toBe('Fresh');
  await click('driver-nav-home-button'); expect(node('driver-today-summary-card').querySelectorAll('.grid p')[4].textContent).toBe('80.00');
});
test.each([
  [{ id: 'other', driver_id: 'other-driver' }, 'other-token'],
  [{ driver_id: 'other-driver' }, 'token-a'],
  [{}, 'rotated-token'],
])('driver profile account/resource/token switch %j fences late initial profile', async (replacement, token) => {
  let release, reads = 0; const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation((url, options) => {
    if (!url.endsWith('/dashboard')) return initialGet(url, options);
    reads++; return reads === 1 ? new Promise((resolve) => { release = resolve; }) : Promise.resolve(dashboard('active',
      { id: replacement.driver_id || 'driver', first_name: 'New', total_earnings: 777.77 }));
  });
  await mount('driver'); user = { ...user, ...replacement }; orders = [];
  useAuth.mockReturnValue({ user, token, logout: jest.fn() }); await act(async () => root.render(<DriverApp />));
  const call = axios.get.mock.calls.filter(([url]) => url.endsWith('/dashboard'))[1];
  expect(call[0]).toBe(`https://qa.invalid/api/drivers/${user.driver_id}/dashboard`);
  expect(call[1]).toEqual({ timeout: 15000, headers: { Authorization: `Bearer ${token}`, 'X-Expected-Actor-ID': user.id } });
  await act(async () => release(dashboard())); await click('driver-nav-profile-button');
  expect(node('driver-profile-first-name-input').value).toBe('New'); expect(node('driver-profile-status-badge').textContent).toBe('Activ');
  await click('driver-nav-home-button'); expect(node('driver-today-summary-card').querySelectorAll('.grid p')[4].textContent).toBe('777.77');
});
test('driver post-receipt profile read cannot publish into replacement account', async () => {
  let release, reads = 0; const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation((url, options) => {
    if (!url.endsWith('/dashboard')) return initialGet(url, options);
    reads++; return reads === 2 ? new Promise((resolve) => { release = resolve; }) : Promise.resolve(reads === 1 ? dashboard() :
      dashboard('active', { id: 'other-driver', first_name: 'Other', total_earnings: 999.99 }));
  });
  await mount('driver', { ...order, status: 'PICKED_UP' }); await driverAction('DELIVERED');
  user = { ...user, id: 'other', driver_id: 'other-driver' }; orders = [];
  useAuth.mockReturnValue({ user, token: 'other-token', logout: jest.fn() }); await act(async () => root.render(<DriverApp />));
  await act(async () => release(dashboard('active', { total_earnings: 80 })));
  await click('driver-nav-profile-button'); expect(node('driver-profile-first-name-input').value).toBe('Other');
  expect(node('status-recovery-state')).toBeNull(); await click('driver-nav-home-button');
  expect(node('driver-today-summary-card').querySelectorAll('.grid p')[4].textContent).toBe('999.99');
});
test('driver confirmed dashboard refresh preserves unsaved profile and operational forms', async () => {
  let currentDashboard = dashboard(); const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation(async (url, options) => url.endsWith('/dashboard') ? currentDashboard : initialGet(url, options));
  await mount('driver', { ...order, status: 'PICKED_UP' }); await click('driver-nav-profile-button');
  await typeInput('driver-profile-first-name-input', 'Unsaved draft'); await click('driver-nav-delivery-button');
  await act(async () => node('driver-delivery-tab').querySelector('[data-value="break"]').click());
  await typeInput('driver-break-minutes-input', '45'); currentDashboard = dashboard('active', { first_name: 'Server changed', total_earnings: 123.45 });
  await driverAction('DELIVERED'); expect(node('driver-break-minutes-input').value).toBe('45');
  expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ'); await click('driver-nav-profile-button');
  expect(node('driver-profile-first-name-input').value).toBe('Unsaved draft');
  await click('driver-nav-home-button'); expect(node('driver-today-summary-card').querySelectorAll('.grid p')[4].textContent).toBe('123.45');
});
test('driver awaiting receipt does not synthesize active status or refresh profile before server confirmation', async () => {
  let currentDashboard = dashboard(); const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation(async (url, options) => url.endsWith('/dashboard') ? currentDashboard : initialGet(url, options));
  let release; transport.post.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  await mount('driver', { ...order, status: 'PICKED_UP' }); await driverAction('DELIVERED');
  expect(axios.get.mock.calls.filter(([url]) => url.endsWith('/dashboard'))).toHaveLength(1);
  expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('In livrare'); expect(toast.success).not.toHaveBeenCalled();
  orders = []; currentDashboard = dashboard('active', { total_deliveries: 8, total_earnings: 80 }); await act(async () => release(done));
  expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
});
test('driver same-ID recovery after release refreshes dashboard without currentOrder', async () => {
  localStorage.setItem(KEY, JSON.stringify({ actor_id: 'actor', actor_role: 'driver', actor_resource_id: 'driver', order_id: 'order',
    expected_order_version: 4, status: 'DELIVERED', client_operation_id: ID, receipt: pending.data }));
  let reads = 0; const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation(async (url, options) => url.endsWith('/dashboard') ? (++reads === 1 ? dashboard() :
    dashboard('active', { total_deliveries: 8, total_earnings: 80 })) : initialGet(url, options));
  transport.get.mockResolvedValue(pending); transport.post.mockResolvedValue(done); await mount('driver', null);
  await click('driver-nav-delivery-button'); expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
  expect(node('driver-no-delivery-state')).not.toBeNull(); expect(reads).toBe(2);
  expect(transport.post.mock.calls[0][0]).toMatch(new RegExp(`/${ID}/resume$`)); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test('driver failed dashboard refresh retains cache but marks status and payout unavailable', async () => {
  let reads = 0; const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation(async (url, options) => {
    if (!url.endsWith('/dashboard')) return initialGet(url, options);
    if (++reads === 1) return dashboard(); throw { response: { status: 404 } };
  });
  await mount('driver', { ...order, status: 'PICKED_UP' }); await driverAction('DELIVERED');
  expect(node('status-recovery-state').textContent).toContain('confirmat');
  expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Neactualizat');
  expect(node('driver-profile-freshness').textContent).toContain('Status/incasari neactualizate');
  await click('driver-nav-profile-button'); expect(container.textContent).toContain('Server Driver');
  await click('driver-nav-home-button'); expect(node('driver-today-summary-card').querySelectorAll('.grid p')[4].textContent).toBe('--');
});
test.each([
  ['missing driver', { status: 200, data: {} }],
  ['missing ID', dashboard('active', { id: undefined })],
  ['unknown status', dashboard('available')],
  ['missing label', dashboard('active', { operational_status_label: undefined })],
  ['missing count', dashboard('active', { total_deliveries: undefined })],
  ['fractional count', dashboard('active', { total_deliveries: 1.5 })],
  ['string count', dashboard('active', { total_deliveries: '8' })],
  ['negative count', dashboard('active', { total_deliveries: -1 })],
  ['missing earnings', dashboard('active', { total_earnings: undefined })],
  ['string earnings', dashboard('active', { total_earnings: '80' })],
  ['NaN earnings', dashboard('active', { total_earnings: NaN })],
  ['infinite earnings', dashboard('active', { total_earnings: Infinity })],
  ['negative earnings', dashboard('active', { total_earnings: -1 })],
  ['unconfirmed HTTP', { ...dashboard('active'), status: 202 }],
])('driver freshness rejects %s after committed release without abandoning receipt', async (_name, invalid) => {
  let reads = 0; const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation(async (url, options) => url.endsWith('/dashboard') ? (++reads === 1 ? dashboard() : invalid) : initialGet(url, options));
  await mount('driver', { ...order, status: 'PICKED_UP' }); await driverAction('DELIVERED');
  expect(node('driver-profile-freshness').textContent).toContain('incomplet sau invalid');
  expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Neactualizat');
  expect(node('driver-profile-refresh-button').disabled).toBe(false); expect(reads).toBe(2);
  await click('driver-nav-home-button'); const values = node('driver-today-summary-card').querySelectorAll('.grid p');
  expect(values[0].textContent).toBe('--'); expect(values[4].textContent).toBe('--');
  expect(JSON.parse(localStorage.getItem(KEY)).receipt).toEqual(done.data);
  expect(transport.post).toHaveBeenCalledTimes(1); expect(transport.put).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1);
});
test('driver freshness manual read after committed-but-503 refresh is finite, preserves drafts/receipt and clears stale on valid server data', async () => {
  jest.useFakeTimers();
  try {
    let reads = 0, phase = 'failed', release; const initialGet = axios.get.getMockImplementation();
    axios.get.mockImplementation(async (url, options) => {
      if (!url.endsWith('/dashboard')) return initialGet(url, options);
      reads++; if (reads === 1) return dashboard();
      if (phase === 'failed') throw { response: { status: 503 } };
      return new Promise((resolve) => { release = resolve; });
    });
    await mount('driver', { ...order, status: 'PICKED_UP' }); await click('driver-nav-profile-button');
    await typeInput('driver-profile-first-name-input', 'Untouched draft'); await driverAction('DELIVERED');
    await act(async () => jest.advanceTimersByTime(500)); expect(reads).toBe(3);
    expect(node('driver-profile-freshness').textContent).toContain('Status/incasari neactualizate');
    const retained = localStorage.getItem(KEY); phase = 'manual';
    await act(async () => { node('driver-profile-refresh-button').click(); node('driver-profile-refresh-button').click(); });
    expect(reads).toBe(4); expect(node('driver-profile-refresh-button').disabled).toBe(true);
    expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Neactualizat');
    await act(async () => release(dashboard('active', { first_name: 'Server replacement', total_deliveries: 8, total_earnings: 876.54 })));
    expect(node('driver-profile-freshness')).toBeNull(); expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
    await click('driver-nav-profile-button'); expect(node('driver-profile-first-name-input').value).toBe('Untouched draft');
    await click('driver-nav-home-button'); const values = node('driver-today-summary-card').querySelectorAll('.grid p');
    expect(values[0].textContent).toBe('8'); expect(values[4].textContent).toBe('876.54');
    expect(localStorage.getItem(KEY)).toBe(retained); expect(transport.post).toHaveBeenCalledTimes(1);
    expect(transport.put).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1);
    await act(async () => jest.advanceTimersByTime(10000)); expect(reads).toBe(4);
  } finally { jest.useRealTimers(); }
});
test('driver freshness manual malformed retry stays stale and offline retry sends nothing', async () => {
  let currentDashboard = dashboard(); const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation(async (url, options) => url.endsWith('/dashboard') ? currentDashboard : initialGet(url, options));
  await mount('driver', { ...order, status: 'PICKED_UP' }); currentDashboard = dashboard('active', { total_earnings: null });
  await driverAction('DELIVERED'); const calls = axios.get.mock.calls.filter(([url]) => url.endsWith('/dashboard')).length;
  await click('driver-profile-refresh-button'); expect(node('driver-profile-freshness')).not.toBeNull();
  expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Neactualizat');
  expect(axios.get.mock.calls.filter(([url]) => url.endsWith('/dashboard'))).toHaveLength(calls + 1);
  useNetworkStatus.mockReturnValue({ isOnline: false }); await act(async () => root.render(<DriverApp />));
  expect(node('driver-profile-refresh-button').disabled).toBe(true); await click('driver-profile-refresh-button');
  expect(axios.get.mock.calls.filter(([url]) => url.endsWith('/dashboard'))).toHaveLength(calls + 1);
  expect(JSON.parse(localStorage.getItem(KEY)).receipt).toEqual(done.data); expect(transport.post).toHaveBeenCalledTimes(1);
});
test('driver freshness stale malformed response cannot invalidate a newer guarded successful read', async () => {
  let reads = 0, release; const initialGet = axios.get.getMockImplementation();
  axios.get.mockImplementation((url, options) => {
    if (!url.endsWith('/dashboard')) return initialGet(url, options);
    reads++; return reads === 1 ? new Promise((resolve) => { release = resolve; }) : Promise.resolve(dashboard('active', { total_deliveries: 8, total_earnings: 80 }));
  });
  await mount('driver', { ...order, status: 'PICKED_UP' }); await driverAction('DELIVERED');
  await act(async () => release(dashboard('active', { total_earnings: NaN })));
  expect(node('driver-profile-freshness')).toBeNull(); expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Activ');
  await click('driver-nav-home-button'); expect(node('driver-today-summary-card').querySelectorAll('.grid p')[4].textContent).toBe('80.00');
});
test.each(['HTTP503', 'foreign driver'])('FRESHNESS RED: committed driver release with %s keeps visible stale warning and manual read', async (failure) => {
  jest.useFakeTimers();
  try {
    let reads = 0; const initialGet = axios.get.getMockImplementation();
    axios.get.mockImplementation(async (url, options) => {
      if (!url.endsWith('/dashboard')) return initialGet(url, options);
      if (++reads === 1) return dashboard();
      if (failure === 'HTTP503') throw { response: { status: 503 } };
      return dashboard('active', { id: 'foreign' });
    });
    await mount('driver', { ...order, status: 'PICKED_UP' }); await driverAction('DELIVERED');
    await act(async () => jest.advanceTimersByTime(500));
    expect(node('driver-profile-freshness')).not.toBeNull();
    expect(node('driver-profile-freshness').textContent).toContain('Status/incasari neactualizate');
    expect(node('driver-profile-refresh-button').disabled).toBe(false);
    expect(node('driver-delivery-tab').querySelector('h2').textContent).toBe('Neactualizat');
    await click('driver-nav-home-button'); expect(node('driver-today-summary-card').querySelectorAll('.grid p')[4].textContent).toBe('--');
    expect(JSON.parse(localStorage.getItem(KEY)).receipt).toEqual(done.data); expect(transport.post).toHaveBeenCalledTimes(1);
  } finally { jest.useRealTimers(); }
});
test.each(['driver', 'restaurant', 'admin'])('%s versioned disabled marker disables action and makes zero legacy requests', async (role) => {
  enabled = false; await mount(role, role === 'restaurant' ? { ...order, status: 'NEW', preparation_status: 'NEW' } : order);
  if (role === 'driver') { await click('driver-nav-delivery-button'); expect(node('accept-button').disabled).toBe(true); await click('accept-button'); }
  if (role === 'restaurant') { await click('cancel-order'); await type('cancel-reason-input', 'reason'); expect(node('confirm-cancel-btn').disabled).toBe(true); await click('confirm-cancel-btn'); }
  if (role === 'admin') { await adminSelect(); expect(node('admin-status-accepted').disabled).toBe(true); await click('admin-status-accepted'); }
  expect(node('status-capability-state').textContent).toContain('legacy este blocat');
  expect(transport.put).not.toHaveBeenCalled(); expect(transport.post).not.toHaveBeenCalled();
});
test.each(['driver', 'restaurant', 'admin'])('%s missing revision keeps guarded legacy with no status capability probe', async (role) => {
  enabled = false; const legacy = { ...order, ...(role === 'restaurant' ? { status: 'NEW', preparation_status: 'NEW' } : {}) }; delete legacy.order_version;
  await mount(role, legacy);
  if (role === 'driver') { await click('driver-nav-delivery-button'); await click('accept-button'); }
  if (role === 'restaurant') { await click('cancel-order'); await type('cancel-reason-input', 'Legacy reason'); await click('confirm-cancel-btn'); }
  if (role === 'admin') { await adminSelect(); await click('admin-status-accepted'); }
  expect(transport.put).toHaveBeenCalledTimes(1); expect(transport.put.mock.calls[0][2].headers['X-Expected-Actor-ID']).toBe('actor');
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.get.mock.calls.some(([p]) => p.endsWith('/status/capabilities'))).toBe(false);
});
test('driver reload after delivery disappears still displays operation and recovers same ID', async () => {
  localStorage.setItem(KEY, JSON.stringify({ actor_id: 'actor', actor_role: 'driver', actor_resource_id: 'driver', order_id: 'order',
    expected_order_version: 4, status: 'DELIVERED', client_operation_id: ID, receipt: pending.data }));
  transport.get.mockImplementation(async (p) => p.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: false } } : pending);
  transport.post.mockResolvedValue(done); await mount('driver', null);
  expect(node('status-recovery-state').textContent).toContain('DELIVERED'); expect(node('status-recovery-state').textContent).toContain('confirmat');
  expect(transport.post.mock.calls[0][0]).toMatch(new RegExp(`/${ID}/resume$`)); expect(transport.post.mock.calls[0][1]).toBeUndefined();
  expect(transport.put).not.toHaveBeenCalled(); expect(node('action-buttons')).toBeNull();
});
test('unreachable lookup on delivery reload leaves visible uncertainty without currentOrder', async () => {
  localStorage.setItem(KEY, JSON.stringify({ actor_id: 'actor', actor_role: 'driver', actor_resource_id: 'driver', order_id: 'order',
    expected_order_version: 4, status: 'DELIVERED', client_operation_id: ID, receipt: null }));
  transport.get.mockRejectedValue({ response: { status: 503, data: { detail: { code: 'RECOVERY_UNAVAILABLE' } } } });
  await mount('driver', null); expect(node('status-recovery-state').textContent).toContain('neconfirmat');
  expect(node('status-recover-button')).not.toBeNull(); expect(toast.success).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
  expect(localStorage.getItem(KEY)).not.toBeNull();
});
test('pending driver submit keeps buttons disabled and no success until server receipt', async () => {
  transport.post.mockResolvedValue(pending);
  transport.get.mockImplementation(async (p) => p.endsWith('capabilities') ? { status: 200, data: { status_recovery_enabled: true } } : pending);
  await mount('driver'); await click('driver-nav-delivery-button'); await click('accept-button');
  expect(node('status-recovery-state').textContent).toContain('neconfirmat'); expect(node('accept-button').disabled).toBe(true);
  expect(node('status-acknowledge-button')).toBeNull(); expect(toast.success).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('restaurant cancellation exact reason only in server command, not durable metadata', async () => {
  await mount('restaurant', { ...order, status: 'NEW', preparation_status: 'NEW' });
  expect(transport.get.mock.calls.some(([p]) => p.endsWith('/status/capabilities'))).toBe(false);
  await click('cancel-order'); await type('cancel-reason-input', 'Private Cancellation Sentinel'); await click('confirm-cancel-btn');
  expect(transport.post.mock.calls[0][1]).toEqual({ client_operation_id: ID, expected_order_version: 4, status: 'CANCELLED', cancellation_reason: 'Private Cancellation Sentinel' });
  expect(localStorage.getItem(KEY)).not.toContain('Private'); expect(sessionStorage.length).toBe(0); expect(node('status-acknowledge-button')).not.toBeNull();
});
test.each(['ASSIGNED', 'ACCEPTED'])('FE-02 RED: own versioned restaurant %s can cancel before custody', async (status) => {
  await mount('restaurant', { ...order, status }); await click('restaurant-stat-preparing');
  await click('cancel-order'); await type('cancel-reason-input', 'Exact pre-custody reason'); await click('confirm-cancel-btn');
  expect(transport.post).toHaveBeenCalledTimes(1);
  expect(transport.post.mock.calls[0][1]).toEqual({ client_operation_id: ID, expected_order_version: 4,
    status: 'CANCELLED', cancellation_reason: 'Exact pre-custody reason' });
  expect(JSON.parse(localStorage.getItem(KEY))).toMatchObject({ actor_id: 'actor', actor_role: 'restaurant',
    actor_resource_id: 'restaurant', order_id: 'order', client_operation_id: ID, receipt: done.data });
  expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1); expect(transport.put).not.toHaveBeenCalled();
  expect(localStorage.getItem(KEY)).not.toContain('Exact pre-custody reason'); expect(sessionStorage.length).toBe(0);
});
test.each(['ASSIGNED', 'ACCEPTED'])('restaurant %s versioned disabled marker shows refusal and never uses legacy', async (status) => {
  enabled = false; await mount('restaurant', { ...order, status }); await click('restaurant-stat-preparing');
  await click('cancel-order'); await type('cancel-reason-input', 'reason');
  expect(node('confirm-cancel-btn').disabled).toBe(true); await click('confirm-cancel-btn');
  expect(node('status-capability-state').textContent).toContain('legacy este blocat');
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).not.toHaveBeenCalled();
});
test.each(['ASSIGNED', 'ACCEPTED'])('restaurant legacy %s retains original absence of cancel action', async (status) => {
  const legacy = { ...order, status }; delete legacy.order_version;
  await mount('restaurant', legacy); await click('restaurant-stat-preparing');
  expect(container.textContent).toContain('QA-1'); expect(node('cancel-order')).toBeNull();
  expect(transport.get.mock.calls.some(([p]) => p.endsWith('/status/capabilities'))).toBe(false);
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test.each(['ASSIGNED', 'ACCEPTED'])('restaurant foreign versioned %s has no cancel action', async (status) => {
  await mount('restaurant', { ...order, restaurant_id: 'foreign', status }); await click('restaurant-stat-preparing');
  expect(node('cancel-order')).toBeNull(); expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test.each(['PICKED_UP', 'DELIVERED'])('restaurant versioned %s has no simple cancellation', async (status) => {
  await mount('restaurant', { ...order, status }); await click(status === 'DELIVERED' ? 'restaurant-stat-delivered' : 'restaurant-stat-preparing');
  expect(node('cancel-order')).toBeNull(); expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('restaurant assigned double click keeps one durable intent until receipt', async () => {
  await mount('restaurant'); await click('restaurant-stat-preparing'); await click('cancel-order'); await type('cancel-reason-input', 'One exact reason');
  let release; transport.post.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  await act(async () => { node('confirm-cancel-btn').click(); node('confirm-cancel-btn').click(); while (!release) await Promise.resolve(); });
  expect(transport.post).toHaveBeenCalledTimes(1); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1);
  expect(node('confirm-cancel-btn').disabled).toBe(true); expect(toast.success).not.toHaveBeenCalled();
  expect(JSON.parse(localStorage.getItem(KEY))).toMatchObject({ client_operation_id: ID, status: 'CANCELLED', receipt: null });
  await act(async () => release(done)); expect(node('status-acknowledge-button')).not.toBeNull();
  expect(localStorage.getItem(KEY)).not.toContain('One exact reason'); expect(sessionStorage.length).toBe(0);
});
test('restaurant accepted lost ACK resolves only same-ID receipt without duplicate cancellation', async () => {
  await mount('restaurant', { ...order, status: 'ACCEPTED' }); await click('restaurant-stat-preparing');
  await click('cancel-order'); await type('cancel-reason-input', 'Lost ACK exact reason');
  transport.post.mockImplementationOnce(async () => { orders = []; throw new Error('lost ACK'); });
  await click('confirm-cancel-btn'); expect(transport.post).toHaveBeenCalledTimes(1); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1);
  expect(transport.get.mock.calls.some(([p]) => p.endsWith(`/order/${ID}`))).toBe(true);
  expect(JSON.parse(localStorage.getItem(KEY))).toMatchObject({ client_operation_id: ID, order_id: 'order', receipt: done.data });
  expect(node('status-acknowledge-button')).not.toBeNull(); expect(transport.put).not.toHaveBeenCalled();
});
test('restaurant uncertain cancellation survives refresh and same-ID recovery without stale GET reversal', async () => {
  await mount('restaurant'); await click('restaurant-stat-preparing'); let release;
  axios.get.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  await act(async () => node('refresh-button').click());
  await click('cancel-order'); await type('cancel-reason-input', 'Retained exact reason');
  transport.post.mockRejectedValueOnce(new Error('unknown ACK'));
  const normalGet = transport.get.getMockImplementation();
  transport.get.mockImplementation(async (p, options) => p.endsWith(`/order/${ID}`) ? Promise.reject(new Error('unavailable')) : normalGet(p, options));
  await click('confirm-cancel-btn'); expect(toast.success).not.toHaveBeenCalled(); expect(node('status-recovery-state').textContent).toContain('neconfirmat');
  expect(node('cancel-order').disabled).toBe(true); await click('refresh-button'); expect(node('status-recover-button')).not.toBeNull();
  orders = []; transport.get.mockImplementation(normalGet); await click('status-recover-button');
  expect(node('status-recovery-state').textContent).toContain('confirmat');
  await act(async () => release({ status: 200, data: [{ ...order }] }));
  expect(node('cancel-order')).toBeNull(); expect(JSON.parse(localStorage.getItem(KEY)).receipt).toEqual(done.data);
  expect(transport.post).toHaveBeenCalledTimes(1); expect(transport.put).not.toHaveBeenCalled(); expect(window.crypto.randomUUID).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(KEY)).not.toContain('Retained exact reason'); expect(sessionStorage.length).toBe(0);
});
test('admin own cancellation and postpickup cancel absent', async () => {
  await mount('admin'); await adminSelect(); await type('admin-status-cancel-reason', 'Admin reason'); await click('admin-status-cancelled');
  expect(transport.post.mock.calls[0][1].cancellation_reason).toBe('Admin reason'); expect(localStorage.getItem(KEY)).not.toContain('Admin reason');
  await click('status-acknowledge-button'); orders = [{ ...order, status: 'PICKED_UP' }]; await click('refresh-button');
  expect(node('admin-status-cancelled')).toBeNull(); expect(node('admin-status-delivered')).not.toBeNull();
});
test('typed conflict is not success and requires explicit new-attempt refresh', async () => {
  transport.post.mockRejectedValue({ response: { status: 409, data: { client_operation_id: ID, state: 'rejected', error_code: 'ORDER_VERSION_CONFLICT' } } });
  await mount('driver'); await click('driver-nav-delivery-button'); await click('accept-button');
  expect(toast.success).not.toHaveBeenCalled(); expect(node('status-recovery-state').textContent).toContain('s-a schimbat');
  expect(node('accept-button').disabled).toBe(true); expect(transport.put).not.toHaveBeenCalled();
});
test('mutation invalidates older polling GET response', async () => {
  await mount('driver'); await click('driver-nav-delivery-button'); let release;
  axios.get.mockImplementationOnce(() => new Promise((r) => { release = r; })); let refresh;
  await act(async () => { refresh = node('refresh-button').click(); await Promise.resolve(); });
  await click('accept-button'); expect(node('pickup-button')).not.toBeNull();
  await act(async () => { release({ status: 200, data: [{ ...order }] }); await refresh; });
  expect(node('accept-button')).toBeNull(); expect(node('pickup-button')).not.toBeNull();
});
test('in-flight session switch never shows old actor success or late current order', async () => {
  await mount('driver'); await click('driver-nav-delivery-button'); let release; transport.post.mockImplementation(() => new Promise((r) => { release = r; }));
  await act(async () => { node('accept-button').click(); while (!release) await Promise.resolve(); });
  useAuth.mockReturnValue({ user: { ...user, id: 'other', driver_id: 'other-driver' }, token: 'other-token', logout: jest.fn() }); orders = [];
  await act(async () => root.render(<DriverApp />)); await act(async () => release(done));
  expect(toast.success).not.toHaveBeenCalled(); expect(node('status-recovery-state')).toBeNull(); expect(JSON.parse(localStorage.getItem(KEY)).receipt).toBeNull();
});
