import { requireOptionalNativeModule } from 'expo-modules-core';
import { parseBatteryReport } from './batteryReport';
type BatteryModule = {
  start(runId: string, kind: string): string;
  markPhase(runId: string, sessionId: string): string;
  stop(runId: string, reason: string): string;
  status(): string;
  checkGpsStart(runId: string): string;
  foregroundReady(): boolean;
};
const module = requireOptionalNativeModule<BatteryModule>('ProDeliveryBattery');
function available(): BatteryModule {
  if (!module) throw new Error('battery_native_build_required');
  return module;
}
export const batteryNative = {
  available: !!module,
  peek: () => parseBatteryReport(available().status()),
  checkGpsStart: (runId: string) => parseBatteryReport(available().checkGpsStart(runId)),
  foregroundReady: () => available().foregroundReady() === true,
  cancelCurrentSync: () => {
    if (!module) return;
    const report = parseBatteryReport(module.status());
    if (report.runId && !['none', 'completed', 'incomplete'].includes(report.phase)) module.stop(report.runId, 'cancelled');
  },
  status: async () => parseBatteryReport(await available().status()),
  start: async (runId: string, kind: 'pilot' | 'full') => parseBatteryReport(await available().start(runId, kind)),
  markGps: async (runId: string, sessionId: string) => parseBatteryReport(await available().markPhase(runId, sessionId)),
  stop: async (runId: string, reason: 'gps_stopped' | 'cancelled') => parseBatteryReport(await available().stop(runId, reason)),
};
