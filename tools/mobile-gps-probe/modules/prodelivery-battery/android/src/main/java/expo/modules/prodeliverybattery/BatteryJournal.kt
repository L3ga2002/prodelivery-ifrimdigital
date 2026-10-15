package expo.modules.prodeliverybattery

import android.content.Context
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileNotFoundException
import java.io.FileOutputStream

/** Private, append-only, bounded diagnostic data. Never reads or writes the GPS database. */
internal object BatteryJournal {
  private const val MAX_BYTES = 1_048_576L
  private const val MAX_RUNS = 64
  private var model: BatteryProtocol? = null
  private var journal: File? = null
  private var sequence = 0L
  private var durabilityError: String? = null
  var observerActive = false; private set
  private var pendingStart = false

  private fun directory(context: Context): File = File(context.filesDir, "prodelivery-battery-v1").also {
    check(it.exists() || it.mkdir()) { "journal_directory_failed" }
  }

  @Synchronized
  fun load(context: Context): BatteryProtocol? {
    if (model != null) return model
    val latest = File(directory(context), "latest-run.txt")
    // Use the same atomic boundary as prepare: the base file can contain an
    // interrupted write while AtomicFile still owns a committed backup.
    val id = try {
      AtomicFile(latest).openRead().bufferedReader(Charsets.UTF_8).use { it.readText().trim() }
    } catch (error: FileNotFoundException) {
      // Only a genuinely absent pointer means no run. Preserve I/O failures
      // (including an unrecoverable legacy backup) as errors, never success.
      if (latest.exists() || File(latest.path + ".bak").exists()) throw error
      return null
    }
    check(BatteryProtocol.validRunId(id)) { "journal_pointer_invalid" }
    readJournal(File(directory(context), "$id.jsonl"))
    if (model?.terminal == false) recordInterrupt("process_interrupted")
    return model
  }

  @Synchronized
  fun prepare(context: Context, runId: String, kind: String, snapshot: BatterySnapshot): BatteryProtocol {
    require(BatteryProtocol.validRunId(runId)) { "invalid_run_id" }
    require(kind == "pilot" || kind == "full") { "invalid_run_kind" }
    load(context)
    val current = model
    if (current != null && current.runId == runId) {
      require(current.kind == kind) { "run_kind_conflict" }
      return current
    }
    check(current == null || current.terminal) { "observer_already_running" }
    check(!observerActive && !pendingStart) { "observer_still_closing" }
    val dir = directory(context)
    val target = File(dir, "$runId.jsonl")
    check(!target.exists()) { "run_id_already_exists" }
    check((dir.listFiles { file -> file.extension == "jsonl" }?.size ?: MAX_RUNS) < MAX_RUNS) {
      "journal_storage_limit"
    }
    durabilityError = null
    model = BatteryProtocol(runId, kind, snapshot.elapsedMs, BatteryProtocol.GPS_ADMISSION_POLICY)
    journal = target
    sequence = 0
    try {
      check(target.createNewFile()) { "run_id_already_exists" }
      append(JSONObject().put("type", "start").put("runId", runId).put("kind", kind)
        .put("startedElapsedMs", snapshot.elapsedMs)
        .put("gpsAdmissionPolicy", BatteryProtocol.GPS_ADMISSION_POLICY))
      val pointer = AtomicFile(File(dir, "latest-run.txt"))
      val stream = pointer.startWrite()
      try { stream.write(runId.toByteArray(Charsets.UTF_8)); pointer.finishWrite(stream) }
      catch (error: Exception) { pointer.failWrite(stream); throw error }
      observe(snapshot)
      pendingStart = model?.terminal == false
      return model!!
    } catch (error: Exception) {
      durabilityError = "journal_write_failed"
      model?.interrupt("journal_write_failed")
      pendingStart = false
      throw error
    }
  }

  @Synchronized
  fun attach(context: Context, runId: String): Boolean {
    val active = model ?: load(context)
    if (active == null || active.runId != runId || active.terminal || durabilityError != null) return false
    observerActive = true
    pendingStart = false
    return true
  }

  @Synchronized
  fun detach(reason: String = "service_destroyed") {
    observerActive = false
    pendingStart = false
    if (model?.terminal == false) recordInterrupt(reason)
  }

