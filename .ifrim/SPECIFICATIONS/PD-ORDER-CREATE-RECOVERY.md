# Recoverable create - integration boundary

Implementation increment S2-02A/B/C. Legacy POST /api/orders remains unchanged.
New endpoints are additive, authenticated and no-store:

- POST /api/orders/operations/create: strict CreateOrderCommand.
- GET /api/orders/operations/create/{client_operation_id}: read-only receipt.

201 applied / 200 replayed include order_id and immutable creation receipt
order_version=0. This does not publish current business order revision. Read
the ordinary authorized order endpoint for its current state.

202 pending includes Retry-After and retry_after_seconds. Client must retain
the same ID and exact semantic intent. A lost response is not permission to
generate another ID. GET 404 does not prove a previously submitted POST failed:
an admission may still be in flight; resume the same POST, not a new intent.

409 rejected/conflict and other errors are explicit. Persisted rejection is
stable for its intent; reopening a paused restaurant does not change a rejected
receipt. A changed operation identity requires an intentional new action after
the previous outcome is known. 503 means unavailable/unprepared; preserve the
intent. No silent fallback to legacy for a recoverable operation.

Operation identity is actor/create/client_operation_id. Server authenticates
and rereads actor; the immutable digest binds all create fields. Retrying with
different fields conflicts. Persisted command, actor, restaurant and digest
are revalidated together before recovery; malformed state fails closed.

Admitted command/customer data remains server-side in order_operations for
recovery, not in receipt/logs. No TTL or automatic deletion: identity retention
must be designed alongside customer-data retention before activation, otherwise
the same intent could be recreated. No new browser storage introduced here.

Admission uses majority write and hashed deterministic _id. Business order,
global counter increment, critical audit and operation outcome commit together
in a Mongo transaction. Conditional real actor/restaurant writes serialize with
changes to those same authoritative documents. Topology support is mandatory.

Activation: absent/disabled order_operation_settings _id=order-create-v1 blocks
new admission without writes. Marker provision, initialized/reconciled counter,
backup/restore and any topology/index/migration changes need explicit live
approval. Nothing is provisioned at app import/startup. Existing pending intents
continue recovery after disabling admission; committed lookup/replay remains.
Cutoff applies to preflight, not a strict instantaneous kill switch for calls
which already passed it. This behavior is deliberate and must be documented
when activation is approved.

Request work budget10s, max3 body attempts, max3 commit attempts. Actual response
may include bounded cleanup wait. Unknown commit outcome never means rejection;
recovery rereads durable outcome on the same identity. Cleanup must be serialized
behind any still-running driver call and never share a session concurrently.
Driver-side CSOT, observers and independent cancellation regressions are required.

Frontend S2-02D is not implemented in this increment. Restaurant/driver workflows,
all legacy writers and problem-followup creation are unchanged. No v2 editing,
global CAS revision or multi-order dispatch is activated. S2-COMPAT and S2-05
remain distinct dependencies, not claimed by transactional CREATE.

Motor CSOT compatibility checked against official documentation:
https://motor.readthedocs.io/en/stable/examples/timeouts.html
Current library migration to PyMongo Async is future maintenance, not an
unreviewed dependency rewrite inside this narrow increment.
