import { createOrderAssignmentRecovery, isOrderAssignable, isAssignmentDriverAvailable,
  validateAssignmentReceipt, hasAssignmentRevision, validAssignmentDate, ASSIGN_REQUEST_TIMEOUT_MS, MAX_ASSIGN_RECOVERY_READS } from './orderAssignmentRecovery';

const ID = '123e4567-e89b-42d3-a456-426614174000';
const NEXT = '123e4567-e89b-42d3-a456-426614174001';
const KEY = 'prodelivery:order-assign:v1:admin';
const CAP = '/api/orders/operations/assign/capabilities';
const BASE = '/api/orders/operations/assign/order';
const order = (extra = {}) => ({ id: 'order', restaurant_id: 'restaurant', order_version: 4, status: 'NEW',
  preparation_status: 'NEW', driver_id: null, customer_name: 'Customer Secret Sentinel', notes: 'Private Notes Sentinel', ...extra });
const record = (receipt = null) => ({ actor_id: 'admin', order_id: 'order', client_operation_id: ID,
  expected_order_version: 4, driver_id: 'driver', receipt });
const receipt = (state = 'applied', extra = {}) => ({ client_operation_id: ID, state,
  order_id: ['applied', 'replayed'].includes(state) ? 'order' : null,
  order_version: ['applied', 'replayed'].includes(state) ? 5 : null,
  error_code: state === 'rejected' ? 'ORDER_VERSION_CONFLICT' : null,
  retry_after_seconds: state === 'pending' ? 1 : null, ...extra });
const response = (r = receipt()) => ({ status: r.state === 'pending' ? 202 : r.state === 'rejected' ? 409 : 200,
  data: r, headers: r.state === 'pending' ? { 'retry-after': '1' } : {} });
const missing = { response: { status: 404, data: { detail: { code: 'OPERATION_NOT_FOUND' } } } };
const storage = () => {
  const map = new Map();
  return { getItem: jest.fn((k) => map.get(k) ?? null), setItem: jest.fn((k, v) => map.set(k, v)),
    removeItem: jest.fn((k) => map.delete(k)), text: () => JSON.stringify([...map]) };
};
const harness = (extra = {}) => {
  const options = { actorId: 'admin', durableStorage: storage(), locks: { request: jest.fn(async (_k, _o, cb) => cb({})) },
    crypto: { randomUUID: jest.fn().mockReturnValueOnce(ID).mockReturnValue(NEXT) }, wait: jest.fn(async () => {}),
    api: { get: jest.fn(async (path) => path === CAP ? { status: 200, data: { assign_recovery_enabled: true } } :
      path === '/api/auth/me' ? { status: 200, data: { id: 'admin', role: 'admin' } } : response(receipt('replayed'))),
      post: jest.fn(async () => response()), put: jest.fn(async () => ({ status: 200, data: { message: 'assigned' } })) }, ...extra };
  return { ...options, controller: createOrderAssignmentRecovery(options) };
};
const availableDriver = (extra = {}) => ({ id: 'driver', is_active: true, driver_status: 'active', operational_status: 'active', ...extra });
const command = (extra = {}) => ({ order: order(), driverId: 'driver', driver: availableDriver({ id: extra.driverId ?? 'driver' }), ...extra });
const legacy = () => { const value = order(); delete value.order_version; return value; };
const unresolved = async (h) => {
  h.api.post.mockRejectedValue(new Error('lost ACK'));
  h.api.get.mockImplementation(async (path) => { if (path === CAP) return { status: 200, data: { assign_recovery_enabled: true } }; throw new Error('offline'); });
  await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'RECOVERY_UNAVAILABLE' });
};

