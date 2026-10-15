/** @jest-environment jsdom */
import { act, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { AuthProvider, useAuth } from "./AuthContext";

const A = { id: "synthetic-a", role: "admin", name: "A" };
const B = { id: "synthetic-b", role: "admin", name: "B" };
const path = (config) => config.url.slice(config.url.indexOf("/api/"));
const response = (config, data) => ({ config, data, status: 200, headers: {}, statusText: "OK" });
const fault = (config) => Object.assign(new Error("Synthetic401"), { config, response: { config, status: 401, data: {} } });
function gate() {
  let enter, resolve, reject;
  const entered = new Promise((yes) => { enter = yes; });
  const result = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { entered, enter, resolve, reject, result };
}
const bounded = (promise) => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error("Finite barrier expired")), 1500);
  promise.then((value) => { clearTimeout(timer); resolve(value); }, (error) => { clearTimeout(timer); reject(error); });
});
const outcome = (promise) => promise.then((value) => ({ value }), (error) => ({ error }));
let current, root, container, adapter, dispatch, previousAdapter, previousHeaders, previousAct;
const calls = (name) => adapter.mock.calls.map(([config]) => config).filter((config) => path(config) === name);
const normal = (config) => {
  switch (path(config)) {
    case "/api/auth/me": return response(config, A);
    case "/api/auth/login": return response(config, { user: B, token: "token-b" });
    case "/api/auth/refresh": return response(config, { user: A, token: "token-refreshed" });
    case "/api/auth/logout": return response(config, {});
    default: return response(config, { ok: true });
  }
};
function Probe() { current = useAuth(); return <span>{current.user?.id || "anonymous"}:{String(current.isLoading)}</span>; }
const mount = async (strict = false) => {
  await act(async () => root.render(strict ? <StrictMode><AuthProvider><Probe /></AuthProvider></StrictMode> : <AuthProvider><Probe /></AuthProvider>));
};
const enter = async (barrier) => { await act(async () => bounded(barrier.entered)); };
const release = async (barrier, config, value, fail = false) => {
  await act(async () => { if (fail) barrier.reject(fault(config)); else barrier.resolve(response(config, value)); });
};

beforeEach(() => {
  previousAdapter = axios.defaults.adapter;
  previousHeaders = { ...axios.defaults.headers.common };
  previousAct = globalThis.IS_REACT_ACT_ENVIRONMENT;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  delete axios.defaults.headers.common.Authorization;
  dispatch = normal;
  adapter = jest.fn((config) => Promise.resolve().then(() => dispatch(config)));
  axios.defaults.adapter = adapter;
  jest.spyOn(XMLHttpRequest.prototype, "send").mockImplementation(() => { throw new Error("Live HTTP forbidden"); });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount()); container.remove();
  axios.defaults.adapter = previousAdapter; axios.defaults.headers.common = previousHeaders;
  globalThis.IS_REACT_ACT_ENVIRONMENT = previousAct; jest.restoreAllMocks();
});

test.each([false, true])("init refresh pending then login: cookie exchanges serialize, old success/failure cannot replace B (%s)", async (fail) => {
  const barrier = gate(); let oldConfig;
  dispatch = (config) => {
    if (path(config) === "/api/auth/me") throw fault(config);
    if (path(config) === "/api/auth/refresh") { oldConfig = config; barrier.enter(); return barrier.result; }
    return normal(config);
  };
  await mount(); await enter(barrier);
  let login;
  await act(async () => { login = outcome(current.login("synthetic-b", "synthetic-only")); });
  expect(calls("/api/auth/login")).toHaveLength(0);
  await release(barrier, oldConfig, { token: "old-token", user: A }, fail);
  await act(async () => expect((await bounded(login)).value.success).toBe(true));
  expect(current.user).toEqual(B); expect(current.token).toBe("token-b"); expect(current.isLoading).toBe(false);
  expect(axios.defaults.headers.common.Authorization).toBe("Bearer token-b");
  expect(calls("/api/auth/me")).toHaveLength(1);
});

test("init GET A late after login B is aborted and never published", async () => {
  const barrier = gate(); let config;
  dispatch = (next) => { if (path(next) === "/api/auth/me") { config = next; barrier.enter(); return barrier.result; } return normal(next); };
  await mount(); await enter(barrier);
  await act(async () => expect((await current.login("B", "synthetic-only")).success).toBe(true));
  expect(config.signal.aborted).toBe(true);
  await release(barrier, config, A);
  expect(current.user).toEqual(B); expect(current.isLoading).toBe(false); expect(calls("/api/auth/refresh")).toHaveLength(0);
});

