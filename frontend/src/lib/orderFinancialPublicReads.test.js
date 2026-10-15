import { readOrderFinance, clientCollectionText } from "./orderFinance";
import { parseOrderPage, parseOrderDetail } from "./orderReads";
import { readFinancialActivity, financialEventEligibility } from "./orderFinancialActivity";
import { readCustodyActivity } from "./orderCustody";
import { custodyOrder, IDS } from "./orderCustody.fixtures";
import { pureLegacyRemake } from "./orderRemakeFinance";

const full = (payment = "CASH") => ({ id: "order", restaurant_id: "restaurant", driver_id: "driver", status: "ACCEPTED", source: "S",
  created_at: "2026-10-15T00:00:00Z", payment_type: payment, order_version: 3, financial_contract_version: 1,
  financial: { contract_version: 1, currency: "RON", restaurant_id: "restaurant", tariff_version: "public-v1", products_bani: 4321,
    collection_mode: payment === "CASH" ? "cash" : "prepaid", client_collection_bani: payment === "CASH" ? 4321 : 0,
    restaurant_transport_bani: 1600, courier_remuneration_bani: 917, advance_required_bani: payment === "CASH" ? 4321 : 0,
    advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null, basis: "zone", snapshot_at: "2026-10-15T00:00:00Z",
    snapshot_digest: "a".repeat(64), operation_ref: "PRIVATE", tariff_rule: { private: "PRIVATE" } } });
const publicOrder = (visibility = "restaurant", payment = "CASH") => {
  const order = full(payment);
  for (const key of ["snapshot_digest", "operation_ref", "tariff_rule"]) delete order.financial[key];
  if (visibility === "restaurant") delete order.financial.courier_remuneration_bani;
  return { ...order, financial_read_contract_version: 1, financial_read_visibility: visibility };
};
const page = (order) => parseOrderPage({ items: [order], next_cursor: null, has_more: false, limit: 25, data_warnings: [] }).items[0];
const envelope = (order, history = []) => ({ order, history, next_history_before: null, history_has_more: false, data_warnings: [],
  read_contract_version: 1, read_visibility: order.financial_read_visibility || "restaurant" });
const detail = (order) => parseOrderDetail(envelope(order), order.id).order;

