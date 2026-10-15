# ProDelivery Phase Roadmap

## Actualizare prioritara 2026-09-26

Cele zece etape ale noului pachet operational sunt in `EXECUTION_PLAN_2026-09-26.md`. Ele nu se confunda cu numerotarea comerciala istorica Phase 2/Stage 1 de mai jos. Catalin a aprobat pregatirea noului plan si a executiei; nu a autorizat prin aceasta migrarea datelor reale, lansarea sau costuri externe.

Sursa curenta: `EXECUTION_PLAN_2026-09-26.md` si planul client v1.2 din 26 septembrie 2026. Notele de mai jos raman istoric; nu prevaleaza asupra acestei decizii. Autorizarea curenta nu include commit/push/deploy, schimbari de secrete, baze de date sau lansarea agentilor externi. Cerintele noi sunt planificate, nu implementate prin actualizarea documentelor.

## Istoric pastrat

Source: Catalin provided the older Emergent roadmap again on 2026-07-03 and clarified the business rule: ProDelivery is paid by phases. Codex must not move the project into a later phase until Catalin explicitly says to do so.

## Business Rule

- Catalin controls phase transitions.
- Current approved commercial phase: Phase 2.
- Do not start Phase 3, Phase 4, or any later phase just because the codebase technically allows it.
- Before suggesting work, map it to the current approved phase.
- If a task belongs to a future phase, pause and ask Catalin for explicit approval.
- Internal engineering stage labels such as quality hardening or release preparation do not replace the client/payment phase roadmap.

## Historical Agent Report Rule

On 2026-07-03 Catalin provided a detailed historical AI-agent report from the older Emergent work context.

Use that report as:

- product intent and client-workflow context
- historical implementation notes
- clues for the next audit
- warnings about things that were important to the client

Do not use that report as:

- guaranteed current code truth
- proof that a feature is still implemented correctly
- approval to restart from the beginning
- approval to enter Phase 3 or later

Before treating any claim from that report as current, Codex must verify it against the active ProDelivery codebase and live preview/tests when practical.

## Official Commercial Phases

Catalin confirmed on 2026-07-03 that the following list is the official commercial phase roadmap from the beginning of the ProDelivery project. This list overrides older agent/report labels when deciding paid scope.

### Phase 2 - Panou pentru restaurante

Objective: restaurantul vede comenzile si marcheaza cand sunt gata de ridicat.

Current status: current approved phase. Treat this as the active scope until Catalin explicitly approves Phase 3.

In scope:

- restaurant order panel
- restaurant sees active orders
- restaurant accepts/manages preparation
- restaurant marks orders ready for pickup
- basic reliability around loading/error/duplicate clicks for this workflow
- adjacent restaurant operational states only where they support the restaurant panel handoff

Not in scope unless Catalin explicitly approves:

- real GPS live tracking
- automatic closest-driver allocation
- native mobile app
- full advanced reporting

### Phase 3 - GPS live pe harta

Objective: se vede in timp real cum se misca livratorii pe harta.

Status: future paid phase, not approved yet.

Notes:

- Any existing map/demo/simulated movement must not be counted as completed Phase 3.
- Real Phase 3 requires actual driver location flow, freshness/offline state, and admin map behavior that reflects real data.

### Phase 4 - Alocare automata

Objective: sistemul alege singur cel mai apropiat livrator, fara interventie manuala.

Status: future paid phase, not approved yet.

Notes:

- Manual assignment or UI toggles do not complete this phase.
- Real Phase 4 needs distance/location logic, eligible driver filtering, conflict handling, and clear override rules.

### Phase 5 - Notificari cu sunet

Objective: livratorii primesc alerta sonora instant cand au comanda noua.

Status: future paid phase, not approved yet.

Notes:

- Polling/demo sounds are not enough for a production-ready interpretation unless Catalin/client accepts that scope.
- Real Phase 5 needs reliable notification behavior, permission handling, fallback states, and duplicate-alert control.

### Phase 6 - Rapoarte complete

Objective: statistici: comenzi pe zi, kilometri parcursi, incasari per livrator.

Status: future paid phase, not approved yet.

Notes:

- Basic dashboard stats do not complete this phase.
- Full phase scope needs report filters, persisted data correctness, and driver-level km/revenue calculations.

### Phase 7 - Aplicatie mobila nativa

