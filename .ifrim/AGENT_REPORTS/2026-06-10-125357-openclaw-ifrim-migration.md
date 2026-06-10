# OpenClaw report: ifrim-migration

- Generated: 2026-06-10-125357
- Project: ProDelivery
- Mode: read-only
|
o  Doctor warnings ------------------------------------------------------+
|                                                                        |
|  - Left plugin install index in place because shared SQLite state has  |
|    conflicting plugin install metadata for: codex                      |
|                                                                        |
+------------------------------------------------------------------------+
[state-migrations] Legacy state migration warnings:
- Left plugin install index in place because shared SQLite state has conflicting plugin install metadata for: codex
|
o  Doctor warnings ------------------------------------------------------+
|                                                                        |
|  - Left plugin install index in place because shared SQLite state has  |
|    conflicting plugin install metadata for: codex                      |
|                                                                        |
+------------------------------------------------------------------------+
[plugins] plugins.allow is empty; discovered non-bundled plugins may auto-load: codex (C:\Users\mihai\.openclaw\npm\projects\openclaw-codex-8902d781d4\node_modules\@openclaw\codex\dist\index.js). Set plugins.allow to explicit trusted ids.
Read-only report complete. I did not edit, commit, push, run tests, or read `.env`/private/upload/credential/token files.

**1. What This Project Is**
ProDelivery is an IfrimDigital delivery operations platform for Bacău: FastAPI + MongoDB backend, React/CRACO/Tailwind frontend, PWA-ish service worker, role-based UI for `admin`, `driver`, and `restaurant`.

**2. Already Implemented**
- Backend API under `/api` via `backend/server.py`, with routers for auth, drivers, restaurants, orders, stats, schedules, emergency slots, zones, geocoding, and seed.
- MongoDB via Motor in `backend/database.py`.
- Auth uses httpOnly access/refresh cookies, JWT fallback Bearer support, refresh/logout, brute-force lockout, role guards.
- Main workflows exist: order creation/assignment/status, restaurant prep timers/status/schedule/analytics, driver status/profile/avatar/schedule/email verification, delivery zones with polygon detection, admin schedule generation/quick adjust, live-map data.
- Demo seeding is protected by `ALLOW_SEED=true` and admin auth, but it intentionally rewrites demo collections.
- Frontend routes: `/login`, `/admin`, `/driver`, `/restaurant`.
- External services: Resend email, Nominatim/OSM geocoding.
- Tests exist under `backend/tests/` plus `backend_test.py`.

**3. Risky / Incomplete / Needs Verification**
- Hard env requirements will crash at import if missing: `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `CORS_ORIGINS`, Nominatim vars, Resend vars where used.
- `CORS_ORIGINS="*"` is noted in PRD/deployment history, but credentials + wildcard CORS needs verification at ingress and backend.
- `SettingsTab.jsx` is explicitly demo/mock; auto-assignment settings are not persisted.
- SMS verification is deferred, not implemented.
- Avatar storage appears server-filesystem based behind backend helpers; production persistence/object storage must be verified.
- Seed endpoint is destructive for demo data collections and should stay disabled outside controlled preview.
- Frontend depends on `REACT_APP_BACKEND_URL`; if unset, API calls become broken URLs.
- `frontend/README.md` is still stock CRA documentation; root README is the real useful one.
- No explicit external-builder string was found in searched code, but PRD still has old `/app/backend/` path context.

**4. User/Client-Facing Workflows Affected**
- Admin dispatch dashboard: live map, orders, restaurants, drivers, schedules, zones, analytics.
- Restaurant kitchen flow: online/pause/close day, prep timers, order ready/cancel/problem-order, history/analytics.
- Driver mobile flow: login by email/phone, active/break/offline status, current order status, schedule, profile/avatar/email verification.
- Delivery-zone workflow: restaurant-specific polygons, address/geocoding, delivery fee/availability detection.
- Demo/preview workflow: seed data, demo login buttons, live route examples.

**5. Recommended Next 3 Actions**
1. Verify local preview from clean env without reading secrets: MongoDB service, `.\dev-start.ps1`, `http://127.0.0.1:3000`, `http://127.0.0.1:8000/api/`.
2. Audit env contract into a checked-in `.env.example` or deployment checklist: backend required vars, frontend `REACT_APP_BACKEND_URL`, Resend/Nominatim, seed controls, CORS policy.
3. Replace or clearly quarantine demo-only production gaps: Admin Settings persistence, SMS plan, avatar storage persistence, ingress CORS behavior.

**6. Files Codex Should Understand First**
- `README.md`, `dev-start.ps1`, `dev-stop.ps1`
- `backend/server.py`, `backend/database.py`, `backend/auth.py`
- `backend/routers/auth.py`, `orders.py`, `drivers.py`, `restaurants.py`, `schedules.py`, `emergency_slots.py`, `zones.py`, `geocoding.py`, `seed.py`
- `frontend/package.json`, `frontend/craco.config.js`
- `frontend/src/App.js`, `frontend/src/context/AuthContext.js`
- `frontend/src/pages/AdminDashboard.jsx`, `DriverApp.jsx`, `RestaurantApp.jsx`, `LoginPage.jsx`
- `frontend/src/components/admin/SettingsTab.jsx`
- `memory/PRD.md`

Exact discovered commands:
- Install/start all preview: `.\dev-start.ps1`
- Stop preview: `.\dev-stop.ps1`
- Backend test script: `.\.venv\Scripts\python.exe backend_test.py`
- Frontend install: `cd frontend; yarn install`
- Frontend start: `cd frontend; yarn start`
- Frontend build: `cd frontend; yarn build`
- Backend direct start: `cd backend; ..\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload`
