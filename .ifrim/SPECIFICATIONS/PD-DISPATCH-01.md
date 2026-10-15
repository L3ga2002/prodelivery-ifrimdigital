## Clarificări client primite la 12 octombrie 2026

Cele 11 răspunsuri din al treilea set sunt integrate în `LOOP_REPORTS/2026-10-12-client-operational-rules-third-set.md`. Numerotarea acestui set este distinctă de cele două chestionare anterioare. Q7/Q8 retrag întrebările; decontările și închiderea zilei se păstrează. Q10 stabilește alocări obligatorii, fără drept de refuz comercial; confirmările tehnice și refuzurile pentru autorizare, capacitate ori date invalide rămân necesare.

Intake-ul documentar este închis după verificări independente de consistență și impact. Grilele și excepțiile financiare, plus exemplul pauzei A/B/C, rămân de completat. Reguli salvate nu înseamnă funcții implementate. Etapele 1 și 2 rămân deschise; ordinea este 1 → 2 → 3, cu loturile exacte din raport.

Răspunsurile clientului nu mai sunt amânate sau absente. Proba Android a8c este încheiată INCOMPLETE/heartbeat_gap, HONOR este restaurat și serviciile proprii sunt absente în dovada de recuperare. Vechile instrucțiuni PENDING, restaurare pending sau scoatere USB din corp sunt istorice și nu se execută. Restanțe Etapa 1: baterie, precizie în exterior, offline complet și clarificări; iOS fără Mac rămâne amânat.

Răspunsul Q10 supersedează refuzul comercial prevăzut în specificația de dispatch. Prototipurile și testele istorice sunt păstrate; schimbarea de contract trebuie verificată în lotul său. Hashurile și stările din tabelul istoric de mai jos sunt dovezi ale citirilor anterioare, nu hashuri ale fișierelor după acest prepend.

## Amendament de contract Q10 — 13 octombrie 2026

Versiune documentară propusă: PD-DISPATCH-01 v0.4-contract-candidate. Nu este versiune activă de API/DB sau implementare multi. Autoritate comercială: al treilea set de răspunsuri, Q10, `LOOP_REPORTS/2026-10-12-client-operational-rules-third-set.md:20,39`. Acest bloc supersedează numai semantica de acceptare opțională/refuz comercial din corpul istoric v0.3; păstrează restul invariantelor și amendamentele D0/A8.

Orice sarcină alocată valid este obligatorie. Confirmarea livratorului este ACK tehnic de primire; nu reprezintă alegerea de a executa sau refuza comercial. Autentificarea, ownership-ul, versiunile, capacitatea și eligibilitatea rămân verificate. O operație invalidă se respinge tehnic fără efect business; acesta nu este un drept de refuz al sarcinii.

Pentru incrementul viitor separăm două concepte în modelul tehnic propus:

1. Rezervare internă provizorie, înaintea unei sarcini obligatorii comise: consumă un loc rezervat; expirarea poate elibera acel loc numai prin operație atomică/CAS, fără sarcină comisă și fără custodie. Nu este ofertă opțională către driver. Politica și deadline-ul rezervării se fixează în packetul tehnic, fără TTL care șterge dovada.
2. Sarcină obligatorie comisă: `assigned_unacknowledged -> acknowledged -> picked_up -> delivered`, cu identitate și ownership durabile. Numele sunt conceptuale propuse; integrarea stabilește mappingul explicit cu stările legacy. Sarcina ocupă un loc activ din momentul commitului alocării obligatorii. ACK-ul nu creează și nu eliberează loc, nu schimbă proprietarul și nu produce venit sau pickup.

`open_count = reserved_count + active_count <= configured_order_limit` rămâne invariantul comun. Tranziția rezervare internă -> sarcină obligatorie mută reserved -> active în același commit; ACK-ul conservă contoarele. Ordinea de rezervare/commit/ACK și toate proiecțiile trebuie validate într-un singur protocol; nu coexistă două surse de autoritate.

Absența ACK-ului, timeoutul notificării, offline-ul ori pierderea răspunsului NU închid automat sarcina obligatorie comisă, NU eliberează locul și NU reasignează marfa. Starea de neconfirmare și incidentul/escaladarea către operator sunt vizibile. Pragurile și bugetele de retry se declară în packetul tehnic. Notificarea trimisă nu dovedește primirea sau execuția.

GET/replay și confirmarea tehnică a primirii nu autorizează navigarea pe o rută dirty. După ACK, pickup-ul cere în continuare pregătire READY, proprietar curent, versiuni și oprire executabilă. Livrarea fizic efectuată și raportarea incidentului rămân protejate conform regulii de custodie din v0.3; ACK-ul nu este o dovadă fizică.

