import test, { type TestContext } from 'node:test';
import assert from 'node:assert/strict';
import { setImmediate } from 'node:timers/promises';
import { NATIVE_WATCHDOG_MS, RecorderController } from '../src/controller.ts';
import { RecorderStore } from '../src/store.ts';
import { ForegroundWatch, UNCONFIRMED } from '../src/shutdown.ts';
import { database, deferred, FakeNative, NOW, sample } from './helpers.ts';

async function fixture(t: TestContext) {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const local = database();
  t.after(() => local.db.close());
  const native = new FakeNative();
  let id = 0;
  let renders = 0;
  const controller = new RecorderController(local.store, native, () => NOW, () => `s${++id}`, () => { renders++; });
  await controller.initialize();
  return { ...local, native, controller, renders: () => renders };
}

function diagnostic(controller: RecorderController, operation: 'start' | 'stop') {
  assert.equal(controller.state.phase, 'error');
  assert.equal(controller.state.sessionId, null);
  assert.equal(controller.state.nativeShutdown, 'unconfirmed');
  assert.equal(controller.state.watchdog, operation);
  assert.equal(controller.state.error, `native_${operation}_timeout_shutdown_unconfirmed`);
}

test('watchdog: permanently pending native Start closes/fences locally and publishes diagnostic without cancellation', async t => {
  const f = await fixture(t);
  f.native.waitStart = new Promise<void>(() => {});
  let settled = false;
  void f.controller.start('background').then(() => { settled = true; });
  await setImmediate();
  f.native.callback(sample());
  const observations = f.db.prepare("SELECT * FROM events WHERE kind='sample'").all();
  assert.equal(observations.length, 1);
  t.mock.timers.tick(NATIVE_WATCHDOG_MS - 1);
  assert.equal(f.controller.state.phase, 'starting');
  const renders = f.renders();
  t.mock.timers.tick(1);
  diagnostic(f.controller, 'start');
  assert.ok(f.renders() > renders);
  assert.equal(f.store.snapshot().active_session, null);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
  f.native.callback(sample(NOW + 1));
  const reopened = new RecorderStore(f.adapter);
  assert.equal(reopened.record('s1', 'background', sample(), NOW, 'precise'), 'late');
  assert.deepEqual(f.db.prepare("SELECT * FROM events WHERE kind='sample'").all(), observations);
  await f.controller.start('foreground');
  assert.equal(f.native.starts, 1);
  assert.equal(f.native.stops, 1); // Only initialization; cleanup still waits for Start.
  assert.equal(settled, false);
  diagnostic(f.controller, 'start');
});

test('watchdog: permanently pending native Stop escalates at the bound and repeated Stop coalesces', async t => {
  const f = await fixture(t);
  await f.controller.start('background');
  f.native.waitStop = new Promise<void>(() => {});
  const stopping = f.controller.stop();
  let settled = false;
  void stopping.then(() => { settled = true; });
  await setImmediate();
  assert.equal(f.store.snapshot().active_session, null);
  t.mock.timers.tick(NATIVE_WATCHDOG_MS - 1);
  assert.equal(f.controller.state.phase, 'stopping');
  t.mock.timers.tick(1);
  diagnostic(f.controller, 'stop');
  assert.equal(f.controller.stop(), stopping);
  assert.equal(f.controller.stop('ui_unmounted'), stopping);
  await f.controller.start('background');
  t.mock.timers.tick(NATIVE_WATCHDOG_MS * 2);
  await setImmediate();
  assert.equal(f.native.stops, 2);
  assert.equal(f.native.starts, 1);
  assert.equal(settled, false);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
  diagnostic(f.controller, 'stop');
});

test('watchdog: Stop waiting for permanently pending Start has its own deadline; stale Start timer cannot win', async t => {
  const f = await fixture(t);
  f.native.waitStart = new Promise<void>(() => {});
  void f.controller.start('foreground');
  await setImmediate();
  t.mock.timers.tick(5000);
  const stopping = f.controller.stop();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS - 5000);
  assert.equal(f.controller.state.phase, 'stopping');
  assert.equal(f.controller.state.watchdog, null);
  t.mock.timers.tick(5000);
  diagnostic(f.controller, 'stop');
  assert.equal(f.controller.stop(), stopping);
  f.native.callback(sample());
  assert.equal(f.store.snapshot().latest.some(row => row.kind === 'sample'), false);
  assert.equal(f.native.stops, 1);
});

