import test from 'node:test';
import assert from 'node:assert/strict';
import { validateSample, FRESH_MS, MAX_AGE_MS } from '../src/sample.ts';
import { NOW, sample } from './helpers.ts';

test('finite coordinates include zero and boundaries; only clean observations eligible', () => {
  const s = sample(); s.coords.latitude = 0; s.coords.longitude = -180; s.coords.accuracy = 0;
  const v = validateSample(s, NOW, 'precise');
  assert.equal(v.ok && v.value.eligible, true);
});
for (const [name, value] of Object.entries({
  null: null, missing: {}, nanTime: { ...sample(), timestamp: NaN }, old: sample(NOW - MAX_AGE_MS - 1),
  future: sample(NOW + 5001), lat: { ...sample(), coords: { ...sample().coords, latitude: 91 } },
  lon: { ...sample(), coords: { ...sample().coords, longitude: Infinity } },
  accuracy: { ...sample(), coords: { ...sample().coords, accuracy: -1 } },
  mockType: { ...sample(), mocked: 'false' },
})) test(`reject malformed observation: ${name}`, () => assert.equal(validateSample(value, NOW, 'precise').ok, false));
test('stale, approximate, mocked and unknown accuracy remain observations but never eligible', () => {
  const input = { ...sample(NOW - FRESH_MS - 1), mocked: true, coords: { ...sample().coords, accuracy: null } };
  const result = validateSample(input, NOW, 'approximate');
  assert.ok(result.ok);
  assert.equal(result.value.eligible, false);
  assert.deepEqual(result.value.flags, ['stale', 'approximate', 'accuracy_unknown', 'mocked']);
});
test('clock tolerance and permission precision unknown do not imply eligibility', () => {
  const result = validateSample(sample(NOW + 5000), NOW, 'unknown');
  assert.ok(result.ok); assert.deepEqual(result.value.flags, ['clock_ahead', 'precision_unknown']);
});
test('accuracy threshold and age boundary are explicit', () => {
  const s = sample(NOW - FRESH_MS); s.coords.accuracy = 100;
  const good = validateSample(s, NOW, 'precise'); assert.ok(good.ok && good.value.eligible);
  s.coords.accuracy = 100.01;
  const bad = validateSample(s, NOW, 'precise'); assert.ok(bad.ok && !bad.value.eligible);
});