  @Synchronized
  fun observe(snapshot: BatterySnapshot, diagnostic: JSONObject? = null) {
    val active = model ?: return
    if (active.terminal || durabilityError != null) return
    // Commit the input before deriving the result. A failed write can never be a PASS.
    val event = JSONObject().put("type", "sample").put("snapshot", snapshotJson(snapshot))
    callbackDiagnosticJson(diagnostic, snapshot)?.let { event.put("diagnostic", it) }
    append(event)
    active.observe(snapshot)
  }

  // Optional timing evidence is copied through a strict scalar allowlist, never into the protocol.
  // Invalid or absent metadata means UNKNOWN; it cannot alter an observation or its verdict.
  private fun callbackDiagnosticJson(candidate: JSONObject?, snapshot: BatterySnapshot): JSONObject? {
    val keys = setOf("trigger", "elapsedBeforeMs", "uptimeBeforeMs", "uptimeAfterMs", "elapsedAfterMs")
    val triggers = setOf("heartbeat", "battery_changed", "screen_on", "screen_off", "charging", "discharging")
    return try {
      if (candidate == null || candidate.length() != keys.size || !keys.all { candidate.has(it) }) return null
      val trigger = candidate.opt("trigger") as? String ?: return null
      if (trigger !in triggers) return null
      val elapsedBefore = diagnosticClock(candidate, "elapsedBeforeMs") ?: return null
      val uptimeBefore = diagnosticClock(candidate, "uptimeBeforeMs") ?: return null
      val uptimeAfter = diagnosticClock(candidate, "uptimeAfterMs") ?: return null
      val elapsedAfter = diagnosticClock(candidate, "elapsedAfterMs") ?: return null
      if (elapsedBefore > elapsedAfter || uptimeBefore > uptimeAfter ||
        snapshot.elapsedMs !in elapsedBefore..elapsedAfter) return null
      JSONObject().put("trigger", trigger).put("elapsedBeforeMs", elapsedBefore)
        .put("uptimeBeforeMs", uptimeBefore).put("uptimeAfterMs", uptimeAfter).put("elapsedAfterMs", elapsedAfter)
    } catch (_: Exception) { null }
  }

  private fun diagnosticClock(candidate: JSONObject, key: String): Long? {
    val value = candidate.opt(key)
    val clock = when (value) {
      is Byte -> value.toLong()
      is Short -> value.toLong()
      is Int -> value.toLong()
      is Long -> value
      is Double -> if (value.isFinite() && value % 1.0 == 0.0 &&
        value >= 0.0 && value <= 9_007_199_254_740_991.0) value.toLong() else return null
      is Float -> if (value.isFinite() && value % 1.0f == 0.0f &&
        value >= 0.0f && value.toDouble() <= 9_007_199_254_740_991.0) value.toLong() else return null
      else -> return null
    }
    return clock.takeIf { it in 0L..9_007_199_254_740_991L }
  }

  @Synchronized
  fun checkGpsStart(runId: String, snapshot: BatterySnapshot) {
    val active = requireNotNull(model) { "observer_not_started" }
    require(active.runId == runId) { "run_id_conflict" }
    check(observerActive && durabilityError == null) { "observer_not_active" }
    require(active.kind == "full" && active.phase == "awaiting_gps") { "idle_window_required" }
    // Permission prompts may have consumed the lifetime. Commit a fresh observation before Start.
    observe(snapshot)
    check(!active.terminal && active.phase == "awaiting_gps") { "observer_incomplete" }
    check(snapshot.ownGpsServiceStarted == false) { "gps_not_stopped" }
    if (!active.hasGpsAdmissionBudget(snapshot)) {
      // An explicit durable event distinguishes a refused attempt from a later deadline.
      recordInterrupt("gps_budget_insufficient")
      error("gps_budget_insufficient")
    }
  }

