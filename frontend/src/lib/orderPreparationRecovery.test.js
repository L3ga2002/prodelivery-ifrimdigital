import { createOrderPreparationRecovery, validatePreparationReceipt, preparationRejectionStatus } from "./orderPreparationRecovery";

const ID = "c19da70e-b79e-4345-a22c-161064899315";
const actor = { id: "synthetic-user", role: "restaurant", restaurant_id: "synthetic-restaurant" };
const start = "2026-10-11T08:00:00+00:00", due = "2026-10-11T08:15:00+00:00";
const intent = { version: 1, actor_id: actor.id, role: actor.role, restaurant_id: actor.restaurant_id,
  order_id: "synthetic-order", action: "preparing", client_operation_id: ID, expected_order_version: 3, preparation_time: 15, receipt: null };
const order = { id: intent.order_id, restaurant_id: actor.restaurant_id, status: "NEW", order_version: 3 };
const response = (state = "applied", changes = {}) => ({ status: state === "pending" ? 202 : state === "rejected" ? 409 : 200,
  headers: state === "pending" ? { "retry-after": "2" } : {}, data: { client_operation_id: ID, state,
    order_id: ["applied", "replayed"].includes(state) ? order.id : null,
    order_version: ["applied", "replayed"].includes(state) ? 4 : null,
    preparation_status: ["applied", "replayed"].includes(state) ? "PREPARING" : null,
    preparation_time: ["applied", "replayed"].includes(state) ? 15 : null,
    preparation_started_at: ["applied", "replayed"].includes(state) ? start : null,
    preparation_due_at: ["applied", "replayed"].includes(state) ? due : null,
    preparation_ready_at: null, preparation_estimated_seconds: ["applied", "replayed"].includes(state) ? 900 : null,
    preparation_actual_seconds: null, preparation_delay_seconds: null,
    error_code: state === "rejected" ? "ORDER_VERSION_CONFLICT" : null,
    retry_after_seconds: state === "pending" ? 2 : null, ...changes } });
const missing = () => Object.assign(new Error("Not admitted"), { response: { status: 404, data: { detail: { code: "OPERATION_NOT_FOUND" } } } });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const key = `prodelivery:order-preparation:v1:${actor.id}:restaurant:${actor.restaurant_id}`;
const makeStorage = () => {
  const values = new Map();
  return { getItem: jest.fn((k) => values.get(k) ?? null), setItem: jest.fn((k, v) => values.set(k, String(v))), removeItem: jest.fn((k) => values.delete(k)) };
};
const makeLocks = () => {
  const held = new Set();
  return { request: jest.fn(async (name, options, callback) => {
    expect(options).toEqual({ ifAvailable: true });
    if (held.has(name)) return callback(null);
    held.add(name); try { return await callback({ name }); } finally { held.delete(name); }
  }) };
};
const fixture = (changes = {}) => {
  const storage = changes.storage || makeStorage(), locks = changes.locks || makeLocks();
  const api = { get: jest.fn(async (path) => path.endsWith("/capabilities") ? { status: 200, data: { preparation_recovery_enabled: true } } :
    path.endsWith("/auth/me") ? { status: 200, data: actor } : response("replayed")), put: jest.fn(async () => response()), post: jest.fn(async () => response("replayed")) };
  const options = { actor, api, durableStorage: storage, locks, crypto: { randomUUID: jest.fn(() => ID) },
    ...(changes.options || {}) };
  const controller = createOrderPreparationRecovery(options);
  return { controller, storage, api, locks, options,
    seed: (r = intent) => storage.setItem(key, JSON.stringify(r)),
    submit: (v = {}) => controller.submit({ order, action: "preparing", preparationTime: 15, ...v }) };
};

