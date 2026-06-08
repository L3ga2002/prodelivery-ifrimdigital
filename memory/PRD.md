# ProDelivery Bacău - PRD

## Problem Statement
Platformă de management livrări și ride-sharing pentru zona Bacău, România. Proiect dezvoltat în faze pe 7-8 luni, buget total €20,000.

## Roluri Utilizatori
- **Admin**: Dashboard, management, analytics, program control (10-02), sloturi urgență (10-22), zone de livrare
- **Șofer**: Comenzi, program 10-22, sloturi urgență disponibile, actualizare status
- **Restaurant**: Gestionare comenzi, confirmare "gata", anulare cu motiv

## Arhitectură
```
/app/backend/ → server.py, database.py, auth.py
  models/ → user, driver, restaurant, order, schedule, emergency_slot, delivery_zone
  routers/ → auth, drivers, restaurants, orders, stats, seed, schedules, emergency_slots, zones
```

## Reguli Program
- **Livratori**: selectează 10:00-22:00 | **Admin**: controlează 10:00-02:00
- **Fereastră**: Duminică 22:00 → Luni 10:00
- **Urgență**: doar 10:00-22:00, admin setează locuri, livratorii fără program iau
- **Format**: intervale "10-11", "11-12" etc.
- **Viitor**: ranking → prioritate calendar + algoritm automat urgență

## Credențiale

Credențialele demo locale sunt definite în fișiere `.env` ignorate de git. Nu salva parole reale sau credentiale de producție în repository.

