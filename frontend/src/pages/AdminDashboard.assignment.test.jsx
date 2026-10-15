import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
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
jest.mock('../components/admin/OrdersTab', () => ({ OrdersTab: ({ activeOrders, onAssignOrder }) => <div>{activeOrders.map((order) =>
  <button key={order.id} data-testid={`open-order-${order.id}`} onClick={() => onAssignOrder(order)}>{order.id}</button>)}</div> }));
jest.mock('../components/admin/AdminCommandCenter', () => ({ AdminCommandCenter: () => null }));
jest.mock('../components/admin/LiveMapPanel', () => ({ LiveMapPanel: () => null }));
jest.mock('../components/admin/RestaurantsTab', () => ({ RestaurantsTab: () => null }));
jest.mock('../components/admin/SettingsTab', () => ({ SettingsTab: () => null }));
jest.mock('../components/admin/DriverManagementDialog', () => ({ DriverManagementDialog: () => null }));
jest.mock('../components/admin/MapMarkerIcons', () => ({ restaurantIcon: {} }));
jest.mock('../components/AdminScheduleView', () => ({ AdminScheduleView: () => null }));
jest.mock('../components/DriverAvatar', () => ({ DriverAvatar: () => null }));
jest.mock('../components/LocationAutocomplete', () => ({ LocationAutocomplete: () => null }));
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

process.env.REACT_APP_BACKEND_URL = 'https://qa.invalid';
const AdminDashboard = jest.requireActual('./AdminDashboard').default;
const ID = '123e4567-e89b-42d3-a456-426614174000';
const NEXT = '123e4567-e89b-42d3-a456-426614174001';
const KEY = 'prodelivery:order-assign:v1:admin';
const order = { id: 'order', restaurant_id: 'restaurant', order_number: 'QA-1', order_version: 4, status: 'NEW',
  preparation_status: 'NEW', customer_name: 'Synthetic Customer', customer_address: 'Synthetic Street', total_amount: 20 };
const driver = { id: 'driver', name: 'Synthetic Driver', is_active: true, operational_status: 'active', driver_status: 'active' };
const record = { actor_id: 'admin', order_id: 'order', client_operation_id: ID, expected_order_version: 4, driver_id: 'driver', receipt: null };
const done = { status: 200, data: { client_operation_id: ID, state: 'applied', order_id: 'order', order_version: 5 } };
let root, container, transport, orders, drivers;
const node = (id) => container.querySelector(`[data-testid="${id}"]`);
const click = (id) => act(async () => { const el = node(id); expect(el).not.toBeNull(); el.click(); });
const render = () => act(async () => root.render(<AdminDashboard />));
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; process.env.REACT_APP_BACKEND_URL = 'https://qa.invalid';
  localStorage.clear(); jest.clearAllMocks(); orders = [{ ...order }]; drivers = [{ ...driver }];
  useAuth.mockReturnValue({ user: { id: 'admin', role: 'admin' }, token: 'token-a', logout: jest.fn() });
  useNetworkStatus.mockReturnValue({ isOnline: true });
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_k, _o, cb) => cb({}) } });
  Object.defineProperty(window, 'crypto', { configurable: true, value: { randomUUID: jest.fn().mockReturnValueOnce(ID).mockReturnValue(NEXT) } });
  axios.get.mockImplementation(async (url) => ({ data: url.endsWith('/orders') ? orders.map((o) => ({ ...o })) : url.endsWith('/drivers') ? drivers.map((d) => ({ ...d })) : url.endsWith('/restaurants') ? [] : {} }));
  transport = { get: jest.fn(async (url) => url.endsWith('/api/auth/me') ? { status: 200, data: { id: 'admin', role: 'admin' } } : { status: 200, data: { assign_recovery_enabled: true } }),
    post: jest.fn(async () => done), put: jest.fn(async () => ({ status: 200, data: { message: 'assigned' } })) };
  axios.create.mockReturnValue(transport); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); await Promise.resolve(); container.remove(); });

