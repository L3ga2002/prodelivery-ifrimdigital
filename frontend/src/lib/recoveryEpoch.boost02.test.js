// BOOST02 direct-controller adversarial checks. Storage/Web Locks/API are test fakes.
// A queued suspend runs after request-wrapper owner validation and before its caller resumes.
// These are finite unit probes, not real BFCache, browser locks, authentication, or Mongo proof.
import { createOrderRecovery } from './orderCreationRecovery';
import { createOrderEditingRecovery } from './orderEditingRecovery';
import { createOrderAssignmentRecovery } from './orderAssignmentRecovery';

const ACTOR = 'boost02-epoch-actor';
const OTHER = 'boost02-epoch-other';
const UUID = '9f005efa-d12d-4eb2-87bd-b90d73e8abcd';
const ORDER = 'boost02-epoch-order';
const DRIVER = 'boost02-epoch-driver';
const clone = (value) => JSON.parse(JSON.stringify(value));
const order = () => ({ id: ORDER, restaurant_id: 'boost02-restaurant', order_version: 7,
  status: 'NEW', preparation_status: 'NEW', driver_id: null, customer_name: 'Synthetic Epoch Customer',
  customer_phone: '0700000022', customer_address: 'Synthetic Epoch Address',
  customer_latitude: null, customer_longitude: null, notes: 'Synthetic Epoch Original Note' });
const creation = () => ({ restaurant_id: 'boost02-restaurant', customer_name: 'Synthetic Epoch Customer',
  customer_phone: '0700000022', customer_address: 'Synthetic Epoch Address', total_amount: 25,
  items: [], payment_type: 'CASH', source: 'qa', notes: 'Synthetic Epoch Original Note' });

function storage() {
  const values = new Map();
  return { getItem: jest.fn((key) => values.get(key) ?? null),
    setItem: jest.fn((key, value) => values.set(key, String(value))),
    removeItem: jest.fn((key) => values.delete(key)), seed: (key, value) => values.set(key, JSON.stringify(value)),
    entries: () => [...values].sort(([a], [b]) => a.localeCompare(b)), text: () => JSON.stringify([...values]) };
}
const response = (kind, state = 'pending') => ({
  status: state === 'pending' ? 202 : kind === 'create' && state === 'applied' ? 201 : 200,
  headers: state === 'pending' ? { 'retry-after': '1' } : {},
  data: { client_operation_id: UUID, state,
    order_id: state === 'pending' ? null : ORDER,
    order_version: state === 'pending' ? null : kind === 'create' ? 0 : 8,
    error_code: null, retry_after_seconds: state === 'pending' ? 1 : null },
});
const keyFor = (kind, actor = ACTOR) => `prodelivery:order-${kind}:v1:${encodeURIComponent(actor)}`;
const recordFor = (kind, actor = ACTOR, state = null) => kind === 'create'
  ? { version: 1, actor_id: actor, client_operation_id: UUID, created_at: 100,
    receipt: state ? response(kind, state).data : null }
  : { actor_id: actor, order_id: ORDER, expected_order_version: 7, client_operation_id: UUID,
    ...(kind === 'assign' ? { driver_id: DRIVER } : {}), receipt: state ? response(kind, state).data : null };
const factories = { create: createOrderRecovery, edit: createOrderEditingRecovery, assign: createOrderAssignmentRecovery };

