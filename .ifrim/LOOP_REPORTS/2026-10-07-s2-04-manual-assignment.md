# ProDelivery - S2-04 alocare manuala recuperabila

Data: 2026-10-07. Cerere: Catalin a solicitat plan pentru inchiderea Etapei2
si executia. Planul ramas este salvat separat, fara renumerotarea fazelor.
Status: source integrated14files; independent review scopedPASS. Final recovery
aggregate:532passed,0failed. Etapa2 comerciala ramane in_progress.
Nu este lansare, activare live sau livrarea alocarii automate/minimum10.

## Implementare concreta

1. Asignare si realocare manuala pe comenzi versionate pre-accept: CAS n/n+1,
   disponibilitate/rol curent, tranzactie claim nou + release vechi potrivit +
   comanda + audit embedded/global + rezultat durabil. Nu exista efect partial.
2. Pregatirea/timerul restaurantului, produsele, contactul si valorile financiare
   raman intacte. Custodia acceptata/ridicata si statusurile terminale nu se muta.
3. Doi admini/o comanda, doua comenzi/un slot, pauza/dezactivare concurenta,
   orphan claims, versiuni/ledger/date malformate sunt tratate conservator.
4. Intentie actor-scoped persistata fara date client, lookup/bodyless resume,
   retry finit/deadline, acelasi ID dupa ACKlost/reload/offline/tabs. Fara fallback
   legacy sau generarea unui ID nou cat rezultatul este incert.
5. UI actual pastrat, cu loading/disabled, confirmare durabila, conflict si
   actiune explicita de reincarcare pentru o intentie noua dupa refuz.
6. Header comparativ X-Expected-Actor-ID pe toate operatiile si legacy PUT,
   verificat fata de autentificarea REALA cookie-first inainte de business DB.
   Un cookie schimbat in alt tab nu poate readmite sub alt admin intentia veche.
7. Writeri adiacenti reparati: statusul livratorului nu mai copiaza claimul vechi;
   CAS la status/disable previne suprascrierea alocarii concurente. Disable
   partial cu user-write esuat ramane blocat503/retry, nu compensare nesigura.
8. UI/API legacy refuza reprezentari multiple necunoscute si date imposibile.
   Revenirea explicit active nu este blocata de un timer de pauza valid pastrat.

## Fisiere integrate si motiv

| Fisier | Motiv |
| --- | --- |
| backend/utils/order_assignment.py (nou) | Tranzactie/CAS, ledger, audit, recovery, roluri/disponibilitate curente |
| backend/routers/order_operations.py | Patru rute additive, owner header, no-store, response/body deadline |
| backend/routers/orders.py | Numai compatibilitatea assign: actor, representation/date/availability CAS |
| backend/routers/drivers.py | Numai status/disable CAS si raspuns explicit la user-write partial |
| frontend/src/pages/AdminDashboard.jsx | Conectarea dialogului actual, recovery/reassign, disabled/loading/conflict |
| frontend/src/lib/orderAssignmentRecovery.js (nou) | Validare snapshot/receipt, intentie persistenta, Web Locks, retry finit |
| frontend/src/hooks/useOrderAssignmentRecovery.js (nou) | Transport izolat, actor/session guards, storage events, loading |
| backend/tests/test_order_assignment_recovery.py (nou) |134 teste Mongo, concurrency/fault rollback/representation/orphans |
| backend/tests/test_order_assignment_http.py (nou) |37 teste contracte HTTP/autorizare/no-store/bodyless/deadline |
| backend/tests/test_order_assignment_driver_status.py (nou) |13 teste writeri status/disable intercalati cu alocarea reala |
| backend/tests/test_order_assignment_owner_guard.py (nou) |73 teste autentificare cookie/Bearer reala cu JWT/DB sintetice |
| frontend/src/lib/orderAssignmentRecovery.test.js (nou) |254 teste recovery/receipt/types/representation/date/session |
| frontend/src/hooks/useOrderAssignmentRecovery.test.jsx (nou) |36 teste lifecycle/session/transport/header/tab/loading |
| frontend/src/pages/AdminDashboard.assignment.test.jsx (nou) |15 teste dialog real si actiuni/refuzuri/loading/owner |

Total562 teste noi. Nu au fost rescrise module mari, sterse feature-uri sau
schimbate arhitectura/designul. Nu au fost modificate teste protejate existente.
4 originale de sursa au backup; toate14 au hashguard inainte/dupa integrare.
Backup-ul si fiecare SHA256 sunt in QA_RUNS/.../publication.json. Istoricul
memoriei este pastrat byte-for-byte la inserarea checkpointurilor noi.

## Review independent

Codex: coordonare/integratie, writeri adiacenti, QA browser/regresie/checkpoint.
Dirac: owner backend; Rawls: owner frontend; Aristotle: teste independente;
Tesla: reviewer read-only. Numai subagenti interni Codex, fara OpenClaw/Claude.
Reviewerul nu si-a fixat/aprobat singur codul. R1-R5 CLOSED pe snapshot-ul exact:

- R1/P1: writer legacy status/disable putea suprascrie claimul nou.
- R2/P1: cookie actor switch putea atribui intentia veche altui cont.
- R3/P2: frontend omitted backend-known multi fields.
- R4/P2: JS normaliza calendar imposibil drept pauza expirata.
- R5/P2: active era blocat pana la expirarea unui timer vechi valid.

Raportul independent complet si hashurile finale: REVIEW_S2_04.md.

## Dovezi actuale, nu rezultate istorice

- Regresie unit/compat/roluri/middleware pe sursa integrata:1750 passed,
 84 subtests passed. Log backend-unit-verified-final.txt.3 deprecation warnings
 (httpx TestClient si FastAPI on_event); nu sunt erori/build failures.
