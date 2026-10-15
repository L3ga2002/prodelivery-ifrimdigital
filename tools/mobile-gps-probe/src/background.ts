import { NATIVE_WATCHDOG_MS, type Permissions } from './controller.ts';
import type { RecorderStore } from './store.ts';
import { UNCONFIRMED } from './shutdown.ts';

const TIMEOUT = 'native_stop_timeout_shutdown_unconfirmed';
function shutdownFault(fault: string | null) {
  return fault === UNCONFIRMED || fault === TIMEOUT || fault === 'native_start_timeout_shutdown_unconfirmed';
}

export async function recordBackgroundBatch(deps: {
  store: () => RecorderStore; permissions: () => Promise<Permissions>;
  stop: () => Promise<void>; now: () => number;
}, data: unknown, nativeError = false) {
  let local: RecorderStore | undefined;
  let captured: string | null = null;
  let storageEvidenceUnknown = false;
  const snapshot = () => {
    try { return local!.snapshot(); }
    catch (error) { storageEvidenceUnknown = true; throw error; }
  };
  let nativeStop: Promise<'stopped' | 'failed' | 'timeout'> | undefined;
  const conservativeFault = (reason: string | null) => {
    const evidence = snapshot();
    if (shutdownFault(evidence.fault)) return evidence.fault;
    if (evidence.shutdownUnconfirmed) return UNCONFIRMED;
    if (evidence.nativeCleanupPending && evidence.fault && reason !== 'native_stop_failed') return evidence.fault;
    return reason;
  };
  const stopOnce = () => nativeStop ??= new Promise(resolve => {
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      // Diagnostic only: no native cancellation or sensor acknowledgement.
      // The already persisted pending barrier remains closed even if latch writes fail.
      if (local) {
        let diagnostic: string | undefined;
        try { const evidence = snapshot(); diagnostic = shutdownFault(evidence.fault) ? evidence.fault! : evidence.shutdownUnconfirmed ? UNCONFIRMED : TIMEOUT; }
        catch { /* Preserve the unknown fault. */ }
        try { local.markShutdownUnconfirmed(); } catch { /* Pending barrier is still conservative. */ }
        try { if (diagnostic) local.setFault(diagnostic); } catch { /* Never overwrite unknown durable evidence. */ }
      }
      resolve('timeout');
    }, NATIVE_WATCHDOG_MS);
    // Retain both handlers after the deadline: late rejection is consumed, never
    // an unhandled error; late success cannot clear either durable start barrier.
    Promise.resolve().then(() => deps.stop()).then(() => {
      clearTimeout(timer); if (!timedOut) resolve('stopped');
    }, () => { clearTimeout(timer); if (!timedOut) resolve('failed'); });
  });
  const shutdown = async (fault: string | null) => {
    const token = local!.beginNativeStop(captured, deps.now(), conservativeFault(fault));
    if (token === null) return;
    const result = await stopOnce();
    if (result === 'timeout') return;
    local!.finishNativeStop(token, result === 'failed' ? conservativeFault('native_stop_failed') : null);
  };
  try {
    local = deps.store();
    let session;
    try { session = local.active(); } catch (error) { storageEvidenceUnknown = true; throw error; }
    captured = session?.id ?? null;
    if (!session) { await shutdown(snapshot().fault); return; }
    if (session.mode !== 'background') return;
    if (nativeError) throw new Error('callback_failed');
    const permissions = await deps.permissions();
    if (!local.ownsSession(captured)) return;
    if (!permissions.foreground || !permissions.background || !permissions.services) throw new Error('permission_revoked');
    const locations = (data as { locations?: unknown[] } | undefined)?.locations;
    if (!Array.isArray(locations)) throw new Error('payload_invalid');
    for (const sample of locations) {
      const result = local.record(session.id, 'background', sample, deps.now(), permissions.precision);
      if (result === 'capacity' || (result === 'late' && !local.active())) { await shutdown(snapshot().fault); return; }
    }
    const stats = snapshot();
    if (stats.count >= stats.limit) await shutdown('capacity');
  } catch {
    if (local) {
      try {
        // An unreadable safety snapshot must not be replaced by a generic fault.
        if (storageEvidenceUnknown) throw new Error('storage_uncertain');
        conservativeFault(null);
        if (!local.ownsSession(captured)) return;
        await shutdown('background_task_failed'); return;
      } catch {
        let diagnostic: string | undefined;
        try { const evidence = snapshot(); diagnostic = shutdownFault(evidence.fault) ? evidence.fault! : evidence.shutdownUnconfirmed ? UNCONFIRMED : TIMEOUT; }
        catch { /* Preserve the unknown fault. */ }
        try { local.markShutdownUnconfirmed(); } catch { /* Local gate remains uncertain. */ }
      }
    }
    await stopOnce();
    throw new Error('background_task_failed_storage_unavailable');
  }
}
