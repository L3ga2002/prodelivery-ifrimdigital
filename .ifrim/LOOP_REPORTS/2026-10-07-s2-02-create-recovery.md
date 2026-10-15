# ProDelivery - S2-02 backend create/recovery

Date: 2026-10-07. Scope: the approved expanded Stage 2 plan, lots S2-02A/B/C.
Coordinator/implementation: Codex. Independent reviewer: Epicurus. Independent
test author and QA: Popper. No OpenClaw or Claude invocation, as requested.

## Delivered scope

- Additive authenticated create-operation API and read-only recovery lookup.
- Immutable operation identity, semantic payload binding and durable admission.
- Same identity retries/replays without an additional order, including lost ACK
  and interrupted process recovery, on the tested replica-set fixture.
- Transactional order, numbering, critical audit and resolved operation receipt.
- Current authoritative role/tenant/account checks, restaurant pause/close guards,
  finite retry budgets, deadline handling and serialized deferred session cleanup.
- Sanitized validation/error responses and no-store operation responses.
- Existing business pricing preserved; legacy POST /api/orders remains unchanged.

Source changes:

| File | Reason |
| --- | --- |
| backend/utils/order_creation.py | Recoverable transaction/admission protocol, authorization, data checks, bounded retry and session lifecycle |
| backend/routers/order_operations.py | Additive POST and GET APIs, private receipts and sanitized HTTP validation |
| backend/tests/test_order_creation_recovery.py | 112 independently authored service and fault-injection regressions |
| backend/server.py | Only import and registration of the new router |

The original server and original project-memory files were backed up before
integration. Existing unrelated dirty changes were preserved. No UI design,
legacy create handler, secrets, environment, application database, activation
marker, indexes, topology, Git history/remotes, commit, push or deploy changed.

## Evidence and final verification

Final integrated-checkout totals and exact source hashes are recorded in
verification.json, published-source.json and the referenced XML/JSON artifacts.
The selected suite is not a claim that every historical integration test ran.

Final totals: **121 new + 1193 existing backend + 74 unchanged frontend helper
tests = 1388 distinct selected automated tests passed**, zero final failures or
skips. Independent QA reran 112 of the new service tests; those reruns are not
counted twice. Additionally **3/3 OS process checks passed** on integrated source.
The Pydantic warning is intentional malformed-output injection; the baseline also
reports the existing Starlette/httpx deprecation.

New-source flake8 E9,F passed. Including existing server.py exposed its preexisting
unused database.db import (F401), confirmed in the original backup. It was not
removed as an unrelated edit. git diff --check passed, with only an existing
LF/CRLF advisory for tools/claude-review.ps1. These checks are not full project lint.

Local preview was restarted only after verifying ownership of its old uvicorn
processes. Final GET checks: login/API/OpenAPI 200, both new paths mounted, and
unauthenticated operation lookup 401. No authenticated live mutation was performed.
The owned Mongo test fixture PID 20284 was stopped; synthetic data retained.

- published-create.xml: new service + authenticated HTTP regression suite.
- published-baseline.xml: selected existing backend regression/contracts/security.
- frontend-regression.json: existing frontend helper tests; no frontend changes.
- process-published.json: three real owned-child-process interruption/concurrency
  checks against the isolated synthetic database.
- qa-release.xml / QA_RELEASE.md: independent 112-case service verification.
- REVIEW_RELEASE.md: independent final source review; older review artifacts are
  historical snapshots, not the final decision.
- live-health.json: read-only local preview/API/OpenAPI/mounted-route checks.

HTTP tests use real JWT verification with a synthetic test key and unique test
databases. They do not certify password login, live authentication configuration,
CORS, physical devices, browser interaction or public deployment.

The fixture uses an owned loopback Mongo replica set on port 27941, never the
application database. Synthetic databases are retained, not erased. The fixture
is stopped after verification; its data/runtime-state are not copied into project
reports. No external services or customer data were used.

## Review findings and fixes

First review exposed 38 new service regressions and five HTTP privacy regressions
in focused RED runs. A second review added five lifecycle regressions. These are
48 distinct added regression cases, not the failure count of one full initial
suite. The initially implemented 70-case suite had passed before those additions.

Fixes cover persisted-intent integrity, BSON integer counters, defensive output
checks, transactional authorization/restaurant serialization, response deadlines,
sanitized FastAPI validation, and non-cancellable Motor executor work.

Three older fault simulations initially kept an artificial 60-second read alive
without the real driver's deadline. QA replaced only their completion simulation
with explicit release barriers while retaining strict response bounds, injection,
no-overlap, worker-done and private-error assertions. No test was deleted/skipped
and no production validation was relaxed. qa-fixture-diagnostic.xml retains the
three diagnostic failures; qa-lifecycle-serial-green.xml is historical despite
its name and still contains the real N1 failure.

That retained N1 test revealed Python 3.14 asyncio.shield logging late raw
exceptions despite central exception observation. The service now uses
asyncio.wait around tracked worker futures, consumes late exceptions and defers
abort/end until the original session worker completes. Final QA checks the strict
privacy and serial-session assertions. See QA_NOTES.md for the full RED history.

## Activation and compatibility boundaries

The new path is not connected to the frontend. New admission requires the explicit
enabled order-create-v1 setting and transaction support. No live activation or
counter provisioning was performed. Counter reconciliation, retention/access
controls, backup/restore and operational activation require a separate approved
step. Existing pending intents can recover after admission is disabled; completed
receipts can be read/replayed without enabling new admission.

Admission disabling is a preflight cutoff, not a strict linearized kill switch.
The operation's order_version=0 is an immutable creation receipt, not the current
business revision. No business order_version/CAS was activated. S2-COMPAT remains
mandatory before versioned changes to existing order writers.

The work deadline is 10 seconds, with three transaction and three commit attempts.
Cleanup has .25-second wait budgets per action; response time can include roughly
.5 seconds additional cleanup plus scheduling. Deferred worker/session cleanup
can outlive the response. This is not a universal hard 10.000-second response or
executor-thread-drain guarantee. Driver timeouts use CSOT:
https://motor.readthedocs.io/en/stable/examples/timeouts.html

Identity records retain the command for recovery. Do not add automatic TTL/deletion
without a retention/idempotency design: forgetting an identity can create duplicates.

## Remaining work and next lot

- S2-02D: connect admin order creation to the recoverable protocol, persist the
  original intent through timeout/refresh, show pending/rejected/replayed outcomes,
  prevent duplicate submit, and verify real browser valid/invalid/error flows.
- Do not silently fall back from an uncertain recoverable intent to legacy create.
- S2-COMPAT before integrating revision/CAS into existing edits/status writers.
- Legacy problem/follow-up creation and other status side effects are not converted
  by this increment. Current current_order_id remains singular.
- Stage 2 remains in progress; Stage 1 physical native/GPS evidence is incomplete.
- No automatic multi-order dispatch, ten-order route feasibility, native release,
  real GPS, sustained load benchmark, Mongo failover or store publication claim.
- The process checks cover kill after admission and kill after commit before ACK,
  plus two-process duplicate intent. They do not prove kill during Mongo commit,
  actual packet loss or primary failover.
- Late start_session completion is protected in source but has no separate targeted
  executor regression in this increment. Sharded and real standalone deployments
  were not tested; unsupported topology was injected.

Local preview: http://127.0.0.1:3000/login
Backend: http://127.0.0.1:8000/api/
No fresh UI click-through claim is made for this backend-only checkpoint.
