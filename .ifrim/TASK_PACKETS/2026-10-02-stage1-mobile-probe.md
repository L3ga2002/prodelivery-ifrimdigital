# PD-MOBILE-PROBE-01 / pregatire etapa 2

Date: 2026-10-02. Project: ProDelivery, real root C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery.

## Scope and authorization

Catalin requests the next-stage plan and conditional start after current-stage tests pass. Stage 1 remains in_progress; Stage 2 not_started. Native probe preparation is already approved. No new commercial stage, production database, environment, credentials, paid cloud build, publication, Git action, or external message is authorized here.

- Owner: Codex coordinator for Stage 2 plan and integration; internal Codex mobile implementer for probe only.
- Review: independent internal Codex reviewer, report and tests only.
- QA: pure logic tests, SQLite adapter tests where feasible, typecheck and both platform JS bundles; physical Android/iOS checks NOT_RUN until devices/build path are available.
- Routing: Codex only with internal subagents; OpenClaw/Claude explicitly excluded by Catalin.
- Lock: disjoint staging write sets, mobile implementer owns probe/; coordinator owns documents/publication; reviewer owns review/.
- Backup: new files only initially. Before publishing existing memory additions, hash-guard and backup exact prior files; never mass replace project memory.

## Native probe acceptance

Isolated Expo/React Native diagnostic app using the supported SDK 57 family, exact package versions from official compatibility metadata. No modifications to the existing React/FastAPI application. Separate application identifier. Internal technical probe, not a released driver app.

1. Explicit foreground/background mode and start/stop. No automatic permission request or tracking on initial launch. Native permission denial/revocation, unavailable background mode, double-click and start/stop errors remain visible.
2. Top-level task registration, foreground service/background configuration per Expo official SDK 57 docs; no claim that Expo Go/web proves background GPS.
3. Durable device-local SQLite recording with bounded capacity, session identity, sequence, source, sample/receipt time and accuracy. No silent deletion or destructive reset. Stop must reject late callbacks and stop native tracking; failures never display false success.
4. Validate invalid/old/future timestamps, coordinates/accuracy and duplicate samples. Distinguish stale/approximate/mocked observations from eligible coordinates; no current position is fabricated.
5. No network upload/client login or live order actions. Record local observations while offline; true reconnect/sync to server remains out of scope and NOT_RUN. Export/share GPS data must not occur automatically.
6. Useful local counters/errors without coordinates in console logs. Document storage/privacy limits of this internal probe.
7. Tests must exercise real validation, controller lifecycle, persistence/duplicate/capacity behavior; do not claim mocks prove device behavior.
8. Verify dependencies/typecheck/Android+iOS JS bundling where possible; native build and physical OS/background/battery/reconnect tests reported separately.

## Stage 2 plan acceptance

Read current application source and specs, retain working features, map each increment to files/contracts/tests. Explicit dependency gate on Stage 1 physical probe and accepted spec. Include manual allocation/reallocation plus compatibility with later automatic multi-order allocation, minimum 10 when feasible; no two-order limit. Define rollback, authorization, duplicate/conflict/audit and end-to-end acceptance. No Stage 2 production implementation in this packet.

## Preview

Existing http://127.0.0.1:3000/login and http://127.0.0.1:8000/api/ returned HTTP 200 at task start. Existing UI unchanged; no production order creation. Native preview blocked pending native build tooling and physical devices, not replaced with web GPS simulation.

## Primary references

- https://docs.expo.dev/versions/v57.0.0/sdk/location/
- https://docs.expo.dev/versions/v57.0.0/sdk/task-manager/
- https://docs.expo.dev/versions/v57.0.0/sdk/sqlite/
- https://expo.dev/changelog/sdk-57
