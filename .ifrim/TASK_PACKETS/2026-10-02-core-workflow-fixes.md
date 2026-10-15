# ProDelivery - PD-CORE-CANCELLED-01 / PD-CORE-PREP-DISPATCH-01

Date: 2026-10-02. Scope: engineering_support for Stage 1 baseline closure, not authorization to activate stages 4-10. Catalin authorizes implementation and independent Codex subagents, followed by Stage 2 only after Stage 1 evidence passes.

Goal: terminal orders cannot hide actionable driver work; restaurant preparation can continue after early assignment/acceptance without regressing dispatch state or losing ownership.

Owner: main Codex backend; separate gpt-6.1-sol High frontend implementer. Independent QA author/runner High; independent reviewer Max. No OpenClaw/Claude. Disjoint staging write sets, no concurrent writers to backend order lifecycle. Hub is read-only; local packet/backup is the fallback, no Hub lock claimed.

Backup: staging/originals is created before any edits; original-hashes.json guards publication. Project backup before guarded publish. Preserve previous dirty files, reports and tests.

Boundaries: no live DB writes, topology/index changes, .env/secrets/private/tmp/uploads access, paid providers, commit/push/deploy. No redesign or broad rewrite. Public order status enum and singular assignment stay compatible; small additive preparation field is only source code, not migration of existing data.

Acceptance:
- Driver feed/selection exclude DELIVERED and CANCELLED; history remains available through existing general feed.
- Admin active counts omit terminal orders, without deleting history.
- NEW/PREPARING/READY legacy paths and ASSIGNED/ACCEPTED preparation coexist.
- Preparation mutations preserve assigned driver and public dispatch state.
- Duplicate clicks, stale updates and terminal-state writes do not reset timers or produce duplicate audit events.
- Pickup requires actual readiness; expiry of an estimated timer does not auto-mark ready.
- Strict role/object checks and invalid payload checks remain intact.
- Assigned usable driver is considered for preparation availability without permitting arbitrary short preparation for orphan/disabled assignments.
- Regression tests and API/UI synthetic flow pass; build/lint pass; independent review findings are resolved or explicitly blocked.

Preview: frontend http://127.0.0.1:3000; API http://127.0.0.1:8000/api/. Browser QA uses synthetic/intercepted API or isolated in-memory API, never mutates current Mongo.

Stage gate: existing 18 tests and isolated optimizer 65 tests are not proof of Mongo transactions, phone background GPS or full production readiness. Keep Stage 1 in_progress if required real-environment probes remain unavailable; do not silently start commercial Stage 2.