## Implementat
- Phase 1: MVP, branding, hartă, demo
- Phase 2: Backend modular, program șoferi, confirmări, analytics fără financiar, urgență
- Task 2.2: Zone de livrare geospațiale (Leaflet/OSM, poligoane pe hartă, CRUD zone, detecție automată zonă, taxe livrare) - COMPLETAT 26 Mar 2026
- Task 2.2.1: Sectoare livrare Bacău (Nord, Centru, Sud, Nord Extrem) cu 3 niveluri fixe per sector - IMPLEMENTAT 25 Apr 2026
- Admin poate acum filtra pe sector, redesena conturul unei zone, adăuga zone noi manual și folosește tarifare fixă per nivel: Zona 1 = 14 lei, Zona 2 = 22 lei, Zona 3 = 33 lei
- Seed demo creează 12 zone (4 sectoare × 3 zone) ca primă aproximare editabilă pe baza hărților primite de la user
- Refinement 25 Apr 2026: am rafinat manual poligoanele seed pentru cele 4 sectoare și am schimbat afișarea hărții astfel încât în modul "Toate" se văd doar contururile exterioare, iar pe filtru de sector se văd toate cele 3 zone pentru sectorul ales
- Flux comenzi 25 Apr 2026: creare comandă admin cu locație selectată pe hartă, detectare automată zonă/sector/nivel și calcul automat taxă + total final în backend și frontend
- Task 2.3: Ranking livratori + acces etapizat la calendar - IMPLEMENTAT 25 Apr 2026 (tier-uri Gold / Silver / Bronze / Start, scor calculat din livrări + anulări + punctualitate + senioritate, ferestre separate de acces la calendar)
- Task 2.4: Auto-generator sloturi de urgență - IMPLEMENTAT 25 Apr 2026 (buton admin + algoritm pe ore de vârf, sloturi marcate AUTO/system)
- UI/UX 25 Apr 2026: Adăugat sistem light/dark theme cu toggle vizibil pe Login, Admin, Driver și Restaurant, cu persistență locală și ajustări de contrast pentru dark mode
- Security/Quality 25 Apr 2026: migrare auth frontend/backend pe cookie-uri httpOnly + refresh/logout, fallback Bearer păstrat pentru compatibilitate, demo/test credentials mutate în variabile de mediu, curățare console logs, chei React stabilizate, helper comun pentru testele backend și refactor helper în `schedules.py` + `emergency_slots.py`
- Security/Quality 25 Apr 2026 (batch 2): refactor helper în `zones.py` + `orders.py`, `seed.py` mutat pe `secrets.SystemRandom()`, memoizare pentru calculele grele din `DeliveryZonesManager` și `DriverSchedule`, validare completă frontend/backend după batch-ul mare
- Production hardening 25 Apr 2026: cookie-urile auth trec pe `secure + SameSite=None` pe HTTPS, iar `CORS_ORIGINS` include și `prodeliverybacau.com` / `www.prodeliverybacau.com`; preview validat fără regresii după patch
- Phase 2 Rework P0 07 Mai 2026: restaurantele au acum locație individuală cu autocomplete/geocoding gratuit OpenStreetMap/Nominatim prin backend proxy, hartă care se centrează pe restaurant și marker automat
- Phase 2 Rework P0 07 Mai 2026: zonele de livrare sunt gestionate individual per restaurant; zonele globale vechi Zona 1/2/3 au fost eliminate din workflow și seed-ul demo creează doar zone per restaurant
- Phase 2 Rework P0 07 Mai 2026: tab-ul Restaurante include managerul de arii de livrare pentru restaurantul selectat, cu desenare UX nouă, auto-închidere poligon când se apasă primul punct, nume zonă, preț livrare, culoare, activ/inactiv și undo prin buton / Ctrl
- Phase 2 Rework P0 07 Mai 2026: harta live principală nu mai afișează poligoane de livrare; rămâne concentrată pe livratori și restaurante
- Phase 2 Rework P0 07 Mai 2026: backend-ul detectează zona doar în contextul restaurantului selectat și expune `/api/restaurants/available` pentru filtrarea internă a restaurantelor disponibile după coordonate
- Phase 2 Rework P1 07 Mai 2026: UX desenare zone modificat conform cerinței userului — tasta `Ctrl` șterge ultimul punct/ultima linie, nu Backspace/C
- Phase 2 Rework P1 07 Mai 2026: Restaurant App afișează timer live după selectarea timpului de preparare; timerul numără invers, devine întârziere după expirare, redă alertă sonoră scurtă și păstrează butonul „Comanda gata” sub timer
- Phase 2 Rework P1 07 Mai 2026: backend-ul salvează timp estimat, start, deadline, timp real și întârziere pentru prepararea comenzilor (`preparation_*` fields)
- Phase 2 Rework P1 07 Mai 2026: Admin Restaurants include analytics detaliat per restaurant cu KPI-uri, grafice pe ore/luni și istoric comenzi cu timpi de preparare/livrare
- Phase 2 Rework P1 07 Mai 2026: Program/Sloturi reorganizat în jurul sloturilor normale; există modal setup pentru generare automată cu zile, interval, număr sloturi, tip normal/urgență și repetare
- Phase 2 Rework P1 07 Mai 2026: backend-ul include generare automată sloturi normale, ștergere bulk a sloturilor automate și generare setup pentru sloturi de urgență
- Phase 2 Design Polish 07 Mai 2026: roșul agresiv a fost redus; UI-ul folosește mai mult slate/navy/amber pentru un look de dispecerat logistic, păstrând roșu doar pentru alerte/întârzieri/acțiuni distructive
- Phase 2 UX/Design Polish 07 Mai 2026: la adăugare restaurant, după autocomplete/geocoding, pinul de pe hartă poate fi ajustat manual prin drag sau click pe hartă; coordonatele lat/lng se actualizează înainte de salvare
- Phase 2 UX/Design Polish 07 Mai 2026: Admin Dashboard are hero premium „Control Room · Bacău” și KPI cards redesenate pentru o prezentare mai solidă în fața clientului
- Phase 2 Analytics Polish 07 Mai 2026: analytics restaurant extins în UI cu grafice vizibile pe ore, zile, săptămâni, luni, ani + card de insight operațional
- Phase 2 Program Polish 07 Mai 2026: adăugat endpoint și UI pentru ștergere bulk sloturi de urgență generate conform setup-ului; curăță și intrările de urgență din programele livratorilor
- Phase 2 UX Bugfix 07 Mai 2026: schimbarea între restaurante în tab-ul Restaurante nu mai demontează/înlocuiește agresiv panoul analytics; datele rămân afișate și se actualizează discret, fără refresh vizual/jump urât
- Phase 2 Design Pass 07 Mai 2026: aplicat polish A+B+C+D cerut de user — tab Restaurante cu carduri premium și selector stabil, Program/Sloturi cu contrast indigo/amber mai curat, Comenzi/Admin cu control surface și tabel mai profesional, Restaurant App cu hero „Kitchen Queue”, stat tiles și timer mare premium
- Phase 2 Map Polish 07 Mai 2026: harta principală folosește iconițe operaționale custom 3D/SVG — livratori pe scuter și restaurante storefront, cu legendă dedicată și fără poligoane de zone pe harta live
- Phase 2 UX Cleanup 07 Mai 2026: butonul și modalul „Tur Client” au fost eliminate la cererea userului
- Phase 2 Refactor 07 Mai 2026: extras harta live în `components/admin/LiveMapPanel.jsx`, iconițele/Leaflet setup în `components/admin/MapMarkerIcons.jsx` și hero/KPI/action buttons în `components/admin/AdminCommandCenter.jsx`, reducând riscul pentru modificări înainte de redeploy
- Phase 2 Map Status Polish 07 Mai 2026: marker-ele livratorilor au status vizual disponibil/ocupat/offline cu culori și mini-badge; popup-urile de hartă au fost redesenate cu informații clare pentru livrator/restaurant
- Code Review Fix Pass 07 Mai 2026: eliminat `dangerouslySetInnerHTML` din frontend; legenda hărții folosește SVG React safe, iar marker-ele Leaflet sanitizează id/aria înainte de HTML static intern
- Code Review Fix Pass 07 Mai 2026: reparate hook/catch issues principale în `RestaurantApp`, `DriverApp`, `AdminDashboard`; empty catches au log/debug/toast, iar timpii magici principali au fost extrași în constante
- Code Review Fix Pass 07 Mai 2026: extras `OrdersTab` și `RestaurantAnalyticsPanel` din `AdminDashboard`, pe lângă modulele deja extrase pentru hartă și command center
- Code Review Fix Pass 07 Mai 2026: refactor backend pentru `emergency_slots.bulk_delete_emergency_slots` și `restaurants.get_restaurant_analytics` în helper functions; `server.py` are return type hints de bază
- Code Review Fix Pass 07 Mai 2026: `DriverSchedule` a fost refăcut din table tags în CSS grid cu roluri ARIA, eliminând warning-urile DOM nesting/hydration din Driver App
- Code Review Fix Pass 10 Mai 2026: aplicat al doilea val de review — ThemeContext nu mai folosește `localStorage` (sessionStorage pentru preferință temă), `RestaurantApp`/`DriverApp` au catch-uri logate și constante pentru timing, iar callback-urile principale au dependențe stabilizate
- Code Review Fix Pass 10 Mai 2026: memoizate obiecte/array-uri inline în hartă, preview restaurant, zone polygons și analytics pentru a reduce rerender-uri inutile
- Code Review Fix Pass 10 Mai 2026: `AdminDashboard` a fost redus suplimentar prin extragerea `OrdersTab` și `RestaurantAnalyticsPanel`; `AdminCommandCenter`, `LiveMapPanel` și `MapMarkerIcons` rămân module separate
- Code Review Fix Pass 10 Mai 2026: backend refactor suplimentar — `schedules.auto_generate_normal_slots`, `zones.build_zone_update_payload` și `seed.seed_data` au fost sparte în helper functions mai mici
- Code Review Validation 10 Mai 2026: testing agent iteration 20 PASS 100% backend/frontend; static checks confirmă fără `dangerouslySetInnerHTML`, fără `localStorage`, fără identity comparisons evidente, fără warnings DriverSchedule DOM nesting
- Code Review Completion Pass 10 Mai 2026: după feedback user, au fost închise și resturile de maintainability: `RestaurantsTab`, `SettingsTab` și `DeliveryZoneMapParts` extrase; `DeliveryZonesManager` este mai mic și logica de hartă/desenare/poligoane este separată
- Code Review Completion Pass 10 Mai 2026: `SettingsTab` are `data-testid` pe controls, iar iteration 21 PASS confirmă Admin/Restaurant/Driver, seed, analytics, schedules, zones update, static checks și lipsa runtime errors după login
- Phase 2 Demo Data Cleanup 07 Mai 2026: curățat restaurant test non-demo din baza preview; demo-ul afișează 5 restaurante curate
- Operations UX Patch 10 Mai 2026: modalul „Alocă comandă” a fost refăcut cu layering peste overlay, search live/debounce pentru livratori și selecție comandă+livrator într-un singur flow.
- Operations UX Patch 10 Mai 2026: harta live are restaurante mai mici, statusuri livratori „Activ / În pauză / Offline / În livrare”, iconițe scuter/mașină, popup livrator fără coordonate și buton „Alocă comandă”, plus trasee dashed livrator→restaurant→client pentru comenzile active.
- Operations UX Patch 10 Mai 2026: butonul „Adaugă livrator” a fost mutat în tabul Livratori, iar „Adaugă restaurant” în tabul Restaurante; demo-ul și „Comandă nouă” rămân active în command center.
- Operations UX Patch 10 Mai 2026: adăugarea livratorilor include vehicul scuter/mașină și integrare Resend pentru cod verificare email; în preview, senderul `onboarding@resend.dev` este limitat de Resend până la verificarea domeniului.
- Resend Restriction Fix 10 Mai 2026: dacă Resend returnează 403 pentru `onboarding@resend.dev` către destinatari externi, aplicația nu mai eșuează flow-ul; creează livratorul, păstrează hash-ul codului în DB și afișează adminului un cod local temporar pentru verificare în preview. Emailul real rămâne activ automat după verificarea domeniului și schimbarea senderului.
- Resend Domain Activation 10 Mai 2026: domeniul `prodeliverybacau.com` este verificat în Resend, iar aplicația folosește acum `verificare@prodeliverybacau.com` ca sender real; testul backend a returnat `email_delivery.status=sent` și `email_id` valid.
- Admin Program Visibility Patch 10 Mai 2026: calendarul rapid afișează acum explicit sloturile standard create, împărțirea Admin/Livrator și sloturile de urgență cu ocupate/total/libere direct în celule, plus sumar săptămânal de sloturi.
- Admin Driver Management Patch 10 Mai 2026: cardurile de livratori sunt clickabile și deschid dialog de gestiune; adminul poate seta scor manual 0-100 pentru rank, adăuga notă internă, reveni la scor automat și șterge livratorul din DB cu confirmare `STERGE`.
- Admin Driver Management Patch 10 Mai 2026: backend-ul include `PATCH /api/drivers/{driver_id}/ranking` și `DELETE /api/drivers/{driver_id}?confirm_delete=true`; ștergerea este blocată dacă livratorul are comenzi active și curăță userul, programările și claim-urile de urgență.
- Live Map Demo Routes Patch 10 Mai 2026: seed-ul și baza preview conțin acum 3 comenzi active `LIVE.101-103`, legate de 3 livratori în livrare; două profiluri demo sunt setate pe vehicul `car`, astfel încât clientul vede trasee dashed și diferența scuter/mașină direct pe hartă.
- Operations UX Patch 10 Mai 2026: Programul admin are calendar rapid permanent 10:00-02:00, sloturi standard verzi, sloturi urgență roșii, confirmare pentru intervale de noapte și flow „Refă sloturile săptămânii trecute” cu preview.
- Operations UX Patch 10 Mai 2026: zonele de livrare create sunt blocate implicit; editarea/ștergerea cer confirmare explicită `CONFIRM`, iar backend-ul refuză modificările fără confirmare.
- Operations UX Patch 10 Mai 2026: Driver App are notificare profesională „Urmează să primești o comandă”, card verificare email pentru livratori neverificați și dialog explicativ pentru scor/rank.
- Security Patch 10 Mai 2026: login-ul are brute-force lockout după 5 încercări eșuate, iar backend-ul returnează CORS explicit intern; preflight-ul extern din ingress încă răspunde wildcard la OPTIONS înainte de backend.
- Phase 2 Advanced Driver Ops 16 Mai 2026: statusurile livratorilor au fost refăcute în `Activ / În livrare / În pauză / Offline`; pauza păstrează livratorul vizibil pe hartă cu timer countdown, iar offline este ascuns de pe harta live.
- Phase 2 Advanced Driver Ops 16 Mai 2026: adminul are dashboard individual complet de livrator cu profil, status operațional, rank manual, calendar vizual, avatar, istoric comenzi și audit securitate.
- Phase 2 Advanced Driver Ops 16 Mai 2026: adminul poate modifica nume/telefon/email și poate seta/resetă manual parola livratorului; acțiunile sunt validate și logate în `audit_logs`.
- Phase 2 Advanced Driver Ops 16 Mai 2026: calendarul individual al livratorului are grilă vizuală verde/roșu/gri, quick edit `-5…+5`, sloturi forțate permise cu warning de supraîncărcare și salvare prin flow admin.
- Phase 2 Avatar Workflow 16 Mai 2026: adăugat upload avatar cu galerie/selfie, crop client-side, limită 4MB, compresie server-side WebP și stocare pe server; upload-ul livratorului intră `pending`, adminul aprobă/respinge, iar upload-ul adminului devine activ automat.
- Phase 2 Driver App UX 16 Mai 2026: aplicația livratorului include card profil/status cu direcție vizuală orange/gri, setare rapidă Activ/Pauză/Offline și upload poză profil trimis spre aprobare.
- Phase 2 Orders Source Fix 16 Mai 2026: tabelul de comenzi afișează sursa completă `Site / Bolt / Wolt / Glovo`, nu doar prescurtările `S/B/W/G`.
- Validation 16 Mai 2026: lint frontend/backend PASS; self-test API PASS pentru login, driver dashboard, status pauză, blocare pauză/offline în livrare, avatar admin, avatar driver pending/aprobare; smoke Playwright PASS pentru Admin Drivers dialog și Orders source labels. Testing Agent iteration 24: 13/14 backend PASS + frontend major flows PASS; singurul fail rămas este preflight CORS extern interceptat la ingress.
- Program UX Fix 16 Mai 2026: quick edit `-3/-2/-1/+1/+2/+3` a fost mutat în calendarul principal de Program, pe fiecare celulă de zi/oră; inputul numeric și flow-ul vechi de selectare/creare au fost eliminate din zona rapidă.
- Program UX Fix 16 Mai 2026: bugul de scos sloturi a fost reparat prin endpoint backend `POST /api/schedules/admin/quick-adjust`, care adaugă/scade sloturi standard sau urgență pe celula exactă; la scădere standard se șterg întâi sloturile admin/auto ca să nu dispară accidental orele alese manual de livratori.
- Program UX Fix 16 Mai 2026: dialogul simplu deschis din cardul unui livrator în tabul Program a fost simplificat vizual: total ore, ore livrator, ore admin, celule mari Verde/Gri/Roșu și quick edit pe zi `-3…+3` pentru adăugare/scoatere rapidă.
- Validation 16 Mai 2026 Program UX Fix: backend quick-adjust testat cu curl pentru `+1/-1` standard și `+2/-2` urgență; Playwright smoke PASS pentru deschiderea quick dialog din calendar, click `+1` și `-1`, plus dialog program simplu livrator; lint frontend/backend PASS.
- Program UX Clarification 16 Mai 2026: în dialogul rapid a fost adăugat câmp manual unde adminul poate scrie numărul de sloturi de adăugat/scăzut; quick-adjust acceptă acum valori manuale până la 100. Sloturile standard rămân ore atribuite livratorilor existenți, deci nu pot depăși numărul de livratori disponibili fără program pe ora respectivă; sloturile de urgență sunt capacitate liberă și pot fi crescute independent.
- Validation 16 Mai 2026 Manual Quick Input: testat cu curl `delta=12` standard, sistemul a adăugat doar câți livratori reali erau disponibili și a curățat prin `delta=-added`; Playwright smoke PASS pentru input manual editabil în dialogul rapid; lint frontend/backend PASS.
- Driver App Redesign 16 Mai 2026: aplicația livratorului a fost refăcută mobile-first după imaginile clientului — login alb/gri/orange cu wave-uri, inputuri mari și CTA orange; aplicația post-login este dark/orange cu header vizual, greeting, card comandă curentă, sumar și bottom navigation.
- Driver App Redesign 16 Mai 2026: adăugate rubrici separate `Acasă / Livrare / Calendar / Profil`; `Livrare` conține status operațional + comandă curentă, `Calendar` are sumar compact + editor program existent, iar `Profil` are avatar și date personale.
- Driver Profile 16 Mai 2026: profilul livratorului include nume, prenume, CNP, data nașterii, sex masculin/feminin, email, telefon și avatar; profilul se salvează din aplicația livratorului prin endpoint dedicat.
- Auth/Profile 16 Mai 2026: login-ul acceptă email sau telefon; telefonul are validare de format (`07xxxxxxxx` sau `+407xxxxxxxx`) și rămâne neverificat până la integrarea SMS reală. Emailul păstrează flow-ul existent cu Resend/cod.
- SMS Decision 16 Mai 2026: clientul a ales să amâne codurile SMS reale deoarece furnizorii tip Twilio sunt plătiți; nu există SMS MOCKED, UI-ul explică explicit că SMS se conectează ulterior.
- Validation 16 Mai 2026 Driver App Redesign: self-test curl PASS pentru login email, login telefon, dashboard, PATCH profil cu CNP/telefon/email; Playwright smoke PASS pentru login, Driver App, Profil/Calendar/Livrare tabs. Testing Agent iteration 25: frontend requested flows PASS, backend 10/11 PASS; singurul fail rămas este preflight CORS extern la ingress.
- Admin Responsive Pass 16 Mai 2026: dashboard-ul admin a fost optimizat laptop-first și mobile-safe: container max-width mare pentru laptop, header flexibil, tabs scrollabile pe mobil, tabele protejate de overflow și carduri mobile pentru comenzi active.
- Restaurant App Redesign 16 Mai 2026: aplicația restaurant a fost refăcută ca interfață dark/orange tip `Kitchen Queue`/KDS, cu hero operațional, status restaurant online/pauză, statistici vizuale, carduri comenzi în grid responsive, timer mare și acțiuni clare pentru preparare/gata/anulare.
- Restaurant Status 16 Mai 2026: statusul restaurantului este persistat în backend prin `PATCH /api/restaurants/{restaurant_id}/status`; restaurantele puse pe pauză sunt excluse din disponibilitatea pentru comenzi noi.
- Seed Safety 16 Mai 2026: seed-ul demo păstrează/administrează adminul idempotent prin update/upsert și nu mai șterge userii admin la resetarea demo.
- Validation 16 Mai 2026 Admin/Restaurant: self-test Playwright PASS pe Admin laptop 1920 și mobil 390 fără overflow, Restaurant desktop/mobil fără overflow; curl PASS pentru login restaurant, GET/PATCH status restaurant. Testing Agent iteration 26: toate flow-urile Admin/Restaurant/Driver cerute PASS; singurul fail rămas este CORS preflight extern la ingress.
- Driver Individual Calendar Cleanup 16 Mai 2026: eliminate controalele rapide `-5…+5` din calendarul individual al livratorului din dashboard admin; rămâne doar click direct pe celulele orare pentru adăugare/scoatere și un text scurt explicativ.
- Validation 16 Mai 2026 Driver Calendar Cleanup: lint frontend PASS; Playwright smoke PASS în Admin > Livratori > Dashboard livrator > Calendar, cu `driver-quick-slot-*` count 0 și celule calendar vizibile.
- Phase Curentă Advanced Restaurant/Admin 06 Iun 2026: Restaurant App are acum pauză rapidă 15/20/30/45/60 minute + închidere zi cu timer persistat, program lucru pe zile/ore, filtre Active/În lucru/Livrate/Istoric/Analytics, istoric cu search și analytics propriu accesibil rolului restaurant.
- Phase Curentă Advanced Restaurant/Admin 06 Iun 2026: Restaurant App afișează telefonul clientului pe cardurile de comandă, verifică disponibilitatea livratorilor înainte de timpi scurți de preparare și poate crea comenzi legate pentru probleme de tip produs lipsă/produs nou.
- Phase Curentă Advanced Restaurant/Admin 06 Iun 2026: Admin alocare manuală păstrează comanda selectată inițial în modal; harta live folosește iconițe simple, pin pentru client și trasee mai groase/vizibile, fără eticheta „Offline ascuns”.
- UX Fix 06 Iun 2026: modalul Admin „Alocă comandă” afișează acum lista completă de livratori într-un panou scrollabil; livratorii indisponibili rămân vizibili cu status clar (`Offline`, `În livrare`, `În pauză`) dar nu pot fi selectați, iar comanda aleasă inițial rămâne blocată în partea stângă.
- UX Fix 06 Iun 2026: harta live colorează marker-ele real prin SVG `currentColor`: livratorii activi/restaurantele active sunt verzi, livratorii în livrare albaștri, pauzele portocalii; statusul hărții prioritizează `current_order_id` și `is_active`, ca să apară și scuterele active. Pentru demo preview, `driver-004` a fost setat activ/scuter ca să existe două scutere vizibile. Butoanele avatar `Din galerie` și `Selfie` au contrast mai puternic și sunt vizibile în dialog.
- UX Fix 06 Iun 2026: calendarul rapid dispecerat împarte fiecare celulă orară în două jumătăți vizuale permanente: sus `Standard` verde cu Admin/Liv, jos `Urgență` roșu cu Ocupate/Libere. Celula arată separat chiar și când una dintre categorii este 0, astfel adminul vede simultan normal + urgență în același chenar.
- UX Fix 06 Iun 2026: dialogul individual `Program simplu` al livratorului din Admin > Program nu mai afișează butoanele rapide `-3/-2/-1/+1/+2/+3`. Fiecare chenar orar este acum split în două zone clickabile: `Std` pentru standard/admin/livrator și `Urg` pentru urgență, permițând standard + urgență în aceeași oră fără să arate încărcat.
- UX Fix 06 Iun 2026: Restaurant App nu mai are filtre duplicate sub cardurile de statistici; cardurile `Noi`, `În lucru`, `Livrate` sunt acum filtre directe. `Istoric`, `Analytics`, `Program lucru`, pauză avansată și viitorul `Catalog produse/meniu` au fost mutate în `Mai mult` sus stânga. Problema comandă (`produs lipsă/adaugă produs`) apare doar la comenzile livrate și în detaliul comenzii istorice. Istoricul are dialog mare cu toate detaliile comenzii, iar Analytics folosește dark UI cu culori vizibile.
- UX Fix 06 Iun 2026: calendarul din aplicația livratorului a fost regândit mobile-first. Tabelul orizontal greu de citit a fost înlocuit cu selector pe zile + listă verticală de intervale pentru ziua aleasă, chip-uri compacte pentru `ale tale/admin/urgență`, legendă scurtă și acțiuni mari touch-friendly. Sumarul vechi pe zile a fost eliminat ca să nu dubleze calendarul.
- Bug Fix 06 Iun 2026: statusul livratorului din aplicația Driver nu mai rămâne `Offline` după setarea `Activ`. Backend-ul nu mai condiționează `operational_status=active` de existența unui slot în ora curentă; dacă livratorul setează manual `Activ`, dashboard-ul returnează `Activ` și `is_active=true`. Validat prin API și Playwright mobile.
- Deployment Readiness 06 Iun 2026: Deployment Agent PASS. Ajustări aplicate: `backend/.env` are `CORS_ORIGINS="*"`, backend restartat, `.gitignore` nu mai blochează `.env/.env.*/*.env` necesare deploymentului, dar păstrează ignorate fișierele sensibile `credentials.json/*.pem/*.key/.credentials`. Health check final: no blockers, app ready for deployment.
- Code Review Fixes 06 Iun 2026: au fost aplicate fixurile imediate de calitate: eliminat warning-ul real de hook dependencies din `AuthContext`, eliminate `console.*` din `RestaurantApp`, `DriverApp` și fișierele verificate, înlocuit broad `eslint-disable` din fișierele principale modificate, verificat `seed.py` că folosește `secrets.SystemRandom()` în loc de `random`, verificat backend activ cu lint Python fără undefined variables. Build frontend final compilează cu succes.
- Code Review Fixes Wave 2 06 Iun 2026: eliminate toate `console.*`, `import random/random.*`, broad `/* eslint-disable */`, `is True/is False` din frontend/backend/teste; `stats/hourly` folosește hash deterministic în loc de random; testele folosesc truthy/falsy checks; `seed_data()` a fost spart în helper-e (`clear_demo_collections`, `seed_admin_account`, `seed_driver_accounts`, `seed_restaurant_accounts`, `seed_delivery_zones`); ternarele complexe din `DriverApp`, `AdminDashboard`, `AdminScheduleView` au fost extrase în funcții helper. Verificări: Python compile PASS, Python lint PASS, frontend build PASS, admin smoke PASS.
- Phase Curentă Advanced Restaurant/Admin 06 Iun 2026: Livratorii au soft-disable (`PATCH /api/drivers/{id}/disable`) protejat de comenzi active; calendarul individual permite alegerea sloturilor normale verzi sau urgență roșii; upload avatar acceptă 10MB și comprimă WebP.
- Validation 06 Iun 2026 Phase Curentă: lint frontend/backend PASS; self-test API PASS pentru restaurant pause/schedule/analytics/prep-availability/problem-order și disable guard; Playwright smoke PASS Restaurant filters/history/analytics; Testing Agent iteration 27 backend 100%, frontend 93%, funcționalitățile principale PASS. Rămâne doar CORS preflight extern la Ingress și Admin Settings MOCKED/demo.

