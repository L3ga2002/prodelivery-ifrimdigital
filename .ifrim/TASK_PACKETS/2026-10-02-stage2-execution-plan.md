# ProDelivery - Etapa 2: Comenzi si administrare

Data: 2026-10-02. Status: PLAN PREGATIT; IMPLEMENTARE ETAPA 2 NEINCEPUTA.

## 1. Autoritate si conditie de pornire

Acesta este detaliul Etapei 2 din EXECUTION_PLAN_2026-09-26.md, pachetul operational nou cu 10 etape. Nu renumeroteaza fazele istorice si nu reface functionalitati deja existente. Catalin a aprobat continuarea, cu conditia explicita ca Etapa 1 sa se incheie dupa verificarile cerute. Cererea "daca termini, fa planul pentru urmatoarea etapa si incepe" pastreaza aceasta conditie.

Etapa 1 ramane in_progress. Probele solver si Mongo sunt artefacte izolate, nu alocare multipla activata. Micro-proba nativa se pregateste in continuare; buildul nativ, telefoanele Android/iOS si verificarile fizice GPS/fundal sunt distincte de testele desktop. Lipsa lor nu se transforma in PASS. Documentatia conectorului restaurant ramane explicit deferred, conform deciziei lui Catalin.

Gate de pornire: raport de inchidere Etapa 1, cu matrice cerinta-cod-test actualizata, limitele prototipurilor, probleme blocking rezolvate si probele fizice cerute documentate. Orice derogare de la aceasta conditie necesita decizia explicita a lui Catalin. Benchmarkul complet 50 restaurante/100 livratori ramane in Etapa 9; proba timpurie nu este benchmark si nu garanteaza acest profil.

## 2. Rezultatul pentru utilizator

Administratorul poate crea si urmari comenzi, corecta datele permise, aloca sau realoca manual cand starea permite si vede cine a modificat comanda. Un dublu-click, doi administratori sau un raspuns pierdut nu trebuie sa creeze comenzi/asignari duble ori sa ascunda o operatie incerta. Restaurantul si livratorul isi pastreaza fluxurile existente si accesul numai la comenzile lor.

Alocarea manuala ramane functie permanenta de interventie. Nu inlocuieste cerinta alocarii AUTOMATE din Etapa 7. Arhitectura trebuie sa permita minimum 10 comenzi active pe acelasi livrator cand sunt fezabile; nu introducem plafon artificial de doua. Activarea multi-comanda necesita toate consumatoarele si protocolul de capacitate/ruta verificate, nu doar o lista noua in schema.

## 3. Baza existenta, verificata in sursa la aceasta data

| Zona | Exista acum | Ce NU rezulta din existenta ei |
| --- | --- | --- |
| backend/models/order.py | Modele create/status/assign/preparation, extra-forbid pe requesturi, limite de campuri | Nu exista revizie publica a comenzii sau schema de editare partiala |
| backend/routers/orders.py:create_order | Rol admin/restaurant, ownership restaurant, pauza/inchidere, numar comanda si audit | Nu exista identitate durabila a intentiei de creare pentru replay dupa raspuns pierdut |
| orders.py:assign_order | Alocare admin, revendicare atomica a driverului, CAS pe snapshot, duplicate din acelasi status | Model singular current_order_id; scrierile driver/order nu formeaza tranzactia prototipului nou |
| orders.py:set_preparing/set_ready | Pregatire decuplata logic de asignare, CAS si metadate | Nu demonstreaza contractul complet multi-comanda |
| orders.py:update_order_status | Tranzitii controlate, ownership, audit inline, cleanup conditional | Actualizarea terminala si efectele in driver/audit extern nu sunt protocolul tranzactional durabil nou |
| orders.py:get_orders/get_restaurant_orders | Filtrare pe rol; limite de 1000/100 rezultate | Nu este paginare completa/stabila a istoricului |
| frontend/src/pages/AdminDashboard.jsx | Creare, dialog de alocare, loading, refresh, protectie raspuns GET vechi | Blocarea prin state React nu este idempotenta server-side si nu supravietuieste reloadului |
| frontend/src/components/admin/OrdersTab.jsx | Lista activa desktop/mobil si alocare pentru NEW/PREPARING/READY | Nu este un flux complet de editare/realocare/istoric detaliat |
| frontend/src/lib/api.js | Timeout implicit 15 s, retry limitat pentru citiri, mesaje offline/server | Timeout-ul unei mutatii nu confirma daca efectul a avut loc |

