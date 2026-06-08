# Code Review Report - 2026-06-08

Source: IfrimDigital OpenClaw specialist reviewers.

## Lead Findings

### P0/P1 Release Blockers

- Public seed/reset endpoint can wipe data and expose demo credentials.
  - Files: `backend/routers/seed.py`, `backend/server.py`
  - Owner: `ifrim-backend`
  - Fix: require admin/dev-only gate or remove from production router.

- Public registration allows arbitrary privileged roles.
  - Files: `backend/models/user.py`, `backend/routers/auth.py`
  - Owner: `ifrim-backend`
  - Fix: ignore client-supplied privileged roles; default public registration to customer or disable public registration.

- Order read endpoints leak cross-tenant data.
  - File: `backend/routers/orders.py`
  - Owner: `ifrim-backend`
  - Fix: enforce role and object ownership filters for admin, restaurant, driver, and customer contexts.

- Order mutation endpoints allow cross-role or cross-tenant status changes.
  - File: `backend/routers/orders.py`
  - Owner: `ifrim-backend`
  - Fix: enforce allowed status transitions per role and ownership.

- Driver profile endpoint exposes sensitive driver data.
  - Files: `backend/models/driver.py`, `backend/routers/drivers.py`
  - Owner: `ifrim-backend`
  - Fix: restrict to admin-or-self and return sanitized response models.

## Frontend / DevOps Findings

- Demo credentials can be exposed in public login UI/config.
- Service worker references production/static assets in a fragile way.
- Push notification icons reference missing PNG files.
- `dev-stop.ps1` can kill unrelated processes on ports 3000/8000.
- `dev-start.ps1` should validate health after start and handle occupied ports safely.

## Recommended Fix Order

1. Backend security P0/P1 issues.
2. Frontend credential exposure and service worker/push icon issues.
3. DevOps script safety.
4. QA verification.
5. Security reviewer sign-off.
