import { createOperationalReporting, reportApplied, reportPaths, reportStorageKey } from "./operationalReporting";
const operation = "719ae221-cb0d-4bf0-b6a5-ab4d21ab781f";
const actor = { id: "restaurant-user", role: "restaurant", restaurant_id: "restaurant-a" };
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const fixture = (options = {}) => {
  const values = new Map(); const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
  let active = true, online = true;
  const applied = { state: "applied", client_operation_id: operation, operation_type: "close_day", restaurant_id: "restaurant-a", close_day_operation_id: operation,
    closed_today: true, accepting_orders: false, pause_until: "2026-10-10T22:00:00Z" };
  const api = { get: jest.fn(async (path) => ({ status: 200, data: path.endsWith("/me") ? actor : path.endsWith("/capabilities") ? { close_day_enabled: true, incident_reporting_enabled: true } : applied })),
    patch: jest.fn(async () => ({ status: 200, data: applied })), post: jest.fn(async () => ({ status: 200, data: applied })) };
  const change = jest.fn();
  const make = () => createOperationalReporting({ actor, scope: "restaurant-a", api, storage, crypto: { randomUUID: () => operation },
    isOnline: () => online, isOwnerActive: () => active, onChange: change, ...options });
  const controller = make(); controller.activate();
  return { controller, make, values, storage, api, applied, change, active: (v) => { active = v; }, online: (v) => { online = v; } };
};
const input = { operation_type: "close_day", resource_id: "restaurant-a" };
test("close-day submits only stable intent; server pause wins over local state", async () => {
  const f = fixture(); const receipt = await f.controller.submit(input);
  expect(receipt.accepting_orders).toBe(false); expect(receipt.pause_until).toBe("2026-10-10T22:00:00Z");
  expect(f.api.patch.mock.calls[0][1]).toEqual({ client_operation_id: operation });
  expect(JSON.parse([...f.values.values()][0]).command.client_operation_id).toBe(operation);
});
test("same tick double submit is single flight", async () => {
  const f = fixture(), gate = deferred(); f.api.patch.mockReturnValue(gate.promise);
  const first = f.controller.submit(input); expect(await f.controller.submit(input)).toBeNull();
  await Promise.resolve(); await Promise.resolve(); gate.resolve({ status: 200, data: f.applied }); await first;
  expect(f.api.patch).toHaveBeenCalledTimes(1);
});
test("storage failure prevents admission", async () => {
  const f = fixture(); f.storage.setItem = () => { throw Error("storage denied"); };
  await expect(f.controller.submit(input)).rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" }); expect(f.api.patch).not.toHaveBeenCalled();
});
test("disabled marker prevents new write", async () => {
  const f = fixture(); f.api.get.mockImplementation(async (path) => ({ status: 200, data: path.endsWith("/me") ? actor : { close_day_enabled: false } }));
  await expect(f.controller.submit(input)).rejects.toMatchObject({ code: "NOT_ENABLED" }); expect(f.api.patch).not.toHaveBeenCalled(); expect(f.values.size).toBe(0);
});
test("lost ACK retains exact intent and reload recovers with lookup only", async () => {
  const f = fixture(); f.api.patch.mockRejectedValue(Error("ACK lost"));
  await expect(f.controller.submit(input)).rejects.toThrow("ACK lost"); const second = f.make(); second.activate();
  expect(reportApplied(await second.recover())).toBe(true); expect(f.api.patch).toHaveBeenCalledTimes(1); expect(f.api.post).not.toHaveBeenCalled();
  expect(f.api.get.mock.calls.at(-1)[0]).toBe(reportPaths({ ...input, client_operation_id: operation }).lookup);
});
test("unadmitted lookup requires explicit retry with same UUID and body", async () => {
  const f = fixture(); f.api.patch.mockRejectedValueOnce(Error("network")); await expect(f.controller.submit(input)).rejects.toThrow();
  const normal = f.api.get.getMockImplementation(); f.api.get.mockImplementation((path) => path.includes("/operations/") ? Promise.reject({ response: { status: 404 } }) : normal(path));
  await expect(f.controller.recover()).rejects.toMatchObject({ code: "NOT_ADMITTED" }); expect(f.api.patch).toHaveBeenCalledTimes(1);
  await f.controller.recover(true); expect(f.api.patch).toHaveBeenCalledTimes(2); expect(f.api.patch.mock.calls[1][1]).toEqual(f.api.patch.mock.calls[0][1]);
});
test("pending recovery resumes bodyless with same target and operation", async () => {
  const f = fixture(); f.api.patch.mockResolvedValue({ status: 202, data: { state: "pending", client_operation_id: operation, operation_type: "close_day", retry_after_seconds: 2 } });
  await f.controller.submit(input); const normal = f.api.get.getMockImplementation();
  f.api.get.mockImplementation((path) => path.includes("/operations/") ? Promise.resolve({ status: 202, data: { state: "pending", client_operation_id: operation, operation_type: "close_day", retry_after_seconds: 2 } }) : normal(path));
  await f.controller.recover(); expect(f.api.post.mock.calls[0][1]).toBeUndefined(); expect(f.api.post.mock.calls[0][0]).toBe(reportPaths({ ...input, client_operation_id: operation }).resume);
});
test("cookie actor change fences mutation", async () => {
  const f = fixture(); f.api.get.mockResolvedValue({ status: 200, data: { ...actor, id: "other-actor" } });
  await expect(f.controller.submit(input)).rejects.toMatchObject({ code: "SESSION_CHANGED" }); expect(f.api.patch).not.toHaveBeenCalled();
});
test.each(["submit", "revalidate"])("suspend in verified auth continuation gap fences %s before action or storage publication", async (action) => {
  const f = fixture(), actual = { ...actor }; let fired = false;
  Object.defineProperty(actual, "is_disabled", { get: () => { if (!fired) { fired = true; queueMicrotask(() => f.controller.suspend()); } return false; } });
  f.api.get.mockResolvedValue({ status: 200, data: actual }); f.change.mockClear(); const read = jest.spyOn(f.storage, "getItem");
  await expect(action === "submit" ? f.controller.submit(input) : f.controller.revalidate()).rejects.toMatchObject({ code: "SESSION_CHANGED" });
  expect(f.api.patch).not.toHaveBeenCalled(); expect(read).not.toHaveBeenCalled(); expect(f.change).not.toHaveBeenCalled(); expect(f.values.size).toBe(0);
});
test("actor retired before ACK cannot persist terminal success", async () => {
  const f = fixture(), gate = deferred(), entered = deferred(); f.api.patch.mockImplementation(() => { entered.resolve(); return gate.promise; });
  const first = f.controller.submit(input); await entered.promise;
  f.active(false); gate.resolve({ status: 200, data: f.applied }); await expect(first).rejects.toMatchObject({ code: "SESSION_CHANGED" });
  expect(f.controller.snapshot().receipt).toBeNull();
});
test("pagehide fences late ACK and revalidation restores exact intent", async () => {
  const f = fixture(), gate = deferred(), entered = deferred(); f.api.patch.mockImplementation(() => { entered.resolve(); return gate.promise; });
  const first = f.controller.submit(input); await entered.promise;
  f.controller.suspend(); gate.resolve({ status: 200, data: f.applied }); await expect(first).rejects.toMatchObject({ code: "SESSION_CHANGED" });
  expect(f.controller.snapshot().receipt).toBeNull(); await f.controller.revalidate(); expect(reportApplied(await f.controller.recover())).toBe(true);
});
test.each(["client_operation_id", "restaurant_id", "close_day_operation_id"])("foreign receipt %s cannot confirm close-day", async (field) => {
  const f = fixture(); f.api.patch.mockResolvedValue({ status: 200, data: { ...f.applied, [field]: "foreign" } });
  await expect(f.controller.submit(input)).rejects.toMatchObject({ code: "INVALID_RECEIPT" }); expect(f.controller.snapshot().receipt).toBeNull();
});
test.each([404, 409])("applied response on HTTP %s is inconsistent and stays uncertain", async (status) => {
  const f = fixture(); f.api.patch.mockResolvedValue({ status, data: f.applied });
  await expect(f.controller.submit(input)).rejects.toMatchObject({ code: "INVALID_RECEIPT" }); expect(f.controller.snapshot().receipt).toBeNull();
});
test("invalid saved draft remains retained and blocks network", async () => {
  const f = fixture(), key = reportStorageKey(actor.id, "restaurant-a"); f.values.set(key, "malformed"); const second = f.make();
  expect(() => second.activate()).toThrow(); expect(f.values.get(key)).toBe("malformed"); await expect(second.recover()).rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" }); expect(f.api.get).not.toHaveBeenCalled();
});
test("offline retains intent without API replay", async () => {
  const f = fixture(); f.api.patch.mockRejectedValue(Error("network")); await expect(f.controller.submit(input)).rejects.toThrow(); f.api.get.mockClear(); f.online(false);
  await expect(f.controller.recover()).rejects.toMatchObject({ code: "OFFLINE" }); expect(f.api.get).not.toHaveBeenCalled(); expect(f.controller.snapshot().command.client_operation_id).toBe(operation);
});
test("a permanently pending request settles at finite watchdog", async () => {
  const f = fixture({ timeout: 10 }); f.api.patch.mockReturnValue(new Promise(() => {}));
  await expect(f.controller.submit(input)).rejects.toMatchObject({ code: "UNCERTAIN" }); expect(f.controller.snapshot().receipt).toBeNull();
});
test("versioned incident sends strict operational fields without financial controls", async () => {
  const f = fixture(), receipt = { state: "applied", client_operation_id: operation, operation_type: "incident", order_id: "order-a", order_version: 5, incident_id: "incident-a" };
  f.api.post.mockResolvedValue({ status: 200, data: receipt });
  await f.controller.submit({ operation_type: "incident", resource_id: "order-a", expected_order_version: 4, incident_type: "missing_product", description: "Missing bag" });
  expect(f.api.post.mock.calls[0][1]).toEqual({ client_operation_id: operation, expected_order_version: 4, incident_type: "missing_product", description: "Missing bag" });
});
test("legacy incident preserves null revision in immutable intent", async () => {
  const f = fixture(); f.api.post.mockResolvedValue({ status: 200, data: { state: "applied", client_operation_id: operation, operation_type: "incident", order_id: "legacy", order_version: null, incident_id: "incident-a" } });
  await f.controller.submit({ operation_type: "incident", resource_id: "legacy", expected_order_version: null, incident_type: "other", description: "Check" });
  expect(f.api.post.mock.calls[0][1].expected_order_version).toBeNull();
});
