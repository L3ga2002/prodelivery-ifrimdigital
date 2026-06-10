# OpenClaw report: ifrim-design

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
**ProDelivery UX/Product Design Report**

1. **What This Is**
ProDelivery is a role-based delivery operations platform for Bacău: admin dispatch/control room, driver mobile PWA, and restaurant kitchen queue/KDS. The frontend is React + Tailwind + shadcn/Radix + Leaflet + Recharts, routed through protected role screens in [App.js](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/App.js:97).

2. **Already Implemented**
The app has three distinct user-facing experiences:
- Admin dashboard: command center, orders, analytics, live map, drivers, scheduling, restaurants, settings in [AdminDashboard.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:249).
- Driver app: mobile-first dark/orange shell with home, delivery, calendar, profile, order actions, phone/navigation, avatar, status, email verification in [DriverApp.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/DriverApp.jsx:388).
- Restaurant app: dark KDS with active order cards, prep timers, pause/close controls, history, analytics, schedule, problem-order flow in [RestaurantApp.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/RestaurantApp.jsx:456).

Design system is mostly coherent: Public Sans + Barlow Condensed, slate/navy/orange, dark restaurant/driver surfaces, admin control surfaces, responsive admin order cards, Leaflet markers and route styling in [index.css](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/index.css:1) and [App.css](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/App.css:110).

3. **Risks / Incomplete / Needs Verification**
- Admin Settings is explicitly demo-only: save button says “Setări salvate (demo)” and the panel warns “Mod Demo” in [SettingsTab.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/admin/SettingsTab.jsx:58).
- Admin UX is still structurally heavy: [AdminDashboard.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:249) is about 1.5k lines; [AdminScheduleView.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/AdminScheduleView.jsx:128) is about 1.2k lines. Design changes there are higher-risk.
- Several dense operational surfaces use horizontal overflow: schedule calendar, emergency grid, simple driver schedule, orders table. They need real-device verification, especially laptop widths and 390px mobile.
- Driver app is capped at `max-w-md`, good for PWA/mobile, but desktop/tablet driver presentation is intentionally phone-like in [DriverApp.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/DriverApp.jsx:523).
- Admin map currently simulates driver movement client-side with `Math.random()` and refreshes every 10s, so “live” behavior must be verified against real tracking expectations before client signoff.
- SMS is deferred, not mocked: driver profile says phone validation will be connected later in [DriverApp.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/DriverApp.jsx:514).

4. **Key Client-Facing Workflows**
- Admin: create/assign orders, inspect active orders, dispatch from live map, manage drivers, manage restaurant zones, tune weekly schedule.
- Driver: login by email/phone, set active/break/offline, accept/pick up/deliver/cancel order, call customer, open navigation, edit schedule/profile.
- Restaurant: receive new orders, pick prep time, monitor countdown/late timer, mark ready, pause/close restaurant, search history, create linked problem orders.
- Restaurant zones: draw/edit/delete protected restaurant-specific delivery zones with explicit `CONFIRM` guard in [RestaurantZonesManager.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/RestaurantZonesManager.jsx:173).

5. **Recommended Next 3 Actions**
1. Run a visual QA pass with real/demo-rich data on admin schedule, live map, restaurant KDS, and driver mobile at 390px, 768px, 1366px, 1920px; focus on overflow, clipped text, sticky/fixed bottom controls, and map popups.
2. Replace or clearly hide unfinished demo surfaces before client review, especially Admin Settings and any simulation/demo CTA that could look production-ready.
3. Split/refactor the largest UI files before major new design work: `AdminDashboard`, `AdminScheduleView`, then `RestaurantApp`; this will reduce regression risk.

6. **Files Codex Should Understand First**
- [frontend/src/App.js](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/App.js:97)
- [frontend/src/pages/AdminDashboard.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:249)
- [frontend/src/components/AdminScheduleView.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/AdminScheduleView.jsx:128)
- [frontend/src/pages/DriverApp.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/DriverApp.jsx:110)
- [frontend/src/pages/RestaurantApp.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/pages/RestaurantApp.jsx:170)
- [frontend/src/components/admin/LiveMapPanel.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/admin/LiveMapPanel.jsx:123)
- [frontend/src/components/admin/OrdersTab.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/admin/OrdersTab.jsx:33)
- [frontend/src/components/RestaurantZonesManager.jsx](C:/Users/mihai/OneDrive/Desktop/Ifrim%20Digital%20Proiecte/ProDelivery/frontend/src/components/RestaurantZonesManager.jsx:173)

Read-only inspection only. I did not run the app or visually verify screenshots, so layout quality still needs browser/device validation.
