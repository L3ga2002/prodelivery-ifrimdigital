import test from 'node:test';
import assert from 'node:assert/strict';
import { setImmediate } from 'node:timers/promises';
import { RecorderController } from '../src/controller.ts';
import { database, deferred, FakeNative, NOW, sample } from './helpers.ts';

async function fixture(limit = 1000) {
  const local = database(':memory:', limit);
  const native = new FakeNative();
  let id = 0;
  const controller = new RecorderController(local.store, native, () => NOW, () => `s${++id}`);
  await controller.initialize();
  return { ...local, native, controller };
}
test('initialization never requests permissions or starts location', async () => {
  const f = await fixture();
  assert.deepEqual(f.native.requests, []); assert.equal(f.native.starts, 0);
  assert.equal(f.controller.state.phase, 'idle'); f.db.close();
});
test('explicit start and stop invalidate both captured callback and durable session', async () => {
  const f = await fixture(); await f.controller.start('foreground');
  f.native.callback(sample());
  const late = f.native.callback;
  await f.controller.stop(); late(sample(NOW + 1));
  assert.equal(f.store.snapshot().count, 3);
  assert.equal(f.store.active(), null); assert.equal(f.native.stopped, true);
  assert.equal(f.controller.state.phase, 'idle'); f.db.close();
});
test('duplicate Start cannot create another subscription/session', async () => {
  const f = await fixture(); const wait = deferred(); f.native.waitStart = wait.promise;
  const first = f.controller.start('foreground'); await setImmediate();
  await f.controller.start('foreground');
  assert.equal(f.native.starts, 1); assert.equal(f.store.snapshot().sessionCount, 1);
  assert.equal(f.controller.state.notice, 'start_unavailable_or_already_pending');
  wait.resolve(); await first; await f.controller.stop(); f.db.close();
});
test('Stop while permission request awaits prevents any native start', async () => {
  const f = await fixture(); const wait = deferred(); f.native.waitPermission = wait.promise;
  const first = f.controller.start('foreground'); await setImmediate();
  const stopping = f.controller.stop();
  wait.resolve(); await Promise.all([first, stopping]);
  assert.equal(f.native.starts, 0); assert.equal(f.controller.state.phase, 'idle'); f.db.close();
});
test('Stop during native start waits for resource then tears it down; no late write', async () => {
  const f = await fixture(); const wait = deferred(); f.native.waitStart = wait.promise;
  const starting = f.controller.start('foreground'); await setImmediate();
  const stopping = f.controller.stop(); f.native.callback(sample());
  assert.equal(f.store.active(), null); assert.equal(f.controller.state.phase, 'stopping');
  wait.resolve(); await Promise.all([starting, stopping]);
  assert.equal(f.native.stopped, true); assert.equal(f.controller.state.phase, 'idle');
  assert.equal(f.store.snapshot().latest.some(row => row.kind === 'sample'), false); f.db.close();
});
test('background unavailable does not ask for any permissions', async () => {
  const f = await fixture(); f.native.available = false;
  await f.controller.start('background');
  assert.equal(f.controller.state.error, 'background_unavailable');
  assert.deepEqual(f.native.requests, []); assert.equal(f.native.starts, 0); f.db.close();
});
for (const key of ['foreground', 'background', 'services'] as const) test(`denied ${key} blocks native start`, async () => {
  const f = await fixture(); f.native.permission[key] = false;
  await f.controller.start('background'); assert.equal(f.native.starts, 0);
  assert.equal(f.controller.state.phase, 'error'); assert.equal(f.store.active(), null); f.db.close();
});
test('permission revocation while recording closes native and local recorder', async () => {
  const f = await fixture(); await f.controller.start('background');
  f.native.permission.background = false; await f.controller.check();
  assert.equal(f.store.active(), null); assert.equal(f.native.stopped, true);
  assert.equal(f.controller.state.error, 'permission_or_services_revoked'); f.db.close();
});
test('foreground mode ends on leaving active; background mode remains and logs lifecycle', async () => {
  const f = await fixture(); await f.controller.start('foreground');
  await f.controller.lifecycle('background'); assert.equal(f.native.stopped, true);
  await f.controller.start('background'); await f.controller.lifecycle('background');
  assert.equal(f.controller.state.phase, 'recording');
  assert.ok(f.store.snapshot().latest.some(r => r.flags === 'background'));
  await f.controller.stop(); f.db.close();
});
test('partial native start failure cleans up and exposes sanitized failure', async () => {
  const f = await fixture(); f.native.failStart = true;
  await f.controller.start('foreground');
  assert.equal(f.controller.state.error, 'start_failed'); assert.equal(f.native.stopped, true);
  assert.equal(f.store.active(), null); f.db.close();
});
test('failed native Stop stays error and blocks restart until explicit retry succeeds', async () => {
  const f = await fixture(); await f.controller.start('foreground'); f.native.failStop = true;
  await f.controller.stop(); assert.equal(f.controller.state.error, 'native_stop_failed');
  f.native.callback(sample()); assert.equal(f.store.snapshot().latest.some(r => r.kind === 'sample'), false);
  await f.controller.start('foreground'); assert.equal(f.native.starts, 1);
  f.native.failStop = false; await f.controller.stop();
  assert.equal(f.controller.state.phase, 'idle'); f.db.close();
});
test('capacity stops recorder without removing old observations', async () => {
  const f = await fixture(2); await f.controller.start('foreground');
  f.native.callback(sample()); f.native.callback(sample(NOW + 1)); await setImmediate();
  assert.equal(f.controller.state.error, 'capacity'); assert.equal(f.native.stopped, true);
  assert.equal(f.store.snapshot().count, 2); f.db.close();
});
test('UI process recovery closes previous session without automatically starting a new one', async () => {
  const f = database(); f.store.start('old', 'background', NOW);
  const native = new FakeNative();
  const controller = new RecorderController(f.store, native, () => NOW + 1, () => 'new');
  await controller.initialize();
  assert.equal(f.store.active(), null); assert.equal(native.starts, 0);
  assert.equal(controller.state.error, 'interrupted_session'); f.db.close();
});
test('Stop during boot waits for initialization cleanup and never requests tracking', async () => {
  const f = database(); const native = new FakeNative(); const wait = deferred(); native.waitStop = wait.promise;
  const controller = new RecorderController(f.store, native, () => NOW, () => 's');
  const boot = controller.initialize(); const stop = controller.stop();
  assert.equal(controller.state.phase, 'stopping'); wait.resolve(); await Promise.all([boot, stop]);
  assert.equal(controller.state.phase, 'idle'); assert.equal(native.starts, 0); f.db.close();
});
test('explicit Stop during failed-start cleanup does not expose a restart window', async () => {
  const f = await fixture(); const wait = deferred(); f.native.waitStop = wait.promise; f.native.failStart = true;
  const start = f.controller.start('foreground'); await setImmediate();
  const stop = f.controller.stop(); wait.resolve(); await Promise.all([start, stop]);
  assert.equal(f.controller.state.phase, 'idle'); assert.equal(f.store.active(), null); f.db.close();
});
test('reaching capacity with no more location callbacks still stops on health check', async () => {
  const f = await fixture(2); await f.controller.start('foreground'); f.native.callback(sample());
  await f.controller.check();
  assert.equal(f.native.stopped, true); assert.equal(f.controller.state.error, 'capacity'); f.db.close();
});
