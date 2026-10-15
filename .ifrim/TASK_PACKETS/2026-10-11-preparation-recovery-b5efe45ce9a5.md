# A8 — preparation and READY recovery sublot

Project: ProDelivery. Authorized by the user's request to start the proposed refactor while retaining all client functionality. This is the explicit backend sublot anticipated by the approved plan, because existing state-idempotent PUTs cannot attribute a lost response to a particular preparation time.

## Owners and separation

- Backend owner: refactor_preparation_backend; stages code only.
- Frontend owner/integrator: root.
- Independent reviewer: refactor_review_resume.
- Independent runtime QA: refactor_qa_resume.
- Baseline, backups and prior integration receipts: QA_RUNS/2026-10-11-restaurant-refactor-b5efe45ce9a5.

## Scope

Add strict preparation commands/receipts and an additive durable service using the existing operation ledger and runtime. Preserve legacy PUT routes, authentication, financial policy, transactions of existing services, existing test files and all restaurant features. No migration, production marker activation, deployment, Git writes, live database, phone action or paid external agent.

Backend editable files: new models/order_preparation_operations.py; new utils/order_preparation_operations.py; additive routes in routers/order_operations.py; new tests/test_order_preparation_recovery.py and test_order_preparation_operations_routes.py. Frontend editable files: new lib/orderPreparationRecovery.js, hooks/useOrderPreparationRecovery.js, components/restaurant/PreparationRecoveryPanel.jsx and focused additive tests; bounded wiring in pages/RestaurantApp.jsx, RestaurantOrderCard.jsx and RestaurantDialogs.jsx if required. Existing common runtime and recovery transport/lifecycle policy stay intact.

## Wire contract

- GET /api/orders/operations/preparation/capabilities: preparation_recovery_enabled boolean.
- PUT /api/orders/operations/preparing/{order_id}: client_operation_id, mandatory expected_order_version and preparation_time.
- PUT /api/orders/operations/ready/{order_id}: client_operation_id and mandatory expected_order_version.
- GET /api/orders/operations/{preparing|ready}/{order_id}/{client_operation_id}: actor-scoped immutable receipt lookup.
- POST same URL + /resume: explicitly bodyless user action.

expected_order_version is either a strict integer in the existing backend revision range or explicit null, which requires that the order has no revision field. Never promote a legacy order or accept a malformed/null persisted revision. Browser input/output versions must be safe integers; values outside the exact JavaScript range fail closed. Backend BSON boundary handling remains unchanged.

The flat receipt contains client_operation_id, state, order_id, order_version, preparation_status, preparation_time, preparation_started_at, preparation_due_at, preparation_ready_at, preparation_estimated_seconds, preparation_actual_seconds, preparation_delay_seconds, error_code, retry_after_seconds. Pending/rejected effect fields are null; pending has HTTP202 and Retry-After2; business rejection has its documented status/code. Applied/replayed has HTTP200 and the original immutable effect, not the order's current state. Timestamps are canonical UTC ISO strings; absent compatible legacy timestamps remain null.

Only a validated ledger entry bound to actor, operation identity, action, target, expected revision and payload can confirm applied/replayed. Different minutes, action, target or revision under an existing identity conflict. A fresh intent finding preparation already started/ready is rejected distinctly; a GET showing the desired phase is not attributed to this intent. Order CAS, embedded history, audit projection and terminal ledger update commit atomically. Assignment and driver reservation remain independent. Short preparation retains the existing free-driver/eligible-assigned-driver rule.

## Frontend rules

Persist the small non-customer intent before admission. Preserve UUID and exact payload across timeout/reload. Cross-tab Web Locks and synchronous single-flight guard protect writes. Actor/role/restaurant/token/lifecycle generation fences prevent old work from publishing or writing after suspension. Pagehide suspends the controller; verified auth reactivation must confirm actor, role, restaurant link and enabled account. Storage failures retain the uncertain state and block new work.

Automatic mount/reconnect/timer work may only make bounded GET reads, never PUT or resume POST. Lookup404 retains the original intent and offers explicit same-intent resend. Pending offers explicit bodyless resume. Terminal rejection permits a new decision only after acknowledgement/authoritative refresh; never invent a new UUID to escape uncertainty. Capability false selects the existing legacy feature before any durable intent; unknown capability blocks admission. No fallback to legacy after durable intent persistence or uncertain admission.

The panel presents in progress, uncertain, confirmed or rejected/conflict, with explicit verify/resend/resume/acknowledge controls. Preparation timers and READY confirmation remain explicit. All 17 surfaces in the preservation inventory remain.

## Acceptance

Pure/schema tests, real synthetic Mongo transaction tests, actual router/auth tests and browser checks must cover same-intent concurrency/replay, lost ACK/reload,5-vs15 conflict, legacy/versioned/BSON boundaries, malformed/corrupted record refusal, same-actor token rotation/actor change/BFCache, driver/assignment and old/new route races, READY/pickup ordering, no partial effects under injected failures, feature-off recovery, no automatic writes and cross-tab/storage failure. Preserve all140 protected files. Existing old test-oracle failures remain named; no new applicable failure can be called green. Review exact final hashes and save reproducible evidence before closing.
