import { requireOptionalNativeModule } from 'expo-modules-core';

export interface BatterySnapshot {
  elapsedMs: number;
  wallMs: number;
  levelPercent: number | null;
  plugMask: number | null;
  charging: boolean | null;
  chargeCounterUah: number | null;
  screenInteractive: boolean | null;
  ownGpsServiceStarted: boolean | null;
}

export interface BatteryWindow {
  phase: 'idle' | 'gps';
  start: BatterySnapshot;
  end: BatterySnapshot;
  sampleCount: number;
  maxGapMs: number;
  elapsedMs: number;
  valid: boolean;
  reasons: string[];
}

export interface BatteryNativeModule {
  foregroundReady(): boolean;
  start(runId: string, kind: 'pilot' | 'full'): string;
  status(): string;
  checkGpsStart(runId: string): string;
  markPhase(runId: string, sessionId: string): string;
  stop(runId: string, reason: 'gps_stopped' | 'cancelled'): string;
}

export default requireOptionalNativeModule<BatteryNativeModule>('ProDeliveryBattery');
