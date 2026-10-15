import { validateSample, type Mode, type Precision } from './sample.ts';

type Bind = string | number | null;
export interface Sqlite {
  execSync(sql: string): void;
  runSync(sql: string, params: Bind[]): { changes: number };
  getFirstSync<T>(sql: string, params?: Bind[]): T | null;
  getAllSync<T>(sql: string, params?: Bind[]): T[];
}
export type Session = { id: string; mode: Mode; started_at: number; stopped_at: number | null };
type Control = { active_session: string | null; fault: string | null; duplicates: number; rejected: number; late: number };
export type EventRow = {
  session_id: string; sequence: number; kind: string; source: string; captured_at: number | null;
  received_at: number; accuracy: number | null; flags: string; eligible: number;
};
export type RecordResult = 'saved' | 'duplicate' | 'rejected' | 'late' | 'capacity';
export const EVENT_LIMIT = 1000;
export const SESSION_LIMIT = 100;

export class RecorderStore {
  private db: Sqlite;
  private limit: number;
  private accepting = true;
  constructor(db: Sqlite, limit = EVENT_LIMIT) {
    if (!Number.isInteger(limit) || limit < 2 || limit > EVENT_LIMIT) throw new Error('invalid_capacity');
    this.db = db;
    this.limit = limit;
    const version = db.getFirstSync<{ user_version: number }>('PRAGMA user_version')?.user_version ?? 0;
    if (version !== 0 && version !== 1) throw new Error('unsupported_schema');
    db.execSync(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=3000; PRAGMA foreign_keys=ON;
      CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY, mode TEXT NOT NULL CHECK(mode IN ('foreground','background')),
        started_at REAL NOT NULL, stopped_at REAL
      );
      CREATE TABLE IF NOT EXISTS control (
        id INTEGER PRIMARY KEY CHECK(id=1), active_session TEXT REFERENCES sessions(id), fault TEXT,
        duplicates INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0,
        late INTEGER NOT NULL DEFAULT 0
      );
      INSERT OR IGNORE INTO control(id) VALUES(1);
      CREATE TABLE IF NOT EXISTS native_barrier (
        id INTEGER PRIMARY KEY CHECK(id=1), token INTEGER NOT NULL DEFAULT 0,
        pending INTEGER NOT NULL DEFAULT 0, shutdown_unconfirmed INTEGER NOT NULL DEFAULT 0
      );
      INSERT OR IGNORE INTO native_barrier(id) VALUES(1);
      CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
        sequence INTEGER NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
        captured_at REAL, received_at REAL NOT NULL, latitude REAL, longitude REAL, accuracy REAL,
        flags TEXT NOT NULL, eligible INTEGER NOT NULL DEFAULT 0, sample_key TEXT,
        UNIQUE(session_id, sequence), UNIQUE(session_id, sample_key)
      );
      PRAGMA user_version=1;`);
  }
  private tx<T>(work: () => T): T {
    this.db.execSync('BEGIN IMMEDIATE');
    try { const result = work(); this.db.execSync('COMMIT'); return result; }
    catch (error) { this.db.execSync('ROLLBACK'); throw error; }
  }
  private count(table: 'events' | 'sessions') {
    return this.db.getFirstSync<{ n: number }>(`SELECT count(*) n FROM ${table}`)!.n;
  }
  private control() { return this.db.getFirstSync<Control>('SELECT * FROM control WHERE id=1')!; }
  private activeRow(): Session | null {
    return this.db.getFirstSync<Session>('SELECT s.* FROM sessions s JOIN control c ON s.id=c.active_session WHERE c.id=1');
  }
  active(): Session | null { return this.accepting && this.control().fault === null ? this.activeRow() : null; }
  private insertEvent(id: string, kind: string, source: string, now: number, flags: string,
    values: Bind[] = [null, null, null, null, 0, null]) {
    this.db.runSync(`INSERT INTO events(session_id,sequence,kind,source,received_at,flags,
      captured_at,latitude,longitude,accuracy,eligible,sample_key)
      VALUES(?,(SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE session_id=?),?,?,?,?,?,?,?,?,?,?)`,
    [id, id, kind, source, now, flags, ...values]);
  }
  start(id: string, mode: Mode, now: number): Session {
    const session = this.tx(() => {
      if (this.db.getFirstSync<{ pending: number }>('SELECT pending FROM native_barrier WHERE id=1')!.pending) throw new Error('native_cleanup_pending');
      if (this.shutdownUnconfirmed()) throw new Error('foreground_shutdown_unconfirmed');
      if (this.activeRow()) throw new Error('session_active');
      if (this.count('events') >= this.limit || this.count('sessions') >= SESSION_LIMIT) throw new Error('capacity');
      this.db.runSync('INSERT INTO sessions(id,mode,started_at) VALUES(?,?,?)', [id, mode, now]);
      this.db.runSync('UPDATE control SET active_session=?,fault=NULL WHERE id=1', [id]);
      this.insertEvent(id, 'lifecycle', 'controller', now, 'start');
      return { id, mode, started_at: now, stopped_at: null };
    });
    this.accepting = true;
    return session;
  }
  close(now: number, fault: string | null = null) {
    this.accepting = false;
    this.tx(() => this.closeRows(now, fault));
  }
  private closeRows(now: number, fault: string | null) {
      const active = this.activeRow();
      // Invalidate the durable session before attempting asynchronous native shutdown.
      this.db.runSync('UPDATE control SET active_session=NULL,fault=? WHERE id=1', [fault]);
      if (active) {
        this.db.runSync('UPDATE sessions SET stopped_at=? WHERE id=?', [now, active.id]);
        if (this.count('events') < this.limit) this.insertEvent(active.id, 'lifecycle', 'controller', now, fault ?? 'stop');
      }
  }
  ownsSession(id: string | null): boolean {
    if (id === null) return this.activeRow() === null;
    return this.db.getFirstSync<{ id: string }>('SELECT id FROM sessions ORDER BY rowid DESC LIMIT 1')?.id === id;
  }
  beginNativeStop(id: string | null, now: number, fault: string | null): number | null {
    return this.tx(() => {
      if (!this.ownsSession(id)) return null;
      const barrier = this.db.getFirstSync<{ pending: number; token: number }>('SELECT * FROM native_barrier WHERE id=1')!;
      if (barrier.pending) return null;
      this.db.runSync('UPDATE native_barrier SET pending=1,token=token+1 WHERE id=1', []);
      this.accepting = false;
      this.closeRows(now, fault);
      return barrier.token + 1;
    });
  }
  finishNativeStop(token: number, fault: string | null = null) {
    this.tx(() => {
      const barrier = this.db.getFirstSync<{ pending: number; token: number }>('SELECT * FROM native_barrier WHERE id=1')!;
      if (!barrier.pending || barrier.token !== token) return;
      // A failed stop retains the durable start barrier, even across JS runtimes.
      if (fault) this.setFault(fault);
      else this.db.runSync('UPDATE native_barrier SET pending=0 WHERE id=1 AND token=?', [token]);
    });
  }
  setFault(code: string) { this.db.runSync('UPDATE control SET fault=? WHERE id=1', [code]); }
  markShutdownUnconfirmed() { this.db.runSync('UPDATE native_barrier SET shutdown_unconfirmed=1 WHERE id=1', []); }
  shutdownUnconfirmed() { return !!this.db.getFirstSync<{ shutdown_unconfirmed: number }>('SELECT shutdown_unconfirmed FROM native_barrier WHERE id=1')!.shutdown_unconfirmed; }
  lifecycle(id: string, state: 'active' | 'inactive' | 'background', now: number): boolean {
    return this.tx(() => {
      if (this.active()?.id !== id) return false;
      if (this.count('events') >= this.limit) return false;
      this.insertEvent(id, 'lifecycle', 'controller', now, state);
      return true;
    });
  }
  record(id: string, source: Mode, sample: unknown, now: number, precision: Precision): RecordResult {
    return this.tx(() => {
      const session = this.active();
      if (session?.id !== id || session.mode !== source) return this.bump('late');
      const result = validateSample(sample, now, precision);
      if (result.ok && result.value.capturedAt < session.started_at) return this.bump('late');
      if (result.ok && this.db.getFirstSync('SELECT id FROM events WHERE session_id=? AND sample_key=?', [id, result.value.key])) {
        return this.bump('duplicates');
      }
      if (this.count('events') >= this.limit) {
        this.db.runSync("UPDATE control SET active_session=NULL,fault='capacity' WHERE id=1", []);
        this.db.runSync('UPDATE sessions SET stopped_at=? WHERE id=?', [now, id]);
        return 'capacity';
      }
      if (!result.ok) {
        this.insertEvent(id, 'rejected', source, now, result.reason);
        return this.bump('rejected');
      }
      const v = result.value;
      const newest = this.db.getFirstSync<{ ts: number | null }>('SELECT MAX(captured_at) ts FROM events WHERE session_id=?', [id])?.ts;
      if (newest != null && v.capturedAt < newest) { v.flags.push('out_of_order'); v.eligible = false; }
      this.insertEvent(id, 'sample', source, now, v.flags.join(',') || 'eligible_at_receipt',
        [v.capturedAt, v.latitude, v.longitude, v.accuracy, v.eligible ? 1 : 0, v.key]);
      return 'saved';
    });
  }
  private bump(column: 'duplicates' | 'rejected' | 'late'): RecordResult {
    this.db.runSync(`UPDATE control SET ${column}=MIN(${column}+1,2147483647) WHERE id=1`, []);
    return column === 'duplicates' ? 'duplicate' : column;
  }
  snapshot() {
    const current = this.active();
    return {
      ...this.control(), shutdownUnconfirmed: this.shutdownUnconfirmed(),
      nativeCleanupPending: !!this.db.getFirstSync<{ pending: number }>('SELECT pending FROM native_barrier WHERE id=1')!.pending,
      count: this.count('events'), sessionCount: this.count('sessions'), limit: this.limit,
      currentSample: current ? this.db.getFirstSync<EventRow>(`SELECT session_id,sequence,kind,source,captured_at,received_at,accuracy,flags,eligible
        FROM events WHERE session_id=? AND kind='sample' ORDER BY captured_at DESC,id DESC LIMIT 1`, [current.id]) : null,
      latest: this.db.getAllSync<EventRow>(`SELECT session_id,sequence,kind,source,captured_at,received_at,accuracy,flags,eligible
        FROM events ORDER BY id DESC LIMIT 8`),
    };
  }
}
