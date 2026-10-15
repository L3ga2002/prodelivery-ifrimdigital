# ProDelivery - S2-04 and Stage 2 closure plan

Authority: Catalin approved planning and execution on 2026-10-07.
Project root: C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery
Commercial Stage 2: in_progress. No Stage 3+ implementation or live activation.

## Closure sequence

1. S2-04 manual assign/reassign: atomic order + driver claim/release + operation
   outcome + audit. Stable identity, CAS, finite recovery, fresh availability.
2. S2-05 custody transitions/cancel/problem follow-up: preserve financial policy,
   release only affected resources, no terminal reset or silent custody transfer.
3. S2-06 authorized complete paginated lists/detail/history, stale-read fencing.
4. S2-07 audit/diagnostics throughout, no customer values in unnecessary logs.
5. S2-08 full regression: create, prepare, assign, accept, ready, pickup, delivery,
   reassign, cancel, incident, foreign roles, duplicates, offline/reload/lost ACK.
6. Separate live gate: migration exclusion, backup/restore, retention, financial
   policy and marker/index/topology approval. Do not claim activation from tests.

## Current implementation packet: S2-04

Backend owner: internal Codex worker, exclusively order_assignment.py and
order_operations.py in staging. Frontend owner: internal Codex worker, exclusively
new assignment controller/hook and AdminDashboard.jsx in staging.
Reviewer: separate internal Codex agent. QA/test owner: coordinator plus independent
test/reviewer agents. No OpenClaw/Claude or Agent Hub mutation.
Advisory locks: order operations router/backend; admin assignment/frontend.

## Contract

POST /api/orders/operations/assign/{order_id}, AssignOrderCommand (existing).
GET /api/orders/operations/assign/capabilities -> assign_recovery_enabled: bool.
GET /assign/{order_id}/{client_operation_id}; POST same path + /resume (bodyless).
MutationResult and statuses follow editing/create protocol. Distinct default-deny
marker order-assign-v1. Missing business revision is not zero or promoted.
Pending admitted operations can recover after disable; no fallback to legacy.
Only current enabled admin, role rechecked and actor fenced inside transaction.

Eligible NEW/PREPARING/READY unassigned and ASSIGNED pre-accept reassignments.
ACCEPTED/PICKED_UP/terminal refuse; no silent custody transfer. Preserve preparation
state/timer. Single-slot compatibility in current runtime; never advertise this
as the future minimum10/multi-order/automatic allocator. Reject unknown multi
assignment data rather than clearing it; old claim release targets only this order.
Driver current state revalidated at transaction commit; enabled, active, not pause/
offline, no other current order or orphan conflicting order. No force override.
Order/driver/snapshot integrity and malformed metadata fail closed.

Atomic CAS order update, new claim, old claim release, immutable result + audit.
Exact same actor/type/client ID/target/revision/driver is the same intent. Reusing
identity for other data is conflict. Stored tenant/envelope integrity revalidated.
Finite request/transaction/retry/cleanup deadlines using existing reviewed runtime.
Logs contain operation reference/request ID and diagnostic codes, not customer PII.

Frontend keeps current layout/legacy single flow. Versioned order uses recoverable
protocol only; legacy remains existing route. A pending recoverable identity never
falls back. Synchronous mutex + shared Web Locks, persist opaque identity/driver
only, bounded lookup/resume, explicit acknowledgement before new intent, error/
conflict/loading/offline/refresh outcomes, stale session fences. No customer draft.

Acceptance: two admins/order; two orders/last slot; same-ID concurrent retry;
different intent; missing/null/bool/overflow revision; stale version; preparation
race; old driver inconsistent; paused/disabled/offline target; audit failure;
transaction/lost ACK recovery; actor switch/disable; bodyless resume; mobile and
adjacent creation/correction/restaurant workflows. Real Mongo only isolated owned
loopback fixture27941, synthetic databases. No env/secrets/private/uploads/live DB.

Scoped source backup + hashes before integration; preserve unrelated dirty work.
Tests and originals protected; never relax tests to obtain PASS. Reviewer reports
severity/evidence/impact/owner/fix/verification. No commit/push/deploy.