describe('assignment eligibility and safe business revision', () => {
  test.each([null, undefined, true, false, '4', 4.1, -1, NaN, Infinity, Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER + 1])('present malformed revision %s is not legacy', (value) => {
    const o = order({ order_version: value }); expect(hasAssignmentRevision(o)).toBe(true); expect(isOrderAssignable(o)).toBe(false);
  });
  test('creation receipt is not promoted into an absent business revision', async () => {
    const h = harness(); const o = legacy(); o.creation_receipt = { order_version: 0 };
    expect(hasAssignmentRevision(o)).toBe(false);
    await expect(h.controller.submit(command({ order: o }))).rejects.toMatchObject({ code: 'ORDER_VERSION_REQUIRED' });
    expect(h.api.post).not.toHaveBeenCalled(); expect(h.crypto.randomUUID).not.toHaveBeenCalled();
  });
  test.each(['NEW', 'PREPARING', 'READY'])('unassigned %s remains eligible', (status) => expect(isOrderAssignable(order({ status, preparation_status: status }))).toBe(true));
  test('pre-accept ASSIGNED reassign and optional preparation state', () => {
    const assigned = { status: 'ASSIGNED', driver_id: 'old', assigned_at: '2026-10-07T10:00:00Z', preparation_status: 'READY' };
    expect(isOrderAssignable(order(assigned))).toBe(true);
    expect(isOrderAssignable(order({ ...assigned, preparation_status: null }))).toBe(true);
    expect(isOrderAssignable(order({ preparation_status: null }))).toBe(true);
  });
  test.each(['ACCEPTED', 'PICKED_UP', 'DELIVERED', 'CANCELLED', 'UNKNOWN'])('%s refuses custody transfer', (status) => expect(isOrderAssignable(order({ status }))).toBe(false));
  test.each([{ driver_id: '' }, { driver_name: 'orphan' }, { assigned_at: false }, { accepted_at: '' }, { picked_up_at: 'x' },
    { cancelled_by: false }, { cancellation_reason: '' }, { preparation_status: 'READY' }, { preparation_status: [] },
    { preparation_time: true }, { preparation_time: 0 }, { preparation_estimated_seconds: 14401 }, { preparation_delay_seconds: -1 },
    { preparation_due_at: 'bad' }, { preparation_started_at: '2026-10-07T10:00:00Z' }, { audit_trail: {} }, { audit_trail: [null] },
    { status: 'ASSIGNED', driver_id: 'old', assigned_at: 'bad' }, { restaurant_id: ' ' }])('malformed snapshot %j fails closed', (extra) => expect(isOrderAssignable(order(extra))).toBe(false));
  const multiFields = ['current_order_ids', 'active_order_ids', 'assigned_order_ids', 'reserved_order_ids', 'order_ids', 'assignments',
    'assignment_ids', 'active_assignments', 'reserved_assignments', 'current_assignment_id', 'assignment_id', 'dispatch_version', 'route_version', 'active_count', 'reserved_count'];
  test.each(multiFields)('unknown %s representation blocks order and driver', (field) => {
    expect(isOrderAssignable(order({ [field]: null }))).toBe(false);
    expect(isAssignmentDriverAvailable({ id: 'driver', is_active: true, operational_status: 'active', [field]: [] })).toBe(false);
  });
  test.each([{ is_active: false }, { is_active: 1 }, { operational_status: 'break' }, { operational_status: 'offline' },
    { driver_status: 'offline' }, { current_order_id: '' }, { current_order_id: 'other' }, { account_disabled: true }, { account_disabled: 'false' },
    { break_started_at: false }, { driver_status: 'break', break_until: '2999-10-07T10:00:00Z' }, { break_until: '2020-01-01T12:00:00' }])('unavailable driver %j', (extra) => expect(isAssignmentDriverAvailable({ id: 'driver', is_active: true, operational_status: 'active', ...extra })).toBe(false));
  test('expired pause metadata is preserved without hiding resumed active drivers', () => {
    expect(isAssignmentDriverAvailable({ id: 'driver', is_active: true, driver_status: 'active', operational_status: 'active',
      break_started_at: '2020-01-01T10:00:00Z', break_until: '2020-01-01T12:00:00Z' })).toBe(true);
  });
});