test('disabled versioned capability keeps existing modal but disables submit; no legacy fallback', async () => {
  transport.get.mockResolvedValue({ status: 200, data: { assign_recovery_enabled: false } });
  await render(); await click('open-order-order'); await click('assign-driver-option-driver');
  expect(node('assign-capability-state').textContent).toContain('indisponibila'); expect(node('assign-confirm-button').disabled).toBe(true);
  await click('assign-confirm-button'); expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('versioned success freezes selection and waits for explicit terminal acknowledgement', async () => {
  await render(); await click('open-order-order'); await click('assign-driver-option-driver'); await click('assign-confirm-button');
  expect(transport.post.mock.calls[0][1]).toEqual({ client_operation_id: ID, expected_order_version: 4, driver_id: 'driver' });
  expect(node('assign-order-dialog')).not.toBeNull(); expect(node('assign-recovery-state').textContent).toContain('confirmata');
  expect(node('assign-confirm-button')).toBeNull(); expect(node('assign-driver-option-driver').disabled).toBe(true);
  await click('assign-cancel-button'); expect(localStorage.getItem(KEY)).not.toBeNull();
  await click('assign-open-button'); await click('assign-acknowledge-button');
  expect(localStorage.getItem(KEY)).toBeNull(); expect(node('assign-order-dialog')).toBeNull(); expect(transport.put).not.toHaveBeenCalled();
});
test('legacy order preserves current PUT even when assignment capability disabled', async () => {
  delete orders[0].order_version; transport.get.mockImplementation(async (url) => url.endsWith('/api/auth/me') ?
    { status: 200, data: { id: 'admin', role: 'admin' } } : { status: 200, data: { assign_recovery_enabled: false } });
  await render(); await click('open-order-order'); await click('assign-driver-option-driver');
  expect(node('assign-confirm-button').disabled).toBe(false); await click('assign-confirm-button');
  expect(transport.put.mock.calls[0][0]).toMatch(/\/api\/orders\/order\/assign$/);
  expect(transport.put.mock.calls[0][1]).toEqual({ driver_id: 'driver' }); expect(transport.post).not.toHaveBeenCalled();
  expect(transport.put.mock.calls[0][2].headers['X-Expected-Actor-ID']).toBe('admin');
  expect(localStorage.getItem(KEY)).toBeNull(); expect(node('assign-order-dialog')).toBeNull();
});
test.each([null, true, '4', Number.MAX_SAFE_INTEGER])('present malformed revision %s cannot use legacy UI', async (value) => {
  orders[0].order_version = value; await render(); await click('open-order-order'); await click('assign-driver-option-driver');
  expect(node('assign-confirm-button').disabled).toBe(true); expect(transport.put).not.toHaveBeenCalled(); expect(transport.post).not.toHaveBeenCalled();
});
test('reload offline automatically surfaces opaque pending operation through existing modal', async () => {
  orders = []; localStorage.setItem(KEY, JSON.stringify(record)); useNetworkStatus.mockReturnValue({ isOnline: false });
  await render(); expect(node('assign-order-dialog')).not.toBeNull(); expect(node('assign-locked-order-summary').textContent).toContain('order');
  expect(node('assign-recovery-state').textContent).toContain('neconfirmata'); expect(node('assign-recover-button').disabled).toBe(true);
  expect(node('assign-driver-option-driver').disabled).toBe(true); expect(node('assign-confirm-button')).toBeNull();
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('rejected conflict refresh requires fresh revision and a new explicit driver selection', async () => {
  localStorage.setItem(KEY, JSON.stringify({ ...record, receipt: { client_operation_id: ID, state: 'rejected', error_code: 'ORDER_VERSION_CONFLICT' } }));
  transport.get.mockImplementation(async (url) => url.endsWith('/api/orders/order') ? { status: 200, data: { ...order, order_version: 8 } } :
    { status: 200, data: { assign_recovery_enabled: true } });
  transport.post.mockResolvedValue({ status: 200, data: { ...done.data, client_operation_id: ID, order_version: 9 } });
  await render(); expect(node('assign-recovery-state').textContent).toContain('ORDER_VERSION_CONFLICT'); await click('assign-retry-button');
  expect(localStorage.getItem(KEY)).toBeNull(); expect(node('assign-confirm-button').disabled).toBe(true);
  await click('assign-driver-option-driver'); await click('assign-confirm-button'); expect(transport.post.mock.calls[0][1].expected_order_version).toBe(8);
});
test('reassignment selectable only before accept, with other available driver and same modal', async () => {
  orders = [{ ...order, status: 'ASSIGNED', driver_id: 'old', assigned_at: '2026-10-07T10:00:00Z', preparation_status: 'READY' },
    { ...order, id: 'accepted', status: 'ACCEPTED', accepted_at: '2026-10-07T10:05:00Z' }];
  drivers.push({ ...driver, id: 'old', current_order_id: 'order', operational_status: 'delivery', driver_status: 'delivery' });
  await render(); await click('assign-open-button'); expect(node('assign-order-option-order')).not.toBeNull(); expect(node('assign-order-option-accepted')).toBeNull();
  await click('assign-order-option-order'); expect(node('assign-driver-option-old').disabled).toBe(true); await click('assign-driver-option-driver');
  expect(node('assign-confirm-button').textContent).toContain('Reasigna'); await click('assign-confirm-button');
  expect(transport.post.mock.calls[0][1]).toEqual({ client_operation_id: ID, expected_order_version: 4, driver_id: 'driver' });
});
test('actor switch closes old modal and cannot display another actors pending data', async () => {
  useNetworkStatus.mockReturnValue({ isOnline: false }); localStorage.setItem(KEY, JSON.stringify(record)); await render();
  expect(node('assign-order-dialog')).not.toBeNull(); useAuth.mockReturnValue({ user: { id: 'other', role: 'admin' }, token: 'token-b', logout: jest.fn() });
  await render(); expect(node('assign-order-dialog')).toBeNull(); expect(localStorage.getItem(KEY)).not.toBeNull();
});
test.each([true, 'false', null])('disabled/malformed admin flag %j cannot assign', async (account_disabled) => {
  useAuth.mockReturnValue({ user: { id: 'admin', role: 'admin', account_disabled }, token: 'token-a', logout: jest.fn() });
  await render(); await click('open-order-order'); expect(node('assign-confirm-button').disabled).toBe(true);
  expect(axios.create).not.toHaveBeenCalled(); expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test('explicit break -> active retains a valid future deadline and becomes selectable', async () => {
  drivers[0] = { ...driver, driver_status: 'break', operational_status: 'break', break_started_at: '2026-10-07T10:00:00Z', break_until: '2999-10-07T11:00:00Z' };
  await render(); await click('open-order-order'); expect(node('assign-driver-option-driver').disabled).toBe(true);
  drivers[0] = { ...drivers[0], driver_status: 'active', operational_status: 'active' };
  await click('assign-cancel-button'); await click('refresh-button');
  await click('assign-open-button'); await click('assign-order-option-order');
  // Opening again uses the fetched current driver object; no pause data is erased.
  expect(node('assign-driver-option-driver').disabled).toBe(false); await click('assign-driver-option-driver'); await click('assign-confirm-button');
  expect(transport.post.mock.calls[0][1].driver_id).toBe('driver');
});
