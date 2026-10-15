import { canChangeOrderStatus, createOrderStatusRecovery } from "./orderStatusRecovery";

const ID = "a68c289d-bdb1-4bfb-8c2d-acdcf9981354";
const actors = {
  admin: { id: "admin-user", role: "admin" },
  driver: { id: "driver-user", role: "driver", driver_id: "driver" },
  restaurant: { id: "restaurant-user", role: "restaurant", restaurant_id: "restaurant" },
};
const targets = ["ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"];
const allowed = [["admin", "ACCEPTED"], ["admin", "PICKED_UP"], ["admin", "DELIVERED"], ["admin", "CANCELLED"],
  ["driver", "ACCEPTED"], ["driver", "PICKED_UP"], ["driver", "DELIVERED"], ["restaurant", "CANCELLED"]];
const forbidden = [["driver", "CANCELLED"], ["restaurant", "ACCEPTED"], ["restaurant", "PICKED_UP"], ["restaurant", "DELIVERED"]];
const sourceOrder = (target) => ({ id: "order", restaurant_id: "restaurant", driver_id: "driver", order_version: 7,
  status: target === "ACCEPTED" ? "ASSIGNED" : target === "DELIVERED" ? "PICKED_UP" : "ACCEPTED", preparation_status: "READY" });
const pending = () => ({ status: 202, headers: { "retry-after": "1" },
  data: { client_operation_id: ID, state: "pending", retry_after_seconds: 1 } });
const terminal = (state = "applied") => state === "rejected" ? { status: 409,
  data: { client_operation_id: ID, state, error_code: "STATUS_TRANSITION_INVALID" } } : { status: 200,
  data: { client_operation_id: ID, state, order_id: "order", order_version: 8 } };
const missing = { response: { status: 404, data: { detail: { code: "OPERATION_NOT_FOUND" } } } };
const denied = { response: { status: 403, data: { detail: { code: "NOT_AUTHORIZED" } } } };
const storage = () => {
  const values = new Map();
  return { values, getItem: jest.fn((key) => values.get(key) ?? null),
    setItem: jest.fn((key, value) => values.set(key, value)), removeItem: jest.fn((key) => values.delete(key)) };
};
const make = (role = "driver", target = "CANCELLED", options = {}) => {
  const actor = { ...actors[role] }, durable = storage(), drafts = storage();
  const key = `prodelivery:order-status:v1:${encodeURIComponent(actor.id)}`, draftKey = `${key}:draft:${ID}`;
  const record = { actor_id: actor.id, actor_role: actor.role, actor_resource_id: actor[`${role}_id`] ?? null,
    order_id: "order", expected_order_version: 7, status: target, client_operation_id: ID, receipt: options.receipt ?? null };
  const { receipt, ...metadata } = record;
  const draft = { ...metadata, cancellation_reason: "Exact private cancellation reason" };
  const api = { get: jest.fn(async () => pending()), post: jest.fn(async () => terminal()), put: jest.fn() };
  const crypto = { randomUUID: jest.fn(() => ID) };
  const recovery = createOrderStatusRecovery({ actor, api, durableStorage: durable, draftStorage: drafts,
    crypto, locks: { request: async (_key, _options, callback) => callback({}) }, wait: async () => {},
    ...(options.owner ? { isOwnerActive: options.owner } : {}) });
  const seed = (withDraft = true) => {
    durable.values.set(key, JSON.stringify(record));
    if (target === "CANCELLED" && withDraft) drafts.values.set(draftKey, JSON.stringify(draft));
  };
  return { actor, api, crypto, durable, drafts, key, draftKey, record, draft, seed, recovery };
};
const noMutation = (h) => {
  expect(h.api.post).not.toHaveBeenCalled(); expect(h.api.put).not.toHaveBeenCalled();
  expect(h.crypto.randomUUID).not.toHaveBeenCalled(); expect(h.durable.removeItem).not.toHaveBeenCalled();
};

