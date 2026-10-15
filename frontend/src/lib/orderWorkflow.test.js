import { describe, test, expect } from "@jest/globals";
import {
  getPreparationStatus,
  isActionableDriverOrder,
  isActiveOrder,
  isNewRestaurantOrder,
  isShortPreparationBlocked,
  splitRestaurantOrders,
} from "./orderWorkflow.js";

const order = (status, fields = {}) => ({ id: "order-1", status, ...fields });
const started = "2026-10-02T10:00:00Z";
const ready = "2026-10-02T10:15:00Z";

describe("active and actionable orders", () => {
  test("cancelled-first and malformed records cannot hide a valid assignment", () => {
    const assignment = order("ASSIGNED", { id: "assignment" });
    const orders = [order("CANCELLED"), null, {}, order("UNKNOWN"), order("DELIVERED"), assignment];
    expect(orders.find(isActionableDriverOrder)).toBe(assignment);
    expect(orders.filter(isActiveOrder)).toEqual([assignment]);
    expect(orders).toHaveLength(6);
  });

  test.each(["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP"])(
    "%s is active for admin", (status) => expect(isActiveOrder(order(status))).toBe(true)
  );
  test.each(["ASSIGNED", "ACCEPTED", "PICKED_UP"])(
    "%s is actionable for the driver", (status) => expect(isActionableDriverOrder(order(status))).toBe(true)
  );
  test.each(["NEW", "PREPARING", "READY", "CANCELLED", "DELIVERED"])(
    "%s is not actionable driver work", (status) => expect(isActionableDriverOrder(order(status))).toBe(false)
  );
  test.each([undefined, null, {}, [], "ASSIGNED", { status: "ASSIGNED" }, order("ASSIGNED", { id: " " }), order("ASSIGNED", { id: 1 })])(
    "rejects malformed record %p", (record) => {
      expect(isActiveOrder(record)).toBe(false);
      expect(isActionableDriverOrder(record)).toBe(false);
      expect(getPreparationStatus(record)).toBeNull();
    }
  );
  test.each([undefined, null, "", "assigned", "ASSIGNED ", "UNKNOWN", {}, ["ASSIGNED"], 1])(
    "rejects malformed status %p", (status) => {
      expect(isActiveOrder(order(status))).toBe(false);
      expect(isActionableDriverOrder(order(status))).toBe(false);
      expect(getPreparationStatus(order(status, { preparation_status: "READY" }))).toBeNull();
    }
  );
});

describe("preparation compatibility", () => {
  test.each(["NEW", "PREPARING", "READY"])("legacy public %s wins over timestamps", (status) => {
    expect(getPreparationStatus(order(status, { preparation_started_at: started, preparation_ready_at: ready }))).toBe(status);
    ["NEW", "PREPARING", "READY", null].forEach((preparation_status) => {
      expect(getPreparationStatus(order(status, { preparation_status, preparation_ready_at: ready }))).toBe(status);
    });
  });
  test.each(["NEW", "PREPARING", "READY"])("public %s fails closed for invalid explicit preparation state", (status) => {
    ["BROKEN", "INVALID", "", "ready", {}, [], false, 0].forEach((preparation_status) => {
      const record = order(status, { preparation_status, preparation_started_at: started, preparation_ready_at: ready });
      expect(getPreparationStatus(record)).toBeNull();
      expect(isNewRestaurantOrder(record)).toBe(false);
      expect(splitRestaurantOrders([record]).newOrders).toEqual([]);
      expect(record.status).toBe(status);
    });
  });
  test.each(["ASSIGNED", "ACCEPTED"])(
    "additive preparation states are authoritative with public %s", (status) => {
      ["NEW", "PREPARING", "READY"].forEach((preparation_status) => {
        const record = order(status, { preparation_status, preparation_started_at: started, preparation_ready_at: ready });
        expect(getPreparationStatus(record)).toBe(preparation_status);
        expect(record.status).toBe(status);
      });
    }
  );
  test.each(["ASSIGNED", "ACCEPTED"])("legacy dispatch %s uses timestamps or NEW", (status) => {
    expect(getPreparationStatus(order(status))).toBe("NEW");
    expect(getPreparationStatus(order(status, { preparation_status: null }))).toBe("NEW");
    expect(getPreparationStatus(order(status, { preparation_started_at: started }))).toBe("PREPARING");
    expect(getPreparationStatus(order(status, { preparation_ready_at: ready }))).toBe("READY");
    expect(getPreparationStatus(order(status, { preparation_started_at: started, preparation_ready_at: ready }))).toBe("READY");
    expect(getPreparationStatus(order(status, { preparation_started_at: "invalid", preparation_ready_at: {} }))).toBeNull();
  });
  test.each(["PICKED_UP", "DELIVERED", "CANCELLED"])("%s cannot expose preparation actions", (status) => {
    expect(getPreparationStatus(order(status, { preparation_status: "READY", preparation_ready_at: ready }))).toBeNull();
    expect(isNewRestaurantOrder(order(status, { preparation_status: "NEW" }))).toBe(false);
  });
  test.each(["", "ready", "INVALID", {}, [], false])("malformed additive state %p fails closed", (preparation_status) => {
    expect(getPreparationStatus(order("ACCEPTED", { preparation_status, preparation_ready_at: ready }))).toBeNull();
  });
  test("expired estimate alone is never actual readiness", () => {
    expect(getPreparationStatus(order("ACCEPTED", { preparation_due_at: started }))).toBe("NEW");
    expect(getPreparationStatus(order("ACCEPTED", { preparation_started_at: started, preparation_due_at: ready }))).toBe("PREPARING");
  });
});

