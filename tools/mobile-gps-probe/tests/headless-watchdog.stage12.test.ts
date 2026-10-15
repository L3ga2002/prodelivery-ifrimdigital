import test from 'node:test';
import assert from 'node:assert/strict';
import { setImmediate } from 'node:timers/promises';
import { recordBackgroundBatch } from '../src/background.ts';
import { RecorderStore } from '../src/store.ts';
import { database, deferred, FakeNative, NOW, sample } from './helpers.ts';
const BOUND = 15_000;
const TIMEOUT = 'native_stop_timeout_shutdown_unconfirmed';
function fixture(t: import('node:test').TestContext) {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const f = database(); t.after(() => f.db.close()); const native = new FakeNative();
  const run = () => recordBackgroundBatch({ store: () => f.store, permissions: () => native.permissions(), stop: () => native.stop(), now: () => NOW }, undefined, true);
  return { ...f, native, run };
}
test('headless deadline closes durably, settles finitely and coalesces a second callback; late ACK cannot authorize Start', async t => {
  const f = fixture(t); f.store.start('a','background',NOW); const wait = deferred(); f.native.waitStop = wait.promise;
  const running=f.run(); let settled=false; void running.then(()=>{settled=true;});
  try {
    await setImmediate(); t.mock.timers.tick(BOUND-1); assert.equal(settled,false);
    t.mock.timers.tick(1); await setImmediate();
    assert.equal(settled,true); assert.equal(f.store.snapshot().fault,TIMEOUT);
    assert.equal(f.store.snapshot().shutdownUnconfirmed,true); assert.equal(f.store.active(),null);
    const reopened=new RecorderStore(f.adapter); assert.throws(()=>reopened.start('b','background',NOW));
    await f.run(); assert.equal(f.native.stops,1); assert.equal(f.store.record('a','background',sample(),NOW,'precise'),'late');
  } finally { wait.resolve(); await running; }
  await setImmediate(); assert.equal(f.store.snapshot().fault,TIMEOUT);
  assert.equal(f.store.snapshot().nativeCleanupPending,true); assert.throws(()=>f.store.start('c','background',NOW));
});
test('headless late native rejection cannot downgrade durable timeout diagnostic', async t => {
  const f=fixture(t);f.store.start('a','background',NOW);const wait=deferred();f.native.waitStop=wait.promise;
  const running=f.run();try { await setImmediate();t.mock.timers.tick(BOUND);await setImmediate();assert.equal(f.store.snapshot().fault,TIMEOUT); }
  finally { wait.reject(new Error('private native detail'));await running; }
  await setImmediate();assert.equal(f.store.snapshot().fault,TIMEOUT);assert.equal(f.store.snapshot().shutdownUnconfirmed,true);
});
test('headless native rejection preserves an existing shutdown timeout rather than overwriting it', async t => {
  const f=fixture(t);f.store.setFault('native_start_timeout_shutdown_unconfirmed');f.store.markShutdownUnconfirmed();f.native.failStop=true;
  await f.run();assert.equal(f.store.snapshot().fault,'native_start_timeout_shutdown_unconfirmed');assert.equal(f.store.snapshot().shutdownUnconfirmed,true);
});
test('headless no-session callback preserves the one-way shutdown latch as a conservative diagnostic', async t => {
  const f=fixture(t);f.store.markShutdownUnconfirmed();await f.run();
  assert.equal(f.store.snapshot().fault,'foreground_shutdown_unconfirmed');assert.equal(f.store.snapshot().shutdownUnconfirmed,true);assert.throws(()=>f.store.start('new','background',NOW));
});
test('headless unknown durable read cannot erase the stored safety fault through fallback shutdown', async t => {
  const f=fixture(t);f.store.setFault(TIMEOUT);let once=true;const snapshot=f.store.snapshot.bind(f.store);
  f.store.snapshot=()=>{if(once){once=false;throw new Error('private SQL');}return snapshot();};
  await assert.rejects(f.run(),/^Error: background_task_failed_storage_unavailable$/);
  assert.equal(snapshot().fault,TIMEOUT);assert.equal(snapshot().shutdownUnconfirmed,true);assert.equal(f.native.stops,1);
});
test('headless unreadable storage still bounds a pending native stop and emits only sanitized failure', async t => {
  t.mock.timers.enable({apis:['setTimeout']});const wait=deferred();let stops=0;let settled=false;
  const running=recordBackgroundBatch({store:()=>{throw new Error('private path');},permissions:async()=>new FakeNative().permission,stop:async()=>{stops++;await wait.promise;},now:()=>NOW},undefined);
  void running.then(()=>{},()=>{settled=true;});
  try {await setImmediate();t.mock.timers.tick(BOUND);await setImmediate();assert.equal(settled,true);assert.equal(stops,1);}
  finally {wait.resolve();await assert.rejects(running,/^Error: background_task_failed_storage_unavailable$/);}
});
test('headless failed timeout-latch write leaves existing durable pending barrier closed after late ACK', async t => {
  const f=fixture(t);f.store.start('a','background',NOW);const wait=deferred();f.native.waitStop=wait.promise;
  f.store.markShutdownUnconfirmed=()=>{throw new Error('private write failure');};const running=f.run();
  try {await setImmediate();t.mock.timers.tick(BOUND);await setImmediate();assert.equal(f.store.snapshot().nativeCleanupPending,true);}
  finally {wait.resolve();await running;}
  await setImmediate();assert.equal(f.store.snapshot().nativeCleanupPending,true);assert.throws(()=>new RecorderStore(f.adapter).start('b','background',NOW));
});
test('headless timely acknowledged stop cancels diagnostic timer without inventing a shutdown latch', async t => {
  const f=fixture(t);f.store.start('a','background',NOW);await f.run();t.mock.timers.tick(BOUND*2);
  assert.equal(f.store.snapshot().fault,'background_task_failed');assert.equal(f.store.snapshot().nativeCleanupPending,false);assert.equal(f.store.snapshot().shutdownUnconfirmed,false);
  assert.equal(f.native.stops,1);f.store.start('b','background',NOW);
});

test('headless transient active-session read failure still stops native and preserves unknown safety evidence', async t => {
  const f=fixture(t);f.store.start('a','background',NOW);f.store.setFault(TIMEOUT);const active=f.store.active.bind(f.store);let once=true;
  f.store.active=()=>{if(once){once=false;throw new Error('private SQL read');}return active();};
  await assert.rejects(f.run(),/^Error: background_task_failed_storage_unavailable$/);
  assert.equal(f.native.stops,1);assert.equal(f.store.snapshot().fault,TIMEOUT);assert.equal(f.store.snapshot().shutdownUnconfirmed,true);
});
