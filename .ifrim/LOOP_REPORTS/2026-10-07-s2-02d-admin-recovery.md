# ProDelivery - S2-02D admin create/recovery

Data: 2026-10-07. Status: sursa integrata si verificata; activare live separata.
Etapa2: in_progress. Acest raport nu inchide intreaga etapa si nu renumeroteaza
planul comercial cu10 etape. Catalin a aprobat continuarea loturilor interne.

## Rezultat concret

Formularul de creare din admin poate folosi protocolul recuperabil S2-02 dupa
capability explicit enabled. Genereaza o singura identitate pentru intentie,
protejeaza submitul sincron si intre taburi, pastreaza ID dupa refresh/reload,
confirma rezultatul prin lookup/resume si nu inventeaza o comanda noua la timeout.

Un rezultat neconfirmat ramane vizibil si blocheaza modificarea payloadului;
butonul verifica aceeasi intentie. Aplicat/recuperat/respins necesita actiune
explicita pentru o alta comanda sau corectie. Succesul salvarii si esecul
actualizarii listei au mesaje distincte. Designul actual este pastrat; numai
states necesare si inaltimea/scrollul local al dialogului au fost ajustate.

Capabilitate explicit disabled pastreaza POST /api/orders, dar sub acelasi Web
Lock si cu recitirea metadata. Eroarea de capability nu permite fallback. Un ID
recuperabil existent nu poate fi ocolit prin ruta veche. Legacy nu devine astfel
durabil/exactly-once la ACK pierdut; acesta este un risc ramas explicit.

## Fisiere si motive

| Fisier fata de root ProDelivery | Modificare / motiv |
| --- | --- |
| frontend/src/lib/orderCreationRecovery.js | Controller strict: input/output, ID, storage, payload detasat, Web Locks, timeout15000ms, recovery finit, same-intent-only, lifecycle owner |
| frontend/src/hooks/useOrderCreationRecovery.js | Integrare React, StrictMode/in-flight, actor isolation, offline/capability/errors, transport Axios izolat fara refresh/replay ascuns |
| frontend/src/pages/AdminDashboard.jsx | Conectare conditionata, blocare form/butoane, rezultat versus refresh, acknowledgement explicit, dimensionare dialog mobil |
| frontend/src/lib/orderCreationRecovery.test.js | 120 teste independente pastrate neschimbate dupa reparatii |
| frontend/src/lib/orderCreationRecovery.integration.test.js | 27 regresii React-jsdom/real Axios: bodyless, stale tab, actor change, StrictMode, auth401, token A/B/null |
| frontend/eslint.config.mjs | Declara globals.jest numai pentru test files; nicio regula dezactivata/test ignorat |
| backend/utils/order_creation.py | Doua metode aditive: capabilities read-only/current admin, resume pentru intentia deja stocata; protocolul vechi pastrat |
| backend/routers/order_operations.py | Doua rute aditive private/no-store; resume refuza orice body, inclusiv{} |
| backend/tests/test_order_creation_ui_bridge.py | 75 cazuri in-memory/ASGI pentru bridge, autorizare, malformed settings/intent, erori/timeouts/payload privacy |

Nu am modificat auth shared, business writerii legacy, schema live, dependentele
aplicatiei, env/secrete sau alte proiecte. HTTP/Mongo suplimentar15 cazuri din
QA_RUNS/test_create_http.py include9 existente +6 noi; este harness opt-in, nu
un test care se conecteaza implicit la date reale. Istoricul testelor este pastrat.

## Agent routing si review

Codex coordonator/frontend owner; Parfit backend owner; Arendt reviewer
independent; Descartes QA/tests independente. Numai subagenti interni Codex,
fara OpenClaw/Claude. Scope-urile de scriere au fost disjuncte.

Review-ul R1-R7 a cerut si apoi a inchis reparatii pentru resume cu body, legacy
cu state vechi, StrictMode, efecte dupa schimbarea sesiunii, auth replay, rezultat
intarziat publicat altui actor si bearer implicit mostenit. Reviewerul raporteaza
PASS_SOURCE_INSPECTION pe hashurile finale; nu pretinde ca a executat QA.

Patru teste originale RED au prins trei defecte concrete: aliasul payloadului,
storage read-failure si doua cazuri de order_id cu spatii. QA a mai reprodus un
defect real de actor-switch in React. Ownerul a reparat sursa, nu asertiunile.
Detalii RED/GREEN si hashuri: QA_RUNS/2026-10-07-s2-02d/QA_NOTES.md, REVIEW.md.

