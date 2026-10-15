/** @jest-environment jsdom */
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { createOrderRecovery } from './orderCreationRecovery';
import { useOrderCreationRecovery } from '../hooks/useOrderCreationRecovery';
import { AuthProvider } from '../context/AuthContext';

const ACTOR = 'qa-integration-admin-a';
const OTHER_ACTOR = 'qa-integration-admin-b';
const ID = '123e4567-e89b-42d3-a456-426614174000';
const API = 'https://qa.invalid';
const CREATE = '/api/orders/operations/create';
const LOOKUP = `${CREATE}/${ID}`;
const RESUME = `${LOOKUP}/resume`;
const CAPABILITY = '/api/orders/operations/capabilities';
const keyFor = (actor = ACTOR) => `prodelivery:order-create:v1:${encodeURIComponent(actor)}`;
const PII = ['QA Hook Customer Sentinel', '0712345678', 'QA Hook Private Street 42', 'QA Hook Notes Sentinel'];

function order() {
  return {
    restaurant_id: 'qa-restaurant', customer_name: PII[0], customer_phone: PII[1],
    customer_address: PII[2], customer_latitude: 46.57, customer_longitude: 26.91,
    items: [{ name: 'QA Item', quantity: 1, price: 50 }],
    total_amount: 55, subtotal_amount: 50, delivery_fee: 5,
    payment_type: 'CASH', source: 'S', delivery_zone_id: 'qa-zone', notes: PII[3],
  };
}

function receipt(state = 'replayed', id = ID) {
  const terminal = state === 'applied' || state === 'replayed';
  return {
    client_operation_id: id, state,
    order_id: terminal ? 'qa-created-order' : null,
    order_version: terminal ? 0 : null,
    error_code: state === 'rejected' ? 'RESTAURANT_PAUSED' : null,
    retry_after_seconds: state === 'pending' ? 1 : null,
  };
}

function record(state = null, actor = ACTOR) {
  return { version: 1, actor_id: actor, client_operation_id: ID, created_at: 1,
    receipt: state ? receipt(state) : null };
}

function response(status, data, config) {
  return { status, data, config, statusText: String(status), headers: {} };
}

