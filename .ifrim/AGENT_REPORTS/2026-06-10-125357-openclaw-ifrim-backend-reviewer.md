# OpenClaw report: ifrim-backend-reviewer

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
**Backend Report**

Read-only backend review only. I did not edit, commit, push, run tests, or read `.env`, `.ifrim/private`, `.ifrim/tmp`, uploads, credential/token files, or `memory/test_credentials.md`.

**1. What This Is**

ProDelivery is a FastAPI + MongoDB/Motor delivery management backend for Bacău, with role-based flows for admins, restaurants, and drivers. The backend owns auth/session cookies, order lifecycle, restaurant availability, driver operations, delivery zones, schedules, emergency slots, analytics, geocoding, seed/demo data, avatar upload, and email verification.

Evidence: [README.md](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/README.md:1>), [backend/server.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:22>).

**2. Already Implemented**

Auth: JWT access/refresh cookies plus bearer fallback, login lockout, public driver registration, logout/refresh/me, disabled-account checks. See [backend/auth.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/auth.py:76>) and [backend/routers/auth.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/auth.py:116>).

Orders: role-scoped reads, restaurant/admin creation, zone fee detection, assignment, preparing/ready timing, problem follow-up orders, status transitions. See [backend/routers/orders.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/orders.py:155>).

Drivers: admin CRUD/profile/ranking/status/disable/delete, driver self-profile, email verification via Resend, avatar upload/moderation, location updates, dashboard. See [backend/routers/drivers.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/drivers.py:184>).

Restaurants/zones/schedules: restaurant accounts/status/hours/analytics, delivery polygons with fees, schedule selection gated by driver ranking, admin auto-generate/bulk/clone/quick-adjust, emergency slot claim flow. See [restaurants.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/restaurants.py:157>), [zones.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/zones.py:72>), [schedules.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/schedules.py:298>), [emergency_slots.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/emergency_slots.py:203>).

Tests exist for auth/security, zones, schedules, emergency slots, driver mobile/profile/avatar, restaurant/admin flows, and regression iterations under `backend/tests/`.

**3. Risky / Incomplete / Mocked / Fragile**

[P1] Order numbers are race-prone. `create_order` and problem orders use `count_documents({}) + 1`, so concurrent creates can duplicate order numbers. Evidence: [orders.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/orders.py:207>) and [orders.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/orders.py:339>). Use an atomic counter collection or unique indexed sequence per source.

[P1] Emergency slot claiming is not atomic. It checks `remaining_spots` then later `$inc`s by `-1`; two drivers can race below zero. Evidence: [emergency_slots.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/emergency_slots.py:153>) and [emergency_slots.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/emergency_slots.py:371>). Use `find_one_and_update` with `remaining_spots: {"$gt": 0}` and duplicate-driver guard.

[P1] Demo/seed route can wipe core collections if enabled. It is admin-gated and `ALLOW_SEED=true` gated, but `clear_demo_collections` deletes users except admins, all drivers, restaurants, orders, schedules, zones, emergency slots. Evidence: [seed.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/seed.py:17>) and [seed.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/seed.py:195>). Production deploy must hard-disable or remove this route.

[P2] Some analytics are synthetic/demo-shaped. `/api/stats/hourly` hashes date/hour instead of reading orders, and emergency auto-demand falls back to fixed peak counts when real orders are zero. Evidence: [stats.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/stats.py:31>) and [emergency_slots.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/emergency_slots.py:106>). Client-facing dashboards may look real while not reflecting operations.

[P2] Env handling is fail-fast but brittle: import-time `os.environ[...]` for DB, CORS, geocoding, Resend. Good for production clarity, but local/migration setup fails at import if any variable is missing. Evidence: [database.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/database.py:9>), [server.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:45>), [geocoding.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/geocoding.py:12>).

[P2] Validation is uneven. Core models use mostly plain `str`, `float`, and list defaults for order statuses/payment/source/items/polygons, with route-level validation in some places. Evidence: [order.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/models/order.py:31>) and [delivery_zone.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/models/delivery_zone.py:22>). Invalid polygons and bad payment/source values need explicit constraints/tests.

**4. Client-Facing Workflows Affected**

Login/session persistence and driver onboarding: auth cookies, phone/email login, refresh, disabled accounts, email verification.

Restaurant order handling: create order, detect delivery fee zone, mark preparing/ready, create problem follow-up, pause/close restaurant.

Dispatcher/admin live operations: assign orders, track active drivers, disable/delete drivers safely, moderate avatars, view restaurant analytics.

Driver mobile app: update profile, verify email, upload avatar, change active/break/offline state, update location, accept/pick up/deliver/cancel assigned orders.

Scheduling: tier-based schedule access, admin bulk generation, emergency slot claiming, clone previous week.

**5. Recommended Next 3 Actions**

1. Fix race-prone writes first: atomic order numbering and atomic emergency slot claim; add concurrency tests.
2. Lock down production readiness: ensure `ALLOW_SEED` cannot be enabled in prod, replace synthetic stats/emergency fallback data with real queries or label them as demo-only.
3. Harden contracts: add Pydantic constraints/enums for order status/source/payment, preparation bounds, zone polygon validity, coordinate ranges, and unique DB indexes for user email, order number, driver/user IDs.

**6. Files Codex Should Understand First**

Start with [backend/server.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:1>), [backend/database.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/database.py:1>), [backend/auth.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/auth.py:1>), then routers: `auth.py`, `orders.py`, `drivers.py`, `restaurants.py`, `zones.py`, `schedules.py`, `emergency_slots.py`, `stats.py`, `seed.py`, `geocoding.py`. Models to read next: `models/order.py`, `models/driver.py`, `models/schedule.py`, `models/delivery_zone.py`, `models/user.py`.

Tests were not executed; this report is static code evidence only.
⚠️ 🛠️ `"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command "rg -…kend\\utils\\avatar_storage.py backend\\routers\\drivers.py" (in ~\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery)` failed