## Dovezi executate acum

| Pachet | Rezultat final |
| --- | --- |
| Frontend pe sursa integrata | 221/221 teste, 3/3 suite |
| Backend S2-02/bridge pe sursa integrata | 202/202:112 service +15 HTTP/Mongo +75 doubles |
| Regresii backend selectate pe sursa integrata | 1193/1193 |
| Total distinct teste | 1616 trecute,0 finale picate; rerularile nu se aduna |
| Procese/crash/concurenta, sursa hash-identica | 3/3 separat |
| Browser click-through sintetic | 17/17 scenarii grupate separat,0 page errors |
| Lint frontend complet, integrat | 0 erori,0 warninguri |
| Flake8 fisiere Python schimbate E9/F | exit0 |
| Build izolat staged si integrat, fara dotenv | 0 erori,0 warninguri |

Browserul a folosit frontend real compilat la http://127.0.0.1:57225/admin cu
API/comenzi/user sintetice. Clickuri reale: invalid/valid, dublu-click, ACK pierdut,
pre-admitere pierduta, timeout15s, receipt gresit, pending/reload/doua taburi,
rejected/corectie, offline/revenire,503, capability unavailable/disabled, state
vechi fara storage events, taburi adiacente, mobil320/390 si height500/667, plus
eroare refresh dupa salvare. Native Web Locks/Crypto/storage sunt exercitate in
Chromium; viewport emulat nu este test pe Android/iPhone sau cu tastatura fizica.

La inchidere TCP brusca s-au observat pana la doua transmisii cu acelasi ID;
invarianta verificata este un singur efect/order si rezultat recuperat, nu
promisiunea ca stackul browserului nu retransmite pachete. Bugetele logice ale
controllerului si absenta autoreplay401 au teste separate.

Preview real pastrat: http://127.0.0.1:3000/login, backend8000/api HTTP200.
Backendul vechi a fost repornit separat dupa identificarea workerului si
supervisorului, ca endpointul nou sa fie incarcat. Capabilities anonim raspunde
401/no-store. Browser anonim la3000/admin redirectioneaza login; fara conturi,
autentificare pe date reale sau creare de comenzi. Consola login are401 asteptate
si hint autocomplete; acestea nu sunt prezentate ca test E2E autentificat.

Rularea este reproductibila din QA_RUNS/2026-10-07-s2-02d/VERIFICATION.md.
Backup si hashuri ale celor9 fisiere integrate: source-publication.json.
Capturi: output/playwright/. Fixture Mongo este separat, loopback27941, datele
sintetice sunt pastrate, nu baza aplicatiei. Artefactele nu contin .env/secrete.

## Limite si gate-uri

Activare live: NOT_PERFORMED. Markerul bazei active nu a fost inspectat; nu am
provisionat marker/contor/index/topologie, schimbat env, comis/push/deploy sau
modificat Hub. Aprobarea lucrului intern nu inlocuieste aprobarea date/migrare.

Retentie/privacy trebuie inchise: sessionStorage pastreaza temporar payloadul
client plaintext pentru retry pre-admitere; terminal/logout/navigation il elimina.
Metadata durabila contine actor/ID/time/receipt, nu adresa/telefon. Fara draft,
GET404 ramane incert/manual verification, nu reset automat sau nou ID.

Nu sunt certificate: Safari/telefoane fizice, PWA SW/offline cache, harti/GPS real,
failover/sharding/load, toate testele istorice cu credentiale reale sau readiness
de productie. Warningurile backend: Starlette/httpx deprecation si Pydantic
in testul deliberat cu model invalid. Initialele harness errors sunt documentate,
nu confundate cu defecte de productie sau teste business trecute.

## Urmatorul lot

S2-COMPAT, inainte de S2-03: inventar complet create/edit/assign/reassign,
preparing/ready, accept/pickup/deliver/cancel, probleme/refaceri si scrieri indirecte.
Revizie/CAS comuna sau refuz explicit v2 pentru fiecare writer; teste de races,
update pierdut si rollback/recovery. Nu activa versionare pe date existente fara
dry-run/restore si aprobarea distincta. Receipt order_version=0 nu este versiunea
business actuala. Celelalte loturi Etapa2 si Etapa1 mobile/GPS raman deschise;
minimum10, auto-dispatch, OCR/API si native/store nu sunt implementate de acest lot.
