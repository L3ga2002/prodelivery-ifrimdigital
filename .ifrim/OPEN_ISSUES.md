# Open Issues

## P0/P1 Security And Backend

- Public seed/reset endpoint needs auth/admin/dev-only gating.
- Registration must not allow arbitrary privileged roles.
- Order read endpoints need role and object-level authorization.
- Order mutation endpoints need role and tenant checks.
- Driver profile data exposure needs admin-or-self restriction.

Source: `AGENT_REPORTS/2026-06-08-code-review.md`

## Code Quality

- Frontend components are too large and complex:
  - `frontend/src/pages/AdminDashboard.jsx`
  - `frontend/src/components/AdminScheduleView.jsx`
  - `frontend/src/pages/RestaurantApp.jsx`
  - `frontend/src/pages/DriverApp.jsx`
- Frontend ESLint 9 is installed but not configured as a project-native command.
- Backend tests are fragile depending on working directory and server availability.
- Backend `flake8` currently fails on unused imports/style noise.
- Frontend has nested ternaries that should be extracted into helpers/config maps.
- Frontend has no detected test suite in `src`.

Source: `AGENT_REPORTS/2026-06-08-quality-review.md`

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
- Local env values must be replaced with production secrets in deployment.
- Final security reviewer sign-off is required before production.
