import test from 'node:test';
import assert from 'node:assert/strict';
import { setImmediate } from 'node:timers/promises';
import { batteryBudget, batteryBudgetBlocksGpsStart, batteryBudgetMessage, batteryBudgetWarning } from '../src/batteryBudget.ts';
import { batteryObservationsComplete, parseBatteryReport, type BatteryReport, type BatterySnapshot } from '../src/batteryReport.ts';
import { batteryStartRunForReport, markBatteryGpsWindow, withBatteryGpsStartGuard } from '../src/batteryGpsBoundary.ts';
import { batteryActionDiagnostic } from '../src/batteryStartBoundary.ts';
import { RecorderController, type ControllerState, type LocationPort } from '../src/controller.ts';
import { database, deferred, FakeNative, NOW } from './helpers.ts';

const RUN = 'pd-battery-budget-boundary';
function sample(elapsedMs: number, ownGpsServiceStarted = false): BatterySnapshot {
  return { elapsedMs, wallMs: 1_800_000_000_000 + elapsedMs, levelPercent: 80, plugMask: 0,
    charging: false, chargeCounterUah: null, screenInteractive: true, ownGpsServiceStarted };
}
function report(remainingRunMs = 1_700_000): BatteryReport {
  const snapshots = [sample(0), sample(2_700_000 - remainingRunMs)];
  return { schemaVersion: 1, runId: RUN, kind: 'full', phase: 'awaiting_gps', observerActive: true,
    starting: false, stopReason: null, gpsSessionId: null, startedElapsedMs: 0,
    lastSnapshot: snapshots.at(-1)!, snapshots, windows: [], failures: [], durabilityError: null,
    gateMs: 20_000, heartbeatMs: 10_000, maxGapMs: 25_000, targetWindowMs: 900_000, maxRunMs: 2_700_000,
    gpsAdmissionPolicy: 'full_window_reserve_v1', remainingRunMs, gpsAdmissionRequiredMs: 925_000 };
}
function gpsOwner(sessionId = 'captured-session') {
  const state: ControllerState = { phase: 'recording', mode: 'background', sessionId, permissions: null,
    error: null, notice: null, nativeShutdown: 'not_attempted', watchdog: null };
  let stops = 0;
  return { state, stop: async () => { stops++; state.phase = 'idle'; state.sessionId = null; }, get stops() { return stops; } };
}

function completedFull(gpsStartRemainingMs: number): BatteryReport {
  const value = report(); const gpsStartMs = 2_700_000 - gpsStartRemainingMs;
  const gpsEndMs = gpsStartMs + 900_000;
  value.snapshots = [];
  for (let ms = 0; ms < gpsStartMs; ms += 10_000) value.snapshots.push(sample(ms));
  const gpsStart = sample(gpsStartMs, true); value.snapshots.push(gpsStart);
  for (let ms = gpsStartMs + 10_000; ms <= gpsEndMs; ms += 10_000) value.snapshots.push(sample(ms, true));
  const gpsEnd = value.snapshots.at(-1)!;
  value.windows = [{ phase: 'idle', start: value.snapshots[2], end: value.snapshots[92], sampleCount: 91,
    maxGapMs: 10_000, elapsedMs: 900_000, valid: true, reasons: [] },
  { phase: 'gps', start: gpsStart, end: gpsEnd, sampleCount: 91, maxGapMs: 10_000,
    elapsedMs: 900_000, valid: true, reasons: [] }];
  value.phase = 'completed'; value.observerActive = false; value.gpsSessionId = 'completed-session';
  value.stopReason = 'gps_stopped'; value.lastSnapshot = gpsEnd; value.remainingRunMs = gpsStartRemainingMs - 900_000;
  return value;
}