Inspectie focalizata, nu audit exhaustiv. Suitele precedente si rezultatele Mongo se gasesc in LOOP_REPORTS/2026-10-02-mongo-concurrency-probe.md; nu sunt declarate rerulate prin acest plan. Nicio functionalitate de mai sus nu se sterge sau rescrie integral.

## 4. Loturi de executie, in ordine

### S2-01 - Contracte de mutatie si compatibilitate

Primul lot dupa gate. Owner: Codex backend. Reviewer: subagent intern backend/data. QA: teste pure si HTTP sintetice separate.

- Inventariem exact campurile editabile, tranzitiile si consumatorii actuali; pastram API legacy pana la adaptorul verificat.
- Definim schema stricta pentru operation_id, expected_order_version si erorile de conflict; identitatea actorului vine din autentificare, nu din payload.
- Distingem applied/replayed/pending/rejected. Un 202 sau timeout nu produce toast de succes; replay nu pretinde ca starea veche este inca actuala.
- Identitatea unica de admitere este exact (actor, tip, client_operation_id), conform PD-DISPATCH-01. Targetul din URI intra in digestul imuabil impreuna cu payloadul semantic si versiunile, nu creeaza un scope nou. Aceeasi identitate cu alt target/date/versiuni produce conflict. O operatie incerta nu este retrimisa cu alte versiuni/date.
- Validam inputurile finite, coordonate pereche, text dupa trim, bool versus numere cand contractul cere strictete, limite si calcul monetar coerent. Contractul monetar actual nu se schimba tacit prin refactor.
- Fisiere vizate: backend/models/order.py, un modul mic dedicat contractelor mutatiilor daca este justificat, backend/tests/test_order_mutation_contracts.py (nou). In primul lot nu activam scrieri v2 pe baza aplicatiei.
- Acceptare: contract legacy acoperit, schema noua respinge inputuri gresite, aceeasi cheie cu target diferit produce conflict, niciun actor/restaurant/driver falsificat din request; baseline relevant ramane verde.

### S2-02 - Creare comanda recuperabila

Depinde de S2-01. Owner backend; reviewer backend/data; QA Mongo real separat + HTTP.

- Admisie durabila a intentiei si ID stabil; insertul business, auditul critic si rezultatul trebuie legate prin protocolul ales, cu deadline finit.
- Refolosim regulile existente de restaurant, zona, taxa si numerotare. Nu folosim potrivirea aproximativa a numelui/adresei ca deduplicare distructiva.
- Revalidam contul, rolul si starea restaurantului la executie; doua procese nu creeaza doua comenzi pentru aceeasi intentie.
- GET/replay al operatiei cere autorizarea actuala. Raspuns pierdut dupa commit: clientul regaseste aceeasi comanda, nu genereaza imediat alta cheie.
- Pending/recovery este bounded si vizibil. Rezultatele testului Mongo anterior nu sunt copiate ca dovada a integrarii.
- Gate S2-COMPAT, obligatoriu INAINTE de activarea oricarei editari versionate: inventariem toti scriitorii comenzii/asignarii/pregatirii, inclusiv preparing/ready/status/problem, si ii trecem prin aceeasi revizie/CAS ori respingem explicit documentele v2. Nu presupunem ca rutele vechi incrementeaza deja version. Adaptorul extins multi-comanda din S2-04 nu amana aceasta protectie.
- Fisiere: orders.py, modul de operatii/persistenta dimensionat strict, database.py numai pentru indexuri/topologie dupa gate separat, teste create/idempotency/recovery. Nicio migrare/indexare live automata la import/startup in acest lot.
- Acceptare: double-click, doua taburi, replay dupa reload, doua procese, payload diferit, crash inainte/dupa commit, restaurant inchis intre validare si commit; un singur efect business si audit coerent. Gate S2-COMPAT include teste editare concurenta cu preparing/ready/pickup din client legacy: un singur castigator sau refuz explicit, fara update pierdut.