test.each(Object.keys(actors).flatMap((role) => targets.map((target) => [role, target])))
("fresh policy %s/%s preserves the exact role matrix", async (role, target) => {
  const h = make(role, target), order = sourceOrder(target);
  const permitted = allowed.some(([r, t]) => r === role && t === target);
  expect(canChangeOrderStatus(order, target, h.actor)).toBe(permitted);
  h.api.get.mockResolvedValue({ status: 200, data: { status_recovery_enabled: true } });
  const input = { order, status: target, ...(target === "CANCELLED" ? { cancellationReason: "  reason  " } : {}) };
  if (permitted) {
    await expect(h.recovery.submit(input)).resolves.toEqual(terminal().data);
    expect(h.api.post).toHaveBeenCalledWith("/api/orders/operations/status/order", {
      client_operation_id: ID, expected_order_version: 7, status: target,
      ...(target === "CANCELLED" ? { cancellation_reason: "reason" } : {}),
    }, { timeout: 15000 });
  } else {
    await expect(h.recovery.submit(input)).rejects.toMatchObject({ code: "STATUS_TRANSITION_INVALID" });
    noMutation(h); expect(h.api.get).not.toHaveBeenCalled(); expect(h.durable.values.size).toBe(0);
  }
});

test.each(forbidden)("%s/%s GET404 refuses resend and preserves original bytes", async (role, target) => {
  const h = make(role, target); h.seed(); h.api.get.mockRejectedValue(missing);
  const before = h.durable.getItem(h.key), privateBefore = h.drafts.getItem(h.draftKey);
  await expect(h.recovery.recover()).rejects.toMatchObject({ code: "NOT_AUTHORIZED" });
  noMutation(h); expect(h.api.get).toHaveBeenCalledTimes(1);
  expect(h.durable.getItem(h.key)).toBe(before); expect(h.drafts.getItem(h.draftKey)).toBe(privateBefore);
  expect(h.durable.setItem).not.toHaveBeenCalled(); expect(h.drafts.removeItem).not.toHaveBeenCalled();
});

// These pending replies are adversarial client-boundary fixtures; the actual
// backend rejects pending lookup for role-forbidden targets with403.
test.each(forbidden)("%s/%s GET202 retains valid pending but never resumes", async (role, target) => {
  const h = make(role, target); h.seed(); const privateBefore = h.drafts.getItem(h.draftKey);
  for (let attempt = 0; attempt < 2; attempt++) {
    await expect(h.recovery.recover()).rejects.toMatchObject({ code: "NOT_AUTHORIZED" });
    expect(h.recovery.snapshot()).toEqual({ ...h.record, receipt: pending().data });
    expect(h.drafts.getItem(h.draftKey)).toBe(privateBefore);
  }
  noMutation(h); expect(h.api.get).toHaveBeenCalledTimes(2);
  expect(h.drafts.removeItem).not.toHaveBeenCalled();
  expect(h.durable.getItem(h.key)).not.toContain("Exact private");
});

test.each(["applied", "replayed", "rejected"])("new validated %s terminal cleans retained pending draft and enables ACK", async (state) => {
  const h = make(); h.seed();
  await expect(h.recovery.recover()).rejects.toMatchObject({ code: "NOT_AUTHORIZED" });
  expect(h.drafts.getItem(h.draftKey)).not.toBeNull();
  h.api.get.mockResolvedValue(terminal(state));
  await expect(h.recovery.recover()).resolves.toEqual(terminal(state).data);
  expect(h.recovery.snapshot().receipt).toEqual(terminal(state).data);
  expect(h.drafts.getItem(h.draftKey)).toBeNull(); noMutation(h);
  await h.recovery.acknowledge(); expect(h.durable.getItem(h.key)).toBeNull();
  expect(h.api.get).toHaveBeenCalledTimes(2); expect(h.api.post).not.toHaveBeenCalled();
});

