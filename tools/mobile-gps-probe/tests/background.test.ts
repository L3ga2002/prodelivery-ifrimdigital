import test from 'node:test';
import assert from 'node:assert/strict';
import { recordBackgroundBatch } from '../src/background.ts';
import { database, deferred, FakeNative, NOW, sample } from './helpers.ts';

function fixture(limit = 1000) {
  const local = database(':memory:', limit); const native = new FakeNative();
  return { ...local, native, run: (data: unknown, error = false) => recordBackgroundBatch({
    store: () => local.store, permissions: () => native.permissions(), stop: () => native.stop(), now: () => NOW,
  }, data, error) };
}
test('headless callback without consented session stops native and stores no sample', async () => {
  const f = fixture(); await f.run({ locations: [sample()] });
  assert.equal(f.store.snapshot().count, 0); assert.equal(f.native.stops, 1); f.db.close();
});
test('headless batch deduplicates and continues after cached old sample', async () => {
  const f = fixture(); f.store.start('s', 'background', NOW);
  await f.run({ locations: [sample(NOW - 1), sample(), sample()] });
  assert.equal(f.store.snapshot().count, 2); assert.equal(f.store.snapshot().late, 1);
  assert.equal(f.store.snapshot().duplicates, 1); assert.equal(f.native.stops, 0); f.db.close();
});
test('headless capacity fills without deletion, closes gate and stops native', async () => {
  const f = fixture(2); f.store.start('s', 'background', NOW);
  await f.run({ locations: [sample()] });
  assert.equal(f.store.snapshot().count, 2); assert.equal(f.store.snapshot().fault, 'capacity');
  assert.equal(f.store.active(), null); assert.equal(f.native.stopped, true); f.db.close();
});
test('headless permission revocation is durable and no sample is captured', async () => {
  const f = fixture(); f.store.start('s', 'background', NOW); f.native.permission.foreground = false;
  await f.run({ locations: [sample()] });
  assert.equal(f.store.active(), null); assert.equal(f.store.snapshot().fault, 'background_task_failed');
  assert.equal(f.store.snapshot().latest.some(r => r.kind === 'sample'), false); f.db.close();
});
test('headless native stop failure is visible in durable status', async () => {
  const f = fixture(); f.store.start('s', 'background', NOW); f.native.failStop = true;
  await f.run(undefined, true);
  assert.equal(f.store.snapshot().fault, 'native_stop_failed'); assert.equal(f.store.active(), null); f.db.close();
});
test('UI stop while headless permission check awaits rejects entire late batch', async () => {
  const f = fixture(); f.store.start('s', 'background', NOW); const wait = deferred();
  const running = recordBackgroundBatch({ store: () => f.store, now: () => NOW,
    permissions: async () => { await wait.promise; return f.native.permission; }, stop: () => f.native.stop(),
  }, { locations: [sample()] });
  f.store.close(NOW); wait.resolve(); await running;
  assert.equal(f.store.snapshot().latest.some(r => r.kind === 'sample'), false); f.db.close();
});
test('unavailable database still attempts native shutdown and surfaces sanitized error', async () => {
  let stops = 0;
  await assert.rejects(recordBackgroundBatch({ store: () => { throw new Error('private detail'); },
    permissions: async () => new FakeNative().permission, stop: async () => { stops++; }, now: () => NOW,
  }, { locations: [] }), /^Error: background_task_failed_storage_unavailable$/);
  assert.equal(stops, 1);
});