test("admission persists exact non-customer intent before one explicit PUT", async () => {
  const f = fixture();
  f.api.put.mockImplementation(async (_path, body) => {
    expect(JSON.parse(f.storage.getItem(key))).toEqual(intent);
    expect(body).toEqual({ client_operation_id: ID, expected_order_version: 3, preparation_time: 15 });
    return response();
  });
  expect(await f.submit()).toEqual(response().data);
  expect(f.api.put).toHaveBeenCalledTimes(1); expect(f.api.post).not.toHaveBeenCalled();
  expect(f.controller.snapshot().receipt.state).toBe("applied");
});
test("lost ACK is recovered by GET without a second mutation", async () => {
  const f = fixture(); f.api.put.mockRejectedValue(new Error("ACK lost"));
  expect((await f.submit()).state).toBe("replayed");
  expect(f.api.put).toHaveBeenCalledTimes(1); expect(f.api.post).not.toHaveBeenCalled();
  expect(f.controller.snapshot().client_operation_id).toBe(ID);
});
test("lookup404 after timeout retains UUID/payload and never automatically resends", async () => {
  const f = fixture(), normal = f.api.get.getMockImplementation();
  f.api.put.mockRejectedValue(new Error("Uncertain admission"));
  f.api.get.mockImplementation((path, options) => path.endsWith("/capabilities") ? normal(path, options) : Promise.reject(missing()));
  expect(await f.submit()).toEqual({ not_admitted: true });
  expect(f.controller.snapshot()).toEqual(intent); expect(f.api.put).toHaveBeenCalledTimes(1);
  expect(await f.controller.recover()).toEqual({ not_admitted: true });
  expect(f.api.put).toHaveBeenCalledTimes(1); expect(f.api.post).not.toHaveBeenCalled();
  f.api.put.mockResolvedValue(response());
  expect((await f.controller.resend()).state).toBe("applied");
  expect(f.api.put).toHaveBeenCalledTimes(2); expect(f.api.put.mock.calls[1][1]).toEqual(f.api.put.mock.calls[0][1]);
});
test("reload/pending lookup remains GET-only and resume is explicit/bodyless", async () => {
  const f = fixture(); f.seed(); f.api.get.mockResolvedValue(response("pending"));
  expect((await f.controller.recover()).state).toBe("pending");
  expect(f.api.put).not.toHaveBeenCalled(); expect(f.api.post).not.toHaveBeenCalled();
  expect((await f.controller.resume()).state).toBe("replayed");
  expect(f.api.post.mock.calls[0][0]).toBe(`/api/orders/operations/preparing/${order.id}/${ID}/resume`);
  expect(f.api.post.mock.calls[0][1]).toBeUndefined(); expect(f.api.put).not.toHaveBeenCalled();
});
test("explicit resend reconciles a now-admitted intent instead of writing again", async () => {
  const f = fixture(); f.seed();
  expect((await f.controller.resend()).state).toBe("replayed");
  expect(f.api.put).not.toHaveBeenCalled(); expect(f.api.post).not.toHaveBeenCalled();
});
test("same actor across tabs has one admission while the second tab is blocked", async () => {
  const shared = { storage: makeStorage(), locks: makeLocks() }, a = fixture(shared), b = fixture(shared), gate = deferred();
  a.api.put.mockReturnValue(gate.promise);
  const first = a.submit();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  await expect(b.submit()).rejects.toMatchObject({ code: "BUSY" });
  gate.resolve(response()); await first;
  expect(b.api.put).not.toHaveBeenCalled();
  await expect(b.submit()).rejects.toMatchObject({ code: "INTENT_PENDING" });
});
test("different minutes under uncertainty cannot create or replace an intent", async () => {
  const f = fixture(); f.seed();
  await expect(f.submit({ preparationTime: 5 })).rejects.toMatchObject({ code: "INTENT_PENDING" });
  expect(f.controller.snapshot().preparation_time).toBe(15); expect(f.api.put).not.toHaveBeenCalled();
});
test("feature off allows only unstarted legacy selection, never fallback for stored intent", async () => {
  const f = fixture(); f.api.get.mockResolvedValue({ status: 200, data: { preparation_recovery_enabled: false } });
  expect(f.controller.canUseLegacy()).toBe(false);
  expect(await f.controller.capability()).toBe(false); expect(f.controller.canUseLegacy()).toBe(true);
  f.seed(); expect(f.controller.canUseLegacy()).toBe(false);
  await expect(f.controller.capability()).rejects.toMatchObject({ code: "INTENT_PENDING" });
  expect(f.api.put).not.toHaveBeenCalled();
});
test.each([{}, { preparation_recovery_enabled: "false" }, { preparation_recovery_enabled: false, extra: true }])("unknown/malformed capability cannot select legacy: %p", async (body) => {
  const f = fixture(); f.api.get.mockResolvedValue({ status: 200, data: body });
  await expect(f.controller.capability()).rejects.toMatchObject({ code: "CAPABILITY_UNAVAILABLE" });
  expect(f.controller.canUseLegacy()).toBe(false); expect(f.api.put).not.toHaveBeenCalled();
});
test("feature disabled later does not block recovery of an admitted attempt", async () => {
  const f = fixture(); f.seed({ ...intent, receipt: response("pending").data });
  f.api.get.mockResolvedValue(response("replayed"));
  expect((await f.controller.recover()).state).toBe("replayed");
  expect(f.api.get.mock.calls.every(([path]) => !path.endsWith("/capabilities"))).toBe(true);
});
test.each([null, true, 3.5, -1, Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER + 1])("malformed/unsafe revision is refused without a write: %p", async (revision) => {
  const f = fixture();
  await expect(f.submit({ order: { ...order, order_version: revision } })).rejects.toMatchObject({ code: "ORDER_VERSION_INVALID" });
  expect(f.api.put).not.toHaveBeenCalled(); expect(f.storage.getItem(key)).toBeNull();
});
test("legacy absent version sends explicit null and is never promoted", async () => {
  const f = fixture(), legacy = { ...order }; delete legacy.order_version;
  f.api.put.mockResolvedValue(response("applied", { order_version: null }));
  expect((await f.submit({ order: legacy })).order_version).toBeNull();
  expect(f.api.put.mock.calls[0][1].expected_order_version).toBeNull();
});
test("READY retains explicit phase/intent with nullable legacy timestamps", async () => {
  const f = fixture();
  const ready = response("applied", { preparation_status: "READY", preparation_started_at: null, preparation_due_at: null,
    preparation_ready_at: start, preparation_time: null, preparation_estimated_seconds: null, preparation_actual_seconds: null, preparation_delay_seconds: 0 });
  f.api.put.mockResolvedValue(ready);
  expect((await f.submit({ action: "ready", order: { ...order, status: "PREPARING" } })).preparation_status).toBe("READY");
  expect(f.api.put.mock.calls[0][1]).toEqual({ client_operation_id: ID, expected_order_version: 3 });
});
test.each([0, 241, true, "15", 5.5, null])("invalid minutes have no durable record or PUT: %p", async (value) => {
  const f = fixture(); await expect(f.submit({ preparationTime: value })).rejects.toMatchObject({ code: "ORDER_NOT_ELIGIBLE" });
  expect(f.api.put).not.toHaveBeenCalled(); expect(f.storage.getItem(key)).toBeNull();
});
test.each([{ restaurant_id: "other" }, { status: "READY" }, { status: "PICKED_UP" }, { id: " " }])("wrong scope/phase/order is refused: %p", async (change) => {
  const f = fixture(); await expect(f.submit({ order: { ...order, ...change } })).rejects.toMatchObject({ code: "ORDER_NOT_ELIGIBLE" });
  expect(f.api.put).not.toHaveBeenCalled();
});
test("preparation remains available after assignment without changing its intent", async () => {
  const f = fixture(); await f.submit({ order: { ...order, status: "ACCEPTED", preparation_status: "NEW", driver_id: "driver" } });
  expect(f.api.put.mock.calls[0][1]).toEqual({ client_operation_id: ID, expected_order_version: 3, preparation_time: 15 });
});
test("storage denial occurs before request admission", async () => {
  const f = fixture(); f.storage.setItem.mockImplementation(() => { throw new Error("Quota"); });
  await expect(f.submit()).rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" }); expect(f.api.put).not.toHaveBeenCalled();
});
test("without Web Locks durable admission refuses instead of weakening protection", async () => {
  const f = fixture({ options: { locks: undefined } });
  await expect(f.submit()).rejects.toMatchObject({ code: "LOCK_UNAVAILABLE" }); expect(f.api.put).not.toHaveBeenCalled();
});
test("old request cannot publish after deactivation even when same controller is reactivated", async () => {
  const f = fixture(), gate = deferred(); f.seed(); f.api.get.mockReturnValue(gate.promise);
  const pending = f.controller.recover(); await Promise.resolve();
  f.controller.deactivate(); f.controller.activate(); gate.resolve(response("replayed"));
  await expect(pending).rejects.toMatchObject({ code: "SESSION_CHANGED" });
  expect(f.controller.snapshot().receipt).toBeNull();
});
test("late response after actor retirement cannot clear or replace saved attempt", async () => {
  let alive = true; const f = fixture({ options: { isOwnerActive: () => alive } }), gate = deferred();
  f.seed(); f.api.get.mockReturnValue(gate.promise); const pending = f.controller.recover();
  await Promise.resolve(); alive = false; gate.resolve(response("replayed"));
  await expect(pending).rejects.toMatchObject({ code: "SESSION_CHANGED" });
  expect(JSON.parse(f.storage.getItem(key)).receipt).toBeNull();
});
test.each([{ ...actor, restaurant_id: "rebound" }, { ...actor, role: "admin" }, { ...actor, account_disabled: true }, { ...actor, id: "other" }])("BFCache restore checks complete account binding: %p", async (user) => {
  const f = fixture(); f.seed(); f.controller.deactivate(); f.api.get.mockResolvedValue({ status: 200, data: user });
  await expect(f.controller.restoreSession()).rejects.toMatchObject({ code: "SESSION_CHANGED" });
  expect(() => f.controller.snapshot()).toThrow(); expect(f.api.put).not.toHaveBeenCalled();
});
test("offline retains stored attempt without requests", async () => {
  const f = fixture({ options: { isOnline: () => false } }); f.seed();
  await expect(f.controller.recover()).rejects.toMatchObject({ code: "OFFLINE" });
  expect(f.api.get).not.toHaveBeenCalled(); expect(f.controller.snapshot()).toEqual(intent);
});
test.each([{ preparation_time: 5 }, { order_id: "other" }, { order_version: 5 }, { preparation_status: "READY" }, { client_operation_id: ID + "a" },
  { preparation_due_at: "2026-10-11T08:05:00+00:00" }, { preparation_started_at: "2026-02-31T08:00:00+00:00" }, { extra: true }])("receipt with different/corrupt attribution cannot confirm: %p", (change) => {
  expect(() => validatePreparationReceipt(response("applied", change), intent)).toThrow();
});
test("pending/rejected receipt cannot carry partial business effects", () => {
  expect(() => validatePreparationReceipt(response("pending", { preparation_time: 15 }), intent)).toThrow();
  expect(() => validatePreparationReceipt(response("rejected", { order_id: order.id }), intent)).toThrow();
  const pending = response("pending"); pending.headers = {}; expect(() => validatePreparationReceipt(pending, intent)).toThrow();
});
test.each(Object.entries(preparationRejectionStatus))("business rejection %s is retained and requires acknowledgement", async (code, status) => {
  const f = fixture(); f.seed(); f.api.get.mockResolvedValue({ ...response("rejected", { error_code: code }), status });
  expect((await f.controller.recover()).state).toBe("rejected");
  await expect(f.submit()).rejects.toMatchObject({ code: "INTENT_PENDING" });
  f.api.get.mockImplementation(async (path) => path === `/api/orders/${order.id}` ? { status: 200, data: order } : { ...response("rejected", { error_code: code }), status });
  await f.controller.acknowledge(); expect(f.storage.getItem(key)).toBeNull(); expect(f.api.put).not.toHaveBeenCalled();
});
test("uncertain intent cannot be acknowledged away", async () => {
  const f = fixture(); f.seed(); await expect(f.controller.acknowledge()).rejects.toMatchObject({ code: "OPERATION_UNCERTAIN" });
  expect(f.controller.snapshot()).toEqual(intent);
});
test("corrupt saved record fails closed without erasing it", async () => {
  const f = fixture(); f.seed({ ...intent, unexpected: "private" }); const raw = f.storage.getItem(key);
  await expect(f.controller.recover()).rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" });
  expect(f.storage.getItem(key)).toBe(raw); expect(f.api.get).not.toHaveBeenCalled();
});
test("acknowledgement retains the gate until authoritative refresh completes", async () => {
  const f = fixture(), gate = deferred(); f.seed({ ...intent, receipt: response("rejected").data });
  f.api.get.mockImplementation((path) => path === `/api/orders/${order.id}` ? gate.promise : Promise.resolve(response("rejected")));
  const ack = f.controller.acknowledge(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  expect(f.storage.getItem(key)).not.toBeNull(); await expect(f.submit()).rejects.toMatchObject({ code: "BUSY" });
  gate.resolve({ status: 200, data: { ...order, status: "PREPARING", order_version: 4 } });
  expect((await ack).status).toBe("PREPARING"); expect(f.storage.getItem(key)).toBeNull();
});
test.each(["offline", "failed-read", "foreign-order", "unsafe-revision"])("acknowledgement keeps terminal intent on %s", async (kind) => {
  const f = fixture({ options: { isOnline: () => kind !== "offline" } });
  f.seed({ ...intent, receipt: response("rejected").data }); const before = f.storage.getItem(key);
  f.api.get.mockImplementation(async (path) => {
    if (path !== `/api/orders/${order.id}`) return response("rejected");
    if (kind === "failed-read") throw new Error("Read failed");
    return { status: 200, data: { ...order, ...(kind === "foreign-order" ? { restaurant_id: "other" } : { order_version: Number.MAX_SAFE_INTEGER + 1 }) } };
  });
  await expect(f.controller.acknowledge()).rejects.toBeInstanceOf(Error);
  expect(f.storage.getItem(key)).toBe(before); expect(f.api.put).not.toHaveBeenCalled();
});
test("a fresh failed capability probe expires a previous false legacy decision", async () => {
  const f = fixture(); f.api.get.mockResolvedValue({ status: 200, data: { preparation_recovery_enabled: false } });
  expect(await f.controller.capability()).toBe(false); expect(f.controller.canUseLegacy()).toBe(true);
  f.api.get.mockRejectedValue(new Error("Connection failed"));
  await expect(f.controller.capability()).rejects.toThrow(); expect(f.controller.canUseLegacy()).toBe(false);
});
test("PREPARING receipt preserves legacy historical ready metadata without confusing action identity", () => {
  const r = response("applied", { preparation_ready_at: "2026-10-10T08:00:00+00:00", preparation_actual_seconds: 300, preparation_delay_seconds: 0 });
  expect(validatePreparationReceipt(r, intent).preparation_ready_at).toBe("2026-10-10T08:00:00+00:00");
});
test("READY requires delay and supports actual null only when legacy start is absent", () => {
  const readyIntent = { ...intent, action: "ready", preparation_time: null };
  const r = response("applied", { preparation_status: "READY", preparation_ready_at: due, preparation_actual_seconds: 900, preparation_delay_seconds: 0 });
  expect(validatePreparationReceipt(r, readyIntent).preparation_status).toBe("READY");
  expect(() => validatePreparationReceipt({ ...r, data: { ...r.data, preparation_delay_seconds: null } }, readyIntent)).toThrow();
  expect(() => validatePreparationReceipt({ ...r, data: { ...r.data, preparation_actual_seconds: null } }, readyIntent)).toThrow();
  expect(() => validatePreparationReceipt({ ...r, data: { ...r.data, preparation_estimated_seconds: 14401 } }, readyIntent)).toThrow();
});