test.each([null, pending().data])("missing cancel draft or admitted GET404 remains uncertain: receipt=%p", async (receipt) => {
  const h = make("driver", "CANCELLED", { receipt }); h.seed(false); h.api.get.mockRejectedValue(missing);
  await expect(h.recovery.recover()).rejects.toMatchObject({ code: "OPERATION_UNCERTAIN" });
  noMutation(h); expect(h.recovery.snapshot()).toEqual(h.record);
});

test("previously stored forbidden pending survives403 and ACK cannot clear it", async () => {
  const h = make("driver", "CANCELLED", { receipt: pending().data }); h.seed();
  const privateBefore = h.drafts.getItem(h.draftKey); h.api.get.mockRejectedValue(denied);
  expect(h.recovery.snapshot()).toEqual(h.record);
  await expect(h.recovery.recover()).rejects.toMatchObject({ code: "NOT_AUTHORIZED" });
  await expect(h.recovery.acknowledge()).rejects.toMatchObject({ code: "OPERATION_UNCERTAIN" });
  expect(h.drafts.getItem(h.draftKey)).toBe(privateBefore); noMutation(h);
});

test.each([{ cancellation_reason: " " }, { expected_order_version: 6 }])("invalid cancellation draft retains storage failure precedence: %p", async (patch) => {
  const h = make(); h.seed(); h.drafts.values.set(h.draftKey, JSON.stringify({ ...h.draft, ...patch }));
  const before = h.drafts.getItem(h.draftKey); h.api.get.mockRejectedValue(missing);
  await expect(h.recovery.recover()).rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" });
  noMutation(h); expect(h.drafts.getItem(h.draftKey)).toBe(before); expect(h.recovery.storageBlocked()).toBe(true);
});

