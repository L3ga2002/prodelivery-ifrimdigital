import { DatabaseSync } from 'node:sqlite';
import { RecorderStore, type Sqlite } from '../src/store.ts';
import type { LocationPort, Permissions } from '../src/controller.ts';
import type { Mode } from '../src/sample.ts';

export const NOW = 1_800_000_000_000;
export const sample = (timestamp = NOW) => ({ timestamp, coords: { latitude: 46.5, longitude: 26.9, accuracy: 12 }, mocked: false });
export function database(path = ':memory:', limit = 1000) {
  const db = new DatabaseSync(path);
  const adapter: Sqlite = {
    execSync: sql => db.exec(sql),
    runSync: (sql, params) => ({ changes: Number(db.prepare(sql).run(...params).changes) }),
    getFirstSync: <T>(sql: string, params: (string | number | null)[] = []) => (db.prepare(sql).get(...params) as T) ?? null,
    getAllSync: <T>(sql: string, params: (string | number | null)[] = []) => db.prepare(sql).all(...params) as T[],
  };
  return { db, store: new RecorderStore(adapter, limit), adapter };
}
export function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
export class FakeNative implements LocationPort {
  permission: Permissions = { foreground: true, background: true, services: true, precision: 'precise' };
  available = true;
  starts = 0;
  stops = 0;
  requests: Mode[] = [];
  stopped = true;
  failStart = false;
  failStop = false;
  waitStart: Promise<void> | null = null;
  waitPermission: Promise<void> | null = null;
  waitStop: Promise<void> | null = null;
  callback: (value: unknown) => void = () => {};
  nativeError: () => void = () => {};
  async backgroundAvailable() { return this.available; }
  async permissions(mode?: Mode) {
    if (mode) this.requests.push(mode);
    if (mode && this.waitPermission) await this.waitPermission;
    return { ...this.permission };
  }
  async start(_mode: Mode, callback: (value: unknown) => void, error: () => void) {
    this.starts++; this.callback = callback; this.nativeError = error; this.stopped = false;
    if (this.waitStart) await this.waitStart;
    if (this.failStart) throw new Error('native detail must not reach UI');
  }
  async stop() { this.stops++; if (this.waitStop) await this.waitStop; if (this.failStop) throw new Error('native failure'); this.stopped = true; }
}