describe('strict assignment receipts', () => {
  test.each([{ client_operation_id: NEXT }, { order_id: 'foreign' }, { order_version: 0 }, { order_version: 4 }, { order_version: 6 },
    { order_version: true }, { error_code: 'NO_CHANGES' }, { retry_after_seconds: 1 }, { customer_name: 'private' }])('unconfirmed success %j', (extra) => expect(() => validateAssignmentReceipt(response(receipt('applied', extra)), record())).toThrow());
  test.each([{ state: 'unknown' }, { order_id: 'order' }, { order_version: 5 }, { error_code: 'NO_CHANGES' }, { retry_after_seconds: 0 },
    { retry_after_seconds: 61 }, { retry_after_seconds: true }])('malformed pending %j', (extra) => expect(() => validateAssignmentReceipt(response(receipt('pending', extra)), record())).toThrow());
  test.each(['applied', 'replayed', 'pending', 'rejected'])('HTTP mismatch for %s', (state) => expect(() => validateAssignmentReceipt({ ...response(receipt(state)), status: 201 }, record())).toThrow());
  test.each(['UNKNOWN', 'constructor', '__proto__', 'toString', '', null, undefined])('unknown rejection %s cannot clear identity', (code) => {
    const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify(record(receipt('rejected', { error_code: code }))));
    expect(() => h.controller.snapshot()).toThrow(); expect(h.controller.storageBlocked()).toBe(true);
    expect(h.durableStorage.removeItem).not.toHaveBeenCalled();
  });
  test.each(['ORDER_VERSION_CONFLICT', 'ORDER_NOT_ASSIGNABLE', 'DRIVER_DISABLED', 'DRIVER_NOT_AVAILABLE', 'DRIVER_BUSY',
    'DRIVER_DATA_INVALID', 'ASSIGNMENT_INCONSISTENT', 'ASSIGNMENT_REPRESENTATION_UNSUPPORTED', 'NO_CHANGES'])('known business rejection %s', (code) => {
    expect(validateAssignmentReceipt(response(receipt('rejected', { error_code: code })), record()).state).toBe('rejected');
  });
  test.each(['ORDER_NOT_FOUND', 'DRIVER_NOT_FOUND'])('%s requires HTTP404', (code) => {
    const r = receipt('rejected', { error_code: code });
    expect(validateAssignmentReceipt({ status: 404, data: r }, record()).state).toBe('rejected');
    expect(() => validateAssignmentReceipt({ status: 409, data: r }, record())).toThrow();
  });
  test('Retry-After must match; highest safe success needs safe predecessor', () => {
    expect(() => validateAssignmentReceipt({ ...response(receipt('pending')), headers: {} }, record())).toThrow();
    expect(() => validateAssignmentReceipt({ ...response(receipt('pending')), headers: { 'retry-after': '2' } }, record())).toThrow();
    expect(validateAssignmentReceipt(response(receipt('applied', { order_version: Number.MAX_SAFE_INTEGER })),
      { ...record(), expected_order_version: Number.MAX_SAFE_INTEGER - 1 }).order_version).toBe(Number.MAX_SAFE_INTEGER);
  });
});