function harness(kind, actor = ACTOR, shared = {}) {
  const durableStorage = shared.durableStorage || storage();
  const draftStorage = shared.draftStorage || storage();
  const events = [], state = { arm: false, tripped: false, restoration: null, beforeGap: null };
  const crypto = { randomUUID: jest.fn(() => UUID) };
  const locks = { request: jest.fn(async (_key, options, callback) => {
    expect(options).toEqual({ ifAvailable: true }); return callback({ mode: 'exclusive' });
  }) };
  const api = {
    get: jest.fn(async (path) => {
      if (path === '/api/auth/me') { events.push('auth-read'); return { status: 200, data: { id: actor, role: 'admin', account_disabled: false } }; }
      if (path.endsWith('/capabilities')) return { status: 200, data: { edit_recovery_enabled: true, assign_recovery_enabled: true } };
      return response(kind);
    }),
    post: jest.fn(async () => response(kind, 'applied')),
  };
  let controller;
  const options = { actorId: actor, api, durableStorage, draftStorage, locks, crypto,
    isOnline: () => true, wait: jest.fn(async () => {}), isOwnerActive: () => {
      if (state.arm && !state.tripped) {
        state.tripped = true;
        state.beforeGap = { durable: durableStorage.entries(), draft: draftStorage.entries() };
        events.push('request-wrapper-owner-validated');
        queueMicrotask(() => {
          events.push('suspend-in-wrapper-caller-gap');
          controller.deactivate({ preserveDraft: true });
          state.restoration = controller.restoreSession().then(() => events.push('restored-actor-verified'));
        });
      }
      return true;
    } };
  controller = factories[kind](options);
  return { kind, actor, controller, options, api, durableStorage, draftStorage, crypto, events, state };
}
function seed(h, state = null) {
  h.durableStorage.seed(keyFor(h.kind, h.actor), recordFor(h.kind, h.actor, state));
  if (h.kind === 'create') h.draftStorage.seed(`${keyFor(h.kind, h.actor)}:draft:${UUID}`,
    { actor_id: h.actor, client_operation_id: UUID, order: creation() });
  if (h.kind === 'edit') h.draftStorage.seed(`${keyFor(h.kind, h.actor)}:draft:${UUID}`,
    { actor_id: h.actor, order_id: ORDER, expected_order_version: 7, client_operation_id: UUID,
      changes: { notes: 'Synthetic Epoch Exact Correction' } });
}
function armResponse(h, value) { h.state.arm = true; return value; }
function submit(h) {
  if (h.kind === 'create') return h.controller.submit(creation());
  if (h.kind === 'edit') return h.controller.submit({ order: order(), changes: { notes: 'Synthetic Epoch Exact Correction' } });
  return h.controller.submit({ order: order(), driverId: DRIVER,
    driver: { id: DRIVER, is_active: true, driver_status: 'active', operational_status: 'active' } });
}
async function gapOutcome(h, promise) {
  let caught;
  try { await promise; } catch (error) { caught = error; h.events.push('old-caller-rejected'); }
  // Finite microtask flushing only; no while loops or live timers.
  for (let index = 0; index < 12; index += 1) await Promise.resolve();
  expect(h.state.tripped).toBe(true);
  expect(h.state.restoration).not.toBeNull();
  await h.state.restoration;
  expect(caught).toMatchObject({ code: 'SESSION_CHANGED' });
  expect(h.events.indexOf('request-wrapper-owner-validated')).toBeLessThan(h.events.indexOf('suspend-in-wrapper-caller-gap'));
  expect(h.events.indexOf('suspend-in-wrapper-caller-gap')).toBeLessThan(h.events.indexOf('old-caller-rejected'));
  expect(h.durableStorage.entries()).toEqual(h.state.beforeGap.durable);
  expect(h.draftStorage.entries()).toEqual(h.state.beforeGap.draft);
  return caught;
}