test('watchdog: late Start resolution runs exactly one serialized cleanup and cannot clear the safety barrier', async t => {
  const f = await fixture(t);
  const startWait = deferred();
  const stopWait = deferred();
  f.native.waitStart = startWait.promise;
  f.native.waitStop = stopWait.promise;
  const starting = f.controller.start('background');
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  const cleanup = f.controller.stop();
  assert.equal(f.native.stops, 1);
  startWait.resolve();
  await starting;
  await setImmediate();
  assert.equal(f.native.stops, 2);
  assert.equal(f.controller.stop(), cleanup);
  await f.controller.start('background');
  assert.equal(f.native.starts, 1);
  diagnostic(f.controller, 'start');
  stopWait.resolve();
  await cleanup;
  await f.controller.stop(); // A new generation after cleanup still cannot reset anything.
  await f.controller.initialize();
  await f.controller.check();
  await f.controller.start('foreground');
  assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
  assert.equal(f.native.starts, 1);
  diagnostic(f.controller, 'start');
});

test('watchdog: late rejected Start still gets serialized cleanup, not a stale error or restart window', async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitStart = wait.promise;
  const starting = f.controller.start('background');
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  const cleanup = f.controller.stop();
  wait.reject(new Error('private native detail'));
  await Promise.all([starting, cleanup]);
  assert.equal(f.native.stops, 2);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
  diagnostic(f.controller, 'start');
});

for (const reject of [false, true]) test(`watchdog: late Stop ${reject ? 'rejection' : 'success'} cannot downgrade unconfirmed status`, async t => {
  const f = await fixture(t);
  await f.controller.start('background');
  const wait = deferred();
  f.native.waitStop = wait.promise;
  const stopping = f.controller.stop();
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  if (reject) wait.reject(new Error('private native detail'));
  else wait.resolve();
  await stopping;
  diagnostic(f.controller, 'stop');
  f.native.waitStop = null;
  await f.controller.stop();
  await f.controller.start('background');
  assert.equal(f.native.starts, 1);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
  diagnostic(f.controller, 'stop');
});

test('watchdog: persisted timeout survives store/controller reconstruction and late old-generation completion', async t => {
  const f = await fixture(t);
  await f.controller.start('background');
  const wait = deferred();
  f.native.waitStop = wait.promise;
  const oldStop = f.controller.stop();
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  const reopened = new RecorderStore(f.adapter);
  const native = new FakeNative();
  const cold = new RecorderController(reopened, native, () => NOW, () => 'replacement');
  await cold.initialize();
  await cold.stop();
  await cold.start('foreground');
  assert.equal(cold.state.nativeShutdown, 'unconfirmed');
  assert.equal(cold.state.phase, 'error');
  assert.equal(native.starts, 0);
  wait.resolve();
  await oldStop;
  assert.throws(() => reopened.start('replacement', 'background', NOW), /foreground_shutdown_unconfirmed/);
  assert.equal(reopened.snapshot().active_session, null);
  diagnostic(f.controller, 'stop');
});

test('watchdog: permanently pending initialization shutdown is diagnosed without Start or duplicate initialization', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const f = database();
  t.after(() => f.db.close());
  f.store.start('interrupted', 'background', NOW);
  const native = new FakeNative();
  native.waitStop = new Promise<void>(() => {});
  const controller = new RecorderController(f.store, native, () => NOW, () => 'new');
  const boot = controller.initialize();
  assert.equal(controller.initialize(), boot);
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  diagnostic(controller, 'stop');
  assert.equal(f.store.snapshot().active_session, null);
  await controller.start('background');
  assert.equal(native.starts, 0);
  assert.equal(native.stops, 1);
});

