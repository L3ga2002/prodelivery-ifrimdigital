# Project State

Project: ProDelivery
Owner workspace: IfrimDigital
Local path: `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`
Last updated: 2026-06-10

## Purpose

ProDelivery is a local delivery management platform for Bacau. It has admin, restaurant, and driver flows, with live order management, delivery zones, schedules, and demo data.

## Stack

- Backend: FastAPI, MongoDB, Motor, Pydantic, JWT auth
- Frontend: React, CRACO, Tailwind, Radix UI, Leaflet
- Database: local MongoDB at `127.0.0.1:27017`
- Local env files:
  - `backend/.env`
  - `frontend/.env`

## Current Local Status

- Backend preview target: `http://127.0.0.1:8000/api/`
- Frontend preview target: `http://127.0.0.1:3000`
- Main script: `.\dev-start.ps1`
- Stop script: `.\dev-stop.ps1`
- Seed data was created during migration: 103 orders, 5 drivers, 5 restaurants.
- Browser preview was verified on admin and restaurant/login flows.

## Recent Verification

- `backend_test.py`: passed 8/8 in local API smoke test.
- `yarn build`: passed.
- `ifrim-qa`: passed smoke review with minor warnings.
- `ifrim-quality-reviewer`: produced scorecard 63/100 on current local code.
- `backend/tests/test_security_authorization.py`: passed 10/10 after P0/P1 and P2 security hardening.
- `ifrim-security-reviewer`: no blocker found after security hardening in `AGENT_REPORTS/2026-06-10-215444-openclaw-security-rereview-after-hardening.md`.
- `yarn lint`: passed with 0 errors and 0 warnings after frontend lint cleanup.
- `yarn build`: passed after frontend lint cleanup.
- Browser preview: `http://127.0.0.1:3000/restaurant` verified with 0 console errors after frontend UI component fix.
- Browser preview: `http://127.0.0.1:3000/login` and `http://127.0.0.1:3000/restaurant` verified with 0 console errors after frontend lint cleanup.

## Current Phase

Phase 2: client-review readiness and stabilization of existing flows.

Do not treat this copy as production-ready. Do not start future-phase scope such as real live GPS, client ordering app, product catalog, Android app, or advanced analytics unless Catalin confirms client scope/payment.

## Security Status

- P0/P1 security/backend issues from older reports are fixed in code and locally verified.
- Cookie auth uses `SameSite=Lax` plus strict origin checks for unsafe methods.
- Login lockout no longer trusts spoofable `X-Forwarded-For`.
- Remaining security/product decisions: production `CORS_ORIGINS`, public driver avatar serving, all-role stats/restaurant directory access, and public registration rate limiting.

## Important Notes

- This copy was migrated from an exported project archive.
- Old external-builder artifacts were removed from the active copy.
- Active prompts/config should stay branded to IfrimDigital.
- Do not store production secrets in this folder.
- Demo credentials are for local testing only and must be changed before production.