### S2-03 - Corectarea controlata a comenzilor

Depinde de S2-01/S2-02 si PASS pe S2-COMPAT, nu doar de existenta noii scheme. Owner backend + frontend in fisiere disjuncte; reviewer backend/frontend; QA admin si restaurant.

- Adaugam endpoint/dialoage de editare numai pentru campurile aprobate, cu revizie obligatorie pentru noul flux si audit al modificarilor. Nu permitem schimbarea id/restaurant/source/actor sau status printr-un patch generic.
- Regula conservatoare propusa: corectii operationale inainte de pickup; modificarile care afecteaza ruta invalideaza/revalideaza planul. Dupa pickup, schimbarea destinatiei/marfii este incident controlat, nu editare silentioasa. Se inchide aceasta regula in S2-01 inainte de activare.
- Doi admini pe acelasi snapshot: un castigator, al doilea vede conflict si starea curenta; nu pierdem textul introdus de utilizator.
- Formulare cu validare frontend/backend, loading, blocare sincrona la submit si mesaje de eroare. Pastram designul; adaugam numai controalele necesare.
- Fisiere: backend/models/order.py, backend/routers/orders.py, AdminDashboard.jsx, OrdersTab.jsx, componenta mica dedicata formularului/detaliului daca evita duplicare reala.
- Acceptare: editare valida, valori goale/limita, versiune veche, alt rol, status terminal, coordonate/taxa dependente, pierdere retea; nicio comanda veche schimbata neautorizat.

### S2-04 - Alocare si realocare manuala consistenta

Depinde de S2-01/S2-02; compatibilitate PD-DISPATCH-01 obligatorie. Owner backend; reviewer data/security; QA concurenta si cele trei roluri.

- Administratorul poate interveni manual fara sa ocoleasca invizibil capacitatea, ownership-ul, starea driverului sau custodia marfii.
- Canal comun pentru comanda/asignare/driver/rezultat/audit; nu adaugam current_order_ids cu increment/decrement in scrieri independente.
- Conservam pregatirea restaurantului la realocare, anulam explicit vechea oferta/asignare, folosim identitati/revizii, eliberam numai resursele comenzii afectate.
- Acceptare/realocare simultana: un singur rezultat; actiunea vechiului livrator nu confirma comanda noului livrator. Pickup deja efectuat: fara transfer automat.
- Pregatim adaptorul legacy si scenariile 1/2/5/10, dar pastram gate-ul multi inchis pana la consumatoare, GPS/ruta si verificari complete. Nu copiem protocol.py din proba direct in API fara adaptare async/auth/review.
- Fisiere: orders.py, driver.py/drivers.py strict unde este necesar, serviciu comun de asignare, AdminDashboard.jsx, orderWorkflow.js si consumatori afectati; fiecare subincrement are tests si review separat.
- Acceptare: doi admini, doi driveri aceeasi comanda, doua comenzi acelasi ultim slot, cont dezactivat/pauza, preparare modificata, expirare/replay, finalizare una nu sterge celelalte noua in contractul v2; regresie singulara intacta.

### S2-05 - Anulare si incidente fara pierderea custodiei

Depinde de S2-04. Owner backend/frontend; reviewer data; QA cancel/prepare/accept/pickup/deliver concurente.