test('watchdog: explicit Stop during boot stays queued behind the pending native operation after escalation', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const f = database();
  t.after(() => f.db.close());
  const native = new FakeNative();
  const wait = deferred();
  native.waitStop = wait.promise;
  const controller = new RecorderController(f.store, native, () => NOW, () => 'new');
  const boot = controller.initialize();
  const stopping = controller.stop();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  diagnostic(controller, 'stop');
  assert.equal(controller.stop(), stopping);
  assert.equal(native.stops, 1);
  wait.resolve();
  await Promise.all([boot, stopping]);
  assert.equal(native.stops, 2);
  diagnostic(controller, 'stop');
});

test('watchdog: failed-Start cleanup with permanently pending Stop is also bounded and fenced', async t => {
  const f = await fixture(t);
  f.native.failStart = true;
  f.native.waitStop = new Promise<void>(() => {});
  void f.controller.start('background');
  await setImmediate();
  assert.equal(f.native.stops, 2);
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  diagnostic(f.controller, 'stop');
  const cleanup = f.controller.stop();
  assert.equal(f.controller.stop(), cleanup);
  await f.controller.start('background');
  assert.equal(f.native.starts, 1);
  assert.equal(f.native.stops, 2);
  assert.equal(f.store.snapshot().active_session, null);
});

test('watchdog: failed durable close still fences callbacks and reconstructed readers, preserves storage error', async t => {
  const f = await fixture(t);
  f.native.waitStart = new Promise<void>(() => {});
  void f.controller.start('background');
  await setImmediate();
  f.db.exec(`CREATE TRIGGER fail_close BEFORE UPDATE OF active_session ON control
    WHEN NEW.active_session IS NULL BEGIN SELECT RAISE(ABORT,'synthetic'); END;`);
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  assert.equal(f.controller.state.error, 'storage_close_failed');
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
  assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
  f.native.callback(sample());
  const reopened = new RecorderStore(f.adapter);
  assert.equal(reopened.active(), null);
  assert.equal(reopened.record('s1', 'background', sample(), NOW, 'precise'), 'late');
  assert.equal(f.store.snapshot().latest.some(row => row.kind === 'sample'), false);
  await f.controller.start('foreground');
  assert.equal(f.native.starts, 1);
});

test('watchdog: successful operations clear their timers; old generations cannot poison a newer recording', async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitStart = wait.promise;
  const starting = f.controller.start('background');
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS - 1);
  wait.resolve();
  await starting;
  await f.controller.stop();
  f.native.waitStart = null;
  await f.controller.start('background');
  t.mock.timers.tick(NATIVE_WATCHDOG_MS * 3);
  assert.equal(f.controller.state.phase, 'recording');
  assert.equal(f.controller.state.watchdog, null);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
  assert.equal(f.store.active()?.id, 's2');
  await f.controller.stop();
});

test('watchdog: Stop awaiting permission diagnoses cancellation, not an attempted sensor shutdown', async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitPermission = wait.promise;
  const starting = f.controller.start('foreground');
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  assert.equal(f.controller.state.phase, 'starting');
  assert.equal(f.controller.state.watchdog, null);
  const cleanup = f.controller.stop();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  assert.equal(f.controller.state.watchdog, 'cancellation_pending');
  assert.equal(f.controller.state.nativeShutdown, 'not_attempted');
  assert.equal(f.controller.state.error, 'start_cancellation_pending');
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
  assert.equal(f.store.snapshot().fault, null);
  assert.equal(f.native.starts, 0);
  assert.equal(f.native.stops, 1);
  assert.equal(f.controller.stop(), cleanup);
  await f.controller.start('background');
  assert.equal(f.native.requests.length, 1);
  wait.resolve();
  await Promise.all([starting, cleanup]);
  assert.equal(f.native.starts, 0);
  assert.equal(f.store.snapshot().sessionCount, 0);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
  assert.equal(f.controller.state.phase, 'idle');
  assert.equal(f.controller.state.watchdog, null);
});

