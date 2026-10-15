# Probe source checkpoint

Date: 2026-10-02, Europe/Bucharest. Scope: this isolated `probe/` directory only.
Disposition: SOURCE_READY_FOR_INDEPENDENT_REREVIEW; DEPENDENCY_INSTALL / TYPECHECK / JS_EXPORTS BLOCKED.
This is not reviewer approval, a native-build result, physical GPS evidence, or Stage1 PASS.

## Review fixes

| Finding | Implemented behavior | Local verification |
| --- | --- | --- |
| R1 | Initialization attempts native cleanup even after SQLite failure; storage failure remains visible and restart stays blocked until reconciliation succeeds. | Independent R1 and additional combined storage/native failure regression pass. |
| R2 | Captured session fences stale success/error cleanup. A transaction claims a durable token/barrier before native Stop; Start is blocked until that stop finishes. Stale completion cannot write into a replacement. Failed/interrupted cleanup retains the barrier. | Both independent R2 cases plus pending-stop, failed-stop persistence and stale-token regressions pass. |
| R3 | Inactive/background cancels pending foreground Start; controller waits for late registration then cleans up. Native adapter rechecks AppState after registration. | Independent delayed-native-start case and own pending-permission/inactive case pass. Native AppState integration remains unexecuted. |
| R5 | Public SDK void unsubscribe is never treated as native acknowledgement. Foreground intent is durably marked before watch registration. Local session closure and unconfirmed native shutdown have separate UI states; repeated Stop/relaunch cannot clear the diagnostic or unblock Start. | Four explicit R5 tests pass for void/throwing/late subscriptions, local close versus unconfirmed shutdown, controller reconstruction and interrupted foreground intent. Hardware shutdown remains UNCONFIRMED by design. |

R1-R3 reproduced failures are closed in implementer verification. R5 is addressed by the explicit conservative diagnostic/recovery contract, not by claiming an acknowledged foreground shutdown API. Parent/reviewer owns final disposition. `review/` files were never edited.

## Executed tests

Runtime: Node v24.14.0, npm 11.9.0, Windows. Commands below were executed from this directory with `C:\Program Files\nodejs\node.exe`.

```powershell
& 'C:\Program Files\nodejs\node.exe' --experimental-strip-types --test --test-reporter=spec .\tests\*.test.ts
& 'C:\Program Files\nodejs\node.exe' --experimental-strip-types --test --test-reporter=spec ..\review\native-independent.test.mjs
```

- Own suite: **58 tests, 58 passed, 0 failed/skipped/cancelled**, exit 0; runner duration 3202.501 ms. Includes nine added review regressions (four R5). Pure validation and production SQL run against real Node SQLite; native location/permission/lifecycle behavior is mocked.
- Independent suite, unchanged: **28 tests, 28 passed, 0 failed/skipped/cancelled**, exit 0; runner duration 2836.7739 ms. This supersedes the preliminary 24/28 result for these source files, without rewriting the preliminary report.
- Earlier combined run: 77/77 passed (49 original own + 28 independent), before adding the nine new own regressions. Do not confuse 77 with the final 58 + 28 counts.
- Node emitted its expected experimental SQLite warning. Tests used synthetic data only; no native SQLite bridge, device location, backend or account was exercised.
- Independent test SHA256 before and after: `27ADB557B6BB86066484F68126616505DF632FC7C26EFDB20E03B7DB32E41379`.

## Dependency result and preserved failures

Exact direct pins come from official npm/Expo metadata, documented in `DEPENDENCIES.md`. No other project's dependency tree was used. Installation lifecycle scripts were disabled throughout.

| Command | Actual result |
| --- | --- |
| `npm.cmd install --ignore-scripts --no-audit --no-fund` | Session 33986 stalled without completion; individually interrupted, exit 1. Last log progress 19:51:18. No explicit network/permission error established. |
| `npm.cmd install --ignore-scripts --no-audit --no-fund --fetch-timeout=120000 --fetch-retries=1 --maxsockets=8 --loglevel=error` | Session 24762 stalled without completion; individually interrupted, exit 1. Last log progress 20:03:36. |
| `node "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js" install --offline --ignore-scripts --no-audit --no-fund --loglevel=verbose` | Session 17666 read cached packages but did not complete; individually interrupted, exit 1. Last log progress 20:21:55. |
| `node "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js" install --package-lock-only --offline --ignore-scripts --no-audit --no-fund --loglevel=error` | Session 37881 completed, exit 0, `up to date in 1m`. This resolves the lockfile only, NOT installed modules. |

