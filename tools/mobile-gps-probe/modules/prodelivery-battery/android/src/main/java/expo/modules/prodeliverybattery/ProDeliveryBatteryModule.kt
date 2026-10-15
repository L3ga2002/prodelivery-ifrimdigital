package expo.modules.prodeliverybattery

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class ProDeliveryBatteryModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("ProDeliveryBattery")

    Function("status") { BatteryJournal.status(context()) }

    Function("foregroundReady") {
      val activity = appContext.currentActivity
      activity != null && !activity.isFinishing && !activity.isDestroyed && activity.hasWindowFocus()
    }

    Function("start") { runId: String, kind: String ->
      val context = context()
      val activity = requireNotNull(appContext.currentActivity) { "foreground_start_required" }
      check(!activity.isFinishing && !activity.isDestroyed && activity.hasWindowFocus()) {
        "foreground_start_required"
      }
      if (Build.VERSION.SDK_INT >= 33) check(context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
        "notification_permission_required"
      }
      BatteryObserverService.ensureVisibleNotification(context)
      val model = BatteryJournal.prepare(context, runId, kind, BatteryObserverService.snapshot(context))
      if (!model.terminal && !BatteryJournal.observerActive) {
        try {
          val serviceIntent = Intent(context, BatteryObserverService::class.java).putExtra(BatteryObserverService.RUN_ID, runId)
          if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(serviceIntent) else context.startService(serviceIntent)
        } catch (error: Exception) {
          BatteryJournal.detach("start_failed")
          throw error
        }
      }
      BatteryJournal.status(context)
    }

    Function("checkGpsStart") { runId: String ->
      val context = context()
      BatteryJournal.load(context)
      try {
        BatteryJournal.checkGpsStart(runId, BatteryObserverService.snapshot(context))
      } catch (error: Exception) {
        try { stopTerminalObserver(context, runId) }
        catch (cleanupError: Exception) { error.addSuppressed(cleanupError) }
        throw error
      }
      BatteryJournal.status(context)
    }

    Function("markPhase") { runId: String, sessionId: String ->
      val context = context()
      // Parent invokes this only after its existing background GPS controller confirms Start.
      try {
        BatteryJournal.beginGps(runId, sessionId, BatteryObserverService.snapshot(context))
      } catch (error: Exception) {
        try { stopTerminalObserver(context, runId) }
        catch (cleanupError: Exception) { error.addSuppressed(cleanupError) }
        throw error
      }
      BatteryJournal.status(context)
    }

    Function("stop") { runId: String, reason: String ->
      val context = context()
      BatteryJournal.load(context)
      BatteryJournal.stop(runId, reason, BatteryObserverService.snapshot(context))
      context.stopService(Intent(context, BatteryObserverService::class.java))
      BatteryJournal.status(context)
    }
  }

  private fun stopTerminalObserver(context: Context, runId: String) {
    if (BatteryJournal.shouldStopObserver(runId)) {
      context.stopService(Intent(context, BatteryObserverService::class.java))
    }
  }

  private fun context(): Context = requireNotNull(appContext.reactContext) { "react_context_unavailable" }.applicationContext
}
