# Quality Review Report - 2026-06-08

Source: `ifrim-quality-reviewer`

## Scorecard

- Code Quality Score: 63/100
- Backend: 68/100
- Frontend: 58/100

## Counts

- Undefined variables: 0 confirmed
- Missing React hook dependencies: 0 confirmed
- High-complexity functions/components: 15 confirmed
- Long files/functions/components: 11 production files over 400 lines; 13 long functions/components
- Empty error handlers: 0 empty `catch {}` blocks confirmed
- Nested ternaries / fragile patterns: 12 confirmed
- Build/lint blockers: 3

## Confirmed Findings

### P1 Frontend components are very large and complex

Files:

- `frontend/src/pages/AdminDashboard.jsx`
- `frontend/src/components/AdminScheduleView.jsx`
- `frontend/src/pages/RestaurantApp.jsx`
- `frontend/src/pages/DriverApp.jsx`

Fix recipe:

1. Split `AdminDashboard` into focused tabs/panels.
2. Split `AdminScheduleView` into grid, editor, bulk actions, and emergency slot modules.
3. Verify with `yarn build` and browser smoke checks.

### P1 ESLint cannot run natively

File: `frontend/package.json`

Evidence:

- ESLint 9 exists in dev dependencies.
- There is no `eslint.config.js`.
- There is no `lint` script.

Fix recipe:

1. Add ESLint 9 flat config.
2. Add `"lint": "eslint src"`.
3. Enable React hooks, no-undef, and maintainability rules.

### P1 Backend tests depend on working directory/server mode

File: `backend/tests/_settings.py`

Fix recipe:

1. Standardize imports and documented test working directory.
2. Split integration tests from collect/unit checks.
3. Add a stable CI/local test command.

### P2 Backend has complexity in key routes

Files:

- `backend/routers/drivers.py`
- `backend/routers/orders.py`
- `backend/routers/seed.py`

Fix recipe:

1. Extract validation and mapping helpers.
2. Keep behavior covered by existing tests.

### P2 Backend flake8 fails on import/style noise

Files include:

- `backend/models/__init__.py`
- `backend/models/emergency_slot.py`
- `backend/routers/schedules.py`
- `backend/server.py`

Fix recipe:

1. Remove unused imports or add justified `__all__`/local ignores.
2. Configure line length if the project standard is not 79.
3. Re-run `python -m flake8 .`.

### P2 Frontend nested ternaries

Files include:

- `frontend/src/components/admin/DriverManagementDialog.jsx`
- `frontend/src/components/admin/MapMarkerIcons.jsx`
- `frontend/src/components/AdminScheduleView.jsx`
- `frontend/src/pages/AdminDashboard.jsx`
- `frontend/src/pages/RestaurantApp.jsx`

Fix recipe:

1. Extract helper functions or config maps.
2. Verify with lint and build.

## Tool Notes

The reviewer compared current local code with the external pasted report and found several old or unconfirmed claims in that report. Current local code should be treated as source of truth.