Nu se implementează ruta/controlul de refuz comercial propus anterior `POST assignments/{id}/refuse`. Un astfel de request nu trebuie să elibereze sarcina/contorul/ruta. Contractul HTTP exact de respingere se fixează în implementare, în acord cu compatibilitatea; nu se inventează aici o rută deja existentă. Ruta accept/confirm, dacă se păstrează numele pentru compatibilitate, este documentată explicit ca ACK tehnic. Un nou nume și aliasul legacy necesită mapping și aceeași identitate semantică.

Reasignarea administrativă rămâne o operație autorizată distinctă, cu guarduri, înainte de pickup și invalidarea ownershipului vechi; nu este refuz comercial mascat. După pickup, nici ACK timeout, nici offline-ul nu transferă custodia. Incidentul și rezoluția fizică explicită rămân necesare.

Cererea de pauză/final de tură nu anulează sarcini. Regula Q11 privind A în curs, B asignată/gata și C gata/neasignată, precum și momentul opririi noilor alocări rămân neclarificate. Nu adoptăm implicit A+B ori A+B+C; fixtures tehnice poartă politica sintetică explicită și nu activează comportamentul comercial.

Corpul istoric de la invariantul 2, invalidarea rutei, stările assignment, API accept/refuse și cursa accept/expire se citește cu aceste amendamente. Cursa tehnică viitoare este rezervare internă/commit/expirare; sarcina comisă/ACK/timeout nu poate folosi expirarea rezervării pentru a elibera obligația. Identitățile, lease/fence, CAS și replay rămân recuperabile.

Compatibilitate: A8 `preparation_status` și pregătirea după asignare sunt păstrate. `current_order_id` rămâne doar proiecție în viitorul multi, nu contor autoritativ. Ledgerul existent `order_operations`, namespace-urile și pending-urile nu sunt rescrise/readmise prin `dispatch_operations`. Un adaptor și o versiune nouă trebuie să dovedească un singur efect logic și recovery pentru intențiile deja admise. Default-disabled și capabilitățile tuturor clienților rămân gate-uri; oprirea admisiilor noi nu abandonează sarcinile existente.

Acceptare de contract pentru viitorul increment: (a) un request de refuz comercial nu eliberează sarcina; (b) actor străin/refuz tehnic are zero writes business; (c) ACK duplicat și ACK pierdut/replay conservă ownership și contoare; (d) timeout/offline păstrează sarcina comisă și o face vizibilă operatorului; (e) două rezervări la ultimul loc au exact un câștigător; (f) expirarea unei rezervări nu poate închide o sarcină deja comisă; (g) reasignarea înainte pickup invalidează ACK-ul actorului vechi; (h) pickup/incident/realocare concurente păstrează custodia; (i) oprirea admisiei păstrează lookup/recovery. Sunt criterii planificate, nu teste executate de acest amendament.

Etapa 7 rămâne neînchisă. A0–A8 sunt loturi restaurant închise local, iar D0 este inventar static; niciunul nu certifică implementarea multi, ruta live sau capacitatea fizică.

# PD-DISPATCH-01 - specificatie de lucru pentru asignare multipla

Data: 2026-10-02. Versiune: 0.3. Statut: propunere tehnica verificabila, completata dupa review independent; nu functie implementata sau migrare aprobata.

Autoritate: `.ifrim/EXECUTION_PLAN_2026-09-26.md`, plan client v1.2 si cerinta explicita minimum 10 comenzi active pe ACELASI livrator. Nu introducem limita de doua comenzi. Nu obligam livratorul sa transporte zece comenzi incompatibile.

## 1. Contractele existente si discrepantele reale

| Suprafata verificata | Comportament actual | Cerinta pentru increment |
| --- | --- | --- |
| `backend/models/order.py:7` | NEW, PREPARING, READY, ASSIGNED, ACCEPTED, PICKED_UP, DELIVERED, CANCELLED intr-un singur enum | Pastreaza aceste valori pentru clientii vechi; stari operationale independente pentru clientii noi |
| `backend/models/driver.py:33` | `current_order_id` singular | Adaptor temporar; nu sursa autoritativa pentru capacitate |
| `backend/routers/orders.py:421` | PUT assign numai admin; a doua comanda respinsa; rezervare pe document driver | Cota activa + rezervata, versiune si protocol atomic pentru tot incrementul |
| `backend/routers/orders.py:519`, `:643` | preparing numai NEW; ready numai PREPARING | Pregatirea trebuie sa continue independent de oferta/asignare |
| `backend/routers/orders.py:30`, `:450` | Se poate asigna NEW/PREPARING/READY, apoi status devine ASSIGNED | Azi pregatirea/ready pot fi blocate dupa asignare; nu declara combinatia functionala |
| `backend/routers/orders.py:216`, `:705` | Driver modifica numai comanda lui, admin poate modifica; tranzitii controlate | Pastreaza ownership; valideaza si assignment_id, versiune, stop, stare restaurant |
| `backend/routers/orders.py:287`, `:308` | Finalizare/anulare elibereaza intreg `current_order_id` | Elibereaza numai resursele comenzii vizate, o singura data |
| `backend/routers/drivers.py:671`, `:697` | GPS fara timestamp/accuracy; pauza/offline blocate dupa camp singular | Date GPS validate si maturitate masurata; pauza verifica toate asignarile |
| `DriverApp.jsx:177`, `AdminDashboard.jsx:734`, `LiveMapPanel.jsx:147` | O comanda principala, driver liber numai fara camp singular, un traseu | Lista completa, urmatoarea oprire si sloturi reale; fara activare backend inaintea consumatorilor |
| `backend/routers/orders.py:326` | Feed exclude DELIVERED, nu CANCELLED | Defect separat `PD-CORE-CANCELLED-01`; istoricul nu este coada activa |