test('watchdog: late foreground subscription is unsubscribed but void remove never acknowledges native shutdown', async t => {
  const f = await fixture(t);
  const wait = deferred();
  const watch = new ForegroundWatch();
  let removed = 0;
  f.native.start = async (_mode, callback) => {
    f.native.starts++;
    f.native.callback = callback;
    f.store.markShutdownUnconfirmed();
    watch.begin();
    await wait.promise;
    watch.attach({ remove: () => { removed++; } });
  };
  f.native.stop = async () => {
    f.native.stops++;
    watch.close();
    if (watch.unconfirmed) throw new Error(UNCONFIRMED);
  };
  const starting = f.controller.start('foreground');
  await setImmediate();
  const stopping = f.controller.stop();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  diagnostic(f.controller, 'stop');
  assert.equal(removed, 0);
  wait.resolve();
  await Promise.all([starting, stopping]);
  assert.equal(removed, 1);
  assert.equal(watch.unconfirmed, true);
  await f.controller.stop();
  assert.equal(removed, 1);
  diagnostic(f.controller, 'stop');
  assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
});

test('watchdog: foreground lifecycle cancellation awaiting native Start also exposes bounded owner intervention', async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitStart = wait.promise;
  const starting = f.controller.start('foreground');
  await setImmediate();
  const leaving = f.controller.lifecycle('inactive');
  assert.equal(f.store.snapshot().active_session, null);
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  diagnostic(f.controller, 'stop');
  wait.resolve();
  await Promise.all([starting, leaving]);
  assert.equal(f.native.stops, 2);
  diagnostic(f.controller, 'stop');
});

test('watchdog: Stop budget spans pending Start plus native Stop rather than restarting its deadline', async t => {
  const f = await fixture(t);
  const startWait = deferred();
  const stopWait = deferred();
  f.native.waitStart = startWait.promise;
  f.native.waitStop = stopWait.promise;
  const starting = f.controller.start('background');
  await setImmediate();
  const stopping = f.controller.stop();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS - 1000);
  startWait.resolve();
  await starting;
  await setImmediate();
  assert.equal(f.native.stops, 2);
  assert.equal(f.controller.state.phase, 'stopping');
  t.mock.timers.tick(1000);
  diagnostic(f.controller, 'stop');
  stopWait.resolve();
  await stopping;
  diagnostic(f.controller, 'stop');
});

test('watchdog: failed barrier persistence remains storage-uncertain until external recovery, never API-acknowledged', async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitStart = wait.promise;
  const starting = f.controller.start('background');
  await setImmediate();
  f.db.exec(`CREATE TRIGGER fail_barrier BEFORE UPDATE OF shutdown_unconfirmed ON native_barrier
    BEGIN SELECT RAISE(ABORT,'synthetic'); END;`);
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
  assert.equal(f.controller.state.error, 'storage_close_failed');
  assert.equal(f.store.snapshot().active_session, null);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false); // Persistence was genuinely refused.
  await f.controller.start('foreground');
  assert.equal(f.native.starts, 1);
  const cleanup = f.controller.stop();
  wait.resolve();
  await Promise.all([starting, cleanup]);
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
  assert.equal(f.controller.state.error, 'storage_close_failed');
  assert.equal(f.store.snapshot().fault, 'native_start_timeout_shutdown_unconfirmed');
  const native = new FakeNative();
  const cold = new RecorderController(new RecorderStore(f.adapter), native, () => NOW, () => 'cold');
  await cold.initialize();
  await cold.stop();
  await cold.start('background');
  assert.equal(cold.state.nativeShutdown, 'unconfirmed');
  assert.equal(native.starts, 0);
  assert.equal(f.store.snapshot().fault, 'native_start_timeout_shutdown_unconfirmed');
  const coldAgainNative = new FakeNative();
  const coldAgain = new RecorderController(new RecorderStore(f.adapter), coldAgainNative, () => NOW, () => 'cold-again');
  await coldAgain.initialize();
  await coldAgain.stop();
  await coldAgain.start('foreground');
  assert.equal(coldAgain.state.nativeShutdown, 'unconfirmed');
  assert.equal(coldAgainNative.starts, 0);
  f.db.exec('DROP TRIGGER fail_barrier');
  await f.controller.stop();
  assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
  await f.controller.start('background');
  assert.equal(f.native.starts, 1);
});

