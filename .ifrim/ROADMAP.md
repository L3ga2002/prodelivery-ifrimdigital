# ProDelivery Bacau Roadmap

Source: user-provided roadmap from the original Emergent-started project context.
Last updated from user context: 2026-06-10

## Purpose

ProDelivery Bacau is intended as a complete local delivery management platform for Bacau, with admin/dispatch, restaurant, and driver workflows. The long-term direction includes live GPS, smarter dispatching, product catalog/menu, client ordering app, Android driver app, notifications, and advanced analytics.

## Initial Plan

### Admin / Dispatch

Admin should be able to:

- view all orders
- manually create orders
- assign drivers
- track order status
- manage restaurants
- manage drivers
- view a live map
- view general statistics
- manage delivery zones
- manage driver schedules

### Restaurant App

Restaurants should be able to:

- view incoming orders
- accept, prepare, and mark orders ready
- set preparation time
- view order history
- work quickly with minimal clicks

### Driver App

Drivers should be able to:

- authenticate
- view current order
- accept order
- mark picked up / delivered
- view restaurant and customer address
- set status
- view schedule
- view profile

### Maps And Zones

The system should include:

- admin map
- restaurants on map
- drivers on map
- delivery zones
- zone-based fees
- easier assignment based on location

### Basic Analytics

Initial analytics target:

- total orders
- active orders
- delivered orders
- active drivers
- active restaurants
- simple admin statistics

### Future Direction

The project has long-term potential for:

- Android app for drivers
- client app
- product catalog / menu
- real live GPS
- push notifications
- automatic or semi-automatic assignment

## Implemented

### Backend

Implemented FastAPI + MongoDB backend for:

- auth
- roles: admin, restaurant, driver
- orders
- restaurants
- drivers
- delivery zones
- driver schedules
- emergency slots
- analytics
- avatar upload
- driver email verification
- driver status
- restaurant status
- restaurant pause
- problem orders

Status: implemented.

### Login And Roles

Separate login exists for:

- Admin
- Restaurant
- Driver

Each role routes to its app:

- Admin Dashboard
- Restaurant App
- Driver App

Status: implemented.

### Admin Dashboard

Admin currently has:

- general dashboard
- active orders
- orders table
- order source: Site, Bolt, Wolt, Glovo
- new order creation
- manual assignment
- drivers list
- restaurants list
- live map
- driver schedule
- analytics
- demo admin settings
- dark mode
- responsive layout

Status: implemented partially/completely, but Admin Settings remains mocked/demo.

### Admin Orders

Implemented:

- order list
- order status
- driver assignment
- assignment modal
- scrollable drivers list
- available/unavailable drivers
- selected order stays locked in modal
- clear sources: Site, Bolt, Wolt, Glovo

Status: implemented.

### Admin Live Map

Implemented:

- restaurants on map
- drivers on map
- car/scooter differentiated icons
- demo routes between driver, restaurant, and customer
- customer pin
- colored markers:
  - green = active
  - blue = delivering
  - orange = break
  - gray = offline
- green active restaurants
- visible scooters for demo

Status: demo/preview implemented; real live GPS is still missing.

### Admin Drivers

Admin can:

- add driver
- set vehicle: scooter/car
- send verification email
- view driver details
- view score/rank
- manually edit score
- add internal note
- change status
- put driver on break
- soft-disable account
- delete account with protections
- upload avatar
- manage individual schedule

Status: implemented.

### Driver Email Verification

Resend integration exists for:

- sending verification code
- real verified domain
- new driver creation flow

Status: implemented.

### Driver Avatar

Implemented:

- avatar upload
- gallery button
- selfie button
- 10MB limit
- crop / WebP compression
- more visible UI buttons

Status: implemented.

### Admin Schedule / Calendar

Implemented:

- weekly calendar
- standard slots
- emergency slots
- visual cell split:
  - top = standard
  - bottom = emergency
- standard slot count
- emergency slot count
- occupied/free state
- colors:
  - green standard
  - red emergency
  - gray free
- individual driver dialog
- simplified driver program without quick +1/+2/+3 buttons
- standard/emergency split in individual calendar

Status: implemented.

### Driver App

Complete redesign implemented:

- mobile-first
- bottom tabs
- home
- delivery
- calendar
- profile
- avatar
- active/break/offline status
- extended profile:
  - name
  - email
  - phone
  - CNP
  - gender
  - birth date
