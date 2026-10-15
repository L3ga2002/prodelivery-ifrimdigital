import { act, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { useOrderReadDetail, useOrderReads } from "./useOrderReads";
import { MAX_READ_CURSORS } from "../lib/orderReads";

jest.mock("axios", () => ({ create: jest.fn() }));
const order = { id: "order", restaurant_id: "restaurant", status: "NEW", order_version: 4, preparation_status: "NEW", created_at: "2026-10-08T10:00:00Z" };
const page = (items = [order], next = null) => ({ data: { items, next_cursor: next, has_more: next !== null, limit: 25, data_warnings: [] } });
const detail = (history = [], next = null, current = order) => ({ data: { order: current, history, next_history_before: next, history_has_more: next !== null, data_warnings: [] } });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
let root, container, result, transport;
function Harness({ actorId = "admin", token = "token-a", isOnline = true, filters = {}, reloadKey = 0, pollKey = 0, orderId, apiUrl = "https://qa.invalid" }) {
  const context = { actorId, token, apiUrl, isOnline, pollKey };
  const list = useOrderReads(context, filters, reloadKey);
  const one = useOrderReadDetail(context, orderId || "order", reloadKey);
  result = orderId ? one : list;
  return null;
}
const render = (props = {}) => act(async () => root.render(<StrictMode><Harness {...props} /></StrictMode>));
const pageCalls = () => transport.get.mock.calls.filter(([url]) => url.endsWith("/page"));
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; jest.clearAllMocks();
  transport = { get: jest.fn(async (url) => url.includes("/detail/") ? detail() : page()) };
  axios.create.mockReturnValue(transport); container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); jest.useRealTimers(); });

