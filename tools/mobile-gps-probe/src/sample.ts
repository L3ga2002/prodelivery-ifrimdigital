export type Mode = 'foreground' | 'background';
export type Precision = 'precise' | 'approximate' | 'unknown';
export type Sample = {
  timestamp: number;
  coords: { latitude: number; longitude: number; accuracy: number | null };
  mocked?: boolean;
};
export const FRESH_MS = 90_000;
export const MAX_AGE_MS = 24 * 60 * 60 * 1000;
export const MAX_ACCURACY_M = 100;

export type Observation = {
  capturedAt: number; receivedAt: number; latitude: number; longitude: number;
  accuracy: number | null; flags: string[]; eligible: boolean; key: string;
};

export function validateSample(input: unknown, now: number, precision: Precision):
  { ok: true; value: Observation } | { ok: false; reason: string } {
  if (!input || typeof input !== 'object') return { ok: false, reason: 'invalid_sample' };
  const s = input as Sample;
  if (!Number.isFinite(s.timestamp) || s.timestamp <= 0) return { ok: false, reason: 'invalid_time' };
  if (s.timestamp > now + 5_000) return { ok: false, reason: 'future_time' };
  if (now - s.timestamp > MAX_AGE_MS) return { ok: false, reason: 'too_old' };
  const c = s.coords;
  if (!c || !Number.isFinite(c.latitude) || Math.abs(c.latitude) > 90 ||
      !Number.isFinite(c.longitude) || Math.abs(c.longitude) > 180) {
    return { ok: false, reason: 'invalid_coordinates' };
  }
  if (c.accuracy !== null && (!Number.isFinite(c.accuracy) || c.accuracy < 0)) {
    return { ok: false, reason: 'invalid_accuracy' };
  }
  if (s.mocked !== undefined && typeof s.mocked !== 'boolean') return { ok: false, reason: 'invalid_mock_flag' };
  const flags: string[] = [];
  if (now - s.timestamp > FRESH_MS) flags.push('stale');
  if (s.timestamp > now) flags.push('clock_ahead');
  if (precision === 'approximate') flags.push('approximate');
  if (precision === 'unknown') flags.push('precision_unknown');
  if (c.accuracy === null) flags.push('accuracy_unknown');
  else if (c.accuracy > MAX_ACCURACY_M) flags.push('low_accuracy');
  if (s.mocked) flags.push('mocked');
  return { ok: true, value: {
    capturedAt: s.timestamp, receivedAt: now, latitude: c.latitude, longitude: c.longitude,
    accuracy: c.accuracy, flags, eligible: flags.length === 0,
    key: JSON.stringify([s.timestamp, c.latitude, c.longitude, c.accuracy, s.mocked ?? null]),
  } };
}
