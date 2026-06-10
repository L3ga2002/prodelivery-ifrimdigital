# OpenClaw report: ifrim-frontend

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
**Frontend Report**
Read-only audit only. No files changed, no commits/pushes. I used `rg`, `Get-Content`, and `Select-String`; I did not run build/browser because CRA build writes output.

**What This Is**
ProDelivery’s frontend is a React/CRA + CRACO delivery operations app with role-based routes: `/login`, `/admin`, `/driver`, `/restaurant` in [App.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/App.js:95>). It uses Tailwind, Radix/shadcn-style UI, `axios`, Leaflet maps, Recharts, and PWA service worker support.

**Already Implemented**
- Auth shell with cookie credentials, bearer token support, `/me`, refresh, login/logout in [AuthContext.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/context/AuthContext.js:47>).
- Admin dashboard: orders, drivers, restaurants, stats, analytics, live map, manual assignment, order/driver/restaurant creation, zone detection, schedule management, and demo order simulation in [AdminDashboard.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:363>).
- Driver mobile app: current order polling, accept/pickup/deliver/cancel, call/navigation links, schedule, profile editing, avatar upload, email verification, PWA install in [DriverApp.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/DriverApp.jsx:160>).
- Restaurant app: kitchen queue, prep timers, ready/cancel flows, pause/open/close controls, schedule settings, history, analytics, linked problem orders in [RestaurantApp.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/RestaurantApp.jsx:232>).
- Delivery zones and restaurant zones are real map-backed CRUD surfaces via `/api/zones` in [DeliveryZonesManager.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/DeliveryZonesManager.jsx:95>) and [RestaurantZonesManager.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/RestaurantZonesManager.jsx:188>).
- Admin/driver scheduling is substantial: auto-generate, emergency slots, bulk delete, quick adjust, clone previous week, driver claims in [AdminScheduleView.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/AdminScheduleView.jsx:155>) and [DriverSchedule.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/DriverSchedule.jsx:90>).

**Risks / Incomplete**
- Admin settings are explicitly demo-only and do not persist: [SettingsTab.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/admin/SettingsTab.jsx:58>).
- Admin “simulation” creates and mutates real orders through real API calls; must be gated or removed before client production use: [AdminDashboard.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:622>).
- Heavy polling: admin every 10s, driver/restaurant every 5s. No websocket/SSE; freshness, race conditions, and battery usage need verification.
- PWA service worker looks fragile: caches `/static/js/bundle.js`, references `.png` notification icons while manifest has `.svg`, and may serve stale app shells.
- React `19.0.0` with `react-scripts@5` is a compatibility risk; build/runtime must be verified in the actual environment.
- No frontend test files found. Backend has tests, but UI regressions appear uncovered.
- Several UX controls are placeholder-ish: login eye icon does not toggle password visibility; driver menu button has no action; phone SMS validation is future-only.
- Maps depend on external OSM tiles and Leaflet behavior; marker rendering and mobile map sizing need browser verification.

**Client-Facing Workflows**
- Admin dispatcher: monitor orders, assign drivers, create orders, create restaurants/drivers, inspect map/routes, manage schedules/zones.
- Restaurant operator: receive new orders, choose prep time, mark ready, cancel with reason, pause/close restaurant, manage schedule, view history/analytics.
- Driver mobile/PWA: login, see active delivery, accept/pick up/deliver/cancel, navigate/call customer, manage profile/avatar, claim schedule slots.
- Login/auth recovery: role redirect, session refresh, logout, demo login only in development env.
- Zone/location workflow: geocode Bacau addresses, select pins, detect delivery zones, calculate fees.

**Next 3 Actions**
1. Run a real frontend verification pass: install deps, start app, test login and each role route in browser/mobile viewport, check console/network/PWA/map errors.
2. Remove or hard-gate production-dangerous/demo surfaces: admin simulation, demo settings, demo credential UI, and any preview-only email fallback copy.
3. Add focused frontend smoke tests or Playwright flows for login redirects, admin assignment, restaurant prep/ready, driver delivery status, and zone detection.

**Files Codex Should Read First**
- [App.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/App.js:29>)
- [AuthContext.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/context/AuthContext.js:6>)
- [AdminDashboard.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:363>)
- [DriverApp.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/DriverApp.jsx:160>)
- [RestaurantApp.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/RestaurantApp.jsx:197>)
- [AdminScheduleView.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/AdminScheduleView.jsx:155>)
- [RestaurantZonesManager.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/RestaurantZonesManager.jsx:188>)
- [package.json](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/package.json:63>)
⚠️ 🛠️ `"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command "rg -…frontend | rg \"(test|spec)\\.(js|jsx|ts|tsx)"'$|__tests__"' (in ~\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery)` failed
