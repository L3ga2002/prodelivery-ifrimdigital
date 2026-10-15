import { parseOrderDetail } from "./orderReads";
import { IDS } from "./orderCustody.fixtures";

const order = { id: "order", restaurant_id: "restaurant", status: "NEW", order_version: 4, preparation_status: "NEW", created_at: "2026-10-14T08:00:00Z" };
const history = (changes, action = "order.delivery_wait_started") => ({ id: IDS[2], action, performed_by: "actor", performed_by_role: "driver", created_at: order.created_at, from_order_version: 3, to_order_version: 4, changes });
const parse = (entries) => parseOrderDetail({ order, history: entries, next_history_before: null, history_has_more: false, data_warnings: [] }, order.id);
const custodyChanges = (status, decision) => ({ custody_status: status, incident_id: IDS[1], custody_event_id: IDS[2], decision });
const financialChanges = (status) => ({ declared_unpaid_bani: 5250, declaration_id: IDS[2], approval_id: status === "declared" ? null : IDS[3], financial_activity_status: status,
  ...(status === "outstanding" ? { repayment_due_policy: "next_pickup_else_shift_end", from_status: "ACCEPTED", to_status: "PICKED_UP" } : {}) });

// Exact synthetic public rows produced by backend safe_history during browser QA.
// Provenance: campaign review/history-public-rows.json (server_warnings: []).
const publicBrowserHistory = [
  {
    "index": 0,
    "id": "b084c68e-03d3-5fb7-ad7a-5f01c7787e1f",
    "action": "order.created",
    "performed_by": "s12-restaurant1",
    "performed_by_role": "restaurant",
    "created_at": "2026-10-13T22:21:59.247Z",
    "from_order_version": null,
    "to_order_version": 0,
    "changes": {
      "financial_snapshot_digest": "de112669e2114b2f7a42c3375f1e1d7eb5357a413acad59049d11442d700eb31"
    }
  },
  {
    "index": 1,
    "id": "7d7f1ee2-19b0-5e53-91bc-c9da7e3c17af",
    "action": "order.preparing_started",
    "performed_by": "s12-restaurant1",
    "performed_by_role": "restaurant",
    "created_at": "2026-10-13T22:21:59.300Z",
    "from_order_version": 0,
    "to_order_version": 1,
    "changes": {
      "from_preparation_status": "NEW",
      "from_status": "NEW",
      "preparation_due_at": "2026-10-13T22:41:59.300699+00:00",
      "preparation_time": 20,
      "to_preparation_status": "PREPARING",
      "to_status": "PREPARING"
    }
  },
  {
    "index": 2,
    "id": "c0af3e6f-4527-58d1-bb2f-6ccdc8f3aa22",
    "action": "order.ready",
    "performed_by": "s12-restaurant1",
    "performed_by_role": "restaurant",
    "created_at": "2026-10-13T22:21:59.340Z",
    "from_order_version": 1,
    "to_order_version": 2,
    "changes": {
      "from_preparation_status": "PREPARING",
      "from_status": "PREPARING",
      "preparation_actual_seconds": 0,
      "preparation_delay_seconds": 0,
      "to_preparation_status": "READY",
      "to_status": "READY"
    }
  },
  {
    "index": 3,
    "id": "1f1724aa-aa27-50fd-93bc-ce85525615b1",
    "action": "order.assigned",
    "performed_by": "s12-admin1",
    "performed_by_role": "admin",
    "created_at": "2026-10-13T22:21:59.403Z",
    "from_order_version": 2,
    "to_order_version": 3,
    "changes": {
      "from_status": "READY",
      "new_driver_id": "s12-d1",
      "old_driver_id": null,
      "to_status": "ASSIGNED"
    }
  },
  {
    "index": 4,
    "id": "f1cd408b-c14c-5721-817a-8069add43fd7",
    "action": "order.status_changed",
    "performed_by": "s12-driver1",
    "performed_by_role": "driver",
    "created_at": "2026-10-13T22:21:59.460Z",
    "from_order_version": 3,
    "to_order_version": 4,
    "changes": {
      "financial_snapshot_digest": "de112669e2114b2f7a42c3375f1e1d7eb5357a413acad59049d11442d700eb31",
      "from_status": "ASSIGNED",
      "to_status": "ACCEPTED"
    }
  },
  {
    "index": 5,
    "id": "e1f8e274-a976-57b1-8a30-e828dd37d79a",
    "action": "order.advance_not_paid_declared",
    "performed_by": "s12-driver1",
    "performed_by_role": "driver",
    "created_at": "2026-10-13T22:21:59.537Z",
    "from_order_version": 4,
    "to_order_version": 5,
    "changes": {
      "approval_id": null,
      "declaration_id": "7fff2d0a-2310-5ef2-9582-5ecbe5689c81",
      "declared_unpaid_bani": 5250,
      "financial_activity_status": "declared"
    }
  },
  {
    "index": 6,
    "id": "8f83bd59-293a-59b2-84e5-439e950c8b33",
    "action": "order.advance_shortfall_acknowledged",
    "performed_by": "s12-restaurant1",
    "performed_by_role": "restaurant",
    "created_at": "2026-10-13T22:21:59.625Z",
    "from_order_version": 5,
    "to_order_version": 6,
    "changes": {
      "approval_id": "2ed83d0e-7ecd-5632-ae7d-b61813a9e9ac",
      "declaration_id": "7fff2d0a-2310-5ef2-9582-5ecbe5689c81",
      "declared_unpaid_bani": 5250,
      "financial_activity_status": "approved"
    }
  },
  {
    "index": 7,
    "id": "f0ae3549-5f87-51e2-914d-517772403fa3",
    "action": "order.status_changed",
    "performed_by": "s12-driver1",
    "performed_by_role": "driver",
    "created_at": "2026-10-13T22:21:59.701Z",
    "from_order_version": 6,
    "to_order_version": 7,
    "changes": {
      "approval_id": "2ed83d0e-7ecd-5632-ae7d-b61813a9e9ac",
      "declaration_id": "7fff2d0a-2310-5ef2-9582-5ecbe5689c81",
      "declared_unpaid_bani": 5250,
      "financial_activity_status": "outstanding",
      "financial_snapshot_digest": "de112669e2114b2f7a42c3375f1e1d7eb5357a413acad59049d11442d700eb31",
      "from_status": "ACCEPTED",
      "repayment_due_policy": "next_pickup_else_shift_end",
      "to_status": "PICKED_UP"
    }
  },
  {
    "index": 8,
    "id": "25af90b9-938e-5ded-9180-2187a915bf59",
    "action": "order.incident_reported",
    "performed_by": "s12-driver1",
    "performed_by_role": "driver",
    "created_at": "2026-10-13T22:26:58.303Z",
    "from_order_version": 7,
    "to_order_version": 8,
    "changes": {
      "incident_id": "7dd79801-7285-5d72-9932-6eeb52935f08"
    }
  },
  {
    "index": 9,
    "id": "bc90f669-9679-54f5-bf04-e5986987b890",
    "action": "order.delivery_wait_started",
    "performed_by": "s12-driver1",
    "performed_by_role": "driver",
    "created_at": "2026-10-13T22:29:12.388Z",
    "from_order_version": 8,
    "to_order_version": 9,
    "changes": {
      "custody_event_id": "bd7a4e77-ec2a-5bf4-8278-bf708ddebaa8",
      "custody_status": "waiting",
      "decision": null,
      "incident_id": "7dd79801-7285-5d72-9932-6eeb52935f08"
    }
  },
  {
    "index": 10,
    "id": "9b359084-5d72-5cd4-884f-f742cc86f780",
    "action": "order.delivery_failure_reviewed",
    "performed_by": "s12-admin1",
    "performed_by_role": "admin",
    "created_at": "2026-10-13T22:47:44.060Z",
    "from_order_version": 9,
    "to_order_version": 10,
    "changes": {
      "custody_event_id": "d05256c7-44c7-5021-a603-b9004b08a1bf",
      "custody_status": "reviewed",
      "decision": null,
      "incident_id": "7dd79801-7285-5d72-9932-6eeb52935f08"
    }
  }
];