Objective: publicare in Google Play si App Store.

Status: future paid phase, not approved yet.

Notes:

- Current web/PWA-like screens do not count as native mobile release.
- Real Phase 7 requires mobile architecture, packaging, store assets, and store submission readiness.

### Phase 8 - Lansare si suport

Objective: testare finala, optimizare, lansare oficiala.

Status: future paid phase, not approved yet.

Notes:

- Release readiness tasks can support Phase 2, but official launch/support is Phase 8 unless Catalin says otherwise.

## Engineering Support vs Commercial Phases

- Code quality, test hardening, preview reliability, security fixes, and production-readiness checks are engineering support tasks.
- They do not become a new commercial phase by themselves.
- They can be done inside Phase 2 only when they are needed to safely close or present the Phase 2 restaurant-panel workflow.
- Admin Settings real is not listed as an official commercial phase item. Treat it as an operational/change-request item that needs Catalin's scope approval before implementation.

## Current Interpretation

- Current approved commercial phase: Phase 2 - Panou pentru restaurante.
- Do not start Phase 3 GPS live, Phase 4 automatic allocation, Phase 5 sound notifications, Phase 6 full reports, Phase 7 native app, or Phase 8 launch/support until Catalin explicitly approves that phase transition.
- Some future-phase UI/code may already exist partially or as demo/simulation. Existing partial code does not mean the commercial phase is approved or complete.
- When labels conflict, Catalin's latest confirmed phase list wins.

## Detailed Commercial Phase Breakdown

### Phase 2 Detailed Scope - Restaurant Panel

Goal: restaurant staff can operate incoming orders clearly and mark them ready for pickup.

Must have:

- restaurant login and role-safe access
- active order queue for the logged-in restaurant only
- clear separation between new, preparing/in progress, ready, delivered/history, and problem orders where already supported
- order cards with customer name, phone, address, source, products/notes, totals, and operational status
- accept/preparation flow where the existing workflow supports it
- preparation time selection and timer display where available
- mark order ready for pickup
- refresh-safe state after page reload
- duplicate-click protection for accept/preparing/ready/problem actions
- clear loading, disabled, empty, and error states
- restaurant pause / close-day only as adjacent support for not receiving new orders, not as a new future feature
- backend role checks so a restaurant cannot see or modify another restaurant's orders
- audit/log trail for important status changes

Acceptance:

- a real restaurant user can complete the order-ready workflow without admin help
- double-clicks do not create wrong transitions or duplicate requests
- refresh does not lose the current status
- backend refuses invalid status transitions and cross-restaurant access
- Phase 2 demo/client review does not promise GPS, automatic allocation, native app, or full reports

Not included:

- real live GPS
- automatic closest-driver allocation
- marketplace/POS API integrations
- advanced reports
- native app store release
- final production launch/support package

### Phase 3 Detailed Scope - GPS Live On Map

Goal: admin/dispatcher sees real driver movement on the map.

Must have:

- driver location permission flow
- driver app sends real latitude/longitude while active or in delivery
- backend endpoint/storage for latest driver location
- timestamp for last known location
- stale/offline state when location is old or missing
- admin map uses real backend location, not random/simulated movement
- privacy and battery-aware update interval
- error handling for denied GPS permission, no internet, background limitations, and invalid coordinates
- audit/debug logs for location updates without exposing sensitive location unnecessarily

Acceptance:

- active drivers appear on the map from real location data
- stale drivers are visibly marked
- offline/no-permission drivers do not look live
- simulation/demo movement is removed or clearly restricted to local demo mode

### Phase 4 Detailed Scope - Automatic Allocation

Goal: system chooses the best/closest available driver without manual dispatcher work.

Must have:

- eligible driver filtering by status, active shift, pause/offline, current order, disabled account, and vehicle/type if needed
- distance calculation from driver to restaurant/customer as agreed
- rule for nearest/best driver selection
- conflict protection when multiple orders or admins trigger allocation at the same time
- idempotency so repeated allocation requests do not assign twice
- manual override/reassign by admin
- clear reason when no driver is available
- audit trail showing who/what assigned the order and why

Acceptance:

- two simultaneous allocation attempts cannot corrupt assignment
- unavailable drivers are never selected
- admin can see and override the decision
- allocation can be explained to the client/operator

### Phase 5 Detailed Scope - Sound Notifications

