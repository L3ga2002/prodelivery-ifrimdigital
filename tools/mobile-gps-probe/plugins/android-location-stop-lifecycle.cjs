// Applies only inside an explicitly owned isolated build copy. No shared package patch.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const CONSUMER = 'node_modules/expo-location/android/src/main/java/expo/modules/location/taskConsumers/LocationTaskConsumer.kt';
const MODULE = 'node_modules/expo-location/android/src/main/java/expo/modules/location/LocationModule.kt';
const SERVICE = 'node_modules/expo-location/android/src/main/java/expo/modules/location/services/LocationTaskService.kt';
const UTILS = 'node_modules/expo-task-manager/android/src/main/java/expo/modules/taskManager/TaskManagerUtils.java';
const INTERFACE = 'node_modules/expo-modules-core/android/src/main/java/expo/modules/interfaces/taskManager/TaskManagerUtilsInterface.java';
const HELPER = 'node_modules/expo-location/android/src/main/java/expo/modules/location/taskConsumers/ProbeLocationLifecycle.kt';
const BASE = {
  [UTILS]: 'E73FB69B38B07A21D669DBF746B7B3711B3BB83D0159AF795E450708F9FA2679',
  [INTERFACE]: 'F2010A941BFE900D215BF877EB17C400D142BD1E912DE5AC04C5E2DA560D5AC2',
  [SERVICE]: '7954E7E7BE7B9780FE852F99B996291C37FFA07163834CF75DC81B9C51C36A4A',
  [CONSUMER]: '4ED55AE2A285FFC3ADD788266AD997808754D82B09559D0D03237FFDC218ACB4',
  [MODULE]: '74404105155747A6EEEDEE253F4F42D252D2160598870DE84E8A259043737846',
};
const sha = text => crypto.createHash('sha256').update(text).digest('hex').toUpperCase();
function once(text, before, after) {
  if (text.split(before).length !== 2) throw new Error('Unsupported Expo location source anchor.');
  return text.replace(before, after);
}
function lockMethod(text, signature) {
  const anchor = signature + ' {';
  if (text.split(anchor).length !== 2) throw new Error('Unsupported lifecycle lock anchor.');
  const start = text.indexOf(anchor) + anchor.length;
  let depth = 1, end = start;
  // The exact fingerprinted Kotlin methods have balanced lexical braces.
  for (; end < text.length && depth; end++) {
    if (text[end] === '{') depth++; else if (text[end] === '}') depth--;
  }
  if (depth) throw new Error('Unsupported lifecycle method body.');
  const body = text.slice(start, end - 1);
  return text.slice(0, start) + '\n    mProbeLifecycle.withLock {' + body + '  }\n  ' + text.slice(end - 1);
}
function transformConsumer(text) {
  text = once(text, '  private var mService: LocationTaskService? = null', `  private var mService: LocationTaskService? = null
  private var mServiceConnection: ServiceConnection? = null
  private val mProbeLifecycle = ProbeLocationLifecycle()`);
  text = once(text, '    mTask = task\n    startLocationUpdates()', '    mTask = task\n    if (!mProbeLifecycle.register()) {\n      stopLocationUpdates()\n      stopForegroundService()\n      return\n    }\n    startLocationUpdates()');
  text = once(text, '  override fun didUnregister() {\n    stopLocationUpdates()', '  override fun didUnregister() {\n    mProbeLifecycle.unregister()\n    stopLocationUpdates()');
  text = once(text, '    // Restart location updates\n    stopLocationUpdates()\n    startLocationUpdates()', `    // A task restored from persistent options is not fresh user consent.
    mProbeLifecycle.unregister()
    stopLocationUpdates()
    stopForegroundService()
    if (!mProbeLifecycle.register()) return
    startLocationUpdates()`);
  text = once(text, '  override fun didReceiveBroadcast(intent: Intent) {\n    mTask ?: return', '  override fun didReceiveBroadcast(intent: Intent) {\n    if (!mProbeLifecycle.isActive()) return\n    mTask ?: return');
  text = once(text, '  private fun handleLocationUpdate(locations: List<Location>) {', '  private fun handleLocationUpdate(locations: List<Location>) {\n    if (!mProbeLifecycle.isActive()) return');
  text = once(text, '  private fun stopLocationUpdates() {', '  private fun stopLocationUpdates() {\n    if (!mProbeLifecycle.canStopService()) return');
  text = once(text, '    mPendingIntent?.let {\n      mLocationClient.removeLocationUpdates(it)\n      it.cancel()\n    }', `    mProbeLifecycle.stopHandle({ mPendingIntent }, { intent ->
      mLocationClient.removeLocationUpdates(intent)
      intent.cancel()
    }, {
      // Recover only an already existing OS token; never create/start GPS here.
      mTask?.let { taskManagerUtils.cancelTaskIntent(context, it.appScopeKey, it.name) }
    })`);
  text = once(text, '  private fun startLocationUpdates() {', '  private fun startLocationUpdates() {\n    if (!mProbeLifecycle.isActive()) return');
  text = once(text, '  private fun maybeStartForegroundService() {', '  private fun maybeStartForegroundService() {\n    if (!mProbeLifecycle.isActive()) return');
  text = once(text, '    mIsHostPaused = false\n    maybeReportDeferredLocations()', '    mIsHostPaused = false\n    if (mProbeLifecycle.isActive()) maybeReportDeferredLocations()');
  const start = text.indexOf('      context.bindService(\n');
  const end = text.indexOf('\n    } else {\n      // Restart the service', start);
  if (start < 0 || end < 0) throw new Error('Unsupported binding source.');
  text = text.slice(0,start) + `      val generation = mProbeLifecycle.epoch()
      val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, service: IBinder) {
          val boundService = (service as? ServiceBinder)?.service ?: return
          // Validation, publication and start/stop effects are one monitor transition.
          mProbeLifecycle.connect(generation, { mServiceConnection === this }, {
            mService = boundService
            boundService.setParentContext(context)
            boundService.startForeground(serviceOptions)
          }, { boundService.stop() })
        }
        override fun onServiceDisconnected(name: ComponentName) {
          mProbeLifecycle.withLock {
            if (mServiceConnection !== this) return
            if (mProbeLifecycle.canStopService()) mService?.stop()
            mService = null
          }
        }
      }
      mServiceConnection = connection
      if (!context.bindService(serviceIntent, connection, Context.BIND_AUTO_CREATE)) {
        mServiceConnection = null
        context.stopService(serviceIntent)
        throw IllegalStateException("Probe location service binding failed")
      }` + text.slice(end);
  text = once(text, '  private fun stopForegroundService() {\n    mService?.stop()\n  }', `  private fun stopForegroundService() {
    val service = mService
    val connection = mServiceConnection
    mService = null
    mServiceConnection = null
    val mayStop = mProbeLifecycle.canStopService()
    if (mayStop) service?.stop()
    val appContext = context ?: return
    if (connection != null) {
      try { appContext.unbindService(connection) }
      catch (_: IllegalArgumentException) { /* Already detached by Android. */ }
    }
    // Also stops a started service whose onServiceConnected callback is pending.
    if (mayStop) appContext.stopService(Intent(appContext, LocationTaskService::class.java))
  }`);
  text = once(text, '    if (locationBundles.isNotEmpty() && mTask != null) {', '    if (mProbeLifecycle.isActive() && locationBundles.isNotEmpty() && mTask != null) {');
  // The same monitor covers task registration, Stop, options, provider start and
  // foreground service binding. Callback publication cannot outlive a Stop ACK.
  for (const signature of [
    '  override fun didRegister(task: TaskInterface)', '  override fun didUnregister()',
    '  override fun setOptions(options: Map<String, Any>)',
    '  override fun didReceiveBroadcast(intent: Intent)',
    '  private fun handleLocationUpdate(locations: List<Location>)',
    '  private fun startLocationUpdates()', '  private fun stopLocationUpdates()',
    '  private fun maybeStartForegroundService()', '  private fun stopForegroundService()',
    '  private fun executeTaskWithLocationBundles(locationBundles: ArrayList<Bundle>, callback: TaskExecutionCallback)',
    '  override fun onHostResume()', '  override fun onHostPause()', '  override fun onHostDestroy()',
  ]) text = lockMethod(text, signature);
  return text;
}
function transformModule(text) {
  if (text.includes('ProbeLocationStartGate.explicitStart')) throw new Error('Unsupported already patched module.');
  return once(text, '      mTaskManager.registerTask(taskName, LocationTaskConsumer::class.java, options.toMutableMap())', `      expo.modules.location.taskConsumers.ProbeLocationStartGate.explicitStart {
        mTaskManager.registerTask(taskName, LocationTaskConsumer::class.java, options.toMutableMap())
      }`);
}
function patchProject(root) {
  root = fs.realpathSync(root);
  const markerPath = path.join(root,'.pd-owned-location-patch.json');
  const marker = JSON.parse(fs.readFileSync(markerPath,'utf8'));
  if (fs.realpathSync(marker.projectRoot) !== root || marker.purpose !== 'stage12-isolated-gps-build' || !/^[a-f0-9]{32}$/.test(marker.nonce)) throw new Error('Unowned location patch root.');
  const sourceBuildSelection = JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8')).expo?.autolinking?.android?.buildFromSource;
  if (!Array.isArray(sourceBuildSelection) || sourceBuildSelection.length !== 3 || sourceBuildSelection[0] !== 'expo-location' || sourceBuildSelection[1] !== 'expo-task-manager' || sourceBuildSelection[2] !== 'unimodules-app-loader') throw new Error('Source build selection must explicitly compile expo-location, expo-task-manager and unimodules-app-loader.');
  const pkg = JSON.parse(fs.readFileSync(path.join(root,'node_modules/expo-location/package.json'),'utf8'));
  if (pkg.version !== '57.0.20') throw new Error('Unsupported Expo location version.');
  const reportPath = path.join(root,'.pd-location-patch-result.json');
  if (fs.existsSync(reportPath)) {
    const prior=JSON.parse(fs.readFileSync(reportPath,'utf8'));
    if (JSON.stringify(prior.sourceBuildSelection) !== JSON.stringify(sourceBuildSelection)) throw new Error('Source build selection changed after patch.');
    for (const [file,hash] of Object.entries(prior.after)) if (sha(fs.readFileSync(path.join(root,file))) !== hash) throw new Error('Patched location source drift.');
    if (sha(fs.readFileSync(path.join(root,'plugins/native/ProbeLocationLifecycle.kt'))) !== prior.after[HELPER]) throw new Error('Probe helper source drift.');
    for (const [file,expected] of Object.entries(BASE)) if (!(file in prior.after) && sha(fs.readFileSync(path.join(root,file))) !== expected) throw new Error('Read-only task cleanup contract drift.');
    return prior;
  }
  const before={};const original={};
  for (const [file,expected] of Object.entries(BASE)) {
    const bytes=fs.readFileSync(path.join(root,file));before[file]=sha(bytes);
    if(before[file]!==expected)throw new Error('Unrecognized Expo location source; patch refused.');
    original[file]=bytes.toString('utf8');
  }
  const helper=fs.readFileSync(path.join(root,'plugins/native/ProbeLocationLifecycle.kt'),'utf8');
  if(fs.existsSync(path.join(root,HELPER)))throw new Error('Unexpected pre-existing probe helper.');
  const outputs={[SERVICE]:once(original[SERVICE], '    return START_REDELIVER_INTENT', '    // Probe collection never restarts itself after process death.\n    return START_NOT_STICKY'),[CONSUMER]:transformConsumer(original[CONSUMER]),[MODULE]:transformModule(original[MODULE]),[HELPER]:helper};
  // Fingerprints and every anchor were validated before any dependency write.
  fs.mkdirSync(path.join(root,'.pd-location-baseline'),{recursive:false});
  for(const [file,text] of Object.entries(original))fs.writeFileSync(path.join(root,'.pd-location-baseline',path.basename(file)),text,{flag:'wx'});
  for(const [file,text] of Object.entries(outputs))fs.writeFileSync(path.join(root,file),text,{flag:file===HELPER?'wx':'w'});
  const report={purpose:marker.purpose,nonce:marker.nonce,projectRoot:root,sourceBuildSelection,before,after:Object.fromEntries(Object.keys(outputs).map(file=>[file,sha(fs.readFileSync(path.join(root,file)))]))};
  fs.writeFileSync(reportPath,JSON.stringify(report,null,2),{flag:'wx'});return report;
}
module.exports = function withProbeLocationStop(config) {
  const { withDangerousMod } = require('@expo/config-plugins');
  return withDangerousMod(config,['android',async mod => {patchProject(mod.modRequest.projectRoot);return mod;}]);
};
module.exports.testing={transformConsumer,transformModule,patchProject,BASE,CONSUMER,MODULE,SERVICE,HELPER,UTILS,INTERFACE};
