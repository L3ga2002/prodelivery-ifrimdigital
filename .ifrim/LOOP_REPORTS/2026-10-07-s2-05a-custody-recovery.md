# ProDelivery - S2-05A: custodie si anulare recuperabile

Data: 2026-10-07. Etapa comerciala: 2 - Comenzi si administrare.
Status: implementat si integrat, verificat pe sursa reala in mediu sintetic.
Etapa2: **in_progress**, nu inchisa. Activare live: **neefectuata**.

## Cerere si plan

Catalin a cerut planul pentru finalizarea Etapei2 si executia. Continuam
S2-01/02/COMPAT/03/04 existente; nu reconstruim aplicatia. Planul complet este
`TASK_PACKETS/2026-10-07-stage2-closure-plan.md`. Acest lot inchide S2-05A,
nu incidentele/refacerile S2-05B, listele S2-06 sau acceptarea S2-07/08.

Codex: owner backend si coordonare. Euler: owner frontend. Galileo: teste/QA
backend independente. Planck: review independent. Numai subagenti interni;
fara OpenClaw, Claude sau mutatii Agent Hub. Fisierele au fost separate prin
ownership, freeze si verificare de hash. Reviewerul nu a implementat fixurile.

## Ce s-a implementat

- Acceptare -> ridicare -> livrare cu intentie stabila, actor real, revizie exacta
  si rezultat recuperabil. Pregatirea restaurantului ramane stare distincta;
  ridicarea necesita READY real, nu expirarea timerului sau o presupunere UI.
- Anulare pre-pickup cu motiv, verificata pentru admin si propriul restaurant/
  livrator. Eliberarea atinge numai rezervarea corespunzatoare comenzii.
- Dupa pickup nu exista CANCELLED simplu care sa piarda marfa sau custodia.
  Incidentul si rezolutia vor fi tratate in S2-05B, nu prin bypass administrativ.
- O tranzactie Mongo leaga CAS-ul comenzii, rezervarea/eliberarea livratorului,
  contorii, auditul embedded/global si ledgerul. Rollback la esec partial.
- Livrarea acorda exact o crestere de contor si creditul existent
  `total_amount * 0.1`. Nu am schimbat politica de plata; valori monetare/countere
  invalide sau nefinite sunt refuzate, nu normalizate la zero sau reinterpretate.
- Identitatea livratorului deriva din schema existenta `drivers.user_id`.
  Legatura optionala `users.driver_id`, daca exista, trebuie sa fie coerenta.
- Pending lookup/resume reverifica proprietarul actual. Un rezultat terminal
  este numai dovada operatiunii originale a actorului, nu acces la snapshotul
  curent al unei comenzi devenite straine.
- Requesturi finite/deadline, commit/cleanup serializat, erori typed/no-store,
  header comparativ `X-Expected-Actor-ID` peste autentificarea reala. Headerul
  nu acorda autoritate si nu inlocuieste contul autentificat.
- Frontend cu timeout15s, loading/disabled, WebLocks, metadata actor-bound,
  lookup finit, acelasi ID dupa ACKlost/reload si fara fallback legacy incert.
  Motivul anularii este draft temporar in sessionStorage, nu payload client
  persistent in localStorage. Stergerea draftului nu sterge identitatea incerta.
- Panoul de rezultat ramane vizibil dupa ce comanda dispare din lista activa.
  Statusul/incasarile livratorului se recitesc dupa efect, cu fencing pentru
  raspunsuri vechi, schimbare cont, requesturi suprapuse si componenta demontata.
  503/date gresite arata explicit Neactualizat si --, apoi refresh GET manual
  finit; nu se retrimite livrarea si nu se afiseaza un zero financiar fictiv.
- Revenirea BFCache reverifica actorul real si blocheaza vechile callbacks.
  Fix separat pentru initial recovery sub StrictMode: intentia pending este
  recuperata/semnalata fara replay paralel, chiar la ciclul dublu al efectelor.
- Designul, formularele adiacente, preturile si fluxurile legacy sunt pastrate.
  Legacy nu devine implicit transactional; orice prezenta de revizie refuza
  un writer legacy si comenzile nu sunt promovate automat.

## Fisiere si motiv

