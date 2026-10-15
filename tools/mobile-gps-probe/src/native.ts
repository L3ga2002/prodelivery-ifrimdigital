import * as Location from 'expo-location';
import * as TaskManager from 'expo-task-manager';
import * as SQLite from 'expo-sqlite';
import { AppState, Platform } from 'react-native';
import type { LocationPort, Permissions } from './controller.ts';
import { RecorderStore, type Sqlite } from './store.ts';
import type { Mode } from './sample.ts';
import { recordBackgroundBatch } from './background.ts';
import { ForegroundWatch, UNCONFIRMED } from './shutdown.ts';

export const TASK_NAME = 'prodelivery-local-gps-v1';
let store: RecorderStore | undefined;
export function getStore() {
  if (!store) {
    const database = SQLite.openDatabaseSync('prodelivery-gps-probe-v1.db');
    const adapter: Sqlite = {
      execSync: sql => database.execSync(sql),
      runSync: (sql, params) => database.runSync(sql, params),
      getFirstSync: <T>(sql: string, params: SQLite.SQLiteBindValue[] = []) => database.getFirstSync<T>(sql, params),
      getAllSync: <T>(sql: string, params: SQLite.SQLiteBindValue[] = []) => database.getAllSync<T>(sql, params),
    };
    store = new RecorderStore(adapter);
  }
  return store;
}

export async function readPermissions(): Promise<Permissions> {
  const foreground = await Location.getForegroundPermissionsAsync();
  const background = await Location.getBackgroundPermissionsAsync();
  const accuracy = foreground.android?.accuracy ?? foreground.ios?.accuracy;
  return {
    foreground: foreground.granted, background: background.granted,
    services: await Location.hasServicesEnabledAsync(),
    precision: accuracy === 'fine' || accuracy === 'full' ? 'precise' :
      accuracy === 'coarse' || accuracy === 'reduced' ? 'approximate' : 'unknown',
  };
}

export async function stopBackground() {
  if (await Location.hasStartedLocationUpdatesAsync(TASK_NAME)) await Location.stopLocationUpdatesAsync(TASK_NAME);
  if (await Location.hasStartedLocationUpdatesAsync(TASK_NAME)) throw new Error('native_stop_failed');
}

export function makeNativePort(): LocationPort {
  const watch = new ForegroundWatch();
  return {
    backgroundAvailable: async () => Platform.OS !== 'web' && await TaskManager.isAvailableAsync() && await Location.isBackgroundLocationAvailableAsync(),
    permissions: async (request?: Mode) => {
      if (request && await Location.hasServicesEnabledAsync()) {
        const fg = await Location.getForegroundPermissionsAsync();
        if (!fg.granted && fg.canAskAgain) await Location.requestForegroundPermissionsAsync();
        if (request === 'background' && (await Location.getForegroundPermissionsAsync()).granted) {
          const bg = await Location.getBackgroundPermissionsAsync();
          if (!bg.granted && bg.canAskAgain) await Location.requestBackgroundPermissionsAsync();
        }
      }
      return readPermissions();
    },
    start: async (mode, onSample, onError) => {
      if (Platform.OS === 'web') throw new Error('native_build_required');
      if (AppState.currentState !== 'active') throw new Error('foreground_start_required');
      if (mode === 'foreground') {
        getStore().markShutdownUnconfirmed();
        watch.begin();
        watch.attach(await Location.watchPositionAsync({ accuracy: Location.Accuracy.High, timeInterval: 10_000, distanceInterval: 0, mayShowUserSettingsDialog: false }, onSample, onError));
        if (AppState.currentState !== 'active') throw new Error('foreground_start_required');
      } else {
        await Location.startLocationUpdatesAsync(TASK_NAME, {
          accuracy: Location.Accuracy.High, timeInterval: 10_000, distanceInterval: 0,
          deferredUpdatesInterval: 10_000, pausesUpdatesAutomatically: false,
          activityType: Location.ActivityType.OtherNavigation, showsBackgroundLocationIndicator: true,
          mayShowUserSettingsDialog: false,
          foregroundService: {
            notificationTitle: 'ProDelivery: recorder GPS local',
            notificationBody: 'Sesiune activa. Oprire din aplicatie.',
            notificationColor: '#16734b', killServiceOnDestroy: true,
          },
        });
      }
    },
    stop: async () => {
      let failed = false;
      try { watch.close(); } catch { failed = true; }
      try { await stopBackground(); } catch { failed = true; }
      if (watch.unconfirmed) throw new Error(UNCONFIRMED);
      if (failed) throw new Error('native_stop_failed');
    },
  };
}

// Module-scope registration is required when the OS launches a headless task.
TaskManager.defineTask<{ locations?: Location.LocationObject[] }>(TASK_NAME, async ({ data, error }) => {
  await recordBackgroundBatch({ store: getStore, permissions: readPermissions, stop: stopBackground, now: Date.now }, data, !!error);
});
