# ProDelivery GPS: Android local build, 2026-10-09/10

## Scope

Catalin approved installation of free Google SDK tooling and necessary SDK
licenses, local build and installation on his authorized HONOR. Codex owns the
task; separate internal OpenAI implementation, review and QA roles were used.
No OpenClaw, Claude, paid cloud build, account credentials, client databases,
main application changes, Git mutation or publication.

This is the isolated GPS recorder, not the complete Stage5 courier application.
Its package is `ro.ifrimdigital.prodelivery.gpsprobe`. Collection requires the
tester to approve permissions and explicitly enable consent/Start on the phone.
No ADB permission grants, GPS activation, phone PIN use or unrelated phone files.

## Executed Source Checks

| Check | Fresh result |
| --- | --- |
| Immutable npm install in isolated short path | 475 packages installed, lockfile preserved |
| Strict TypeScript on final candidate | PASS, exit0 |
| Entire recorder test suite on final candidate | 101 passed, 0 failed/skipped/cancelled |
| Original tests | 58, unchanged; included in 101, not added twice |
| Added watchdog regressions | 43, included in 101 |
| Independent transient SQLite read regressions | 8/8 passed in memory with fake native port |
| Independent R2 native/static source QA | 60 passed, 8 skipped pending compiled/native evidence |
| Independent R2 config-plugin QA | 24 passed, 0 failed |
| Independent compiled test-APK gate | 20 passed, 0 failed, 3 skipped |
| Independent idle device UI evidence review | Four screenshot/JSON pairs inspected, scoped PASS; GPS untested |
| Android JS export, before watchdog delta | PASS, 718 modules; not final APK provenance |

Pure tests use fake native location and real SQL against Node SQLite. They do
not establish physical GPS, Expo native SQLite, battery, phone background
behavior or server synchronization. The 8 reviewer checks overlap targeted
regressions and are separate independent evidence, not 8 new product tests.
Historical main-application test counts were not rerun in this native task.

## SDK And Build Environment

- Node `24.14.0`; Java `21.0.10` from the installed Android Studio runtime.
- Installed lockfile resolves Expo `57.0.26` and React Native `0.86.3`.
- Google commandline archive `commandlinetools-win-15859902_latest.zip` was
  downloaded from `https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip`.
- Published SHA256 verified before extraction:
  `90AE805D20434428BFFCB699C290860F19BB5F66A67E6B330067E3DE801FB04A`.
- SDK root: `C:\Users\mihai\AppData\Local\Android\Sdk`.
- Platform36, build-tools36.0.0, platform-tools installed. Gradle also installed
  requested build-tools35.0.0, NDK27.1.12297006 and CMake3.22.1 with the approved
  Google licenses. This is not a downgrade of the app's target/compile SDK36.
- Effective intended app configuration: min24, target36, compile36, arm64-v8a.
- Build root: `C:\Users\mihai\AppData\Local\Temp\pd-gps-1009-b1\app`.
- Local junction `C:\pdg1009` targets ONLY this build's `.gradle` cache at
  `C:\Users\mihai\AppData\Local\Temp\pd-gps-1009-b1\.gradle`.
  No global environment/registry/long-path policy was changed.

