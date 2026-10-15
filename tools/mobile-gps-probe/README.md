# ProDelivery local GPS recorder

Isolated Stage1 technical probe. Preparation is approved. Existing React/FastAPI source, databases and project memory are untouched. Android/iOS identifier: `ro.ifrimdigital.prodelivery.gpsprobe`. This is not the Stage5 courier application.

## Behavior

- Explicit foreground/background selection, local-storage consent and Start/Stop. Launch only reads permission status and attempts to stop an interrupted native session; it never requests permissions or starts collection automatically. Background Start has a separate explanation before any OS permission flow.
- Foreground mode ends when the app leaves the active state. Background mode uses a module-scope Expo TaskManager registration and an Android location foreground service / iOS location background mode. Both require a compatible native binary. Expo Go and web are not background-GPS evidence.
- SQLite stores session IDs, ordered sequence numbers, capture/receipt timestamps, source, coordinates, reported accuracy and classification flags. The global limit is 1,000 event rows and 100 sessions, including lifecycle/rejected events. At capacity the recorder stops; prior rows remain. Duplicate/late counters are bounded integers. There is no reset, rotation, deletion, export or share command.
- Duplicate samples do not create another row. Invalid coordinates/accuracy/timestamps are rejected without storing their coordinates. Samples over 24 h old or over 5 s in the future are invalid. Valid stale (>90 s), approximate, mocked, low accuracy (>100 m), unknown precision/accuracy, clock-ahead and out-of-order samples are retained as ineligible observations. These are internal diagnostic thresholds, not an operational SLA.
- Stop invalidates the callback generation and durable session before native shutdown, then waits for any pending start and attempts cleanup. SQLite failure cannot skip native cleanup. A foreground Start is cancelled on inactive/background even while permissions or watch registration await. Permission checks run every 2 s while JS is active, on lifecycle changes and before background batches. OS suspension can delay checks; this is not a guaranteed revocation-detection deadline.
- A stale background batch cannot close/fault/stop a newer session. A transaction claims a durable native-stop barrier before asynchronous shutdown; replacement Start is blocked until that exact stop finishes. Failed or interrupted headless cleanup retains the barrier without automatic release. Genuine unreadable-storage failures still attempt fail-closed native shutdown.
- An interrupted foreground/UI process is closed on the next UI initialization. A headless task may serve an explicitly started active background session; task registration alone never starts one. A cold UI launch ends that session rather than silently beginning another.

## Privacy and limits

This is a **local recorder**, not a server-reconnect proof. There is no fetch/HTTP/socket upload, account login, live backend, order action or automatic sharing in the probe source. Offline observations remain on the device; nothing is replayed to a server after internet recovery. OTA updates are disabled.

Coordinates are not rendered in the UI or logged to the console. They are stored as plaintext in the app's SQLite sandbox (`prodelivery-gps-probe-v1.db`), including SQLite journal/WAL files. There is no application-level encryption or timed expiry. Android OS backup is disabled in app config. iOS/device-owner backups are not controlled or verified by this probe, so do not equate local app storage with a guarantee against OS/cloud backups. Use only a consenting tester's non-client route and a device whose backup settings are acceptable.

At capacity, retain evidence and agree a separate owner-controlled disposal procedure. There is deliberately no destructive reset here. If storage and native shutdown both fail, the UI/task surfaces an error; software tests cannot establish that the OS stopped its sensor. The owner must check the device indicator/settings before assuming tracking is off.

## Native shutdown and recovery contract (R5)

Expo SDK57 `watchPositionAsync()` returns a subscription whose public `remove(): void` removes the JS callback but does not return/await `removeWatchAsync`. Awaiting that void value cannot confirm native shutdown. No SDK patch or private native API is used here.

The foreground adapter durably marks shutdown as unconfirmed **before** attempting a watch. On Stop, the session is closed and late callbacks rejected, but the controller reports `foreground_shutdown_unconfirmed`, not native success. The UI separately displays the SQLite session and native shutdown status. The diagnostic and Start block survive repeated Stop, remount, app relaunch and reconstructed storage. A watch returned after a lifecycle cancellation is unsubscribed by the serialized cleanup and still remains unconfirmed. A crash before Stop retains the same durable diagnostic.

This intentionally limits a foreground probe to one attempted native recording per fresh diagnostic store. There is no automatic reset, second-session bypass, or claim that relaunch repairs the hardware state. Similarly, failed/interrupted headless shutdown keeps `native_cleanup_pending`. The device owner must stop the application via OS controls, inspect location indicators/permissions and preserve diagnostic evidence; an authorized recovery/disposal procedure and physical stop verification remain external prerequisites before a subsequent probe. This preparation performs none of those actions. Even `api_acknowledged` for background means only that the supported native APIs returned and reported the task unregistered, not physical sensor/battery evidence.

## Local verification

Node 24.14.0 was used. Install only inside this directory:

```powershell
& 'C:\Program Files\nodejs\npm.cmd' ci --ignore-scripts --no-audit --no-fund
& 'C:\Program Files\nodejs\npm.cmd' test
& 'C:\Program Files\nodejs\npm.cmd' run typecheck
```

For local JS export, no Expo account is needed. Run each platform after setting these process-local values:

```powershell
$env:CI='1'
$env:EXPO_OFFLINE='1'
$env:EXPO_NO_TELEMETRY='1'
$env:EXPO_NO_DOTENV='1'
$env:EXPO_HOME=Join-Path (Get-Location) '.expo-home'
$env:TEMP=Join-Path (Get-Location) '.tmp'
$env:TMP=$env:TEMP
& 'C:\Program Files\nodejs\npm.cmd' run bundle:android
& 'C:\Program Files\nodejs\npm.cmd' run bundle:ios
```

Tests exercise pure validation, controller races and the actual production SQL against Node's SQLite engine, including reopen/two connections/capacity/deduplication. Native location and permissions are test doubles. Tests leave only synthetic databases under ignored `.tmp/`. They do not test the Expo SQLite native bridge or phone GPS.

No native build, prebuild, SDK installation, pairing, phone install, GPS permission request, physical recording, paid service or Expo cloud build was performed for preparation. A future native build and consenting physical Android/iPhone are required for the physical matrix. Stage1 remains open.

## Source map

| File | Purpose |
| --- | --- |
| `App.tsx`, `index.ts` | Diagnostic controls/status and entry-point task registration |
| `src/sample.ts` | Validation and observation classification |
| `src/store.ts` | Portable SQLite SQL, durable session gate and bounded event store |
| `src/controller.ts` | Permission/start/stop/lifecycle controller |
| `src/background.ts` | Headless batch controller with the same store and stop gate |
| `src/native.ts` | Expo SQLite/Location/TaskManager adapters |
| `src/shutdown.ts` | Explicit foreground unsubscribe versus native-acknowledgement contract |
| `tests/*.test.ts`, `tests/helpers.ts` | Validation, real SQLite and lifecycle/background tests |
| `app.json`, `package.json`, `package-lock.json`, `tsconfig.json` | Isolated native configuration and pinned dependencies |
| `DEPENDENCIES.md`, `VERIFICATION.md` | Version evidence and executed results/gaps |

Parent owns publication, Stage2 planning and independent review. This folder's tests are implementer verification only.
