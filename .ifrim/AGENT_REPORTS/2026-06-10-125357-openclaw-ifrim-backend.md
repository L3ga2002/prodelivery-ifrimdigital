# OpenClaw report: ifrim-backend

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
**ProDelivery Backend Report**

1. **What It Is**
ProDelivery is a FastAPI + MongoDB delivery operations backend for Bacău: admin dispatch, restaurant order prep, driver scheduling/status, delivery zones, emergency slots, analytics, auth, email verification, and demo seeding. Main entrypoint is [backend/server.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\server.py:1>), with all APIs mounted under `/api`.

2. **Already Implemented**
- Auth: JWT access/refresh tokens in httpOnly cookies, Bearer fallback, refresh/logout, role context, disabled-account checks, login lockout. See [backend/auth.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\auth.py:1>) and [backend/routers/auth.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\auth.py:1>).
- Orders: create/list/filter, restaurant/driver/admin authorization, assignment, prep timer, ready/delivered/cancelled lifecycle, problem follow-up orders, delivery-zone fee detection. See [backend/routers/orders.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\orders.py:1>).
- Drivers: CRUD-ish admin management, ranking override, profile/self-profile, status active/break/offline/delivery, location, avatar upload/moderation, email verification, soft-disable/delete guards. See [backend/routers/drivers.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\drivers.py:1>).
- Restaurants: create restaurant + login user, availability by zone coverage, pause/close day status, schedule settings, restaurant analytics. See [backend/routers/restaurants.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\restaurants.py:1>).
- Zones: restaurant-scoped polygon zones, locked edits/deletes requiring confirmation, Shapely point-in-polygon detection, legacy global zone cleanup. See [backend/routers/zones.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\zones.py:1>).
- Scheduling: driver/admin hours, ranking-gated calendar access, normal slot generation, bulk delete, quick adjust, clone previous week. See [backend/routers/schedules.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\schedules.py:1>).
- Emergency slots: create/list/claim/delete, auto-generation, setup generation, bulk delete with schedule cleanup. See [backend/routers/emergency_slots.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\emergency_slots.py:1>).
- External services: Nominatim geocoding proxy, Resend email verification, local WebP avatar processing.

3. **Risky / Incomplete / Needs Verification**
- CORS is a known deployment risk. Backend has explicit origin handling, but PRD says external ingress still returns wildcard preflight; also `CORS_ORIGINS="*"` was reportedly used for deployment, which should be rechecked with credentialed cookies.
- MongoDB is schemaless here: no migrations/index definitions found. Need verify unique indexes for user email/phone, order numbers, and ids; `order_number` uses `count_documents`, which can race.
- Avatar storage writes to `backend/uploads/driver_avatars`; good abstraction, but not durable across multi-instance/multi-deploy unless backed by persistent volume or object storage.
- SMS phone verification is deferred, not implemented. Phone login exists, but `phone_verified` remains a future integration concern.
- Emergency auto-generation uses fallback demand values when order history is thin; tune with real client volume.
- Seed endpoint is protected by `ALLOW_SEED` and admin auth, but it mutates demo data heavily. Treat as non-production or lock tightly.
- I did not run tests because they call live endpoints and can seed/mutate MongoDB.

4. **Client-Facing Workflows Affected**
- Admin dispatch: create/assign orders, live map data, driver status, driver disable/delete, ranking, scheduling, emergency capacity.
- Restaurant app: accept/pause/close, set prep time, mark ready, cancel with reason, view history/analytics, create problem follow-up orders.
- Driver app: login by email/phone, set active/break/offline, receive assigned orders, update delivery status, manage profile/avatar, claim emergency slots, choose schedule.
- Delivery pricing/coverage: restaurant-specific polygons determine available restaurants and delivery fee.
- Demo/client preview: `/api/seed` creates demo users, restaurants, orders, routes, zones.

5. **Recommended Next 3 Actions**
1. Verify production CORS/auth end-to-end with cookies through the real ingress: `OPTIONS`, login, refresh, authenticated GET, and logout from actual frontend domains.
2. Add/confirm Mongo indexes and uniqueness constraints for `users.email`, `users.phone`, ids, and order numbering; replace count-based order numbers if concurrency matters.
3. Decide storage/integration production posture: persistent avatar storage, Resend monitoring, SMS provider decision, and whether seed routes are disabled outside preview.

6. **Files Codex Should Read First**
- [backend/server.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\server.py:1>)
- [backend/auth.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\auth.py:1>)
- [backend/database.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\database.py:1>)
- [backend/routers/orders.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\orders.py:1>)
- [backend/routers/drivers.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\drivers.py:1>)
- [backend/routers/schedules.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\schedules.py:1>)
- [backend/routers/zones.py](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\backend\routers\zones.py:1>)
- [memory/PRD.md](<C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\memory\PRD.md:1>)

Env vars observed from code/tests: `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `CORS_ORIGINS`, `NOMINATIM_BASE_URL`, `NOMINATIM_USER_AGENT`, `NOMINATIM_BACAU_VIEWBOX`, `RESEND_API_KEY`, `SENDER_EMAIL`, `ALLOW_SEED`, plus demo account vars used by seed/tests.
