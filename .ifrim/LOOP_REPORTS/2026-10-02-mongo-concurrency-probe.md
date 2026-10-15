# ProDelivery - Stage 1 isolated real-Mongo probe

Date: 2026-10-02. Classification: Stage 1 engineering feasibility, not Stage 2, application activation or production release.

## Authority and outcome

Catalin explicitly approved the preceding plan, including a completely separate synthetic Mongo environment: "ok aprob tot, apuca te si termina". The earlier Mongo-approval blocker is resolved. No conversion/access of application Mongo27017, live/client data mutation, secrets/env changes, paid service, commit/push/deploy is included.

The isolated transactional reservation/recovery subset is implemented and tested. The current application remains singular (`current_order_id`); these scripts do not register application routes, replace persistence, activate automatic dispatch or migrate data. Stage 1 remains `in_progress`; physical mobile gates are unverified, so Stage 2 was not started.

## Implementation and ownership

- Main Codex: owned Mongo runtime, current-router real Mongo checks, actual separate-process/crash tests, integration and handoff.
- Internal Codex implementer Nietzsche (`gpt-6.1-sol`, High): protocol.py, pure control-flow tests and contract.
- Independent Codex reviewer/QA Franklin (`gpt-6.1-sol`, Max): adversarial suite, durable-state oracles, runtime review and regression closure.
- Internal Codex mobile preflight Schrodinger (`gpt-6.1-sol`, High): allowed-source/tool/device inventory and physical test matrix. Not physical QA.
- No OpenClaw/Claude or Hub modification. No independent review is claimed for work performed solely by main.

## What the probe does

Durable scoped operation identity, semantic payload/version digest, pending/claimed/committed/rejected outcomes, leases with monotonic fencing, transactionally coupled order/assignment/driver guard/audit/outbox writes and bounded retry/reconciliation. Reserve, accept, expire, pickup, deliver, cancel, reassign, policy and preparation have fixture contracts. Closing one of ten assignments preserves the other nine; manual-like and internal-worker actions follow common guards.

The fixture is MongoDB 8.0.4, single-member replica set `pd_stage1_probe`, only `127.0.0.1:27941`, a fresh dedicated dbpath and database names `pd_probe_*`. It uses the already installed binary. No new packages or system service/autostart/config changes. Runtime ownership checks bind the exact PID, dbpath, port, bind address and replica set before shutdown. Data directories are retained; no database/collection is dropped.

Runtime staging: `C:\Users\mihai\.codex\visualizations\2026\06\09\019eae21-cb0d-7bf0-b6a5-ab4d21ab781f\prodelivery-stage1-mongo-20261002`. Only portable scripts/reports, not Mongo storage/logs or the active runtime manifest, are published to project evidence.

## Verification actually run in this turn

| Suite | Result | Scope and evidence |
| --- | --- | --- |
| Existing backend baseline | 672 passed, 0 failed | Current real source, original protected suites retained; unit/in-memory, one existing Starlette/httpx deprecation; baseline-current.xml |
| Existing frontend helpers | 74 passed, 0 failed | Current real orderWorkflow source; frontend-current.json; not full browser/mobile |
| Current application routes on real Mongo | 16 passed, 0 failed | Current create/prepare/ready/assign/deliver/feed/stats/ownership handlers; real Motor DB, synthetic identities; existing-routes-first.xml |
| Protocol unit + actual process suite, final | 38 passed, plus 28 unittest subtests; 0 failed | 29 pure/control-flow methods + 9 process/real persistence cases; protocol-process-final.xml; 127.16s pytest duration, not SLA |
| Independent QA, stable final | 97 passed, 0 failed/errors/skips | 72 real-Mongo integration cases and 25 pure/runtime negative cases; qa-results.json and qa-review.md |

Counts refer to separate suites, not 897 end-to-end scenarios. The 28 subtests are not added as independent test methods. No original tests were deleted or validations loosened.

Main process suite: two process crashes (before/after commit), persisted admission reopened through a new client, lost commit ACK injection once/repeatedly after a real commit, same-order/two-driver and last-slot races with both shared and distinct admin/worker actors. A barrier coordinates processes after separate claims. Independent thread/session races additionally prove overlapping pre-business snapshots with different actor documents, so same-actor auth serialization does not mask the guard behavior.

