import { act } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";
import { canChangeOrderStatus } from "../lib/orderStatusRecovery";
jest.mock("axios", () => ({ get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), defaults: {}, interceptors: { response: { use: jest.fn() } } }));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() } }));
jest.mock("../context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("../context/ThemeContext", () => ({ useTheme: () => ({ isDark: false, toggleTheme: jest.fn() }) }));
jest.mock("../hooks/useNetworkStatus", () => ({ useNetworkStatus: () => ({ isOnline: true }) }));
jest.mock("../hooks/useOrderStatusRecovery", () => {
  const verify = jest.fn(async () => true);
  const recovery = { capability: { ready: true, enabled: true }, available: true, canSubmit: () => true, verifyCapability: verify };
  return { useOrderStatusRecovery: () => recovery, OrderStatusRecoveryPanel: () => null };
});
jest.mock("../components/admin/RestaurantAnalyticsPanel", () => ({ RestaurantAnalyticsPanel: ({ analytics }) => <div data-testid="qa-analytics">{JSON.stringify(analytics)}</div> }));
jest.mock("../components/DriverSchedule", () => ({ DriverSchedule: () => null }));
jest.mock("../components/AvatarUploadCropper", () => ({ AvatarUploadCropper: () => null }));
jest.mock("../components/DriverAvatar", () => ({ DriverAvatar: () => null }));
jest.mock("../components/ui/dialog", () => {
  const Part = ({ children, ...props }) => <div data-testid={props["data-testid"]}>{children}</div>;
  return { Dialog: ({ open, children }) => open ? <div>{children}</div> : null,
    DialogContent: Part, DialogDescription: Part, DialogHeader: Part, DialogTitle: Part, DialogFooter: Part };
});
process.env.REACT_APP_BACKEND_URL = "https://qa.invalid";
const RestaurantApp = jest.requireActual("./RestaurantApp").default;
const DriverApp = jest.requireActual("./DriverApp").default;
const syntheticOrder = (status = "DELIVERED", restaurant = "restaurant-a") => ({ id: "order-a", order_version: 4,
  restaurant_id: restaurant, driver_id: "driver-a", status, preparation_status: status === "ASSIGNED" ? "READY" : "PREPARING",
  order_number: "QA-ORDER-A", customer_name: "PRIVATE-SENTINEL-A", customer_phone: "0700000000",
  customer_address: "SYNTHETIC-STREET-A", total_amount: 20, items: [], created_at: "2026-10-10T10:00:00Z" });
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
let root, container, actor, orders;
const node = (id) => container.querySelector('[data-testid="' + id + '"]');
const click = (id) => act(async () => { const target = node(id); expect(target).not.toBeNull(); target.click(); });
const render = async (role = "restaurant", id = "a") => {
  actor = { id: "actor-" + id, role, name: "Synthetic " + id, [role + "_id"]: role + "-" + id };
  useAuth.mockReturnValue({ user: actor, token: "synthetic-token-" + id, logout: jest.fn() });
  await act(async () => root.render(role === "restaurant" ? <RestaurantApp /> : <DriverApp />));
};
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; jest.clearAllMocks(); orders = [syntheticOrder()];
  axios.get.mockImplementation(async (url) => ({ status: 200, data: url.endsWith("/prep-availability") ?
    { available_drivers: 1, blocked_short_options: false, minimum_preparation_minutes: 5 } :
    url.includes("/api/orders/") ? orders :
    url.endsWith("/analytics") ? { sentinel: "ANALYTICS-" + actor.id } :
    url.endsWith("/dashboard") ? { driver: { id: actor.driver_id, operational_status: "active", operational_status_label: "Activ" } } :
      { id: actor.restaurant_id, accepting_orders: true, schedule_settings: {} } }));
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
const history = async () => { await click("restaurant-more-left-button"); await click("restaurant-more-history-button"); await click("restaurant-history-order-order-a"); };
test("restaurant actor switch closes the old customer detail", async () => {
  await render(); await history(); expect(node("restaurant-history-detail-dialog").textContent).toContain("PRIVATE-SENTINEL-A");
  orders = []; await render("restaurant", "b");
  expect(node("restaurant-history-detail-dialog")).toBeNull();
  expect(container.textContent).not.toContain("PRIVATE-SENTINEL-A");
});
test("restaurant actor switch closes the old problem draft", async () => {
  await render(); await history(); await click("history-detail-problem-button");
  expect(node("restaurant-problem-order-dialog")).not.toBeNull();
  orders = []; await render("restaurant", "b"); expect(node("restaurant-problem-order-dialog")).toBeNull();
});
test("restaurant actor switch closes the old ready confirmation", async () => {
  orders = [syntheticOrder("PREPARING")]; await render(); await click("restaurant-stat-preparing"); await click("ready-order-a");
  expect(node("confirm-ready-btn")).not.toBeNull();
  orders = []; await render("restaurant", "b"); expect(node("confirm-ready-btn")).toBeNull();
});
test("late status GET from restaurant A cannot replace B's state", async () => {
  const gate = deferred(); const normal = axios.get.getMockImplementation();
  axios.get.mockImplementation((url, options) => url.endsWith("/restaurants/restaurant-a") ? gate.promise : normal(url, options));
  orders = []; await render(); await render("restaurant", "b");
  expect(node("restaurant-operational-toggle").textContent).toContain("Acceptă comenzi");
  await act(async () => gate.resolve({ status: 200, data: { id: "restaurant-a", accepting_orders: false } }));
  expect(node("restaurant-operational-toggle").textContent).toContain("Acceptă comenzi");
});
test("late preparation availability from A cannot block B's short options", async () => {
  const gate = deferred(); const normal = axios.get.getMockImplementation();
  axios.get.mockImplementation((url, options) => url.endsWith("/restaurant/restaurant-a/prep-availability") ? gate.promise : normal(url, options));
  orders = [syntheticOrder("NEW")]; await render();
  orders = [{ ...syntheticOrder("NEW", "restaurant-b"), id: "order-b" }]; await render("restaurant", "b");
  await act(async () => gate.resolve({ status: 200, data: { available_drivers: 0, blocked_short_options: true, minimum_preparation_minutes: 15 } }));
  expect(node("prep-5-order-b").disabled).toBe(false);
});
test("late analytics from A cannot replace B's analytics", async () => {
  const gate = deferred(); const normal = axios.get.getMockImplementation();
  axios.get.mockImplementation((url, options) => url.endsWith("/restaurants/restaurant-a/analytics") ? gate.promise : normal(url, options));
  orders = []; await render(); await click("restaurant-more-left-button"); await click("restaurant-more-analytics-button");
  await render("restaurant", "b");
  await act(async () => gate.resolve({ status: 200, data: { sentinel: "PRIVATE-ANALYTICS-A" } }));
  expect(container.textContent).not.toContain("PRIVATE-ANALYTICS-A");
});
test("driver cancellation is refused while admin and own restaurant retain pre-pickup cancellation", () => {
  const order = syntheticOrder("ACCEPTED");
  expect(canChangeOrderStatus(order, "CANCELLED", { id: "driver-user", role: "driver", driver_id: "driver-a" })).toBe(false);
  expect(canChangeOrderStatus(order, "CANCELLED", { id: "admin", role: "admin" })).toBe(true);
  expect(canChangeOrderStatus(order, "CANCELLED", { id: "restaurant-user", role: "restaurant", restaurant_id: "restaurant-a" })).toBe(true);
});
test("driver delivery screen offers acceptance but no cancellation action", async () => {
  orders = [syntheticOrder("ASSIGNED")]; await render("driver"); await click("driver-nav-delivery-button");
  expect(node("accept-button")).not.toBeNull(); expect(node("cancel-order-button")).toBeNull();
});

const enterProblem = async () => {
  await history(); await click('history-detail-problem-button');
  const textarea = node('restaurant-problem-order-dialog').querySelector('textarea');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(textarea, 'Synthetic incident');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
};
const beginLegacyAction = async (kind) => {
  if (kind === 'status') await click('restaurant-operational-toggle');
  if (kind === 'schedule') {
    await click('restaurant-more-left-button'); await click('restaurant-more-schedule-button');
    await click('restaurant-schedule-save-button');
  }
  if (kind === 'problem') { await enterProblem(); await click('problem-submit-button'); }
};
const busyNode = (kind) => node(kind === 'status' ? 'restaurant-operational-toggle' : kind === 'schedule' ? 'restaurant-schedule-save-button' : 'problem-submit-button');
test.each(['status', 'schedule', 'problem'])('late %s mutation from A cannot change B dialog/state/busy or request A reads', async (kind) => {
  const a = deferred(), b = deferred();
  axios.patch.mockImplementation((url) => url.includes('restaurant-a') ? a.promise : b.promise);
  axios.post.mockImplementation(() => actor.id === 'actor-a' ? a.promise : b.promise);
  await render(); await beginLegacyAction(kind);
  orders = [syntheticOrder('DELIVERED', 'restaurant-b')]; await render('restaurant', 'b');
  if (kind === 'schedule') { await click('restaurant-more-left-button'); await click('restaurant-more-schedule-button'); }
  if (kind === 'problem') await enterProblem();
  expect(busyNode(kind).disabled).toBe(false);
  await click(kind === 'status' ? 'restaurant-operational-toggle' : kind === 'schedule' ? 'restaurant-schedule-save-button' : 'problem-submit-button');
  expect(busyNode(kind).disabled).toBe(true);
  const readsA = () => axios.get.mock.calls.filter(([url]) => url.includes('restaurant-a')).length;
  const beforeReads = readsA();
  toast.success.mockClear(); toast.error.mockClear();
  await act(async () => a.resolve({ data: { accepting_orders: false, pause_until: null } }));
  expect(readsA()).toBe(beforeReads);
  expect(toast.success).not.toHaveBeenCalled(); expect(toast.error).not.toHaveBeenCalled();
  expect(busyNode(kind)).not.toBeNull(); expect(busyNode(kind).disabled).toBe(true);
  await act(async () => b.resolve({ data: { accepting_orders: false, pause_until: null } }));
  expect(toast.success).toHaveBeenCalledTimes(1);
});
test('status GET started before same-actor PATCH cannot overwrite the mutation result', async () => {
  const gate = deferred(), normal = axios.get.getMockImplementation();
  axios.get.mockImplementation((url, options) => url.endsWith('/restaurants/restaurant-a') ? gate.promise : normal(url, options));
  axios.patch.mockResolvedValue({ data: { accepting_orders: false, pause_until: null } });
  await render(); await click('restaurant-operational-toggle');
  expect(node('restaurant-operational-toggle').textContent).toContain('Pauză');
  await act(async () => gate.resolve({ data: { accepting_orders: true } }));
  expect(node('restaurant-operational-toggle').textContent).toContain('Pauză');
});