for (const reject of [false, true]) for (const reason of [null, 'ui_unmounted']) {
  test(`P1: ${reason ?? 'Stop'} preserves rejected-latch timeout before pending cleanup and cold controller; late ${reject ? 'reject' : 'success'}`, async t => {
    const f = await fixture(t);
    await f.controller.start('background');
    f.db.exec(`CREATE TRIGGER fail_barrier BEFORE UPDATE OF shutdown_unconfirmed ON native_barrier
      BEGIN SELECT RAISE(ABORT,'synthetic'); END;`);
    const firstWait = deferred();
    f.native.waitStop = firstWait.promise;
    const firstStop = f.controller.stop();
    await setImmediate();
    t.mock.timers.tick(NATIVE_WATCHDOG_MS);
    const fault = 'native_stop_timeout_shutdown_unconfirmed';
    assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
    assert.equal(f.store.snapshot().fault, fault);
    firstWait.resolve();
    await firstStop;
    const retryWait = deferred();
    f.native.waitStop = retryWait.promise;
    const retry = f.controller.stop(reason);
    // The safety evidence must survive synchronously, before any await/late callback.
    assert.equal(f.store.snapshot().fault, fault);
    assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
    let retrySettled = false;
    void retry.then(() => { retrySettled = true; });
    const native = new FakeNative();
    const cold = new RecorderController(new RecorderStore(f.adapter), native, () => NOW, () => 'cold');
    const boot = cold.initialize();
    assert.equal(f.store.snapshot().fault, fault);
    assert.equal(cold.state.nativeShutdown, 'unconfirmed');
    await boot;
    await cold.start('background');
    assert.equal(native.starts, 0);
    assert.equal(retrySettled, false);
    if (reject) retryWait.reject(new Error('private native detail'));
    else retryWait.resolve();
    await retry;
    await cold.start('foreground');
    assert.equal(native.starts, 0);
    assert.equal(f.store.snapshot().fault, fault);
    assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
    assert.equal(cold.state.nativeShutdown, 'unconfirmed');
  });
}

for (const reject of [false, true]) test(`P1: failed-Start cleanup preserves historical timeout before late native Stop ${reject ? 'reject' : 'success'}`, async t => {
  const f = await fixture(t);
  const permission = deferred();
  const cleanupWait = deferred();
  f.native.waitPermission = permission.promise;
  const starting = f.controller.start('foreground');
  await setImmediate();
  const fault = 'native_stop_timeout_shutdown_unconfirmed';
  f.store.setFault(fault);
  f.db.exec(`CREATE TRIGGER fail_barrier BEFORE UPDATE OF shutdown_unconfirmed ON native_barrier
    BEGIN SELECT RAISE(ABORT,'synthetic'); END;`);
  f.native.waitStop = cleanupWait.promise;
  f.native.permission.foreground = false;
  permission.resolve();
  await setImmediate();
  assert.equal(f.native.starts, 0);
  assert.equal(f.store.snapshot().fault, fault);
  const native = new FakeNative();
  const cold = new RecorderController(new RecorderStore(f.adapter), native, () => NOW, () => 'cold');
  await cold.initialize();
  await cold.start('background');
  assert.equal(native.starts, 0);
  assert.equal(f.store.snapshot().fault, fault);
  if (reject) cleanupWait.reject(new Error('private native detail'));
  else cleanupWait.resolve();
  await starting;
  assert.equal(f.store.snapshot().fault, fault);
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
});

for (const granted of [false, true]) test(`P2: legitimate long OS prompt ${granted ? 'grant' : 'deny'} creates no premature sensor barrier`, async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitPermission = wait.promise;
  const starting = f.controller.start('foreground');
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS * 4);
  assert.equal(f.controller.state.phase, 'starting');
  assert.equal(f.controller.state.watchdog, null);
  assert.equal(f.native.starts, 0);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
  assert.equal(f.store.snapshot().sessionCount, 0);
  f.native.permission.foreground = granted;
  wait.resolve();
  await starting;
  assert.equal(f.controller.state.phase, granted ? 'recording' : 'error');
  assert.equal(f.native.starts, granted ? 1 : 0);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
  if (granted) await f.controller.stop();
  else {
    assert.equal(f.controller.state.error, 'permission_denied');
    f.native.permission.foreground = true;
    await f.controller.start('foreground');
    assert.equal(f.native.starts, 1);
    await f.controller.stop();
  }
});

