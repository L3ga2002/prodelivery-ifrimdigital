# PD-STAGE1-PLAN-20261002 - plan de atac si criterii de inchidere

Data: 2026-10-02. Proiect: ProDelivery. Etapa comerciala: 1 din 10, pachetul suplimentar de 10.000 EUR.
Completion: `in_progress`. Nu este o etapa declarata finalizata.

## Scop

Inchidem inventarul actual, regulile si specificatia tehnica necesare urmatoarelor incremente. Nu repornim proiectul, nu implementam toate functionalitatile viitoare sub numele Etapei 1 si nu activam alocarea reala.

Rezumat produs: firma clientului centralizeaza comenzile restaurantelor, pregatirea lor si executia livrarilor; administratorul coordoneaza, restaurantul foloseste web/PWA, iar livratorul va folosi Android/iOS. Noul model trebuie sa permita minimum 10 comenzi active pe acelasi livrator atunci cand sunt compatibile operational.

## Routing si limite

- Owner: Codex.
- Review: trecere de consistenta separata Codex; nu este audit independent.
- QA: teste locale izolate, probe reproductibile, browser si dispozitive fizice unde este cazul.
- Invocation: tools locale; fara OpenClaw/Claude conform cererii lui Catalin.
- Backup/lock acum: nu sunt necesare pentru citire si acest document aditiv. Inainte de cod/schema: checkpoint verificat, scope ingust si lock pentru suprafata partajata.
- Nu sunt autorizate prin acest plan: migrari sau modificari ale bazei existente, env/secrete, costuri externe, commit/push/deploy, schimbari Agent Hub sau lansare de agenti externi.

## Evidenta existenta versus verificare curenta

Raportul `.ifrim/LOOP_REPORTS/2026-10-02-stage1-baseline.md` consemneaza 18/18 teste pe mediu izolat cu FakeDb, lint exit 0, preview si diagnostic pentru CANCELLED. Acele teste nu au fost rerulate pentru acest plan si nu dovedesc atomicitate Mongo reala.

Raportul `.ifrim/LOOP_REPORTS/2026-10-02-oss-dispatch-research.md` documenteaza sursele primare si candidatii OR-Tools/VROOM; niciun motor nu a fost instalat sau benchmarkuit in acea cercetare.

Verificari executate pentru acest plan:

- `git status --short --branch`: `main...origin/main`, worktree cu modificari preexistente, pastrate.
- `GET http://127.0.0.1:3000/login`: HTTP 200.
- `GET http://127.0.0.1:8000/api/`: HTTP 200.
- Agent Hub continuation read-only: online; taskul returnat ramane `PD-HUB-001`, `Phase 2 Restaurant Panel Closure Map`, status `ready`. Nu prevaleaza asupra planului comercial curent; nu am modificat Hub.
- MongoDB `hello`, citire directa fara dotenv si fara documente client: `topology=Single`, `replica_set=false`, `writable_primary=true`, `logical_sessions=true`.

