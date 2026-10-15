import { act } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { createOrderRecovery } from "../lib/orderCreationRecovery";
import { useOrderCreationRecovery } from "./useOrderCreationRecovery";
jest.mock("axios", () => ({ create: jest.fn() }));
const ID = "123e4567-e89b-42d3-a456-426614174000", KEY = "prodelivery:order-create:v1:actor", DRAFT = `${KEY}:draft:${ID}`;
const record = { version: 1, actor_id: "actor", client_operation_id: ID, created_at: 1, receipt: null };
const draft = { actor_id: "actor", client_operation_id: ID, order: { restaurant_id: "r", customer_name: "Private clone", customer_phone: "0700000000", customer_address: "Inherited private address", items: [], total_amount: 26, payment_type: "CASH", source: "S" } };
const terminal = { ...record, receipt: { client_operation_id: ID, state: "applied", order_id: "order", order_version: 0 } };
let root, node, recovery, transport;
function Harness() { recovery = useOrderCreationRecovery("actor", "https://qa.invalid", true); return null; }
const flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
const storage = async (oldValue, newValue, key = KEY) => {
 await act(async () => { window.dispatchEvent(new StorageEvent("storage", { key, oldValue, newValue })); await flush(); });
};
const hide = async () => { await act(async () => { const e = new Event("pagehide"); Object.defineProperty(e, "persisted", { value: true }); window.dispatchEvent(e); await flush(); }); };
const show = async () => { await act(async () => { const e = new Event("pageshow"); Object.defineProperty(e, "persisted", { value: true }); window.dispatchEvent(e); await flush(); }); };
beforeEach(async () => {
 globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear();
 Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_k, _o, cb) => cb({}) } });
 transport = { get: jest.fn(async (url) => url.endsWith("/auth/me") ? { status: 200, data: { id: "actor", role: "admin" } } : url.endsWith("/capabilities") ? { status: 200, data: { create_recovery_enabled: true } } : { status: 202, data: { client_operation_id: ID, state: "pending", retry_after_seconds: 1 } }), post: jest.fn() };
 axios.create.mockReturnValue(transport); node = document.createElement("div"); document.body.append(node); root = createRoot(node);
 // Terminal mount avoids auto-recovery; the pending clone is introduced before suspension.
 localStorage.setItem(KEY, JSON.stringify(terminal)); sessionStorage.setItem(DRAFT, JSON.stringify(draft));
 await act(async () => root.render(<Harness />));
 // An inherited pending payload is present at suspension, like a cloned live tab.
 localStorage.setItem(KEY, JSON.stringify(record)); sessionStorage.setItem(DRAFT, JSON.stringify(draft));
 await storage(JSON.stringify(terminal), JSON.stringify(record), "unrelated");
 await hide();
});
afterEach(async () => { await act(async () => root.unmount()); node.remove(); });
async function peerAck(value = terminal) {
 localStorage.setItem(KEY, JSON.stringify(value)); await storage(JSON.stringify(record), JSON.stringify(value));
 localStorage.removeItem(KEY); await storage(JSON.stringify(value), null);
}
test("peer terminal plus ACK during suspension clears exact clone only after matching verified restore", async () => {
 await peerAck(); expect(sessionStorage.getItem(DRAFT)).toBe(JSON.stringify(draft)); expect(recovery.sessionSuspended).toBe(true);
 await show(); expect(recovery.sessionSuspended).toBe(false); expect(recovery.record).toBeNull(); expect(sessionStorage.getItem(DRAFT)).toBeNull();
 expect(transport.post).not.toHaveBeenCalled(); expect(localStorage.getItem(KEY)).toBeNull();
});

