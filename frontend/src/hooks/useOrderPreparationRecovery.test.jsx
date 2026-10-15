import { act, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { useOrderPreparationRecovery } from "./useOrderPreparationRecovery";
import { PreparationRecoveryPanel } from "../components/restaurant/PreparationRecoveryPanel";
jest.mock("axios", () => ({ create: jest.fn() }));

const actor = { id: "synthetic-hook-user", role: "restaurant", restaurant_id: "synthetic-restaurant" };
const ID = "8e949378-150f-4934-aa82-aa130009578b", key = `prodelivery:order-preparation:v1:${actor.id}:restaurant:${actor.restaurant_id}`;
const order = { id: "synthetic-order", restaurant_id: actor.restaurant_id, status: "NEW", order_version: 2 };
const stored = { version: 1, actor_id: actor.id, role: actor.role, restaurant_id: actor.restaurant_id,
  order_id: order.id, action: "preparing", client_operation_id: ID, expected_order_version: 2, preparation_time: 15, receipt: null };
const receipt = (state = "pending") => ({ status: state === "pending" ? 202 : 200, headers: state === "pending" ? { "retry-after": "2" } : {},
  data: { client_operation_id: ID, state, order_id: state === "pending" ? null : order.id, order_version: state === "pending" ? null : 3,
    preparation_status: state === "pending" ? null : "PREPARING", preparation_time: state === "pending" ? null : 15,
    preparation_started_at: state === "pending" ? null : "2026-10-11T10:00:00+00:00",
    preparation_due_at: state === "pending" ? null : "2026-10-11T10:15:00+00:00", preparation_ready_at: null,
    preparation_estimated_seconds: state === "pending" ? null : 900, preparation_actual_seconds: null, preparation_delay_seconds: null,
    error_code: null, retry_after_seconds: state === "pending" ? 2 : null } });
const missing = () => Object.assign(new Error("not admitted"), { response: { status: 404, data: { detail: { code: "OPERATION_NOT_FOUND" } } } });
const deferred = () => { let resolve; const promise = new Promise((yes) => { resolve = yes; }); return { promise, resolve }; };
let root, container, view, transport, onAcknowledged;
const Probe = ({ user = actor, token = "synthetic-token", online = true, acknowledge }) => {
  view = useOrderPreparationRecovery(user, "https://qa.invalid", online, token);
  return <PreparationRecoveryPanel recovery={acknowledge ? { ...view, acknowledge } : view} isOnline={online} onAcknowledged={onAcknowledged} />;
};
const render = (props = {}, strict = false) => act(async () => root.render(strict ? <StrictMode><Probe {...props} /></StrictMode> : <Probe {...props} />));
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
const event = (name, persisted = true) => act(async () => {
  const e = new Event(name); Object.defineProperty(e, "persisted", { value: persisted }); window.dispatchEvent(e);
});
const node = (id) => container.querySelector(`[data-testid="${id}"]`);
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; jest.clearAllMocks(); window.localStorage.clear();
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: jest.fn(async (_key, _opts, callback) => callback({})) } });
  Object.defineProperty(window, "crypto", { configurable: true, value: { randomUUID: () => ID } });
  transport = { get: jest.fn(async (path) => path.endsWith("/auth/me") ? { status: 200, data: actor } :
    path.endsWith("/capabilities") ? { status: 200, data: { preparation_recovery_enabled: true } } : receipt()),
    put: jest.fn(async () => receipt("applied")), post: jest.fn(async () => receipt("replayed")) };
  axios.create.mockReturnValue(transport); onAcknowledged = jest.fn();
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

