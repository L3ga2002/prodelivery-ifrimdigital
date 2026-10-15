# ProDelivery - pornire executie pachet 10.000 EUR

Data: 2026-10-02. Task: `PD-STAGE1-20261002`. Etapa curenta: 1 din 10, in lucru.

## Scop si autoritate

Evaluam exclusiv pachetul operational de 10.000 EUR, nu vechiul plan de 26.000 EUR. Sursa locala curenta este `.ifrim/EXECUTION_PLAN_2026-09-26.md`, confirmata prin cerintele lui Catalin. Pastram lucrarile existente. Documentul de fata este inventar focalizat si baseline, nu audit exhaustiv si nu dovada ca toate cele zece etape sunt terminate.

Codex este owner/coordonator. Review: trecere separata Codex; nu pretindem auditor independent. QA: verificari locale descrise mai jos. OpenClaw si Claude Code nu au fost invocate, conform restrictiei specifice ProDelivery. Catalin gestioneaza actualizarea Agent Hub; nu am modificat Hub.

Git la pornire: `main...origin/main`, HEAD `9229618`, cu modificari preexistente in memoria proiectului, configuratia Claude si documente/scripturi. Le-am pastrat. Nu am modificat sursa aplicatiei sau date client si nu am facut commit/push/deploy. Pornirea preview-ului a generat loguri locale normale. Rapoartele noi sunt aditive.

Agent Hub a fost consultat read-only. Contextul returnat indica inca taskul istoric `PD-HUB-001` / Phase 2 si lock advisory pe restaurant-panel. Acestea nu inlocuiesc planul comercial nou. Inventarul nu editeaza panoul restaurantului; Hub nu este un blocaj pentru pregatirea ProDelivery.

## Verificari executate acum

| Verificare | Rezultat | Limita dovezii |
| --- | --- | --- |
| Teste `test_order_hardening_unit.py` si `test_order_critical_flows.py` | 18 trecute, 0 picate la rularea finala | Reguli pure si FakeDb; nu dovedesc atomicitate Mongo reala |
| `npm.cmd run lint`, in frontend | Exit 0 | Verificare statica, nu regresie UI completa |
| `dev-start.ps1` | Pornire finalizata; frontend compilat cu succes | Au ramas avertismente de deprecari Node/webpack-dev-server; nu a fost rulat build de productie |
| `GET http://127.0.0.1:8000/api/` | HTTP 200, API running | Nu certifica toate rutele sau performanta |
| `GET http://127.0.0.1:3000/login` | HTTP 200 | Verificat suplimentar in browser |
| Browser Brave, pagina login | Pagina randata; click cu formular gol blocat de validare; parola lipsa blocheaza submit | Fara autentificare sau scrieri in comenzi; nu am testat dashboardurile autentificate |
| Console browser pe login | Nicio intrare error/warn capturata | Numai pagina/sesiunea observata |
| Caz CANCELLED in fluxul livratorului, fixture separat | Defect reprodus: feed-ul contine CANCELLED si ASSIGNED | Diagnostic pe functia reala cu FakeDb, nu test pe baza existenta |

Prima incercare a celor 18 teste a avut 10 pass / 8 fail deoarece runnerul izolat bloca inclusiv socketpair-ul intern folosit de asyncio pe Windows. Nu erau opt defecte ale aplicatiei. Runnerul a fost corectat sa permita loopback-ul intern pe porturi efemere; Mongo real si incarcarea `.env` au ramas blocate. Rularea finala a trecut 18/18 in 10,24 secunde. Am pastrat XML-ul initial separat de cel final.

Nu am citit/afisat `.env`, credentiale, `.ifrim/private`, `.ifrim/tmp` sau uploads. Testele HTTP care pot crea/modifica date in baza existenta nu au fost rulate. Izolarea completa a suitei de integrare ramane lucrare necesara.

Browserul integrat a esuat la atasarea webview-ului; verificarea a continuat in Brave. Acest blocaj al instrumentului nu este o eroare a aplicatiei. Captura locala a paginii este in dovezile acestui task.

## Inventar pe cele zece etape