test.each(["restaurant", "assigned_driver"])("public %s exact contract survives both parsers and a second parse", (visibility) => {
  for (const payment of ["CASH", "CARD"]) {
    const order = publicOrder(visibility, payment), before = JSON.stringify(order);
    for (const read of [order, page(order), detail(order), page(page(order)), detail(detail(order))]) {
      expect(readOrderFinance(read)).toEqual({ state: "ready", value: order.financial });
      expect(Object.hasOwn(read.financial, "courier_remuneration_bani")).toBe(visibility === "assigned_driver");
      expect(clientCollectionText(read)).toBe(payment === "CASH" ? "43,21 RON" : "0,00 RON");
      expect(JSON.stringify(read.financial)).not.toMatch(/PRIVATE|snapshot_digest|tariff_rule|operation_ref/);
    }
    expect(JSON.stringify(order)).toBe(before);
  }
});
test.each([true, false, "1", null, -1, 0.1, 100000001, NaN, Infinity, Number.MAX_SAFE_INTEGER])("public money rejects %p", (bad) => {
  for (const key of ["products_bani", "client_collection_bani", "restaurant_transport_bani", "advance_required_bani", "courier_remuneration_bani"]) {
    const order = publicOrder("assigned_driver"); order.financial[key] = bad;
    expect(readOrderFinance(order).state).toBe("invalid"); expect(page(order).read_actions_unavailable).toBe(true);
  }
});
test.each(["advance_paid_bani", "refund_due_bani", "refund_paid_bani"])("public %s must be present and exactly null", (field) => {
  for (const bad of [undefined, 0, false, "0", 1]) {
    const order = publicOrder(); order.financial[field] = bad; expect(readOrderFinance(order).state).toBe("invalid");
  }
  const order = publicOrder(); delete order.financial[field]; expect(readOrderFinance(order).state).toBe("invalid");
});
test.each(["snapshot_digest", "tariff_rule", "operation_ref", "courier_remuneration_bani", "salary", "extra"])("restaurant DTO rejects extra %s even null", (field) => {
  const order = publicOrder(); order.financial[field] = null;
  expect(readOrderFinance(order).state).toBe("invalid"); expect(detail(order).read_data_invalid).toBe(true);
});
test.each(["", " r ", "x\u0000", "\ud800", "x".repeat(121)])("public identity rejects invalid case %#", (value) => {
  for (const field of ["restaurant_id", "tariff_version"]) {
    const order = publicOrder(); order.financial[field] = value; if (field === "restaurant_id") order.restaurant_id = value;
    expect(readOrderFinance(order).state).toBe("invalid");
  }
});
test.each(["2026-02-30T00:00:00Z", "2026-10-15T00:00:00+03:00", "2026-10-15", "0000-01-01T00:00:00Z", 0, null])("public UTC time rejects %p", (value) => {
  const order = publicOrder(); order.financial.snapshot_at = value; expect(readOrderFinance(order).state).toBe("invalid");
});
test("strict marker pairs and obligations cannot downgrade to full or legacy", () => {
  for (const patch of [{ financial_read_contract_version: true }, { financial_read_contract_version: null }, { financial_read_visibility: "admin" },
    { financial_contract_version: true }, { restaurant_id: "foreign" }, { payment_type: "CARD" }]) {
    expect(readOrderFinance({ ...publicOrder(), ...patch }).state).toBe("invalid");
  }
  for (const field of ["financial_read_contract_version", "financial_read_visibility", "financial_contract_version", "financial"]) {
    const order = publicOrder(); delete order[field]; expect(readOrderFinance(order).state).toBe("invalid");
  }
  const order = publicOrder(); order.financial.advance_required_bani = 0; expect(readOrderFinance(order).state).toBe("invalid");
  expect(readOrderFinance(full()).state).toBe("ready");
});
test("absent legacy survives normalized roundtrip and old remake eligibility; own null or undefined does not", () => {
  const legacy = { id: "order", restaurant_id: "restaurant", status: "DELIVERED", source: "S", total_amount: 12, created_at: "2026-10-15T00:00:00Z" };
  for (const value of [legacy, page(legacy), detail(legacy), page(page(legacy))]) {
    expect(readOrderFinance(value).state).toBe("legacy"); expect(Object.hasOwn(value, "financial")).toBe(false);
    expect(pureLegacyRemake(value)).toBe(true);
  }
  for (const value of [null, undefined, {}, false]) {
    const order = { ...legacy, financial: value }; expect(readOrderFinance(order).state).toBe("invalid");
    expect(readOrderFinance(page(order)).state).toBe("invalid"); expect(pureLegacyRemake(page(order))).toBe(false);
  }
});
test("public detail discriminator binds role and strict bounded history, while admin history stays full", () => {
  const history = [{ index: 0, id: "h", action: "created", performed_by: "u", performed_by_role: "admin", created_at: "2026-10-15T00:00:00Z", changes: { notes: "kept" } }];
  const parsed = parseOrderDetail(envelope(publicOrder(), history), "order");
  expect(parsed.history[0].index).toBe(0); expect(parsed.read_visibility).toBe("restaurant");
  for (const key of ["courier_remuneration_bani", "financial_snapshot_digest", "operation_ref", "tariff_rule"]) {
    const bad = JSON.parse(JSON.stringify(history)); bad[0].changes[key] = null;
    expect(() => parseOrderDetail(envelope(publicOrder(), bad), "order")).toThrow();
  }
  for (const patch of [{ read_contract_version: true }, { read_visibility: "assigned_driver" }]) {
    expect(() => parseOrderDetail({ ...envelope(publicOrder()), ...patch }, "order")).toThrow();
  }
  const admin = envelope(full(), [{ ...history[0], changes: { courier_remuneration_bani: 917, financial_snapshot_digest: "a".repeat(64) } }]);
  delete admin.read_contract_version; delete admin.read_visibility;
  expect(parseOrderDetail(admin, "order").history[0].changes.courier_remuneration_bani).toBe(917);
});
test("public activity and custody retain exact obligations without snapshot digests", () => {
  const order = publicOrder("assigned_driver");
  expect(financialEventEligibility(order, { role: "driver", driver_id: "driver" }).amount_bani).toBe(4321);
  order.financial_activity_contract_version = 1;
  order.financial_activity = { contract_version: 1, status: "declared", driver_id: "driver", declared_unpaid_bani: 4321,
    declaration_id: IDS[0], approval_id: null, declared_at: "2026-10-15T00:00:00Z", approved_at: null, picked_up_at: null,
    outstanding_bani: null, repayment_due_policy: null };
  expect(readFinancialActivity(detail(order)).state).toBe("ready");
  expect(financialEventEligibility(order, { role: "restaurant", restaurant_id: "restaurant" }).declaration_id).toBe(IDS[0]);
  for (const status of ["waiting", "reviewed", "returned", "kept"]) {
    const custodied = { ...publicOrder(), ...custodyOrder(status) };
    expect(readCustodyActivity(detail(custodied)).state).toBe("ready");
    expect(readOrderFinance(custodied).value.refund_due_bani).toBeNull();
  }
});
test("public incident summary is exact and corruption disables actions", () => {
  const order = { ...publicOrder(), incident_summary: [{ id: "incident", incident_type: "other" }] };
  expect(detail(order).incident_summary).toEqual(order.incident_summary);
  for (const incident_summary of [[{ ...order.incident_summary[0], operation_ref: "private" }], Array(51).fill(order.incident_summary[0]), null]) {
    expect(page({ ...order, incident_summary }).read_actions_unavailable).toBe(true);
  }
});