for (const result of ['grant', 'deny', 'reject'] as const) test(`P2: timed cancellation of OS prompt fences late ${result}, blocks Start only until queue completion`, async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitPermission = wait.promise;
  const starting = f.controller.start('foreground');
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS * 2);
  const stopping = f.controller.stop();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  assert.equal(f.controller.state.watchdog, 'cancellation_pending');
  assert.equal(f.controller.state.nativeShutdown, 'not_attempted');
  assert.equal(f.controller.stop('ui_unmounted'), stopping);
  await f.controller.start('background');
  assert.equal(f.native.requests.length, 1);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
  assert.equal(f.store.snapshot().fault, null);
  assert.equal(f.store.snapshot().sessionCount, 0);
  f.native.permission.foreground = result === 'grant';
  if (result === 'reject') wait.reject(new Error('private permission detail'));
  else wait.resolve();
  await Promise.all([starting, stopping]);
  assert.equal(f.native.starts, 0);
  assert.equal(f.controller.state.phase, 'idle');
  assert.equal(f.controller.state.watchdog, null);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
  f.native.waitPermission = null;
  f.native.permission.foreground = true;
  await f.controller.start('background');
  assert.equal(f.native.starts, 1);
  await f.controller.stop();
});

for (const cancel of [false, true]) test(`P2: long background availability wait ${cancel ? 'cancelled' : 'allowed'} is preflight, not a native sensor attempt`, async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.backgroundAvailable = async () => { await wait.promise; return true; };
  const starting = f.controller.start('background');
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS * 3);
  assert.equal(f.controller.state.watchdog, null);
  assert.equal(f.native.starts, 0);
  const stopping = cancel ? f.controller.stop() : null;
  if (cancel) {
    t.mock.timers.tick(NATIVE_WATCHDOG_MS);
    assert.equal(f.controller.state.watchdog, 'cancellation_pending');
    assert.equal(f.controller.state.nativeShutdown, 'not_attempted');
  }
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
  wait.resolve();
  await starting;
  if (stopping) await stopping;
  assert.equal(f.native.starts, cancel ? 0 : 1);
  assert.equal(f.native.requests.length, cancel ? 0 : 1);
  assert.equal(f.controller.state.watchdog, null);
  if (!cancel) await f.controller.stop();
});

test('P2: historical timeout appearing during OS prompt survives cancellation; never reports sensor-not-attempted as recovery', async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitPermission = wait.promise;
  const starting = f.controller.start('foreground');
  await setImmediate();
  const fault = 'native_stop_timeout_shutdown_unconfirmed';
  f.store.setFault(fault);
  f.db.exec(`CREATE TRIGGER fail_barrier BEFORE UPDATE OF shutdown_unconfirmed ON native_barrier
    BEGIN SELECT RAISE(ABORT,'synthetic'); END;`);
  const stopping = f.controller.stop('ui_unmounted');
  assert.equal(f.store.snapshot().fault, fault);
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  assert.notEqual(f.controller.state.watchdog, 'cancellation_pending');
  assert.equal(f.store.snapshot().fault, fault);
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
  wait.resolve();
  await Promise.all([starting, stopping]);
  await f.controller.start('background');
  assert.equal(f.native.starts, 0);
  assert.equal(f.store.snapshot().fault, fault);
});

test('P2: granted OS prompt starts a fresh native-only watchdog interval', async t => {
  const f = await fixture(t);
  const permission = deferred();
  const nativeStart = deferred();
  f.native.waitPermission = permission.promise;
  f.native.waitStart = nativeStart.promise;
  const starting = f.controller.start('foreground');
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS * 5);
  assert.equal(f.native.starts, 0);
  permission.resolve();
  await setImmediate();
  assert.equal(f.native.starts, 1);
  t.mock.timers.tick(NATIVE_WATCHDOG_MS - 1);
  assert.equal(f.controller.state.phase, 'starting');
  assert.equal(f.controller.state.watchdog, null);
  t.mock.timers.tick(1);
  diagnostic(f.controller, 'start');
  const stopping = f.controller.stop();
  nativeStart.resolve();
  await Promise.all([starting, stopping]);
  diagnostic(f.controller, 'start');
});

