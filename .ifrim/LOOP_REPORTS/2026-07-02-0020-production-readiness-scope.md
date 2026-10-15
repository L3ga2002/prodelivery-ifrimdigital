# ProDelivery Production Readiness Scope

Date: 2026-07-02  
Source: Catalin answers to Project Stage Loop questions  
Mode: scope/memory update only, no source-code implementation  

## Decisions

Catalin selected:

1. Next push optimization: **B - Real production launch readiness**
2. Demo-only handling: **C - Convert Admin Settings and live map to real features now**
3. Next user focus: **A - Admin/dispatcher operational reliability**

## Product Direction

ProDelivery is moving from "client-review demo readiness" toward **production launch readiness**, with the first production-ready slice focused on the Admin/dispatcher side of the platform.

This does not mean the whole product is production-ready now. It means the next implementation stage should remove the most important demo/simulation risks from the Admin operational workflow.

## Scope Boundary

In scope now:

- reliable local preview and verification path
- real persisted Admin Settings
- real live map / driver location behavior
- admin/dispatcher operational reliability
- backend validation and logs for the above
- QA over Admin, Restaurant, Driver flows affected by production-readiness changes
- security/release review before any deploy

Out of scope until Catalin separately confirms:

- client ordering app
- product catalog/menu
- Android driver app
- advanced analytics
- full payment flow
- public production deployment changes

## Execution Order

### 0. Stabilize Verification Path

Reason: production-readiness work cannot be trusted if local preview/test commands are unreliable.

Owner: `ifrim-devops`  
Reviewer: `ifrim-devops-reviewer`  
QA: `ifrim-qa`  

Expected work:

- make `dev-start.ps1` validate backend/frontend health
- make `dev-stop.ps1` avoid killing unrelated local processes
- document one reliable backend/frontend smoke path
- confirm `http://127.0.0.1:8000/api/` and `http://127.0.0.1:3000/login`

Acceptance:

- preview starts reliably
- preview stops safely
- backend health check is documented
- frontend route check is documented

### 1. Real Admin Settings

Owner: `ifrim-backend` + `ifrim-frontend`  
Reviewer: `ifrim-backend-reviewer` + `ifrim-frontend-reviewer`  
QA: `ifrim-qa`  

Expected work:

- create real persisted settings model/storage
- add `GET /api/settings`
- add `PATCH /api/settings`
- validate setting ranges and types
- update Admin Settings UI to load/save real values
- remove "demo save" behavior
- add loading, error, success, empty/default states
- add duplicate-save protection
- add useful logs without secrets

Suggested settings for first production slice:

- delivery radius
- order timeout
- schedule rules
- emergency slot rules
- delivery fee defaults
- notification toggles/placeholders

Acceptance:

- settings persist after refresh/restart
- invalid values are rejected with clear errors
- Admin UI cannot double-submit saves
- no demo-only success message remains
- backend/API checks and preview QA pass

### 2. Real Live Map / Driver Location

Owner: `ifrim-backend` + `ifrim-frontend`  
Reviewer: `ifrim-backend-reviewer` + `ifrim-frontend-reviewer` + `ifrim-security-reviewer`  
QA: `ifrim-qa`  

Expected work:

- verify existing driver location endpoint behavior
- add/verify driver-side location update flow
- add browser permission handling where applicable
- store latest driver location with timestamp
- show stale/offline status on admin map
- remove random driver movement from production mode
- keep demo simulation only behind explicit local/demo control if still needed
- ensure role/object authorization on location updates

Acceptance:

- admin map uses real stored driver coordinates
- stale locations are visually distinct
- offline/no-permission state is handled
- simulated movement is not active in production-like mode
- driver cannot update another driver's location unless authorized
- QA verifies admin map + driver status flow

### 3. Admin/Dispatcher Reliability Pass

Owner: `ifrim-product` + `ifrim-frontend` + `ifrim-backend`  
Reviewer: `ifrim-quality-reviewer` + relevant specialist reviewers  
QA: `ifrim-qa`  

Expected work:

- audit admin order creation and assignment flow
- verify driver availability and schedule impact
- verify order status transitions
- verify zones/fees behavior
- verify restaurant/driver lists and operational actions
- add missing loading/error/empty states
- reduce misleading demo/test controls

Acceptance:

- admin can operate main dispatch workflow end to end
- failures show clear messages
- duplicate actions are protected
- related restaurant/driver views still work
- regression QA report exists

### 4. Production Readiness Gate

Owner: Codex coordinator  
Reviewer: `ifrim-security-reviewer`, `ifrim-devops-reviewer`, optional Claude Opus if available and justified  
QA: `ifrim-qa`  

Checks:

- explicit `CORS_ORIGINS`
- no production secrets in repo
- demo credentials not shown in production UI
- public avatar serving decision
- all-role stats/restaurant directory decision
- public registration abuse controls
- build/lint/test/smoke pass
- release/deploy commands documented
- rollback path documented

Acceptance:

- security reviewer has no blocker
- devops reviewer has no release blocker
- QA has verified affected flows
- Catalin approves deploy/push/release actions explicitly

## Next Best Task

Task: **Stabilize local preview and verification path**

Reason: this is prerequisite infrastructure for production-readiness work. Real Admin Settings and live map changes will touch backend, frontend, and role flows; we need reliable preview/health checks before editing those areas.

Owner: `ifrim-devops`  
Reviewer: `ifrim-devops-reviewer`  
QA: `ifrim-qa`  

## Agent Routing For Next Implementation

Implementation:

- `ifrim-devops` for preview scripts
- Codex can implement directly if OpenClaw is unavailable, but must follow regression QA

Review:

- `ifrim-devops-reviewer`
- `ifrim-quality-reviewer` if script behavior changes broadly

QA:

- `ifrim-qa`
- local checks: backend API health, frontend login route, stop/start behavior

Claude:

- not needed for preview script work
- optional Opus 4.8 later for production security/release review if available

## Stop Rules

Stop and ask Catalin before:

- deploying
- pushing to GitHub
- changing production domains/remotes
- deleting existing data
- changing secrets/env files
- replacing large modules
- enabling real public production access

