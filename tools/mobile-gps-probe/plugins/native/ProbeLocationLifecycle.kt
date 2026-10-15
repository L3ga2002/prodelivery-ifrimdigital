package expo.modules.location.taskConsumers

// Probe-only: volatile call scope, never persisted in task options. A restored
// task cannot authorize GPS or service start before a new explicit foreground Start.
object ProbeLocationStartGate {
  private val explicit = ThreadLocal<Boolean>()
  fun allowed(): Boolean = explicit.get() == true
  fun <T> explicitStart(block: () -> T): T {
    val prior = explicit.get()
    explicit.set(true)
    try { return block() } finally {
      if (prior == null) explicit.remove() else explicit.set(prior)
    }
  }
}

// The probe has one process-local location task. Consumer recreation must share
// the same owner monitor; no owner or Start permission survives process death.
class ProbeLocationLifecycle {
  companion object {
    @PublishedApi internal val monitor = Any()
    private var owner: ProbeLocationLifecycle? = null
  }
  private var active = false
  private var generation = 0L
  inline fun <T> withLock(block: () -> T): T = synchronized(monitor) { block() }
  fun register(): Boolean = withLock {
    generation++
    active = ProbeLocationStartGate.allowed()
    if (active) owner = this else if (owner === this) owner = null
    active
  }
  fun unregister() = withLock {
    active = false; generation++
    if (owner === this) owner = null
  }
  fun isActive(): Boolean = withLock { active && owner === this }
  fun epoch(): Long = withLock { generation }
  fun canConnect(epoch: Long, currentConnection: Boolean): Boolean = withLock {
    active && owner === this && epoch == generation && currentConnection
  }
  fun shouldStopLateConnection(): Boolean = withLock { owner == null }
  fun canStopService(): Boolean = withLock { owner == null || owner === this }
  fun <T> stopHandle(handle: () -> T?, removeAndCancel: (T) -> Unit,
                     cancelPersisted: () -> Unit) = withLock {
    if (owner != null && owner !== this) return@withLock
    val existing = handle()
    if (existing != null) removeAndCancel(existing) else cancelPersisted()
  }
  fun connect(epoch: Long, currentConnection: () -> Boolean,
              onActive: () -> Unit, onStopped: () -> Unit) = withLock {
    if (active && owner === this && epoch == generation && currentConnection()) onActive()
    else if (owner == null) onStopped()
  }
}
