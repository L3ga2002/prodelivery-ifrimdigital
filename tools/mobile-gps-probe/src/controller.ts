import type { Mode, Precision } from './sample.ts';
import type { RecorderStore } from './store.ts';
import { UNCONFIRMED } from './shutdown.ts';

// A JS diagnostic deadline, never a native cancellation or sensor acknowledgement.
export const NATIVE_WATCHDOG_MS = 15_000;
type NativeTimeout = 'start' | 'stop';
function isShutdownFault(fault: string | null) {
  return fault === UNCONFIRMED || fault === 'native_start_timeout_shutdown_unconfirmed' ||
    fault === 'native_stop_timeout_shutdown_unconfirmed';
}

export type Permissions = { foreground: boolean; background: boolean; services: boolean; precision: Precision };
export interface LocationPort {
  backgroundAvailable(): Promise<boolean>;
  permissions(request?: Mode): Promise<Permissions>;
  start(mode: Mode, sample: (value: unknown) => void, error: () => void): Promise<void>;
  stop(): Promise<void>;
}
export type ControllerState = {
  phase: 'boot' | 'idle' | 'starting' | 'recording' | 'stopping' | 'error';
  mode: Mode; sessionId: string | null; permissions: Permissions | null;
  error: string | null; notice: string | null;
  nativeShutdown: 'not_checked' | 'not_attempted' | 'pending' | 'api_acknowledged' | 'unconfirmed' | 'failed';
  watchdog: NativeTimeout | 'cancellation_pending' | null;
};

