# Etapa 1 - matrice cerinta/cod/test si gate-uri

Data: 2026-10-02. Plan operational suplimentar 10.000 EUR, 10 etape. Nu este audit exhaustiv sau acceptanta de productie.

## Probe executate in acest increment

- `run_unit_baseline.py`: 18 passed in 4.58s. Importurile folosesc database stub, dotenv dezactivat si blocare socket pentru DB/exterior; numai socketpair local efemer pentru asyncio. Rezultat nou `unit-baseline-final.xml` in staging, apoi publicat in QA_RUNS.
- Acopera `backend/tests/test_order_hardening_unit.py` (9 teste) si `backend/tests/test_order_critical_flows.py` (9 teste). Acestea verifica reguli si FakeDb, nu concurenta Mongo.
- GET `http://127.0.0.1:3000/login` si `http://127.0.0.1:8000/api/`: HTTP 200. Nu am folosit endpointuri mutante, seed, login demo sau date client.
- Agent Hub read-only: task `PD-HUB-001`, status ready; eticheta comerciala istorica. Nu am modificat Hub, sursa activa ramane planul din 26 septembrie.

## Matrice focalizata

Fisierele UI sunt sub `frontend/src`; serverul sub `backend`. Testul complet FakeDb este `test_complete_order_delivery_flow_records_real_state_changes`; testul repetarilor este `test_duplicate_order_actions_are_idempotent_and_do_not_rewrite_flow`.

| Cerinta | Cod/owner de date actual | Dovada existenta executata acum | Lipsa/risc pentru noul plan |
| --- | --- | --- | --- |
| Creare manuala comanda | `routers/orders.py:360`, `models/order.py`, admin/restaurant propriu | Validare extra-forbid; creare in flux complet FakeDb | Idempotenta durabila si race cu pauza necesita integrare reala |
| Restaurant accepta/seteaza pregatire | `routers/orders.py:519`, RestaurantApp; rol admin/restaurant propriu | Flux complet, bounds 1..240, repeat preparing | Preparing nu se poate modifica dupa ASSIGNED; politica ajustare estimare separata |
| Marcheaza gata | `routers/orders.py:643`, RestaurantApp | Flux complet si repeat ready | Nu functioneaza concomitent cu assignment in actualul enum; timerul nu confirma gata |
| Admin aloca/realoca | `routers/orders.py:421`, AdminDashboard | Flux complet si repetare aceleiasi asignari | O singura comanda; tranzactie multi-document si race realocare neprobate |
| Driver accepta | `routers/orders.py:705`, DriverApp | Flux complet si duplicate status | Assignment identity/lease/version lipsesc; ecran singular |
| Ridica | `routers/orders.py:31`, `:705` | Tranzitie ACCEPTED -> PICKED_UP; jump invalid respins | Guard separat ready + oprire curenta necesar; readiness nu este verificata independent |
| Livreaza | `routers/orders.py:308`, `:705` | Flux complet; efecte FakeDb, repetari | Eliberare driver singulara, crash intre order update si finalizare; nu dovada de exact-once |
| Anuleaza | `routers/orders.py:268`, `:287`, DriverApp | Motiv obligatoriu si tranzitii controlate | CANCELLED intra in feed activ; dupa pickup cere incident, nu eliberare simpla |
| Refacere partiala | `routers/orders.py:590`, RestaurantApp | Legatura originala, DELIVERED required, restaurant closed, duplicate serial | Insert followup + marker original separate; doua cereri simultane neprobate |
| Pauza/iesire din pauza | `routers/restaurants.py:249`, RestaurantApp | Persistare FakeDb si blocare create in pauza | Browser/revenire automata si create vs pause concurent neprobate |
| Inchidere zi | `routers/restaurants.py:249` | Inchidere, blocare create, midnight Bucuresti | Zi operationala live/DST/device si continuitate comenzi active end-to-end neprobate |
| Roluri/ownership | `orders.py:177`, `:196`, `:207`, `:216`; auth existent | Reguli citite; nu am rulat suita API de securitate in acest increment | `test_security_authorization.py` exista, necesita mediu izolat/autorizat; nu folosim istoricul drept dovada noua |
| Loading/offline/refresh | `DriverApp.jsx:107`, `:352`; utilitare API existente | Cod citit, nu click-through autentificat actual | False success, offline/resync/conflict si double click end-to-end de verificat |
| Lista/asignari multiple | `models/driver.py:33`, `orders.py:450`, `DriverApp.jsx:177`, `AdminDashboard.jsx:734` | Restrictia singulara confirmata in cod | PD-DISPATCH-01 necesar; nu doar redenumire camp |
| GPS/harta | `drivers.py:671`, `components/admin/LiveMapPanel.jsx:147` | Campuri/consumator citite; fara probe fizice | Timestamp/accuracy GPS, stale data, background, harta rutata reala nevalidate |
| OCR + un conector API | Specificatie plan; provider initial neidentificat | Blocker documentat; nicio integrare probata | Date restaurant/provider/documentatie/acces; nu blocker pentru spec dispatch |

Nu deducem ca toate cele 18 teste garanteaza fiecare cerinta; coloana descrie exact suprafata verificata. Niciun test de baza simulata nu este benchmark 50 restaurante/100 driveri sau audit de securitate complet.

## Statusul Etapei 1

- Inventar focalizat si baseline: facute, cu limitari explicite.
- Spec multi-comanda: document de lucru nou, in review independent; activarea nu este autorizata prin document.
- Solver: proba izolata in curs; rezultatele finale apar separat in raportul probei.
- Concurenta Mongo reala: neexecutata; mediu separat/topologie si fault injection de pregatit.
- Android/iOS fizic GPS/push/fundal: neexecutat; framework/dispozitive de stabilit pentru proba.
- Conector: blocker explicit, detaliile furnizorului se pot completa ulterior.
- Production readiness completa: NU demonstrata. Etapa 1 nu se inchide numai pentru ca lint, HTTP sau proba solver trec.

## Urmatoarele pachete, fara a le activa automat

1. PD-CORE-CANCELLED-01: fix ingust feed driver/backend + selectie frontend + regresii; istoric pastrat.
2. PD-CORE-PREP-DISPATCH-01: teste reproductibile pregatire/ready dupa asignare; fix incremental al contractului comun, nu relaxarea tranzitiilor.
3. PD-DISPATCH-CONCURRENCY-PROBE: mediu sintetic separat aprobat, ultimul slot, ownership, replay, crash, transfer, celelalte noua intacte.
4. PD-MOBILE-FEASIBILITY: proba fizica Android/iOS; nu promitem functionare GPS fundal din browser.

Primele doua sunt engineering support pentru fluxurile existente si se trateaza cu scope/review/QA separat. Ultimele sunt probe timpurii ale Etapei 1, nu lansari reale ale etapelor viitoare.
