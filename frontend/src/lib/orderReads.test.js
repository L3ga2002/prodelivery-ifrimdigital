import { emptyReadFilters, formatReadTime, normalizeReadFilters, orderReadError, ORDER_SOURCE_LABELS, ORDER_STATUS_LABELS, parseOrderDetail, parseOrderPage, readOwnLabel, readText, readTimestamp, validReadActor } from "./orderReads";
import { isOrderEditable } from "./orderEditingRecovery";
import { hasAssignmentRevision, isOrderAssignable } from "./orderAssignmentRecovery";

const order = { id: "order", restaurant_id: "restaurant", status: "NEW", order_version: 4, preparation_status: "NEW", created_at: "2026-10-08T10:00:00Z" };
const page = (items = [order], extra = {}) => ({ items, next_cursor: null, has_more: false, limit: 25, data_warnings: [], ...extra });
const detail = (extra = {}) => ({ order, history: [], next_history_before: null, history_has_more: false, data_warnings: [], ...extra });

test("filters have bounded limit and explicit inclusive-start/exclusive-end UTC dates", () => {
  expect(normalizeReadFilters(emptyReadFilters())).toEqual({ view: "active", limit: 25 });
  expect(normalizeReadFilters({ view: "history", status: "DELIVERED", restaurant_id: "r", driver_id: "d", from_date: "2026-10-08", to_date: "2026-10-09" })).toEqual({ view: "history", status: "DELIVERED", restaurant_id: "r", driver_id: "d", from_date: "2026-10-08T00:00:00.000Z", to_date: "2026-10-09T00:00:00.000Z", limit: 25 });
});
test.each([{ view: "bad" }, { status: "bad" }, { restaurant_id: " " }, { driver_id: {} }, { limit: 0 }, { limit: 101 }, { from_date: "2026-02-30" }, { to_date: "0000-01-01" }, { from_date: "2026-10-09", to_date: "2026-10-09" }, { from_date: "2026-10-10", to_date: "2026-10-09" }])("invalid query is rejected locally: %j", (filters) => expect(() => normalizeReadFilters(filters)).toThrow());
test.each([null, [], {}, { items: [], limit: 25, has_more: false }, page([], { has_more: "false" }), page([], { has_more: true }), page([], { next_cursor: "c" }), page([], { limit: 26 }), page(new Array(26).fill(order)), page([], { data_warnings: ["<script>"] })])("invalid envelope cannot masquerade as empty: %j", (value) => expect(() => parseOrderPage(value)).toThrow());
test("mixed fields and duplicate IDs warn without rendering objects or inventing status/date", () => {
  const result = parseOrderPage(page([{ ...order, customer_name: { unsafe: true }, status: "ALIEN", created_at: "2026-02-30T10:00:00Z", secrets: "hidden" }, order, null, { id: {} }]));
  expect(result.items).toHaveLength(1); expect(result.items[0]).not.toHaveProperty("customer_name");
  expect(result.items[0]).not.toHaveProperty("status"); expect(result.items[0].created_at).toBeNull();
  expect(result.items[0]).not.toHaveProperty("secrets"); expect(result.items[0].read_data_invalid).toBe(true);
  expect(result.data_warnings).toEqual(expect.arrayContaining(["INVALID_ORDER_FIELDS", "DUPLICATE_ORDER_ITEM", "INVALID_ORDER_ITEM", "ORDER_DATE_UNAVAILABLE"]));
});
test.each([null, true, "4", {}, -1, Number.MAX_SAFE_INTEGER + 1])("any malformed revision presence remains versioned, never legacy: %j", (value) => {
  const parsed = parseOrderPage(page([{ ...order, order_version: value }])).items[0];
  expect(Object.hasOwn(parsed, "order_version")).toBe(true); expect(hasAssignmentRevision(parsed)).toBe(true);
  expect(isOrderAssignable(parsed)).toBe(false); expect(isOrderEditable(parsed)).toBe(false);
});
test("valid revisions and preparation/custody fields are preserved for existing workflows", () => {
  const parsed = parseOrderDetail(detail({ order: { ...order, preparation_due_at: null, preparation_time: 15, driver_id: null, assigned_at: null } }), "order").order;
  expect(parsed.order_version).toBe(4); expect(parsed.preparation_time).toBe(15); expect(parsed.preparation_due_at).toBeNull();
  expect(isOrderEditable(parsed)).toBe(true); expect(isOrderAssignable(parsed)).toBe(true);
});
test("missing optional enum fields projected null do not disable legitimate legacy assignment", () => {
  const legacy = { ...order, preparation_status: null, source: null }; delete legacy.order_version;
  const parsed = parseOrderPage(page([legacy])).items[0];
  expect(parsed.preparation_status).toBeNull(); expect(parsed.source).toBeNull();
  expect(parsed.read_data_invalid).toBeUndefined(); expect(isOrderAssignable(parsed)).toBe(true);
  expect(parsed).not.toHaveProperty("order_version");
});
test("absent preparation projection permits versioned correction; explicit null/malformed stays ineligible", () => {
  const projected = { ...order, read_actions_unavailable: false }; delete projected.preparation_status;
  const parsed = parseOrderDetail(detail({ order: projected }), "order").order;
  expect(parsed).not.toHaveProperty("preparation_status"); expect(isOrderEditable(parsed)).toBe(true);
  [null, { malformed: true }, "ALIEN"].forEach((value) => {
    const invalid = parseOrderDetail(detail({ order: { ...projected, preparation_status: value } }), "order").order;
    expect(Object.hasOwn(invalid, "preparation_status")).toBe(true); expect(isOrderEditable(invalid)).toBe(false);
  });
});
test("detail keeps canonical safe scalar audit only and no internal/raw data", () => {
  const result = parseOrderDetail(detail({ history: [{ id: "audit", action: "order.corrected", performed_by: "admin", performed_by_role: "admin", created_at: order.created_at, from_order_version: 3, to_order_version: 4,
    changes: { customer_name: "<b>plain</b>", notes: null, from_status: "NEW", old_driver_id: "old", new_driver_id: "new", fields: "customer_name", credentials: "hidden", raw: { nested: true } }, ledger: "hidden" }, null] }), "order");
  expect(result.history).toHaveLength(1); expect(result.history[0].changes).toEqual({ customer_name: "<b>plain</b>", notes: null, from_status: "NEW", old_driver_id: "old", new_driver_id: "new", fields: "customer_name" });
  expect(result.history[0]).not.toHaveProperty("ledger"); expect(result.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
});
test.each([detail({ order: { ...order, id: "foreign" } }), detail({ history_has_more: true }), detail({ next_history_before: -1 }), detail({ history_has_more: true, next_history_before: 7 }), detail({ history: new Array(51).fill({}) })])("wrong detail or invalid/non-decreasing history anchor fails", (value) => expect(() => parseOrderDetail(value, "order", 7)).toThrow());
test("history anchor zero is valid; absent dates remain unavailable", () => {
  const result = parseOrderDetail(detail({ history_has_more: true, next_history_before: 0, history: [{ action: "legacy" }] }), "order", 3);
  expect(result.next_history_before).toBe(0); expect(result.history[0].created_at).toBeNull();
  expect(formatReadTime(undefined)).toBe("Indisponibil"); expect(readText({ raw: true })).toBe("Indisponibil");
});
test.each(["2026-02-30T10:00:00Z", "2026-10-08T25:00:00Z", "2026-10-08T10:00:00+25:00", "yesterday", {}, null])("malformed timestamp is not normalized into an invented time: %j", (value) => expect(readTimestamp(value)).toBeNull());
test("offset dates normalize UTC and malformed identifiers cannot reach URL encoder", () => {
  expect(readTimestamp("2026-10-08T13:00:00+03:00")).toBe("2026-10-08T10:00:00.000Z");
  expect(validReadActor("\ud800")).toBe(false); expect(validReadActor("admin\n")).toBe(false);
});
test.each([[401, "Sesiunea"], [403, "Sesiunea"], [409, "Contul"], [422, "Filtre"], [404, "Comanda"], [503, "temporar"]])("safe HTTP %s errors do not echo backend objects", (status, text) => expect(orderReadError({ response: { status, data: { detail: "secret" } } })).toContain(text));
test("unknown transport failures never echo private error messages", () => expect(orderReadError(new Error("SECRET"))).not.toContain("SECRET"));
test("compact cursor contract accepts 4096 characters but rejects oversized tokens", () => {
  expect(parseOrderPage(page([], { has_more: true, next_cursor: "c".repeat(4096) })).next_cursor).toHaveLength(4096);
  expect(() => parseOrderPage(page([], { has_more: true, next_cursor: "c".repeat(4097) }))).toThrow();
});
test.each(["__proto__", "constructor", "toString", "hasOwnProperty", "valueOf", "legacy.unknown_action"])("R7 own-string labels never resolve inherited key %s", (key) => {
  expect(readOwnLabel(ORDER_STATUS_LABELS, key)).toBe("Indisponibil");
  expect(readOwnLabel(ORDER_SOURCE_LABELS, key)).toBe("Indisponibil");
  expect(readOwnLabel({ known: "Eticheta" }, key, key)).toBe(key);
});
test.each([null, undefined, {}, () => {}, true, 7, Symbol("label")])("R7 non-string keys cannot coerce into dictionary properties", (key) => expect(readOwnLabel({ known: "Eticheta" }, key)).toBe("Indisponibil"));
test("R7 only own string values are usable; non-string own labels and inherited labels fall back", () => {
  const labels = Object.assign(Object.create({ inherited: "Nu se foloseste" }), { known: "Eticheta", object: {}, fn: () => {}, number: 1 });
  expect(readOwnLabel(labels, "known")).toBe("Eticheta");
  ["inherited", "object", "fn", "number"].forEach((key) => expect(readOwnLabel(labels, key)).toBe("Indisponibil"));
  expect(readOwnLabel(Object.assign(Object.create(null), { known: "Eticheta" }), "known")).toBe("Eticheta");
  expect(readOwnLabel(labels, "unknown", { raw: true })).toBe("Indisponibil");
  expect(readOwnLabel(ORDER_STATUS_LABELS, "READY")).toBe("Gata"); expect(readOwnLabel(ORDER_SOURCE_LABELS, "S")).toBe("Site");
});

const supplementaryIdCharacter = String.fromCodePoint(0x1f600);
const idBoundaries = [
  ["ASCII120", "a".repeat(120), true], ["ASCII121", "a".repeat(121), false],
  ["supplementary60", supplementaryIdCharacter.repeat(60), true], ["supplementary61", supplementaryIdCharacter.repeat(61), true],
  ["supplementary120", supplementaryIdCharacter.repeat(120), true], ["supplementary121", supplementaryIdCharacter.repeat(121), false],
  ["mixed120", "\u00e9".repeat(60) + supplementaryIdCharacter.repeat(60), true],
  ["mixed121", "\u00e9".repeat(61) + supplementaryIdCharacter.repeat(60), false],
  ["internal-space120", "a".repeat(59) + " " + supplementaryIdCharacter.repeat(60), true],
  ["internal-control", "a\u0000b", false], ["control31", "a\u001fb", false], ["DEL", "a\u007fb", false],
  ["leading-space", " id", false], ["trailing-space", "id ", false], ["only-space", " ", false],
  ["leading-NBSP", "\u00a0id", false], ["trailing-tab", "id\t", false],
  ["unpaired-high", "\ud800", false], ["unpaired-low", "\udc00", false],
  ["unpaired-high-middle", "a\ud800b", false], ["unpaired-low-middle", "a\udc00b", false],
];
test.each(idBoundaries)("R8 %s page/detail/filter identity follows 1..120 code points", (_name, id, valid) => {
  expect(validReadActor(id)).toBe(valid);
  const projected = { ...order, id, restaurant_id: id, driver_id: id, created_at: "2026-10-08T10:00:00.000Z", read_actions_unavailable: false };
  const result = parseOrderPage(page([projected]));
  if (valid) {
    expect(result.items).toHaveLength(1); expect(result.items[0]).toEqual(projected);
    expect(result.data_warnings).not.toContain("INVALID_ORDER_ITEM");
    expect(parseOrderDetail(detail({ order: projected }), id).order.id).toBe(id);
    expect(normalizeReadFilters({ restaurant_id: id, driver_id: id })).toEqual({ view: "active", limit: 25, restaurant_id: id, driver_id: id });
    expect(decodeURIComponent(encodeURIComponent(id))).toBe(id);
    expect(encodeURIComponent(id).length).toBeLessThanOrEqual(1440);
  } else {
    expect(result.items).toEqual([]); expect(result.data_warnings).toContain("INVALID_ORDER_ITEM");
    expect(() => parseOrderDetail(detail({ order: projected }), id)).toThrow();
    expect(() => normalizeReadFilters({ restaurant_id: id })).toThrow();
    expect(() => normalizeReadFilters({ driver_id: id })).toThrow();
  }
});
test("R8 supplementary IDs differing at the last code point are not truncated or normalized", () => {
  const first = supplementaryIdCharacter.repeat(119) + "a", second = supplementaryIdCharacter.repeat(119) + "b";
  const result = parseOrderPage(page([{ ...order, id: first }, { ...order, id: second }]));
  expect(result.items.map((item) => item.id)).toEqual([first, second]); expect(result.data_warnings).not.toContain("DUPLICATE_ORDER_ITEM");
  expect(() => parseOrderDetail(detail({ order: { ...order, id: first } }), second)).toThrow("nu corespunde");
});