test('P2: permanently pending OS prompt cancellation never invents a persistent sensor attempt', async t => {
  const f = await fixture(t);
  f.native.waitPermission = new Promise<void>(() => {});
  void f.controller.start('foreground');
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS * 10);
  assert.equal(f.controller.state.phase, 'starting');
  const stopping = f.controller.stop();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS * 10);
  assert.equal(f.controller.state.watchdog, 'cancellation_pending');
  assert.equal(f.controller.state.nativeShutdown, 'not_attempted');
  assert.equal(f.controller.stop(), stopping);
  await f.controller.start('foreground');
  assert.equal(f.native.requests.length, 1);
  assert.equal(f.native.starts, 0);
  assert.equal(f.native.stops, 1);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
  assert.equal(f.store.snapshot().fault, null);
});

test('P1: late grant rechecks a historical durable fault before creating a session/native attempt', async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitPermission = wait.promise;
  const starting = f.controller.start('foreground');
  await setImmediate();
  const fault = 'native_start_timeout_shutdown_unconfirmed';
  f.store.setFault(fault);
  wait.resolve();
  await starting;
  assert.equal(f.native.starts, 0);
  assert.equal(f.store.snapshot().sessionCount, 0);
  assert.equal(f.store.snapshot().fault, fault);
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
  await f.controller.start('background');
  assert.equal(f.native.starts, 0);
});

test('P2: historical durable native-cleanup barrier is retained during preflight cancellation', async t => {
  const f = await fixture(t);
  const wait = deferred();
  f.native.waitPermission = wait.promise;
  const starting = f.controller.start('foreground');
  await setImmediate();
  const token = f.store.beginNativeStop(null, NOW, 'background_task_failed');
  assert.notEqual(token, null);
  const stopping = f.controller.stop();
  assert.equal(f.store.snapshot().nativeCleanupPending, true);
  assert.equal(f.store.snapshot().fault, 'background_task_failed');
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  assert.notEqual(f.controller.state.watchdog, 'cancellation_pending');
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
  wait.resolve();
  await Promise.all([starting, stopping]);
  assert.equal(f.native.starts, 0);
  assert.equal(f.store.snapshot().nativeCleanupPending, true);
  assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
  assert.equal(f.store.snapshot().fault, 'background_task_failed');
});

test('P1: failing close keeps its original safety fault in the fallback write, before pending native cleanup', async t => {
  const f = await fixture(t);
  const fault = 'native_start_timeout_shutdown_unconfirmed';
  f.store.setFault(fault);
  f.db.exec(`CREATE TRIGGER fail_close BEFORE UPDATE OF active_session ON control
    WHEN NEW.active_session IS NULL BEGIN SELECT RAISE(ABORT,'synthetic'); END;
    CREATE TRIGGER fail_barrier BEFORE UPDATE OF shutdown_unconfirmed ON native_barrier
    BEGIN SELECT RAISE(ABORT,'synthetic'); END;`);
  const wait = deferred();
  f.native.waitStop = wait.promise;
  const stopping = f.controller.stop('ui_unmounted');
  assert.equal(f.store.snapshot().fault, fault);
  await setImmediate();
  t.mock.timers.tick(NATIVE_WATCHDOG_MS);
  assert.equal(f.store.snapshot().fault, fault);
  assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
  assert.equal(f.controller.state.error, 'storage_close_failed');
  const native = new FakeNative();
  const cold = new RecorderController(new RecorderStore(f.adapter), native, () => NOW, () => 'cold');
  await cold.initialize();
  await cold.start('background');
  assert.equal(native.starts, 0);
  assert.equal(cold.state.nativeShutdown, 'unconfirmed');
  assert.equal(f.store.snapshot().fault, fault);
  wait.resolve();
  await stopping;
  assert.equal(f.store.snapshot().fault, fault);
});