describe("strict legacy preparation timestamps (paired API/UI fixtures)", () => {
  const validTimestamps = [
    "2026-10-02T10:00:00Z", "2026-10-02 10:00:00", "2026-10-02T10:00:00",
    "2026-10-02T10:00:00.1Z", "2026-10-02 10:00:00.123456+00:00",
    "2026-10-02T10:00:00+03:00", "2026-10-02T10:00:00.123-04:30",
    "2024-02-29T23:59:59Z", "2000-02-29T00:00:00Z", "0001-01-01T00:00:00Z",
    // Native Mongo datetime is serialized by the API as an ISO string.
    "2026-10-02T10:00:00.123456+00:00",
  ];
  const invalidTimestamps = [
    "not-a-date", "", " ", "\t", 0, 123, false, {}, { bad: "timestamp" }, [], new Date(started),
    "2026-02-30T10:00:00Z", "2026-02-29T10:00:00Z", "1900-02-29T10:00:00Z",
    "2026-04-31T10:00:00Z", "0000-01-01T10:00:00Z", "2026-00-02T10:00:00Z",
    "2026-13-02T10:00:00Z", "2026-10-00T10:00:00Z", "2026-10-32T10:00:00Z",
    "2026-10-02T24:00:00Z", "2026-10-02T10:60:00Z", "2026-10-02T10:00:60Z",
    "2026-10-02", "2026-10-02T10:00Z", "2026-10-02T10:00:00.Z",
    "2026-10-02T10:00:00.1234567Z", "2026-10-02t10:00:00z", "2026-10-02T10:00:00+0300",
    "2026-10-02T10:00:00+24:00", "2026-10-02T10:00:00+03:60",
    "2026-10-02T10:00:00Z\n", " 2026-10-02T10:00:00Z", "2026-10-02T10:00:00Z ",
  ];

  test.each(["ASSIGNED", "ACCEPTED"])("legacy %s accepts strict ISO strings for either field", (status) => {
    [undefined, null].forEach((preparation_status) => {
      validTimestamps.forEach((timestamp) => {
        expect(getPreparationStatus(order(status, { preparation_status, preparation_started_at: timestamp }))).toBe("PREPARING");
        expect(getPreparationStatus(order(status, { preparation_status, preparation_ready_at: timestamp }))).toBe("READY");
        expect(getPreparationStatus(order(status, { preparation_status, preparation_started_at: timestamp, preparation_ready_at: ready }))).toBe("READY");
      });
    });
  });
  test.each(["ASSIGNED", "ACCEPTED"])("legacy %s rejects either malformed field even when the other is valid", (status) => {
    [undefined, null].forEach((preparation_status) => {
      invalidTimestamps.forEach((timestamp) => {
        [
          { preparation_started_at: timestamp }, { preparation_ready_at: timestamp },
          { preparation_started_at: timestamp, preparation_ready_at: ready },
          { preparation_started_at: started, preparation_ready_at: timestamp },
        ].forEach((fields) => {
          const record = order(status, { preparation_status, ...fields });
          expect(getPreparationStatus(record)).toBeNull();
          expect(isNewRestaurantOrder(record)).toBe(false);
          expect(splitRestaurantOrders([record]).newOrders).toEqual([]);
          expect(getPreparationStatus(record) === "READY").toBe(false);
        });
      });
    });
  });
  test.each(["ASSIGNED", "ACCEPTED"])("legacy %s missing/null timestamp combinations remain NEW", (status) => {
    [undefined, null].forEach((preparation_status) => {
      [undefined, null].forEach((preparation_started_at) => {
        [undefined, null].forEach((preparation_ready_at) => {
          expect(getPreparationStatus(order(status, { preparation_status, preparation_started_at, preparation_ready_at }))).toBe("NEW");
        });
      });
      expect(getPreparationStatus(order(status, { preparation_status, preparation_started_at: started, preparation_ready_at: null }))).toBe("PREPARING");
      expect(getPreparationStatus(order(status, { preparation_status, preparation_started_at: null, preparation_ready_at: ready }))).toBe("READY");
    });
  });
  test.each(["ASSIGNED", "ACCEPTED"])("valid explicit %s preparation ignores malformed legacy timestamps", (status) => {
    ["NEW", "PREPARING", "READY"].forEach((preparation_status) => {
      invalidTimestamps.forEach((timestamp) => {
        expect(getPreparationStatus(order(status, { preparation_status, preparation_started_at: timestamp, preparation_ready_at: timestamp }))).toBe(preparation_status);
      });
    });
  });
  test.each(["NEW", "PREPARING", "READY"])("public %s precedence ignores malformed legacy timestamps after enum validation", (status) => {
    [undefined, null, "NEW", "PREPARING", "READY"].forEach((preparation_status) => {
      invalidTimestamps.forEach((timestamp) => {
        expect(getPreparationStatus(order(status, { preparation_status, preparation_started_at: timestamp, preparation_ready_at: timestamp }))).toBe(status);
      });
    });
  });
});