test('new policy requires strictly more than full GPS window plus maximum observation gap', () => {
  for (const [remaining, allowed] of [[925_001, true], [925_000, false], [924_999, false], [900_001, false], [0, false]] as const) {
    const value = parseBatteryReport(JSON.stringify(report(remaining)));
    assert.equal(batteryBudget(value).admission, allowed ? 'allowed' : 'insufficient');
    assert.equal(batteryBudgetBlocksGpsStart(value), !allowed);
    if (allowed) assert.equal(batteryStartRunForReport(value, 'background'), RUN);
    else assert.throws(() => batteryStartRunForReport(value, 'background'), /gps_budget_insufficient/);
  }
});
test('legacy absent and null policy keep historical reports and Start behavior', () => {
  for (const policy of [undefined, null] as const) {
    const value = report(802_167); value.gpsAdmissionPolicy = policy;
    delete value.remainingRunMs; delete value.gpsAdmissionRequiredMs;
    const parsed = parseBatteryReport(JSON.stringify(value));
    assert.equal(batteryBudget(parsed).admission, 'legacy');
    assert.equal(batteryStartRunForReport(parsed, 'background'), RUN);
    assert.equal(batteryBudgetMessage(parsed).includes('necunoscut'), true);
  }
});
test('unknown policy cannot silently downgrade to historical admission', () => {
  assert.throws(() => parseBatteryReport(JSON.stringify({ ...report(), gpsAdmissionPolicy: 'new_unrecognized_policy' })), /battery_report_invalid/);
  const unsafe = { ...report(), gpsAdmissionPolicy: 'new_unrecognized_policy' } as unknown as BatteryReport;
  assert.equal(batteryBudget(unsafe).admission, 'unknown');
  assert.equal(batteryBudgetBlocksGpsStart(unsafe), true);
});
test('missing, null, inconsistent, unsafe or rollback native budget fails closed without invented time', () => {
  const invalid = [
    { remainingRunMs: undefined }, { remainingRunMs: null }, { gpsAdmissionRequiredMs: undefined },
    { startedElapsedMs: null }, { startedElapsedMs: Number.MAX_SAFE_INTEGER + 1 }, { startedElapsedMs: -1 },
    { lastSnapshot: null }, { lastSnapshot: sample(-1) }, { lastSnapshot: sample(Number.MAX_SAFE_INTEGER + 1) },
    { remainingRunMs: 1_700_001 }, { remainingRunMs: NaN }, { remainingRunMs: Infinity },
    { snapshots: [] }, { snapshots: [sample(0), sample(1_000_000), sample(999_999)] },
    { snapshots: [sample(0), sample(999_999)] }, { lastSnapshot: sample(1_000_000.5) },
  ];
  for (const change of invalid) {
    const value = { ...report(), ...change } as BatteryReport;
    assert.deepEqual(batteryBudget(value), { remainingMs: null, observedAtElapsedMs: null, admission: 'unknown' });
    assert.equal(batteryBudgetBlocksGpsStart(value), true);
    assert.equal(batteryBudgetMessage(value).includes('necunoscut'), true);
  }
  for (const change of [{ remainingRunMs: -1 }, { remainingRunMs: 2_700_001 },
    { remainingRunMs: 1.5 }, { gpsAdmissionRequiredMs: 900_000 }])
    assert.throws(() => parseBatteryReport(JSON.stringify({ ...report(), ...change })), /battery_report_invalid/);
});
test('budget remains explicitly AS-OF snapshot despite stale wall clock or elapsed real time', t => {
  const value = report(925_001);
  value.lastSnapshot!.wallMs = -9_000;
  const budget = batteryBudget(value); const text = batteryBudgetMessage(value);
  t.mock.timers.enable({ apis: ['Date'] }); t.mock.timers.setTime(9_999_999_999_999);
  assert.deepEqual(batteryBudget(value), budget); assert.equal(batteryBudgetMessage(value), text);
  assert.equal(budget.observedAtElapsedMs, 1_774_999);
  assert.match(text, /ultima observatie nativa/); assert.match(text, /Valoare memorata, nu cronometru curent/);
});
test('full mode identity and phase restrictions are preserved regardless of sufficient budget', () => {
  const value = report();
  assert.throws(() => batteryStartRunForReport(value, 'foreground'), /battery_gps_start_blocked/);
  assert.throws(() => batteryStartRunForReport({ ...value, starting: true }, 'background'), /battery_gps_start_blocked/);
  assert.throws(() => batteryStartRunForReport({ ...value, phase: 'idle' }, 'background'), /battery_gps_start_blocked/);
  assert.equal(batteryStartRunForReport({ ...value, phase: 'incomplete' }, 'background'), null);
});
test('fresh post-permission rejection blocks location start and closes actual controller SQLite session', async t => {
  const local = database(':memory:'); t.after(() => local.db.close());
  const native = new FakeNative(); const delayed = deferred();
  let checks = 0; let live = report(925_001);
  const guarded = withBatteryGpsStartGuard(native, () => RUN, id => {
    checks++; assert.equal(id, RUN); assert.equal(native.requests.at(-1), 'background'); return live;
  });
  // FakeNative uses prototype methods; bind explicitly to preserve the real port contract.
  const port: LocationPort = { backgroundAvailable: () => native.backgroundAvailable(), permissions: mode => native.permissions(mode),
    start: guarded.start, stop: () => native.stop() };
  const controller = new RecorderController(local.store, port, () => NOW, () => 'late-permission-session');
  await controller.initialize(); native.waitPermission = delayed.promise;
  assert.equal(batteryStartRunForReport(live, 'background'), RUN);
  const starting = controller.start('background'); await setImmediate();
  assert.equal(checks, 0); assert.equal(native.starts, 0);
  live = report(925_000); delayed.resolve(); await starting;
  assert.equal(checks, 1); assert.equal(native.starts, 0); assert.equal(local.store.active(), null);
  assert.equal(controller.state.phase, 'error'); assert.equal(controller.state.nativeShutdown, 'api_acknowledged');
});
test('fresh native insufficient exception and changed trial identity both prevent native Start', async () => {
  let starts = 0; let trial: string | null = RUN;
  const port: LocationPort = { backgroundAvailable: async () => true,
    permissions: async () => ({ foreground: true, background: true, services: true, precision: 'precise' }),
    start: async () => { starts++; }, stop: async () => {} };
  const rejected = withBatteryGpsStartGuard(port, () => trial, () => { throw new Error('gps_budget_insufficient'); });
  await assert.rejects(rejected.start('background', () => {}, () => {}), /gps_budget_insufficient/);
  const swapped = withBatteryGpsStartGuard(port, () => trial, () => { trial = 'pd-battery-other-run'; return report(); });
  await assert.rejects(swapped.start('background', () => {}, () => {}), /battery_gps_start_expired/);
  assert.equal(starts, 0); assert.equal(batteryActionDiagnostic(new Error('native: gps_budget_insufficient')), 'gps_budget_insufficient');
});
test('successful fresh guard starts background once without changing non-trial Start', async () => {
  let checks = 0; let starts = 0;
  const port: LocationPort = { backgroundAvailable: async () => true,
    permissions: async () => ({ foreground: true, background: true, services: true, precision: 'precise' }),
    start: async () => { starts++; }, stop: async () => {} };
  await withBatteryGpsStartGuard(port, () => RUN, () => { checks++; return report(925_001); }).start('background', () => {}, () => {});
  await withBatteryGpsStartGuard(port, () => null, () => { throw new Error('unexpected_check'); }).start('foreground', () => {}, () => {});
  assert.equal(checks, 1); assert.equal(starts, 2);
});
test('marker budget failure cancels observer before stopping only captured GPS owner', async () => {
  const owner = gpsOwner(); const order: string[] = [];
  const stop = owner.stop; owner.stop = async () => { order.push('gps_stop'); await stop(); };
  const result = await markBatteryGpsWindow(owner, report(), async () => { order.push('mark'); throw new Error('gps_budget_insufficient'); },
    async (id, reason) => { order.push('cancel'); assert.equal(id, RUN); assert.equal(reason, 'cancelled');
      return { ...report(), phase: 'incomplete', stopReason: 'gps_budget_insufficient', failures: ['gps_budget_insufficient'] }; });
  assert.deepEqual(order, ['mark', 'cancel', 'gps_stop']); assert.equal(owner.stops, 1);
  assert.equal(result.phase, 'incomplete'); assert.equal(result.gpsSessionId, null);
  assert.match(batteryBudgetWarning(result)!, /Proba incompleta/);
  assert.equal(batteryBudgetWarning(result)!.includes('Start este blocat'), false);
});
test('failed marker cannot stop a replacement owner and cleanup still runs if observer stop fails', async () => {
  const swapped = gpsOwner();
  await markBatteryGpsWindow(swapped, report(), async () => { swapped.state.sessionId = 'new-session'; throw new Error('gps_budget_insufficient'); },
    async () => ({ ...report(), phase: 'incomplete' }));
  assert.equal(swapped.stops, 0); assert.equal(swapped.state.sessionId, 'new-session');
  const same = gpsOwner();
  await assert.rejects(markBatteryGpsWindow(same, report(), async () => { throw new Error('gps_budget_insufficient'); },
    async () => { throw new Error('journal_write_failed'); }), /journal_write_failed/);
  assert.equal(same.stops, 1);
});
test('valid pilot and complete full evidence remain valid; terminal low remaining budget never erases completion', () => {
  const value = report(); value.snapshots = [0, 10_000, 20_000, 30_000, 40_000, 50_000].map(ms => sample(ms));
  value.kind = 'pilot'; value.targetWindowMs = 30_000; value.phase = 'completed'; value.observerActive = false;
  value.stopReason = 'pilot_window_complete'; value.lastSnapshot = value.snapshots.at(-1)!;
  value.remainingRunMs = null; value.gpsAdmissionRequiredMs = null;
  value.windows = [{ phase: 'idle', start: value.snapshots[2], end: value.snapshots[5], sampleCount: 4,
    maxGapMs: 10_000, elapsedMs: 30_000, valid: true, reasons: [] }];
  assert.equal(batteryObservationsComplete(parseBatteryReport(JSON.stringify(value))), true);
  assert.equal(batteryBudgetBlocksGpsStart(value), false);
  const full = report(); full.snapshots = [];
  for (let ms = 0; ms <= 1_820_000; ms += 10_000) full.snapshots.push(sample(ms, ms >= 920_000));
  const gpsStart = sample(920_000, true); const idleEnd = sample(920_000, false);
  full.snapshots.splice(92, 0, idleEnd);
  full.windows = [{ phase: 'idle', start: full.snapshots[2], end: idleEnd, sampleCount: 91,
    maxGapMs: 10_000, elapsedMs: 900_000, valid: true, reasons: [] },
  { phase: 'gps', start: gpsStart, end: full.snapshots.at(-1)!, sampleCount: 91,
    maxGapMs: 10_000, elapsedMs: 900_000, valid: true, reasons: [] }];
  // Adjacent windows cannot share contradictory GPS observations; put marker one millisecond after idle.
  full.snapshots = full.snapshots.filter(s => s !== gpsStart && !(s.elapsedMs === 920_000 && s.ownGpsServiceStarted));
  const marker = sample(920_001, true); full.snapshots.splice(93, 0, marker);
  const end = sample(1_820_001, true); full.snapshots.push(end);
  full.windows[1] = { phase: 'gps', start: marker, end, sampleCount: 92, maxGapMs: 10_000,
    elapsedMs: 900_000, valid: true, reasons: [] };
  full.phase = 'completed'; full.observerActive = false; full.gpsSessionId = 'valid-session'; full.stopReason = 'gps_stopped';
  full.lastSnapshot = end; full.remainingRunMs = 879_999;
  assert.equal(batteryObservationsComplete(parseBatteryReport(JSON.stringify(full))), true);
  assert.equal(batteryBudgetBlocksGpsStart(full), false);
});
test('completed new-policy evidence must prove the same strict GPS admission reserve; legacy completion is preserved', () => {
  for (const remaining of [900_001, 924_999, 925_000, 925_001]) {
    const value = completedFull(remaining);
    assert.equal(batteryObservationsComplete(parseBatteryReport(JSON.stringify(value))), remaining > 925_000);
    for (const policy of [undefined, null] as const) {
      const legacy = { ...value, gpsAdmissionPolicy: policy };
      delete legacy.remainingRunMs; delete legacy.gpsAdmissionRequiredMs;
      assert.equal(batteryObservationsComplete(parseBatteryReport(JSON.stringify(legacy))), true);
    }
  }
  const valid = completedFull(925_001);
  for (const change of [{ gpsAdmissionRequiredMs: null }, { gpsAdmissionRequiredMs: undefined },
    { startedElapsedMs: -1 }, { startedElapsedMs: Number.MAX_SAFE_INTEGER + 1 }])
    assert.equal(batteryObservationsComplete({ ...valid, ...change } as BatteryReport), false);
});