| Fisier | Modificare |
| --- | --- |
| backend/utils/order_status.py | Serviciu nou: status/custodie/cancel, autorizare, CAS, tranzactie, ledger/recovery, invarianti si deadline. |
| backend/routers/order_operations.py | Patru rute guarded: capability, submit, lookup, bodyless resume. Contract privat/no-store. |
| backend/routers/orders.py | Guard incremental pentru actorul asteptat la status legacy; comportamentul existent pastrat. |
| backend/tests/test_order_status_recovery.py | 264 cazuri independente Mongo, concurenta, rollback, recovery, roluri/date invalide. |
| backend/tests/test_order_status_http.py | 58 cazuri HTTP: contract/erori/roluri/body/no-store/lookup/resume. |
| backend/tests/test_order_status_owner_guard.py | 65 cazuri de auth cookie/header real, driver schema, pending versus terminal ownership si legacy guard. |
| frontend/src/lib/orderStatusRecovery.js | Controller strict: schema, receipts, intentie, storage/locks, finite recovery, actor si legacy refusal. |
| frontend/src/lib/orderStatusRecovery.test.js | Teste controller pentru receipts invalide, duplicate, ACKlost, limite si storage/session. |
| frontend/src/hooks/useOrderStatusRecovery.js | Lifecycle React, loading/disabled, BFCache/StrictMode, rezultat persistent si guarduri pentru callbacks vechi. |
| frontend/src/hooks/useOrderStatusRecovery.test.jsx | Regresii hook, sesiuni/conturi diferite, BFCache, StrictMode pending recovery si async lifecycle. |
| frontend/src/pages/AdminDashboard.jsx | Dialog status/cancel, recovery exterior dialogului si refresh fenced; creare/alocare/editare pastrate. |
| frontend/src/pages/DriverApp.jsx | Custodie/cancel propriu, recovery si recitire status/incasari cu freshness/error explicit. |
| frontend/src/pages/RestaurantApp.jsx | Anulare proprie pre-pickup inclusiv ASSIGNED/ACCEPTED versionat, pregatire/gata pastrate. |
| frontend/src/pages/OrderStatus.status-sidecar.test.jsx | Teste pe cele trei pagini, role boundaries, duplicate, refresh/freshness, formulare si legacy. |

14 fisiere sursa/test. Modulul assignment/runtime existent a fost dependinta
verificata, nu rescris. Testele adiacente protejate nu au fost slabite sau sterse.
Istoricul Git si modificarile preexistente, inclusiv stergerile anterioare, au
ramas neatinse. Backup initial: `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery\.ifrim\BACKUPS\2026-10-07-s2-05a-f865f1a6a07c4fb38b77d11fd4937ce5`.
Fixul StrictMode are un backup suplimentar, identificat in integrated-manifest.

## Verificare finala, executata in aceasta sesiune

| Grup | Rezultat distinct |
| --- | --- |
| Backend unit/contract/security pure | 1750 passed |
| Recovery existente create/edit/assign | 532 passed |
| Status recovery/HTTP/auth noi | 387 passed |
| Frontend, toate suitele existente si noi | 879 passed |
| Total | **3548 passed, 0 final failed** |

Cele84 subteste ranking sunt separate; JUnit le include in1834 pentru primul
grup, dar numarul de teste distincte ramane1750. Rerularile staged, targetate,
ale ownerului si reviewerului nu se aduna din nou. Nu este procent de branch
coverage si nici certificare de productie. Sase teste vechi live/credentiale
nu au fost executate; helperii live si DB-ul aplicatiei au fost blocati in runner.

Build pe aceleasi hashuri implementate: 0 errors/0 warnings. Lint8 fisiere:
0 errors/0 warnings. Review scoped independent: niciun P1/P2 confirmat deschis.
Backend testele folosesc replica set izolat27941, nu DB clientului. Auth real
in teste inseamna JWT/cookies/DB sintetice fara dependency override; browserul
foloseste roluri injectate, fara autentificare sau date reale.

