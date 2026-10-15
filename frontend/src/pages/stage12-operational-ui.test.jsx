import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";
jest.mock("axios", () => ({ get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), create: jest.fn(), defaults: {}, interceptors: { response: { use: jest.fn() } } }));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() } }));
jest.mock("../context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("../hooks/useNetworkStatus", () => ({ useNetworkStatus: () => ({ isOnline: true }) }));
jest.mock("../hooks/useOrderStatusRecovery", () => ({ useOrderStatusRecovery: () => ({ capability: { ready: true, enabled: true }, canSubmit: () => true, verifyCapability: jest.fn(async () => true) }), OrderStatusRecoveryPanel: () => null }));
jest.mock("../components/admin/RestaurantAnalyticsPanel", () => ({ RestaurantAnalyticsPanel: () => null }));
jest.mock("../components/ui/dialog", () => { const Part = ({ children, ...props }) => <div data-testid={props["data-testid"]}>{children}</div>; return { Dialog: ({ open, children }) => open ? <div>{children}</div> : null, DialogContent: Part, DialogDescription: Part, DialogHeader: Part, DialogTitle: Part, DialogFooter: Part }; });
process.env.REACT_APP_BACKEND_URL = "https://qa.invalid";
const RestaurantApp = jest.requireActual("./RestaurantApp").default;
const { OperationalIncidentReporter } = jest.requireActual("../components/OperationalIncidentReporter");
const { IncidentHistory } = jest.requireActual("../components/OperationalIncidentReporter");
const { useOperationalReporting } = jest.requireActual("../hooks/useOperationalReporting");
const { useOrderReadDetail } = jest.requireActual("../hooks/useOrderReads");
const operation = "719ae221-cb0d-4bf0-b6a5-ab4d21ab781f";
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
let root, container, actor, transport, restaurant;
const node = (id) => container.querySelector(`[data-testid="${id}"]`);
const click = (id) => act(async () => { const value = node(id); expect(value).not.toBeNull(); value.click(); });
const render = async (id = "a", token = `token-${id}`) => { actor = { id: `actor-${id}`, role: "restaurant", restaurant_id: `restaurant-${id}`, name: "Synthetic" }; useAuth.mockReturnValue({ user: actor, token, logout: jest.fn() }); await act(async () => root.render(<RestaurantApp />)); };
const response = (intent, extra = {}) => ({ status: 200, data: { state: "applied", client_operation_id: intent.client_operation_id, operation_type: "close_day", restaurant_id: actor.restaurant_id, close_day_operation_id: intent.client_operation_id, closed_today: true, accepting_orders: restaurant.accepting_orders, pause_until: restaurant.pause_until, ...extra } });
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; jest.clearAllMocks(); window.sessionStorage.clear();
  Object.defineProperty(window, "crypto", { configurable: true, value: { randomUUID: () => operation } });
  restaurant = { accepting_orders: true, pause_until: null };
  transport = { get: jest.fn(async (url) => ({ status: 200, data: url.endsWith("/auth/me") ? actor : url.endsWith("/incidents") ? { incidents: [], next_cursor: null } : { close_day_enabled: true, incident_reporting_enabled: true } })),
    patch: jest.fn(async (url, intent) => response(intent)), post: jest.fn() };
  axios.create.mockReturnValue(transport);
  axios.get.mockImplementation(async (url) => ({ status: 200, data: url.endsWith("/prep-availability") ? { available_drivers: 1, blocked_short_options: false } : url.includes("/api/orders/") ? [] : { id: actor.restaurant_id, ...restaurant, schedule_settings: {} } }));
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
test("restaurant status is passive and no self pause/resume is offered", async () => {
  await render(); expect(node("restaurant-operational-toggle").tagName).toBe("SPAN");
  expect(node("restaurant-compact-manual-pause-button")).toBeNull(); expect(node("restaurant-compact-online-button")).toBeNull();
  await click("restaurant-more-left-button"); expect(node("restaurant-resume-orders-button")).toBeNull(); expect(node("restaurant-manual-pause-button")).toBeNull(); expect(axios.patch).not.toHaveBeenCalled();
});
test("close-day retains authoritative admin pause and frozen bearer identity", async () => {
  restaurant = { accepting_orders: false, pause_until: "2026-10-10T22:00:00Z" }; await render(); await click("restaurant-compact-close-today-button");
  expect(transport.patch.mock.calls[0][0]).toBe("https://qa.invalid/api/restaurants/restaurant-a/close-day");
  expect(transport.patch.mock.calls[0][1]).toEqual({ client_operation_id: operation });
  expect(transport.patch.mock.calls[0][2].headers).toEqual({ Authorization: "Bearer token-a", "X-Expected-Actor-ID": "actor-a" });
  expect(node("restaurant-operational-toggle").textContent).toContain("Pauză"); expect(toast.success).toHaveBeenCalledTimes(1);
});
test("double close click has one HTTP intent", async () => {
  const gate = deferred(); transport.patch.mockReturnValue(gate.promise); await render();
  await act(async () => { node("restaurant-compact-close-today-button").click(); node("restaurant-compact-close-today-button").click(); });
  expect(transport.patch).toHaveBeenCalledTimes(1); await act(async () => gate.resolve(response({ client_operation_id: operation })));
});
test("close-day ACK loss reads actual pause and exposes same-intent recovery", async () => {
  transport.patch.mockImplementation(async () => { restaurant = { accepting_orders: false, pause_until: "2026-10-10T22:00:00Z" }; throw Error("ACK lost"); });
  await render(); await click("restaurant-compact-close-today-button");
  expect(node("restaurant-operational-toggle").textContent).toContain("Pauză"); expect(node("operational-report-lookup")).not.toBeNull();
  expect(node("restaurant-compact-close-today-button").disabled).toBe(true); expect(toast.success).not.toHaveBeenCalled();
  const normal = transport.get.getMockImplementation(); transport.get.mockImplementation((url) => url.includes("/operations/") ? Promise.resolve(response({ client_operation_id: operation })) : normal(url));
  await click("operational-report-lookup"); expect(toast.success).toHaveBeenCalledTimes(1); expect(transport.patch).toHaveBeenCalledTimes(1);
});
test("late close-day from actor A cannot replace B state", async () => {
  const gate = deferred(); transport.patch.mockReturnValue(gate.promise); await render(); await click("restaurant-compact-close-today-button");
  await render("b"); toast.success.mockClear(); await act(async () => gate.resolve(response({ client_operation_id: operation }, { restaurant_id: "restaurant-a", accepting_orders: false })));
  expect(node("restaurant-operational-toggle").textContent).toContain("Acceptă comenzi"); expect(toast.success).not.toHaveBeenCalled();
});
test.each([4, undefined])("incident dialog submits operation with revision %s and no price controls", async (version) => {
  actor = { id: "actor-a", role: "restaurant", restaurant_id: "restaurant-a" };
  const order = { id: "order-a", restaurant_id: "restaurant-a", status: "PICKED_UP", ...(version === undefined ? {} : { order_version: version }) };
  transport.post.mockResolvedValue({ status: 200, data: { state: "applied", client_operation_id: operation, operation_type: "incident", order_id: "order-a", order_version: version === undefined ? null : version + 1, incident_id: "incident-a" } });
  await act(async () => root.render(<OperationalIncidentReporter actor={actor} token="token-a" scope="incident" apiUrl="https://qa.invalid" isOnline order={order} />));
  await click("report-operational-incident"); expect(node("operational-incident-dialog").querySelector('input[type="number"]')).toBeNull();
  const text = node("operational-incident-description"); await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set.call(text,"Missing bag"); text.dispatchEvent(new Event("input", { bubbles: true })); });
  await click("operational-incident-submit"); expect(transport.post.mock.calls[0][1]).toEqual({ client_operation_id: operation, expected_order_version: version === undefined ? null : version, incident_type: "other", description: "Missing bag" });
  expect(node("operational-incident-dialog")).toBeNull();
});
test("incident history reads and renders persisted linked incident", async () => {
  actor = { id: "actor-a", role: "restaurant", restaurant_id: "restaurant-a" }; const normal = transport.get.getMockImplementation();
  transport.get.mockImplementation((url, config) => url.endsWith("/incidents") ? Promise.resolve({ status: 200, data: { incidents: [{ id: "incident-a", incident_type: "other", order_id: "order-a", description: "Warehouse issue" }], next_cursor: null } }) : normal(url, config));
  await act(async () => root.render(<OperationalIncidentReporter actor={actor} token="token-a" scope="incident" apiUrl="https://qa.invalid" isOnline order={{ id: "order-a", status: "DELIVERED" }} />));
  expect(node("operational-incident-history").textContent).toContain("Warehouse issue");
  expect(transport.get.mock.calls[0][1].headers["X-Expected-Actor-ID"]).toBe("actor-a");
});
test("valid cookie session after reload can close-day without in-memory bearer", async () => {
  await render("a", null); await click("restaurant-compact-close-today-button");
  expect(transport.patch).toHaveBeenCalledTimes(1); expect(transport.patch.mock.calls[0][2].headers).toEqual({ Authorization: null, "X-Expected-Actor-ID": "actor-a" });
  expect(axios.create).toHaveBeenCalledWith({ withCredentials: true }); expect(toast.success).toHaveBeenCalledTimes(1);
});
test("valid cookie-only session reads incident history after reload", async () => {
  actor = { id: "actor-a", role: "restaurant", restaurant_id: "restaurant-a" }; const normal = transport.get.getMockImplementation();
  transport.get.mockImplementation((url, config) => url.endsWith("/incidents") ? Promise.resolve({ status: 200, data: { incidents: [{ id: "incident-a", incident_type: "other", order_id: "order-a", description: "Cookie persisted" }], next_cursor: null } }) : normal(url, config));
  await act(async () => root.render(<OperationalIncidentReporter actor={actor} token={null} scope="incident" apiUrl="https://qa.invalid" isOnline order={{ id: "order-a", status: "DELIVERED" }} />));
  expect(node("operational-incident-history").textContent).toContain("Cookie persisted"); expect(transport.get.mock.calls[0][1].headers.Authorization).toBeNull();
});
test("pagehide during close-day suppresses toast and all follow-up reads while retaining intent", async () => {
  const gate = deferred(); transport.patch.mockReturnValue(gate.promise); await render(); await click("restaurant-compact-close-today-button");
  const reads = axios.get.mock.calls.length;
  await act(async () => window.dispatchEvent(new Event("pagehide")));
  await act(async () => gate.resolve(response({ client_operation_id: operation })));
  expect(toast.success).not.toHaveBeenCalled(); expect(axios.get.mock.calls.length).toBe(reads);
  expect(window.sessionStorage.length).toBe(1); expect(node("operational-report-lookup")).not.toBeNull();
});
test("pagehide during post-close followup order GET forbids late private orders publication", async () => {
  await render(); const gate = deferred(), entered = deferred(), normal = axios.get.getMockImplementation();
  axios.get.mockImplementation((url) => { if (url.endsWith("/api/orders/restaurant/restaurant-a")) { entered.resolve(); return gate.promise; } return normal(url); });
  await click("restaurant-compact-close-today-button"); await entered.promise;
  await act(async () => window.dispatchEvent(new Event("pagehide")));
  await act(async () => gate.resolve({ status: 200, data: [{ id: "late-private", restaurant_id: "restaurant-a", order_number: "Private Followup", status: "NEW", customer_name: "Private Followup", items: [] }] }));
  expect(container.textContent).not.toContain("Private Followup"); expect(window.sessionStorage.length).toBe(1);
});
test("incident callback propagates lease through a deferred parent followup", async () => {
  actor = { id: "actor-a", role: "restaurant", restaurant_id: "restaurant-a" }; const gate = deferred(), entered = deferred(), publish = jest.fn();
  transport.post.mockResolvedValue({ status: 200, data: { state: "applied", client_operation_id: operation, operation_type: "incident", order_id: "order-a", order_version: 5, incident_id: "incident-a" } });
  const onReported = async (receipt, guard) => { entered.resolve(); const value = await gate.promise; if (guard.isCurrent()) publish(value); };
  await act(async () => root.render(<OperationalIncidentReporter actor={actor} token="token-a" scope="parent" apiUrl="https://qa.invalid" isOnline order={{ id: "order-a", order_version: 4, status: "PICKED_UP" }} onReported={onReported} />));
  await click("report-operational-incident"); const text = node("operational-incident-description");
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set.call(text,"Delayed parent"); text.dispatchEvent(new Event("input", { bubbles: true })); });
  await click("operational-incident-submit"); await entered.promise;
  await act(async () => window.dispatchEvent(new Event("pagehide"))); await act(async () => gate.resolve("private followup"));
  expect(publish).not.toHaveBeenCalled();
});
const adminDetail = (label, version = 4) => ({ status: 200, data: { order: { id: "order-a", restaurant_id: "restaurant-a", status: "NEW", order_version: version, preparation_status: "NEW", created_at: "2026-10-10T10:00:00Z", customer_name: label }, history: [], next_history_before: null, history_has_more: false, data_warnings: [] } });
test("admin post-incident refresh survives temporary child unmount and publishes valid control", async () => {
  let read; const unmount = jest.fn(); transport.get.mockResolvedValue(adminDetail("Initial"));
  const Child = () => { useEffect(() => unmount, []); return <span>child</span>; };
  const Harness = () => { read = useOrderReadDetail({ actorId: "admin-a", role: "admin", token: "token-a", apiUrl: "https://qa.invalid", isOnline: true }, "order-a"); return <div>{read.data?.order.customer_name}{read.data && <Child />}</div>; };
  await act(async () => root.render(<Harness />)); const gate = deferred(); transport.get.mockReturnValue(gate.promise);
  await act(async () => read.refresh()); expect(unmount).toHaveBeenCalledTimes(1);
  await act(async () => gate.resolve(adminDetail("Updated after incident", 5)));
  expect(container.textContent).toContain("Updated after incident"); expect(read.data.order.order_version).toBe(5);
});
test("admin deferred detail after pagehide cannot disclose private data and refresh rejects changed cookie", async () => {
  let read; transport.get.mockResolvedValue(adminDetail("Initial private"));
  const Harness = () => { read = useOrderReadDetail({ actorId: "admin-a", role: "admin", token: null, apiUrl: "https://qa.invalid", isOnline: true }, "order-a"); return <div>{read.data?.order.customer_name}</div>; };
  await act(async () => root.render(<Harness />)); const gate = deferred(); transport.get.mockReturnValue(gate.promise);
  await act(async () => read.refresh()); const signal = transport.get.mock.calls.at(-1)[1].signal;
  await act(async () => window.dispatchEvent(new Event("pagehide"))); expect(signal.aborted).toBe(true);
  await act(async () => gate.resolve(adminDetail("Late private")));
  expect(container.textContent).not.toContain("private"); expect(read.data).toBeNull();
  transport.get.mockRejectedValue({ response: { status: 403 } }); await act(async () => read.refresh());
  expect(read.phase).toBe("error"); expect(read.data).toBeNull(); expect(transport.get.mock.calls.at(-1)[1].headers["X-Expected-Actor-ID"]).toBe("admin-a");
});
test("pagehide between returned receipt and consumer invalidates both leases", async () => {
  actor = { id: "actor-a", role: "restaurant", restaurant_id: "restaurant-a" }; let reporting;
  const Harness = () => { reporting = useOperationalReporting(actor, "gap", "https://qa.invalid", "token-a", true); return null; };
  await act(async () => root.render(<Harness />)); const lease = reporting.captureLease(); let receipt;
  await act(async () => { receipt = await reporting.submit({ operation_type: "close_day", resource_id: "restaurant-a" }); });
  expect(reporting.isCurrentReceipt(receipt)).toBe(true); expect(reporting.isCurrentLease(lease)).toBe(true);
  await act(async () => window.dispatchEvent(new Event("pagehide")));
  const consume = jest.fn(); if (reporting.isCurrentReceipt(receipt) && reporting.isCurrentLease(lease)) consume(receipt);
  expect(consume).not.toHaveBeenCalled(); expect(window.sessionStorage.length).toBe(1);
});
test("rehide during explicit revalidation retains suspension and sends no new close", async () => {
  actor = { id: "actor-a", role: "restaurant", restaurant_id: "restaurant-a" }; let reporting;
  const Harness = () => { reporting = useOperationalReporting(actor, "rehide", "https://qa.invalid", "token-a", true); return null; };
  await act(async () => root.render(<Harness />)); await act(async () => window.dispatchEvent(new Event("pagehide")));
  const gate = deferred(); transport.get.mockReturnValue(gate.promise); let action;
  await act(async () => { action = reporting.submit({ operation_type: "close_day", resource_id: "restaurant-a" }); });
  await act(async () => window.dispatchEvent(new Event("pagehide")));
  await act(async () => { gate.resolve({ status: 200, data: actor }); await action; });
  expect(reporting.suspended).toBe(true); expect(transport.patch).not.toHaveBeenCalled(); expect(window.sessionStorage.length).toBe(0);
});
test("history late response after pagehide stays private and changed cookie link forbids reread", async () => {
  actor = { id: "actor-a", role: "restaurant", restaurant_id: "restaurant-a" }; const gate = deferred(), entered = deferred();
  transport.get.mockImplementation(async (url) => { if (url.endsWith("/auth/me")) return { status: 200, data: actor }; entered.resolve(); return gate.promise; });
  const renderActor = { ...actor };
  await act(async () => root.render(<IncidentHistory actor={renderActor} token={null} apiUrl="https://qa.invalid" isOnline order={{ id: "order-a" }} />)); await entered.promise;
  await act(async () => window.dispatchEvent(new Event("pagehide")));
  await act(async () => gate.resolve({ status: 200, data: { incidents: [{ id: "incident-a", incident_type: "other", order_id: "order-a", description: "Private Sentinel" }], next_cursor: null } }));
  expect(container.textContent).not.toContain("Private Sentinel"); actor = { ...actor, restaurant_id: "restaurant-b" };
  const reads = transport.get.mock.calls.filter(([url]) => url.endsWith("/incidents")).length;
  await click("operational-incident-refresh"); expect(container.textContent).not.toContain("Private Sentinel");
  expect(transport.get.mock.calls.filter(([url]) => url.endsWith("/incidents")).length).toBe(reads);
});
test.each(["role", "restaurant_id"])("same actor id and token with changed %s invalidates returned receipt and private history", async (field) => {
  actor = { id: "actor-a", role: "restaurant", restaurant_id: "restaurant-a" }; let reporting;
  const Harness = ({ user }) => { reporting = useOperationalReporting(user, "context", "https://qa.invalid", "token-a", true); return <IncidentHistory actor={user} token="token-a" apiUrl="https://qa.invalid" isOnline order={{ id: "order-a" }} />; };
  const normal = transport.get.getMockImplementation(); transport.get.mockImplementation((url, config) => url.endsWith("/incidents") ? Promise.resolve({ status: 200, data: { incidents: [{ id: "incident-a", incident_type: "other", order_id: "order-a", description: "Prior Context" }], next_cursor: null } }) : normal(url, config));
  await act(async () => root.render(<Harness user={actor} />)); const lease = reporting.captureLease(); let receipt;
  await act(async () => { receipt = await reporting.submit({ operation_type: "close_day", resource_id: "restaurant-a" }); }); expect(container.textContent).toContain("Prior Context");
  const next = { ...actor, [field]: field === "role" ? "admin" : "restaurant-b" };
  await act(async () => root.render(<Harness user={next} />));
  expect(reporting.isCurrentReceipt(receipt)).toBe(false); expect(reporting.isCurrentLease(lease)).toBe(false); expect(container.textContent).not.toContain("Prior Context");
});
