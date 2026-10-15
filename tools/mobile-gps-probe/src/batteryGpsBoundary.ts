import type { ControllerState, LocationPort } from './controller.ts';
import type { BatteryReport } from './batteryReport.ts';
import type { Mode } from './sample.ts';
import { batteryBudgetBlocksGpsStart } from './batteryBudget.ts';

export function batteryStartRunForReport(report: BatteryReport | null, mode: Mode): string | null {
  if (!report || ['none', 'completed', 'incomplete'].includes(report.phase)) return null;
  if (report.kind === 'full' && report.phase === 'awaiting_gps' && !report.starting && report.runId && mode === 'background') {
    if (batteryBudgetBlocksGpsStart(report)) throw new Error('gps_budget_insufficient');
    return report.runId;
  }
  throw new Error('battery_gps_start_blocked');
}
export function withBatteryGpsStartGuard(port: LocationPort, getTrial: () => string | null, checkTrial: (id: string) => BatteryReport): LocationPort {
  return { ...port, start: async (mode, sample, error) => {
    const trial = getTrial();
    if (trial) {
      const report = checkTrial(trial);
      if (mode !== 'background' || batteryStartRunForReport(report, mode) !== trial || getTrial() !== trial) throw new Error('battery_gps_start_expired');
    }
    await port.start(mode, sample, error);
  } };
}
type GpsOwner = { state: ControllerState; stop(): Promise<void> };
type BatteryStop = (id: string, reason: 'gps_stopped' | 'cancelled') => Promise<BatteryReport>;
type BatteryMark = (id: string, sessionId: string) => Promise<BatteryReport>;
export async function markBatteryGpsWindow(owner: GpsOwner, report: BatteryReport, markBattery: BatteryMark, stopBattery: BatteryStop): Promise<BatteryReport> {
  if (!report.runId || !owner.state.sessionId) throw new Error('battery_handoff_identity_required');
  const runId = report.runId; const sessionId = owner.state.sessionId;
  try {
    const result = await markBattery(runId, sessionId);
    if (result.runId !== runId || result.phase !== 'gps' || result.gpsSessionId !== sessionId) throw new Error('battery_gps_handoff_unconfirmed');
    if (owner.state.phase !== 'recording' || owner.state.mode !== 'background' || owner.state.sessionId !== sessionId || owner.state.watchdog) throw new Error('battery_gps_owner_changed');
    return result;
  } catch {
    // The observer may fail before assigning gpsSessionId. Cancel before Stop,
    // then clean up only the GPS session captured for this handoff.
    try { return await stopBattery(runId, 'cancelled'); }
    finally { if (owner.state.sessionId === sessionId) await owner.stop(); }
  }
}
export function canCompleteGpsWindow(report: BatteryReport, state: ControllerState): boolean {
  return report.phase === 'awaiting_stop' && !!report.gpsSessionId &&
    state.phase === 'recording' && state.mode === 'background' && state.sessionId === report.gpsSessionId && !state.watchdog;
}
export async function closeBatteryGpsWindow(owner: GpsOwner | null, report: BatteryReport, stopBattery: BatteryStop): Promise<BatteryReport> {
  if (!report.runId) throw new Error('battery_run_required');
  const canComplete = !!owner && canCompleteGpsWindow(report, owner.state);
  if (!canComplete) {
    // The native Function writes cancellation synchronously before this first await.
    // Main Stop -> Home cannot leave the observer declaring a later valid GPS window.
    try { return await stopBattery(report.runId, 'cancelled'); }
    finally { if (owner) await owner.stop(); }
  }
  try { await owner!.stop(); }
  catch { return stopBattery(report.runId, 'cancelled'); }
  const state = owner!.state;
  return stopBattery(report.runId, state.phase === 'idle' && state.nativeShutdown === 'api_acknowledged' && !state.watchdog
    ? 'gps_stopped' : 'cancelled');
}
