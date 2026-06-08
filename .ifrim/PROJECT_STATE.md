# Project State

Project: ProDelivery
Owner workspace: IfrimDigital
Local path: `C:\Users\mihai\OneDrive\Documente\IfrimDigital Projects\ProDelivery`
Last updated: 2026-06-08

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

## Important Notes

- This copy was migrated from an exported project archive.
- Old external-builder artifacts were removed from the active copy.
- Active prompts/config should stay branded to IfrimDigital.
- Do not store production secrets in this folder.
- Demo credentials are for local testing only and must be changed before production.