test.each([
  ["pending header", () => ({ ...pending(), headers: { "retry-after": "2" } })],
  ["operation id", () => ({ ...terminal(), data: { ...terminal().data, client_operation_id: "wrong_operation_id" } })],
  ["order version", () => ({ ...terminal(), data: { ...terminal().data, order_version: 7 } })],
  ["order id", () => ({ ...terminal(), data: { ...terminal().data, order_id: "another-order" } })],
])("invalid %s GET cannot persist or discard private draft", async (_name, response) => {
  const h = make(); h.seed(); const before = h.durable.getItem(h.key), privateBefore = h.drafts.getItem(h.draftKey);
  h.api.get.mockResolvedValue(response());
  await expect(h.recovery.recover()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  noMutation(h); expect(h.durable.getItem(h.key)).toBe(before); expect(h.drafts.getItem(h.draftKey)).toBe(privateBefore);
});

test("failed pending persistence retains draft and prevents resume", async () => {
  const h = make(); h.seed(); const before = h.durable.getItem(h.key), privateBefore = h.drafts.getItem(h.draftKey);
  h.durable.setItem.mockImplementation(() => { throw Error("blocked synthetic storage"); });
  await expect(h.recovery.recover()).rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" });
  noMutation(h); expect(h.durable.getItem(h.key)).toBe(before); expect(h.drafts.getItem(h.draftKey)).toBe(privateBefore);
});

test.each(["admin", "restaurant"])("allowed %s cancellation still rolls back draft when metadata write fails", async (role) => {
  const h = make(role); h.api.get.mockResolvedValue({ status: 200, data: { status_recovery_enabled: true } });
  h.durable.setItem.mockImplementation(() => { throw Error("blocked synthetic storage"); });
  await expect(h.recovery.submit({ order: sourceOrder("CANCELLED"), status: "CANCELLED", cancellationReason: "reason" }))
    .rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" });
  expect(h.api.post).not.toHaveBeenCalled(); expect(h.drafts.getItem(h.draftKey)).toBeNull();
  expect(h.durable.getItem(h.key)).toBeNull(); expect(h.recovery.storageBlocked()).toBe(true);
});

test.each([false, true])("deactivate preserveDraft=%s keeps the existing session cleanup boundary", async (preserveDraft) => {
  const h = make(); h.seed(); await expect(h.recovery.recover()).rejects.toMatchObject({ code: "NOT_AUTHORIZED" });
  const before = h.durable.getItem(h.key), privateBefore = h.drafts.getItem(h.draftKey);
  if (preserveDraft) h.recovery.deactivate({ preserveDraft: true }); else h.recovery.deactivate();
  expect(h.drafts.getItem(h.draftKey)).toBe(preserveDraft ? privateBefore : null);
  expect(h.durable.getItem(h.key)).toBe(before); noMutation(h);
});

test.each(allowed)("allowed %s/%s recovery404 preserves exact retry wire", async (role, target) => {
  const h = make(role, target); h.seed(); h.api.get.mockRejectedValue(missing);
  await expect(h.recovery.recover()).resolves.toEqual(terminal().data);
  expect(h.api.post).toHaveBeenCalledTimes(1);
  expect(h.api.post).toHaveBeenCalledWith("/api/orders/operations/status/order", {
    client_operation_id: ID, expected_order_version: 7, status: target,
    ...(target === "CANCELLED" ? { cancellation_reason: h.draft.cancellation_reason } : {}),
  }, { timeout: 15000 });
  expect(h.crypto.randomUUID).not.toHaveBeenCalled(); expect(h.drafts.getItem(h.draftKey)).toBeNull();
});

test.each(allowed)("allowed %s/%s pending resumes bodyless with no local draft", async (role, target) => {
  const h = make(role, target, { receipt: pending().data }); h.seed(false);
  await expect(h.recovery.recover()).resolves.toEqual(terminal().data);
  expect(h.api.post).toHaveBeenCalledTimes(1);
  expect(h.api.post).toHaveBeenCalledWith(`/api/orders/operations/status/order/${ID}/resume`, undefined, { timeout: 15000 });
  expect(h.crypto.randomUUID).not.toHaveBeenCalled(); expect(h.api.get).toHaveBeenCalledTimes(1);
});

test("owner changed during GET prevents every late save and resume", async () => {
  let active = true, resolveResponse, resolveStarted;
  const started = new Promise((resolve) => { resolveStarted = resolve; });
  const response = new Promise((resolve) => { resolveResponse = resolve; });
  const h = make("restaurant", "CANCELLED", { owner: () => active }); h.seed();
  const before = h.durable.getItem(h.key), privateBefore = h.drafts.getItem(h.draftKey);
  h.api.get.mockImplementation(() => { resolveStarted(); return response; });
  const job = h.recovery.recover(); await started; active = false; resolveResponse(pending());
  await expect(job).rejects.toMatchObject({ code: "SESSION_CHANGED" });
  noMutation(h); expect(h.durable.getItem(h.key)).toBe(before); expect(h.drafts.getItem(h.draftKey)).toBe(privateBefore);
});

test("target helper does not weaken actor, ownership, version or lifecycle checks", () => {
  for (const patch of [{ account_disabled: true }, { is_disabled: null }, { id: "" }, { driver_id: "foreign" }]) {
    expect(canChangeOrderStatus(sourceOrder("ACCEPTED"), "ACCEPTED", { ...actors.driver, ...patch })).toBe(false);
  }
  expect(canChangeOrderStatus({ ...sourceOrder("CANCELLED"), restaurant_id: "foreign" }, "CANCELLED", actors.restaurant)).toBe(false);
  expect(canChangeOrderStatus({ ...sourceOrder("ACCEPTED"), order_version: null }, "ACCEPTED", actors.driver)).toBe(false);
  expect(canChangeOrderStatus({ ...sourceOrder("CANCELLED"), status: "PICKED_UP" }, "CANCELLED", actors.admin)).toBe(false);
  expect(canChangeOrderStatus(sourceOrder("ACCEPTED"), "NEW", actors.admin)).toBe(false);
});