  @Synchronized
  fun beginGps(runId: String, sessionId: String, snapshot: BatterySnapshot) {
    val active = requireNotNull(model) { "observer_not_started" }
    require(active.runId == runId) { "run_id_conflict" }
    check(observerActive && durabilityError == null) { "observer_not_active" }
    require(active.phase == "awaiting_gps" || (active.phase == "gps" && active.gpsSessionId == sessionId)) {
      "idle_window_required"
    }
    require(snapshot.unpowered()) { "unplug_required" }
    require(snapshot.ownGpsServiceStarted == true) { "gps_start_unconfirmed" }
    require(Regex("[A-Za-z0-9_-]{1,100}").matches(sessionId)) { "invalid_session_id" }
    if (active.phase == "gps") return
    append(JSONObject().put("type", "gps").put("sessionId", sessionId).put("snapshot", snapshotJson(snapshot)))
    active.beginGps(snapshot, true, sessionId)
    // The parent must run its ownership-safe GPS cleanup if Start won the timing race.
    check(active.stopReason != "gps_budget_insufficient") { "gps_budget_insufficient" }
  }

  @Synchronized
  fun stop(runId: String, reason: String, snapshot: BatterySnapshot) {
    val active = requireNotNull(model) { "observer_not_started" }
    require(active.runId == runId) { "run_id_conflict" }
    require(reason == "gps_stopped" || reason == "cancelled") { "invalid_stop_reason" }
    if (active.terminal) return
    append(JSONObject().put("type", "stop").put("reason", reason).put("snapshot", snapshotJson(snapshot)))
    active.stop(snapshot, reason)
  }

  @Synchronized
  fun recordInterrupt(reason: String) {
    val active = model ?: return
    if (active.terminal || durabilityError != null) return
    append(JSONObject().put("type", "interrupted").put("reason", reason))
    active.interrupt(reason)
  }

  @Synchronized
  fun status(context: Context): String {
    load(context)
    val active = model
    val budgetApplies = active?.gpsAdmissionPolicy == BatteryProtocol.GPS_ADMISSION_POLICY && active.kind == "full"
    val remainingBudget = if (budgetApplies && "monotonic_rollback" !in active!!.failures) {
      active.snapshots.lastOrNull()?.let(active::remainingRunMs)
    } else null
    val status = JSONObject().put("schemaVersion", 1)
      .put("runId", active?.runId ?: JSONObject.NULL)
      .put("kind", active?.kind ?: JSONObject.NULL)
      .put("phase", if (durabilityError != null) "incomplete" else active?.phase ?: "none")
      .put("observerActive", observerActive).put("starting", pendingStart)
      .put("stopReason", durabilityError ?: active?.stopReason ?: JSONObject.NULL)
      .put("gpsSessionId", active?.gpsSessionId ?: JSONObject.NULL)
      .put("startedElapsedMs", active?.startedElapsedMs ?: JSONObject.NULL)
      .put("lastSnapshot", active?.snapshots?.lastOrNull()?.let(::snapshotJson) ?: JSONObject.NULL)
      .put("snapshots", JSONArray().also { rows -> active?.snapshots?.forEach { rows.put(snapshotJson(it)) } })
      .put("windows", JSONArray().also { rows -> active?.windows?.forEach { rows.put(windowJson(it)) } })
      .put("failures", JSONArray((active?.failures?.toList() ?: emptyList()) + listOfNotNull(durabilityError)))
      .put("durabilityError", durabilityError ?: JSONObject.NULL)
      .put("gateMs", BatteryProtocol.UNPLUG_GATE_MS).put("heartbeatMs", BatteryProtocol.HEARTBEAT_MS)
      .put("maxGapMs", BatteryProtocol.MAX_GAP_MS).put("targetWindowMs", active?.targetMs ?: JSONObject.NULL)
      .put("maxRunMs", BatteryProtocol.MAX_RUN_MS)
      .put("gpsAdmissionPolicy", active?.gpsAdmissionPolicy ?: JSONObject.NULL)
      .put("remainingRunMs", remainingBudget ?: JSONObject.NULL)
      .put("gpsAdmissionRequiredMs", if (budgetApplies) BatteryProtocol.GPS_ADMISSION_REQUIRED_MS else JSONObject.NULL)
    return status.toString()
  }

  @Synchronized
  fun current(): BatteryProtocol? = model

  @Synchronized
  fun shouldStopObserver(runId: String): Boolean = model?.let {
    it.runId == runId && (it.terminal || durabilityError != null)
  } == true

  private fun append(event: JSONObject) {
    val file = requireNotNull(journal) { "journal_not_open" }
    event.put("schemaVersion", 1).put("sequence", sequence)
    val bytes = (event.toString() + "\n").toByteArray(Charsets.UTF_8)
    try {
      check(file.length() + bytes.size <= MAX_BYTES) { "journal_storage_limit" }
      FileOutputStream(file, true).use { stream -> stream.write(bytes); stream.fd.sync() }
      sequence += 1
    } catch (error: Exception) {
      durabilityError = "journal_write_failed"
      throw error
    }
  }