| Etapa | Reutilizabil / observat in cod | Ce ramane necesar |
| --- | --- | --- |
| 1. Inventar si specificatie | Planul curent, harta consumatorilor singulari, baseline si preview confirmate | Contractele pentru asignari multiple; protocol de concurenta; mediu Mongo de test; probe mobil/GPS/dispatch; decizii furnizori |
| 2. Comenzi si administrare | Rute comenzi, validari, stari controlate, audit, asignare manuala; teste de flux trecute pe FakeDb | Fix feed livrator pentru CANCELLED; model multi-comanda; regresie UI autentificata, concurenta reala, idempotenta durabila si compatibilitate |
| 3. Restaurant PWA | Ecran restaurant; acceptare/pregatire/gata/pauza/inchidere; validari/teste existente | Probe browser pe fluxuri si incidente, conexiune pierduta/refresh/conflict; nu reconstruim ce exista |
| 4. OCR si un conector API | Introducere manuala existenta | OCR cu fotografiere/extragere/confirmare/corectare/deduplicare; conector dupa identificarea sistemului, documentatie si acces autorizat |
| 5. Livrator Android/iOS | Ecran web livrator cu statusuri, confirmari, navigatie externa si date profil | Proiect/aplicatie mobila si teste pe telefoane; lista si opriri pentru mai multe comenzi, offline/revenire, fundal, distributie |
| 6. GPS si harta | Harta admin si endpoint de actualizare locatie | GPS real de pe dispozitive, varsta/precizie, fundal/baterie, pozitii stale si confidentialitate; harta singura nu probeaza tracking real |
| 7. Alocare automata | Rezervare atomica existenta pentru modelul singular | Minimum 10 active pe acelasi livrator, capacitate/ferestre/pregatire/eligibilitate, ordine pickup-dropoff, timeout/replanificare, concurenta/restart |
| 8. Notificari/incidente/rapoarte simple | Sunet/vibratie in browser si componente/statistici deja prezente | Push/fundal pe telefoane, exceptii operationale, rapoarte din date reale si probe de livrare a notificarilor |
| 9. Infrastructura/securitate/performanta | Autorizari, loguri/audit, validari si hardening existente | Verificari actuale de securitate/roluri, deploy autorizat, monitorizare, backup/restore demonstrat, benchmark 50 restaurante/100 livratori |
| 10. Pilot/publicare/predare | Plan de pilot si criterii documentate | Zi reala de operare, corectii, pachete/dispozitive, depunere in magazine, instruire si predare; aprobarea magazinelor este distincta |

Cautarea focalizata in `frontend/src`, `backend/routers`, `backend/models`, `frontend/package.json` si fisierele PWA nu a identificat implementarea OCR, proiect mobil nativ sau motorul de alocare multipla. Este o constatare asupra zonelor verificate, nu inventarul tuturor fisierelor istorice/artefactelor.

## Harta modelului singular, verificata in cod

| Fisier / linie | Dependenta | Cerinta la adaptare |
| --- | --- | --- |
| `backend/models/driver.py:33` | `current_order_id` singular | Asignari/ruta/capacitate cu sursa autoritativa clara si adaptor legacy |
| `backend/routers/orders.py:450` | Alta comanda curenta produce 409 | Plafon configurabil si verificari de fezabilitate, nu eliminarea simpla a conflictului |
| `backend/routers/orders.py:462` | Claim atomic pe un singur camp | Rezervare atomica a locurilor, cu oferte active numarate si crash recovery |
| `backend/routers/orders.py:291`, `:308` | Elibereaza intregul current_order_id la anulare/livrare | Eliberarea numai a asignarii vizate; celelalte noua raman intacte |
| `backend/routers/orders.py:499`, `:510` | Rollback/realocare pentru un camp | Reconciliere si rollback scoped pe operatia/asignarea exacta |
| `backend/routers/drivers.py:161`, `:674`, `:697`, `:711` | Status, GPS, pauza/offline se bazeaza pe singular | Reguli pe toate asignarile active, pastrarea protectiilor de rol |
| `frontend/src/pages/AdminDashboard.jsx:694`, `:734` | Disponibil numai fara current_order_id | UI cu numar locuri/liber, stari curente si conflicte explicabile |
| `frontend/src/components/admin/LiveMapPanel.jsx:147` | Ruta pentru o singura comanda | Opriri ordonate, versiune si compatibilitate cu ruta curenta |
| `frontend/src/components/admin/MapMarkerIcons.jsx:84` | Indicator livrare din singular | Stare operationala coerenta cu toate sarcinile |
| `frontend/src/pages/DriverApp.jsx:177`, `:210` | Selecteaza prima comanda diferita de DELIVERED | Lista activa corecta, sarcina/oprire curenta, fara ascunderea celorlalte comenzi |

## Defect nou confirmat: PD-CORE-CANCELLED-01