Acestea sunt dovezi citite in codul actual, nu o afirmatie ca toate fluxurile au fost executate. Aplicatia foloseste rolurile `admin`, `restaurant`, `driver`; nu inventam rol implementat de dispecer sau multi-tenancy care nu exista.

## 2. Invarianti care nu pot fi negociati de solver

1. Un `order_id` are maximum o asignare deschisa, inclusiv o oferta care rezerva locul. Niciun worker/admin nu poate crea alta fara inchiderea celei vechi in aceeasi operatie atomica.
2. `open_count = reserved_count + active_count <= configured_order_limit`. Acceptarea muta un loc rezervat in activ, nu mai consuma inca unul. Expirarea/refuzul elibereaza exact un loc prin CAS; timestamp expirat nu elibereaza singur slotul.
3. Cota de comenzi nu este capacitatea fizica. Volum/greutate/unitati transportate se verifica pe fiecare segment. Zece active pot avea pickup-uri succesive fara a transporta simultan zece.
4. Ridicarea precede livrarea. Pentru o comanda deja ridicata exista numai dropoff ramas si marfa intra in incarcarea initiala. Opririle executate sunt istoric imuabil, nu input reordonabil.
5. Livrarea/anularea uneia din zece nu pierde celelalte noua. Contorul, ruta, istoricul, castigurile si auditul se aplica o singura data logic.
6. Revalidarea la commit include ownership, status, versiuni, disponibilitate, GPS si politica; o propunere solver nu este autorizatie de scriere.
7. Repetarea dupa raspuns pierdut nu reaplica operatia. Aceeasi cheie cu alt payload este conflict, nu un nou succes.
8. Realocarea unei comenzi ridicate este incident asistat; nu se transfera automat. Anularea dupa pickup nu elimina dovada marfii aflate la driver.
9. Disponibilitatea, politica de capacitate si asignarea se serializeaza pe acelasi guard de driver. Un endpoint vechi nu poate ocoli protocolul nou.
10. Niciun output incomplet/nefezabil/expirat de la solver sau provider nu intra in ruta executabila. Nu folosim LLM pentru fiecare decizie.

## 3. Model incremental propus

Nu se creeaza colectiile/indexurile de mai jos in acest task.

| Model propus | Sursa autoritativa si responsabilitate |
| --- | --- |
| `dispatch_assignments` | `id`, `order_id`, `driver_id`, `is_open`, `state`, `version`, `offer_expires_at`, `accepted_at`, `closed_reason`. Autoritatea ownership-ului si rezervarii |
| `driver_dispatch_state` | Un document per driver: `version`, `policy_version`, `configured_order_limit`, `reserved_count`, `active_count`, `accepting_assignments`, `route_version`, `route_validity`, dependency_versions, opriri viitoare. Guard pentru serializarea capacity/route/status |
| `orders` existent | Campuri aditive `version`, `preparation_state`, timpi preparare, `dispatch_schema_version`. Ownership/status legacy sunt proiectii tranzactionale, nu alta sursa de capacitate |
| `dispatch_operations` | `operation_ref` unic global server-side; actor/tip/cheie client unice impreuna; digest imuabil, intentie durabila, pending/committed/rejected, lease/fence, rezultat si versiuni commit |
| `dispatch_outbox` | Evenimente dupa commit, identitate unica event_id, lease worker, retry finit; audit critic persistat in aceeasi tranzactie |

Indexuri propuse: assignment `order_id` unic partial pentru `is_open=true`; ID-uri unice; lookup driver+is_open; expirare prin worker explicit. Rezerva si activeaza dupa politica comuna. TTL nu inlocuieste reconcilierea si nu sterge asignari/audit/operatii necesare replay-ului.