test("init refresh success after logout cannot resurrect A or issue followup me", async () => {
  const barrier = gate(); let config;
  dispatch = (next) => { if (path(next) === "/api/auth/me") throw fault(next); if (path(next) === "/api/auth/refresh") { config = next; barrier.enter(); return barrier.result; } return normal(next); };
  await mount(); await enter(barrier);
  let logout; await act(async () => { logout = outcome(current.logout()); });
  expect(current.user).toBeNull(); expect(calls("/api/auth/logout")).toHaveLength(0);
  await release(barrier, config, { user: A, token: "old-token" });
  await act(async () => bounded(logout));
  expect(current.user).toBeNull(); expect(current.token).toBeNull(); expect(calls("/api/auth/me")).toHaveLength(1);
  expect(axios.defaults.headers.common.Authorization).toBeUndefined(); expect(calls("/api/auth/logout")).toHaveLength(1);
});

test("ordinary A401 arriving after login B causes zero refresh and zero replay", async () => {
  await mount(); const barrier = gate(); let config;
  dispatch = (next) => { if (path(next) === "/api/old") { config = next; barrier.enter(); return barrier.result; } return normal(next); };
  let old; await act(async () => { old = outcome(axios.get("/api/old")); }); await enter(barrier);
  await act(async () => current.login("B", "synthetic-only")); await release(barrier, config, null, true);
  expect((await bounded(old)).error).toBeDefined(); expect(calls("/api/old")).toHaveLength(1); expect(calls("/api/auth/refresh")).toHaveLength(0);
  expect(current.user).toEqual(B); expect(current.token).toBe("token-b");
});

test.each([false, true])("ordinary refresh A pending then login B: no A replay/clear/header publication (%s)", async (fail) => {
  await mount(); const barrier = gate(); let config;
  dispatch = (next) => { if (path(next) === "/api/old") throw fault(next); if (path(next) === "/api/auth/refresh") { config = next; barrier.enter(); return barrier.result; } return normal(next); };
  let old, login; await act(async () => { old = outcome(axios.get("/api/old")); }); await enter(barrier);
  await act(async () => { login = outcome(current.login("B", "synthetic-only")); });
  expect(calls("/api/auth/login")).toHaveLength(0);
  await release(barrier, config, { user: A, token: "old-refresh" }, fail);
  await act(async () => bounded(login)); expect((await bounded(old)).error).toBeDefined();
  expect(calls("/api/old")).toHaveLength(1); expect(current.user).toEqual(B); expect(current.token).toBe("token-b");
  expect(axios.defaults.headers.common.Authorization).toBe("Bearer token-b");
});

test("two current401 share one refresh and each replay uses refreshed Bearer", async () => {
  await mount(); const barrier = gate(); let config; const seen = new Set();
  dispatch = (next) => {
    if (path(next) === "/api/auth/refresh") { config = next; barrier.enter(); return barrier.result; }
    if (path(next).startsWith("/api/control")) { if (!seen.has(path(next))) { seen.add(path(next)); throw fault(next); } expect(next.headers.Authorization).toBe("Bearer token-refreshed"); return response(next, { ok: true }); }
    return normal(next);
  };
  let first, second; await act(async () => { first = outcome(axios.get("/api/control1", { headers: { Authorization: "Bearer expired" } })); second = outcome(axios.get("/api/control2", { headers: { Authorization: "Bearer expired" } })); });
  await enter(barrier); expect(calls("/api/auth/refresh")).toHaveLength(1);
  await release(barrier, config, { user: A, token: "token-refreshed" });
  expect((await bounded(first)).value.status).toBe(200); expect((await bounded(second)).value.status).toBe(200);
  expect(current.user).toEqual(A); expect(current.token).toBe("token-refreshed");
  expect(calls("/api/control1")).toHaveLength(2); expect(calls("/api/control2")).toHaveLength(2);
});

test("refresh with a different cookie actor clears locally and never replays A request", async () => {
  await mount(); dispatch = (config) => { if (path(config) === "/api/old") throw fault(config); if (path(config) === "/api/auth/refresh") return response(config, { user: B, token: "token-b" }); return normal(config); };
  let result; await act(async () => { result = await outcome(axios.get("/api/old")); });
  expect(result.error).toBeDefined(); expect(current.user).toBeNull(); expect(calls("/api/old")).toHaveLength(1);
});

test("logout A finishes before queued login B and never clears B", async () => {
  await mount(); const barrier = gate(); let config;
  dispatch = (next) => { if (path(next) === "/api/auth/logout") { config = next; barrier.enter(); return barrier.result; } return normal(next); };
  let logout, login; await act(async () => { logout = outcome(current.logout()); }); await enter(barrier);
  expect(current.user).toBeNull(); await act(async () => { login = outcome(current.login("B", "synthetic-only")); });
  expect(calls("/api/auth/login")).toHaveLength(0); await release(barrier, config, {});
  await act(async () => { await bounded(logout); expect((await bounded(login)).value.success).toBe(true); });
  expect(current.user).toEqual(B); expect(axios.defaults.headers.common.Authorization).toBe("Bearer token-b");
});

