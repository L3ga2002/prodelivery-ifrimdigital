import { custodyCommandEligible, custodyBlocksNormalMutation, readCustodyActivity, custodyResolved } from "./orderCustody";
import { parseOrderDetail } from "./orderReads";
import { readFinancialActivity } from "./orderFinancialActivity";
import { canChangeOrderStatus } from "./orderStatusRecovery";
import { IDS, custodyOrder, driver, restaurant, admin, waitCommand } from "./orderCustody.fixtures";
const detail = (order) => parseOrderDetail({ order, history: [], next_history_before: null, history_has_more: false, data_warnings: [] }, order.id).order;
test.each(["waiting", "reviewed", "return_requested", "keep_authorized", "returned", "kept"])("strict %s projection survives public read", (status) => {
  const order = custodyOrder(status); expect(readCustodyActivity(order).state).toBe("ready"); expect(detail(order).custody_activity).toEqual(order.custody_activity);
  expect(custodyResolved(order)).toBe(["returned", "kept"].includes(status)); expect(custodyBlocksNormalMutation(order)).toBe(!["waiting", "reviewed"].includes(status));
});
test("marker parity, private data, chronology, forged receipts and unknown money fail closed", () => {
  const o = custodyOrder("returned");
  const cases = [{ custody_activity: null }, { custody_contract_version: true }, { read_custody_invalid: null }, { driver_id: "other" }, { cancelled_at: null }, { cancelled_by: null }, { cancellation_reason: "unrelated" }, { delivered_at: "2026-10-14T08:20:00Z" }, { status: "DELIVERED" }];
  for (const patch of cases) { const bad = { ...o, ...patch }; expect(readCustodyActivity(bad).state).toBe("invalid"); expect(detail(bad).read_actions_unavailable).toBe(true); }
  for (const patch of [{ binding: {} }, { refund_paid_bani: 0 }, { driver_id: "other" }, { review_id: IDS[2] }, { wait_eligible_at: "2026-10-14T08:10:59Z" }, { reviewed_at: "2026-10-14T08:10:59Z" }, { decision: "keep" }, { pricing_status: "paid" }, { incident_id: "a".repeat(999) }, { customer_contact_attempted: false }]) expect(readCustodyActivity({ ...o, custody_activity: { ...o.custody_activity, ...patch } }).state).toBe("invalid");
  const markerless = { ...o }; delete markerless.custody_contract_version; expect(readCustodyActivity(markerless).state).toBe("invalid");
  expect(readCustodyActivity({ custody_contract_version: 1 }).state).toBe("invalid");
});
test.each(["waiting", "reviewed"])("real DELIVERED accepts only coherent historical %s facts", (status) => {
  const o = custodyOrder(status, { status: "DELIVERED", delivered_at: "2026-10-14T08:21:00Z" }); expect(readCustodyActivity(o).state).toBe("ready"); expect(detail(o).custody_activity.status).toBe(status);
  for (const patch of [{ delivered_at: null }, { delivered_at: "2026-10-14T07:59:00Z" }, { cancellation_reason: "wrong" }, { cancelled_by: "actor" }]) expect(readCustodyActivity({ ...o, ...patch }).state).toBe("invalid");
  expect(custodyCommandEligible(o, driver, waitCommand())).toBe(false);
});
test("actor/own target/exact predecessor gates and final decision blocks normal delivered", () => {
  expect(custodyCommandEligible(custodyOrder(), driver, waitCommand())).toBe(true);
  expect(custodyCommandEligible(custodyOrder(), { ...driver, driver_id: "foreign" }, waitCommand())).toBe(false);
  expect(custodyCommandEligible(custodyOrder(), admin, waitCommand())).toBe(false);
  const review = { event_type: "delivery_failure_reviewed", incident_id: IDS[1], predecessor_id: IDS[2], customer_contact_attempted: true, restaurant_contacted: true, coordination_confirmed: true };
  expect(custodyCommandEligible(custodyOrder("waiting"), admin, review)).toBe(true);
  for (const patch of [{ coordination_confirmed: false }, { predecessor_id: IDS[4] }, { incident_id: IDS[5] }, { amount_bani: 0 }]) expect(custodyCommandEligible(custodyOrder("waiting"), admin, { ...review, ...patch })).toBe(false);
  expect(custodyCommandEligible(custodyOrder("reviewed"), restaurant, { event_type: "products_disposition_decided", incident_id: IDS[1], predecessor_id: IDS[3], decision: "return" })).toBe(true);
  expect(custodyCommandEligible(custodyOrder("return_requested"), driver, { event_type: "products_return_received", incident_id: IDS[1], predecessor_id: IDS[4] })).toBe(false);
  expect(canChangeOrderStatus(custodyOrder("waiting"), "DELIVERED", driver)).toBe(true);
  expect(canChangeOrderStatus(custodyOrder("return_requested"), "DELIVERED", driver)).toBe(false);
  expect(canChangeOrderStatus(custodyOrder("keep_authorized"), "DELIVERED", admin)).toBe(false);
});
test("L4A debt survives only verified resolved custody cancellation, snapshot unknown refunds remain unknown", () => {
  const financial = { contract_version: 1, currency: "RON", collection_mode: "cash", products_bani: 6530, client_collection_bani: 6530, restaurant_transport_bani: 1700, courier_remuneration_bani: 900, advance_required_bani: 6530, advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null, tariff_version: "v1", restaurant_id: "restaurant", basis: "zone", snapshot_at: "2026-10-14T07:00:00Z", snapshot_digest: "a".repeat(64) };
  const activity = { contract_version: 1, status: "outstanding", driver_id: "driver", declared_unpaid_bani: 6530, declaration_id: IDS[0], approval_id: IDS[1], declared_at: "2026-10-14T07:30:00Z", approved_at: "2026-10-14T07:40:00Z", picked_up_at: "2026-10-14T08:00:00Z", outstanding_bani: 6530, repayment_due_policy: "next_pickup_else_shift_end" };
  for (const status of ["returned", "kept"]) { const o = custodyOrder(status, { payment_type: "CASH", financial_contract_version: 1, financial, financial_activity_contract_version: 1, financial_activity: activity }); expect(readFinancialActivity(o).state).toBe("ready"); expect(detail(o).financial_activity.outstanding_bani).toBe(6530); expect(detail(o).financial.refund_due_bani).toBeNull();
    expect(readFinancialActivity({ ...o, custody_activity: null }).state).toBe("invalid"); const legacy = { ...o }; delete legacy.custody_contract_version; delete legacy.custody_activity; expect(readFinancialActivity(legacy).state).toBe("invalid"); }
});