test("mount/reconnect with saved pending intent performs GET only", async () => {
  window.localStorage.setItem(key, JSON.stringify(stored)); await render(); await flush();
  expect(node("preparation-resume-button")).not.toBeNull(); expect(transport.get).toHaveBeenCalled();
  expect(transport.put).not.toHaveBeenCalled(); expect(transport.post).not.toHaveBeenCalled();
  await render({ online: false }); await render({ online: true }); await flush();
  expect(transport.put).not.toHaveBeenCalled(); expect(transport.post).not.toHaveBeenCalled();
  await act(async () => node("preparation-resume-button").click());
  expect(transport.post).toHaveBeenCalledTimes(1); expect(transport.post.mock.calls[0][1]).toBeUndefined();
});
test("StrictMode lookup404 offers explicit resend without mutation on mount", async () => {
  window.localStorage.setItem(key, JSON.stringify(stored)); transport.get.mockRejectedValue(missing());
  await render({}, true); await flush();
  expect(node("preparation-resend-button")).not.toBeNull(); expect(transport.put).not.toHaveBeenCalled();
  await act(async () => node("preparation-resend-button").click());
  expect(transport.put).toHaveBeenCalledTimes(1); expect(transport.post).not.toHaveBeenCalled();
  expect(transport.put.mock.calls[0][1]).toEqual({ client_operation_id: ID, expected_order_version: 2, preparation_time: 15 });
});
test("two synchronous actions admit one mutation", async () => {
  await render(); const gate = deferred(); transport.put.mockReturnValue(gate.promise);
  let first, second;
  await act(async () => { first = view.submit({ order, action: "preparing", preparationTime: 15 }); second = view.submit({ order, action: "preparing", preparationTime: 15 }); });
  expect(await second).toBeNull(); expect(transport.put).toHaveBeenCalledTimes(1);
  await act(async () => { gate.resolve(receipt("applied")); await first; });
  expect(view.record.receipt.state).toBe("applied");
});
test("actor switch immediately hides old saved intent and fences its late response", async () => {
  const gate = deferred(); window.localStorage.setItem(key, JSON.stringify(stored)); transport.get.mockReturnValue(gate.promise);
  await render(); await render({ user: { ...actor, id: "other", restaurant_id: "other-restaurant" } });
  expect(node("preparation-recovery-state")).toBeNull();
  await act(async () => gate.resolve(receipt("replayed")));
  expect(view.record).toBeNull(); expect(JSON.parse(window.localStorage.getItem(key)).receipt).toBeNull();
  expect(transport.put).not.toHaveBeenCalled();
});
test("token rotation keeps exact stored intent and clears inherited bearer on cookie-only requests", async () => {
  window.localStorage.setItem(key, JSON.stringify(stored)); await render(); await render({ token: null }); await flush();
  expect(view.record.client_operation_id).toBe(ID);
  expect(transport.get.mock.calls.at(-1)[1].headers).toEqual({ Authorization: null, "X-Expected-Actor-ID": actor.id });
  expect(transport.put).not.toHaveBeenCalled(); expect(transport.post).not.toHaveBeenCalled();
});
test("BFCache reactivation validates restaurant binding and never resumes automatically", async () => {
  window.localStorage.setItem(key, JSON.stringify(stored)); await render(); await event("pagehide");
  expect(view.sessionSuspended).toBe(true); expect(node("preparation-resume-button").disabled).toBe(true);
  transport.get.mockImplementation(async (path) => path.endsWith("/auth/me") ? { status: 200, data: { ...actor, restaurant_id: "rebound" } } : receipt());
  await event("pageshow"); expect(view.sessionSuspended).toBe(true); expect(view.errorCode).toBe("SESSION_CHANGED");
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test("BFCache correct restoration only reads and leaves pending resume explicit", async () => {
  window.localStorage.setItem(key, JSON.stringify(stored)); await render(); await event("pagehide"); await event("pageshow"); await flush();
  expect(view.sessionSuspended).toBe(false); expect(node("preparation-resume-button")).not.toBeNull();
  expect(transport.post).not.toHaveBeenCalled(); expect(transport.put).not.toHaveBeenCalled();
});
test("offline acknowledgement is disabled and preserves terminal result", async () => {
  window.localStorage.setItem(key, JSON.stringify({ ...stored, receipt: receipt("applied").data })); await render({ online: false });
  expect(node("preparation-acknowledge-button").disabled).toBe(true); expect(window.localStorage.getItem(key)).not.toBeNull();
  expect(onAcknowledged).not.toHaveBeenCalled();
});
test("acknowledgement does not unblock until authoritative order refresh succeeds", async () => {
  window.localStorage.setItem(key, JSON.stringify({ ...stored, receipt: receipt("applied").data }));
  const gate = deferred(); transport.get.mockImplementation((path) => path.endsWith(`/api/orders/${order.id}`) ? gate.promise : Promise.resolve(receipt("replayed")));
  await render(); await act(async () => node("preparation-acknowledge-button").click());
  expect(view.blocked).toBeTruthy(); expect(window.localStorage.getItem(key)).not.toBeNull(); expect(onAcknowledged).not.toHaveBeenCalled();
  const fresh = { ...order, status: "PREPARING", order_version: 3 };
  await act(async () => gate.resolve({ status: 200, data: fresh })); await flush();
  expect(view.blocked).toBeFalsy(); expect(onAcknowledged).toHaveBeenCalledWith(fresh); expect(window.localStorage.getItem(key)).toBeNull();
});
test("corrupt storage stays visible and blocks new actions without erasing evidence", async () => {
  window.localStorage.setItem(key, "bad-json"); await render();
  expect(node("preparation-recovery-error")).not.toBeNull(); expect(view.blocked).toBeTruthy();
  expect(window.localStorage.getItem(key)).toBe("bad-json"); expect(transport.put).not.toHaveBeenCalled();
});

test.each(["actor", "token", "restaurant", "role", "is_disabled", "account_disabled", "pagehide"])("queued acknowledgement cannot publish after %s changes", async (kind) => {
  window.localStorage.setItem(key, JSON.stringify({ ...stored, receipt: receipt("applied").data }));
  const gate = deferred(), acknowledge = jest.fn(() => gate.promise);
  await render({ acknowledge }); await act(async () => node("preparation-acknowledge-button").click());
  expect(acknowledge).toHaveBeenCalledTimes(1);
  if (kind === "pagehide") await event("pagehide");
  else if (kind === "token") await render({ acknowledge, token: "rotated-token" });
  else {
    const changes = kind === "actor" ? { id: "other-actor" } : kind === "restaurant" ? { restaurant_id: "other-restaurant" } :
      kind === "role" ? { role: "admin" } : { [kind]: true };
    await render({ acknowledge, user: { ...actor, ...changes } });
  }
  await act(async () => gate.resolve({ ...order, status: "PREPARING", order_version: 3 })); await flush();
  expect(onAcknowledged).not.toHaveBeenCalled();
  expect(transport.put).not.toHaveBeenCalled(); expect(transport.post).not.toHaveBeenCalled();
});
