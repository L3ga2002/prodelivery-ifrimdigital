# Open Issues

## Resolved P0/P1 Security And Backend

Status 2026-06-10: resolved in code and verified locally.

- Public seed/reset endpoint is gated by auth, admin role, and `ALLOW_SEED=true`.
- Public registration is restricted to driver accounts and ignores restaurant injection.
- Order read endpoints enforce role and object-level authorization.
- Order mutation endpoints enforce role and tenant/object authorization.
- Driver profile data is restricted to admin-or-self.
- Driver schedule reads are restricted to admin-or-self.

Verification:

- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_security_authorization.py -q` -> 10 passed.
- `.\.venv\Scripts\python.exe backend_test.py` -> 8/8 passed.
- `AGENT_REPORTS/2026-06-10-205630-claude-fable-principal.md`
- `AGENT_REPORTS/2026-06-10-215444-openclaw-security-rereview-after-hardening.md`

Sources:

- `AGENT_REPORTS/2026-06-08-code-review.md`
- `AGENT_REPORTS/2026-06-09-232915-claude-fable-principal.md`

## P2 Security Hardening

- Status 2026-06-10: cookie-authenticated mutating endpoints now use `SameSite=Lax` cookies plus strict origin enforcement for unsafe methods.
- Status 2026-06-10: login lockout no longer trusts spoofable `X-Forwarded-For`; it uses server-visible client IP plus an email-level bucket.
- Deployment must verify `CORS_ORIGINS` uses explicit trusted origins, not wildcard behavior with credentials.
- Decide whether public driver avatar image serving is intended.
- Decide whether all-role access to global `/stats` and restaurant directory data is intended.
- Add rate limiting or verification policy for public driver registration to reduce spam accounts.

Sources:

- `AGENT_REPORTS/2026-06-09-232915-claude-fable-principal.md`
- `AGENT_REPORTS/2026-06-10-215444-openclaw-security-rereview-after-hardening.md`

## Code Quality

- Frontend components are too large and complex:
  - `frontend/src/pages/AdminDashboard.jsx`
  - `frontend/src/components/AdminScheduleView.jsx`
  - `frontend/src/pages/RestaurantApp.jsx`
  - `frontend/src/pages/DriverApp.jsx`
- Status 2026-06-10: Frontend ESLint 9 is configured as a project-native command via `frontend/eslint.config.mjs` and `yarn lint`.
- `yarn lint` currently passes with 0 errors and 42 warnings, mainly unused imports/variables in large components.
- Backend tests are fragile depending on working directory and server availability.
- Backend `flake8` currently fails on unused imports/style noise.
- Frontend has nested ternaries that should be extracted into helpers/config maps.
- Frontend has no detected test suite in `src`.

Source: `AGENT_REPORTS/2026-06-08-quality-review.md`

## Phase 2 Client-Review Readiness

- Keep Phase 2 focused on stabilizing the current Admin, Restaurant, Driver, schedules, zones, and order flows.
- Do not start future phases such as real live GPS, client ordering app, product catalog, Android app, or advanced analytics until client scope/payment confirms them.
- Before client demo, mark or hide demo-only functionality that can be mistaken for real operations:
  - Admin Settings is still mock/demo.
  - Admin live map is demo/simulated, not real GPS.
  - Demo simulation can pollute real orders if available outside local/demo mode.
  - Generated passwords for driver/restaurant onboarding should not be exposed in production-like UI flows.

## DevOps / Local Workflow

- `dev-stop.ps1` stops processes by ports and can kill unrelated local processes.
- `dev-start.ps1` should validate health after start and report occupied ports more safely.
- Dependency refresh should be repeatable after requirements or lockfile changes.

## Production Readiness

- Demo credentials must not ship to production UI/config.
- Demo credentials currently appear in local/testing surfaces that need a policy before public git/deploy:
  - `README.md`
  - `backend_test.py`
  - `frontend/src/pages/LoginPage.jsx`
  - `memory/test_credentials.md` (kept ignored/local)
- Status 2026-06-08: hardcoded demo passwords were removed from versionable source/docs/tests; local env still contains demo values and remains ignored.
- Status 2026-06-09: `git ls-files` check found no tracked `.env`, uploads, token/credential files, or `memory/test_credentials.md`.
- Local env values must be replaced with production secrets in deployment.
- Final security reviewer sign-off is required before production.
