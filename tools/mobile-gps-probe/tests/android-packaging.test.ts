import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const { expo } = JSON.parse(readFileSync(
  process.env.PROBE_CONFIG_PATH ?? new URL('../app.json', import.meta.url), 'utf8',
));

test('Android persisted Expo jobs declare the required boot permission', () => {
  assert.ok(expo.android.permissions?.includes('android.permission.RECEIVE_BOOT_COMPLETED'));
  assert.equal(new Set(expo.android.permissions).size, expo.android.permissions.length);
});

test('native runtime fix has an identifiable newer Android version', () => {
  assert.ok(Number.isInteger(expo.android.versionCode) && expo.android.versionCode >= 2);
});

test('probe stays isolated with OTA and Android backup disabled', () => {
  assert.equal(expo.android.package, 'ro.ifrimdigital.prodelivery.gpsprobe');
  assert.equal(expo.updates.enabled, false);
  assert.equal(expo.android.allowBackup, false);
});

test('background location and visible service remain configured', () => {
  const plugin = expo.plugins.find((entry: unknown) => Array.isArray(entry) && entry[0] === 'expo-location');
  assert.equal(plugin?.[1].isAndroidBackgroundLocationEnabled, true);
  assert.equal(plugin?.[1].isAndroidForegroundServiceEnabled, true);
});

test('backup protections and embedded diagnostic build plugins remain enabled', () => {
  assert.ok(expo.plugins.includes('./plugins/android-backup-protection.cjs'));
  assert.ok(expo.plugins.includes('./plugins/android-diagnostic-build.cjs'));
});