- Gravitate: High operational, nu incident de securitate demonstrat.
- Evidence: `get_driver_orders`, `backend/routers/orders.py:332`, filtreaza `$nin: ["DELIVERED"]`. Fixture cu CANCELLED, ASSIGNED, DELIVERED si alta persoana returneaza CANCELLED + ASSIGNED. `DriverApp.jsx:177` alege primul status diferit de DELIVERED.
- Impact: dupa anulare, comanda poate ramane/arata din nou ca sarcina curenta si poate ascunde urmatoarea comanda. AdminDashboard.jsx:732 are de asemenea o lista numita activeOrders care exclude numai DELIVERED; politica tabului/anularilor trebuie verificata separat.
- Owner/fixer: Codex backend + frontend. Nu s-a implementat fixul in acest inventar.
- Fix recipe: definitie comuna si explicita a starilor active; exclude CANCELLED din feed/lista activa, pastreaza comanda si auditul in istoric; valideaza raspunsul in frontend fara a elimina actiuni existente. Verifica restaurarea/refresh-ul si accesul numai la propriul livrator.
- Teste necesare: CANCELLED + ASSIGNED, numai CANCELLED, DELIVERED + CANCELLED, alt driver, refresh dupa anulare, plus suita critica existenta. Nu sterge comenzile anulate ca solutie.

## Primul increment si ordinea de lucru

1. Inchide `PD-CORE-CANCELLED-01` prin fix mic si teste de regresie, fara schimbari de schema sau UI de design.
2. Inchide specificatia `PD-DISPATCH-01`: sursa autoritativa pentru asignari/capacitate/ruta, contracte, compatibilitate, protocol de concurenta si matricea D01-D20 din plan. Nu activa alocarea automata in acest pas.
3. Ruleaza probe izolate pentru 1/2/5/10 comenzi, concurenta si reluare dupa crash; testeaza devreme mobilul si GPS-ul in fundal. Acestea informeaza calendarul, nu se amana pana la final.
4. Implementare incrementala backend, apoi consumatorii admin/restaurant/livrator, review separat si QA pe fluxuri afectate si adiacente.
5. OCR/manual pot avansa independent; conectorul nominal este amanat pana la documentatie/acces. Nu se inventeaza API-ul si nu se rescrie contractul fara acord.

## Termen: o luna fata de planul de trei luni

O luna pentru toate cele zece etape nu poate fi confirmata din dovezile curente. In pachetul de 10.000 EUR raman lucrari majore: model multi-comanda, motor de alocare, OCR, mobil Android/iOS, GPS de teren, push, infrastructura si pilot. Un conector fara documentatie si aprobarea magazinelor sunt dependente externe.

Patru saptamani reprezinta o tinta agresiva pentru un pilot cu scop explicit verificat, nu o garantie de livrare a intregului plan. Deocamdata pastram tinta documentata de trei luni si reestimam pe baza probelor timpurii si a timpului efectiv de implementare. Nici performanta 50/100, nici bugetul intern AI nu devin garantate prin acest baseline.

## Ce nu este inca verificat

- Login autorizat/roluri si toate dashboardurile prin browser; fluxuri complete UI, conexiune pierduta/duplicate/loading/error/empty.
- Mongo real: topologie, tranzactii, indexuri, concurenta, crash recovery, restore.
- Suitele HTTP care modifica date: necesita mediu separat si fixture-uri controlate.
- Telefoane fizice Android/iOS, GPS/push/fundal/camera/OCR.
- Build/release de productie, benchmark, integrare API, pilot si aprobari magazine.

## Dovezi si reproducere

Director dovezi publicabile in proiect: `.ifrim/QA_RUNS/2026-10-02-stage1/`.

- `run_unit_baseline.py`: runner pentru cele doua module existente, fara dotenv/Mongo real; ruleaza cu `.venv\Scripts\python.exe -X utf8 .ifrim\QA_RUNS\2026-10-02-stage1\run_unit_baseline.py`.
- `unit-baseline.xml`: rularea initiala, izolarea prea stricta; `unit-baseline-final.xml`: 18/18 final.
- `check_cancelled_driver_order.py` si `cancelled-driver-evidence.json`: diagnostic read-only pe fixture; scriptul afiseaza observatia, nu transforma defectul in test trecut.
- `login-preview.jpg`: pagina de autentificare observata in Brave.

Final: pregatirea a inceput; inventarul focalizat/baseline-ul sunt facute. Etapa 1 nu este declarata inchisa, iar planul de 10.000 EUR nu este declarat implementat.