SDK download checksum source: [Android Studio downloads](https://developer.android.com/studio).
Backup-rule interpretation: [Android Auto Backup](https://developer.android.com/identity/data/autobackup).

## Findings And Fixes

1. Native start/stop can remain pending indefinitely. A15s JS diagnostic now
   closes/fences local collection, exposes owner intervention, retains native
   shutdown UNCONFIRMED and preserves serialized late cleanup. Timeout is NOT
   native cancellation or a sensor acknowledgement; JS suspension can delay it.
2. Initial watchdog code armed the Start deadline before OS permission prompts.
   It now arms immediately before actual native start. A long legitimate prompt
   cannot fabricate a sensor attempt. Stop waiting only for preflight reports
   cancellation pending and prevents any later unapproved native start.
3. Generic Stop/unmount could overwrite a durable conservative fault. All close
   paths preserve the prior safety diagnostic before awaiting native shutdown.
4. A single transient SQL read error with working writes could still erase the
   fallback fault when latch persistence failed. Independent reproduction had
   `coldStarts=1`. The read-error branch now preserves the unknown durable fault,
   fences locally and attempts the latch without generic fault replacement.
   Four added tests were RED before fix; final101 are PASS. Independent eight
   read/Stop/late-completion combinations have `coldStarts=0`.
5. allowBackup=false alone is not a universal Android OEM D2D exclusion. An
   Expo config plugin emits explicit legacy/cloud/Android D2D exclusions for
   all nine storage domains, including the Expo SQLite directory and journals.
6. Diagnostic native Debug objects were linked with Release RN dependencies,
   causing missing Sealable/DebugStringConvertible ABI symbols. The scoped
   diagnostic CMake argument requests RelWithDebInfo, retaining debug access
   for local diagnostics but using matching Release native flags/dependencies.
7. Ninja hit a Windows260-character header path during the diagnostic build.
   A short owned Gradle-cache junction was tried. Actual CMake paths resolve
   back to the long physical cache path:0 short prefab references,10 long in
   app and60 long in Expo. Archiving only the owned generated cache allowed
   a fresh build to finish; incremental Windows rebuild reliability is NOT
   certified and this junction alone must not be described as a complete fix.

## File Changes

| File | Purpose |
| --- | --- |
| `App.tsx` | Bounded stop fallback and explicit cancellation/shutdown diagnostic UI |
| `src/controller.ts` | Native-only watchdog, serialized cleanup and durable fault preservation |
| `tests/watchdog.test.ts` | 43 real race/storage/permission regressions; original tests preserved |
| `app.json` | Registers two local config plugins; identity and existing permission flow retained |
| `plugins/android-backup-protection.cjs` | Explicit backup/transfer XML and manifest references |
| `plugins/android-diagnostic-build.cjs` | Embedded diagnostic variant, useDevSupport=false, matching native ABI |

Original22 source files were hash-snapshotted and copied before work. The actual
project's main frontend/backend are outside the native write set. Final source
integration, backup path, artifact identity and installation are recorded in the
task's separate final report, not inferred here from staged checks.

## Preserved Build History

- Baseline assembleRelease: SUCCESS,23m7s,299 tasks. APK31,095,166bytes,
  SHA256 `1467A5E2EEF387D7C910931A855080BB9F3FCCB7BD9D15116A1919965AF68FE8`.
  Preserved under build-root `baseline/`; NOT an install candidate: it lacks the
  final watchdog and diagnostic packaging.
- First diagnostic build: FAILED7m26s, path260 and Debug/Release native ABI.
  No diagnostic APK was generated; failure is not removed from the history.
- Final diagnostic rebuild: SUCCESS7m50s,184 tasks(156 executed,28 up-to-date).
  Both arm64 CMake components actually use RelWithDebInfo and -DNDEBUG:10app
  compilation commands,60Expo commands. Release ABI link succeeded.
- Final APK:33,844,909bytes, SHA256
  `C9EFFFD782B5FF0EC31E235F350C4724E186838F8906C752B9829F571B8E42FD`.
  Embedded bundle1,717,124bytes, SHA256
  `752BC7126438445293C4AFC4B6FCE81AC7FD8C954FF6CC7BA3048B95B857828B`.
  Signature verification passed. Installation/UI/compiled independent QA are
  separate gates recorded in the final device report; not inferred from build.

Warnings retained: third-party Kotlin/C++/Gradle deprecations, older Gradle SDK
XML parser warning, and Expo's optional expo-system-ui warning. No dependency
changes, warning suppression or validation weakening was used to hide them.

## Boundaries

- Diagnostic is deliberately debuggable, local and not suitable for store or
  production distribution. Embedded JS/dev support/OTA/compiled metadata need
  verification against the exact final APK, not app.json alone.
- iOS/cross-platform Android36.1 transfer is NOT certified. All-domain excludes
  are present, but real Apple platform-specific identifiers are unavailable;
  no Apple teamId is invented. Physical backup/restore was not run. Do not claim
  universal no-backup protection or trigger a transfer as part of GPS testing.
- Coordinates remain plaintext local SQLite. No timed expiry, encryption,
  reset, deletion, export, accounts, orders, upload or server replay is added.
- The existing foreground one-attempt/unconfirmed-shutdown contract remains.
  Do not clear app data/reinstall to bypass it; preserve evidence and use owner
  Android controls if native shutdown cannot be confirmed.
- Stage1 physical GPS gates and commercial Stage2 remain open. This build does
  not authorize Stage3+, live feature activation, real DB changes or deployment.
- At this task's health check3000/login and8000/api/ refused connections. Main
  web preview was not restarted for the independent offline native recorder.

For owner-controlled physical steps, read `INSTALL_AND_TEST.md`. No GPS matrix
is PASS until it is actually run on a consenting physical phone.
