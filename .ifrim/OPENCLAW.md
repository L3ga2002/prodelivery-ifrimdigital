# OpenClaw - IfrimDigital Agent Team

This project can use the global IfrimDigital OpenClaw agent team configured on this machine.

## Important Paths

- OpenClaw config: `C:\Users\mihai\.openclaw\openclaw.json`
- Main OpenClaw workspace prompt: `C:\Users\mihai\.openclaw\workspace\AGENTS.md`
- IfrimDigital agent workspaces: `C:\Users\mihai\.openclaw\workspace-ifrim-team\`
- OpenClaw dashboard/gateway: `http://127.0.0.1:18789/`
- ProDelivery project path: `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`

## Coordinator Rule

Codex is the coordinator and final reviewer. OpenClaw agents are IfrimDigital specialist engineers. Their outputs are evidence and task packets, not automatic user-facing truth.

Use OpenClaw when a task benefits from focused specialist analysis, parallel review, QA verification, or implementation ownership.

## Available Agents

- `ifrim-architect`: architecture, task slicing, risks, acceptance criteria.
- `ifrim-product`: product scope, user flows, copy, business value.
- `ifrim-migration`: imported/exported app inspection, cleanup, local run plans.
- `ifrim-frontend`: React, Tailwind, routing, UI behavior, browser errors, frontend builds.
- `ifrim-backend`: FastAPI, MongoDB, auth, schemas, API routes, CORS, server issues.
- `ifrim-qa`: tests, smoke checks, API/browser verification, regression checks.
- `ifrim-design`: UX, responsive layout, visual hierarchy, interaction quality.
- `ifrim-integrations`: Stripe, Supabase, OAuth, email, AI APIs, webhooks, analytics.
- `ifrim-devops`: local preview, scripts, Docker, env templates, CI, deploy readiness.
- `ifrim-mobile`: Expo/React Native and mobile deployment readiness.
- `ifrim-prototype`: quick feasibility spikes and throwaway prototypes.
- `ifrim-reviewer`: lead code reviewer and synthesizer.
- `ifrim-backend-reviewer`: Python, FastAPI, MongoDB, async code, API contracts, backend tests.
- `ifrim-frontend-reviewer`: React, state, routing, API calls, responsive UI, accessibility.
- `ifrim-security-reviewer`: auth, cookies, secrets, CORS, validation, data exposure.
- `ifrim-devops-reviewer`: preview, env, scripts, deployment readiness, CI, logs, rollback.
- `ifrim-quality-reviewer`: static quality scorecard, undefined variables, hooks deps, complexity, long files/functions, dead code, lint/build risk.

## Review Flow

1. Codex defines scope and asks `ifrim-reviewer` for review planning or synthesis.
2. Specialist reviewers inspect their area and report only.
3. Each finding must include:
   - severity
   - file/line
   - evidence
   - impact
   - suggested owner/fixer
   - concrete fix recipe
   - verification command
4. Codex assigns fixes to implementation agents.
5. `ifrim-qa` verifies after fixes.

## Implementation Flow

Use implementation agents only for clearly assigned fixes:

- backend fixes -> `ifrim-backend`
- frontend fixes -> `ifrim-frontend`
- scripts/deploy/env -> `ifrim-devops`
- UX/layout polish -> `ifrim-design`
- external services -> `ifrim-integrations`

Review agents do not edit files.

## Example Invocation

From a shell in the ProDelivery project:

```powershell
openclaw agent --agent ifrim-security-reviewer --cwd "C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery" "Review the current P0 security issues. Do not edit files. Report findings with severity, file/line, evidence, impact, fix recipe, and verification command."
```

If OpenClaw CLI syntax changes, run:

```powershell
openclaw --help
openclaw agent --help
```

## Current ProDelivery Priorities

Security P0:

1. Public `/api/seed` endpoint must be gated or disabled outside local/dev.
2. Public registration must not allow arbitrary privileged roles.
3. Orders endpoints need role and tenant/object authorization.

Security P1/P2:

- Driver PII must be admin-or-self scoped.
- Driver schedules must be admin-or-self scoped.
- Cookie auth needs CSRF/same-site/origin hardening.
- Login lockout must not trust spoofable `X-Forwarded-For`.