describe('BOOST02 lifecycle epoch at wrapper/caller microtask gap', () => {
  test.each(['create', 'edit', 'assign'])('%s pending lookup cannot persist or resume after suspend', async (kind) => {
    const h = harness(kind); seed(h);
    h.api.get.mockImplementation(async (path) => path === '/api/auth/me'
      ? { status: 200, data: { id: ACTOR, role: 'admin' } }
      : armResponse(h, response(kind)));
    await gapOutcome(h, h.controller.recover());
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    expect(h.durableStorage.setItem).not.toHaveBeenCalled();
    expect(h.draftStorage.removeItem).not.toHaveBeenCalled();
  });

  test.each(['create', 'edit', 'assign'])('%s applied POST cannot publish receipt or clear exact draft after suspend', async (kind) => {
    const h = harness(kind);
    h.api.post.mockImplementation(async () => armResponse(h, response(kind, 'applied')));
    await gapOutcome(h, submit(h));
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
    expect(JSON.parse(h.durableStorage.getItem(keyFor(kind))).receipt).toBeNull();
    expect(h.durableStorage.removeItem).not.toHaveBeenCalled();
    expect(h.draftStorage.removeItem).not.toHaveBeenCalled();
    expect(h.durableStorage.text()).not.toMatch(/Synthetic Epoch Customer|Synthetic Epoch Address|Exact Correction/);
  });

  test.each(['edit', 'assign'])('%s capability continuation cannot create UUID or persist after suspend', async (kind) => {
    const h = harness(kind);
    h.api.get.mockImplementation(async (path) => path === '/api/auth/me'
      ? { status: 200, data: { id: ACTOR, role: 'admin' } }
      : armResponse(h, { status: 200, data: { edit_recovery_enabled: true, assign_recovery_enabled: true } }));
    await gapOutcome(h, submit(h));
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.durableStorage.setItem).not.toHaveBeenCalled();
    expect(h.draftStorage.setItem).not.toHaveBeenCalled();
    expect(h.durableStorage.entries()).toEqual([]);
  });
});

describe('BOOST02 revalidation roles and actor-scoped UUID', () => {
  test('creation revalidation allows the original restaurant actor before local acknowledgment', async () => {
    const h = harness('create'); seed(h, 'applied');
    h.controller.deactivate({ preserveDraft: true });
    h.api.get.mockResolvedValue({ status: 200, data: { id: ACTOR, role: 'restaurant', restaurant_id: 'boost02-restaurant' } });
    await h.controller.restoreSession();
    await h.controller.acknowledge();
    expect(h.durableStorage.getItem(keyFor('create'))).toBeNull();
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
  });

  test.each(['edit', 'assign'])('%s restaurant role cannot reactivate, acknowledge, or admit', async (kind) => {
    const h = harness(kind); seed(h, 'applied');
    const durable = h.durableStorage.entries(), draft = h.draftStorage.entries();
    h.controller.deactivate({ preserveDraft: true });
    h.api.get.mockResolvedValue({ status: 200, data: { id: ACTOR, role: 'restaurant' } });
    await expect(h.controller.restoreSession()).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
    await expect(h.controller.acknowledge()).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
    await expect(submit(h)).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
    expect(h.durableStorage.entries()).toEqual(durable);
    expect(h.draftStorage.entries()).toEqual(draft);
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.crypto.randomUUID).not.toHaveBeenCalled();
  });

  test.each(['create', 'edit', 'assign'])('%s same UUID in another actor key is independently acknowledged', async (kind) => {
    const first = harness(kind), other = harness(kind, OTHER, first); seed(first, 'applied'); seed(other, 'applied');
    const firstRaw = first.durableStorage.getItem(keyFor(kind, ACTOR));
    const firstDraft = first.draftStorage.getItem(`${keyFor(kind, ACTOR)}:draft:${UUID}`);
    other.controller.deactivate({ preserveDraft: true });
    await other.controller.restoreSession();
    await other.controller.acknowledge();
    expect(first.durableStorage.getItem(keyFor(kind, ACTOR))).toBe(firstRaw);
    expect(first.draftStorage.getItem(`${keyFor(kind, ACTOR)}:draft:${UUID}`)).toBe(firstDraft);
    expect(first.durableStorage.getItem(keyFor(kind, OTHER))).toBeNull();
    expect(other.api.post).not.toHaveBeenCalled();
    expect(other.crypto.randomUUID).not.toHaveBeenCalled();
  });
});