`package-lock.json` now exists: 131244 bytes, written 20:26:42 +03:00, lockfileVersion 3. All **13/13 direct runtime/dev pins** match their lockfile versions. This is not proof of a complete or valid installed dependency tree. Partial `node_modules/` and cache were left intact, with no deletion or rollback. No more installation retries are pending or planned in this checkpoint.

Preserved npm logs, relative to this directory:

- `.npm-cache/_logs/2026-10-02T16_39_53_370Z-debug-0.log`
- `.npm-cache/_logs/2026-10-02T17_01_55_570Z-debug-0.log`
- `.npm-cache/_logs/2026-10-02T17_19_48_821Z-debug-0.log`
- `.npm-cache/_logs/2026-10-02T17_25_19_489Z-debug-0.log` (lockfile-only, exit 0)

The exact root cause of the stalled full installs is **not established**. Registry/cache responses succeeded; there was no observed approval denial, proven network outage or explicit npm error to justify claiming one. The verified immediate blocker is incomplete package extraction/availability.

## Typecheck and platform exports

Final typecheck attempt:

```powershell
& 'C:\Program Files\nodejs\node.exe' .\node_modules\typescript\bin\tsc --noEmit --incremental false
```

Exit 1, four diagnostics (session 50609):

```text
App.tsx(2,97): TS2307 Cannot find module 'react-native' or its corresponding type declarations.
App.tsx(32,58): TS7006 Parameter 'state' implicitly has an 'any' type.
App.tsx(58,24): TS2322 NativeSafeAreaViewProps does not expose style in this unresolved type context.
src/native.ts(4,36): TS2307 Cannot find module 'react-native' or its corresponding type declarations.
```

Earlier transient typechecks also encountered incomplete React Native declarations; an actual Expo SQLite adapter optional-parameter type mismatch was fixed with an explicit adapter, without weakening strict types. Final full typecheck remains **BLOCKED / NOT_PASSED**. Additional diagnostics cannot be ruled out until dependencies are complete. No `any` shim or substituted SDK version was added to conceal the blocker.

Both platform commands were attempted locally with process-only `CI=1`, `EXPO_OFFLINE=1`, `EXPO_NO_TELEMETRY=1`, `EXPO_NO_DOTENV=1`, `EXPO_HOME=<probe>/.expo-home`, and `TEMP=TMP=<probe>/.tmp`:

```powershell
& 'C:\Program Files\nodejs\node.exe' .\node_modules\expo\bin\cli export --platform android --output-dir dist/android
& 'C:\Program Files\nodejs\node.exe' .\node_modules\expo\bin\cli export --platform ios --output-dir dist/ios
```

Each exited 1 before bundling with `Error: Cannot find module '@expo/cli'`, required by `node_modules/expo/bin/cli`. Android JS export: **BLOCKED**. iOS JS export: **BLOCKED**. No successful bundle, APK or IPA is claimed. No server was started. Native configuration generation/build and visual/device UI checks were not run.

## Checkpoint and external gates

`SOURCE_HASHES.json` lists the owned source/config/tests/docs and SHA256 values, including this report and the lockfile. It excludes itself, ignored dependencies/cache/build output and synthetic test databases. Its separate independent-test entry is a read-only integrity reference, not an ownership claim. The source/config is frozen for final independent review; further changes require a new verification snapshot.

Known owned install/test/typecheck sessions are all finished or individually interrupted; none is intentionally left running. No broad process kill, source revert, data deletion, native SDK install, cloud account/build, device pairing/install/permission, physical GPS recording, external publication or real backend action was performed. Existing ProDelivery source/config/memory were untouched. Parent owns publication and stage planning.

Executable now: pure Node/real-SQLite/controller regression suites and source review. Internal work still incomplete: full dependency installation, strict typecheck, both JS exports, supported native binaries and device UI verification. External prerequisites: consenting physical Android/iPhone, a viable Android build path, and macOS/Xcode/signing/device path for iOS. These are not approval blockers for harmless internal preparation, but they remain prerequisites for physical acceptance.

Foreground/background/lockscreen, actual offline capture, recovery, permission revocation and battery behavior remain **NOT_RUN** on physical devices. Simulator/browser behavior would not replace them. Server reconnect/sync is **OUT_OF_SCOPE / NOT_RUN**: this app is only a bounded local recorder. The conservative foreground recovery procedure in `README.md` requires owner OS intervention and later authorized evidence-preserving recovery, not an automatic in-app unblock. Stage1 remains open and the Stage5 courier app has not begun.
