import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const plugin=require('../plugins/android-location-stop-lifecycle.cjs').testing;
const source=path.resolve(import.meta.dirname,'..');
const hash=(b:Buffer|string)=>crypto.createHash('sha256').update(b).digest('hex').toUpperCase();
function fixture() {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'pd-stage12-plugin-')); // Retain every synthetic fixture.
  fs.writeFileSync(path.join(root,'package.json'),JSON.stringify({expo:{autolinking:{android:{buildFromSource:['expo-location','expo-task-manager','unimodules-app-loader']}}}}),{flag:'wx'});
  const marker={projectRoot:root,purpose:'stage12-isolated-gps-build',nonce:crypto.randomUUID().replaceAll('-','')};
  fs.writeFileSync(path.join(root,'.pd-owned-location-patch.json'),JSON.stringify(marker),{flag:'wx'});
  fs.mkdirSync(path.join(root,'node_modules/expo-location'),{recursive:true});fs.writeFileSync(path.join(root,'node_modules/expo-location/package.json'),JSON.stringify({version:'57.0.20'}));
  fs.mkdirSync(path.join(root,'plugins/native'),{recursive:true});fs.copyFileSync(path.join(source,'plugins/native/ProbeLocationLifecycle.kt'),path.join(root,'plugins/native/ProbeLocationLifecycle.kt'));
  for(const file of Object.keys(plugin.BASE)) {fs.mkdirSync(path.dirname(path.join(root,file)),{recursive:true});fs.copyFileSync(path.join(import.meta.dirname,'fixtures/expo-location-57',path.basename(file)),path.join(root,file));}
  return root;
}
test('location patch fingerprints native Expo sources and the exact existing-token cleanup contract and releases a retained service binding',()=>{
  const root=fixture();const result=plugin.patchProject(root);assert.deepEqual(result.before,plugin.BASE);
  const consumer=fs.readFileSync(path.join(root,plugin.CONSUMER),'utf8');
  assert.ok(consumer.includes('appContext.unbindService(connection)'));assert.ok(consumer.includes('appContext.stopService(Intent(appContext, LocationTaskService::class.java))'));
  assert.ok(consumer.includes('mProbeLifecycle.connect(generation, { mServiceConnection === this }, {'));assert.ok(consumer.includes('}, { boundService.stop() })'));
});
test('location patch prevents task restoration from authorizing collection and removes sticky service redelivery',()=>{
  const root=fixture();plugin.patchProject(root);const consumer=fs.readFileSync(path.join(root,plugin.CONSUMER),'utf8');
  assert.ok(consumer.includes('if (!mProbeLifecycle.register()) {\n      stopLocationUpdates()\n      stopForegroundService()\n      return'));assert.ok(consumer.includes('private fun handleLocationUpdate(locations: List<Location>) {\n    mProbeLifecycle.withLock {\n    if (!mProbeLifecycle.isActive()) return'));
  assert.ok(fs.readFileSync(path.join(root,plugin.MODULE),'utf8').includes('ProbeLocationStartGate.explicitStart {'));
  const service=fs.readFileSync(path.join(root,plugin.SERVICE),'utf8');assert.ok(service.includes('return START_NOT_STICKY'));assert.ok(!service.includes('return START_REDELIVER_INTENT'));
});
test('location patch refuses an unowned root before modifying any dependency',()=>{
  const root=fixture();fs.writeFileSync(path.join(root,'.pd-owned-location-patch.json'),JSON.stringify({projectRoot:source,purpose:'stage12-isolated-gps-build',nonce:'a'.repeat(32)}));
  assert.throws(()=>plugin.patchProject(root),/Unowned/);for(const [f,h] of Object.entries(plugin.BASE))assert.equal(hash(fs.readFileSync(path.join(root,f as string))),h);
  assert.equal(fs.existsSync(path.join(root,plugin.HELPER)),false);
});
test('location patch refuses a fingerprint change atomically and preserves the foreign bytes',()=>{
  const root=fixture();fs.appendFileSync(path.join(root,plugin.MODULE),'\n// foreign source');const expected=fs.readFileSync(path.join(root,plugin.MODULE));
  assert.throws(()=>plugin.patchProject(root),/Unrecognized/);assert.deepEqual(fs.readFileSync(path.join(root,plugin.MODULE)),expected);
  assert.equal(hash(fs.readFileSync(path.join(root,plugin.CONSUMER))),plugin.BASE[plugin.CONSUMER]);assert.equal(fs.existsSync(path.join(root,plugin.HELPER)),false);
});
test('location patch repeats without a new write and retains exact original native sources',()=>{
  const root=fixture();const first=plugin.patchProject(root);const bytes=fs.readFileSync(path.join(root,'.pd-location-patch-result.json'));
  assert.deepEqual(plugin.patchProject(root),first);assert.deepEqual(fs.readFileSync(path.join(root,'.pd-location-patch-result.json')),bytes);
  for(const [file,h] of Object.entries(plugin.BASE))assert.equal(hash(fs.readFileSync(path.join(root,'.pd-location-baseline',path.basename(file)))),h);
});
test('location patch rejects post-patch dependency or helper drift without rewriting it',()=>{
  for(const file of [plugin.CONSUMER,plugin.HELPER,plugin.UTILS,plugin.INTERFACE]){const root=fixture();plugin.patchProject(root);fs.appendFileSync(path.join(root,file),'\n// drift');const before=fs.readFileSync(path.join(root,file));assert.throws(()=>plugin.patchProject(root),/drift/);assert.deepEqual(fs.readFileSync(path.join(root,file)),before);}
});
test('location patch source anchors refuse a second transformation rather than inserting duplicate lifecycle guards',()=>{
  const consumer=fs.readFileSync(path.join(import.meta.dirname,'fixtures/expo-location-57/LocationTaskConsumer.kt'),'utf8');
  const module=fs.readFileSync(path.join(import.meta.dirname,'fixtures/expo-location-57/LocationModule.kt'),'utf8');
  assert.throws(()=>plugin.transformConsumer(plugin.transformConsumer(consumer)),/Unsupported/);assert.throws(()=>plugin.transformModule(plugin.transformModule(module)),/Unsupported/);
});

