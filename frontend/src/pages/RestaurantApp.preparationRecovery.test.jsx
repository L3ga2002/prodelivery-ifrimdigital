import { act } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";
import { useOrderPreparationRecovery } from "../hooks/useOrderPreparationRecovery";
jest.mock("axios", () => ({ get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), create: jest.fn(), defaults: {}, interceptors: { response: { use: jest.fn() } } }));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("../context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("../hooks/useNetworkStatus", () => ({ useNetworkStatus: () => ({ isOnline: true }) }));
jest.mock("../hooks/useOrderPreparationRecovery", () => ({ useOrderPreparationRecovery: jest.fn() }));
let mockAcknowledged;
jest.mock("../components/restaurant/PreparationRecoveryPanel", () => ({ PreparationRecoveryPanel: ({ onAcknowledged }) => { mockAcknowledged = onAcknowledged; return null; } }));
jest.mock("../hooks/useOrderStatusRecovery", () => ({ useOrderStatusRecovery: () => ({ capability: { ready: true, enabled: true }, canSubmit: () => true, verifyCapability: jest.fn() }), OrderStatusRecoveryPanel: () => null }));
jest.mock("../hooks/useOperationalReporting", () => {
  const lease = {}, reporting = { captureLease: () => lease, isCurrentLease: (value) => value === lease, available: true };
  return { useOperationalReporting: () => reporting, OperationalReportingPanel: () => null };
});
jest.mock("../components/OperationalIncidentReporter", () => ({ OperationalIncidentReporter: () => null, IncidentSummary: () => null }));
jest.mock("../components/admin/RestaurantAnalyticsPanel", () => ({ RestaurantAnalyticsPanel: () => null }));
jest.mock("../components/ui/dialog", () => { const Part = ({ children, ...props }) => <div data-testid={props["data-testid"]}>{children}</div>; return { Dialog: ({ open, children }) => open ? <div>{children}</div> : null, DialogContent: Part, DialogDescription: Part, DialogHeader: Part, DialogTitle: Part, DialogFooter: Part }; });
process.env.REACT_APP_BACKEND_URL = "https://qa.invalid";
const RestaurantApp = jest.requireActual("./RestaurantApp").default;
const a = { id: "actor-a", role: "restaurant", restaurant_id: "restaurant-a" };
const order = (user = a) => ({ id: `order-${user.id}`, restaurant_id: user.restaurant_id, status: "NEW", order_version: 3,
  order_number: "QA", customer_name: `CUSTOMER-${user.id}`, customer_phone: "0700000000", customer_address: "Synthetic street", items: [], total_amount: 12 });
let root, container, recovery, orders;
const node = (id) => container.querySelector(`[data-testid="${id}"]`);
const render = async (user = a, token = "token-a") => {
  useAuth.mockReturnValue({ user, token, logout: jest.fn() });
  await act(async () => root.render(<RestaurantApp />));
};
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; jest.clearAllMocks(); orders = [order()];
  recovery = { blocked: false, record: null, chooseProtocol: jest.fn(async () => true), canUseLegacy: jest.fn(() => true), submit: jest.fn(async () => ({ state: "applied" })) };
  useOrderPreparationRecovery.mockImplementation(() => recovery);
  axios.get.mockImplementation(async (url) => ({ status: 200, data: url.endsWith("/prep-availability") ? { available_drivers: 1, blocked_short_options: false } :
    url.includes("/api/orders/") ? orders : { accepting_orders: true, schedule_settings: {} } }));
  axios.put.mockResolvedValue({ status: 200, data: {} });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
test.each(["actor", "token"])("late acknowledged order cannot publish across %s switch", async (kind) => {
  await render(); const oldCallback = mockAcknowledged;
  const nextActor = kind === "actor" ? { ...a, id: "actor-b", restaurant_id: "restaurant-b" } : a;
  orders = []; await render(nextActor, "token-b"); const reads = axios.get.mock.calls.length;
  await act(async () => oldCallback({ ...order(), customer_name: "OLD-ACK-CUSTOMER" }));
  expect(container.textContent).not.toContain("OLD-ACK-CUSTOMER"); expect(axios.get.mock.calls.length).toBe(reads);
});
test("verified enabled protocol uses exact durable intent and never legacy PUT", async () => {
  await render(); await act(async () => node("prep-15-order-actor-a").click());
  expect(recovery.submit).toHaveBeenCalledWith({ order: order(), action: "preparing", preparationTime: 15 });
  expect(axios.put).not.toHaveBeenCalled();
});
test("verified disabled protocol retains the legacy action with expected actor", async () => {
  recovery.chooseProtocol.mockResolvedValue(false); await render(); await act(async () => node("prep-15-order-actor-a").click());
  expect(axios.put).toHaveBeenCalledWith("https://qa.invalid/api/orders/order-actor-a/preparing", { preparation_time: 15 },
    { timeout: 15000, headers: { Authorization: "Bearer token-a", "X-Expected-Actor-ID": "actor-a" } });
  expect(recovery.submit).not.toHaveBeenCalled();
});
test.each([null, undefined])("unknown capability does not downgrade to legacy: %p", async (mode) => {
  recovery.chooseProtocol.mockResolvedValue(mode); await render(); await act(async () => node("prep-15-order-actor-a").click());
  expect(axios.put).not.toHaveBeenCalled(); expect(recovery.submit).not.toHaveBeenCalled();
});
test("legacy state-idempotence does not falsely confirm the requested minutes", async () => {
  recovery.chooseProtocol.mockResolvedValue(false); axios.put.mockResolvedValue({ status: 200, data: { idempotent: true } });
  await render(); await act(async () => node("prep-15-order-actor-a").click());
  expect(toast.success).toHaveBeenCalledWith("Comanda era deja în pregătire. Am actualizat starea.");
  expect(toast.success).not.toHaveBeenCalledWith("Timp pregătire setat: 15 minute");
});
test("saved uncertain preparation blocks both preparation and cancellation", async () => {
  recovery.blocked = true; recovery.record = { client_operation_id: "stored", action: "preparing", receipt: null };
  await render(); expect(node("prep-15-order-actor-a").disabled).toBe(true); expect(node("cancel-order-actor-a").disabled).toBe(true);
});
test("restored READY receipt describes a past confirmation, not present custody", async () => {
  orders = [{ ...order(), status: "DELIVERED" }]; recovery.blocked = true;
  recovery.record = { action: "ready", client_operation_id: "old-ready", receipt: { state: "replayed" } };
  await render(); expect(toast.success).toHaveBeenCalledWith("Marcarea comenzii ca gata a fost confirmată.");
  expect(toast.success).not.toHaveBeenCalledWith("Comanda este GATA pentru ridicare!");
});