test("late login A after logout returns no success and cannot authenticate", async () => {
  await mount(); const barrier = gate(); let config;
  dispatch = (next) => { if (path(next) === "/api/auth/login") { config = next; barrier.enter(); return barrier.result; } return normal(next); };
  let login, logout; await act(async () => { login = outcome(current.login("A", "synthetic-only")); }); await enter(barrier);
  await act(async () => { logout = outcome(current.logout()); });
  expect(current.user).toBeNull(); await release(barrier, config, { user: A, token: "token-a" });
  await act(async () => { expect((await bounded(login)).value.success).toBe(false); await bounded(logout); });
  expect(current.user).toBeNull(); expect(current.token).toBeNull(); expect(axios.defaults.headers.common.Authorization).toBeUndefined();
});

test("ordinary A success late after login B is rejected", async () => {
  await mount(); const barrier = gate(); let config;
  dispatch = (next) => { if (path(next) === "/api/private") { config = next; barrier.enter(); return barrier.result; } return normal(next); };
  let old; await act(async () => { old = outcome(axios.get("/api/private")); }); await enter(barrier);
  await act(async () => current.login("B", "synthetic-only")); await release(barrier, config, { private: "A-only" });
  expect((await bounded(old)).error).toBeDefined(); expect(current.user).toEqual(B);
});

test("GET dispatched during login transition cannot publish old cookie A after B; B control succeeds", async () => {
  await mount(); const loginGate = gate(), privateGate = gate(); let loginConfig, privateConfig;
  dispatch = (config) => {
    if (path(config) === "/api/auth/login") { loginConfig = config; loginGate.enter(); return loginGate.result; }
    if (path(config) === "/api/private") { privateConfig = config; privateGate.enter(); return privateGate.result; }
    return normal(config);
  };
  let login, old;
  await act(async () => { login = outcome(current.login("B", "synthetic-only")); }); await enter(loginGate);
  await act(async () => { old = outcome(axios.get("/api/private")); }); await enter(privateGate);
  expect(privateConfig._authSessionActor).toBeNull();
  await release(loginGate, loginConfig, { user: B, token: "token-b" }); await act(async () => bounded(login));
  await release(privateGate, privateConfig, { private: "A-only" });
  expect(axios.isCancel((await bounded(old)).error)).toBe(true);
  await act(async () => expect((await axios.get("/api/valid-b")).status).toBe(200)); expect(current.user).toEqual(B);
});

test("GET dispatched before init completes cannot publish old data after cookie actor initialization", async () => {
  const me = gate(), privateGate = gate(); let meConfig, privateConfig;
  dispatch = (config) => {
    if (path(config) === "/api/auth/me") { meConfig = config; me.enter(); return me.result; }
    if (path(config) === "/api/private") { privateConfig = config; privateGate.enter(); return privateGate.result; }
    return normal(config);
  };
  await mount(); await enter(me); let old;
  await act(async () => { old = outcome(axios.get("/api/private")); }); await enter(privateGate);
  await release(me, meConfig, B); expect(current.user).toEqual(B);
  await release(privateGate, privateConfig, { private: "A-only" }); expect(axios.isCancel((await bounded(old)).error)).toBe(true);
});

test.each([403, 500, null, 401])("old ordinary error %s after B is sanitized cancellation, including retried401", async (status) => {
  await mount(); const barrier = gate(); let config;
  dispatch = (next) => { if (path(next) === "/api/private") { config = next; barrier.enter(); return barrier.result; } return normal(next); };
  let old; await act(async () => { old = outcome(axios.get("/api/private", { _retry: status === 401 })); }); await enter(barrier);
  await act(async () => current.login("B", "synthetic-only"));
  await act(async () => { barrier.reject(Object.assign(new Error("Private old actor message"), { config, response: status ? { status, data: { detail: "A-only" } } : undefined })); });
  const error = (await bounded(old)).error; expect(axios.isCancel(error)).toBe(true); expect(error.message).not.toContain("Private"); expect(error.response).toBeUndefined();
  expect(current.user).toEqual(B); expect(calls("/api/auth/refresh")).toHaveLength(0); expect(calls("/api/private")).toHaveLength(1);
});

test("StrictMode old init GET cannot overwrite current cookie init", async () => {
  await mount(true); expect(current.user).toEqual(A); expect(current.isLoading).toBe(false);
  expect(calls("/api/auth/me")).toHaveLength(1); expect(calls("/api/auth/refresh")).toHaveLength(0);
});

test("provider unmount during refresh rejects retired request without Bearer publication", async () => {
  await mount(); const barrier = gate(); let config;
  dispatch = (next) => { if (path(next) === "/api/old") throw fault(next); if (path(next) === "/api/auth/refresh") { config = next; barrier.enter(); return barrier.result; } return normal(next); };
  let old; await act(async () => { old = outcome(axios.get("/api/old")); }); await enter(barrier);
  await act(async () => root.render(null)); await release(barrier, config, { user: A, token: "retired-token" });
  expect((await bounded(old)).error).toBeDefined(); expect(calls("/api/old")).toHaveLength(1);
  expect(axios.defaults.headers.common.Authorization).not.toBe("Bearer retired-token");
});
