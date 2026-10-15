import type { BatteryReport } from './batteryReport.ts';

export const GPS_ADMISSION_POLICY = 'full_window_reserve_v1';
export const GPS_ADMISSION_REQUIRED_MS = 900_000 + 25_000;
type Admission = 'legacy' | 'unknown' | 'allowed' | 'insufficient';
export type BatteryBudget = {
  remainingMs: number | null; observedAtElapsedMs: number | null; admission: Admission;
};
const safeElapsed = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;

// Presentation and the initial Start gate use only the last native observation.
// A fresh native check after permissions and at the GPS marker remains required.
export function batteryBudget(report: BatteryReport | null): BatteryBudget {
  const unknown: BatteryBudget = { remainingMs: null, observedAtElapsedMs: null, admission: 'unknown' };
  if (!report) return unknown;
  if (report.gpsAdmissionPolicy === undefined || report.gpsAdmissionPolicy === null)
    return { ...unknown, admission: 'legacy' };
  if (report.gpsAdmissionPolicy !== GPS_ADMISSION_POLICY || report.maxRunMs !== 2_700_000 ||
    report.gpsAdmissionRequiredMs !== GPS_ADMISSION_REQUIRED_MS || !safeElapsed(report.startedElapsedMs) ||
    !report.lastSnapshot || !safeElapsed(report.lastSnapshot.elapsedMs) ||
    report.lastSnapshot.elapsedMs < report.startedElapsedMs || !safeElapsed(report.remainingRunMs) ||
    !report.snapshots.length || !report.snapshots.every((sample, i, all) => safeElapsed(sample.elapsedMs) &&
      sample.elapsedMs >= report.startedElapsedMs! && (i === 0 || sample.elapsedMs >= all[i - 1].elapsedMs)) ||
    report.snapshots.at(-1)!.elapsedMs !== report.lastSnapshot.elapsedMs ||
    report.remainingRunMs !== Math.max(0, report.maxRunMs - (report.lastSnapshot.elapsedMs - report.startedElapsedMs)))
    return unknown;
  return { remainingMs: report.remainingRunMs, observedAtElapsedMs: report.lastSnapshot.elapsedMs,
    admission: report.remainingRunMs > GPS_ADMISSION_REQUIRED_MS ? 'allowed' : 'insufficient' };
}

export function batteryBudgetBlocksGpsStart(report: BatteryReport): boolean {
  if (report.kind !== 'full' || report.phase !== 'awaiting_gps') return false;
  const admission = batteryBudget(report).admission;
  return admission === 'insufficient' || admission === 'unknown';
}

export function batteryBudgetMessage(report: BatteryReport | null): string {
  const budget = batteryBudget(report);
  if (budget.remainingMs === null) return 'Buget ramas: necunoscut; lipseste o observatie nativa valida.';
  const seconds = Math.floor(budget.remainingMs / 1000);
  return `Buget ramas la ultima observatie nativa: ${Math.floor(seconds / 60)} min ${seconds % 60} s. Valoare memorata, nu cronometru curent.`;
}

export function batteryBudgetWarning(report: BatteryReport | null): string | null {
  if (!report) return null;
  if (report.stopReason === 'gps_budget_insufficient' || report.failures.includes('gps_budget_insufficient'))
    return 'Proba incompleta: timp insuficient pentru cele 15 minute GPS si marja de observare. Daca GPS este activ, apasa Stop. Nu repeta automat.';
  if (report.kind === 'full' && report.phase === 'awaiting_gps' && batteryBudget(report).admission === 'insufficient')
    return 'Timp insuficient pentru cele 15 minute GPS si marja de observare. Start este blocat. Apasa Stop pentru a inchide proba; nu repeta automat.';
  if (report.kind === 'full' && report.phase === 'awaiting_gps' && batteryBudget(report).admission === 'unknown')
    return 'Bugetul ramas nu este confirmat. Start este blocat. Apasa Stop pentru a inchide proba; nu repeta automat.';
  return null;
}