describe("restaurant grouping and short preparation", () => {
  test("early assignments join new notifications/counts without changing inWork or history semantics", () => {
    const records = [
      order("NEW", { id: "new" }), order("ASSIGNED", { id: "assigned" }),
      order("ACCEPTED", { id: "accepted", preparation_status: "NEW" }),
      order("PREPARING", { id: "preparing" }),
      order("ASSIGNED", { id: "assigned-preparing", preparation_started_at: started }),
      order("READY", { id: "ready" }),
      order("ACCEPTED", { id: "accepted-ready", preparation_status: "READY" }),
      order("PICKED_UP", { id: "picked" }), order("DELIVERED", { id: "delivered" }),
      order("CANCELLED", { id: "cancelled" }), null, order("INVALID"),
    ];
    const snapshot = JSON.stringify(records);
    const groups = splitRestaurantOrders(records);
    expect(groups.newOrders.map(({ id }) => id)).toEqual(["new", "assigned", "accepted"]);
    expect(records.filter(isNewRestaurantOrder)).toEqual(groups.newOrders);
    expect(groups.inWork.map(({ id }) => id)).toEqual(["assigned", "accepted", "preparing", "assigned-preparing", "ready", "accepted-ready", "picked"]);
    expect(groups.active.map(({ id }) => id)).toEqual(["new", "assigned", "accepted", "preparing", "assigned-preparing", "ready", "accepted-ready"]);
    expect(groups.delivered.map(({ id }) => id)).toEqual(["delivered"]);
    expect(records.filter((record) => getPreparationStatus(record) === "READY").map(({ id }) => id)).toEqual(["ready", "accepted-ready"]);
    expect(JSON.stringify(records)).toBe(snapshot);
  });

  const blocked = { available_drivers: 0, blocked_short_options: true, minimum_preparation_minutes: 15 };
  test.each(["ASSIGNED", "ACCEPTED"])("%s with an assignment can offer short prep even with zero free drivers", (status) => {
    expect(isShortPreparationBlocked(order(status, { driver_id: "driver-1" }), 5, blocked)).toBe(false);
    [undefined, null, "", " ", 1, {}].forEach((driver_id) => {
      expect(isShortPreparationBlocked(order(status, { driver_id }), 5, blocked)).toBe(true);
    });
  });
  test.each(["NEW", "PREPARING", "READY", "PICKED_UP", "DELIVERED", "CANCELLED", "INVALID"])(
    "%s cannot bypass blocked short prep just by having driver_id", (status) => {
      expect(isShortPreparationBlocked(order(status, { driver_id: "driver-1" }), 5, blocked)).toBe(true);
    }
  );
  test("normal minimum and free-driver options are preserved", () => {
    expect(isShortPreparationBlocked(order("NEW"), 15, blocked)).toBe(false);
    expect(isShortPreparationBlocked(order("NEW"), 5, { ...blocked, blocked_short_options: false })).toBe(false);
  });
});
