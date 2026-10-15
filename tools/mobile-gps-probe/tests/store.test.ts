import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { RecorderStore, SESSION_LIMIT } from '../src/store.ts';
import { database, NOW, sample } from './helpers.ts';

test('SQLite persists session, sequence and dedup across reopened connection', () => {
  mkdirSync('.tmp', { recursive: true });
  const path = join(mkdtempSync(join('.tmp', 'storage-')), 'probe.db');
  const first = database(path);
  first.store.start('s1', 'background', NOW);
  assert.equal(first.store.record('s1', 'background', sample(), NOW, 'precise'), 'saved');
  first.db.close();
  const second = database(path);
  assert.equal(second.store.active()?.id, 's1');
  assert.equal(second.store.record('s1', 'background', sample(), NOW + 1, 'precise'), 'duplicate');
  second.store.record('s1', 'background', sample(NOW + 2), NOW + 2, 'precise');
  const rows = second.db.prepare('SELECT * FROM events ORDER BY id').all();
  assert.deepEqual(rows.map(r => r.sequence), [1, 2, 3]);
  assert.equal(rows[1].captured_at, NOW);
  assert.equal(rows[1].received_at, NOW);
  assert.equal(rows[1].accuracy, 12);
  assert.equal(rows[1].source, 'background');
  second.db.close();
});
test('bounded storage preserves every prior row and refuses further sessions', () => {
  const { store, db } = database(':memory:', 3);
  store.start('s1', 'foreground', NOW);
  store.record('s1', 'foreground', sample(), NOW, 'precise');
  store.record('s1', 'foreground', sample(NOW + 1), NOW + 1, 'precise');
  const before = db.prepare('SELECT * FROM events').all();
  assert.equal(store.record('s1', 'foreground', sample(NOW + 2), NOW + 2, 'precise'), 'capacity');
  assert.equal(store.active(), null);
  assert.equal(store.snapshot().fault, 'capacity');
  assert.deepEqual(db.prepare('SELECT * FROM events').all(), before);
  assert.throws(() => store.start('s2', 'foreground', NOW + 3), /capacity/);
  db.close();
});
test('stop closes durable gate before late callbacks, including another SQLite connection', () => {
  mkdirSync('.tmp', { recursive: true });
  const path = join(mkdtempSync(join('.tmp', 'stop-')), 'probe.db');
  const a = database(path); const b = database(path);
  a.store.start('s1', 'background', NOW);
  a.store.close(NOW + 1);
  assert.equal(b.store.record('s1', 'background', sample(NOW + 2), NOW + 2, 'precise'), 'late');
  assert.equal(b.store.snapshot().latest.filter(x => x.kind === 'sample').length, 0);
  assert.equal(b.store.snapshot().late, 1);
  a.db.close(); b.db.close();
});
test('old session, wrong mode and cached sample predating start are rejected', () => {
  const { store, db } = database();
  store.start('s1', 'background', NOW); store.close(NOW + 1);
  store.start('s2', 'foreground', NOW + 2);
  assert.equal(store.record('s1', 'foreground', sample(NOW + 3), NOW + 3, 'precise'), 'late');
  assert.equal(store.record('s2', 'background', sample(NOW + 3), NOW + 3, 'precise'), 'late');
  assert.equal(store.record('s2', 'foreground', sample(), NOW + 3, 'precise'), 'late');
  db.close();
});
test('out-of-order and stale samples cannot become eligible; invalid payload has no coordinates', () => {
  const { store, db } = database();
  store.start('s', 'background', NOW - 200_000);
  store.record('s', 'background', sample(), NOW, 'precise');
  store.record('s', 'background', sample(NOW - 100_000), NOW, 'precise');
  store.record('s', 'background', { ...sample(), coords: { latitude: 100, longitude: 26, accuracy: 2 } }, NOW, 'precise');
  const rows = db.prepare('SELECT * FROM events ORDER BY id').all();
  assert.equal(rows[2].flags, 'stale,out_of_order'); assert.equal(rows[2].eligible, 0);
  assert.equal(rows[3].latitude, null); assert.equal(rows[3].longitude, null);
  assert.equal(rows[3].flags, 'invalid_coordinates');
  assert.equal(store.snapshot().rejected, 1);
  db.close();
});
test('SQLite uniqueness and transaction rollback prevent competing sessions', () => {
  const { store, db } = database();
  store.start('one', 'foreground', NOW);
  assert.throws(() => store.start('two', 'foreground', NOW), /session_active/);
  assert.equal(store.snapshot().sessionCount, 1);
  assert.equal(store.active()?.id, 'one');
  store.close(NOW);
  assert.throws(() => store.start('one', 'foreground', NOW), /UNIQUE/);
  assert.equal(store.active(), null);
  db.close();
});
test('session table is bounded independently; no resets or deletes', () => {
  const { store, db } = database();
  for (let i = 0; i < SESSION_LIMIT; i++) { store.start(`s${i}`, 'foreground', NOW); store.close(NOW); }
  assert.throws(() => store.start('overflow', 'foreground', NOW), /capacity/);
  assert.equal(store.snapshot().sessionCount, SESSION_LIMIT);
  db.close();
});
test('unknown schema version is refused without changing database', () => {
  const { db, adapter } = database();
  db.exec('PRAGMA user_version=2');
  assert.throws(() => new RecorderStore(adapter), /unsupported_schema/);
  assert.equal(db.prepare('PRAGMA user_version').get()?.user_version, 2);
  db.close();
});
test('a new session never inherits the previous sessions current observation', () => {
  const { store, db } = database();
  store.start('s1', 'foreground', NOW); store.record('s1', 'foreground', sample(), NOW, 'precise');
  assert.equal(store.snapshot().currentSample?.session_id, 's1');
  store.close(NOW); store.start('s2', 'foreground', NOW + 1);
  assert.equal(store.snapshot().currentSample, null); db.close();
});
test('failed durable close still blocks callbacks in the same runtime', () => {
  const { store, db } = database();
  store.start('s1', 'background', NOW);
  db.exec(`CREATE TRIGGER fail_close BEFORE UPDATE OF active_session ON control
    WHEN NEW.active_session IS NULL BEGIN SELECT RAISE(ABORT,'test close failure'); END;`);
  assert.throws(() => store.close(NOW), /test close failure/);
  assert.equal(store.record('s1', 'background', sample(), NOW, 'precise'), 'late');
  assert.equal(store.snapshot().latest.some(r => r.kind === 'sample'), false); db.close();
});
test('a persisted stop fault rejects callbacks from a new storage instance', () => {
  const { store, db, adapter } = database();
  store.start('s1', 'background', NOW); store.setFault('storage_close_failed');
  const reopened = new RecorderStore(adapter);
  assert.equal(reopened.active(), null);
  assert.equal(reopened.record('s1', 'background', sample(), NOW, 'precise'), 'late'); db.close();
});