18 grupuri Chromium pe frontendul integrat3000 si API sintetic57230:
1. Accept dublu-click, pickup/deliver, trei receipts si un singur credit/release.
2. Reload terminal, Back return si acknowledgement fara efect suplimentar.
3. Pickup refuzat cand pregatirea nu este READY.
4. ACK pierdut si recuperare pe acelasi ID.
5. Doua taburi ale aceluiasi actor, o singura intentie/efect.
6. Lookup503, reload si recuperare explicita fara schimbare de ID.
7. Offline/revenire, disabled si fara duplicate.
8. Conflict409, snapshot nou explicit si intentie noua numai dupa reject.
9. Marker dezactivat: refuz versionat, fara fallback legacy.
10. Legacy legitim fara promovare de revizie.
11. Mobil390x844, delivery/receipt, cancel ascuns dupa pickup, fara overflow.
12. Restaurant NEW: motiv, dublu-click, cancel, reload, receipt pastrat.
13. Restaurant ASSIGNED: anulare proprie si eliberare exacta.
14. Restaurant ACCEPTED: anulare proprie si eliberare exacta.
15. Admin: dialog accept/cancel cu motiv, receipt vizibil in afara dialogului.
16. Restaurant READY pastreaza ACCEPTED, apoi driver pickup/delivery.
17. ProfileGET503 dupa commit: Neactualizat, bani --, manualGET fara replay.
18. ProfileGETwrong-id dupa commit: aceleasi protectii, fara date straine.

Zero pageerrors in aceste contexte QA. Screenshoturi desktop/mobile inclusiv
refresh esuat inspectate pentru text, bounds si overlap. Toastul temporar a
fost lasat sa se inchida in capturile finale; nu am schimbat designul pentru poza.
Proba suplimentara mobil390x844: scrollul aduce intreg sumarul deasupra barei
fixe, -- ramane vizibil, butonul manualGET este accesibil si nu repeta mutatia.
Statistica agregata admin din harness este stub sintetic fix, nu dovada de
reconciliere live a raportarii. Liste/detaliu/istoric/agregate sunt scope S2-06;
receipt-ul nu este interpretat ca snapshot complet al dashboardului.
Istoricul browser a returnat persisted=false: BFCache fizic/Safari/PWA/native,
serviceworker/cache/GPS/load/50restaurante/100livratori nu sunt dovedite aici.

## RED-uri si remedieri, pastrate ca dovezi

- Setup initial:273 erori pentru o ruta de fixture cu testul protectedrevision
  care inspecta fisierul vecin. Testul a fost copiat neschimbat in overlay corect;
  toate273 au trecut. Nu sunt273 defecte ale produsului.
- Noi teste backend: greseli de bariera/fixture/contract in testele nou scrise
  au fost corectate fara slabirea assertion-urilor protejate. Doua defecte reale
  pending ownership au fost fixate in serviciu; aceleasi doua teste RED au trecut,
  apoi322 independent si387 integrat. Detalii in QA_STATUS_NOTES/AFTERFIX/PUBLISHED.
- Testul ownerguard initial: un actor driver era legat de un user admin in
  fixture. Fixture corectat;62/63 initial, apoi63 si65 final. Nicio autorizare slabita.
- Review FE-01/02/03/04: BFCache, cancel restaurant ascuns, receipt rejected
  imposibil si freshness fals dupaGET esuat. Toate remediate de owner si verificate
  separat. Teste noi RED si rapoarte vechi sunt pastrate, nu inlocuite cu PASS.
- Browserul a gasit status/incasari vechi dupa livrare; nu s-a acceptat numai
  dovada commitului Mongo. Driver dashboard se reciteste acum corect; server503
  sau date invalide au stare persistenta de indisponibilitate si manualGET.
- Primul browser integrat dev a trecut5 grupuri apoi a gasit lipsa erorii la
  reload pending sub StrictMode. Fix de lifecycle + teste specifice + review
  independent si rerulare completa; oracle-ul browser nu a fost slabit.
- Harness: parserul CLI cerea arrow function fara trailingsemicolon; un test
  de reload avea o cursa cu auto-recovery; doua setup-uri fake-timer nesuportate.
  Aceste erori sunt separate de defectele reale, cu rezultate initiale retinute.
- Dupa fixul StrictMode, browserul dev a trecut11 grupuri apoi a fortat anularea
  restaurantului inainte ca disponibilitatea protocolului sa activeze butonul.
  Harnessul asteapta acum enabled si verifica motivul exact + zero operatii
  inainte de click. Dublu-clickul fortat si oracle-urile un singur cancel/audit
  raman identice; niciun cod de produs nu a fost schimbat pentru acest precondition.