Ruta are `stop_id`, `assignment_id`, `order_id`, tip pickup/dropoff, coordonate valide, service_duration, window, planned_at si versiune. Bani si date sensibile nu intra in cache-ul solverului. Route projection este verificata fata de asignari inainte de scriere.

Politica, pauza, dezactivarea si modificarea plafonului scriu guard-ul in protocol comun. Scaderea plafonului sub ocuparea curenta este respinsa sau intra explicit in drain mode (nu sterge comenzi). Politica initiala: respingere 409; nu implementam drain implicit. GPS se versioneaza separat cu timestamp server si sample sequence; se citeste din nou la commit cu freshness/accuracy policy. Schimbarea eligibilitatii care invalideaza decizia trebuie sa atinga guard-ul. Predicatul v2 nu este doar `is_active`: active sau delivery cu slot liber, accepting_assignments=true, cont activ, fara pauza/offline, GPS/politica validate. `break` poate avea is_active=true in codul actual, deci nu este eligibil automat.

Prepararea, accept/refuse/expire/reassign/cancel si orice schimbare a setului/opririlor invalideaza atomic ruta dependenta (`route_validity=dirty`, route_version si guard version incrementate) in acelasi commit, sau publica o ruta noua demonstrabil valida in acelasi commit. Dependency_versions includ toate order/preparation/assignment/policy revisions relevante, nu numai comanda pe care driverul actioneaza. GET dirty nu publica urmatoarea oprire drept instructiune executabila. Replanificatorul publica prin CAS pe acea revizie si toate dependentele; un calcul vechi care termina ultimul este respins. Prefixul executat ramane imuabil.

Pana la recalcul se blocheaza pickup nou si acceptarea unei oferte care nu mai are plan fezabil actual. Nu blocam inregistrarea unei livrari fizic efectuate pentru marfa deja ridicata: ownership, custody, order/assignment versions si actiunea explicita se valideaza independent, se inregistreaza stop-ul real, se elibereaza numai resursele lui si ruta ramane dirty pentru restul. Depasirea unei ferestre de planificare este incident/late audit, nu motiv sa ascundem o livrare reala. Raportarea incidentului, ready si GET/replay raman disponibile; ele nu autorizeaza deplasarea pe plan stale. Nicio alta actiune nu presupune ca ruta veche este sigura.

`current_order_id` reprezinta determinist comanda urmatoarei opriri executabile, sau prima asignare deschisa stabil ordonata daca toate sunt in asteptare; null numai la zero asignari deschise. Nu se foloseste pentru a deduce numarul/capacitatea. Clientii vechi nu pot opera un driver multi-comanda prin acest singur camp.

## 4. Protocol de concurenta si topologie

Topologia locala a fost citita prin `hello` la 2026-10-02: Single, fara replica set. Nu am efectuat tranzactii sau modificari. **Nu activam protocolul multi-document pe aceasta baza.** Sesiunile logice nu dovedesc suportul tranzactiilor.

Optiunea preferata pentru proba urmatoare: replica set separat, cu date sintetice, tranzactii multi-document si guard per driver. Este o propunere pentru mediu separat, nu autorizatie de conversie a bazei curente. Alternativa standalone necesita protocol de rezervare si recuperare crash-safe nou, cu dovezi; nu o alegem doar pentru a evita schimbarea infrastructurii.

