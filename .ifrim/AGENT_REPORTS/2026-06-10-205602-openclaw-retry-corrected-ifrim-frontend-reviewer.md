# OpenClaw corrected retry report: ifrim-frontend-reviewer

- Generated: 2026-06-10-205602
- Project: ProDelivery
- Mode: read-only retry corrected syntax

---
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
**ProDelivery Frontend Specialist Report**

ProDelivery is a role-based React delivery operations app migrated from Emergent. Frontend routes are `/login`, `/admin`, `/restaurant`, and `/driver`, guarded by `AuthContext` and role checks in [App.js](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/App.js:29). It already has substantial admin dispatch, restaurant order handling, driver mobile/PWA, schedules, delivery zones, maps, dark mode, and local demo login support.

Preview was not running during review: `http://127.0.0.1:3000` and `http://127.0.0.1:8000/api/` both refused connections. I did not run `yarn build` because it writes to `frontend/build` and this pass is read-only.

**Findings**

[P1] Admin settings are demo-only but presented as operational controls  
File/line: [SettingsTab.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/admin/SettingsTab.jsx:58) and [AdminDashboard.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:325)  
Owner: `ifrim-frontend` + `ifrim-backend`  
Evidence: Settings state is local only; save button only shows `toast.success("Setări salvate (demo)")`; UI labels claim auto assignment/timeout/radius behavior.  
Impact: Client/admin can believe dispatch automation is configured when nothing is persisted or enforced.  
Fix recipe: add real `GET/PATCH /api/settings`, load settings on admin mount, save with loading/error states, hide or label unsupported automation until backend exists. Add UI test for save/reload persistence.  
Verification command: `cd frontend; yarn test --watchAll=false --runTestsByPath src/pages/AdminDashboard.test.jsx`

[P1] “Live” map is simulated, not real GPS-backed  
File/line: [AdminDashboard.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:332), [LiveMapPanel.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/admin/LiveMapPanel.jsx:123), [DriverApp.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/DriverApp.jsx:160)  
Owner: `ifrim-frontend` + `ifrim-backend`  
Evidence: admin randomly moves driver coordinates every 3s; map badge says `LIVE`; driver app polls orders/profile but has no geolocation permission or location POST.  
Impact: Dispatch cannot rely on map positions for real operations, ETAs, or nearest-driver assignment.  
Fix recipe: implement driver geolocation opt-in, `POST /api/drivers/location`, backend last-known position, admin polling or websocket refresh, stale-location UI.  
Verification command: `rg -n "geolocation|drivers/location|driverPositions|Math.random" frontend/src backend`

[P2] Admin demo simulation mutates real order data  
File/line: [AdminCommandCenter.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/admin/AdminCommandCenter.jsx:83), [AdminDashboard.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:646)  
Owner: `ifrim-frontend` + `ifrim-qa`  
Evidence: “Simulare Demo” creates an order and advances it through preparing/ready/assign/accepted/picked-up/delivered via production API calls.  
Impact: A client/admin can pollute real production orders and stats with demo data.  
Fix recipe: gate behind `NODE_ENV === "development"` or explicit demo mode; visually mark sandbox mode; block in production builds. Add test asserting button absent when demo mode disabled.  
Verification command: `rg -n "simulate-demo|Simulare Demo|Simulare demo|api/orders" frontend/src`

[P2] New driver/restaurant creation exposes generated passwords in UI toasts  
File/line: [AdminDashboard.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:553), [AdminDashboard.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:585)  
Owner: `ifrim-frontend` + `ifrim-security`  
Evidence: success/warning toasts include `res.data.password` and restaurant `login_email / password`.  
Impact: Passwords can leak via screen sharing, notifications, screenshots, or browser automation logs.  
Fix recipe: replace with “temporary password sent by email” or one-time reveal modal with copy and expiry; prefer invite/reset flow. Add UI test that toast text does not include password fields.  
Verification command: `rg -n "res\\.data\\.password|Parolă:|Login:" frontend/src`

[P2] Frontend quality gate is not production-ready  
File/line: [package.json](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/package.json:62)  
Owner: `ifrim-frontend`  
Evidence: scripts only include `start`, `build`, `test`; ESLint deps exist but no `lint` script/config found; no `*.test.*`/`*.spec.*` under `frontend/src`.  
Impact: Large role screens can regress hooks, accessibility, responsive behavior, and auth flows without fast CI feedback.  
Fix recipe: add ESLint 9 config and `yarn lint`; add smoke tests for login redirects, admin settings, restaurant order status, driver status update.  
Verification command: `cd frontend; yarn lint && yarn test --watchAll=false`

**Already Implemented**

Auth/session refresh, role redirects, demo-login gating by development env, admin data polling, manual order creation/assignment, restaurant pause/schedule/problem-order flows, driver profile/status/avatar/order polling, Leaflet map, schedules, zones, PWA install UI, and toast-based loading/error feedback are present.

**Key Client Workflows Affected**

Admin dispatch: order creation, manual driver assignment, map monitoring, settings, demo simulation.  
Restaurant operations: accepting/preparing/ready/cancel/problem orders, pause/working hours, analytics.  
Driver app: current delivery, accept/pickup/delivered/cancel, status, profile/avatar, PWA install.

**Recommended Next 3 Actions**

1. Remove or gate production-dangerous demo surfaces: admin simulation, demo settings save, and any password-revealing toasts.  
2. Implement real operational settings and GPS location flow, or clearly downgrade UI copy from “live/automatic” to “demo/manual”.  
3. Add frontend lint/test gate before more feature work, starting with auth routing and the three role dashboards.

**Files Codex Should Understand First**

[App.js](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/App.js:29), [AuthContext.js](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/context/AuthContext.js:44), [LoginPage.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/LoginPage.jsx:22), [AdminDashboard.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:363), [RestaurantApp.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/RestaurantApp.jsx:197), [DriverApp.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/DriverApp.jsx:160), [LiveMapPanel.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/admin/LiveMapPanel.jsx:123), [SettingsTab.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/admin/SettingsTab.jsx:9).
⚠️ 🛠️ `"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command "rg -…"'!node_modules/**'"' -g '"'!build/**'"' -g '"'!**/.env*'"'" (in ~\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery)` failed