- phone validation
- redesigned mobile calendar
- fixed status bug where Active no longer stays Offline

Status: implemented.

### Mobile Driver Calendar

Rebuilt:

- no heavy horizontal table
- day selector
- vertical interval list
- clear colors:
  - orange = driver hours
  - blue = admin
  - red = emergency
  - gray = night/blocked
- touch-friendly mobile UI

Status: implemented.

### Restaurant App

Complete redesign implemented:

- dark/orange layout
- Kanban/Bento style
- top status cards:
  - New
  - In progress
  - Delivered
- cards act as direct filters
- active orders
- in-progress orders
- delivered orders
- restaurant status
- restaurant pause
- pause bar with manual input
- working hours
- order history
- large order detail modal
- restaurant analytics
- problem orders for delivered orders

Status: implemented.

### Restaurant Pause

Implemented:

- quick pause
- manual pause in minutes
- timer
- close for today
- return online
- persisted backend status

Status: implemented.

### Restaurant Working Hours

Implemented:

- active/inactive days
- opening time
- closing time
- backend persistence

Status: implemented.

### Problem Orders

Implemented:

- missing product
- new/additional product
- linked follow-up order from original order
- available only for delivered orders
- accessible from order history detail

Status: implemented.

### Restaurant Order History

Implemented:

- history list
- search
- click order
- large detail modal:
  - customer
  - phone
  - address
  - items
  - total
  - status
  - driver
  - notes

Status: implemented.

### Restaurant Analytics

Implemented:

- restaurant-scoped analytics
- data filtered to the current restaurant
- dark UI charts
- visible colors

Status: basic implementation.

### Delivery Zones

Implemented:

- zones per restaurant
- polygons
- zone fee
- zone level
- deletion protection
- zone detection for orders

Status: implemented.

### Deployment

Production deploy was previously done:

- domain: `prodeliverybacau.com`
- app runs live
- deployment health check previously passed
- `.env`, CORS, and `.gitignore` were adjusted during deployment work

Status: implemented in earlier project history. Production status should be re-verified before relying on it.

## Added During The Project

### Driver App Redesign

Added and implemented:

- mobile-first UX
- tabs
- extended profile
- mobile calendar
- avatar
- statuses
- flow closer to a real Android app

### Restaurant App Redesign

Added and implemented:

- premium dark/orange design
- status cards
- simpler dashboard
- More button
- manual pause
- detailed history
- analytics
- working hours

### Standard / Emergency Calendar Split

Added during the project and implemented in:

- Admin general schedule calendar
- Admin individual driver calendar
- Driver mobile calendar

### Demo Map For Client Presentation

Added and implemented as demo:

- demo routes
- customer pin
- car and scooter drivers
- green active restaurants
- colored markers
- visible routes

### Resend Email Verification

Added and implemented for:

- driver creation
- verification code
- real-domain sending

### Driver Soft Disable

Added and implemented:

- disable account
- keep history
- block login
- protect if driver has active orders

### Code Quality Review

Added quality scope:

- hook dependencies
- large components
- complex Python functions
- `is True` / `is False`
- random/secrets
- console statements
- empty catch blocks
- nested ternaries

Status: started but not fully completed.

### Emergent Inspect Element Issue

After deployment, an "emergent" reference appeared in inspect element.

Current understanding:

- likely deployment infrastructure
- likely injected platform script
- not direct application code

Status: unresolved in code; likely infrastructure/platform-related.

## Remaining Work

### Complete Code Quality

Remaining:

- hook dependencies across large files
- empty catch blocks
- split large components into smaller files
- split complex Python functions into services
- clean nested ternaries
- full lint verification
- remove real warnings via refactor rather than disabling them

Status: in progress / remaining.

### Real Admin Settings

Admin Settings is still mocked/demo.

Needed:

- MongoDB settings collection
- `GET /api/settings`
- `PATCH /api/settings`
- real Admin UI
- persistent settings for:
  - delivery radius
  - order timeout
  - schedule rules
  - emergency rules
  - rank rules
  - fees
  - notifications

Status: remaining.

### Real Live GPS

Map is good for demo, but does not have real periodic GPS from driver app.

Needed:

- driver app requests location permission
- sends coordinates periodically
- backend stores latest position
- admin map updates live
- fallback when GPS is off
- last update timestamp