function httpError(status, config, data = { detail: { code: 'QA_UNAVAILABLE' } }) {
  const error = new Error('QA HTTP fault');
  error.config = config;
  error.response = response(status, data, config);
  return error;
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function outcome(action) {
  try { return { value: await action() }; }
  catch (error) { return { error }; }
}

function memoryStorage() {
  const values = new Map();
  return {
    getItem: jest.fn((key) => values.get(key) ?? null),
    setItem: jest.fn((key, value) => values.set(key, String(value))),
    removeItem: jest.fn((key) => values.delete(key)),
    text: () => JSON.stringify([...values]),
  };
}

function locks({ delayed = false } = {}) {
  const held = new Set();
  const queued = [];
  const run = async (name, callback) => {
    if (held.has(name)) return callback(null);
    held.add(name);
    try { return await callback({ name, mode: 'exclusive' }); }
    finally { held.delete(name); }
  };
  return {
    held, queued,
    request: jest.fn((name, options, callback) => {
      expect(options).toEqual(expect.objectContaining({ ifAvailable: true }));
      if (!delayed) return run(name, callback);
      const gate = deferred();
      queued.push({ name, callback, gate });
      return gate.promise;
    }),
    releaseNext: async () => {
      const entry = queued.shift();
      expect(entry).toBeDefined();
      try { entry.gate.resolve(await run(entry.name, entry.callback)); }
      catch (error) { entry.gate.reject(error); }
      await Promise.resolve();
    },
  };
}

function controllerFixture(changes = {}) {
  const options = {
    actorId: ACTOR, durableStorage: memoryStorage(), draftStorage: memoryStorage(),
    locks: locks(), crypto: { randomUUID: jest.fn(() => ID) },
    isOnline: () => true, wait: jest.fn(async () => {}),
    api: { get: jest.fn().mockRejectedValue(httpError(503)),
      post: jest.fn().mockResolvedValue(response(201, receipt('applied'))) },
    ...changes,
  };
  return { ...options, controller: createOrderRecovery(options),
    another: (extra = {}) => createOrderRecovery({ ...options, draftStorage: memoryStorage(), ...extra }) };
}

function assertNoPII(text) {
  for (const sentinel of PII) expect(text).not.toContain(sentinel);
}

const mounted = new Set();
let adapter;
let dispatch;
let originalAdapter;
let originalHeaders;
let originalCredentials;
let originalActEnvironment;
let lockDescriptor;
let cryptoDescriptor;
let uuid;
let browserLocks;

function urlPath(config) {
  return new URL(config.url, config.baseURL || `${API}/`).pathname;
}

function wireBody(config) {
  if (typeof config.data === 'string') return JSON.parse(config.data);
  return config.data;
}

function callsFor(path, method) {
  return adapter.mock.calls.map(([config]) => config)
    .filter((config) => urlPath(config).endsWith(path) && (!method || config.method === method));
}

function defaultDispatch(config) {
  const path = urlPath(config);
  if (path.endsWith('/api/auth/me')) return response(200, { id: ACTOR, role: 'admin' }, config);
  if (path.endsWith('/api/auth/refresh')) return response(200, { token: 'qa-synthetic-token' }, config);
  if (path === CAPABILITY) return response(200, { create_recovery_enabled: true }, config);
  if (path === CREATE && config.method === 'post') {
    return response(201, receipt('applied', wireBody(config).client_operation_id), config);
  }
  throw httpError(503, config);
}

async function ticks() {
  await act(async () => {
    for (let turn = 0; turn < 20; turn += 1) await Promise.resolve();
  });
}

async function eventually(assertion) {
  let last;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try { assertion(); return; } catch (error) { last = error; }
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
  throw last;
}

async function mount(element) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const view = {
    render: async (next) => { await act(async () => { root.render(next); }); },
    unmount: () => {
      act(() => root.unmount());
      container.remove();
      mounted.delete(view);
    },
  };
  mounted.add(view);
  await view.render(element);
  return view;
}

async function mountHook({ actor = ACTOR, strict = false, online = true, token = null } = {}) {
  let current;
  function Probe(props) {
    current = useOrderCreationRecovery(props.actor, API, props.online, props.token);
    return null;
  }
  const element = (nextActor, nextOnline, nextToken) => {
    const probe = <Probe actor={nextActor} online={nextOnline} token={nextToken} />;
    return strict ? <StrictMode>{probe}</StrictMode> : probe;
  };
  const view = await mount(element(actor, online, token));
  return {
    get current() { return current; },
    unmount: view.unmount,
    rerender: async (nextActor, nextOnline = online, nextToken = token) => view.render(element(nextActor, nextOnline, nextToken)),
  };
}

async function mountAuthWithPositiveReplayControl() {
  await mount(<AuthProvider><span /></AuthProvider>);
  await ticks();
  const previous = dispatch;
  const control = '/api/qa-auth-replay-control';
  let count = 0;
  dispatch = (config) => {
    if (urlPath(config) === control) {
      count += 1;
      if (count === 1) throw httpError(401, config);
      return response(200, { ok: true }, config);
    }
    return previous(config);
  };
  await expect(axios.get(`${API}${control}`)).resolves.toEqual(expect.objectContaining({ status: 200 }));
  expect(callsFor(control, 'get')).toHaveLength(2);
  expect(callsFor('/api/auth/refresh', 'post')).toHaveLength(1);
  dispatch = previous;
  return 1;
}