test("StrictMode sends one live bounded GET with isolated auth and expected actor", async () => {
  await render(); expect(result.phase).toBe("ready"); expect(pageCalls()).toHaveLength(1);
  expect(axios.create).toHaveBeenCalledWith({ withCredentials: true });
  expect(pageCalls()[0]).toEqual(["https://qa.invalid/api/orders/read/page", { params: { view: "active", limit: 25 }, timeout: 15000, signal: expect.any(AbortSignal), headers: { Authorization: "Bearer token-a", "X-Expected-Actor-ID": "admin" } }]);
});
test("next/previous read one page only, double navigation is ignored; refresh keeps filters and clears cursor", async () => {
  transport.get.mockImplementation(async (url, config) => url.includes("/detail/") ? detail() : config.params.cursor ? page([{ ...order, id: "second" }]) : page([order], "next"));
  await render({ filters: { view: "history", restaurant_id: "r" } });
  await act(async () => { result.next(); result.next(); });
  expect(result.items.map((o) => o.id)).toEqual(["second"]); expect(result.page).toBe(2); expect(pageCalls()).toHaveLength(2);
  await act(async () => result.previous()); expect(result.page).toBe(1); expect(result.items[0].id).toBe("order");
  await act(async () => result.next()); await act(async () => result.refresh());
  expect(result.page).toBe(1); expect(pageCalls().at(-1)[1].params).toEqual({ view: "history", restaurant_id: "r", limit: 25 });
});
test.each([{ actorId: "other" }, { token: "token-b" }, { filters: { view: "history" } }, { reloadKey: 1 }])("late data is fenced on actor/token/query/reload changes: %j", async (next) => {
  const late = deferred(); transport.get.mockImplementation((url) => url.includes("/detail/") ? Promise.resolve(detail()) : late.promise);
  await render(); const signal = pageCalls()[0][1].signal;
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail() : page([{ ...order, id: "fresh" }]));
  await render(next); expect(signal.aborted).toBe(true); expect(result.items[0].id).toBe("fresh");
  await act(async () => { late.resolve(page([{ ...order, id: "late-private" }])); await late.promise; });
  expect(result.items[0].id).toBe("fresh");
});
test("offline aborts and clears data; reconnect performs one finite GET without retry loop", async () => {
  await render(); await render({ isOnline: false }); expect(result.phase).toBe("offline"); expect(result.items).toEqual([]);
  const before = pageCalls().length; await render(); expect(pageCalls()).toHaveLength(before + 1); expect(result.phase).toBe("ready");
});
test.each([401, 403, 409, 422, 503])("HTTP %s remains visible and requires explicit refresh", async (status) => {
  transport.get.mockRejectedValue({ response: { status, data: { secret: "not shown" } } });
  await render(); expect(result.phase).toBe("error"); expect(result.items).toEqual([]); expect(result.error).not.toContain("secret");
  expect(pageCalls()).toHaveLength(1);
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail() : page());
  await act(async () => result.refresh()); expect(result.phase).toBe("ready");
});
test("15s deadline settles even if transport ignores abort; late response stays fenced", async () => {
  jest.useFakeTimers(); const late = deferred(); transport.get.mockReturnValue(late.promise);
  await render(); await act(async () => jest.advanceTimersByTime(15000));
  expect(result.phase).toBe("error"); expect(result.error).toContain("15 secunde"); expect(pageCalls()[0][1].signal.aborted).toBe(true);
  await act(async () => { late.resolve(page()); await late.promise; }); expect(result.phase).toBe("error");
  expect(pageCalls()).toHaveLength(1);
});
test("unmount aborts requests and late settlement cannot publish", async () => {
  const late = deferred(); transport.get.mockReturnValue(late.promise); await render(); const signal = pageCalls()[0][1].signal;
  await act(async () => root.unmount()); expect(signal.aborted).toBe(true);
  await act(async () => { late.resolve(page()); await late.promise; }); expect(result.phase).toBe("loading");
});
test("query validation prevents network reads and is repaired by valid filters", async () => {
  await render({ filters: { from_date: "2026-10-10", to_date: "2026-10-09" } });
  expect(result.phase).toBe("error"); expect(pageCalls()).toHaveLength(0); await render(); expect(result.phase).toBe("ready");
});
test("1001 orders are traversed only on demand and never accumulated; last page is finite", async () => {
  transport.get.mockImplementation(async (url, config) => {
    if (url.includes("/detail/")) return detail();
    const start = Number(config.params.cursor || 0), length = Math.min(25, 1001 - start);
    return page(Array.from({ length }, (_v, i) => ({ ...order, id: `order-${start + i}` })), start + length < 1001 ? String(start + length) : null);
  });
  await render(); expect(pageCalls()).toHaveLength(1);
  for (let i = 0; i < 40; i += 1) { await act(async () => result.next()); expect(result.items.length).toBeLessThanOrEqual(25); }
  expect(result.items.map((o) => o.id)).toEqual(["order-1000"]); expect(result.canNext).toBe(false); expect(result.page).toBe(41); expect(pageCalls()).toHaveLength(41);
});
test("cursor memory is bounded to 64 anchors and repeated cursor cannot loop", async () => {
  transport.get.mockImplementation(async (url, config) => url.includes("/detail/") ? detail() : page([order], String(Number(config.params.cursor || 0) + 1)));
  await render(); for (let i = 0; i < MAX_READ_CURSORS + 3; i += 1) await act(async () => result.next());
  for (let i = 0; i < MAX_READ_CURSORS - 1; i += 1) await act(async () => result.previous());
  expect(result.canPrevious).toBe(false); expect(result.page).toBe(5);
  transport.get.mockImplementation(async (url, config) => url.includes("/detail/") ? detail() : page([order], config.params.cursor || "same"));
  await act(async () => result.refresh()); await act(async () => result.next());
  expect(result.canNext).toBe(false); expect(result.cursorError).toContain("repetat");
});
test("detail uses stable history anchor, including zero, replaces history page and resets after mutation", async () => {
  transport.get.mockImplementation(async (url, config) => url.includes("/detail/") ? detail([{ action: config.params.history_before === undefined ? "newest" : "older" }], config.params.history_before === undefined ? 0 : null) : page());
  await render({ orderId: "order" }); await act(async () => result.next());
  expect(result.data.history.map((e) => e.action)).toEqual(["older"]); expect(transport.get.mock.calls.at(-1)[1].params.history_before).toBe(0);
  await render({ orderId: "order", reloadKey: 1 }); expect(result.page).toBe(1); expect(result.data.history[0].action).toBe("newest");
});
test("late detail on changed target cannot disclose previous order history", async () => {
  const late = deferred(); transport.get.mockImplementation((url) => url.includes("/detail/") ? late.promise : Promise.resolve(page()));
  await render({ orderId: "order" }); transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail([], null, { ...order, id: "new" }) : page());
  await render({ orderId: "new" }); await act(async () => { late.resolve(detail([{ action: "private-old-history" }])); await late.promise; });
  expect(result.data.order.id).toBe("new"); expect(result.data.history).toEqual([]);
});
test("cookie-only reads still carry expected actor and invalid actor never GETs", async () => {
  await render({ token: null }); expect(pageCalls()[0][1].headers).toEqual({ "X-Expected-Actor-ID": "admin" });
  const count = pageCalls().length; await render({ actorId: null }); expect(pageCalls()).toHaveLength(count); expect(result.phase).toBe("error");
});
test("successful parent poll shows incoming orders/status on first page without resetting filters", async () => {
  await render({ filters: { view: "active", restaurant_id: "restaurant" } });
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail() : page([{ ...order, status: "PREPARING" }, { ...order, id: "incoming" }]));
  await render({ filters: { view: "active", restaurant_id: "restaurant" }, pollKey: 1 });
  expect(result.items.map((o) => o.id)).toEqual(["order", "incoming"]); expect(result.items[0].status).toBe("PREPARING");
  expect(pageCalls()).toHaveLength(2); expect(pageCalls()[1][1].params).toEqual({ view: "active", restaurant_id: "restaurant", limit: 25 });
});
test("poll while slow read is in flight is skipped, does not abort/starve or defer a retry", async () => {
  const slow = deferred(); await render();
  transport.get.mockImplementation((url) => url.includes("/detail/") ? Promise.resolve(detail()) : slow.promise);
  await render({ pollKey: 1 }); const signal = pageCalls().at(-1)[1].signal;
  await render({ pollKey: 2 }); expect(signal.aborted).toBe(false); expect(pageCalls()).toHaveLength(2);
  await act(async () => { slow.resolve(page()); await slow.promise; }); expect(result.phase).toBe("ready"); expect(pageCalls()).toHaveLength(2);
});
test("periodic signals do not retry failed reads or GET while offline", async () => {
  transport.get.mockRejectedValue({ response: { status: 503 } }); await render(); await render({ pollKey: 1 });
  expect(result.phase).toBe("error"); expect(pageCalls()).toHaveLength(1);
  await render({ isOnline: false, pollKey: 2 }); expect(pageCalls()).toHaveLength(1); expect(result.phase).toBe("offline");
});