test("the actual synthetic public history keeps all eleven rows without inventing history warnings", () => {
  const parsed = parse(publicBrowserHistory);
  expect(parsed.history).toHaveLength(11);
  expect(parsed.history.map(row => row.changes)).toEqual(publicBrowserHistory.map(row => row.changes));
  expect(parsed.data_warnings).toEqual([]);
});

test.each([
  ["waiting", null, "delivery_wait_started"], ["reviewed", null, "delivery_failure_reviewed"],
  ["return_requested", "return", "products_disposition_decided"], ["keep_authorized", "keep", "products_disposition_decided"],
  ["returned", "return", "products_return_received"], ["kept", "keep", "products_keep_acknowledged"],
])("public %s history keeps UUID event, incident and exact nullable decision", (status, decision, event) => {
  const changes = custodyChanges(status, decision), parsed = parse([history(changes, `order.${event}`)]);
  expect(parsed.history[0].changes).toEqual(changes);expect(parsed.history[0].action).toBe(`order.${event}`);expect(parsed.data_warnings).toEqual([]);
});

test.each(["declared", "approved", "outstanding"])("public L4A %s history preserves debt facts without payment/refund inference", status => {
  const changes = financialChanges(status), parsed = parse([history(changes, status === "outstanding" ? "order.status_changed" : `order.advance_${status}`)]);
  expect(parsed.history[0].changes).toEqual(changes);expect(parsed.data_warnings).toEqual([]);
  expect(parsed.history[0].changes).not.toHaveProperty("refund_paid_bani");expect(parsed.history[0].changes).not.toHaveProperty("paid_bani");
});

