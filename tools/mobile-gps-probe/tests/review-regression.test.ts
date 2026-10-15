import test from 'node:test';
import assert from 'node:assert/strict';
import { setImmediate } from 'node:timers/promises';
import { RecorderController } from '../src/controller.ts';
import { RecorderStore } from '../src/store.ts';
import { recordBackgroundBatch } from '../src/background.ts';
import { ForegroundWatch, UNCONFIRMED } from '../src/shutdown.ts';
import { database, deferred, FakeNative, NOW } from './helpers.ts';

test('R1 storage and native initialization failures preserve storage error and block restart until both recover', async t => {
  const f = database(); t.after(() => f.db.close());
  f.store.start('old', 'background', NOW);
  f.db.exec(`CREATE TRIGGER fail_close BEFORE UPDATE OF active_session ON control
    WHEN NEW.active_session IS NULL BEGIN SELECT RAISE(ABORT,'synthetic'); END;`);
  const native = new FakeNative(); native.failStop = true;
  const controller = new RecorderController(f.store, native, () => NOW, () => 'new');
  await controller.initialize();
  assert.equal(native.stops, 1); assert.equal(controller.state.error, 'storage_close_failed');
  assert.equal(controller.state.nativeShutdown, 'failed');
  await controller.start('background'); assert.equal(native.starts, 0);
  native.failStop = false; await controller.stop();
  await controller.start('background'); assert.equal(native.starts, 0);
  f.db.exec('DROP TRIGGER fail_close'); await controller.stop(); await controller.start('background');
  assert.equal(native.starts, 1); await controller.stop();
});

test('R2 pending background stop durably blocks replacement until native completion', async t => {
  const f = database(); t.after(() => f.db.close()); f.store.start('old', 'background', NOW);
  const other = new RecorderStore(f.adapter); const wait = deferred(); let stops = 0;
  const running = recordBackgroundBatch({ store: () => f.store, now: () => NOW,
    permissions: async () => new FakeNative().permission, stop: async () => { stops++; await wait.promise; },
  }, undefined, true);
  assert.equal(f.store.active(), null); assert.equal(other.snapshot().nativeCleanupPending, true);
  assert.throws(() => other.start('replacement', 'background', NOW), /native_cleanup_pending/);
  wait.resolve(); await running;
  other.start('replacement', 'background', NOW);
  assert.equal(other.active()?.id, 'replacement'); assert.equal(stops, 1);
});

test('R2 failed background stop remains durably blocked after UI close and store reconstruction', async t => {
  const f = database(); t.after(() => f.db.close()); f.store.start('old', 'background', NOW);
  await recordBackgroundBatch({ store: () => f.store, now: () => NOW,
    permissions: async () => new FakeNative().permission, stop: async () => { throw new Error('native failure'); },
  }, undefined, true);
  f.store.close(NOW);
  const reopened = new RecorderStore(f.adapter);
  assert.equal(reopened.snapshot().nativeCleanupPending, true);
  assert.throws(() => reopened.start('replacement', 'foreground', NOW), /native_cleanup_pending/);
});

test('R2 stale native completion token cannot write fault into a replacement session', t => {
  const f = database(); t.after(() => f.db.close()); f.store.start('old', 'background', NOW);
  const token = f.store.beginNativeStop('old', NOW, null)!;
  f.store.finishNativeStop(token); f.store.start('replacement', 'background', NOW);
  f.store.finishNativeStop(token, 'native_stop_failed');
  assert.equal(f.store.active()?.id, 'replacement'); assert.equal(f.store.snapshot().fault, null);
  assert.equal(f.store.beginNativeStop('old', NOW, 'stale_failure'), null);
});

test('R3 inactive during permission request cancels foreground before native registration', async t => {
  const f = database(); t.after(() => f.db.close()); const native = new FakeNative();
  const controller = new RecorderController(f.store, native, () => NOW, () => 's'); await controller.initialize();
  const wait = deferred(); native.waitPermission = wait.promise;
  const starting = controller.start('foreground'); await setImmediate();
  const leaving = controller.lifecycle('inactive'); wait.resolve(); await Promise.all([starting, leaving]);
  assert.equal(native.starts, 0); assert.equal(f.store.active(), null);
  assert.equal(controller.state.error, 'foreground_left_active');
});

test('R5 void unsubscribe is never interpreted as a native acknowledgement', () => {
  const watch = new ForegroundWatch(); let removes = 0;
  watch.close(); assert.equal(watch.unconfirmed, false);
  watch.begin(); watch.attach({ remove: () => { removes++; } }); watch.close(); watch.close();
  assert.equal(removes, 1); assert.equal(watch.unconfirmed, true);
});

test('R5 throwing or late-returned subscriptions keep the unconfirmed latch', () => {
  const watch = new ForegroundWatch(); watch.begin(); watch.close();
  watch.attach({ remove: () => { throw new Error('synthetic'); } });
  assert.throws(() => watch.close(), /synthetic/); assert.equal(watch.unconfirmed, true);
  watch.close(); assert.equal(watch.unconfirmed, true);
});

test('R5 local session closes but unconfirmed native shutdown blocks Start and survives controller recreation', async t => {
  const f = database(); t.after(() => f.db.close()); const native = new FakeNative();
  const controller = new RecorderController(f.store, native, () => NOW, () => 's'); await controller.initialize();
  await controller.start('foreground'); native.stop = async () => { throw new Error(UNCONFIRMED); };
  await controller.stop();
  assert.equal(f.store.active(), null); assert.equal(f.store.snapshot().active_session, null);
  assert.equal(controller.state.nativeShutdown, 'unconfirmed'); assert.equal(controller.state.error, UNCONFIRMED);
  await controller.start('foreground'); assert.equal(native.starts, 1);
  const replacement = new FakeNative(); const reopened = new RecorderStore(f.adapter);
  const cold = new RecorderController(reopened, replacement, () => NOW, () => 'new');
  await cold.initialize(); await cold.stop(); await cold.start('background');
  assert.equal(cold.state.nativeShutdown, 'unconfirmed'); assert.equal(cold.state.phase, 'error');
  assert.equal(replacement.starts, 0); assert.equal(reopened.snapshot().shutdownUnconfirmed, true);
});

test('R5 durable foreground intent survives process loss before any Stop callback', async t => {
  const f = database(); t.after(() => f.db.close()); f.store.start('interrupted', 'foreground', NOW);
  f.store.markShutdownUnconfirmed(); const native = new FakeNative();
  const cold = new RecorderController(new RecorderStore(f.adapter), native, () => NOW, () => 'new');
  await cold.initialize(); await cold.start('foreground');
  assert.equal(cold.state.nativeShutdown, 'unconfirmed'); assert.equal(native.starts, 0);
  assert.equal(f.store.snapshot().active_session, null);
});
