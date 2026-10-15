# PD-ORDER-STATUS-RECOVERY - S2-05A

Scope: recoverable custody and pre-pickup cancellation on versioned single-slot
orders. Existing manual assignment/preparation preserved. Not activation, multi
dispatch, incident resolution or financial policy redesign.

## HTTP
- GET /api/orders/operations/status/capabilities: enabled authenticated admin,
  driver or restaurant; read-only {status_recovery_enabled:boolean}, no-store.
- POST /status/{order_id}: existing strict StatusOrderCommand with stable
  client_operation_id, expected_order_version, status and cancellation_reason
  only at cancellation. No tenant, actor, fee, products or arbitrary patch.
- GET /status/{order_id}/{client_operation_id}: actor-bound immutable receipt.
- POST same /resume: bodyless and bounded; only the admitted exact command.
- X-Expected-Actor-ID compares the actual cookie-first authenticated account,
  never supplies authority. Current UI uses it on recovery AND legacy PUT.
- HTTP200 applied/replayed,202pending with Retry-After, typed durable business
  rejection. An uncertain receipt never becomes success, newID or legacy retry.

## Business invariants
- ASSIGNED -> ACCEPTED -> PICKED_UP -> DELIVERED. Pickup requires real READY.
- Pre-pickup cancellation only, with reason. After pickup/delivery requires
  explicit incident resolution, not setting CANCELLED through this protocol.
- Admin may act; driver only its current order; restaurant only own cancel.
- Actual user role/account/resource link rechecked and transaction-fenced.
  Driver identity follows existing drivers.user_id schema; users.driver_id is
  optional, but must be coherent when present. Foreign requests do not admit.
- Missing revision is legacy; malformed/present/max revision is refused,
  never invented from a create receipt. Exact revision n -> n+1 only.
- Order status, timestamps, prep, single representation, driver claim and
  absence of additional active orders must be coherent. Unknown multi fields
  refuse, preserving future minimum10 scope rather than silently corrupting it.
- One transaction commits the order, driver fence/release, delivery counters,
  embedded/global audit and durable outcome. Partial failure rolls all back.
- Delivery credits total_deliveries1 and existing total_amount*0.1 once. Numeric
  counters must be finite, nonnegative and bounded; no pricing policy changes.
- Release touches matching claim only. A paused/offline/disabled account is not
  automatically reactivated. Existing enabled custody can continue despite
  availability state; cancelled disabled claims need an authorized enabled admin.
- Custody timestamps are aware, chronological and nonfuture; no missing pickup
  inferred. Preparation, contact, products, charges, assignment/history retained.
- A replay proves the old operation, not the current order snapshot. Marker
  disable blocks admission, not lookup/resume of admitted operations.
- Three transaction attempts, finite commit attempts, ten-second operation
  deadline and shared serialized worker/abort/end-session cleanup.

## Browser
Isolated axios15s with actual-actor header, no shared mutation interceptor replay.
Actor/role/resource-scoped metadata in localStorage contains opaque identifiers
and receipts only. Cancellation reason is an exact temporary sessionStorage
draft before admission, removed after confirmed admission/terminal or retirement.
Storage/locks/session failure closes new writes. At most3recovery reads,
one exact pre-admission retry and one bodyless resume. No auto newintent.
Terminal requires acknowledgement; explicit fresh snapshot after rejection.
Receipt stays visible even when delivered order disappears from active list.
Refresh failure must not undo a committed receipt; stale reads are fenced.

## Acceptance and gates
Current execution evidence belongs to S2-05 report/QA folder, not this spec.
Default-disabled order-status-v1. No actual DB marker/schema/topology/index/env
changes. Live activation needs the separate migration/exclusion, backup/restore,
reconciliation and retention gates. Client finance decisions not invented.
S2-05B incidents/remakes, S2-06 reads/history, S2-07/08 whole-day acceptance and
native/GPS/OCR/automatic dispatch/store/load remain distinct unverified scope.
