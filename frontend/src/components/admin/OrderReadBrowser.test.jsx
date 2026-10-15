import { act, Component, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { OrderReadBrowser } from "./OrderReadBrowser";
import { OrdersTab } from "./OrdersTab";

jest.mock("axios", () => ({ create: jest.fn() }));
jest.mock("../ui/dialog", () => {
  const Part = ({ children, ...props }) => <div data-testid={props["data-testid"]}>{children}</div>;
  return { Dialog: ({ open, children }) => open ? <div>{children}</div> : null, DialogContent: Part,
    DialogDescription: Part, DialogHeader: Part, DialogTitle: Part, DialogFooter: Part };
});
const order = { id: "order", order_number: "QA-1", restaurant_id: "restaurant", restaurant_name: "Restaurant sintetic", customer_name: "Nume vechi", customer_phone: "0712345678", customer_address: "Adresa sintetica", source: "S", total_amount: 20, status: "NEW", preparation_status: "NEW", order_version: 4, created_at: "2026-10-08T10:00:00Z" };
const page = (items = [order], next = null) => ({ data: { items, next_cursor: next, has_more: next !== null, limit: 25, data_warnings: [] } });
const detail = (current = { ...order, customer_name: "Nume proaspat", order_version: 8 }, next = null, action = "order.corrected") => ({ data: { order: current,
  history: [{ id: "event", action, performed_by: "admin", performed_by_role: "admin", created_at: order.created_at, from_order_version: 7, to_order_version: 8, changes: { from_status: "NEW", to_status: "PREPARING", old_driver_id: "old", new_driver_id: "new", fields: "customer_name" } }], next_history_before: next, history_has_more: next !== null, data_warnings: [] } });
let container, root, context, transport, assign, inspect;
const node = (id) => container.querySelector(`[data-testid="${id}"]`);
const click = (id) => act(async () => { const element = node(id); expect(element).not.toBeNull(); element.click(); });
const change = (id, value) => act(async () => {
  const element = node(id), prototype = element.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, value);
  element.dispatchEvent(new Event(element.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
});
const render = () => act(async () => root.render(<StrictMode><OrderReadBrowser context={context} onAssignOrder={assign} onInspectOrder={inspect} /></StrictMode>));
class ReadRenderBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error) { this.props.onError(error.message); }
  render() { return this.state.failed ? <p data-testid="order-read-render-failure">Render failed</p> : this.props.children; }
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; jest.clearAllMocks(); assign = jest.fn(); inspect = jest.fn();
  context = { actorId: "admin", role: "admin", token: "token-a", apiUrl: "https://qa.invalid", isOnline: true, reloadKey: 0,
    restaurants: [{ id: "restaurant", name: "Restaurant sintetic" }], drivers: [{ id: "driver", name: "Livrator sintetic" }] };
  transport = { get: jest.fn(async (url) => url.includes("/detail/") ? detail() : page()) };
  axios.create.mockReturnValue(transport); container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

test("optional context preserves the protected presentational OrdersTab default", async () => {
  await act(async () => root.render(<OrdersTab activeOrders={[order]} onAssignOrder={assign} onInspectOrder={inspect} />));
  expect(node("admin-orders-control-surface")).not.toBeNull(); expect(node("order-read-browser")).toBeNull();
  await click("admin-order-assign-button-order"); expect(assign).toHaveBeenCalledWith(order); expect(transport.get).not.toHaveBeenCalled();
});
test("context opts into paged browser; filters are server-side and count is page-only", async () => {
  await render(); expect(node("order-read-page").textContent).toBe("Pagina 1 | 1 pe pagina");
  await change("order-read-view", "history"); await change("order-read-status", "DELIVERED");
  await change("order-read-restaurant", "restaurant"); await change("order-read-driver", "driver");
  await change("order-read-from", "2026-10-08"); await change("order-read-to", "2026-10-09");
  expect(transport.get.mock.calls.at(-1)[1].params).toEqual({ view: "history", status: "DELIVERED", restaurant_id: "restaurant", driver_id: "driver", from_date: "2026-10-08T00:00:00.000Z", to_date: "2026-10-09T00:00:00.000Z", limit: 25 });
  expect(container.textContent).not.toContain("total comenzi");
});
test("Eye reads fresh detail/history and invokes correction callback with fresh revision", async () => {
  await render(); await click("order-read-eye-order");
  expect(node("order-read-detail-order").textContent).toContain("Nume proaspat"); expect(node("order-read-detail-order").textContent).toContain("Site");
  expect(node("order-read-history").textContent).toContain("Status anterior: Nou");
  expect(node("order-read-history").textContent).toContain("Livrator nou: new");
  await click("order-read-correct"); expect(inspect).toHaveBeenCalledWith(expect.objectContaining({ id: "order", order_version: 8, customer_name: "Nume proaspat" }));
  expect(node("order-read-detail")).toBeNull();
});
test.each([null, "4", true, {}])("malformed revision %j disables both correction and legacy assignment", async (version) => {
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail({ ...order, order_version: version }) : page([{ ...order, order_version: version }]));
  await render(); expect(node("order-read-assign-order")).toBeNull(); await click("order-read-eye-order");
  expect(node("order-read-correct")).toBeNull(); expect(inspect).not.toHaveBeenCalled(); expect(assign).not.toHaveBeenCalled();
});
test("legacy missing preparation/source projected null remains assignable without inventing values", async () => {
  const legacy = { ...order, preparation_status: null, source: null }; delete legacy.order_version;
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail(legacy) : page([legacy]));
  await render(); await click("order-read-assign-order"); expect(assign).toHaveBeenCalledWith(expect.objectContaining({ id: "order", source: null }));
  await click("order-read-eye-order"); expect(node("order-read-correct")).toBeNull(); expect(node("order-read-detail-order").textContent).toContain("Indisponibil");
});
test.each([{ read_actions_unavailable: true }, { status: "ALIEN" }, { driver_id: { raw: true } }])("unsafe backend action boundary %j remains read-only", async (fields) => {
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail({ ...order, ...fields }) : page([{ ...order, ...fields }]));
  await render(); expect(node("order-read-assign-order")).toBeNull(); await click("order-read-eye-order"); expect(node("order-read-correct")).toBeNull();
});
test("pending correction recovery boundary and non-admin role never offer a new correction", async () => {
  context.canCorrect = false; await render(); await click("order-read-eye-order"); expect(node("order-read-correct")).toBeNull();
  context = { ...context, role: "driver", canCorrect: true }; await render(); expect(node("order-read-correct")).toBeNull();
});
test("parent mutation refresh preserves filters, refreshes selected detail and resets cursor stacks", async () => {
  transport.get.mockImplementation(async (url, config) => url.includes("/detail/") ? detail(undefined, config.params.history_before === undefined ? 1 : null, config.params.history_before === undefined ? "newest" : "older") : page([order], config.params.cursor ? null : "next"));
  await render(); await change("order-read-view", "all"); await click("order-read-next"); await click("order-read-eye-order"); await click("order-read-history-next");
  expect(node("order-read-history-page").textContent).toBe("Pagina 2");
  context = { ...context, reloadKey: 1 }; await render();
  expect(node("order-read-view").value).toBe("all"); expect(node("order-read-page").textContent).toContain("Pagina 1");
  expect(node("order-read-history-page").textContent).toBe("Pagina 1"); expect(node("order-read-history").textContent).toContain("newest");
});
test("parent poll/options rerender does not refetch or reset detail/history and filters", async () => {
  transport.get.mockImplementation(async (url, config) => url.includes("/detail/") ? detail(undefined, config.params.history_before === undefined ? 1 : null) : page([order], config.params.cursor ? null : "next"));
  await render(); await change("order-read-view", "all"); await click("order-read-next"); await click("order-read-eye-order"); await click("order-read-history-next");
  const count = transport.get.mock.calls.length; context = { ...context, restaurants: [...context.restaurants], drivers: [...context.drivers] }; await render();
  expect(transport.get).toHaveBeenCalledTimes(count); expect(node("order-read-page").textContent).toContain("Pagina 2"); expect(node("order-read-history-page").textContent).toBe("Pagina 2");
});
test("successful parent poll revalidates page two at same cursor and does not reset/refetch detail history", async () => {
  context.pollKey = 0;
  transport.get.mockImplementation(async (url, config) => url.includes("/detail/") ? detail(undefined, config.params.history_before === undefined ? 1 : null) : page([order], config.params.cursor ? null : "next"));
  await render(); await change("order-read-view", "all"); await click("order-read-next"); await click("order-read-eye-order"); await click("order-read-history-next");
  const count = transport.get.mock.calls.length; context = { ...context, pollKey: 1 }; await render();
  expect(transport.get).toHaveBeenCalledTimes(count + 1); expect(transport.get.mock.calls.at(-1)[1].params).toEqual({ view: "all", limit: 25, cursor: "next" });
  expect(node("order-read-view").value).toBe("all"); expect(node("order-read-page").textContent).toContain("Pagina 2"); expect(node("order-read-history-page").textContent).toBe("Pagina 2");
});
test("actor/token change closes detail and removes previous actor's rendered data", async () => {
  await render(); await click("order-read-eye-order"); context = { ...context, actorId: "other", token: "other-token" };
  transport.get.mockResolvedValue(page([])); await render(); expect(node("order-read-detail")).toBeNull(); expect(node("order-read-empty")).not.toBeNull(); expect(container.textContent).not.toContain("Nume proaspat");
});
test("delayed detail displays loading without stale callback; offline/error/empty states are explicit", async () => {
  let resolve; transport.get.mockImplementation((url) => url.includes("/detail/") ? new Promise((done) => { resolve = done; }) : Promise.resolve(page()));
  await render(); await click("order-read-eye-order"); expect(node("order-read-detail").textContent).toContain("Se incarca"); expect(node("order-read-correct")).toBeNull();
  await act(async () => resolve(detail())); expect(node("order-read-correct")).not.toBeNull();
  context = { ...context, isOnline: false }; await render(); expect(node("order-read-correct")).toBeNull(); expect(container.textContent).toContain("Fara internet");
  transport.get.mockRejectedValue({ response: { status: 503 } }); context = { ...context, isOnline: true }; await render(); expect(container.textContent).toContain("temporar indisponibila");
});
test("untrusted strings render as text and raw history objects never reach DOM", async () => {
  const response = detail(); response.data.history[0].changes = { customer_name: "<img src=x onerror=alert(1)>", notes: { raw: true } };
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? response : page());
  await render(); await click("order-read-eye-order"); expect(node("order-read-detail").querySelector("img")).toBeNull(); expect(node("order-read-history").textContent).toContain("<img src=x");
  expect(node("order-read-history").textContent).not.toContain("[object Object]");
});
test("backend omission+warning for malformed audit is not rendered as a false deletion", async () => {
  const response = detail(); response.data.history[0].changes = { from_preparation_status: "PREPARING", to_preparation_status: "READY" };
  response.data.data_warnings = ["HISTORY_FIELD_INVALID"];
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? response : page());
  await render(); await click("order-read-eye-order");
  expect(node("order-read-history").textContent).toContain("Pregatire anterioara: Preparare"); expect(node("order-read-history").textContent).toContain("Pregatire noua: Gata");
  expect(node("order-read-history").textContent).not.toContain("Eliminat"); expect(node("order-read-detail").textContent).toContain("HISTORY_FIELD_INVALID");
});
test("only an approved explicit null audit scalar renders Eliminat", async () => {
  const response = detail(); response.data.history[0].changes = { notes: null, customer_name: { malformed: true } };
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? response : page());
  await render(); await click("order-read-eye-order"); expect(node("order-read-history").textContent).toContain("Note: Eliminat");
  expect(node("order-read-history").textContent).not.toContain("Nume client: Eliminat");
});
test("actual backend omission of absent preparation permits eligible versioned correction without helper changes", async () => {
  const projected = { ...order, read_actions_unavailable: false }; delete projected.preparation_status;
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail(projected) : page([projected]));
  await render(); await click("order-read-eye-order"); expect(node("order-read-correct")).not.toBeNull();
  await click("order-read-correct"); expect(inspect).toHaveBeenCalledWith(expect.objectContaining({ order_version: 4 }));
  expect(inspect.mock.calls[0][0]).not.toHaveProperty("preparation_status");
});
test.each([null, { malformed: true }, "ALIEN"])("stored explicit preparation %j never offers versioned correction", async (value) => {
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail({ ...order, preparation_status: value }) : page());
  await render(); await click("order-read-eye-order"); expect(node("order-read-correct")).toBeNull(); expect(inspect).not.toHaveBeenCalled();
});