- Anularea eligibila cere motiv, actor si revizie; nu sterge comanda sau istoricul. Inchide numai asignarea corespunzatoare.
- Dupa ridicare, retur/lipsa/refacere necesita incident si rezolutie explicita; nu marcam disparitia marfii printr-un simplu CANCELLED. Contractul nou modifica deliberat comportamentul actual numai dupa mapare si teste.
- Mentinem legatura comenzii cu problema/refacerea partiala, fara dublarea neintentionata a taxelor/creditului livratorului.
- Scopul acestei etape este siguranta starii si vizibilitatea minima; centrul complet de exceptii/notificari este Etapa 8, reconcilierea financiara avansata nu este introdusa tacit.
- Acceptare: anuleaza inainte pickup, dublu cancel, cancel versus deliver, actiune pe terminal, refacere partiala legata corect; roluri si bani/contori nemultiplicati.

### S2-06 - Lista, detaliu, istoric si refresh sigur

Depinde de contractele mutate stabilizate. Owner frontend cu endpointuri backend inguste; review frontend/backend; QA browser desktop/mobil.

- Separare activa/istoric, filtre relevante restaurant/status/driver/data, paginare server-side cu ordine stabila si limite explicite. Nu ascundem comenzile active dupa primele 100/1000 rezultate.
- Detaliu cu status executie si preparare distincte, driver, sursa, timpi si audit autorizat. Pastram functionalitatile si layoutul existente.
- Dupa mutatie, reconciliere dupa versiune; GET mai vechi nu suprascrie succesul nou. Esuarea refreshului dupa succes afiseaza date neactualizate, nu transforma mutatia reusita in esec/retry automat.
- Stari loading/empty/offline/server error si butoane disabled; single-flight pentru aceeasi intentie; read retry finit, fara retry orb pe mutatii.
- Fisiere: get_orders/detaliu in orders.py, api.js, AdminDashboard.jsx, OrdersTab.jsx, orderWorkflow.js; RestaurantApp.jsx/DriverApp.jsx numai pentru compatibilitate verificata.
- Acceptare: pagination cu timestamp egal, pagina goala/ultima pagina, filtru schimbat in timpul requestului, raspuns gresit/incomplet, refresh in mijlocul actiunii, timeout/401/403/409/5xx, desktop si mobil fara overlap.

### S2-07 - Audit si diagnostic coerent

Transversal S2-02..06, nu amanat dupa implementare. Owner backend; reviewer security/data; QA.

- Actor/rol/sursa/action/operation_ref/order_id/versiune before-after/motiv/ora server/request_id; fara parole, adrese, telefoane sau trasee GPS brute in loguri.
- Audit critic legat de commit; jurnalul extern nu este singura dovada si esecul lui nu dispare fara diagnostic. Outbox pentru efecte externe ulterioare, fara trimitere email/push reala in teste.
- Erori consecvente; un conflict nu devine 500, iar o baza indisponibila nu devine succes. Timpi/deadline/backoff finit si fara retry storm.
- Acceptare: injectie de eroare audit/DB, acces jurnal intre roluri, replay fara eveniment duplicat, verificare loguri fara PII si corelare operatie-efect.

### S2-08 - Inchidere demonstrata a etapei

Owner QA Codex independent de implementer; reviewer final Codex coordinator.

- Rerulam suitele existente relevante, noile teste si protected acceptance; nu stergem teste, nu relaxam validarile.
- Mediu sintetic separat pentru Mongo/HTTP si browser. Niciun test nu importa automat .env sau baza activa. Auth reala de test unde afirmam autentificare end-to-end; actor injectat este etichetat ca atare.
- Flux browser: admin creeaza -> restaurant pregateste -> admin aloca -> driver accepta -> restaurant gata -> pickup -> deliver -> istoric. Variante: realocare permisa, pauza/inchidere restaurant, dublu-click, doi admini, timeout/raspuns pierdut, reload/offline/revenire si problema/refacere.
- Review source, rezultate exacte, hashuri/build testat, screenshots utile fara PII, loguri sanitize. Esuarea unui test blocking tine lotul deschis.
- Etapa 2 complete_with_evidence numai pentru lucrarile si mediul verificate. Nu implica OCR/API functional, APK/IPA publicate, GPS de flota, auto-dispatch production sau capacitate 50/100.

## 5. Ordinea concreta a lucrului

