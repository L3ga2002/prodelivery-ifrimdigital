import { createOrderCustodyRecovery, custodyRejectionStatus, validateCustodyReceipt } from "./orderCustodyRecovery";
import { IDS, custodyOrder, driver, restaurant, admin, waitCommand } from "./orderCustody.fixtures";
const receipt = (state = "applied", code = null) => ({ status: state === "pending" ? 202 : state === "rejected" ? custodyRejectionStatus[code] : 200, headers: { "retry-after": "2" }, data: { client_operation_id: IDS[0], state, order_id: ["applied", "replayed"].includes(state) ? "order" : null, order_version: ["applied", "replayed"].includes(state) ? 4 : null, error_code: code, retry_after_seconds: state === "pending" ? 2 : null } });
const missing = () => Object.assign(Error("missing"), { response: { status: 404, data: { detail: { code: "OPERATION_NOT_FOUND" } } } });
const deferred = () => { let resolve; const promise = new Promise((yes) => { resolve = yes; }); return { promise, resolve }; };
let api, values, storage, locks, uuid, online, controller;
const make = (actor = driver) => createOrderCustodyRecovery({ actor, api, durableStorage: storage, locks, crypto: { randomUUID: uuid }, isOnline: () => online });
const submit = () => controller.submit({ order: custodyOrder(), command: waitCommand() });
beforeEach(() => {
  values = new Map(); storage = { getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) }; online = true;
  locks = { request: jest.fn(async (_k, _o, cb) => cb({})) }; uuid = jest.fn(() => IDS[0]);
  api = { get: jest.fn(async (path) => path.endsWith("capabilities") ? { status: 200, data: { custody_recovery_enabled: true } } : path.endsWith("/order") ? { status: 200, data: custodyOrder("waiting", { order_version: 4 }) } : receipt("replayed")), post: jest.fn(async () => receipt()) }; controller = make();
});
test("durable strict command saves before POST without private order data or invented timestamps/money", async () => {
  api.post.mockImplementation(async (_path, body) => { expect(controller.snapshot().command).toEqual(waitCommand()); expect(body).toEqual({ client_operation_id: IDS[0], expected_order_version: 3, ...waitCommand() }); return receipt(); });
  await controller.submit({ order: { ...custodyOrder(), customer_name: "PRIVATE", customer_address: "SECRET" }, command: waitCommand() });
  expect([...values.values()][0]).not.toMatch(/PRIVATE|SECRET|token|amount_bani|wait_started_at/); expect(controller.snapshot().receipt.state).toBe("applied");
});
test("lost ACK and reload use exact initial identity without automatic POST", async () => {
  api.post.mockRejectedValue(Error("lost")); expect((await submit()).state).toBe("replayed"); controller = make(); await controller.recover(); expect(api.post).toHaveBeenCalledTimes(1); expect(uuid).toHaveBeenCalledTimes(1);
});
test("not admitted lookup offers explicit same-ID resend and blocks opposite or changed target", async () => {
  api.post.mockRejectedValue(Error("lost")); api.get.mockImplementation(async (path) => path.endsWith("capabilities") ? { status: 200, data: { custody_recovery_enabled: true } } : Promise.reject(missing()));
  expect(await submit()).toEqual({ not_admitted: true }); await expect(controller.submit({ order: custodyOrder(null, { id: "other" }), command: { ...waitCommand(), reason: "refused" } })).rejects.toMatchObject({ code: "INTENT_PENDING" });
  controller = make(); await controller.recover(); expect(api.post).toHaveBeenCalledTimes(1); api.post.mockResolvedValue(receipt()); await controller.resend(); expect(api.post.mock.calls[1][1]).toEqual(api.post.mock.calls[0][1]); expect(uuid).toHaveBeenCalledTimes(1);
});
test("pending continuation is bodyless after lookup, remains usable when new admissions are disabled", async () => {
  api.post.mockResolvedValue(receipt("pending")); await submit(); controller = make(); api.get.mockImplementation(async (path) => path.endsWith("capabilities") ? { status: 200, data: { custody_recovery_enabled: false } } : receipt("pending"));
  api.post.mockResolvedValue(receipt("replayed")); await controller.resume(); expect(api.post.mock.calls[1][0]).toBe(`/api/orders/operations/custody/order/${IDS[0]}/resume`); expect(api.post.mock.calls[1][1]).toBeUndefined(); expect(uuid).toHaveBeenCalledTimes(1);
});
test("default off prevents identity allocation and any persistence/mutation", async () => { api.get.mockResolvedValue({ status: 200, data: { custody_recovery_enabled: false } }); await expect(submit()).rejects.toMatchObject({ code: "CUSTODY_DISABLED" }); expect(values.size).toBe(0); expect(uuid).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled(); });
test.each(Object.keys(custodyRejectionStatus))("durable %s rejection is verifiable", async (code) => { api.post.mockResolvedValue(receipt("rejected", code)); expect((await submit()).error_code).toBe(code); expect(controller.snapshot().receipt.state).toBe("rejected"); });
test("actor, role, resource isolate recovery and foreign target cannot be admitted", async () => {
  await submit(); expect(make({ ...driver, id: "other" }).snapshot()).toBeNull(); expect(make({ ...driver, driver_id: "other" }).snapshot()).toBeNull(); expect(make(admin).snapshot()).toBeNull();
  await expect(make({ ...driver, driver_id: "foreign" }).submit({ order: custodyOrder(), command: waitCommand() })).rejects.toMatchObject({ code: "ORDER_NOT_ELIGIBLE" });
});
test("every role command serializes only its frozen fields", async () => {
  const cases = [
    [admin, "waiting", { event_type: "delivery_failure_reviewed", incident_id: IDS[1], predecessor_id: IDS[2], customer_contact_attempted: true, restaurant_contacted: true, coordination_confirmed: true }],
    [restaurant, "reviewed", { event_type: "products_disposition_decided", incident_id: IDS[1], predecessor_id: IDS[3], decision: "return" }],
    [restaurant, "return_requested", { event_type: "products_return_received", incident_id: IDS[1], predecessor_id: IDS[4] }],
    [driver, "keep_authorized", { event_type: "products_keep_acknowledged", incident_id: IDS[1], predecessor_id: IDS[4] }],
  ];
  for (const [actor, status, command] of cases) { values.clear(); controller = make(actor); await controller.submit({ order: custodyOrder(status), command }); expect(api.post.mock.calls.at(-1)[1]).toEqual({ client_operation_id: IDS[0], expected_order_version: 3, ...command }); }
});
test("offline/browser-lock/storage failure preserve safety and emit no POST", async () => {
  online = false; await expect(submit()).rejects.toMatchObject({ code: "OFFLINE" }); online = true; locks.request.mockImplementation(async (_k, _o, cb) => cb(null)); await expect(submit()).rejects.toMatchObject({ code: "BUSY" }); locks.request.mockImplementation(async (_k, _o, cb) => cb({})); storage.setItem = () => { throw Error("quota"); }; await expect(submit()).rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" }); expect(api.post).not.toHaveBeenCalled();
});
test("two controllers share one browser lock; corrupted records retain original bytes", async () => {
  let held = false; const gate = deferred(), started = deferred(); locks.request.mockImplementation(async (_k, _o, cb) => { if (held) return cb(null); held = true; try { return await cb({}); } finally { held = false; } }); api.post.mockImplementation(() => { started.resolve(); return gate.promise; });
  const first = submit(); await started.promise; await expect(make().submit({ order: custodyOrder(), command: waitCommand() })).rejects.toMatchObject({ code: "BUSY" }); gate.resolve(receipt()); await first; expect(api.post).toHaveBeenCalledTimes(1);
  const key = [...values.keys()][0]; values.set(key, "broken JSON"); expect(() => make().snapshot()).toThrow(); expect(values.get(key)).toBe("broken JSON");
});
test("account retirement fences a late server receipt from local storage", async () => {
  const late = deferred(), started = deferred(); api.post.mockImplementation(() => { started.resolve(); return late.promise; }); const flight = submit(); await started.promise; controller.deactivate(); late.resolve(receipt()); await expect(flight).rejects.toMatchObject({ code: "SESSION_CHANGED" }); expect(JSON.parse([...values.values()][0]).receipt).toBeNull();
});
test("acknowledge requires receipt, exact original binding and fresh compatible projection", async () => {
  await submit(); for (const patch of [{ order_version: 3 }, { driver_id: "other" }, { custody_activity: null }, { custody_activity: { ...custodyOrder("waiting").custody_activity, incident_id: IDS[5] } }]) { api.get.mockImplementation(async (path) => path.endsWith("/order") ? { status: 200, data: { ...custodyOrder("waiting"), order_version: 4, ...patch } } : receipt("replayed")); await expect(controller.acknowledge()).rejects.toMatchObject({ code: "INVALID_RESPONSE" }); expect(values.size).toBe(1); }
  api.get.mockImplementation(async (path) => path.endsWith("/order") ? { status: 200, data: custodyOrder("waiting", { order_version: 4 }) } : receipt("replayed")); expect((await controller.acknowledge()).order_version).toBe(4); expect(values.size).toBe(0);
});
test("terminal return replay after driver gets another order never sends a second mutation", async () => {
  controller = make(restaurant); await controller.submit({ order: custodyOrder("return_requested"), command: { event_type: "products_return_received", incident_id: IDS[1], predecessor_id: IDS[4] } });
  api.get.mockImplementation(async (path) => path.endsWith("/order") ? { status: 200, data: custodyOrder("returned", { order_version: 4 }) } : receipt("replayed")); await controller.acknowledge(); expect(api.post).toHaveBeenCalledTimes(1); expect(values.size).toBe(0);
});
test("malformed receipt identity, shape, revision and retry header fail closed", () => {
  const record = { client_operation_id: IDS[0], order_id: "order", expected_order_version: 3 };
  for (const patch of [{ order_id: "other" }, { order_version: 5 }, { extra: "secret" }, { client_operation_id: IDS[1] }]) expect(() => validateCustodyReceipt({ ...receipt(), data: { ...receipt().data, ...patch } }, record)).toThrow(); expect(() => validateCustodyReceipt({ ...receipt("pending"), headers: {} }, record)).toThrow();
});