for (const permissionDelay of [NATIVE_WATCHDOG_MS - 1000, NATIVE_WATCHDOG_MS + 1000]) {
  test(`P2: cancelled prompt resolving after ${permissionDelay}ms transitions to a bounded native Stop without false ack`, async t => {
    const f = await fixture(t);
    const permission = deferred();
    const nativeStop = deferred();
    f.native.waitPermission = permission.promise;
    f.native.waitStop = nativeStop.promise;
    const starting = f.controller.start('foreground');
    await setImmediate();
    const stopping = f.controller.stop();
    t.mock.timers.tick(permissionDelay);
    if (permissionDelay > NATIVE_WATCHDOG_MS) {
      assert.equal(f.controller.state.watchdog, 'cancellation_pending');
      assert.equal(f.controller.state.nativeShutdown, 'not_attempted');
      assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
    }
    permission.resolve();
    await starting;
    await setImmediate();
    assert.equal(f.native.starts, 0);
    assert.equal(f.native.stops, 2);
    assert.equal(f.controller.state.phase, 'stopping');
    assert.equal(f.controller.state.nativeShutdown, 'pending');
    assert.equal(f.controller.state.watchdog, null);
    t.mock.timers.tick(permissionDelay < NATIVE_WATCHDOG_MS ? 1000 : NATIVE_WATCHDOG_MS);
    diagnostic(f.controller, 'stop');
    nativeStop.resolve();
    await stopping;
    assert.equal(f.store.snapshot().shutdownUnconfirmed, true);
    diagnostic(f.controller, 'stop');
  });
}

for (const reject of [false, true]) for (const reason of [null, 'ui_unmounted']) {
  test(`P1: one failed snapshot read preserves unknown durable timeout during ${reason ?? 'Stop'}; cold reconstruction before late ${reject ? 'reject' : 'success'}`, async t => {
    const f = await fixture(t);
    const fault = 'native_stop_timeout_shutdown_unconfirmed';
    f.store.setFault(fault);
    f.db.exec(`CREATE TRIGGER fail_barrier BEFORE UPDATE OF shutdown_unconfirmed ON native_barrier
      BEGIN SELECT RAISE(ABORT,'synthetic'); END;`);
    const read = f.adapter.getAllSync.bind(f.adapter);
    let failedReads = 0;
    // Fail exactly one real snapshot query; SQLite and every subsequent query stay live.
    f.adapter.getAllSync = <T>(sql: string, params: (string | number | null)[] = []) => {
      if (failedReads === 0) { failedReads++; throw new Error('synthetic snapshot read failure'); }
      return read<T>(sql, params);
    };
    const wait = deferred();
    f.native.waitStop = wait.promise;
    const stopping = f.controller.stop(reason);
    let settled = false;
    void stopping.then(() => { settled = true; });
    // No ordinary reason may replace the safety evidence while its read is unknown.
    assert.equal(f.store.snapshot().fault, fault);
    assert.equal(f.store.snapshot().shutdownUnconfirmed, false);
    assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
    assert.equal(f.controller.state.error, 'storage_close_failed');
    assert.equal(f.controller.stop(), stopping);
    await f.controller.start('background');
    assert.equal(f.native.starts, 0);
    await setImmediate();
    assert.equal(f.native.stops, 2); // Initialization plus queued native cleanup; none skipped.
    const native = new FakeNative();
    const cold = new RecorderController(new RecorderStore(f.adapter), native, () => NOW, () => 'cold');
    await cold.initialize();
    await cold.start('background');
    assert.equal(native.starts, 0);
    assert.equal(cold.state.nativeShutdown, 'unconfirmed');
    assert.equal(f.store.snapshot().fault, fault);
    assert.equal(settled, false);
    if (reject) wait.reject(new Error('private native detail'));
    else wait.resolve();
    await stopping;
    await f.controller.start('foreground');
    await cold.start('foreground');
    assert.equal(f.native.starts, 0);
    assert.equal(native.starts, 0);
    assert.equal(f.controller.state.nativeShutdown, 'unconfirmed');
    assert.equal(cold.state.nativeShutdown, 'unconfirmed');
    assert.equal(f.store.snapshot().fault, fault);
    assert.equal(failedReads, 1);
  });
}