  private fun readJournal(file: File) {
    journal = file
    sequence = 0
    durabilityError = null
    check(file.isFile && file.length() <= MAX_BYTES) { "journal_invalid" }
    val text = file.readText(Charsets.UTF_8)
    try {
      check(text.endsWith("\n")) { "journal_truncated" }
      val lines = text.split('\n').dropLast(1)
      check(lines.size <= BatteryProtocol.MAX_SAMPLES + 16) { "journal_storage_limit" }
      for (line in lines) {
        val event = JSONObject(line)
        check(event.getInt("schemaVersion") == 1 && event.getLong("sequence") == sequence) { "journal_sequence_invalid" }
        when (event.getString("type")) {
          "start" -> {
            check(sequence == 0L) { "journal_header_invalid" }
            // Absent policy belongs to the existing journal format. An explicit unknown or
            // malformed policy must fail closed rather than silently disabling admission.
            val policy = if (!event.has("gpsAdmissionPolicy")) null else {
              check(event.opt("gpsAdmissionPolicy") is String &&
                event.getString("gpsAdmissionPolicy") == BatteryProtocol.GPS_ADMISSION_POLICY) {
                "unsupported_gps_admission_policy"
              }
              event.getString("gpsAdmissionPolicy")
            }
            model = BatteryProtocol(event.getString("runId"), event.getString("kind"), event.getLong("startedElapsedMs"), policy)
            check(file.name == "${model!!.runId}.jsonl") { "journal_run_id_invalid" }
          }
          "sample" -> requireNotNull(model).observe(readSnapshot(event.getJSONObject("snapshot")))
          "gps" -> requireNotNull(model).beginGps(readSnapshot(event.getJSONObject("snapshot")), true, event.getString("sessionId"))
          "stop" -> requireNotNull(model).stop(readSnapshot(event.getJSONObject("snapshot")), event.getString("reason"))
          "interrupted" -> requireNotNull(model).interrupt(event.getString("reason"))
          else -> error("journal_event_invalid")
        }
        sequence += 1
      }
      check(model != null) { "journal_header_missing" }
    } catch (error: Exception) {
      durabilityError = "journal_corrupt"
      model?.interrupt("journal_corrupt")
    }
  }

  private fun snapshotJson(s: BatterySnapshot) = JSONObject()
    .put("elapsedMs", s.elapsedMs).put("wallMs", s.wallMs)
    .put("levelPercent", s.levelPercent ?: JSONObject.NULL)
    .put("plugMask", s.plugMask ?: JSONObject.NULL).put("charging", s.charging ?: JSONObject.NULL)
    .put("chargeCounterUah", s.chargeCounterUah ?: JSONObject.NULL)
    .put("screenInteractive", s.screenInteractive ?: JSONObject.NULL)
    .put("ownGpsServiceStarted", s.ownGpsServiceStarted ?: JSONObject.NULL)

  private fun windowJson(w: BatteryWindow) = JSONObject().put("phase", w.phase)
    .put("start", snapshotJson(w.start)).put("end", snapshotJson(w.end))
    .put("sampleCount", w.sampleCount).put("maxGapMs", w.maxGapMs).put("elapsedMs", w.elapsedMs)
    .put("valid", w.valid && durabilityError == null).put("reasons", JSONArray(w.reasons))

  private fun readSnapshot(s: JSONObject) = BatterySnapshot(
    s.getLong("elapsedMs"), s.getLong("wallMs"),
    if (s.isNull("levelPercent")) null else s.getInt("levelPercent"),
    if (s.isNull("plugMask")) null else s.getInt("plugMask"),
    if (s.isNull("charging")) null else s.getBoolean("charging"),
    if (s.isNull("chargeCounterUah")) null else s.getInt("chargeCounterUah"),
    if (s.isNull("screenInteractive")) null else s.getBoolean("screenInteractive"),
    if (!s.has("ownGpsServiceStarted") || s.isNull("ownGpsServiceStarted")) null else s.getBoolean("ownGpsServiceStarted")
  )
}