describe('stable non-customer assignment controller', () => {
  test('persist exact opaque identity and driver before send; no customer/session draft', async () => {
    const h = harness(); h.api.post.mockImplementation(async (path, body, options) => {
      expect(h.controller.snapshot()).toEqual(record()); expect(path).toBe(BASE);
      expect(body).toEqual({ client_operation_id: ID, expected_order_version: 4, driver_id: 'driver' });
      expect(options).toEqual({ timeout: ASSIGN_REQUEST_TIMEOUT_MS }); return response();
    });
    await h.controller.submit(command()); expect(h.durableStorage.text()).not.toMatch(/Customer|Private|notes|token/);
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'INTENT_PENDING' });
    await h.controller.acknowledge(); expect(h.controller.snapshot()).toBeNull();
  });
  test.each([false, null, 'true', undefined])('capability %s default denies without legacy fallback', async (enabled) => {
    const h = harness(); h.api.get.mockResolvedValue({ status: 200, data: { assign_recovery_enabled: enabled } });
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'ASSIGNMENT_DISABLED' });
    expect(h.api.post).not.toHaveBeenCalled(); expect(h.api.put).not.toHaveBeenCalled(); expect(h.crypto.randomUUID).not.toHaveBeenCalled();
  });
  test.each([{ locks: null }, { locks: { request: false } }, { isOnline: () => false }, { crypto: {} }])('unsupported/offline %j never sends', async (extra) => {
    const h = harness(extra); await expect(h.controller.submit(command())).rejects.toThrow(); expect(h.api.post).not.toHaveBeenCalled();
  });
  test('synchronous mutex and actual shared lock prevent double click and second tab', async () => {
    let release, held = false;
    const locks = { request: async (_key, _options, cb) => {
      if (held) return cb(null); held = true; try { return await cb({}); } finally { held = false; }
    } };
    const h = harness({ locks }); h.api.post.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    const other = harness({ locks, durableStorage: h.durableStorage });
    const flight = h.controller.submit(command());
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'BUSY' });
    await expect(other.controller.submit(command())).rejects.toMatchObject({ code: 'BUSY' });
    await Promise.resolve(); await Promise.resolve(); release(response()); await flight;
    await expect(other.controller.submitLegacy(command({ order: legacy() }))).rejects.toMatchObject({ code: 'INTENT_PENDING' });
    expect(other.api.put).not.toHaveBeenCalled(); expect(h.api.post).toHaveBeenCalledTimes(1);
  });
  test('lost ACK -> three lookups and one bodyless resume; pending freezes new ID', async () => {
    const h = harness(); h.api.post.mockRejectedValueOnce(new Error('timeout')).mockResolvedValue(response(receipt('pending')));
    h.api.get.mockImplementation(async (path) => path === CAP ? { status: 200, data: { assign_recovery_enabled: true } } : response(receipt('pending')));
    await expect(h.controller.submit(command())).resolves.toMatchObject({ state: 'pending' });
    expect(h.api.get.mock.calls.filter(([p]) => p !== CAP)).toHaveLength(MAX_ASSIGN_RECOVERY_READS);
    expect(h.api.post.mock.calls[1]).toEqual([`${BASE}/${ID}/resume`, undefined, { timeout: 15000 }]);
    expect(h.wait.mock.calls).toEqual([[1000], [1000]]);
    await expect(h.controller.submit(command({ driverId: 'other' }))).rejects.toMatchObject({ code: 'INTENT_PENDING' });
    await expect(h.controller.acknowledge()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' });
    expect(h.crypto.randomUUID).toHaveBeenCalledTimes(1);
  });
  test('reload and another tab resend exact pre-admission intent with capability disabled', async () => {
    const h = harness(); await unresolved(h);
    const fresh = harness({ durableStorage: h.durableStorage }); fresh.api.get.mockRejectedValue(missing);
    await fresh.controller.recover();
    expect(fresh.api.post.mock.calls[0]).toEqual([BASE, { client_operation_id: ID, expected_order_version: 4, driver_id: 'driver' }, { timeout: 15000 }]);
    expect(fresh.crypto.randomUUID).not.toHaveBeenCalled(); expect(fresh.api.get.mock.calls[0][0]).toBe(`${BASE}/${ID}`);
  });
  test('admitted pending recovers after disable without new POST intent', async () => {
    const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify(record(receipt('pending'))));
    h.api.get.mockResolvedValue(response(receipt('pending'))); h.api.post.mockResolvedValue(response(receipt('replayed')));
    await h.controller.recover(); expect(h.api.post.mock.calls[0][0]).toBe(`${BASE}/${ID}/resume`);
    expect(h.api.post.mock.calls[0][1]).toBeUndefined(); expect(h.api.get.mock.calls.some(([p]) => p === CAP)).toBe(false);
  });
  test('admitted operation disappearing is uncertain, never a resend or ACK', async () => {
    const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify(record(receipt('pending')))); h.api.get.mockRejectedValue(missing);
    await expect(h.controller.recover()).rejects.toMatchObject({ code: 'OPERATION_UNCERTAIN' }); expect(h.api.post).not.toHaveBeenCalled();
    expect(h.controller.snapshot().receipt.state).toBe('pending');
  });
  test('unrecognized lookup404 cannot authorize sending', async () => {
    const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify(record())); h.api.get.mockRejectedValue({ response: { status: 404, data: {} } });
    await expect(h.controller.recover()).rejects.toThrow(); expect(h.api.post).not.toHaveBeenCalled();
  });
  test.each([401, 403, 409, 422])('HTTP%s keeps identity; no auth replay or silent new intent', async (status) => {
    const h = harness(); h.api.post.mockRejectedValue({ response: { status } }); await expect(h.controller.submit(command())).rejects.toThrow();
    expect(h.api.post).toHaveBeenCalledTimes(1); expect(h.api.get).toHaveBeenCalledTimes(1); expect(h.controller.snapshot().receipt).toBeNull();
  });
  test('malformed success recovers via strict lookup without claiming success', async () => {
    const h = harness(); h.api.post.mockResolvedValue(response(receipt('applied', { order_version: 0 })));
    await expect(h.controller.submit(command())).resolves.toMatchObject({ state: 'replayed', order_version: 5 });
    expect(h.api.put).not.toHaveBeenCalled();
  });
  test('storage failure before/after request is fail closed and never clears metadata', async () => {
    const h = harness(); h.durableStorage.setItem.mockImplementation(() => { throw new Error('quota'); });
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' }); expect(h.api.post).not.toHaveBeenCalled();
    const late = harness(); late.api.post.mockImplementation(async () => { late.durableStorage.setItem.mockImplementation(() => { throw new Error('quota'); }); return response(); });
    await expect(late.controller.submit(command())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
    await expect(late.controller.acknowledge()).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
    expect(late.controller.snapshot().receipt).toBeNull(); expect(late.durableStorage.removeItem).not.toHaveBeenCalled();
  });
  test.each([{ actor_id: 'other' }, { expected_order_version: null }, { driver_id: [] }, { notes: 'PII' }, { receipt: { state: 'applied' } }])('malformed stored envelope %j is retained untouched', async (extra) => {
    const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify({ ...record(), ...extra })); const raw = h.durableStorage.getItem(KEY);
    await expect(h.controller.recover()).rejects.toThrow(); expect(h.durableStorage.getItem(KEY)).toBe(raw); expect(h.api.post).not.toHaveBeenCalled();
  });
  test('late outcome fenced when owner changes or intent storage differs', async () => {
    let active = true; const h = harness({ isOwnerActive: () => active });
    h.api.post.mockImplementation(async () => { active = false; return response(); });
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
    expect(JSON.parse(h.durableStorage.getItem(KEY)).receipt).toBeNull();
    const foreign = harness(); foreign.api.post.mockImplementation(async () => { foreign.durableStorage.setItem(KEY, JSON.stringify({ ...record(), driver_id: 'changed' })); return response(); });
    await expect(foreign.controller.submit(command())).rejects.toMatchObject({ code: 'STORAGE_UNAVAILABLE' });
    expect(JSON.parse(foreign.durableStorage.getItem(KEY)).driver_id).toBe('changed');
  });
  test('conflict requires explicit fresh revision and driver selection before new ID', async () => {
    const h = harness(); h.api.post.mockResolvedValue(response(receipt('rejected'))); await h.controller.submit(command());
    await expect(h.controller.submit(command())).rejects.toMatchObject({ code: 'INTENT_PENDING' });
    h.api.get.mockResolvedValueOnce({ status: 200, data: order({ order_version: 8 }) });
    const fresh = await h.controller.refreshForNewAttempt(); expect(fresh.order_version).toBe(8); expect(h.controller.snapshot()).toBeNull();
    h.api.get.mockResolvedValue({ status: 200, data: { assign_recovery_enabled: true } });
    h.api.post.mockResolvedValue(response(receipt('applied', { client_operation_id: NEXT, order_version: 9 })));
    await h.controller.submit(command({ order: fresh, driverId: 'new-driver' })); expect(h.api.post.mock.calls[1][1]).toEqual({ client_operation_id: NEXT, expected_order_version: 8, driver_id: 'new-driver' });
  });
  test('ineligible conflict refresh cannot discard terminal; explicit ACK can close rejected result', async () => {
    const h = harness(); h.durableStorage.setItem(KEY, JSON.stringify(record(receipt('rejected'))));
    h.api.get.mockResolvedValue({ status: 200, data: order({ status: 'ACCEPTED' }) });
    await expect(h.controller.refreshForNewAttempt()).rejects.toMatchObject({ code: 'ORDER_NOT_ASSIGNABLE' });
    expect(h.controller.snapshot().receipt.state).toBe('rejected'); await h.controller.acknowledge(); expect(h.controller.snapshot()).toBeNull();
  });
  test('legacy uses existing PUT only, versioned null or present zero can never fall back', async () => {
    const h = harness(); await h.controller.submitLegacy(command({ order: legacy() }));
    expect(h.api.put.mock.calls[0]).toEqual(['/api/orders/order/assign', { driver_id: 'driver' }, { timeout: 15000 }]);
    expect(h.api.post).not.toHaveBeenCalled(); expect(h.api.get.mock.calls[0][0]).toBe('/api/auth/me'); expect(h.api.get).toHaveBeenCalledTimes(1); expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    for (const v of [0, null, true]) await expect(h.controller.submitLegacy(command({ order: order({ order_version: v }) }))).rejects.toThrow();
    expect(h.api.put).toHaveBeenCalledTimes(1);
  });
});

