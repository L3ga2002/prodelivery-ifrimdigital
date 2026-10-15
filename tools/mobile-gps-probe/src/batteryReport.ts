export type BatteryPhase = 'none' | 'waiting_unplug' | 'idle' | 'awaiting_gps' | 'gps' | 'awaiting_stop' | 'completed' | 'incomplete';
export type BatterySnapshot = {
  elapsedMs: number; wallMs: number; levelPercent: number | null; plugMask: number | null;
  charging: boolean | null; chargeCounterUah: number | null; screenInteractive: boolean | null;
  ownGpsServiceStarted: boolean | null;
};
export type BatteryWindow = {
  phase: 'idle' | 'gps'; start: BatterySnapshot; end: BatterySnapshot;
  sampleCount: number; maxGapMs: number; elapsedMs: number; valid: boolean; reasons: string[];
};
export type BatteryReport = {
  schemaVersion: 1; runId: string | null; kind: 'pilot' | 'full' | null; phase: BatteryPhase;
  observerActive: boolean; starting: boolean; stopReason: string | null; gpsSessionId: string | null;
  startedElapsedMs: number | null; lastSnapshot: BatterySnapshot | null; snapshots: BatterySnapshot[];
  windows: BatteryWindow[]; failures: string[]; durabilityError: string | null;
  gateMs: number; heartbeatMs: number; maxGapMs: number; targetWindowMs: number | null; maxRunMs: number;
  // Absent/null policy belongs to historical journals. Budget values describe
  // lastSnapshot, never a wall-clock countdown or a new native observation.
  gpsAdmissionPolicy?: 'full_window_reserve_v1' | null;
  remainingRunMs?: number | null; gpsAdmissionRequiredMs?: number | null;
};
const phases: BatteryPhase[] = ['none', 'waiting_unplug', 'idle', 'awaiting_gps', 'gps', 'awaiting_stop', 'completed', 'incomplete'];
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const optionalNumber = (v: unknown) => v === null || finite(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 100 && v.every(x => typeof x === 'string' && x.length <= 200);
const optionalString = (v: unknown) => v === null || (typeof v === 'string' && v.length <= 200);
function snapshot(v: unknown): v is BatterySnapshot {
  return object(v) && finite(v.elapsedMs) && v.elapsedMs >= 0 && finite(v.wallMs) &&
    optionalNumber(v.levelPercent) && (v.levelPercent === null || (v.levelPercent >= 0 && v.levelPercent <= 100)) &&
    optionalNumber(v.plugMask) && (v.plugMask === null || (Number.isInteger(v.plugMask) && v.plugMask >= 0)) &&
    (v.charging === null || typeof v.charging === 'boolean') && optionalNumber(v.chargeCounterUah) &&
    (v.screenInteractive === null || typeof v.screenInteractive === 'boolean') &&
    (v.ownGpsServiceStarted === null || typeof v.ownGpsServiceStarted === 'boolean');
}
function window(v: unknown): v is BatteryWindow {
  return object(v) && (v.phase === 'idle' || v.phase === 'gps') && snapshot(v.start) && snapshot(v.end) &&
    finite(v.sampleCount) && Number.isInteger(v.sampleCount) && v.sampleCount >= 1 &&
    finite(v.maxGapMs) && v.maxGapMs >= 0 && finite(v.elapsedMs) && v.elapsedMs >= 0 &&
    typeof v.valid === 'boolean' && strings(v.reasons);
}
export function parseBatteryReport(raw: string): BatteryReport {
  if (raw.length > 2_097_152) throw new Error('battery_report_invalid');
  const v: unknown = JSON.parse(raw);
  if (!object(v) || v.schemaVersion !== 1 || !phases.includes(v.phase as BatteryPhase) ||
    !optionalString(v.runId) || !optionalString(v.stopReason) || !optionalString(v.gpsSessionId) ||
    !optionalString(v.durabilityError) || !optionalNumber(v.startedElapsedMs) ||
    !(v.kind === null || v.kind === 'pilot' || v.kind === 'full') ||
    typeof v.observerActive !== 'boolean' || typeof v.starting !== 'boolean' ||
    !(v.lastSnapshot === null || snapshot(v.lastSnapshot)) ||
    !Array.isArray(v.snapshots) || v.snapshots.length > 4096 || !v.snapshots.every(snapshot) ||
    !Array.isArray(v.windows) || v.windows.length > 2 || !v.windows.every(window) || !strings(v.failures) ||
    v.gateMs !== 20_000 || v.heartbeatMs !== 10_000 || v.maxGapMs !== 25_000 ||
    !(v.targetWindowMs === null || v.targetWindowMs === 30_000 || v.targetWindowMs === 900_000) || v.maxRunMs !== 2_700_000)
    throw new Error('battery_report_invalid');
  if (!(v.gpsAdmissionPolicy === undefined || v.gpsAdmissionPolicy === null || v.gpsAdmissionPolicy === 'full_window_reserve_v1') ||
    !(v.remainingRunMs === undefined || v.remainingRunMs === null ||
      (Number.isSafeInteger(v.remainingRunMs) && (v.remainingRunMs as number) >= 0 && (v.remainingRunMs as number) <= v.maxRunMs)) ||
    !(v.gpsAdmissionRequiredMs === undefined || v.gpsAdmissionRequiredMs === null || v.gpsAdmissionRequiredMs === 925_000))
    throw new Error('battery_report_invalid');
  if (v.phase !== 'none' && (typeof v.runId !== 'string' || !/^pd-battery-[a-z0-9][a-z0-9-]{7,80}$/.test(v.runId) || v.kind === null))
    throw new Error('battery_report_invalid');
  return v as BatteryReport;
}
export function batteryObservationsComplete(report: BatteryReport): boolean {
  const expected = report.kind === 'pilot' ? ['idle'] : report.kind === 'full' ? ['idle', 'gps'] : [];
  const duration = report.kind === 'pilot' ? 30_000 : 900_000;
  const idle = report.windows[0];
  const finalWindow = report.windows.at(-1);
  if (!idle || !finalWindow || !report.snapshots.length) return false;
  if (report.startedElapsedMs === null || report.snapshots[0].elapsedMs < report.startedElapsedMs || idle.start.elapsedMs < report.startedElapsedMs ||
    finalWindow.end.elapsedMs - report.startedElapsedMs >= report.maxRunMs ||
    (report.windows.length === 2 && report.windows[1].start.elapsedMs < idle.end.elapsedMs)) return false;
  if (report.kind === 'full' && report.gpsAdmissionPolicy === 'full_window_reserve_v1') {
    const gpsStart = report.windows[1]?.start.elapsedMs;
    if (report.gpsAdmissionRequiredMs !== 925_000 || !Number.isSafeInteger(report.startedElapsedMs) ||
      report.startedElapsedMs < 0 || !Number.isSafeInteger(gpsStart) || gpsStart! < report.startedElapsedMs ||
      report.maxRunMs - (gpsStart! - report.startedElapsedMs) <= 925_000) return false;
  }
  const unpowered = (s: BatterySnapshot) => s.plugMask === 0 && s.charging === false && s.levelPercent !== null;
  const gateSamples = report.snapshots.filter(s => s.elapsedMs <= idle.start.elapsedMs);
  let gateStart = idle.start.elapsedMs;
  for (let i = gateSamples.length - 1; i >= 0; i--) {
    if (!unpowered(gateSamples[i])) break;
    gateStart = gateSamples[i].elapsedMs;
  }
  if (idle.start.elapsedMs - gateStart < report.gateMs) return false;
  if (!report.snapshots.every((s, i, all) => (i === 0 || (s.elapsedMs >= all[i - 1].elapsedMs &&
    s.elapsedMs - all[i - 1].elapsedMs <= report.maxGapMs)) &&
    (s.elapsedMs < idle.start.elapsedMs || s.elapsedMs > finalWindow.end.elapsedMs || unpowered(s)))) return false;
  return report.phase === 'completed' && !report.observerActive && !report.starting &&
    report.failures.length === 0 && report.durabilityError === null &&
    (report.kind !== 'full' || (report.stopReason === 'gps_stopped' && !!report.gpsSessionId)) &&
    expected.length > 0 && report.windows.length === expected.length && report.windows.every((w, i) => {
      const trace = report.snapshots.filter(s => s.elapsedMs >= w.start.elapsedMs && s.elapsedMs <= w.end.elapsedMs);
      let observedMaxGap = 0;
      for (let j = 1; j < trace.length; j++) observedMaxGap = Math.max(observedMaxGap, trace[j].elapsedMs - trace[j - 1].elapsedMs);
      return w.phase === expected[i] && w.valid && w.reasons.length === 0 && w.elapsedMs >= duration &&
      w.end.elapsedMs - w.start.elapsedMs === w.elapsedMs && w.maxGapMs <= report.maxGapMs &&
      w.maxGapMs >= observedMaxGap && w.sampleCount <= trace.length &&
      trace.every(s => s.ownGpsServiceStarted === (w.phase === 'gps')) &&
      w.sampleCount >= Math.ceil(w.elapsedMs / report.maxGapMs) + 1 &&
      report.snapshots.some(s => JSON.stringify(s) === JSON.stringify(w.start)) &&
      report.snapshots.some(s => JSON.stringify(s) === JSON.stringify(w.end)) &&
      w.start.plugMask === 0 && w.end.plugMask === 0 && w.start.charging === false && w.end.charging === false;
    });
}