test.each(["unavailable", "foreign"])("%s auth cannot clear deferred clone; explicit matching revalidation later can", async (mode) => {
 await peerAck(); transport.get.mockImplementation(async (url) => {
 if (url.endsWith("/auth/me")) { if (mode === "unavailable") throw { response: { status: 503 } }; return { status: 200, data: { id: "foreign", role: "admin" } }; }
 return { status: 200, data: { create_recovery_enabled: true } };
 });
 await show(); expect(recovery.sessionSuspended).toBe(true); expect(sessionStorage.getItem(DRAFT)).toBe(JSON.stringify(draft));
 transport.get.mockImplementation(async (url) => url.endsWith("/auth/me") ? { status: 200, data: { id: "actor", role: "admin" } } : { status: 200, data: { create_recovery_enabled: true } });
 await act(async () => { await recovery.revalidateSession(); });
 expect(recovery.sessionSuspended).toBe(false); expect(sessionStorage.getItem(DRAFT)).toBeNull(); expect(transport.post).not.toHaveBeenCalled();
});
test.each([JSON.stringify(record), JSON.stringify({ ...terminal, actor_id: "foreign" }), "{invalid"])("nonterminal/foreign/invalid peer metadata never authorizes absent-key draft cleanup: %s", async (raw) => {
 localStorage.removeItem(KEY); await storage(raw, null); await show();
 expect(recovery.sessionSuspended).toBe(false); expect(sessionStorage.getItem(DRAFT)).toBe(JSON.stringify(draft)); expect(transport.post).not.toHaveBeenCalled();
});
test("unrelated draft identity survives validated deferred cleanup", async () => {
 const unrelated = `${KEY}:draft:123e4567-e89b-42d3-a456-426614174001`; sessionStorage.setItem(unrelated, "unrelated retained payload");
 await peerAck(); await show(); expect(sessionStorage.getItem(DRAFT)).toBeNull(); expect(sessionStorage.getItem(unrelated)).toBe("unrelated retained payload");
});
test("second suspension fences old successful auth before cleanup; fresh restore consumes retained proof", async () => {
 await peerAck(); let finish;
 transport.get.mockImplementation((url) => url.endsWith("/auth/me") ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve({ status: 200, data: { create_recovery_enabled: true } }));
 await show(); expect(typeof finish).toBe("function"); await hide();
 await act(async () => { finish({ status: 200, data: { id: "actor", role: "admin" } }); await flush(); });
 expect(recovery.sessionSuspended).toBe(true); expect(sessionStorage.getItem(DRAFT)).toBe(JSON.stringify(draft));
 transport.get.mockImplementation(async (url) => url.endsWith("/auth/me") ? { status: 200, data: { id: "actor", role: "admin" } } : { status: 200, data: { create_recovery_enabled: true } });
 await show(); expect(recovery.sessionSuspended).toBe(false); expect(sessionStorage.getItem(DRAFT)).toBeNull(); expect(transport.post).not.toHaveBeenCalled();
});

function directController(options = {}) {
 return createOrderRecovery({ actorId: "actor", api: transport, durableStorage: localStorage, draftStorage: sessionStorage,
 locks: navigator.locks, crypto: window.crypto, ...options });
}
test("failed deferred cleanup keeps controller inactive and exact draft until a successful explicit restore", async () => {
 let blocked = true;
 const storageAdapter = { getItem: (key) => sessionStorage.getItem(key), removeItem: (key) => { if (blocked) throw new Error("synthetic storage refusal"); sessionStorage.removeItem(key); }, setItem: (key, value) => sessionStorage.setItem(key, value) };
 localStorage.setItem(KEY, JSON.stringify(record)); const c = directController({ draftStorage: storageAdapter }); c.snapshot(); c.deactivate({ preserveDraft: true });
 c.rememberStorage({ key: KEY, oldValue: JSON.stringify(terminal), newValue: null }); localStorage.removeItem(KEY);
 await expect(c.restoreSession()).rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" });
 expect(sessionStorage.getItem(DRAFT)).toBe(JSON.stringify(draft)); await expect(c.capability()).rejects.toMatchObject({ code: "SESSION_CHANGED" });
 blocked = false; await c.restoreSession(); expect(sessionStorage.getItem(DRAFT)).toBeNull(); expect(transport.post).not.toHaveBeenCalled();
});
test("unobserved terminal identity is never staged for deferred deletion", async () => {
 const other = "123e4567-e89b-42d3-a456-426614174002", otherKey = `${KEY}:draft:${other}`;
 sessionStorage.setItem(otherKey, "unobserved private draft"); localStorage.setItem(KEY, JSON.stringify(record)); const c = directController(); c.snapshot(); c.deactivate({ preserveDraft: true });
 const unknown = { ...terminal, client_operation_id: other, receipt: { ...terminal.receipt, client_operation_id: other } };
 c.rememberStorage({ key: KEY, oldValue: JSON.stringify(unknown), newValue: null }); localStorage.removeItem(KEY);
 await c.restoreSession(); expect(sessionStorage.getItem(otherKey)).toBe("unobserved private draft"); expect(sessionStorage.getItem(DRAFT)).toBe(JSON.stringify(draft));
});
