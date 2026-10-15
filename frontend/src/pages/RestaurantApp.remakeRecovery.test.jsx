import { act } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { useAuth } from "../context/AuthContext";
import { useOrderRemakeRecovery } from "../hooks/useOrderRemakeRecovery";
jest.mock("axios", () => ({ get: jest.fn(), post: jest.fn(), put: jest.fn(), create: jest.fn(), defaults: {}, interceptors: { response: { use: jest.fn() } } }));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("../context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("../hooks/useNetworkStatus", () => ({ useNetworkStatus: () => ({ isOnline: true }) }));
jest.mock("../hooks/useOrderRemakeRecovery", () => ({ useOrderRemakeRecovery: jest.fn() }));
jest.mock("../hooks/useOrderPreparationRecovery", () => ({ useOrderPreparationRecovery: () => ({ blocked: false, record: null }) }));
jest.mock("../hooks/useOrderFinancialEventRecovery", () => ({ useOrderFinancialEventRecovery: () => ({ blocked: false, record: null }) }));
jest.mock("../hooks/useOrderCustodyRecovery", () => ({ useOrderCustodyRecovery: () => ({ blocked: false, record: null }) }));
jest.mock("../hooks/useOrderStatusRecovery", () => ({ useOrderStatusRecovery: () => ({ capability: { ready: true, enabled: true }, canSubmit: () => true, verifyCapability: jest.fn() }), OrderStatusRecoveryPanel: () => null }));
jest.mock("../hooks/useOperationalReporting", () => {
  const lease = {}, reporting = { captureLease: () => lease, isCurrentLease: (value) => value === lease, available: true };
  return { useOperationalReporting: () => reporting, OperationalReportingPanel: () => null };
});
jest.mock("../components/OperationalIncidentReporter", () => ({ OperationalIncidentReporter: () => null, IncidentSummary: () => null }));
jest.mock("../components/admin/RestaurantAnalyticsPanel", () => ({ RestaurantAnalyticsPanel: () => null }));
jest.mock("../components/restaurant/PreparationRecoveryPanel", () => ({ PreparationRecoveryPanel: () => null }));
jest.mock("../components/restaurant/RestaurantOrderCard", () => ({ RestaurantOrderCard: ({ order, onProblem, preparationBlocked }) => <article><span>{order.customer_name}</span><button data-testid="open-problem" onClick={() => onProblem(order)}>Problem</button><span data-testid="preparation-blocked">{String(preparationBlocked)}</span></article> }));
jest.mock("../components/OrderRemakeDialog", () => ({ OrderRemakeDialog: ({ open, order, token }) => open ? <div data-testid="financial-dialog">{order.id}:{token}</div> : null,
  OrderRemakeRecoveryPanel: ({ recovery }) => recovery.record || recovery.storageInvalid ? <div data-testid="remake-panel">{recovery.record?.parent_id || 'invalid'}</div> : null }));
jest.mock("../components/ui/dialog", () => { const Part = ({ children, ...props }) => <div data-testid={props["data-testid"]}>{children}</div>; return { Dialog: ({ open, children }) => open ? <div>{children}</div> : null, DialogContent: Part, DialogDescription: Part, DialogHeader: Part, DialogTitle: Part, DialogFooter: Part }; });
process.env.REACT_APP_BACKEND_URL = "https://qa.invalid";
const RestaurantApp = jest.requireActual("./RestaurantApp").default;
const actor = { id: "owner", role: "restaurant", restaurant_id: "r1" };
const parent = () => ({ id: "parent", restaurant_id: "r1", status: "NEW", order_number: "QA", customer_name: "Private Client", customer_phone: "0700000000", customer_address: "Synthetic street", items: [], total_amount: 12 });
let root, container, recovery, orders, refresh;
const node = (id) => container.querySelector(`[data-testid="${id}"]`);
const render = async (user = actor, token = "token-a") => { useAuth.mockReturnValue({ user, token, logout: jest.fn() }); await act(async () => root.render(<RestaurantApp />)); };
const change = async (id, value) => act(async () => { const input = node(id), type = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement; Object.getOwnPropertyDescriptor(type.prototype, 'value').set.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); });
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; jest.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); orders = [parent()];
  recovery = { available: true, blocked: false, record: null, storageInvalid: false };
  useOrderRemakeRecovery.mockImplementation((_a, _url, _online, _token, callback) => { refresh = callback; return recovery; });
  axios.get.mockImplementation(async (url) => ({ status: 200, data: url.endsWith('/prep-availability') ? { available_drivers: 1 } : url.includes('/api/orders/') ? orders : { accepting_orders: true, schedule_settings: {} } }));
  axios.post.mockResolvedValue({ status: 200, data: {} }); container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
