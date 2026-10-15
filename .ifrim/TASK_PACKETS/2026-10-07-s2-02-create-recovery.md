# S2-02A/B/C - Recoverable order creation, backend increment

Approved by Catalin: 2026-10-07, continuation of expanded plan.
Owner: Codex backend. Reviewer and QA: separate internal Codex agents.
Project: C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery

Scope: additive service and API for durable creation/recovery. Preserve legacy
POST /orders and all current status/assignment/UI behavior. Do not activate
versioned edits, multi-order dispatch or a live migration.

Files: new backend/utils/order_creation.py, backend/routers/order_operations.py,
backend/tests/test_order_creation_recovery.py, backend/server.py (router include).
Any additional existing-source change must be justified and backed up.

Activation is explicitly fail-closed: `order_operation_settings` document
`_id=order-create-v1` must contain `enabled=true`, and Mongo must support
transactions. No marker/index/collection is provisioned at startup. The active
application DB is not changed. Synthetic test DBs may provision that marker.
Changing live topology/settings requires distinct approval.
Cutoff semantics: enabled is checked at admission preflight. Requests which
passed preflight may still admit if the setting changes concurrently; this is
not a strict instantaneous kill switch. Recovery of already admitted operations
continues after disable. A strict linearized cutoff is not promised by this lot.

Protocol:
- POST /orders/operations/create accepts CreateOrderCommand, returns MutationResult.
- GET /orders/operations/create/{client_operation_id} returns authorized receipt.
- Identity (actor, create, client_operation_id) -> deterministic hashed Mongo _id.
- Durable admission retains immutable normalized command/digest, role/restaurant
  ownership binding and server timestamp. Different payload under same identity
  is conflict. Customer payload must never be logged or returned by lookup.
- Each bounded execute/recovery transaction rereads current actor and restaurant,
  protects concurrent disabling/role reassignment/pause via conditional writes,
  creates order, increments existing global counter, inserts critical audit and
  changes operation pending -> applied atomically.
- No scans/initialization in transaction: missing or invalid global counter is
  deployment-not-ready, not guessed. Existing counter seed/migration is separate.
- Creation receipt version 0 is an immutable creation receipt, not a current
  order revision. No active order_version/CAS contract before S2-COMPAT.
- Pending is truthful after uncertain commit. Same POST replays/recovers; GET is
  read-only and does not resume writing. Retries/commit attempts/deadline finite.
- Request body budget is 10 seconds, with driver CSOT. Session cleanup waits
  at most 0.25 seconds per step; an in-flight abort defers end until completion
  rather than using the same session concurrently. In-flight driver work also
  carries CSOT. Incomplete cleanup is logged without payload.
- Current authorization required for replay/lookup; restaurant context changes
  cannot transfer pending intent or reveal an old restaurant's result.
- Existing financial calculation preserved; server detected-zone fee authoritative.
- Preexisting legacy orders do not receive blind new versions/backfills.

Required tests: strict input, actor/tenant, inactive/missing users/restaurants,
pause/close, changed owner/role, durable admission collision, concurrent callers,
different payload conflict, crash before/after business commit, retry bounds,
audit failure atomic rollback, counter integrity, financial legacy semantics,
unsupported topology/absent marker fails without writes, GET no write, no PII
in responses/logging. Real Mongo only isolated loopback fixture, never 27017.

Evidence: pure/unit + real Mongo concurrency + HTTP with clearly stated auth
boundary; protected old tests rerun. Live preview health only if no UI changed;
new endpoint activation-blocked behavior verified without live data mutations.
No commit/push/deploy/env/client DB writes. Save results and exact remaining gates.
Stored operation payload includes customer data needed for immutable recovery;
retention/access policy must be approved before live activation. No TTL/automatic
deletion is added: removing identity while its business effect exists would
permit duplicate recreation. Follow-up/problem creation remains legacy and is
not covered by this new create protocol until its dedicated S2-05 increment.
