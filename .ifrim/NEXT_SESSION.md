# Next Session

Project: ProDelivery

Start here:

1. Confirm preview status:
   - frontend: `http://127.0.0.1:3000`
   - backend: `http://127.0.0.1:8000/api/`
2. Read `PROJECT_STATE.md`.
3. Read `OPEN_ISSUES.md`.
4. Read `AGENTS.md`.
5. Read `OPENCLAW.md` before asking about or using OpenClaw agents.
6. Read `PREVIEW.md`; for app/UI work, start or verify live preview before editing when practical.
7. Read `ROADMAP.md` for the product roadmap carried over from the original Emergent-started project.
8. Read the latest checkpoint in `CHECKPOINTS/`.
9. If doing review/fixes, read latest reports in `AGENT_REPORTS/`.
10. If doing GitHub work, read `GITHUB.md` first.

Recommended next work:

1. Keep Phase 2 focused on client-review readiness for existing Admin, Restaurant, Driver, schedules, zones, and order flows.
2. Clean backend lint/imports enough to make `flake8` useful as a quality gate.
3. Stabilize backend test command so it works from one documented working directory.
4. Address demo-vs-real risks before client review: mock Admin Settings, simulated live map, demo simulation, and onboarding password exposure.
5. Re-run `ifrim-qa` after fixes.

Recently resolved:

- P0/P1 security/backend issues are fixed in code and locally verified.
- Cookie auth hardening now uses `SameSite=Lax` plus strict origin checks for unsafe methods.
- Login lockout no longer trusts spoofable `X-Forwarded-For`.
- Frontend ESLint is configured and `yarn lint` passes with 0 errors and 0 warnings.
- Security re-review report: `AGENT_REPORTS/2026-06-10-215444-openclaw-security-rereview-after-hardening.md`.

Thread note:

- New Codex threads do not automatically inherit the old conversation about OpenClaw. Read `.ifrim/OPENCLAW.md` to recover the local IfrimDigital OpenClaw agent setup.
- Live preview is expected for visible app changes. If preview cannot run, explain why and record the blocker.
- Before implementation, apply the production rule from `AGENTS.md`: do not build demo-only behavior; build real production features with validations, edge cases, error handling, loading states, duplicate-request protection, useful logs, and no broken existing flows.
