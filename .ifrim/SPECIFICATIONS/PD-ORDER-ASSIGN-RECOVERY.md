# PD-ORDER-ASSIGN-RECOVERY - S2-04

Scope: manual single-slot assignment/reassignment. Automatic dispatch and
minimum ten simultaneous jobs remain later commercial scope, not this protocol.
Source integrated only; marker is default-disabled and no live activation occurs.

## HTTP contract

- GET `/api/orders/operations/assign/capabilities`: current enabled admin,
  topology and `order-assign-v1` availability; read-only, no-store.
- POST `/api/orders/operations/assign/{order_id}`: strict AssignOrderCommand,
  client_operation_id, expected_order_version and driver_id.
- GET `/api/orders/operations/assign/{order_id}/{client_operation_id}`:
  authenticated actor-scoped recovery, no new operation admission.
- POST same operation `/resume`: bodyless, bounded request-body/read/transaction
  deadlines; uses exactly the stored admitted command.
- Optional `X-Expected-Actor-ID` is compared with the REAL authenticated user
  before business DB access. It is not an authorization credential. Current
  assignment UI always supplies it, including the existing legacy PUT.
- HTTP200 applied/replayed; HTTP202 pending plus Retry-After; durable business
  refusals use typed rejection receipts. No-store, no hidden optimistic success.

## Atomic invariants

- CAS business revision n -> n+1. Missing revision stays legacy; malformed
  present revisions are refused. The create receipt revision is not reused.
- Validate stored order, preparation, singular representation, linked enabled
  driver users, current claims, other active orders and orphan assignments.
- Only NEW/PREPARING/READY or consistent pre-accept ASSIGNED is eligible.
  Accepted/picked-up/delivered/cancelled or residual custody is refused.
- One transaction commits new claim, matching old release, order revision,
  embedded/global audit and durable receipt. Failure rolls all effects back.
- Preserve preparation state/timer, products, contact and financial values.
- Old delivery driver returns active only when still enabled/inactive-break-free
  and linked to the correct user. Valid retained break metadata is not a new
  break after an explicit active action; malformed timestamps remain refused.
- Ledger identity binds actor/action/order/driver/revision. A changed payload,
  foreign actor, malformed ledger or receipt cannot be guessed or overwritten.
- Finite retries/deadline and the reviewed shared runtime serialize worker,
  abort and end-session cleanup. Pending is not reported as success/failure.

## Browser behavior

- Isolated axios transport avoids shared auth mutation replay. 15s timeout.
- Persist only opaque intent identifiers, expected revision and receipt in
  actor-scoped localStorage; no name/phone/address/items/GPS draft.
- Web Locks plus in-tab guards prevent duplicate admission across tabs. If
  durable storage/locking is unavailable, versioned actions fail closed.
- Lost ACK/reload/lookup error retains the SAME intent. Bounded recovery reads,
  at most one exact pre-admission resend and one bodyless resume; no legacy
  fallback or new ID while uncertain.
- Actual actor change becomes SESSION_CHANGED and preserves original intent.
- After durable rejection, explicit fresh snapshot permits a new intent.
  Applied/replayed receipt must be acknowledged; stale selection stays frozen.
- Shared current dashboard refresh remains unchanged; a failed read does not
  invalidate a confirmed durable receipt.

## Adjacent compatibility safety

- Legacy status writer no longer copies current_order_id from its stale read;
  snapshot CAS returns DRIVER_STATE_CONFLICT on concurrent claim/release.
- Legacy disable writer pins current claim/availability/user link after count.
  User-write failure returns DRIVER_DISABLE_INCOMPLETE while driver remains
  blocked; retry can reconcile. This legacy two-document flow is not atomic.
- Legacy assignment keeps existing route/receipt behavior, but refuses known
  multi-representation and malformed availability metadata; claim CAS pins
  active status. It is not advertised as transactional recoverable S2-04.

## Live gate and remaining scope

Default-disabled marker, transaction-capable topology, migration/exclusion,
backup/restore, reconciliation and ledger/intent retention need separate evidence
and Catalin approval. No online backfill or activation is implied by tests.
S2-05 custody/cancel/problem remains unconverted for versioned orders. S2-06
pagination/detail/history and S2-07/08 full audit/regression remain open.
Auth owner regression is real ASGI/cookie-first auth with synthetic JWT module
configuration, not a field-device login/load/store/GPS/PWA-cache certification.