## Key API Endpoints - Zone
- `GET /api/zones` - lista toate zonele
- `POST /api/zones` - creează zonă (admin only)
- `PUT /api/zones/{zone_id}` - actualizează zonă (admin only)
- `DELETE /api/zones/{zone_id}` - șterge zonă (admin only)
- `POST /api/zones/detect` - detectează zona pe baza coordonatelor lat/lng
- `GET /api/geocoding/search` - autocomplete/geocoding Nominatim pentru adrese/restaurante în Bacău
- `GET /api/zones?restaurant_id=...` - listează doar zonele unui restaurant
- `POST /api/restaurants/available` - returnează restaurantele care acoperă coordonatele date prin zonele proprii
- `GET /api/restaurants/{restaurant_id}/analytics` - analytics operațional per restaurant
- `PUT /api/orders/{order_id}/preparing` - pornește timerul de preparare și salvează estimarea/deadline-ul
- `PUT /api/orders/{order_id}/ready` - finalizează prepararea și salvează timpul real + întârzierea
- `POST /api/schedules/admin/auto-generate` - generează sloturi normale după setup admin
- `POST /api/schedules/admin/bulk-delete` - șterge bulk sloturile automate normale
- `POST /api/schedules/emergency/setup-generate` - generează/actualizează sloturi de urgență după setup admin
- `POST /api/schedules/emergency/bulk-delete` - șterge bulk sloturi de urgență după săptămână/zile/interval și curăță programările asociate
- `POST /api/drivers/{driver_id}/verify-email` - verifică emailul livratorului cu codul trimis prin Resend
- `POST /api/drivers/{driver_id}/resend-verification` - retrimite codul de verificare email pentru livrator
- `PATCH /api/drivers/{driver_id}/ranking` - setează/șterge scor manual de rank pentru livrator
- `DELETE /api/drivers/{driver_id}?confirm_delete=true` - șterge livratorul și userul asociat, dacă nu există comenzi active
- `POST /api/schedules/admin/clone-previous-week` - preview/confirmare pentru refacerea sloturilor după săptămâna precedentă
- `GET /api/drivers/{driver_id}/dashboard` - profil individual livrator cu rank, program, comenzi recente, avataruri și audit
- `PATCH /api/drivers/{driver_id}/profile` - editare admin nume/telefon/email/parolă, cu audit log
- `PUT /api/drivers/{driver_id}/status` - setează status operațional `active / break / offline`; `delivery` este derivat din comandă activă
- `POST /api/drivers/{driver_id}/avatar` - upload avatar crop-uit/compresat; admin aprobă automat, livrator trimite pending
- `PATCH /api/drivers/{driver_id}/avatars/{avatar_id}` - admin aprobă/respinge avatar pending
- `GET /api/drivers/{driver_id}/avatars/{avatar_id}/image` - servește imaginea avatarului prin backend
- `POST /api/schedules/admin/quick-adjust` - adaugă/scade rapid sloturi pe o celulă exactă din calendarul de Program (`day`, `hour`, `delta`, `slot_type`)
- `PATCH /api/drivers/{driver_id}/self-profile` - actualizează profilul personal al livratorului: nume, prenume, CNP, data nașterii, sex, telefon, email
- `POST /api/auth/login` - acceptă identificator email sau telefon pentru autentificare
- `GET /api/restaurants/{restaurant_id}` - returnează profilul restaurantului curent/admin, inclusiv statusul operațional
- `PATCH /api/restaurants/{restaurant_id}/status` - restaurantul/adminul setează dacă acceptă comenzi; folosit de Restaurant App
- `PATCH /api/restaurants/{restaurant_id}/schedule-settings` - salvează programul restaurantului pe zile și ore
- `GET /api/orders/restaurant/{restaurant_id}/prep-availability` - disponibilitate livratori pentru validarea timpilor de pregătire
- `POST /api/orders/{order_id}/problem` - creează comandă legată pentru produs lipsă/produs nou
- `PATCH /api/drivers/{driver_id}/disable` - dezactivează soft contul livratorului, blocat dacă are comenzi active