test('service reference publication and lifecycle Stop share the exact consumer monitor',()=>{
  const root=fixture();plugin.patchProject(root);const consumer=fs.readFileSync(path.join(root,plugin.CONSUMER),'utf8');
  for(const signature of ['override fun didRegister(task: TaskInterface)','override fun didUnregister()','override fun setOptions(options: Map<String, Any>)','private fun startLocationUpdates()','private fun maybeStartForegroundService()','private fun stopForegroundService()'])assert.ok(consumer.includes(signature+' {\n    mProbeLifecycle.withLock {'));
  assert.ok(consumer.includes('mProbeLifecycle.connect(generation, { mServiceConnection === this }, {\n            mService = boundService'));
  assert.ok(consumer.includes('override fun onServiceDisconnected(name: ComponentName) {\n          mProbeLifecycle.withLock {'));
  assert.equal(consumer.includes('shouldStopLateConnection()'),false);
});

test('recreated consumer owner fences stale service and provider Stop effects',()=>{
  const root=fixture();plugin.patchProject(root);const consumer=fs.readFileSync(path.join(root,plugin.CONSUMER),'utf8');
  assert.ok(consumer.includes('private fun stopLocationUpdates() {\n    mProbeLifecycle.withLock {\n    if (!mProbeLifecycle.canStopService()) return'));
  assert.ok(consumer.includes('val mayStop = mProbeLifecycle.canStopService()\n    if (mayStop) service?.stop()'));
  assert.ok(consumer.includes('if (mayStop) appContext.stopService(Intent(appContext, LocationTaskService::class.java))'));
  assert.ok(consumer.includes('if (mProbeLifecycle.canStopService()) mService?.stop()'));
  const helper=fs.readFileSync(path.join(root,plugin.HELPER),'utf8');assert.ok(helper.includes('private var owner: ProbeLocationLifecycle? = null'));
  assert.ok(helper.includes('active && owner === this'));assert.ok(helper.includes('else if (owner == null) onStopped()'));
});

test('denied restored registration and Stop cancel only an existing task token without new GPS or token creation',()=>{
  const root=fixture();const report=plugin.patchProject(root);const consumer=fs.readFileSync(path.join(root,plugin.CONSUMER),'utf8');
  assert.ok(consumer.includes('mTask = task\n    if (!mProbeLifecycle.register()) {\n      stopLocationUpdates()\n      stopForegroundService()\n      return'));
  assert.ok(consumer.includes('mProbeLifecycle.stopHandle({ mPendingIntent }'));
  assert.ok(consumer.includes('mTask?.let { taskManagerUtils.cancelTaskIntent(context, it.appScopeKey, it.name) }'));
  const utils=fs.readFileSync(path.join(root,plugin.UTILS),'utf8');assert.equal(hash(utils),report.before[plugin.UTILS]);
  assert.ok(utils.includes('createTaskIntent(context, appScopeKey, taskName, PendingIntent.FLAG_NO_CREATE)'));
  const api=fs.readFileSync(path.join(root,plugin.INTERFACE),'utf8');assert.equal(hash(api),report.before[plugin.INTERFACE]);assert.ok(api.includes('void cancelTaskIntent(Context context, String appId, String taskName)'));
});


test('native patch requires explicit source compilation and refuses prebuilt selection before any write',()=>{
  const required=['expo-location','expo-task-manager','unimodules-app-loader'];
  for(const invalid of [undefined,[],['expo-location'],['expo-task-manager'],['expo-location','expo-task-manager'],['expo-location','unimodules-app-loader'],['expo-task-manager','unimodules-app-loader'],['expo-.*']]) {
    const root=fixture();fs.writeFileSync(path.join(root,'package.json'),JSON.stringify({expo:{autolinking:{android:{buildFromSource:invalid}}}}));
    assert.throws(()=>plugin.patchProject(root),/Source build selection/);
    for(const [file,h] of Object.entries(plugin.BASE))assert.equal(hash(fs.readFileSync(path.join(root,file))),h);
    assert.equal(fs.existsSync(path.join(root,plugin.HELPER)),false);assert.equal(fs.existsSync(path.join(root,'.pd-location-patch-result.json')),false);
  }
  const root=fixture();const result=plugin.patchProject(root);assert.deepEqual(result.sourceBuildSelection,required);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(source,'package.json'),'utf8')).expo.autolinking.android.buildFromSource,required);
});
