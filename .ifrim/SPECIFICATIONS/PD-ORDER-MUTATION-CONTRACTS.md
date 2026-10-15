# S2-01 contracts and integration boundaries

These additive models are not enabled in the production routers. Existing Order,
OrderCreate and existing request/response shapes remain unchanged.

## Commands

All commands require client_operation_id (16-128 ASCII letters/digits/_/-).
Edits, assignment, preparation, readiness and status commands additionally require
expected_order_version (strict integer, 0..2^63-1). The verified authenticated actor
is supplied server-side, never in the request model. Extra fields are rejected.

Create accepts `order` using the current business fields, strict numeric types,
finite values, strict nested items, trimmed text bounds and paired coordinates.
Money semantics are intentionally unchanged: the existing server uses subtotal
when supplied, otherwise total as the subtotal fallback, then computes the actual
fee and total. This schema does not independently quote a fare or reinterpret total.

Corrections are deliberately restricted to customer_name, customer_phone,
customer_address, customer_latitude, customer_longitude and notes. Required contact
fields cannot be cleared. Both coordinate keys must be sent together, including
when clearing coordinates with two nulls. Notes may explicitly be cleared.
Unspecified fields must not be materialized as nulls in a patch.
Money/items/payment edits need their own business rules and are not silently
included. Server-side before-pickup/custody rules remain mandatory in S2-03.

Assignment contains driver_id; preparation contains preparation_time (1..240);
readiness has no editable business fields. Generic execution status accepts only
ACCEPTED/PICKED_UP/DELIVERED/CANCELLED. It does not authorize these transitions.
Cancellation requires a nonblank reason; another status cannot carry that reason.

## Identity and replay

Immutable admission identity is `(authenticated actor, operation type, client id)`.
Target order, semantic payload and expected version are included in the SHA-256
fingerprint. Reusing an identity for another target/version/payload conflicts.
Explicit default values normalize consistently for create commands; correction
omission remains distinct from explicit clearing. Normalized intent hashing is
neither a durable ledger nor an authorization check.

## Receipts

`applied`/`replayed` require an order id and version and cannot carry error/retry.
`pending` requires retry_after_seconds (1..60), without a committed order result.
`rejected` requires a bounded error code, without order/retry fields.
A replay receipt refers to the committed operation, not necessarily the current
order state. Consumers must refresh/reconcile the latest order by revision.

## Financial contract boundary — client rules received 12 October 2026

The existing command/receipt schemas describe implemented behavior at their documented versions. They are not authority for a 10% driver remuneration policy or for collecting restaurant transport charges from the recipient. The confirmed rules and open decisions are in `LOOP_REPORTS/2026-10-12-client-operational-rules-third-set.md`, read together with the 8/9 October reports and their explicit supersession rules.

The next financial increment must represent separately: product amount, recipient amount still to collect, restaurant transport charge, driver remuneration, driver advance to restaurant, outstanding amount and actual reimbursement/payment. Approval of insufficient cash is not payment; an obligation to reimburse is not reimbursement; a decision to return is not receipt of products. Explicit zero differs from missing/unknown. Prepaid products are not collected again from the recipient.

Tariff configuration is restaurant-specific and versioned; transport and driver remuneration remain separate. Each admitted operation captures the applicable rule snapshot and currency/rounding semantics. New settings do not recalculate historical operations. Unknown tariffs or exception rules block the dependent new calculation; they do not fall back to zero, 10%, or the unnamed 16/26/36 example. Kilometer floor rounding is confirmed; monetary rounding is not established by that answer.

The new financial schema/version must cover models, validation, API serialization, persistence and UI. Adding ignored fields to documents is insufficient. Existing pending operation identity, expected revisions, semantic digest and lookup/replay remain unchanged; no readmission through a second protocol and no silent historical conversion. Activation remains default-disabled until the concrete schema, compatibility, policy and data gates are verified. Synthetic test prices/policies are explicitly labeled and cannot activate live tariffs.

Insufficient-cash payment timing, exception payers/rate bases, second-address supplement semantics and the A/B/C break boundary remain open. Only independent contracts, fixtures and functionality advance until the relevant answer is received. Close-day and factual incident recovery already have local closure evidence; preserve them and extend only demonstrated gaps.

## Before any activation

S2-02 must persist admission/result, bind audit to the business effect, use the
chosen crash-safe protocol, and recheck actor/tenant/restaurant eligibility.
S2-COMPAT must inventory every legacy writer and use the same revision/CAS or
explicitly refuse v2 documents before any versioned edit is enabled.
Migration/index/topology and restore gates still require separate approval for
live data. Do not create indexes at import/startup or copy a synthetic protocol
into live routes without adaptation and integration review.

S2-01 is a contract checkpoint only: no claim of active duplicate protection,
ten-order dispatch, native GPS, physical devices or production readiness.
