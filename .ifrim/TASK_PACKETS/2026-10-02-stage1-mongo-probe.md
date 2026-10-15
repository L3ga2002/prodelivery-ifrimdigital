# PD-STAGE1-MONGO-01

User approval: 2026-10-02, "ok aprob tot, apuca te si termina", after the ten-stage plan and explicit separate Mongo probe proposal.

Scope: Stage 1 real Mongo concurrency/crash-recovery feasibility probe, isolated from application and client data. Android/iOS capability preflight in parallel. Stage 2 starts only after ALL Stage 1 gates pass; unavailable physical phones are not a pass.

Owner: main Codex owns runtime isolation and integration; internal Codex implementation agent owns probe protocol only; independent reviewer/QA owns adversarial verification. No OpenClaw/Claude, commit, push, deploy, paid provider, env/secret access or application DB mutation.

Isolation: new loopback-only Mongo process at port 27941, replica set pd_stage1_probe; dedicated fresh dbpath in this staging folder. Database names must start pd_probe_. Refuse other topology/host/port. No use of port 27017. Synthetic IDs only, no PII. Never delete an existing database. Retain evidence; stop only owned test processes by verified identity after QA.

Deliverable: runnable isolated transaction protocol and independent tests for capacity, same-order races, duplicate requests, CAS conflicts, cancellation/finalization preserving other assignments, durable operation replay, process crash before/after commit, fencing, pending recovery and bounded retries. Not an application feature or full Stage 7 completion.

Mobile sidecar: read-only tools/device/native scaffold inventory, no installs, account access, live GPS collection or fake physical results. Prepare exact test protocol for unavailable equipment.

Acceptance: explicit passing/failing/not-tested matrix; reviewer findings resolved or gate kept open; hashes and rerunnable commands; no source/client-data changes implied by test results. Main coordinates decisions and publishes only scoped new evidence plus additive memory updates after review.

Affected roles: synthetic admin/worker/restaurant/driver. Affected application surfaces: none modified; current orders/stats handler functions independently exercised against isolated Motor DB. Preview login3000/API8000 read-only health; existing login UI inspected, no real login or client-order changes.

Actual internal assignment: protocol implementation Nietzsche (gpt-6.1-sol High), independent review/QA Franklin (gpt-6.1-sol Max), mobile inventory Schrodinger (gpt-6.1-sol High). Main owns runtime/process harness and publication. Source writes disjoint; no Hub lock claimed. Backup/hash guards required for the three additive project memory updates; runtime storage never copied into application data.

Outcome: see mongo-report.md / project LOOP_REPORTS/2026-10-02-mongo-concurrency-probe.md. Mongo prototype subset verified, Stage1 remains in_progress; Stage2 not started. Physical Android/iOS/native build path remains unresolved. Approval for internal probe work already received, do not re-ask whole plan.