Crash recovery measurement on final run: **69.897 seconds**, **12 pending responses**, after the deliberately killed pre-commit process. Mongo's default transaction lifetime cleanup can retain an abandoned transaction lock; the per-request budget and eventual supervisor recovery are distinct. Every recovery call was bounded under the test's 12s ceiling and eventual recovery under 120s. This is not instant recovery, an SLA or a failover benchmark. No test-server transaction lifetime was shortened to hide the delay.

Unknown commit injection is at the PyMongo acknowledgement boundary AFTER a real commit; it is not a wire-level network partition. The same operation/ref and same live-session commit are retried without rerunning business effects. A conservative pending response can reconcile to committed on disk.

Real reassign closes the previous partial-unique open assignment and inserts its replacement in the same Mongo transaction; independent QA checks one remaining open owner, nine other assignments/stops unchanged and no replay side effects. No index was weakened.

## Problems found and repaired in the new probe

1. Runtime initially expected `replSetName`, but Mongo8 CLI output uses `replSet`; exact supported names are now handled. The failed startup's exact child was terminated and its synthetic directory retained.
2. Process crash exposed raw NetworkTimeout during lease reclaim while the old transaction retained a lock. Claim/recovery now returns bounded pending/reconcile, preserves identity and never writes a false terminal rejection. Recovery includes claim and execution in one request budget.
3. Runtime manifest persistence failure could leak its newly spawned child. Independent negative test caught this; manifest persistence is now within exact-child cleanup protection.
4. Conflicting replica option keys were silently accepted. Independent negative test caught this; every present supported key must exactly match the approved set.

First process run: 4 passed / 3 failed. One was the real recovery timeout; two were harness process-start/barrier timeout failures. Startup/claim/business checkpoints are now distinguished and inter-process message ordering is handled explicitly, without increasing the protocol's business deadline. Second run: 7/7 passed; two distinct-actor cases were added and passed; final frozen run retained all nine cases.

First independent QA: 95 passed / 2 failed, both runtime findings above; its protocol hash changed during execution, so that run is preliminary. It is retained as qa-results-first.json. Final QA reran all 97 unchanged assertions on stable implementation/runtime hashes and closed both findings. See qa-review.md for exact qualifications.

## Source integrity, preview and limits

All nine backend/frontend files from the previous core-fix publication still match their recorded SHA256 hashes. This turn changes only additive project memory and new evidence artifacts, not app source, UI, dependencies, authentication, deploy settings or protected tests.

Frontend `http://127.0.0.1:3000/login` and API `http://127.0.0.1:8000/api/` returned HTTP200. The existing in-app login tab was inspected and shows the login form and role demo buttons. No real login, client-order mutation or fresh authenticated browser end-to-end claim is made. Earlier browser evidence remains historical. Build/lint were not rerun because production sources/dependencies are unchanged; current unit and real-Mongo checks are reported above.

Not demonstrated: entire M3 specification, Mongo failover/multi-node durability/server crash, production migration/backfill, native/mobile/GPS freshness, routing matrix/solver coupling, physical vehicle load/windows, incident resolution, remote notification delivery, money/reconciliation, 50/100 load benchmark or production readiness. Route publication and GPS eligibility are explicit synthetic fixtures. Single actor auth_fence is conservative and serializes that actor's operations; it is not a scalable production authorization design. No dedicated refuse API or worker service is claimed.

## Remaining Stage 1 dependency

Mobile preflight found React/PWA source, no native scaffold or frontend GPS collection. Android Studio/JBR is present, but SDK/ADB was not found in inspected standard locations. Zero matching present USB/PnP interfaces were detected; the user's actual available phones remain unknown. iOS build/provisioning path is not available here. `mobile-preflight.md` distinguishes observed absence from unknown inventory; `mobile-test-matrix.md` contains 16 NOT_RUN physical scenarios with proposed thresholds, not client SLA.

User was asked asynchronously which Android/iPhone and Mac/signed-build access are available. Internal preparation of a small native feasibility probe is already approved; do not ask to reapprove the whole plan. Physical consent/pairing, external accounts and any paid services remain separate. Do not turn a browser/emulator or this Mongo subset into physical PASS. Full application implementation remains Stage5/6, not hidden in Stage1.

Next task: prepare the bounded native probe for the actual available device/build path, run foreground/background/lockscreen/offline/recovery checks, review results, then close Stage1 only with all required evidence. Restaurant API documentation remains deliberately deferred; it does not block this probe.

## References

Mongo transaction semantics were checked against primary docs: [PyMongo transactions](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/) and [Mongo test replica sets](https://www.mongodb.com/docs/manual/tutorial/deploy-replica-set-for-testing/). Public documentation is not a substitute for the local test results above.
