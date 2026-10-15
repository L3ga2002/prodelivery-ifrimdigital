package expo.modules.prodeliverybattery

/** Android-free rules. A valid finite window is not a claim of battery health. */
data class BatterySnapshot(
  val elapsedMs: Long,
  val wallMs: Long,
  val levelPercent: Int?,
  val plugMask: Int?,
  val charging: Boolean?,
  val chargeCounterUah: Int?,
  val screenInteractive: Boolean?,
  val ownGpsServiceStarted: Boolean? = null
) {
  fun known(): Boolean = elapsedMs >= 0 && levelPercent != null && levelPercent in 0..100 &&
    plugMask != null && plugMask >= 0 && charging != null
  fun unpowered(): Boolean = known() && plugMask == 0 && charging == false
}

data class BatteryWindow(
  val phase: String,
  val start: BatterySnapshot,
  val end: BatterySnapshot,
  val sampleCount: Int,
  val maxGapMs: Long,
  val valid: Boolean,
  val reasons: List<String>
) { val elapsedMs: Long get() = end.elapsedMs - start.elapsedMs }

class BatteryProtocol(
  val runId: String,
  val kind: String,
  val startedElapsedMs: Long,
  // A missing policy is historical v1 behavior; never reinterpret existing observations.
  val gpsAdmissionPolicy: String? = null
) {
  companion object {
    const val UNPLUG_GATE_MS = 20_000L
    const val HEARTBEAT_MS = 10_000L
    const val MAX_GAP_MS = 25_000L
    const val PILOT_MS = 30_000L
    const val FULL_WINDOW_MS = 900_000L
    const val MAX_RUN_MS = 2_700_000L
    const val MAX_SAMPLES = 4_096
    const val GPS_ADMISSION_POLICY = "full_window_reserve_v1"
    const val GPS_ADMISSION_REQUIRED_MS = FULL_WINDOW_MS + MAX_GAP_MS
    fun validRunId(id: String) = Regex("pd-battery-[a-z0-9][a-z0-9-]{7,80}").matches(id)
  }

  init {
    require(validRunId(runId)) { "invalid_run_id" }
    require(kind == "pilot" || kind == "full") { "invalid_run_kind" }
    require(startedElapsedMs >= 0) { "invalid_monotonic_time" }
    require(gpsAdmissionPolicy == null || gpsAdmissionPolicy == GPS_ADMISSION_POLICY) {
      "unsupported_gps_admission_policy"
    }
  }

  var phase = "waiting_unplug"; private set
  var stopReason: String? = null; private set
  var gpsSessionId: String? = null; private set
  val snapshots = mutableListOf<BatterySnapshot>()
  val windows = mutableListOf<BatteryWindow>()
  val failures = linkedSetOf<String>()
  private var gateStart: Long? = null
  private val phaseSamples = mutableListOf<BatterySnapshot>()
  val terminal: Boolean get() = phase == "completed" || phase == "incomplete"
  val targetMs: Long get() = if (kind == "pilot") PILOT_MS else FULL_WINDOW_MS

  /** Native monotonic budget, not a wall-clock estimate or a new battery observation. */
  fun remainingRunMs(snapshot: BatterySnapshot): Long? {
    if (startedElapsedMs > 9_007_199_254_740_991L ||
      snapshot.elapsedMs !in startedElapsedMs..9_007_199_254_740_991L) return null
    return maxOf(0L, MAX_RUN_MS - (snapshot.elapsedMs - startedElapsedMs))
  }

  fun hasGpsAdmissionBudget(snapshot: BatterySnapshot): Boolean {
    if (gpsAdmissionPolicy == null || kind != "full") return true
    // The observer rejects at the exact deadline, so equality cannot guarantee completion.
    return remainingRunMs(snapshot)?.let { it > GPS_ADMISSION_REQUIRED_MS } == true
  }

  fun observe(snapshot: BatterySnapshot) {
    if (terminal) return
    val previous = snapshots.lastOrNull()
    if (snapshots.size >= MAX_SAMPLES) { incomplete("sample_limit"); return }
    snapshots.add(snapshot)
    if (!snapshot.known()) { incomplete("battery_unknown"); return }
    if (snapshot.ownGpsServiceStarted == null) { incomplete("gps_service_unknown"); return }
    if (previous != null && snapshot.elapsedMs < previous.elapsedMs) {
      incomplete("monotonic_rollback"); return
    }
    if (snapshot.elapsedMs < startedElapsedMs) { incomplete("monotonic_rollback"); return }
    if (previous != null && snapshot.elapsedMs - previous.elapsedMs > MAX_GAP_MS) {
      incomplete("heartbeat_gap"); return
    }
    if (snapshot.elapsedMs - startedElapsedMs >= MAX_RUN_MS) {
      incomplete("observer_deadline"); return
    }
    when (phase) {
      "waiting_unplug" -> {
        if (snapshot.ownGpsServiceStarted != false) { incomplete("gps_running_during_idle"); return }
        if (!snapshot.unpowered()) { gateStart = null; return }
        if (gateStart == null) gateStart = snapshot.elapsedMs
        if (snapshot.elapsedMs - gateStart!! >= UNPLUG_GATE_MS) {
          phase = "idle"
          phaseSamples.add(snapshot) // Fresh baseline after the actual unplug gate.
        }
      }
      "idle", "gps" -> {
        phaseSamples.add(snapshot)
        if (phase == "idle" && snapshot.ownGpsServiceStarted != false) {
          incomplete("gps_running_during_idle"); return
        }
        if (phase == "gps" && snapshot.ownGpsServiceStarted != true) {
          incomplete("gps_service_stopped"); return
        }
        if (!snapshot.unpowered()) { incomplete("charging_or_plugged"); return }
        if (snapshot.elapsedMs - phaseSamples.first().elapsedMs >= targetMs) {
          closeWindow(true, emptyList())
          phase = when {
            kind == "pilot" -> "completed"
            phase == "idle" -> "awaiting_gps"
            else -> "awaiting_stop"
          }
          if (kind == "pilot") stopReason = "pilot_window_complete"
        }
      }
      // The hand-off is excluded from both durations, but must remain unpowered.
      "awaiting_gps" -> if (!snapshot.unpowered()) incomplete("charging_during_handoff")
      // USB may be reconnected after the GPS window has been durably closed.
      "awaiting_stop" -> Unit
    }
  }

  /** Confirmation is the existing controller's boundary, not sensor proof. */
  fun beginGps(snapshot: BatterySnapshot, gpsRunning: Boolean, sessionId: String) {
    require(kind == "full") { "pilot_has_no_gps_phase" }
    require(gpsRunning) { "gps_confirmation_required" }
    require(Regex("[A-Za-z0-9_-]{1,100}").matches(sessionId)) { "invalid_session_id" }
    if (phase == "gps" && gpsSessionId == sessionId) return
    require(phase == "awaiting_gps") { "idle_window_required" }
    require(snapshot.ownGpsServiceStarted == true) { "gps_start_unconfirmed" }
    // Do not treat the deliberately variable hand-off interval as a GPS window.
    observe(snapshot)
    if (terminal) return // Journal replay must retain the actual failure, not call it corruption.
    require(snapshot.unpowered()) { "unplug_required" }
    if (!hasGpsAdmissionBudget(snapshot)) { incomplete("gps_budget_insufficient"); return }
    gpsSessionId = sessionId
    phase = "gps"
    phaseSamples.clear()
    phaseSamples.add(snapshot)
  }

  fun stop(snapshot: BatterySnapshot, reason: String) {
    require(reason in setOf("gps_stopped", "cancelled", "service_destroyed", "start_failed", "observer_deadline")) {
      "invalid_stop_reason"
    }
    if (terminal) return
    observe(snapshot)
    if (terminal) return
    if (phase == "awaiting_stop" && reason == "gps_stopped" && windows.size == 2 && windows.all { it.valid }) {
      if (snapshot.ownGpsServiceStarted != false) { incomplete("gps_stop_unconfirmed"); return }
      phase = "completed"
      stopReason = reason
    } else incomplete(reason)
  }

  fun interrupt(reason: String = "process_interrupted") {
    if (!terminal) incomplete(reason)
  }

  private fun incomplete(reason: String) {
    failures.add(reason)
    if (phase == "idle" || phase == "gps") {
      snapshots.lastOrNull()?.let { if (phaseSamples.lastOrNull() != it) phaseSamples.add(it) }
      closeWindow(false, listOf(reason))
    }
    phase = "incomplete"
    stopReason = reason
  }

  private fun closeWindow(valid: Boolean, reasons: List<String>) {
    if (phaseSamples.isEmpty()) return
    var maxGap = 0L
    for (i in 1 until phaseSamples.size) maxGap = maxOf(maxGap, phaseSamples[i].elapsedMs - phaseSamples[i - 1].elapsedMs)
    windows.add(BatteryWindow(phase, phaseSamples.first(), phaseSamples.last(), phaseSamples.size, maxGap, valid, reasons))
    phaseSamples.clear()
  }
}