const prototypeKeys = ["__proto__", "constructor", "toString", "hasOwnProperty", "valueOf", "legacy.unknown_action"];
test.each(prototypeKeys.flatMap((value) => ["action", "status", "role", "fields"].map((field) => ({ field, value }))))("R7 StrictMode safely renders unknown $field=$value without errors or warnings", async ({ field, value }) => {
  const response = detail(), entry = response.data.history[0];
  if (field === "action") entry.action = value;
  if (field === "role") entry.performed_by_role = value;
  if (field === "status") entry.changes = { from_status: value, to_status: value, from_preparation_status: value, to_preparation_status: value, preparation_status: value };
  if (field === "fields") entry.changes.fields = `${value}, customer_name`;
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? response : page());
  const errors = [], errorLog = jest.spyOn(console, "error").mockImplementation(() => {}), warningLog = jest.spyOn(console, "warn").mockImplementation(() => {});
  try {
    await act(async () => root.render(<StrictMode><ReadRenderBoundary onError={(message) => errors.push(message)}><OrderReadBrowser context={context} onAssignOrder={assign} onInspectOrder={inspect} /></ReadRenderBoundary></StrictMode>));
    await click("order-read-eye-order");
    expect(errors).toEqual([]); expect(errorLog).not.toHaveBeenCalled(); expect(warningLog).not.toHaveBeenCalled();
    expect(node("order-read-detail")).not.toBeNull(); const history = node("order-read-history"); expect(history).not.toBeNull();
    expect(history.textContent).not.toMatch(/\[object Object\]|function\s/);
    if (field === "action") expect(history.querySelector("p").textContent).toBe(value);
    if (field === "role") expect(history.textContent).toContain("Indisponibil | admin");
    if (field === "status") expect(history.textContent).toContain("Status anterior: Indisponibil");
    if (field === "fields") expect(history.textContent).toContain(`Campuri corectate: ${value}, Nume client`);
  } finally { errorLog.mockRestore(); warningLog.mockRestore(); }
});