const supplementaryPathCharacter = String.fromCodePoint(0x1f600);
test.each([
  ["ASCII120", "a".repeat(120)], ["supplementary60", supplementaryPathCharacter.repeat(60)],
  ["supplementary61", supplementaryPathCharacter.repeat(61)], ["supplementary120", supplementaryPathCharacter.repeat(120)],
  ["mixed120", "\u00e9".repeat(60) + supplementaryPathCharacter.repeat(60)],
  ["escaped-path", "id/with?query#fragment%" + supplementaryPathCharacter],
])("R8 %s detail path and server filter params preserve exact identifier", async (_name, id) => {
  transport.get.mockImplementation(async (url) => url.includes("/detail/") ? detail([], null, { ...order, id }) : page([{ ...order, id }]));
  await render({ orderId: id, filters: { restaurant_id: id, driver_id: id } });
  expect(result.phase).toBe("ready"); expect(result.data.order.id).toBe(id);
  const [path, config] = transport.get.mock.calls.find(([url]) => url.includes("/detail/"));
  expect(path).toBe(`https://qa.invalid/api/orders/read/detail/${encodeURIComponent(id)}`);
  expect(decodeURIComponent(new URL(path).pathname.split("/").at(-1))).toBe(id);
  expect(path.length).toBeLessThanOrEqual("https://qa.invalid/api/orders/read/detail/".length + 1440);
  expect(config.headers["X-Expected-Actor-ID"]).toBe("admin");
  const [listPath, listConfig] = pageCalls()[0];
  expect(listConfig.params).toEqual({ view: "active", limit: 25, restaurant_id: id, driver_id: id });
  const encoded = new URL(listPath); Object.entries(listConfig.params).forEach(([key, value]) => encoded.searchParams.set(key, value));
  expect(encoded.searchParams.get("restaurant_id")).toBe(id); expect(encoded.searchParams.get("driver_id")).toBe(id);
  expect(encoded.search.length).toBeLessThanOrEqual(2 * 1440 + 100);
});
test.each([
  ["ASCII121", "a".repeat(121)], ["supplementary121", supplementaryPathCharacter.repeat(121)],
  ["mixed121", "\u00e9".repeat(61) + supplementaryPathCharacter.repeat(60)],
  ["control", "a\u0000b"], ["leading-space", " id"], ["trailing-space", "id "],
  ["unpaired-high", "\ud800"], ["unpaired-low", "\udc00"], ["unpaired-middle", "a\ud800b"],
])("R8 %s invalid detail/filter identifiers fail visibly before URL encoding or GET", async (_name, id) => {
  await render({ orderId: id, filters: { restaurant_id: id, driver_id: id } });
  expect(result.phase).toBe("error"); expect(result.error).toContain("Identificatorul"); expect(transport.get).not.toHaveBeenCalled();
});