Atomicitatea unui singur document nu acopera automat orders + drivers + assignments. CAS trebuie sa includa valoarea asteptata si sa o modifice. [MongoDB atomicity](https://www.mongodb.com/docs/manual/core/write-operations-atomicity/)

Flux propus pentru reserve/assign/reassign:

1. Autentificare; actor/rol/ownership din server; validare stricta si cheie operatie. Admite intentia durabila conform protocolului de mai jos si verifica replay cu accesul actual. Calculeaza propunerea in afara tranzactiei, pe snapshot versionat.
2. Deschide tranzactia in topologie verificata; toate query/write folosesc aceeasi sesiune. Citeste operatia existenta si starile curente. Nicio cerere externa sau solver in tranzactie.
3. Revalideaza ordinele, GPS/ETA si politica. Modifica guard-urile cu CAS pe versiuni, in ordine stabila a driver_id pentru realocare. Verifica slotul nou; versiunea route/order trebuie sa corespunda snapshot-ului. Un conflict necesita snapshot/propunere noua, nu suprascriere.
4. Schimba assignment, contoare, ruta, order projection, driver projection, audit critic, operation result si outbox in aceeasi tranzactie. Refuz la orice invariant invalid; niciun counter separat incrementeaza in afara tranzactiei.
5. Commit cu write concern/read concern adecvate mediului, timeout explicit si rezultat identificabil. Abia dupa commit evenimentele pot fi publicate de worker.
6. Clientul primeste rezultatul original al operatiunii si state/version actual separat, daca are acces. Nu pretindem ca statusul original este inca actual la replay.

Retry: plafon global de cerere si numar maxim de tentative. Transient transaction retry poate reexecuta corpul: fara email, notificare, contor extern sau ID regenerat in corp. Unknown commit se rezolva cu acelasi transaction/operation identity; nu se executa orb o operatie noua. Daca rezultatul ramane incert, raspuns `operation_pending` si GET operation_ref, nu eroare care indeamna la dublare. Driverul poate reexecuta callback-ul; helper-ul concret si deadline-urile trebuie probate, nu presupuse. [PyMongo transactions](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/)

### Operatii pending durabile si adresare neambigua (R1/R3)

Admisia creeaza inainte de executia business un document pending durabil, cu `operation_ref` server-side UUID unic global, actor din autentificare, tip, client_operation_id, targets din URI, request semantic si digest imuabile, expected_versions, created_at, deadline/recovery metadata. Indexul actor+tip+client_operation_id deduplica admisia; operation_ref este adresa GET unica. Nu acceptam un actor arbitrar in lookup. Digestul canonic include tipul, order/assignment/stop targets, payload validat si expected_versions (incluse intentionat). Alt target, tip sau payload sub aceeasi identitate este conflict, nu replay pentru alta resursa.

| Stare operatie | Tranzitie si dovada |
| --- | --- |
| pending fara claim | Worker/client autorizat face CAS lease+fence monoton; admisia nu modifica assignments/ordine/cota |
| pending claimed | Un executor detine fence-ul. Tranzactia business verifica si modifica acelasi document operations prin CAS; rezultatul committed si toate efectele business se comit impreuna |
| pending, commit incert | In sesiunea vie se incearca acelasi commit in deadline. Dupa restart recovery citeste durabil identitatea; nu interpreta lipsa rezultatului drept abort. Doi recovereri se serializeaza prin claim/fence |
| committed | Rezultat original imuabil, stare actuala separata; replay nu reaplica operatia sau outbox |
| rejected | Eroare definitiva stocata cu motiv/versiuni, numai dupa arbitrare prin CAS/fence pe documentul operatiei; nu se marcheaza rejected doar pentru timeout sau absenta rezultatului |

Lease expirata permite preluare CAS cu fence nou; executorul vechi nu mai poate comite deoarece tranzactia trebuie sa scrie documentul operations cu fence-ul curent. Daca vechiul commit castiga, noul claim pending nu mai potriveste; daca noul fence castiga, tranzactia veche intra in conflict. Validam ambele ordini pe Mongo separat. Reexecutia dupa restart, spre deosebire de retry commit in sesiunea vie, este o noua tranzactie numai sub acelasi operation_ref/digest/fence valid; CAS-ul rezultatului garanteaza o singura aplicare logica. Intentia nu trebuie sa contina PII inutil; accesul/revocarea sunt revalidate la executie si GET.

Admisie cu ACK incert: clientul pastreaza cheia identica si reincearca admisia, nu genereaza alta; serverul cauta tupla completa cu accesul actual. GET dupa operation_ref absent raspunde 404/not_found, fara a-l interpreta ca rejected; clientul care nu a primit ref poate readmite cheia originala. Expirarea cheilor nu este automata in timpul operatiilor/comenzilor active; politica de retentie trebuie sa permita replay conform SLA adoptat. Recovery e finit per executie, cu backoff, alerte si incident persistent pentru pending vechi; nu il abandoneaza sau sterge dupa cateva incercari.

Un 409 definitiv permite refresh si operatie noua cu cheie noua. Un pending/timeout nu permite schimbarea payloadului/expected_versions aceleiasi operatii: mai intai se afla rezultatul sau se arbitreaza terminal in recovery. Intentia pending este exceptia explicita de metadate la regula "zero schimbari inainte de commit business"; niciun slot, order, bani sau notificare nu este schimbat prin simpla admisie.

Propunere initiala pentru proba, nu SLA: 2 secunde solver, 10 secunde cerere interna, maximum 3 incercari tranzactionale in acelasi deadline; timeout provider 3 secunde cu maximum o reluare numai pentru citire si in bugetul global. Deadlines trebuie aliniate client/server/DB; la commit incert continua reconcilierea durabila fara blocarea clientului nelimitat.

## 5. Stari independente si compatibilitate

Preparare: `new -> preparing -> ready`. Expirarea timerului semnaleaza intarziere; NU inseamna gata. Anularea este lifecycle terminal separat. Pickup necesita `preparation_state=ready` si asignare acceptata, cu ownership curent. Nu deduce ready din ASSIGNED/ACCEPTED.

Assignment: `reserved -> accepted -> picked_up -> delivered`, cu ramuri `reserved -> expired/refused/released` si `accepted -> released` doar inainte de pickup. Direct admin assign creeaza accepted sau reserved? Politica pentru compatibilitate: reserved, apoi driver accepta explicit, ca actualul ASSIGNED -> ACCEPTED; aceeasi cota se pastreaza. Nu confundam oferta trimisa cu acceptare.

`delivered`, `expired`, `refused`, `released` inchid asignarea. `picked_up` nu expira. Un incident dupa pickup mentine ocuparea si stop-ul ramas pana la rezolutie explicita, fara migrare de status public inventata.

### Incident dupa pickup si rezolutii (R4)

Incident intern: ID, assignment/order, `open/resolved`, motiv, actor, version, custody_holder, timestamps si resolution/evidence references. Este o stare ortogonala asignarii, nu o nota care poate fi ignorata. Deschiderea incidentei atinge guard/order/route versions si mentine active_count/load; CANCELLED nu se proiecteaza pana la rezolutia fizica. Fiecare rezolutie foloseste operation_ref/CAS/idempotenta/audit; o singura rezolutie terminala poate castiga.

| Rezolutie | Actor/conditie | Efecte exacte |
| --- | --- | --- |
| delivered_confirmed | Driverul proprietar inregistreaza livrarea efectiva; orice restrictie activa de incident necesita aprobarea explicita admin conform politicii convenite | picked_up -> delivered, incident resolved, active-- o data, elimina dropoff ramas, load scade cu marfa comenzii; crediteaza numai efectele unei livrari reale |
| returned_confirmed | Admin, cu receptia marfii confirmata de restaurantul proprietar si evidence/timp/actor | picked_up -> returned intern, is_open=false, incident resolved, active--/load-- numai pentru aceasta comanda; legacy CANCELLED cu motiv returned, nu DELIVERED; zero livrare/castig fictiv; bani deja incasati raman reconciliere explicita, nu se rescriu |
| transfer_requested | Admin solicita transfer asistat; nu este transfer efectuat | Pastreaza picked_up/open/ocuparea pe driverul curent si incidentul; niciun driver nou nu detine implicit marfa |

Transferul fizic intre driveri NU este suportat prin assign/reassign generic in versiunea initiala. Ramane fail-closed/manual incident pana la pachet dedicat care defineste confirmarea custodiei ambilor driveri, capacitatea si slotul nou, lineage si transferul atomic. Nu marcam delivered/returned pentru a simula transferul. Returul confirmat si livrarea reala ofera rezolutii terminale explicite fara a promite aici un feature nou de handover. In acest task acestea sunt contracte, nu rute implementate.

Projectia legacy a order.status: lifecycle CANCELLED/DELIVERED are prioritate; apoi PICKED_UP/ACCEPTED/ASSIGNED; daca nu exista asignare deschisa, preparation READY/PREPARING/NEW. Starea de preparare ramane disponibila separat pentru clientii noi. Anulare dupa pickup: incident mai intai, nu CANCELLED proiectat si slot eliberat automat.

Backfill este conservator: NEW/PREPARING/READY pot furniza preparare; statusurile ASSIGNED/ACCEPTED nu dovedesc gata; foloseste numai campuri/time stamps consistente. Datele ambigue merg in raport de reconciliere, nu sunt inventate. DELIVERED/CANCELLED raman istoric. Camp singular fara order valid sau mai multe orders active deja existente reprezinta discrepanta de inventar.

Pana cand v2 si toate consumatoarele sunt gata, feature gate ramane inchis pentru multi-comanda si pregatire/asignare simultana. Nu activam partial numai modelul. Un endpoint v1 fie trece prin acelasi service si guard, fie respinge explicit actiunea pe driver v2/multi-comanda; nu lasa scrieri legacy directe care invalideaza asignarile. Activarea include gate de capabilitati pe versiunea aplicatiei admin/restaurant/driver; o sesiune legacy nu primeste o ruta multipla pe care o poate vedea doar partial. Restaurantul trebuie sa poata marca prepararea separat chiar cand comanda este asignata. Un refresh sau reconnect al clientului vechi nu ocoleste gate-ul server-side.

## 6. Contracte API aditive propuse (nu rute existente)

Prefix propus `/api/dispatch/v2`. Identitatile sunt scoped la instalatia curenta si legate de restaurante/livratori autentificati, fara camp tenant inventat ca implementat.

Fiecare mutatie: `operation_id`, `expected_order_version`, versiunile driver/route afectate, payload validat extra-forbid. Actorul, ora si ownership nu sunt acceptate de la client ca autoritate. ID invalid, bool in loc de int, float nefinita, coordonate/window invalide sunt respinse inainte de solver/DB.

| Operatie propusa | Rol si restrictii | Efect atomic |
| --- | --- | --- |
| POST assignments/reserve | admin sau worker intern autentificat; NEW/PREPARING/READY fara asignare deschisa | Rezerva slot, oferta cu expirare server; pregatirea nu se pierde |
| POST assignments/{id}/accept | driver destinatar, oferta neexpirata si versiuni actuale | reserved--, active++; ownership si ruta stabile |
| POST assignments/{id}/refuse | driver destinatar, numai reserved | Elibereaza slot/opriri; comanda revine in coada fara pierderea prepararii |
| POST assignments/{id}/reassign | admin; numai inainte pickup | Transfer intre guard-uri, inchide vechea oferta, invalideaza tokenul vechi |
| POST stops/{id}/pickup | driver asignat, accepted, ready, stop curent executabil | Marcheaza pickup, route_version++; incarcare actualizata; nu elibereaza quota |
| POST stops/{id}/deliver | driver asignat, picked_up, stop dropoff ramas al acelei asignari si livrare fizica explicit confirmata; incident restrictions respectate | Ruta valida: flux normal. Ruta dirty: exceptia de inregistrare a faptului fizic din sectiunea 3, fara a cere stop planificat executabil sau a autoriza navigarea stale; inchide numai asignarea, active--, bani/audit o singura data, restul rutei ramane dirty |
| POST orders/{id}/cancel | admin sau restaurantul proprietar; driver cere incident conform politicii | Inainte pickup elibereaza resurse; dupa pickup incident fara eliberare oarba |
| PUT orders/{id}/preparation | admin/restaurantul proprietar | Preparare separata; invalideaza atomic ruta dependenta pana la recalcul CAS, nu schimbare implicita de gata |
| GET drivers/me/dispatch | driver; admin prin ruta scoped separata | Snapshot coerent: asignari, opriri, slots, versiuni, server_time, motive si route_validity; dirty nu expune instructiuni de ruta executabile |
| GET operations/{operation_ref} | actor sau admin autorizat; lookup unic server-side | pending/committed/rejected, rezultat original si stare curenta distincta; 404 nu este dovada de abort |

Raspuns propus: succes `operation_id`, `operation_ref`, `applied`, `replayed`, `versions`, `state`; eroare `error.code`, `error.message`, `retryable`, `request_id`, conflict versions daca accesul permite. 422 invalid, 401 autentificare, 403 ownership, 404 lipsa resursa, 409 stare/capacitate/versiune, 503 indisponibilitate temporara; pending admis este 202 cu operation_ref si Retry-After, nu applied=true. Frontend nu transforma timeout in succes. API legacy ramane contractual pana la incrementul aprobat.

## 7. Solver: propune, nu aloca

Pipeline: valideaza -> filtreaza eligibilitate -> snapshot -> matrice aprobata -> calculeaza -> verifica independent -> revalideaza -> commit. Nu copilam cod proprietar; OR-Tools este candidat evaluat separat.

Input: ID-uri stabile, coordonate validate, timpi de drum directie-specifici, timestamps/accuracy GPS, preparare/window, durata de serviciu, capacitate, comenzi active/rezervate si opriri finalizate. Distanta geometrica poate prefiltra; nu este ETA de productie. Lipsa adresei/geocodarii sau o matrice incompleta produce motiv vizibil `missing_location`/`routing_unavailable`.

Obiectiv initial: minimizeaza timpul de drum pe setul fezabil, cu restrictii dure pentru precedenta/capacitate/ferestre. Fairness, prioritate si intarziere ponderata se adauga numai dupa fixture-uri si politica explicita; nu promitem algoritm identic unei platforme externe sau optim global. Proba actuala cu un driver nu demonstreaza alegerea intre 100 driveri.

Cercetarea Glovo ceruta de Catalin este separata in `LOOP_REPORTS/2026-10-02-glovo-dispatch-factors.md`. Pentru ProDelivery propunem ora/trafic/meteo ca inputuri ale estimatorului, nu ponderi ascunse inventate; active workload si fairness normalizata pe timpul disponibil in tura, nu numarul brut zilnic. Proba sintetica actuala nu implementeaza acesti estimatori, fairness sau alegerea intre mai multi driveri. Nicio informatie despre bonusuri/scor calendar extern nu este reinterpretata ca regula de matching dovedita.

Toate opririle necesare trebuie sa existe exact o data. Outputul verifica ID-urile, legatura assignment, precedenta, load initial/final, ferestre, durata, route version si prefix executat. Un subset returnat nu inseamna ca restul comenzilor sunt alocate. Lipsa solutiei in buget nu dovedeste matematic imposibilitatea: diferentiem `invalid_input`, `no_solution_in_budget`, `unfeasible_precheck` si succes fezabil.

La timeout datele/assignments nu se schimba. Pastram ruta anterior validata NUMAI daca este inca valida pe starea actuala; altfel exceptie/coada manuala. Cache matrice legat de provider/versiune/direction/time bucket, cu TTL si rate/cost limits; fara adrese/telefon in log. Bugetul solverului nu acopera automat overhead si import; probele masoara end-to-end. [OR-Tools routing options](https://developers.google.com/optimization/routing/routing_options)

## 8. Crash, reconciliere si efecte externe

| Moment | Recuperare ceruta |
| --- | --- |
| Inainte de commit business | Numai intentie pending poate fi vizibila; zero schimbari business. Retry cu aceeasi cheie/payload; nu modifica versiunile unei operatii incerte |
| Commit reusit, raspuns pierdut | GET/replay operation gaseste rezultatul; nu contor/bani/opriri duble |
| Commit incert | Identitate pastrata; reconciliere limitata si pending vizibil; nu schimbam payload |
| Notificare neconfirmata | Outbox retry finit; event_id acelasi. Livrare at-least-once, clientul deduplica; fara promisiune exactly-once pentru provider |
| Oferta expira | Worker CAS rezervare in aceeasi tranzactie cu contor/ruta; race accept/expire are un singur castigator |
| Proiectie/contor inconsistent | Alert si quarantine pe driver/order; raport read-only intai. Reparare numai determinista si autorizata, fara stergere masiva |
| Server restarteaza | Lease expirate recuperate; operation/outbox persistente. Fara lock doar in memoria procesului |

Audit critic: actor, rol, action, operation_id, entity ids, before/after version, motiv, ora server, request_id. Nu logam adrese, telefoane, CNP, secrete sau coordonate istorice inutile. Retry extern nu retrimite bani si nu reaplica statusul.

## 9. Incrementare, migrare si gate-uri

1. Pure rules + fixture-uri: tranzitii, capacitate, contracte si ruta; feature flag off, fara schimbari live.
2. Integrare Mongo pe replica set SEPARAT autorizat; doua procese concurente, crash injection, D02/D05/D08/D11/D15. Proba nu se executa pe Mongo actual.
3. Dry-run aditiv pe copie autorizata: inventar counts, orphan/conflicting assignments, mapare prep, proiectii; indexuri unice numai dupa raportul duplicate si backup/restore verificat.
4. Backend compatibility service comun, pregatire decuplata, apoi admin/restaurant/driver/harta. Review independent si fluxuri browser complete in mediu sintetic.
5. Pilot cu feature gate pentru un grup explicit; monitorizare route/conflict/drift/outbox. Oprirea gate-ului opreste OFERTELE NOI; comenzile multi deja active continua cu service-ul v2. Ofertele deja rezervate pot fi acceptate pana la expirare numai dupa revalidarea planului actual, sau expira/release prin acelasi protocol; oprirea gate-ului nu le sterge si nu decrementeaza global. Pregatire, incident, livrare, recovery si outbox continua. Nu revenim la cod singular si nu stergem datele noi.

Activarea tranzactionala/migrarea/etapele viitoare necesita aprobare separata. Specificatia poate ramane reviewed draft pana la dovada concurentei si deciziile operationale; nu mascati un gate lipsa printr-un procent.

## 10. Matrice de verificare si limite

D01-D20 din plan raman contractul de verificare. Proba sintetica demonstreaza numai componenta de ruta din D01/D04/D14/D16 si inputuri asociate. Nu demonstra assignment durable, acceptare reala, quota concurenta, GPS, offline mobil, bani sau 50/100.

| Gate | Dovada necesara |
| --- | --- |
| M1 Model/compatibilitate | Review pe sursa si spec, mapare de status explicita; fara camp legacy folosit drept autoritate |
| M2 Solver | 1/2/5/10 acelasi driver; feasible/infeasible; picked-up; input/output invalid; timeout finite; rezultate independente |
| M3 Concurenta | Mongo real separat: ultimul slot, acelasi order doi driveri, accept vs expire, reserve/accept vs pause/offline/disable/plafon in ambele ordini, cancel vs deliver, recovery/fence/unknown commit, alte noua pastrate |
| M4 End-to-end | Admin/restaurant/driver; invalid/duplicate/loading/error/refresh; fara status vechi sau actiuni ascunse |
| M5 Mobil | Android/iOS fizic: GPS/fundal/permisiuni/baterie/revenire; nu echivalam browser cu telefon |
| M6 Capacitate sistem | Benchmark profil convenit, percentile, infrastructura si durata; 50 restaurante/100 driveri nu sunt promise dintr-o proba cu 10 comenzi |

Decizii operationale inca de confirmat inainte de activare: unitati/volume vehicul, ferestre maxime de livrare si calitate, timeout oferta, politica offline cu marfa, controlul urmatoarei opriri si proba dispozitivelor. Folosim fixture-uri explicite intre timp, nu valori ascunse prezentate ca decizii ale clientului.