describe('independent review regressions R2-R5', () => {
  test.each([undefined, null, {}, { id: 'other', is_active: true, operational_status: 'active' },
    availableDriver({ current_order_id: 'other-order' }), availableDriver({ is_active: false })])('missing/mismatched/unavailable driver snapshot %j never admits or sends legacy', async (driver) => {
    const h = harness(); await expect(h.controller.submit(command({ driver }))).rejects.toMatchObject({ code: 'INVALID_DRIVER' });
    await expect(h.controller.submitLegacy(command({ driver, order: legacy() }))).rejects.toMatchObject({ code: 'INVALID_DRIVER' });
    expect(h.api.get).not.toHaveBeenCalled(); expect(h.api.post).not.toHaveBeenCalled(); expect(h.api.put).not.toHaveBeenCalled(); expect(h.crypto.randomUUID).not.toHaveBeenCalled();
  });
  const allMultiFields = ['current_order_ids', 'active_order_ids', 'assigned_order_ids', 'reserved_order_ids',
    'current_orders', 'active_orders', 'assigned_orders', 'reserved_orders', 'pending_order_ids', 'order_ids', 'driver_ids',
    'assignments', 'assignment_ids', 'active_assignment_ids', 'reserved_assignment_ids', 'active_assignments', 'reserved_assignments',
    'pending_assignments', 'current_assignment_id', 'assignment_id', 'assignment_version', 'dispatch_version', 'route_version', 'active_count', 'reserved_count'];
  test.each(allMultiFields.flatMap((field) => [null, [], ['existing-claim']].map((value) => [field, value])))('backend-refused %s=%j denies legacy and versioned order/driver snapshot', async (field, value) => {
    for (const o of [order({ [field]: value }), { ...legacy(), [field]: value }]) {
      expect(isOrderAssignable(o)).toBe(false); const h = harness();
      await expect(h.controller[hasAssignmentRevision(o) ? 'submit' : 'submitLegacy'](command({ order: o }))).rejects.toThrow();
      expect(h.api.post).not.toHaveBeenCalled(); expect(h.api.put).not.toHaveBeenCalled(); expect(h.crypto.randomUUID).not.toHaveBeenCalled();
    }
    const driver = availableDriver({ [field]: value }); expect(isAssignmentDriverAvailable(driver)).toBe(false);
    const h = harness(); await expect(h.controller.submit(command({ driver }))).rejects.toThrow();
    await expect(h.controller.submitLegacy(command({ driver, order: legacy() }))).rejects.toThrow();
    expect(h.api.get).not.toHaveBeenCalled(); expect(h.api.post).not.toHaveBeenCalled(); expect(h.api.put).not.toHaveBeenCalled();
  });
  const badDates = ['2025-02-30T00:00:00Z', '2025-02-29T00:00:00Z', '2024-02-30T00:00:00Z', '2025-04-31T00:00:00Z',
    '2025-13-01T00:00:00Z', '2025-00-01T00:00:00Z', '2025-01-32T00:00:00Z', '2025-01-00T00:00:00Z',
    '2025-01-01T24:00:00Z', '2025-01-01T00:60:00Z', '2025-01-01T00:00:60Z', '0000-01-01T00:00:00Z',
    '2025-01-01T00:00:00+24:00', '2025-01-01T00:00:00+02:60', '2025-01-01T00:00:00', '2025-01-01',
    ' 2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z ', '2025-01-01T00:00:00Zjunk', '', false, true, 0, {}, []];
  test.each(badDates)('strict invalid pause %j is unavailable and cannot send on either route', async (date) => {
    expect(validAssignmentDate(date)).toBe(false); const driver = availableDriver({ break_until: date });
    expect(isAssignmentDriverAvailable(driver)).toBe(false); const h = harness();
    await expect(h.controller.submit(command({ driver }))).rejects.toMatchObject({ code: 'INVALID_DRIVER' });
    await expect(h.controller.submitLegacy(command({ driver, order: legacy() }))).rejects.toMatchObject({ code: 'INVALID_DRIVER' });
    expect(h.api.get).not.toHaveBeenCalled(); expect(h.api.post).not.toHaveBeenCalled(); expect(h.api.put).not.toHaveBeenCalled();
  });
  test.each(['2024-02-29T00:00:00Z', '2025-02-28T23:59:59.123456+02:00', '2020-01-01T10:00:00-03:30'])('valid expired calendar %s stays available', (date) => {
    expect(validAssignmentDate(date)).toBe(true); expect(isAssignmentDriverAvailable(availableDriver({ break_until: date }))).toBe(true);
  });
  test('null pause means absence, not an invalid calendar or active pause', () => {
    expect(validAssignmentDate(null)).toBe(false); expect(isAssignmentDriverAvailable(availableDriver({ break_until: null }))).toBe(true);
  });
  test('explicit active ends valid future pause, but never conceals malformed calendar or break/offline', async () => {
    const resumed = availableDriver({ break_started_at: '2026-10-07T10:00:00Z', break_until: '2999-10-07T11:00:00Z' });
    expect(isAssignmentDriverAvailable(resumed)).toBe(true); const h = harness(); await h.controller.submit(command({ driver: resumed }));
    for (const extra of [{ driver_status: 'break' }, { operational_status: 'break' }, { driver_status: 'offline' }, { break_until: '2025-02-30T00:00:00Z' }]) {
      expect(isAssignmentDriverAvailable({ ...resumed, ...extra })).toBe(false);
    }
    expect(isAssignmentDriverAvailable({ id: 'driver', is_active: true, break_until: resumed.break_until })).toBe(false);
  });
  test.each([{ id: 'other', role: 'admin' }, { id: 'admin', role: 'driver' }, { id: 'admin', role: 'admin', account_disabled: true },
    { id: 'admin', role: 'admin', account_disabled: 'false' }, {}, null])('legacy preflight current actor %j refuses mutation', async (user) => {
    const h = harness(); h.api.get.mockResolvedValue({ status: 200, data: user });
    await expect(h.controller.submitLegacy(command({ order: legacy() }))).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
    expect(h.api.put).not.toHaveBeenCalled(); expect(h.api.post).not.toHaveBeenCalled(); expect(h.crypto.randomUUID).not.toHaveBeenCalled();
  });
});
