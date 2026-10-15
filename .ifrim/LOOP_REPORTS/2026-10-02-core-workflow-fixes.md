# ProDelivery - Incremental core workflow fixes, 2026-10-02

Scope: `PD-CORE-CANCELLED-01` and `PD-CORE-PREP-DISPATCH-01`, plus directly related independent review findings. Classification: engineering_support for Stage 1 baseline closure, not automatic activation of later commercial stages. Current commercial plan remains the ten-stage 10,000 EUR execution plan. Minimum ten feasible active orders per same courier remains planned; the live application's singular `current_order_id` is unchanged.

## Concrete implementation

| File | Change and reason |
| --- | --- |
| backend/models/order.py | Optional additive preparation_status NEW/PREPARING/READY, preserving public dispatch status and legacy compatibility. No data migration. |
| backend/routers/orders.py | Cancelled/delivered excluded from active driver feed; preparation and actual readiness coexist with ASSIGNED/ACCEPTED; snapshot CAS, idempotency, timer preservation and role/object guards; pickup requires actual readiness, never expired estimate. Exclusive driver reservation and owner-guarded release prevent reviewed stale/duplicate schedules from corrupting another reservation. Separate once-per-winning-terminal-CAS delivery credit. Strict legacy timestamp/calendar/timezone validation before mutation. |
| backend/routers/stats.py | Active count excludes cancelled and delivered, retaining full history and totals. |
| backend/tests/test_order_dispatch_preparation_regression.py | 651 independently authored cases covering real handlers, malformed inputs, role/object checks, deterministic interleavings, duplicate mutations, timer/audit/ownership/credit invariants and legacy compatibility. |
| frontend/src/lib/orderWorkflow.js | Shared narrow status/preparation/grouping predicates; fail-closed malformed legacy values and consistent API/UI behavior. |
| frontend/src/lib/orderWorkflow.test.js | 74 focused helper cases; unchanged lint policy, explicit Jest globals. |
| frontend/src/pages/RestaurantApp.jsx | Assigned/accepted orders retain preparation controls, timer, readiness and counts; synchronous action lock, pending/offline disabled states, stale-response invalidation and refresh after errors. |
| frontend/src/pages/DriverApp.jsx | Actionable selection ignores cancelled/malformed records; pickup and confirmation gated on actual readiness. Bottom spacing includes actions and safe-area so fixed navigation no longer covers delivery button. |
| frontend/src/pages/AdminDashboard.jsx | Known active statuses only, consistent terminal exclusion while preserving history inputs. |

No major redesign, rewrite, package/config change, paid provider, secret/env change, live database mutation, Git reset/commit/push or deployment. Existing dirty project changes and original protected tests preserved. Publication is guarded by original SHA256 hashes with backup before source copying.

## Verification

- Independent final backend suite: **672 passed / 0 failed / 0 errors / 0 skipped**, including both unchanged protected suites 9+9 and three safe pure security cases. These are unit/in-memory handler tests, NOT live database integration proof.
- Independent regression lineage: 104 + 34 + 407 + 106 = 651 cases. Last red run: 596 pass / 76 fail, representing B3-R ownership and F1-R offset gaps. Same tests then 672 green; no deleted/weakened tests. Earlier initial failure histories are preserved in QA reports.
- Frontend helper suite: **74/74 passed** on final source; full src lint **0 errors / 0 warnings / 78 files**.
- Production compilation: succeeded; compiled staging assets main.a83d7bdb.js / main.e3aa0bcf.css. No deployment implied.
- Guarded synthetic HTTP contract suite: **27/27 passed** on final backend.
- Headed browser: **18 grouped checks passed**, actual clicks and navigation, affected and adjacent paths, controlled error, offline/reconnect, delay/loading, duplicate-request counts, expired timer, refresh, malformed legacy data, desktop/mobile screenshots. See browser-qa-report.md for exact cases, harness corrections, console warnings and boundaries.
- Independent reviewer disposition is in backend-review.md/frontend-review.md. Initial findings remain in the reports; latest disposition supersedes them without erasing history.

Historical network integration tests are NOT run against the real database: they require real credentials and mutations prohibited by this packet. No statement that the entire production integration suite passed.

## Preview and evidence

Local application: http://127.0.0.1:3000/login ; API: http://127.0.0.1:8000/api/ . Synthetic browser routes tested at http://127.0.0.1:18943/admin, /restaurant and /driver. Synthetic servers are stopped after QA; no synthetic data are persisted into real DB.

Evidence saved under `.ifrim/QA_RUNS/2026-10-02-core-fixes`, task packet under `.ifrim/TASK_PACKETS/2026-10-02-core-workflow-fixes.md`, backup under `.ifrim/BACKUPS/2026-10-02-core-fixes-verified`.

Manual check: admin creates/selects a test order and assigns courier before preparation; restaurant can set preparation and mark actually ready without losing courier; courier cannot pick up before actual readiness, then can pick up and deliver. Cancelled order stays in history and does not hide the active assignment or inflate active stats. Use only an authorized test account/data set for this manual procedure; this report does not authorize creating live/client orders.

## Stage gate and remaining risks

Stage 1 remains **in_progress**. Catalin authorized Stage 2 only after ALL Stage 1 required evidence passes. Missing gates: separate real Mongo concurrency/crash-recovery probe and physical Android/iOS background GPS feasibility. Approval/device availability questions have been asked, with no answer yet. No conversion of the live standalone DB or creation of a separate DB without approval.

Also not complete: multiple simultaneous assignments in the application, OCR, provider-specific connector (documentation deferred), native apps, GPS reliability, external notifications, load benchmark, backups/restore infrastructure and public production launch. Do not label the two source fixes or the synthetic solver specification as finished automatic allocation for ten orders.

Residual warnings: inherited Starlette/httpx and Node deprecations; browser gesture restrictions for sound/vibration; inherited dialog accessibility warning; telemetry privacy review before production. No new lint warning.

Next best task: approve/provision fully separate synthetic Mongo test environment and identify available Android/iPhone devices; execute missing Stage 1 probes, update evidence, then only if gate is green start Stage 2 commands/admin packet. API documentation can remain deferred, as Catalin requested.

## Post-integration verification

Guarded publication actually completed: nine source/test files and three small additive project-memory updates. All twelve real target hashes match the verified staging manifest; both original protected test hashes are unchanged. Backup, packet and QA destinations exist. An earlier staging evidence audit E1 correctly noted that publication was still planned at its inspection time; the initial finding is retained, with subsequent independent closure after publication.

Safe tests rerun against actual published backend source: **672 passed**, same existing deprecation warning. The first attempt was blocked before test collection by sandbox parent-directory permission, not an application assertion failure; explicit backend rootdir/confcutdir and elevated read resolved it. No real DB was contacted.

Preview source routes additionally tested: **3/3 browser checks passed** at http://127.0.0.1:3000/restaurant, /driver and /admin, with business API traffic still exclusively redirected to synthetic loopback QA. Both frontend login and actual API health return HTTP200. These three checks are separate from the 18 grouped staging-build checks and are not real authentication/database proof.

Final browser per-script logs and structured Result sections are saved alongside screenshots. Synthetic services and the owned browser QA session are stopped after evidence collection; normal preview3000/8000 remains available. No Stage 2 gate or production claim is made.