Rezultatul Mongo local exclude presupunerea suportului tranzactional multi-document in actuala configuratie. Prezenta sesiunilor logice nu este o dovada de suport pentru tranzactii. Serverele standalone nu suporta tranzactiile respective. [Documentatia MongoDB](https://www.mongodb.com/docs/manual/core/transactions-production-consideration/)

Nu am pornit o tranzactie, modificat topologia, creat indexuri/colectii sau citit datele clientilor. Configuratia de productie nu este demonstrata prin aceasta proba locala.

## Ordinea de lucru

### S1-01 - harta cerinta-cod-test

Finalizam matricea pentru creare, acceptare, pregatire, gata, asignare, ridicare, livrare, anulare, incidente, pauza si inchidere zi. Pentru fiecare: owner de date, roluri, stari permise, fisiere, teste existente, defecte, dovezi si lipsuri.

Inventarul si cercetarea deja facute sunt reutilizate. Defectul `PD-CORE-CANCELLED-01` ramane separat, cu fix ingust si regresie in Etapa 2/engineering support; nu stergem comenzile anulate pentru a-l masca.

### S1-02 - specificatia PD-DISPATCH-01

Prima lucrare concreta ramasa: document pentru asignare multipla, ruta si capacitate. Definim:

- Sursa autoritativa a asignarii si cota activa plus rezervata.
- Contractele pentru asignare, acceptare, expirare, refuz, realocare, ridicare, livrare si anulare.
- Versiuni, chei idempotente, concurenta si recuperare dupa crash.
- Ridicare inainte de livrare; protejarea opririlor executate si comenzilor deja ridicate.
- Adaptorul `current_order_id`, ca fluxurile existente sa ramana compatibile.
- GPS/pregatire/vehicul/capacitate/ferestre si motivele de nealocare.
- Timeout si fallback vizibil, fara alocare imposibila sau bucle infinite.

Protocolul de concurenta nu se alege presupunand tranzactii disponibile local. Se compara o topologie tranzactionala intr-un mediu separat cu un protocol atomic si reconciliere crash-safe. Nu convertim Mongo existent in acest task. Orice alegere trebuie sustinuta prin teste reale, nu numai FakeDb.

### S1-03 - probe tehnice izolate

Proba optimizatorului: aceleasi fixture-uri pentru 1/2/5/10 comenzi, inclusiv un caz fezabil si unul nefezabil, deadline, comenzi deja ridicate si date lipsa. Comparam OR-Tools cu alternativa numai daca este necesar. Masuram latenta, fezabilitate si explicatii; nu activam solverul pe comenzile existente.

Proba concurentei: cota aproape plina, doua rezervari simultane, repetarea operatiilor, finalizarea unei comenzi din zece, crash/reluare si realocare cu versiune veche, intr-un mediu separat aprobat.

Proba mobil/GPS: executie pe Android/iOS fizic, permisiuni, ecran blocat, fundal, offline/revenire si baterie. Nu echivalam pagina web/emulatorul cu aceasta dovada. Alegerea frameworkului necesita aceste probe timpurii.

### S1-04 - dependinte si gate-uri

Conectorul unui restaurant: furnizorul/documentatia/accesul raman lipsa, cu blocker explicit. Nu blocheaza inventarul, specificatia interna sau probele de dispatch. Nu cerem parole in chat si nu inventam capabilitatile furnizorului.

Documentam separat accesul la dispozitive si conturi de distributie, optiunile OCR/harta, infrastructura tinta si costurile care cer aprobare. Nu modificam scope-ul commercial printr-o presupunere tehnica.

### S1-05 - review si inchidere

Raport final cu matricea, specificatia, rezultatele probelor, limitele si taskurile urmatoare. Nu se foloseste un procent arbitrar sau numarul de pagini pentru a declara etapa gata.

## Criterii de inchidere

| Criteriu | Stare la acest plan |
| --- | --- |
| Inventar focalizat si baseline existente | Facute; matricea completa ramane de finalizat |
| Modelul si contractele multi-comanda | In lucru; nu inchise |
| Topologia Mongo locala cunoscuta | Verificata; standalone |
| Protocol de concurenta ales si dovedit separat | Neinchis |
| Proba optimizer 1/2/5/10 | Neexecutata |
| Probe fizice Android/iOS GPS | Neexecutate |
| API nominalizat sau blocker explicit | Blocker explicit documentat |
| Report final, gate-uri si taskuri inguste | Acest plan este pregatirea, nu reportul de inchidere |

## Tinta pentru astazi

Putem avansa inventarul si specificatia de baza astazi; nu garantam inchiderea integrala a Etapei 1 inainte de rezultatele probelor. Daca probele fizice/integrate nu pot fi efectuate, raportam exact ce ramane neverificat; nu le bifam pe baza documentatiei.

Next best task: S1-02 / PD-DISPATCH-01 specificatie, folosind harta deja existenta si constatarea topologiei locale. In paralel logic, completam matricea S1-01 fara editari concurente in cod.

Questions for Catalin: accesul la Android si iPhone pentru proba fizica va fi necesar cand pregatim acel test; nu blocheaza lucrul documentar curent. Nu cerem reaprobarea intregului plan.