1. Inchidem gate-ul fizic Etapa 1 si publicam raportul de stage closure. Planul de aici poate fi revizuit intre timp fara implementare Etapa 2.
2. S2-01 si testele contractului, apoi review independent. Acesta este urmatorul PR/increment logic, fara commit automat.
3. S2-02 create/replay; S2-07 merge impreuna cu fiecare mutatie, nu la final.
4. S2-03 editare si S2-04 alocare, separate pe loturi cu QA; S2-05 custodie/incidente dupa contractele lor.
5. S2-06 lista/detaliu/istoric si S2-08 regresie completa. Nu paralelizam doua persoane pe acelasi router fara lock.

Estimarea se revalideaza dupa primul lot integrat, nu promitem incheierea intregii etape intr-o zi pe baza numarului de teste ale unei probe.

## 6. Protectia proiectului si rollback

- Codex si subagenti interni OpenAI; fara OpenClaw/Claude. Owner, reviewer si QA au scope explicit si disjunct.
- Git este dirty; modificarile existente se pastreaza. Snapshot/hash/backup pentru fisierele atinse si lock pe order mutation/dispatch inainte de modificari cross-module.
- Toate experimentele pe date sintetice. Aplicarea indexurilor, conversia topologiei Mongo, migrarea de date reale sau activarea pe clienti necesita aprobare separata, chiar daca codul nou a trecut testele.
- Gate S2-MIGRATION inainte de activare: fixture-uri/copii autorizate cu version lipsa/null/invalid, duplicate si asignari orfane/conflictuale; dry-run aditiv cu backfill conservator si carantina explicita pentru cazuri ambigue; inventar inainte/dupa si reconciliere a counts/legaturilor/invariantilor; raport de duplicate inainte de index unic; backup si RESTORE demonstrat in mediu separat. Raportul, dovada restore si aprobarea distincta trebuie sa existe impreuna. Nu rulam acest backfill pe datele curente prin plan.
- Rollback de cod numai prin procedura revizuita si fara revertarea muncii altora. Daca exista asignari v2 active, oprirea ofertelor noi nu sterge asignarile si nu readuce scriitorul legacy peste ele. Recuperarea/livrarea comenzilor active continua pe protocolul lor.
- Rollback-ul acopera si create pending sau commit cu ACK pierdut, chiar fara asignari v2: se pastreaza operation_ref/identitatile/digesturile, lookup/replay/recovery si outbox-ul compatibile. Se opreste numai admiterea noua care nu mai poate fi servita, nu recuperarea intentiilor existente. Test obligatoriu: rollback dupa create incert, apoi aceeasi operatie recupereaza comanda originala fara duplicare sau modificarea payloadului.
- Fara commit/push/deploy, servicii platite, schimbari env/secrete, date client sau mesaje externe in acest pachet.
- Preview local la fiecare schimbare vizibila: http://127.0.0.1:3000; API http://127.0.0.1:8000/api/. Probele destructive/concurente ruleaza numai separat, nu pe aceste date curente.

## 7. Blocaje si ce nu blocheaza

| Conditie | Impact |
| --- | --- |
| Android/iPhone fizice, tester si cale build iOS neconfirmate | Impiedica PASS fizic si inchiderea gate-ului actual; pregatirea interna a probei continua |
| SDK Android nelocalizat in preflight | Impiedica APK local pana la toolchain verificat; bundle JS nu este APK |
| API restaurant/documentatie lipsa | Blocheaza conectorul specific Etapa 4, nu planul Etapei 2 |
| Topologie DB production/indexuri/migrare neaprobate | Blocheaza activarea transactionala live, nu implementarea/testarea pe mediu sintetic aprobat |
| Hub read-only returneaza faza comerciala istorica | Folosim memoria locala actuala; Catalin gestioneaza actualizarea Hub, nu o modificam aici |

Nu mai cerem aprobarea planului de 10 etape sau a mediului sintetic deja aprobate. Cerem doar accesul/dispozitivele/deciziile realmente lipsa, la momentul in care sunt necesare.