Goal: drivers receive an instant audible alert when a new order is assigned or available according to the agreed workflow.

Must have:

- notification trigger definition: assigned order vs available order
- sound alert in driver app
- permission handling for browser/mobile sound restrictions
- visual fallback when sound cannot play
- duplicate-alert protection
- offline/reconnect behavior
- clear unread/new-order state
- retry/re-poll or push strategy depending on approved tech

Acceptance:

- driver gets a clear alert for a new relevant order
- repeated backend events do not spam sounds
- app recovers after reconnect and does not miss the current active order
- sound behavior is tested on target devices/browsers

### Phase 6 Detailed Scope - Complete Reports

Goal: admin/client can inspect operational performance.

Must have:

- orders per day/week/month
- completed/cancelled/problem orders
- average preparation time
- average delivery time
- driver performance
- kilometers per driver if GPS/distance data exists
- revenue/earnings per driver according to agreed calculation
- filters by date, restaurant, driver, source, status
- export if approved: CSV/PDF
- data correctness rules for manual orders, problem orders, reassigned orders, and marketplace-sourced orders if integrations exist

Acceptance:

- reports match backend order data
- totals are explainable
- filters do not expose data to wrong roles
- reports do not count demo/simulated orders as real production data

### Phase 7 Detailed Scope - Native Mobile App

Goal: publish a native mobile app in Google Play and App Store.

Must have:

- decision: driver-only app, restaurant app, or both
- native/hybrid stack decision
- login/session handling
- order flow parity with web where required
- mobile notifications
- background GPS if Phase 3/driver app requires it
- app icons, splash screens, store metadata, privacy policy links
- Android build and signing
- iOS build and signing
- test builds before store submission

Acceptance:

- app installs on real devices
- core flows work without relying on desktop browser behavior
- app passes store-readiness checks and privacy expectations

### Phase 8 Detailed Scope - Launch And Support

Goal: final testing, optimization, official launch, and support process.

Must have:

- production environment decision
- domain/DNS/SSL/deployment setup
- production secrets configured outside repository
- database backup/restore plan
- monitoring/logging/error visibility
- security review
- performance check
- smoke test checklist
- rollback plan
- support contact/process
- handoff notes for Catalin/client

Acceptance:

- production deployment is repeatable
- critical flows pass final QA
- known risks are documented
- Catalin approves launch/support risk

## Integration Scope Not Yet Placed Commercially

Historical context: `memory/PRD.md` mentions "Phase 5: Integrari externe (Glovo/Wolt/Bolt API)", but Catalin's latest official phase list says Phase 5 is "Notificari cu sunet". Therefore external marketplace/POS integrations are not currently assigned to an approved commercial phase.

Current code evidence:

- The app supports order source labels such as Site, Glovo, Wolt, Bolt.
- There is no verified real Glovo/Wolt/Bolt connector module in the current code.
- Source labels must be treated as manual/demo metadata until real provider access and connector code exist.

Recommended commercial handling:

- Keep Phase 2 unchanged.
- Do not include real Glovo/Wolt/Bolt/POS API integration in Phase 2.
- Add a separate future paid scope: Marketplace/POS API Integrations.
- Catalin must decide whether this becomes Phase 6B, a new Phase 7 that shifts later phases, or a post-launch add-on.

Integration scope would include:

- partner/API access for Glovo, Wolt, Bolt, and/or restaurant POS systems
- credentials and webhook/signature setup
- external order ingestion
- external order id/source/store mapping
- idempotency and duplicate protection
- status mapping between provider statuses and ProDelivery statuses
- cancellation/refund/problem-order mapping
- retry/backoff/dead-letter handling
- raw payload audit storage
- reconciliation job for missed/late events
- operational failure dashboard
- clear decision whether ProDelivery is system of record or mirror/dispatcher only

Integration risks:

- provider APIs may require commercial approval and may not be public
- each provider can expose different order/status/menu capabilities
- provider contracts may limit automation, customer data use, retention, or status updates
- webhook events can arrive late, duplicated, or out of order
- menu/catalog sync is a separate large feature if requested

## Next Required Action Before Implementation

Before implementing new roadmap work, Codex should audit Phase 2 only:

- what is already implemented for the restaurant panel
- what remains to close the restaurant order-ready workflow
- what is only adjacent support for Phase 2
- what must be blocked because it belongs to Phase 3 or later