- Create/edit/assign Mongo+HTTP pe sursa integrata:532passed,0failed in420.47s,
 backend-recovery-verified-fresh.txt.1 avertisment intentionat Pydantic pentru
 payload construit malformat intr-un test de revalidare. Testele nu au fost editate.
- Frontend integrat:674 passed,10 suites,0 failed/pending,21.629s.
- Build pe aceleasi surse frontend cu hash exact:0errors/0warnings,77.524s.
- Lint6fisiere modificate:0errors/0warnings. Git diff --check exit0; doua
 avertismente CRLF pe fisiere preexistente, fara reformatare in acest lot.
- Browser integrat3000/admin si /driver, API integrat sintetic57230:
 12 grupuri PASS,0pageerrors; desktop1440x1000 si mobil390x844. Screenshoturi
 inspectate vizual si bounds/overflow verificate. Date exclusiv sintetice.
- Preview3000/login si API8000/api/ HTTP200 prin rute publice nemutatoare.
- Total distinct, fara a aduna rerularile:2956passed =1750unit+532recovery+674
 frontend.84subtests separat;12grupuri browser separat.6teste live necertificate.

Browser: selectie lipsa/slow/dublu-click; conflict real/fresh snapshot/new ID;
realocare si timer pastrat; pauza dupa selectie; lostACK; offline/revenire;
lookup503/reload/ID pastrat; doua taburi; default-disabled/mobil; legacy fara
promovare; create/correction dialoguri adiacente; driver pauza->active->assign.
Nu echivala zero pageerrors cu zero global console/network errors:401 pe login
anonim si faulturile QA intentionate sunt distincte. Nu s-au folosit conturi reale.

## RED si cauze retinute

- Testele noi initiale134/HTTP au avut54 RED,114pass:52 snapshots omiteau
 actor-admission fence legitim,1 fixtureint nu era BSON-serializabil,1 camp de
 anulare nu era canonic. QA a corectat oracolele exact si a adaugat3 rollback
 cazuri, fara eliminare/xfail;171passed. Reviewerul a auditat explicit delta.
- Owner guard initial67:7RED/60pass, cod422 legacy inventat in oracle. A fost
 corectat exact perruta,6cazuri adaugate,73pass cu hash stabil. Parent collection
 suprapusa acelei editari a raportat7RED/244pass; stable257case rerun a trecut.
 Sursele nu au fost schimbate pentru a se potrivi unui cod de eroare inventat.
- Initial mixed published run:2281passed,4failed,3setup errors.6 cazuri HTTP
 cer un backend/credentiale/date de integrare; izolarea le blocheaza. Middleware
 import avea client/config lipsa in harness; s-a completat numai configuratia
 sintetica si testul original a trecut (apoi intreaga selectie1750 a trecut).
 Nu au fost citite credentiale sau mutata suita pe baza reala ca sa devina verde.
- Primul recovery aggregate:531passed/1RED. Cazul protejat50ms session_delay
 a primit pending in buget, dar fault injection nu a fost atins (injections0),
 nu overlap/cleanup neserializat. Hash test3D6172384CF34B111DA471E7410D2C9B08E5B6FF57B8A36C2529253F6A728801
 a ramas neschimbat. Doua cazuri izolate au trecut pe fixture proaspat in8.73s;
 rerularea integrala seriala532 a trecut in420.47s. Riscul timing ramane
 documentat, nu este ascuns sau declarat reparat printr-un retry verde.
- Primul browser published a trecut9grupuri, apoi GET harness/__qa/state a avut
 ECONNRESET. Conexiuni QA explicite close, fara mutation retry:11grupuri au
 trecut, apoi12 cu driver realUI. Am pastrat ambele rezultate in evidenta.
- Sandbox Windows a blocat event-loop/self-pipe/Jest realpath/ESLint cache.
 Au fost folosite verificari autorizate nesandboxate si cache build separat;
 niciun product test nu a fost sters pentru aceste limitari ale runnerului.
- Primul fixture stop a depasit20s la flush dupa multe baze sintetice; instanta
 s-a oprit, un nou PID/dbpath unic a fost verificat. Nimic strain nu a fost ucis,
 datele anterioare au ramas. Harness-ul asteapta acum120s la stop.

## Ce ramane si ordinea de inchidere

1. S2-05: custodie accept/pickup/deliver, cancel si incidente/refaceri recuperabile.
2. S2-06: liste paginate complete, detaliu/istoric autorizat, stale reads.
3. S2-07/08: audit transversal si regresia unei zile reale pe toate rolurile.
4. Gate distinct live: migration/exclusion/reconciliation, restore, retention,
   politici financiare ambigue confirmate si aprobare pentru DB/markeri/deploy.

Niciun marker nu a fost activat/creat pe baza aplicatiei, niciun index/topology/
schema/data client modificat. Versioned custody ramane refuzat pana la S2-05;
nu activa o creare versionata reala inaintea conversiei writerilor necesari.
Legacy assign ramane two-phase, nu recovery tranzactional. Legacy disable are
partial-state503honest/retry, nu doua-documente atomice. Optional actor header
protejeaza transportul nou care il trimite, nu pretinde auth-global hardening.

Nu sunt certificate Android/iOS fizic, PWA cache, GPS/background, OCR/API extern,
alocare automata/minimum10, load50/100, store, restore sau deploy. Noile probe
real-auth73 sunt ASGI sintetice, nu toate6teste live de auth/tenancy. Doar codul
si dovezile acestui lot sunt integrate. Fara commit/push/deploy, OpenClaw/Claude,
Hub mutation, secret/envfile/private/tmp/uploads sau date reale.