test('pure legacy keeps exact historical problem POST shape', async () => {
  await render(); await act(async () => node('open-problem').click()); expect(node('financial-dialog')).toBeNull();
  await change('problem-item-name-input', 'Replacement'); await change('problem-quantity-input', '2'); await change('problem-price-input', '13.05'); await change('problem-description-input', 'Explicit problem');
  await act(async () => node('problem-submit-button').click());
  expect(axios.post.mock.calls).toEqual([['https://qa.invalid/api/orders/parent/problem', { problem_type: 'missing_product', item_name: 'Replacement', quantity: 2, price: 13.05, problem_description: 'Explicit problem' }, { timeout: 15000 }]]);
});
test.each(['order_version', 'financial', 'custody_activity', 'financial_activity', '_read_invalid'])('own marker %s selects financial dialog without legacy write', async (field) => {
  orders = [{ ...parent(), [field]: null }]; await render(); await act(async () => node('open-problem').click());
  expect(node('financial-dialog')).not.toBeNull(); expect(node('problem-submit-button')).toBeNull(); expect(axios.post).not.toHaveBeenCalled();
});
test('refresh returning a marker-free row cannot downgrade already selected financial original', async () => {
  orders = [{ ...parent(), order_version: 4 }]; await render(); await act(async () => node('open-problem').click());
  orders = [parent()]; await act(async () => refresh({ isCurrent: () => true })); expect(node('financial-dialog')).not.toBeNull(); expect(node('problem-submit-button')).toBeNull();
});
test('independent recovery stays visible with empty list and no original card', async () => { recovery.record = { parent_id: 'parent', receipt: null }; orders = []; await render(); expect(node('remake-panel').textContent).toBe('parent'); expect(node('open-problem')).toBeNull(); });
test('durable remake disables competing preparation', async () => { recovery.record = { parent_id: 'parent', receipt: null }; await render(); expect(node('preparation-blocked').textContent).toBe('true'); });
test('ACK refresh reports true only after valid list publication', async () => { await render(); orders = [{ ...parent(), customer_name: 'NEW READBACK' }]; let result; await act(async () => { result = await refresh({ isCurrent: () => true }); }); expect(result).toBe(true); expect(container.textContent).toContain('NEW READBACK'); });
test.each([{}, null, { orders: [] }])('invalid list %p returns false and preserves rendered list', async (bad) => { await render(); orders = bad; let result; await act(async () => { result = await refresh({ isCurrent: () => true }); }); expect(result).toBe(false); expect(container.textContent).toContain('Private Client'); });
test('stale intent read is never published and reports false', async () => {
  await render(); let resolve, current = true, pending; axios.get.mockImplementation(() => new Promise((done) => { resolve = done; }));
  await act(async () => { pending = refresh({ isCurrent: () => current }); }); current = false;
  let result; await act(async () => { resolve({ status: 200, data: [{ ...parent(), customer_name: 'STALE' }] }); result = await pending; });
  expect(result).toBe(false); expect(container.textContent).not.toContain('STALE');
});
test('token replacement fences late list publication', async () => {
  await render(); let resolve, pending; axios.get.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  await act(async () => { pending = refresh({ isCurrent: () => true }); }); await render(actor, 'token-b');
  let result; await act(async () => { resolve({ status: 200, data: [{ ...parent(), customer_name: 'OLD TOKEN' }] }); result = await pending; }); expect(result).toBe(false); expect(container.textContent).not.toContain('OLD TOKEN');
});