test("generic incident history still accepts the canonical incident UUID without custody state", () => {
  const parsed = parse([history({ incident_id: IDS[1] }, "order.incident_reported")]);
  expect(parsed.history[0].changes).toEqual({ incident_id: IDS[1] });expect(parsed.data_warnings).toEqual([]);
});

test.each([
  ["custody_event_id", IDS[2].toUpperCase()], ["custody_event_id", "a".repeat(36)], ["custody_event_id", IDS[0]],
  ["custody_event_id", IDS[2].slice(0,19) + "7" + IDS[2].slice(20)], ["custody_event_id", null], ["custody_event_id", {}],
  ["incident_id", "-".repeat(36)], ["incident_id", IDS[1] + " "], ["incident_id", true],
  ["declaration_id", IDS[2].replaceAll("-", "")], ["declaration_id", IDS[2].toUpperCase()], ["declaration_id", null],
])("malformed public UUID %s=%j is omitted with an explicit warning", (key, value) => {
  const parsed = parse([history({ ...custodyChanges("waiting", null), [key]: value })]);
  expect(parsed.history[0].changes).not.toHaveProperty(key);expect(parsed.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
});

test.each([
  ["waiting", "return"], ["reviewed", "keep"], ["return_requested", null], ["return_requested", "keep"],
  ["returned", "keep"], ["keep_authorized", "return"], ["kept", null], ["pending", null], ["__proto__", null],
])("custody history rejects inconsistent state/decision %s/%j", (status, decision) => {
  const parsed = parse([history(custodyChanges(status, decision))]);
  expect(parsed.history[0].changes).not.toHaveProperty("decision");expect(parsed.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
  if (["pending", "__proto__"].includes(status)) expect(parsed.history[0].changes).not.toHaveProperty("custody_status");
});

test("custody and financial enums cannot be borrowed from another public field", () => {
  const parsed = parse([history({ custody_status: "return", decision: "pending", financial_activity_status: "kept", repayment_due_policy: "approved" })]);
  expect(parsed.history[0].changes).toEqual({});expect(parsed.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
});

test.each([
  ["declared", IDS[3]], ["approved", null], ["outstanding", null], ["approved", "-".repeat(36)],
  ["declared", false], ["approved", {}], [undefined, null],
])("approval nullability and UUID follow financial history state %s", (status, approval) => {
  const parsed = parse([history({ financial_activity_status: status, approval_id: approval })]);
  expect(parsed.history[0].changes).not.toHaveProperty("approval_id");expect(parsed.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
});

test.each([0, -1, 1.5, 100000001, "5250", true, null])("invalid declaration amount %j is not rendered as financial proof", value => {
  const parsed = parse([history({ ...financialChanges("declared"), declared_unpaid_bani: value })]);
  expect(parsed.history[0].changes).not.toHaveProperty("declared_unpaid_bani");expect(parsed.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
});

test.each([1, 100000000])("declaration amount bound %s remains exact", value => {
  const parsed = parse([history({ ...financialChanges("declared"), declared_unpaid_bani: value })]);
  expect(parsed.history[0].changes.declared_unpaid_bani).toBe(value);expect(parsed.data_warnings).toEqual([]);
});

test.each([["declared", "next_pickup_else_shift_end"], ["approved", null], ["outstanding", null], ["outstanding", "immediate"], ["outstanding", {}]])("repayment policy rejects unconfirmed state/value %s/%j", (status, policy) => {
  const parsed = parse([history({ financial_activity_status: status, repayment_due_policy: policy })]);
  expect(parsed.history[0].changes).not.toHaveProperty("repayment_due_policy");expect(parsed.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
});

test("private and non-public ledger fields remain omitted while valid custody facts survive", () => {
  const changes = custodyChanges("kept", "keep");
  const forbidden = { operation_ref: "private", request_id: "private", binding: {}, custody_snapshot: {}, command: {},
    wait_event_id: IDS[2], review_id: IDS[3], decision_id: IDS[4], resolution_id: IDS[5], custody_resolution: "kept",
    reason: "absent", pricing_status: "pending", amount_bani: 5250, outstanding_bani: 5250, refund_paid_bani: 0, credentials: "private" };
  const parsed = parse([history({ ...changes, ...forbidden })]);
  expect(parsed.history[0].changes).toEqual(changes);expect(parsed.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
  for (const key of Object.keys(forbidden)) expect(parsed.history[0].changes).not.toHaveProperty(key);
});