## DB Schema - delivery_zones
```
{id, restaurant_id, restaurant_name, sector, zone_level, name, color, fee, polygon: [{lat, lng}], is_active, sort_order, created_at, updated_at}
```

## Rămas
- P0: Validare cu clientul pe workflow-ul nou: fiecare restaurant își desenează propriile zone și nu mai există zone globale pe harta live
- P0: Testare reală cu mai multe restaurante + zone suprapuse pentru confirmarea filtrării pe restaurant
- P1: Testare UX cu clientul pe pinul ajustabil, zone per restaurant și modalul de generare sloturi pentru a regla terminologia „slot/oră” vs. „slot total”
- P1: Design polish propus pentru următorul pas: cards restaurante mai profesionale, skeleton-uri subtile, detalii vizuale pe hărți/analytics și ordine mai clară în tab-ul Restaurante
- P1: Testare vizuală cu clientul pe noul contrast indigo/slate/amber și ajustări fine dacă preferă altă direcție cromatică
- P1: Testare vizuală cu clientul pe iconițele 3D ale hărții; ajustare dacă preferă alt simbol pentru restaurante decât storefront
- P2: refactor structural suplimentar pentru split complet pe fișiere/componente încă lungi (`AdminDashboard`, `AdminScheduleView`, `DeliveryZonesManager`) și reducerea suplimentară a dimensiunii lui `seed.py`; `AdminDashboard` rămâne ~1450 LOC după primul split și trebuie continuat într-un pas separat
- P2: după iteration 21, nu există defect blocant cunoscut; rămâne doar cleanup gradual de maintainability pentru `AdminDashboard.jsx` / `AdminScheduleView.jsx`, fără impact funcțional curent
- P2: reglaj fin al algoritmului automat de urgență pe baza datelor reale de volum/comenzi ale clientului
- P1: monitorizare primele emailuri reale Resend pentru spam/deliverability; fallback-ul local rămâne doar backup dacă providerul returnează eroare.
- P1: rezolvare la nivel ingress/platformă pentru preflight OPTIONS care returnează `Access-Control-Allow-Origin: *` extern, deși backend-ul returnează explicit origin intern
- P1: CORS preflight extern necesită modificare de ingress Kubernetes; troubleshoot RCA confirmă că FastAPI răspunde corect pe localhost și OPTIONS este interceptat înainte de backend.
- P1: Polish final design Driver App conform direcției orange/gri din imaginile clientului, după feedback pe noul shell mobile.
- P1: Dacă se dorește stocare persistentă multi-deploy pentru avataruri, migrare din filesystem server-side către object storage dedicat; endpoint-urile actuale ascund detaliul de storage în spatele backend-ului.
- P1: Integrare SMS reală pentru validarea telefonului când clientul aprobă costurile/alege furnizorul (ex. Twilio Verify); în prezent SMS este deferred, nu mocked.
- P1: Refactorizare UI Calendar livrator pentru a înlocui complet componenta veche `DriverSchedule` cu o experiență dark/orange nativă, dacă utilizatorul cere polish total.
- P1: Refactor AdminDashboard în componente mai mici; fișierul rămâne mare, deși UI-ul responsive a fost îmbunătățit.
- P1: Conectare reală Admin Settings, care rămâne MOCKED/demo.
- P1: CORS preflight extern încă returnează wildcard la nivel Ingress; codul aplicației rămâne valid, dar fixul cere setări edge/deployment.
- P1: Refactor RestaurantApp/AdminDashboard în componente mai mici după batch-ul mare Faza curentă.
- P1: suport real pentru multi-comandă pe același livrator dacă business-ul confirmă că livratorii pot prelua încă o comandă simultan
- P2: polish vizual suplimentar pe toate ecranele după feedback client — fără aplicație client final și fără pregătire Faza 3 în acest scope
- Phase 3: GPS tracking în timp real (WebSockets) + Alocare automată comenzi
- Phase 4: Push Notifications (Firebase)
- Phase 5: Integrări externe (Glovo/Wolt/Bolt API)
- Phase 6: Raportare avansată
- Phase 7: Aplicație nativă (Android/iOS)
- Phase 8: Lansare producție

## Tehnologii
- Frontend: React, Tailwind CSS, Recharts, Shadcn UI, PWA, react-leaflet, leaflet-draw
- Backend: FastAPI, Pydantic, Shapely (geo), modular routing
- Database: MongoDB (Motor)
- Mapping: OpenStreetMap/Leaflet (gratuit, fără Google Maps)
