package expo.modules.prodeliverybattery

import android.app.Notification
import android.app.ActivityManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.Process
import android.os.SystemClock
import org.json.JSONObject

/** Observes only. It has no location imports, GPS commands, jobs, restart or wake lock. */
class BatteryObserverService : Service() {
  companion object {
    const val CHANNEL = "prodelivery-battery-diagnostic-v1"
    const val NOTIFICATION_ID = 48274
    const val RUN_ID = "runId"
    private const val GPS_SERVICE_CLASS = "expo.modules.location.services.LocationTaskService"

    @Suppress("DEPRECATION")
    private fun ownGpsServiceStarted(context: Context): Boolean? = try {
      val manager = context.getSystemService(ActivityManager::class.java)
      val services = manager?.getRunningServices(Int.MAX_VALUE)
      // Android limits this deprecated API to the caller's own services. Do not save identifiers.
      services?.any { info -> info.uid == Process.myUid() &&
        info.service.packageName == context.packageName && info.service.className == GPS_SERVICE_CLASS &&
        info.started && info.pid > 0 && info.restarting == 0L }
    } catch (_: Exception) { null }

    fun ensureVisibleNotification(context: Context) {
      val manager = context.getSystemService(NotificationManager::class.java)
      if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(
        NotificationChannel(CHANNEL, "Proba locală a bateriei", NotificationManager.IMPORTANCE_LOW))
      check(manager.areNotificationsEnabled() && (Build.VERSION.SDK_INT < 26 ||
        manager.getNotificationChannel(CHANNEL)?.importance != NotificationManager.IMPORTANCE_NONE)) {
        "notification_permission_required"
      }
    }

    fun snapshot(context: Context, batteryIntent: Intent? = null): BatterySnapshot {
      val sticky = batteryIntent ?: context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
      val manager = context.getSystemService(BatteryManager::class.java)
      val level = sticky?.takeIf { it.hasExtra(BatteryManager.EXTRA_LEVEL) }?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
      val scale = sticky?.takeIf { it.hasExtra(BatteryManager.EXTRA_SCALE) }?.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
      val percent = if (level != null && scale != null && scale > 0 && level in 0..scale)
        ((level.toLong() * 100L) / scale).toInt() else null
      val plugged = sticky?.takeIf { it.hasExtra(BatteryManager.EXTRA_PLUGGED) }
        ?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1)?.takeIf { it >= 0 }
      val status = sticky?.takeIf { it.hasExtra(BatteryManager.EXTRA_STATUS) }
        ?.getIntExtra(BatteryManager.EXTRA_STATUS, BatteryManager.BATTERY_STATUS_UNKNOWN)
      val charging = if (manager != null && status != null && status in BatteryManager.BATTERY_STATUS_CHARGING..BatteryManager.BATTERY_STATUS_FULL)
        manager.isCharging else null
      val charge = manager?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER)?.takeIf { it != Int.MIN_VALUE && it >= 0 }
      return BatterySnapshot(SystemClock.elapsedRealtime(), System.currentTimeMillis(), percent, plugged, charging, charge,
        context.getSystemService(PowerManager::class.java)?.isInteractive, ownGpsServiceStarted(context))
    }
  }

  private val handler = Handler(Looper.getMainLooper())
  private var attached = false
  private var receiverRegistered = false
  private var notifiedPhase: String? = null
  private val tick = object : Runnable {
    override fun run() {
      record("heartbeat")
      if (attached) handler.postDelayed(this, BatteryProtocol.HEARTBEAT_MS)
    }
  }
  private val receiver = object : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
      val trigger = when (intent.action) {
        Intent.ACTION_BATTERY_CHANGED -> "battery_changed"
        Intent.ACTION_SCREEN_ON -> "screen_on"
        Intent.ACTION_SCREEN_OFF -> "screen_off"
        BatteryManager.ACTION_CHARGING -> "charging"
        BatteryManager.ACTION_DISCHARGING -> "discharging"
        else -> null
      }
      record(trigger, if (intent.action == Intent.ACTION_BATTERY_CHANGED) intent else null)
    }
  }

  override fun onBind(intent: Intent?): IBinder? = null

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    val runId = intent?.getStringExtra(RUN_ID)
    if (runId == null || !BatteryProtocol.validRunId(runId)) { stopSelf(); return START_NOT_STICKY }
    if (attached) return START_NOT_STICKY
    try {
      ensureVisibleNotification(this)
      val notification = notification()
      if (Build.VERSION.SDK_INT >= 34) startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
      else startForeground(NOTIFICATION_ID, notification)
      attached = BatteryJournal.attach(this, runId)
      if (!attached) { stopSelf(); return START_NOT_STICKY }
      val filter = IntentFilter().apply {
        addAction(Intent.ACTION_BATTERY_CHANGED)
        addAction(Intent.ACTION_SCREEN_ON)
        addAction(Intent.ACTION_SCREEN_OFF)
        addAction(BatteryManager.ACTION_CHARGING)
        addAction(BatteryManager.ACTION_DISCHARGING)
      }
      if (Build.VERSION.SDK_INT >= 33) registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
      else registerReceiver(receiver, filter)
      receiverRegistered = true
      handler.post(tick)
    } catch (_: Exception) {
      try { BatteryJournal.recordInterrupt("start_failed") } catch (_: Exception) { }
      stopSelf()
    }
    return START_NOT_STICKY
  }

  private fun record(trigger: String?, batteryIntent: Intent? = null) {
    if (!attached) return
    try {
      // Adjacent clock reads bracket only the unchanged snapshot collection, not queue wait or fsync.
      val elapsedBefore = SystemClock.elapsedRealtime()
      val uptimeBefore = SystemClock.uptimeMillis()
      val observation = snapshot(this, batteryIntent)
      val uptimeAfter = SystemClock.uptimeMillis()
      val elapsedAfter = SystemClock.elapsedRealtime()
      val diagnostic = trigger?.let {
        JSONObject().put("trigger", it).put("elapsedBeforeMs", elapsedBefore)
          .put("uptimeBeforeMs", uptimeBefore).put("uptimeAfterMs", uptimeAfter).put("elapsedAfterMs", elapsedAfter)
      }
      BatteryJournal.observe(observation, diagnostic)
      val active = BatteryJournal.current()
      if (active?.terminal != false) finish()
      else if (notifiedPhase != active.phase) {
        notifiedPhase = active.phase
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification())
      }
    } catch (_: Exception) {
      try { BatteryJournal.recordInterrupt("journal_write_failed") } catch (_: Exception) { }
      finish()
    }
  }

  private fun finish() {
    attached = false
    handler.removeCallbacks(tick)
    stopForeground(STOP_FOREGROUND_REMOVE)
    // Ending this observer does not end the independent GPS controller.
    if (BatteryJournal.current()?.kind == "full") {
      getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(false))
    }
    stopSelf()
  }

  private fun notification(ongoing: Boolean = true): Notification {
    val body = when (BatteryJournal.current()?.phase) {
      "awaiting_gps" -> "Repaus înregistrat. Revino în aplicație pentru Start GPS."
      "awaiting_stop" -> "Fereastra GPS încheiată. Revino în aplicație și apasă Stop GPS."
      "incomplete" -> "Măsurare incompletă. Revino în aplicație și verifică Stop GPS."
      else -> "Observator activ. Starea și oprirea sunt în aplicație."
    }
    val builder = (if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL) else Notification.Builder(this))
      .setSmallIcon(android.R.drawable.ic_menu_info_details)
      .setContentTitle("ProDelivery: măsurare locală baterie")
      .setContentText(body)
      .setOngoing(ongoing).setOnlyAlertOnce(true)
    packageManager.getLaunchIntentForPackage(packageName)?.let { launch ->
      builder.setContentIntent(PendingIntent.getActivity(this, NOTIFICATION_ID, launch,
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
    }
    return builder.build()
  }

  override fun onDestroy() {
    attached = false
    handler.removeCallbacks(tick)
    if (receiverRegistered) { unregisterReceiver(receiver); receiverRegistered = false }
    try { BatteryJournal.detach() } catch (_: Exception) { }
    stopForeground(STOP_FOREGROUND_REMOVE)
    super.onDestroy()
  }
}