- Helperul de integrare StrictMode a refuzat initial timestampul JSON convertit
  automat la DateTime de PowerShell. Refuzul a fost inaintea oricarei scrieri;
  normalizarea UTC a fost corectata, rerularile premature oprite si necontabilizate,
  apoi integrarea guarded si verificarile finale au fost reluate separat.
- Preview8000 avea routerul vechi in memorie:404 la capability. A fost repornit
  numai procesul ProDelivery verificat, prin dev-start existent. Endpointul nou
  raspunde401 anonim dupa restart. Nu s-au schimbat env, DB sau scripturi deploy.
- Warnings pastrate: Starlette/httpx TestClient si FastAPI on_event deprecations;
  Pydantic warning intentional pentru constructed-command invalid. Nu sunt
  erori de build/lint si nu au fost ascunse prin modificarea validarilor.

## Siguranta si limite reale

`order-status-v1` este default-disabled/neprovisionat. Markerul real nu a fost
inspectat/modificat. Integrarea sursei NU inseamna activare pe datele aplicatiei.
Nicio modificare env/secrets, DB reala, index/topologie, migrari, Hub, Git
history/commit/push sau deploy. Nicio trimitere externa sau politica noua de bani.
Normalul3000/8000 ramane disponibil; QA owned57230/57231/27941 si browserul propriu
sunt oprite la final. Datele sintetice sunt retinute, nu sterse/dropDB.
Controlul custody este single-slot; minimum10/multi-comenzi/alocare automata
nu sunt indeplinite de acest lot. Erorile HTTP injectate si401 anonim sunt
intentionate; nu pretindem zero global console/network errors.

## Ce urmeaza pentru inchiderea Etapei2

1. S2-05B incidente si refaceri partiale: protocol strict/tranzactie, originalul
   DELIVERED pastrat, un singur followup legat, fara dublarea creditelor/contorilor.
   Custodia si compensatiile necesita contract explicit, nu CANCELLED shortcut.
   Packet: `TASK_PACKETS/2026-10-07-s2-05b-incidents-remakes.md`.
2. S2-06 paginare server-side, liste complete/filtre, detaliu autorizat, istoric
   coerent, empty/error/offline si fencing pentru citiri vechi.
3. S2-07/08 audit si acceptare unei zile complete: creare/pregatire/alocare/
   acceptare/gata/pickup/delivery/istoric, pauza/inchidere, conflict/realocare,
   incidente/refacere si regresii in cele trei roluri.
4. Gate live distinct: dry-run, inventar duplicari/orfani/revizii, excluderea
   writerilor, reconciliere/migrare, backup/restore demonstrat, retentie ledger
   si payload temporar, aprobare punctuala pentru date/markeri/indexuri/deploy.
   Politicile financiare ambigue se confirma, nu se inventeaza.

Nu incepe Etapa3+ si nu cere repetat aprobarea executiei interne deja date.
OCR/API/GPS/native/store/multi10/load au propriile etape si dovezi.

## Verificare manuala, fara atingerea datelor clientului

Preview: http://127.0.0.1:3000/login. Rute afectate: /admin, /restaurant, /driver.
Frontend/API health200; noul capability refuza401 anonim. Previewul local nu
este deployment public. Nu activa markeri sau crea date reale doar pentru demo.
Scenariile versionate de mai sus se reproduc intr-un fixture sintetic verificat:
accept dublu-click -> READY real -> pickup -> delivery; verifica un singur credit,
eliberarea driverului si receipt terminal dupa reload. Simuleaza lookup503 si
profile503/wrong-id; recuperarea foloseste acelasi ID, iar profilul numai GET.
Verifica apoi cancel restaurant ASSIGNED/ACCEPTED, lipsa cancel dupa pickup,
admin status si fluxurile adiacente pregatire/alocare. Dovezile si screenshoturile
sunt in `QA_RUNS/2026-10-07-s2-05a`, nu sunt prezentate drept date ale clientului.

## Evidenta

verification-summary.json, original/source/integrated manifests, JUnit backend,
Jest frontend, build/lint, owner QA, review independent initial si StrictMode,
browser RED/final, preview route health si cleanup. Artefactele au allowlist
explicit si hash-uri; nu se copiaza runtime DB, .env, private/tmp sau uploads.
Memoria proiectului primeste checkpoint nou cu istoricul anterior pastrat.
