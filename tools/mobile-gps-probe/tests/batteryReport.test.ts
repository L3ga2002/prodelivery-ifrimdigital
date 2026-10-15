import { test } from 'node:test';
import assert from 'node:assert/strict';
import { batteryObservationsComplete, parseBatteryReport, type BatteryReport, type BatterySnapshot } from '../src/batteryReport.ts';
function pilot(): BatteryReport {
  const snapshots: BatterySnapshot[] = [0, 10_000, 20_000, 30_000, 40_000, 50_000].map(elapsedMs => ({
    elapsedMs, wallMs: 1_800_000_000_000 + elapsedMs, levelPercent: 80, plugMask: 0,
    charging: false, chargeCounterUah: null, screenInteractive: true, ownGpsServiceStarted: false,
  }));
  return { schemaVersion: 1, runId: 'pd-battery-report-proof', kind: 'pilot', phase: 'completed',
    observerActive: false, starting: false, stopReason: 'pilot_window_complete', gpsSessionId: null,
    startedElapsedMs: 0, lastSnapshot: snapshots.at(-1)!, snapshots,
    windows: [{ phase: 'idle', start: snapshots[2], end: snapshots[5], sampleCount: 4,
      maxGapMs: 10_000, elapsedMs: 30_000, valid: true, reasons: [] }], failures: [], durabilityError: null,
    gateMs: 20_000, heartbeatMs: 10_000, maxGapMs: 25_000, targetWindowMs: 30_000, maxRunMs: 2_700_000 };
}
test('finite pilot recognizes real unplug gate and observations, not zero drain', () => {
  const report = parseBatteryReport(JSON.stringify(pilot()));
  assert.equal(batteryObservationsComplete(report), true);
  assert.equal(report.windows[0].start.levelPercent, report.windows[0].end.levelPercent);
});
test('middle charging invalidates a forged valid window with unpowered endpoints', () => {
  const report = pilot(); report.snapshots[3].plugMask = 2;
  assert.equal(batteryObservationsComplete(report), false);
});
test('wallclock span cannot replace missing monotonic observations', () => {
  const report = pilot(); report.snapshots = [report.snapshots[0], report.snapshots[2], report.snapshots[5]];
  assert.equal(batteryObservationsComplete(report), false);
});
test('unplug gate cannot be invented from a later window duration', () => {
  const report = pilot(); report.snapshots = report.snapshots.slice(2);
  assert.equal(batteryObservationsComplete(report), false);
});
test('terminal journal with missing GPS phase cannot certify a full run', () => {
  const report = pilot(); report.kind = 'full'; report.stopReason = 'gps_stopped'; report.gpsSessionId = 'session';
  assert.equal(batteryObservationsComplete(report), false);
});
test('native interruption and durability errors remain incomplete', () => {
  for (const change of [{ phase: 'incomplete' }, { durabilityError: 'journal_corrupt' }, { observerActive: true }]) {
    const report = { ...pilot(), ...change } as BatteryReport;
    assert.equal(batteryObservationsComplete(report), false);
  }
});
test('malformed or incompatible native bridge values are rejected', () => {
  for (const change of [{ schemaVersion: 2 }, { gateMs: 0 }, { runId: '../../file' },
    { snapshots: [{ elapsedMs: null }] }, { maxGapMs: 60_000 }, { kind: null }]) {
    assert.throws(() => parseBatteryReport(JSON.stringify({ ...pilot(), ...change })));
  }
});
test('USB reconnect after durable pilot window does not rewrite its evidence', () => {
  const report = pilot();
  report.snapshots.push({ ...report.lastSnapshot!, elapsedMs: 60_000, wallMs: 1_800_000_060_000, plugMask: 2, charging: true });
  assert.equal(batteryObservationsComplete(report), true);
});