test.each(["restaurant", "assigned_driver"])("public %s envelope rejects a full snapshot without public row markers", (visibility) => {
  const order = full(), before = JSON.stringify(order);
  expect(readOrderFinance(order).state).toBe("ready");
  expect(() => parseOrderDetail({ ...envelope(order), read_visibility: visibility }, order.id)).toThrow();
  expect(JSON.stringify(order)).toBe(before);
});

test.each(["restaurant", "assigned_driver"])("public %s envelope binds every own financial signal while preserving true legacy absence", (visibility) => {
  const legacy = { id: "legacy", restaurant_id: "restaurant", status: "DELIVERED", source: "S",
    total_amount: 12, created_at: "2026-10-15T00:00:00Z" };
  const parse = (order) => parseOrderDetail({ ...envelope(order), read_visibility: visibility }, order.id).order;
  const normalized = parse(legacy);
  expect(readOrderFinance(normalized).state).toBe("legacy");
  expect(pureLegacyRemake(normalized)).toBe(true);
  for (const key of ["financial", "financial_contract_version", "financial_read_contract_version", "financial_read_visibility"]) {
    for (const value of [undefined, null, false, 1]) expect(() => parse({ ...legacy, [key]: value })).toThrow();
  }
  for (const patch of [{ financial_read_contract_version: undefined }, { financial_read_visibility: null },
    { financial_read_contract_version: true }, { financial_read_visibility: visibility === "restaurant" ? "assigned_driver" : "restaurant" }]) {
    expect(() => parse({ ...publicOrder(visibility), ...patch })).toThrow();
  }
  const invalid = parse({ ...legacy, financial: null, financial_contract_version: 1,
    financial_read_contract_version: 1, financial_read_visibility: visibility });
  expect(readOrderFinance(invalid).state).toBe("invalid");
  expect(invalid.read_actions_unavailable).toBe(true);
  expect(pureLegacyRemake(invalid)).toBe(false);
});

test("unmarked admin detail retains existing full-schema salary and digest normalization", () => {
  const order = full(), raw = envelope(order);
  delete raw.read_contract_version; delete raw.read_visibility;
  const normalized = parseOrderDetail(raw, order.id).order.financial;
  expect(normalized).toEqual(readOrderFinance(order).value);
  expect(normalized.courier_remuneration_bani).toBe(917);
  expect(normalized.snapshot_digest).toBe("a".repeat(64));
});