export class RecorderController {
  state: ControllerState = { phase: 'boot', mode: 'foreground', sessionId: null, permissions: null, error: null, notice: null, nativeShutdown: 'not_checked', watchdog: null };
  private store: RecorderStore;
  private native: LocationPort;
  private now: () => number;
  private id: () => string;
  private changed: () => void;
  private generation = 0;
  private pending: Promise<void> = Promise.resolve();
  private uncertain = true;
  private storageUncertain = false;
  private checking = false;
  private initialized = false;
  private stopInFlight: Promise<void> | null = null;
  private timedOut: NativeTimeout | null = null;
  private shutdownBarrier = false;
  private preflightPending = false;
  constructor(store: RecorderStore, native: LocationPort, now: () => number, id: () => string, changed = () => {}) {
    this.store = store; this.native = native; this.now = now; this.id = id; this.changed = changed;
  }
  private update(values: Partial<ControllerState>) {
    this.state = { ...this.state, ...values };
    if (this.shutdownBarrier) this.state.nativeShutdown = 'unconfirmed';
    // Late completions and subsequent generations cannot downgrade this latch.
    if (this.timedOut) this.state = { ...this.state, phase: 'error', sessionId: null,
      nativeShutdown: 'unconfirmed', watchdog: this.timedOut,
      error: this.storageUncertain ? 'storage_close_failed' : `native_${this.timedOut}_timeout_shutdown_unconfirmed` };
    this.changed();
  }
  private conservativeFault(reason: string | null) {
    const snapshot = this.store.snapshot();
    if (snapshot.shutdownUnconfirmed || isShutdownFault(snapshot.fault)) this.shutdownBarrier = true;
    if (isShutdownFault(snapshot.fault)) return snapshot.fault;
    if (snapshot.nativeCleanupPending) {
      this.uncertain = true;
      if (snapshot.fault) return snapshot.fault;
      if (!this.shutdownBarrier) return 'native_cleanup_pending';
    }
    if (this.timedOut) return `native_${this.timedOut}_timeout_shutdown_unconfirmed`;
    if (this.shutdownBarrier) return UNCONFIRMED;
    return reason;
  }
  private closeLocal(reason: string | null) {
    // Read and preserve the durable safety diagnostic before close() can replace it.
    let fault: string | null;
    try {
      fault = this.conservativeFault(reason);
    } catch (error) {
      // Unknown durable evidence must survive a read failure without any fault rewrite.
      this.shutdownBarrier = true;
      this.uncertain = true;
      this.storageUncertain = true;
      try { this.store.markShutdownUnconfirmed(); } catch { /* Keep the local barrier even if persistence fails. */ }
      throw error;
    }
    try {
      this.store.close(this.now(), fault);
    } catch (error) {
      // A failed close must not replace the safety fault chosen for that close.
      try { this.store.setFault(fault ?? 'storage_close_failed'); } catch { /* Storage remains uncertain. */ }
      throw error;
    }
    return fault;
  }
  private watch(operation: NativeTimeout, generation: number, queue = false) {
    if (this.timedOut) return () => {};
    const timer = setTimeout(() => {
      if (generation !== this.generation || this.timedOut) return;
      if (queue && this.preflightPending && !this.uncertain && !this.shutdownBarrier && !this.storageUncertain) {
        this.update({ phase: 'error', watchdog: 'cancellation_pending', nativeShutdown: 'not_attempted',
          error: 'start_cancellation_pending', notice: null });
        return;
      }
      this.timedOut = operation;
      this.shutdownBarrier = true;
      this.uncertain = true;
      this.generation++;
      const fault = `native_${operation}_timeout_shutdown_unconfirmed`;
      // Persist the existing one-way barrier independently of local close success.
      let storageFailed = false;
      try { this.store.markShutdownUnconfirmed(); } catch { storageFailed = true; }
      try { this.closeLocal(fault); }
      catch { storageFailed = true; }
      this.storageUncertain = storageFailed;
      this.update({ notice: null });
      // Keep the original promise in the queue: timeout cannot cancel a late watch.
      if (operation === 'start') void this.stop(fault);
    }, NATIVE_WATCHDOG_MS);
    return () => clearTimeout(timer);
  }
  private async stopNative(): Promise<string | null> {
    const cancelWatchdog = this.watch('stop', this.generation);
    this.uncertain = true;
    this.update({ nativeShutdown: 'pending', ...(this.state.watchdog === 'cancellation_pending' ?
      { phase: 'stopping' as const, watchdog: null, error: null } : {}) });
    let fault: string | null = null;
    try { await this.native.stop(); }
    catch (error) { fault = error instanceof Error && error.message === UNCONFIRMED ? UNCONFIRMED : 'native_stop_failed'; }
    finally { cancelWatchdog(); }
    if (this.shutdownBarrier) fault = UNCONFIRMED;
    if (fault === UNCONFIRMED) this.shutdownBarrier = true;
    try {
      const snapshot = this.store.snapshot();
      if (snapshot.shutdownUnconfirmed || isShutdownFault(snapshot.fault)) {
        this.shutdownBarrier = true;
        fault = UNCONFIRMED;
      }
      if (fault === UNCONFIRMED) this.store.markShutdownUnconfirmed();
      if (snapshot.nativeCleanupPending) fault ??= 'native_cleanup_pending';
    } catch { this.storageUncertain = true; fault ??= 'storage_close_failed'; }
    this.uncertain = fault !== null;
    this.update({ nativeShutdown: fault === UNCONFIRMED ? 'unconfirmed' : fault ? 'failed' : 'api_acknowledged' });
    return fault;
  }
  initialize(): Promise<void> {
    if (this.initialized) return this.pending;
    this.initialized = true;
    const generation = this.generation;
    this.pending = (async () => {
      let fault: string | null = null;
      try {
        const interrupted = this.store.active() !== null;
        this.closeLocal(interrupted ? 'interrupted_session' : this.store.snapshot().fault);
        this.storageUncertain = false;
      } catch { this.storageUncertain = true; fault = 'storage_close_failed'; }
      // SQLite failure must never skip native shutdown.
      const nativeFault = await this.stopNative();
      fault ??= nativeFault;
      if (generation !== this.generation) return;
      if (fault) { this.update({ phase: 'error', error: fault }); return; }
      try {
        if (generation !== this.generation) return;
        this.preflightPending = true;
        let permissions: Permissions;
        try { permissions = await this.native.permissions(); }
        finally { this.preflightPending = false; }
        if (generation === this.generation) this.update({ phase: 'idle', permissions, error: this.store.snapshot().fault });
      } catch { if (generation === this.generation) this.update({ phase: 'error', error: 'initialization_failed_stop_required' }); }
    })();
    return this.pending;
  }
  start(mode: Mode): Promise<void> {
    if (!['idle', 'error'].includes(this.state.phase) || this.uncertain || this.storageUncertain || this.stopInFlight || this.timedOut) {
      this.update({ notice: 'start_unavailable_or_already_pending' });
      return Promise.resolve();
    }
    const generation = ++this.generation;
    const current = () => generation === this.generation;
    let cancelWatchdog = () => {};
    this.preflightPending = true;
    this.update({ phase: 'starting', mode, error: null, notice: null, nativeShutdown: 'not_checked' });
    this.pending = (async () => {
      try {
        if (mode === 'background' && !await this.native.backgroundAvailable()) throw new Error('background_unavailable');
        if (!current()) return;
        const permissions = await this.native.permissions(mode);
        if (!current()) return;
        this.update({ permissions });
        if (!permissions.services) throw new Error('location_services_off');
        if (!permissions.foreground || (mode === 'background' && !permissions.background)) throw new Error('permission_denied');
        this.conservativeFault(null);
        if (this.shutdownBarrier) throw new Error(UNCONFIRMED);
        const session = this.store.start(this.id(), mode, this.now());
        this.update({ sessionId: session.id });
        if (!current()) return;
        this.preflightPending = false;
        this.uncertain = true;
        cancelWatchdog = this.watch('start', generation);
        await this.native.start(mode, value => {
          if (!current()) return;
          try {
            const result = this.store.record(session.id, mode, value, this.now(), this.state.permissions?.precision ?? 'unknown');
            this.changed();
            if (result === 'capacity') void this.stop('capacity');
          } catch { void this.stop('storage_write_failed'); }
        }, () => { if (current()) void this.stop('native_location_error'); });
        if (current()) this.update({ phase: 'recording' });
      } catch (error) {
        if (!current()) return;
        const known = ['background_unavailable', 'permission_denied', 'location_services_off', 'capacity', 'foreground_start_required', 'native_build_required', 'native_cleanup_pending', UNCONFIRMED];
        const message = error instanceof Error && known.includes(error.message) ? error.message : 'start_failed';
        const cleanupGeneration = ++this.generation;
        this.preflightPending = false;
        try { this.closeLocal(message); this.storageUncertain = false; }
        catch { this.storageUncertain = true; }
        const nativeFault = await this.stopNative();
        if (cleanupGeneration === this.generation) this.update({ phase: 'error', sessionId: null, error: this.storageUncertain ? 'storage_close_failed' : nativeFault ?? message });
      } finally { this.preflightPending = false; cancelWatchdog(); }
    })();
    return this.pending;
  }
  stop(reason: string | null = null): Promise<void> {
    if (this.stopInFlight) return this.stopInFlight;
    const generation = ++this.generation;
    const cancelWatchdog = this.watch('stop', generation, true);
    let fault = reason;
    try { fault = this.closeLocal(reason); if (!this.timedOut) this.storageUncertain = false; }
    catch { this.storageUncertain = true; fault = 'storage_close_failed'; }
    this.update({ phase: 'stopping', sessionId: null, error: fault, notice: null });
    const starting = this.pending;
    const work = (async () => {
      try {
        await starting;
        const nativeFault = await this.stopNative();
        if (generation !== this.generation && !this.timedOut) return;
        if (nativeFault) fault = this.storageUncertain ? 'storage_close_failed' : nativeFault;
        if (fault) {
          try { this.store.setFault(this.conservativeFault(fault)!); }
          catch { this.storageUncertain = true; fault = 'storage_close_failed'; }
        }
        this.update({ phase: fault ? 'error' : 'idle', error: fault, watchdog: null });
      } finally { cancelWatchdog(); }
    })();
    this.pending = this.stopInFlight = work;
    const finished = () => { if (this.stopInFlight === work) this.stopInFlight = null; };
    void work.then(finished, finished);
    return work;
  }
  async check() {
    if (this.checking || this.state.phase === 'boot' || this.state.phase === 'starting' || this.state.phase === 'stopping') return;
    this.checking = true;
    const generation = this.generation;
    try {
      const permissions = await this.native.permissions();
      if (generation !== this.generation) return;
      this.update({ permissions });
      if (this.state.phase === 'recording') {
        if (!permissions.services || !permissions.foreground || (this.state.mode === 'background' && !permissions.background)) {
          await this.stop('permission_or_services_revoked');
        } else if (!this.store.active()) {
          await this.stop(this.store.snapshot().fault ?? 'session_closed');
        } else if (this.store.snapshot().count >= this.store.snapshot().limit) {
          await this.stop('capacity');
        }
      }
    } catch { if (generation === this.generation) await this.stop('permission_check_failed'); }
    finally { this.checking = false; }
  }
  async lifecycle(state: 'active' | 'background' | 'inactive') {
    if (this.state.phase === 'starting' && this.state.mode === 'foreground' && state !== 'active') {
      await this.stop('foreground_left_active'); return;
    }
    if (this.state.phase !== 'recording') return;
    try {
      if (!this.store.lifecycle(this.state.sessionId!, state, this.now())) {
        const stats = this.store.snapshot();
        await this.stop(stats.fault ?? (stats.count >= stats.limit ? 'capacity' : 'session_closed')); return;
      }
      if (this.state.mode === 'foreground' && state !== 'active') await this.stop('foreground_left_active');
      else await this.check();
    } catch { await this.stop('storage_write_failed'); }
  }
}