describe('S2-02D independent R1-R5 integration regressions', () => {
  beforeEach(() => {
    originalActEnvironment = globalThis.IS_REACT_ACT_ENVIRONMENT;
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.clear();
    sessionStorage.clear();
    originalAdapter = axios.defaults.adapter;
    originalHeaders = { ...axios.defaults.headers.common };
    originalCredentials = axios.defaults.withCredentials;
    dispatch = defaultDispatch;
    adapter = jest.fn(async (config) => dispatch(config));
    axios.defaults.adapter = adapter;
    // Any missed instance-adapter injection must fail, never contact an endpoint.
    jest.spyOn(XMLHttpRequest.prototype, 'send').mockImplementation(() => { throw new Error('QA forbids live HTTP'); });
    browserLocks = locks();
    lockDescriptor = Object.getOwnPropertyDescriptor(navigator, 'locks');
    Object.defineProperty(navigator, 'locks', { configurable: true, value: browserLocks });
    uuid = jest.fn(() => ID);
    cryptoDescriptor = Object.getOwnPropertyDescriptor(window, 'crypto');
    Object.defineProperty(window, 'crypto', { configurable: true, value: { randomUUID: uuid } });
  });

  afterEach(async () => {
    for (const view of [...mounted]) view.unmount();
    await ticks();
    axios.defaults.adapter = originalAdapter;
    axios.defaults.headers.common = originalHeaders;
    axios.defaults.withCredentials = originalCredentials;
    if (lockDescriptor) Object.defineProperty(navigator, 'locks', lockDescriptor);
    else delete navigator.locks;
    if (cryptoDescriptor) Object.defineProperty(window, 'crypto', cryptoDescriptor);
    else delete window.crypto;
    globalThis.IS_REACT_ACT_ENVIRONMENT = originalActEnvironment;
    localStorage.clear();
    sessionStorage.clear();
    jest.restoreAllMocks();
  });

  test('R1 pending recovery uses a strictly bodyless resume, matching the bridge policy', async () => {
    const h = controllerFixture();
    h.durableStorage.setItem(keyFor(), JSON.stringify(record('pending')));
    h.api.get.mockResolvedValue(response(202, receipt('pending')));
    h.api.post.mockImplementation(async (path, body) => {
      if (body !== undefined) throw httpError(422, undefined, { detail: { code: 'INVALID_REQUEST' } });
      expect(path).toBe(RESUME);
      return response(200, receipt());
    });
    await h.controller.recover();
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.api.post.mock.calls[0][1]).toBeUndefined();
    expect(h.controller.snapshot().receipt.state).toBe('replayed');
    expect(h.durableStorage.text()).toContain(ID);
  });

  test('R1 real hook/axios adapter serializes no bytes for an initial pending resume', async () => {
    dispatch = (config) => {
      const path = urlPath(config);
      if (path === CREATE) return response(202, receipt('pending'), config);
      if (path === LOOKUP) return response(202, receipt('pending'), config);
      if (path === RESUME) {
        if (config.data != null && config.data !== '') throw httpError(422, config, { detail: { code: 'INVALID_REQUEST' } });
        return response(200, receipt(), config);
      }
      return defaultDispatch(config);
    };
    const view = await mountHook();
    await eventually(() => expect(view.current.capability.ready).toBe(true));
    await act(async () => { await view.current.submit(order()); });
    expect(callsFor(CREATE, 'post')).toHaveLength(1);
    expect(callsFor(RESUME, 'post')).toHaveLength(1);
    expect(callsFor(RESUME, 'post')[0].data == null || callsFor(RESUME, 'post')[0].data === '').toBe(true);
    expect(view.current.record.receipt.state).toBe('replayed');
    expect(uuid).toHaveBeenCalledTimes(1);
  });

  test('R1 same-ID 404 retry422 stays uncertain when the original admission may still complete', async () => {
    const h = controllerFixture();
    h.api.post.mockResolvedValueOnce(response(202, receipt('pending')))
      .mockRejectedValue(httpError(422, undefined, { detail: { code: 'INVALID_REQUEST' } }));
    h.api.get.mockRejectedValue(httpError(404));
    await outcome(() => h.controller.submit(order()));
    expect(h.api.post).toHaveBeenCalledTimes(2);
    expect(h.api.post.mock.calls[0][1]).toEqual(h.api.post.mock.calls[1][1]);
    expect(h.controller.snapshot().receipt?.state).not.toBe('rejected');
    await outcome(() => h.controller.acknowledge());
    expect(h.durableStorage.text()).toContain(ID);
  });

  test('R2 no-existing-ID legacy remains usable and holds the shared lock through completion', async () => {
    const h = controllerFixture();
    const gate = deferred();
    const postLegacy = jest.fn(() => {
      expect(h.locks.held.size).toBe(1);
      return gate.promise;
    });
    expect(typeof h.controller.submitLegacy).toBe('function');
    const pending = outcome(() => h.controller.submitLegacy(order(), postLegacy));
    await ticks();
    expect(postLegacy).toHaveBeenCalledTimes(1);
    expect(h.locks.held.size).toBe(1);
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    gate.resolve(response(201, { id: 'qa-legacy-order' }));
    await pending;
    expect(h.locks.held.size).toBe(0);
    expect(h.durableStorage.getItem(keyFor())).toBeNull();
    expect(h.api.post).not.toHaveBeenCalled();
  });

  test.each([null, 'pending', 'applied', 'replayed', 'rejected'])('R2 stale legacy selection refuses shared %s identity even without a storage event', async (state) => {
    const h = controllerFixture();
    const staleTab = h.another();
    expect(staleTab.snapshot()).toBeNull();
    const raw = JSON.stringify(record(state));
    h.durableStorage.setItem(keyFor(), raw);
    const legacy = jest.fn();
    expect(typeof staleTab.submitLegacy).toBe('function');
    await outcome(() => staleTab.submitLegacy(order(), legacy));
    expect(legacy).not.toHaveBeenCalled();
    expect(h.durableStorage.getItem(keyFor())).toBe(raw);
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
  });

  test('R2 recoverable request in tab B excludes stale legacy selection in tab A', async () => {
    const h = controllerFixture();
    const staleTab = h.another();
    const gate = deferred();
    h.api.post.mockReturnValue(gate.promise);
    const pending = outcome(() => h.controller.submit(order()));
    await ticks();
    const legacy = jest.fn();
    expect(typeof staleTab.submitLegacy).toBe('function');
    await outcome(() => staleTab.submitLegacy(order(), legacy));
    expect(legacy).not.toHaveBeenCalled();
    expect(h.api.post).toHaveBeenCalledTimes(1);
    gate.resolve(response(201, receipt('applied')));
    await pending;
  });

  test('R2 in-flight legacy selection in tab A excludes recoverable creation in tab B', async () => {
    const h = controllerFixture();
    const tabB = h.another();
    const gate = deferred();
    const legacy = jest.fn(() => gate.promise);
    expect(typeof h.controller.submitLegacy).toBe('function');
    const pending = outcome(() => h.controller.submitLegacy(order(), legacy));
    await ticks();
    await outcome(() => tabB.submit(order()));
    expect(legacy).toHaveBeenCalledTimes(1);
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    gate.resolve(response(201, { id: 'qa-legacy-order' }));
    await pending;
  });

  test('R2 storage read failure at legacy selection fails closed', async () => {
    const h = controllerFixture();
    h.durableStorage.getItem.mockImplementation(() => { throw new Error('QA storage denied'); });
    const legacy = jest.fn();
    expect(typeof h.controller.submitLegacy).toBe('function');
    await outcome(() => h.controller.submitLegacy(order(), legacy));
    expect(legacy).not.toHaveBeenCalled();
    expect(h.api.post).not.toHaveBeenCalled();
  });

  test('R4 delayed lock callback after controller deactivation cannot mint, persist or POST', async () => {
    const h = controllerFixture({ locks: locks({ delayed: true }) });
    expect(typeof h.controller.activate).toBe('function');
    expect(typeof h.controller.deactivate).toBe('function');
    h.controller.activate();
    const pending = outcome(() => h.controller.submit(order()));
    expect(h.locks.queued).toHaveLength(1);
    h.controller.deactivate();
    await h.locks.releaseNext();
    await pending;
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.durableStorage.getItem(keyFor())).toBeNull();
    assertNoPII(h.draftStorage.text());
  });

  test('R4 delayed legacy lock callback after deactivation cannot execute legacy POST', async () => {
    const h = controllerFixture({ locks: locks({ delayed: true }) });
    const legacy = jest.fn();
    expect(typeof h.controller.submitLegacy).toBe('function');
    expect(typeof h.controller.deactivate).toBe('function');
    const pending = outcome(() => h.controller.submitLegacy(order(), legacy));
    h.controller.deactivate();
    await h.locks.releaseNext();
    await pending;
    expect(legacy).not.toHaveBeenCalled();
  });

  test('R4 owner predicate changing while a lock waits also prevents unsent effects', async () => {
    let owned = true;
    const h = controllerFixture({ locks: locks({ delayed: true }), isOwnerActive: () => owned });
    const pending = outcome(() => h.controller.submit(order()));
    expect(h.locks.queued).toHaveLength(1);
    owned = false;
    await h.locks.releaseNext();
    await pending;
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    expect(h.durableStorage.getItem(keyFor())).toBeNull();
    assertNoPII(h.draftStorage.text());
  });

  test('R4 deactivation while admitted lookup is in-flight preserves ID and prevents resume POST', async () => {
    const h = controllerFixture();
    h.durableStorage.setItem(keyFor(), JSON.stringify(record('pending')));
    const gate = deferred();
    h.api.get.mockReturnValue(gate.promise);
    const pending = outcome(() => h.controller.recover());
    await ticks();
    expect(h.api.get).toHaveBeenCalledTimes(1);
    expect(typeof h.controller.deactivate).toBe('function');
    h.controller.deactivate();
    gate.resolve(response(202, receipt('pending')));
    await pending;
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.durableStorage.text()).toContain(ID);
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
  });

  test.each(['unmount', 'actor switch'])('R4 real hook %s invalidates an unsent delayed lock action', async (change) => {
    browserLocks = locks({ delayed: true });
    Object.defineProperty(navigator, 'locks', { configurable: true, value: browserLocks });
    const view = await mountHook();
    await eventually(() => expect(view.current.capability.ready).toBe(true));
    let pending;
    act(() => { pending = view.current.submit(order()); });
    expect(browserLocks.queued).toHaveLength(1);
    if (change === 'unmount') view.unmount();
    else await view.rerender(OTHER_ACTOR);
    await ticks();
    await act(async () => { await browserLocks.releaseNext(); await pending; });
    expect(callsFor(CREATE, 'post')).toHaveLength(0);
    expect(uuid).not.toHaveBeenCalled();
    expect(localStorage.getItem(keyFor())).toBeNull();
    assertNoPII(JSON.stringify({ ...sessionStorage }));
  });

  test('R4 actor switch cannot publish the old in-flight receipt into the new actor UI', async () => {
    localStorage.setItem(keyFor(), JSON.stringify(record('pending')));
    const gate = deferred();
    dispatch = (config) => urlPath(config) === LOOKUP ? gate.promise : defaultDispatch(config);
    const view = await mountHook();
    await eventually(() => expect(callsFor(LOOKUP, 'get')).toHaveLength(1));
    await view.rerender(OTHER_ACTOR);
    expect(view.current.record).toBeNull();
    await act(async () => { gate.resolve(response(200, receipt())); });
    await ticks();
    expect(view.current.record).toBeNull();
    expect(view.current.busy).toBe(false);
    expect(localStorage.getItem(keyFor())).toContain(ID);
    expect(localStorage.getItem(keyFor(OTHER_ACTOR))).toBeNull();
    expect(callsFor(CREATE, 'post')).toHaveLength(0);
    expect(uuid).not.toHaveBeenCalled();
  });

  test('R4 unmount during admitted lookup preserves identity without a later resume POST', async () => {
    localStorage.setItem(keyFor(), JSON.stringify(record('pending')));
    const gate = deferred();
    dispatch = (config) => urlPath(config) === LOOKUP ? gate.promise : defaultDispatch(config);
    const view = await mountHook();
    await eventually(() => expect(callsFor(LOOKUP, 'get')).toHaveLength(1));
    view.unmount();
    await ticks();
    await act(async () => { gate.resolve(response(202, receipt('pending'))); });
    await ticks();
    expect(localStorage.getItem(keyFor())).toContain(ID);
    expect(callsFor(RESUME, 'post')).toHaveLength(0);
    expect(callsFor(CREATE, 'post')).toHaveLength(0);
    assertNoPII(JSON.stringify({ ...sessionStorage }));
  });

  test('R3 StrictMode adopts the single in-flight automatic recovery and refreshes the current UI', async () => {
    localStorage.setItem(keyFor(), JSON.stringify(record('pending')));
    const gate = deferred();
    dispatch = (config) => urlPath(config) === LOOKUP ? gate.promise : defaultDispatch(config);
    const view = await mountHook({ strict: true });
    await eventually(() => expect(callsFor(LOOKUP, 'get')).toHaveLength(1));
    expect(JSON.parse(localStorage.getItem(keyFor())).receipt.state).toBe('pending');
    await act(async () => { gate.resolve(response(200, receipt())); });
    await eventually(() => {
      expect(view.current.record?.receipt?.state).toBe('replayed');
      expect(view.current.busy).toBe(false);
    });
    expect(view.current.error).toBe('');
    expect(callsFor(LOOKUP, 'get')).toHaveLength(1);
    expect(callsFor(RESUME, 'post')).toHaveLength(0);
    expect(browserLocks.request).toHaveBeenCalledTimes(1);
    expect(uuid).not.toHaveBeenCalled();
  });

  test('R5 real AuthProvider still replays ordinary requests; recovery GET401 never refreshes/replays', async () => {
    const beforeRefresh = await mountAuthWithPositiveReplayControl();
    localStorage.setItem(keyFor(), JSON.stringify(record('pending')));
    dispatch = (config) => {
      if (urlPath(config) === LOOKUP) {
        if (!config._retry) throw httpError(401, config);
        return response(200, receipt(), config);
      }
      return defaultDispatch(config);
    };
    const view = await mountHook();
    await eventually(() => expect(view.current.busy).toBe(false));
    expect(callsFor(LOOKUP, 'get')).toHaveLength(1);
    expect(callsFor('/api/auth/refresh', 'post')).toHaveLength(beforeRefresh);
    expect(view.current.record?.client_operation_id).toBe(ID);
    expect(view.current.record?.receipt?.state).toBe('pending');
    expect(view.current.error).not.toBe('');
    expect(callsFor(RESUME, 'post')).toHaveLength(0);
    expect(callsFor('/api/orders', 'post')).toHaveLength(0);
  });

  test('R5 pending resume401 cannot invoke global refresh or replay its POST', async () => {
    const beforeRefresh = await mountAuthWithPositiveReplayControl();
    localStorage.setItem(keyFor(), JSON.stringify(record('pending')));
    dispatch = (config) => {
      const path = urlPath(config);
      if (path === LOOKUP) return response(202, receipt('pending'), config);
      if (path === RESUME) {
        if (!config._retry) throw httpError(401, config);
        return response(200, receipt(), config);
      }
      return defaultDispatch(config);
    };
    const view = await mountHook();
    await eventually(() => expect(view.current.busy).toBe(false));
    expect(callsFor(LOOKUP, 'get')).toHaveLength(1);
    expect(callsFor(RESUME, 'post')).toHaveLength(1);
    expect(callsFor('/api/auth/refresh', 'post')).toHaveLength(beforeRefresh);
    expect(view.current.record?.receipt?.state).toBe('pending');
    expect(view.current.record?.client_operation_id).toBe(ID);
  });

  test('R5 create401 retains the intent without global auth refresh/replay', async () => {
    const beforeRefresh = await mountAuthWithPositiveReplayControl();
    dispatch = (config) => {
      if (urlPath(config) === CREATE) {
        if (!config._retry) throw httpError(401, config);
        return response(201, receipt('applied'), config);
      }
      return defaultDispatch(config);
    };
    const view = await mountHook();
    await eventually(() => expect(view.current.capability.ready).toBe(true));
    await act(async () => { await view.current.submit(order()); });
    expect(callsFor(CREATE, 'post')).toHaveLength(1);
    expect(callsFor('/api/auth/refresh', 'post')).toHaveLength(beforeRefresh);
    expect(view.current.record?.client_operation_id).toBe(ID);
    expect(view.current.record?.receipt).toBeNull();
    expect(uuid).toHaveBeenCalledTimes(1);
    assertNoPII(localStorage.getItem(keyFor()));
  });

  test('R5 capability401 is not silently refreshed into legacy-enabled readiness', async () => {
    const beforeRefresh = await mountAuthWithPositiveReplayControl();
    dispatch = (config) => {
      if (urlPath(config) === CAPABILITY) {
        if (!config._retry) throw httpError(401, config);
        return response(200, { create_recovery_enabled: false }, config);
      }
      return defaultDispatch(config);
    };
    const view = await mountHook();
    await eventually(() => expect(view.current.checkingCapability).toBe(false));
    expect(callsFor(CAPABILITY, 'get')).toHaveLength(1);
    expect(callsFor('/api/auth/refresh', 'post')).toHaveLength(beforeRefresh);
    expect(view.current.capability.ready).toBe(false);
    expect(view.current.error).not.toBe('');
  });

  test('R5 isolated transport uses the current optional token, credentials and finite timeout', async () => {
    const view = await mountHook({ token: 'qa-token-one' });
    await eventually(() => expect(view.current.capability.ready).toBe(true));
    expect(callsFor(CAPABILITY, 'get')[0].headers.Authorization).toBe('Bearer qa-token-one');
    await view.rerender(ACTOR, true, 'qa-token-two');
    await act(async () => { await view.current.verifyCapability(); });
    expect(callsFor(CAPABILITY, 'get')).toHaveLength(2);
    expect(callsFor(CAPABILITY, 'get')[1].headers.Authorization).toBe('Bearer qa-token-two');
    for (const config of callsFor(CAPABILITY, 'get')) {
      expect(config.withCredentials).toBe(true);
      expect(config.timeout).toBe(15000);
    }
  });

  test('R7 token A to B to null omits inherited ambient bearer from serialized adapter headers', async () => {
    axios.defaults.headers.common.Authorization = 'Bearer QA-A';
    const view = await mountHook({ token: 'QA-A' });
    await eventually(() => expect(view.current.capability.ready).toBe(true));
    expect(callsFor(CAPABILITY, 'get')[0].headers.get('Authorization')).toBe('Bearer QA-A');
    await view.rerender(ACTOR, true, 'QA-B');
    await act(async () => { await view.current.verifyCapability(); });
    expect(callsFor(CAPABILITY, 'get')[1].headers.get('Authorization')).toBe('Bearer QA-B');
    await view.rerender(ACTOR, true, null);
    await act(async () => { await view.current.verifyCapability(); });
    const requests = callsFor(CAPABILITY, 'get');
    expect(requests).toHaveLength(3);
    const serialized = requests[2].headers.toJSON();
    expect(Object.keys(serialized).some((name) => name.toLowerCase() === 'authorization')).toBe(false);
    expect(JSON.stringify(serialized)).not.toContain('QA-A');
    expect(JSON.stringify(serialized)).not.toContain('QA-B');
    for (const config of requests) {
      expect(config.withCredentials).toBe(true);
      expect(config.timeout).toBe(15000);
    }
    expect(axios.defaults.headers.common.Authorization).toBe('Bearer QA-A');
  });
});