Proposed endpoint:

- `POST /api/drivers/location`

Status: remaining.

### Semi-Automatic Assignment

Current assignment is manual.

Needed:

- driver recommendation
- scoring by:
  - distance
  - status
  - vehicle
  - rank/score
  - schedule
  - active orders
  - break state
- "Recommend driver" button

Status: remaining.

### Product Catalog / Menu

Needed for client app and problem orders:

- product categories
- products
- prices
- images
- availability
- toppings/options
- temporarily unavailable product
- menu per restaurant

Status: remaining / future.

### Client App

End customer could:

- view restaurants
- view menus
- place order
- track delivery
- see estimated time
- see restaurant status
- pay online in a later phase

Status: remaining / future phase.

### Android Driver App

Current Driver App is web/PWA.

For a real Android app:

- React Native / Expo
- background GPS
- push notifications
- APK/AAB
- Android permissions
- test build
- possible Play Store setup

Status: large separate future phase.

### Real Notifications

Needed:

- new order notification for restaurant
- assigned order notification for driver
- delay notification
- break notification
- cancellation notification
- push notifications
- possible future SMS via Twilio

Status: remaining.

### Advanced Analytics

Admin:

- orders by hour
- orders by source
- top drivers
- top restaurants
- busy zones
- cancellations by reason
- delays
- estimated revenue

Restaurant:

- sold products
- average preparation time
- product problems
- peak hours
- missed/cancelled orders

Driver:

- earnings
- hours worked
- punctuality
- delivered orders
- explained score/rank

Status: partially implemented / needs expansion.

### Audit Log

Need audit for:

- who assigned an order
- who cancelled an order
- who changed status
- who modified schedule
- who disabled a driver
- who deleted a zone
- who changed score

Collection:

- `audit_logs`

Status: partial / needs expansion.

## Recommended Phases

### Phase 3 - Stabilization And Code Quality

Objective: make the code clean and maintainable.

Includes:

- hook dependencies
- split large components
- backend service refactor
- remove real warnings
- reduce complexity
- quick tests after each slice

Main files:

- `frontend/src/pages/RestaurantApp.jsx`
- `frontend/src/pages/DriverApp.jsx`
- `frontend/src/components/AdminScheduleView.jsx`
- `frontend/src/pages/AdminDashboard.jsx`
- `frontend/src/components/DeliveryZonesManager.jsx`
- `frontend/src/components/RestaurantZonesManager.jsx`
- `backend/routers/drivers.py`
- `backend/routers/orders.py`
- `backend/routers/restaurants.py`
- `backend/routers/seed.py`

Priority: high.

### Phase 4 - Real Admin Settings And Operational Config

Objective: remove mocked/demo settings.

Includes:

- backend settings
- MongoDB settings
- real admin UI
- saved values
- apply values in logic

Priority: high.

### Phase 5 - Real Live GPS And Smarter Dispatch

Objective: track real drivers.

Includes:

- live GPS from Driver App
- map update
- position timestamp
- GPS status
- driver recommendation
- semi-automatic assignment

Priority: very high for a real product.

### Phase 6 - Product Catalog / Restaurant Menu

Objective: prepare for client app.

Includes:

- products
- categories
- menu
- product availability
- catalog-backed problem orders
- product images

Priority: medium to high.

### Phase 7 - Client App

Objective: end customer orders directly from the platform.

Includes:

- restaurant list
- menu
- cart
- order placement
- order tracking
- delivery status
- client account

Priority: large future phase.

### Phase 8 - Android Driver App

Objective: real native driver app.

Includes:

- React Native / Expo
- background GPS
- push notifications
- test APK
- production AAB
- calendar
- orders
- status
- profile

Priority: large separate phase.

### Phase 9 - Advanced Analytics And Reports

Objective: provide useful business data.

Includes:

- admin reports
- restaurant reports
- driver reports
- CSV/PDF export
- top restaurants
- top drivers
- profitable zones
- peak hours

Priority: medium.

### Phase 10 - Final UI Polish / Client-Ready Product

Objective: make the product fully presentable for end clients.

Includes:

- mobile polish
- empty/loading/error states
- cleaner modals
- complete responsive behavior
- consistent colors
- clearer copy
- shorter flows
- desktop/tablet/mobile testing

Priority: continuous.

