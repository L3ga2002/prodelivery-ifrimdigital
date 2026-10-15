# ProDelivery — plan extins până la pilot și predare

Data: 2026-10-10, Europe/Bucharest.
ID: PD-MASTER-ROADMAP-2026-10-10.
Stare: PROPUNERE DE PLAN. Document nou, pregătit și verificat prin citire; loturile de mai jos nu sunt declarate implementate, testate sau activate.

Rezultat urmărit: admin web, restaurant PWA, livrator Android/iOS, introducere manuală + OCR confirmat de om + un conector API, GPS de tură, alocare automată pentru minimum 10 comenzi fezabile pe același livrator, apoi pilot, publicare și predare. Planul folosește proiectul existent și păstrează cele zece etape comerciale aprobate.

## Punctul de pornire

- BOOST01–03 au dovezi și checkpointuri proprii. Nu le transformăm în loturi noi și nu refacem module care satisfac deja contractul.
- Etapa 2 este încă in_progress. S2-05B, S2-08 și acceptarea comercială nu sunt închise. Gate-urile native ale Etapei 1 rămân distincte; trecerea formală între etape respectă acceptarea sau derogarea explicită aplicabilă.
- Ultimul raport BOOST03 conține 31 cazuri noi distincte PASS. Regresia frontend rămâne 1161 PASS / 15 FAIL / 1 SKIP; cele 5 FAIL backend istorice nu sunt reetichetate ca PASS. Nu se modifică testele protejate pentru a obține verde.
- Modelul aplicației încă impune o comandă neînchisă per livrator. PD-DISPATCH-01 v0.3 și proba sintetică 1/2/5/10 din 2 octombrie sunt baza următorului increment, nu dovada asignărilor durabile sau a dispatch-ului live.
- Microproba GPS pe HONOR nu certifică aplicația nativă completă. Criteriul strict „service absent după Stop UI” a rămas FAIL; startRequested=false, UI idle, contoarele stabile ori force-stop nu îl închid. Terenul, consumul, alte dispozitive și iOS rămân nedovedite.
- Runtime-urile BOOST03 proprii sunt oprite, datele și dovezile sunt păstrate. Planificarea nu le repornește.

Planul comercial general este deja confirmat; nu se cere reconfirmarea sa. Packetul anterior BOOST autoriza Etapa 2 și excludea Etapa 3+. Cererea curentă autorizează acest plan extins, fără a activa implicit implementarea Etapei 3+, date reale, deploy, GPS/ADB, servicii plătite sau magazine. La execuție se delimitează pachetul concret și se rezolvă numai autorizările ori deciziile realmente lipsă.

## Rezultatele mari și corespondența comercială

| Grup | Etape comerciale | Rezultat verificabil |
| --- | --- | --- |
| M0. Reguli și acceptare rămasă | 1–2 | Cerințe legate de cod și probe; gate-uri reale închise sau explicit deschise, fără recontarea BOOST |
| M1. Zi de operare restaurant | 3 | Acceptare → pregătire → READY, close-day corect, incidente și recuperare PWA |
| M2. Nucleu pentru comenzi multiple | Fundament pentru 5/7 | Ownership, rezervări, capacitate și opriri durabile; progres 1 → 2 → 5 → 10 |
| M3. Intrări OCR/API | 4 | Draft OCR confirmat; un conector real cu import recuperabil; manual disponibil |
| M4. Livrator nativ și GPS | 5–6, probă timpurie pentru 8 | Android/iOS, sarcini multiple, offline, GPS/hartă și push demonstrate pe dispozitive |
| M5. Alocare și rutare | 7 | Propuneri fezabile, revalidare la commit, intervenție manuală și activare controlată |
| M6. Notificări și exploatare | 8 | Oferte/incidente vizibile, evenimente fără dubluri, rapoarte simple |
| M7. Infrastructură și securitate | 9 | Roluri/date, restore și migrare verificate, benchmark cu praguri adoptate |
| M8. Pilot și predare | 10 | Zi reală de operare, remediere, instruire, build/depunere în magazine și handoff |

Grupurile nu renumerotează etapele comerciale. M2 este o pistă tehnică pregătită devreme, nu o nouă etapă contractuală.

## 32 de loturi finite

Fiecare lot începe cu o verificare focalizată a lacunei. Dacă acel criteriu are deja dovadă adecvată pe sursa curentă, dovada se reutilizează și lotul se restrânge la ce lipsește. Nu se numără un test reluat ca funcționalitate nouă.

### M0 — Reguli și acceptare rămasă

| Lot | Livrabil | Închidere |
| --- | --- | --- |
| G01. Hartă cerință–cod–probă | Matrice care leagă cerințele aprobate, comportamentul actual, lacunele și dovezile BOOST/native/dispatch | Fiecare cerință are sursă, owner și criteriu observabil; FAIL/SKIP/blocajele au explicații distincte |
| G02. Gate-uri Etapa 1/2 | Acceptarea formală rămasă, inclusiv S2-05B/S2-08, după regulile și probele necesare | Nicio formulă financiară presupusă și nicio acceptare globală dedusă din build; problemele rămase sunt identificate concret |

G02 nu blochează analiza și specificațiile independente; funcționalitățile dependente de regulile lipsă rămân deschise.

### M1 — Zi de operare restaurant: primul rezultat după close-day

| Lot | Livrabil | Închidere |
| --- | --- | --- |
| R01. Close-day operațional | Implementarea delimitată de packetul PD-S3-04-CLOSE-01 existent | Activele continuă și o comandă nouă intră; pauza/deadline-ul exact impuse de admin sunt păstrate, inclusiv la concurență; self-pause restaurant respins 403 cu zero writes; retry explicit al aceleiași intenții după ACK pierdut |
| R02. Liste, detaliu, istoric propriu | Repararea exclusivă a lacunelor de vizibilitate, filtrare și reconciliere a comenzilor restaurantului | Comanda apare în coada/starea corectă; actorul străin nu accesează/modifică datele; rezultate vechi după schimbarea sesiunii nu intră în UI |
| R03. Acceptare și pregătire | Acțiuni recuperabile și timp de pregătire validat, prin protocolul comun existent | Double-click/reload/ACK pierdut nu dublează efectele; conflictul cu adminul este explicabil; valori invalide respinse fără scrieri parțiale |
| R04. READY și timer | Stare gata explicită și afișare corectă a timpului | Expirarea timerului nu inventează READY; confirmarea/pregătirea nu se blochează doar fiindcă există ofertă/asignare; compatibilitatea statusurilor este verificată |
| R05. Incident/refacere legată de original | Incident vizibil și, unde regula permite, refacere identificabilă fără resetarea comenzii terminale | Fără pierderea originalului, dubluri, anulare tăcută după pickup sau rambursare/tarif inventat; restaurantul decide produsele/refacerea |
| R06. PWA și zi completă | Offline/eroare/loading/revenire, sesiune curentă și flux browser admin–restaurant | Creare → acceptare → pregătire → READY; close-day activ/pausat; incident și reload, în browser la 1440/390. Telefonul fizic/Safari au dovadă separată |

R01 nu schimbă cutoff contabil, solduri, remunerație, decont, transport sau zi contabilă. Închiderea zilei nu presupune miezul nopții. R02–R06 folosesc backlogul S3-01/02/03/05/06 numai pentru lacunele rămase.

### M2 — Nucleu pentru comenzi multiple: contract existent, apoi 1/2/5/10

| Lot | Livrabil | Închidere |
| --- | --- | --- |
| D01. Autoritate și inventar writeri | Adaptarea PD-DISPATCH-01 v0.3 la sursa finală; inventar al tuturor consumatorilor current_order_id | dispatch_assignments decide ownership/rezervarea; driver_dispatch_state serializează cota/disponibilitatea/ruta; ledgerul durabil este ales/adaptat explicit, fără două protocoale care admit aceeași intenție |
| D02. O comandă prin noul protocol | Paritate cu fluxul manual, pe Mongo sintetic cu topologie cunoscută | Assignment, guard, contoare, proiecții, audit și rezultatul operației se comit atomic; două procese, restart și commit fără ACK păstrează un singur rezultat logic |
| D03. Două comenzi manual, end-to-end | API și consumatori admin/restaurant/driver adaptați, lista sarcinilor și oprirea selectată | Livrarea/anularea uneia păstrează cealaltă; asignarea în NEW/PREPARING permite apoi pregătire → READY, păstrând ownership-ul și cealaltă comandă; pauza/offline/dezactivarea și writerii legacy respectă același guard; current_order_id rămâne numai proiecție |
| D04. Cinci comenzi și rută versionată | Opriri pickup/dropoff, încărcare pe segment, dependențe și invalidare a rutei | Pickup precede dropoff; marfa ridicată intră în încărcarea inițială; prefixul executat este fix; recalcularea stale este respinsă prin CAS; route dirty nu devine instrucțiune executabilă |
| D05. Zece comenzi și concurență | Caz fezabil și caz nefezabil, capacitate configurabilă și curse adversariale | Nouă ocupate + două rezervări simultane: exact un câștigător; a unsprezecea la plafon 10 este respinsă; livrarea uneia păstrează celelalte nouă; accept/expire/reassign/recovery nu dublează efecte |
| D06. Compatibilitate și migrare aditivă | Dry-run, inventar proiecții, raport integritate și plan de revenire | Fără activare înaintea consumatorilor compatibili; oprirea admisiei noi păstrează execuția/recovery pentru sarcinile deja admise; nu se revine orb la cod singular cu sarcini multiple active |

reserved_count + active_count ≤ configured_order_limit. Acceptarea mută rezervat → activ, fără loc suplimentar. Expirarea este o operație explicită recuperabilă, nu simpla dispariție prin TTL. Schimbarea plafonului/pauzei/disponibilității participă la același guard.

Zece comenzi active nu înseamnă zece transportate simultan. Capacitatea fizică se verifică pe traseu. Nu se forțează o combinație nefezabilă. Comenzile ridicate nu se transferă automat; livrarea fizic efectuată a mărfii în custodie nu este ascunsă fiindcă ruta necesită recalculare. Starea de pregătire rămâne logic distinctă de ofertă/asignare.

### M3 — Introducere manuală, OCR și un conector API

| Lot | Livrabil | Închidere |
| --- | --- | --- |
| I01. OCR cu confirmare umană | Extragere în draft, câmpuri obligatorii, corectare, erori vizibile și fallback manual | Bonul neclar/incomplet nu creează automat o comandă; utilizatorul verifică și confirmă; confirmarea repetată nu dublează; integrarea unui serviciu plătit are gate separat |
| I02. Contract intern de ingestie | Inbox durabil, normalizare, identitate externă, deduplicare și coadă de erori | Crash/replay/ordine inversă/retry finit nu creează duplicate sau regresii de status; potrivirea probabilistică OCR/API/manual cere verificare, nu șterge automat |
| I03. Conector pentru un restaurant | Integrare reală după nominalizarea furnizorului, documentației, autentificării și sandboxului | Import autorizat, payload invalid/429/5xx/timeout/recovery, plus anulare externă după pickup ca incident; dovadă în sandbox, apoi activare distinctă |

Nu se presupune POS sau un API existent. Lipsa furnizorului blochează I03, nu I01/I02, manualul ori M2. Nu se cer credentiale în chat/document. Outbound statuses și posibilitatea recuperării se implementează numai dacă sursa le oferă și cerința le include.

### M4 — Livrator Android/iOS, GPS și probe native timpurii

| Lot | Livrabil | Închidere |
| --- | --- | --- |
| N01. Audit și build reproductibil | Inventar aplicație/microprobă/toolchain; alegerea justificată pe codul existent; traseu Android și iOS/provisioning | Build și instalare reproductibile pe țintele disponibile; limitările și accesul lipsă sunt explicite. Un wrapper/build web nu certifică aplicația livratorului |
| N02. GPS de tură, hartă și Stop | Contract timestamp/precizie/ordine mostre, permisiuni, Start/Stop, investigarea FAIL existent și harta admin/livrator, reutilizată unde este adecvată | Poziția cu vârstă/precizie și opririle/ruta validate sunt vizibile; ruta dirty nu este instrucțiune executabilă. Probe fizice în fundal/ecran blocat/revenire, baterie și Stop după criteriul păstrat; service absent FAIL nu este închis prin UI idle/force-stop. GPS când livratorul este disponibil în tură, cu/fără comandă, fără urmărire 24/7 |
| N03. Sarcini native multiple | Listele tuturor asignărilor, oprirea selectată și acțiuni pe comanda corectă | Actor/context curent, acceptare/pickup/livrare conform ownership/custody; efectuarea unei acțiuni nu șterge celelalte sarcini |
| N04. Offline și revenire | Intenții locale durabile, stare nesincronizată clară și reconciliere | Aceeași cheie și payload la reluare; fără finalizare fictivă, acceptare expirată sau POST orb; restart/reconectare/conflict au rezultat vizibil |
| N05. Probă push timpurie | Permisiuni, tokenuri, primire și deschiderea sarcinii pe Android/iOS | Foreground/background/ecran blocat pe dispozitive; oferta expirată nu este acceptată din notificare; dovada de primire este distinctă de emiterea serverului |

N01/N02/N05 sunt piste de risc timpurii propuse în paralel cu M1/M3; nu așteaptă încheierea tuturor ecranelor. N03/N04 se integrează cu protocolul M2. OFF/deep-Doze, deplasarea în teren și iOS nu se deduc din proba HONOR staționară alimentată USB. Folosirea dispozitivelor, permisiunilor, testerilor și datelor de localizare necesită cadrul autorizat distinct.

### M5 — Alocare automată și rutare

| Lot | Livrabil | Închidere |
| --- | --- | --- |
| A01. Eligibilitate și timpi rutieri | Disponibilitate/capacitate, GPS proaspăt/precis, pregătire/ferestre și provider de rutare aprobat | Lat/lng singure nu dovedesc prospețime; datele sunt reverificate la rezervare/acceptare. Linia dreaptă poate prefiltra, dar nu este prezentată drept ETA rutier validat |
| A02. Solver integrat cu buget finit | Refolosirea probei 1/2/5/10, apoi integrare cu modelul durabil/ruta | Restricții respectate, pickup/dropoff și capacitate pe segment; output incomplet/stale/nefezabil respins; timeout păstrează numai plan valid sau cere intervenție manuală |
| A03. Shadow și activare controlată | Propuneri fără dispatch live, comparație cu operatorul și pilot delimitat | Commit reverifică versiuni, capacitate, GPS și oferta; replanificarea conservă opririle executate/custody; activarea reală și oprirea admisiei au gate distinct |

Fără LLM în bucla de alocare și fără promisiune de optim matematic global. Alocarea manuală rămâne permanent disponibilă și respectă aceiași invarianți. M2 și solverul sintetic pot avansa independent de GPS/provider; dispatch-ul real M5 nu este acceptat fără dovezile GPS, rutare și parametrii operaționali.

### M6 — Notificări, excepții și rapoarte simple

| Lot | Livrabil | Închidere |
| --- | --- | --- |
| O01. Evenimente și notificări durabile | Outbox/worker după commit, ofertă/incident/eroare vizibile; integrarea probei push N05 | Retry finit și identitate event_id fără efecte duplicate; destinatari validați; nedelivrarea vizibilă. Server send nu este confundat cu primire pe telefon |
| O02. Panou operațional și rapoarte | Cozi active/incidente, istoric/audit și sumarul de activitate aprobat | Datele provin din evenimente/comenzi reale ale mediului; filtrele/rolurile sunt corecte; decontarea, remunerarea și cash/returul folosesc numai regulile confirmate |

Regulile financiare care lipsesc rămân cerințe deschise și nu sunt înlocuite cu formule provizorii. Restaurantul decide produsele/refacerea/rambursarea conform politicii; transportul separat nu devine implicit compensare cu încasările produselor.

### M7 — Infrastructură, securitate și capacitate măsurată

| Lot | Livrabil | Închidere |
| --- | --- | --- |
| P01. Roluri, date și operare | Controale actor/context, protecția datelor, loguri utile fără secrete, rate limits și gestionarea erorilor | Probe pe fluxurile finale, inclusiv auth real în cadrul autorizat; testul HTTP loopback sintetic nu certifică TLS/producția |
| P02. Backup/restore și migrare | Restore pe copie autorizată, integritate/legături, compatibilitate și runbook de recuperare | Restaurarea actuală EJSON sintetică nu este declarată PIT/indexuri/TTL/failover. Dovezi separate pentru indexuri/topologie/retenție și orice schimbare autorizată; recovery nu șterge sarcini admise |
| P03. Benchmark adoptat | Profil, infrastructură, durată și praguri de latență/erori stabilite înaintea testului | Scenariu 50 restaurante/100 livratori, 1000 comenzi alocate + 200 în așteptare, concurență și restart, cu limite observate și raport; profilul rămâne țintă până la măsurare |

P01/P02 se aplică și în fiecare increment anterior; nu sunt amânate până la final. Benchmarkul final nu este o garanție de capacitate universală și nu autorizează consum/servicii plătite prin simpla existență a acestui plan.

### M8 — Pilot, magazine, instruire și predare

| Lot | Livrabil | Închidere |
| --- | --- | --- |
| L01. Zi reală de pilot | Restaurant/operator/livratori desemnați, dispozitive, date și intervenție manuală în cadrul aprobat | Traseu real de la creare la livrare, incidente/offline/push/GPS, constatări remediate și regresie relevantă; acceptarea nu se deduce din fixture/browser |
| L02. Release și handoff | Build semnat/depunere magazine, instrucțiuni, runbook, instruire și acceptare documentată | Deploy/depunere autorizate distinct; depunerea nu echivalează cu aprobarea magazinelor. Dovezi finale, limitări, acces și responsabilități de suport conform planului comercial |

## Ordinea practică și paralelismul

La începutul execuției autorizate:
1. G01 delimitează lacunele; R01 închide corecția close-day, apoi R02–R06 livrează „Zi de operare restaurant”.
2. În paralel, D01 stabilește contractul pe baza specificației existente, iar N01/N02/N05 investighează devreme riscurile native/GPS/push. Aceste piste nu activează dispatch live.
3. În laborator, pe fixture-uri sintetice, D02 → D03 → D04 → D05 verifică gradual 1/2/5/10. Compatibilitatea începe în D01 și consumatorii sunt integrați deja în D03; D06 verifică dry-run/recovery/revenirea și rămâne gate înaintea oricărei activări multi-comandă.
4. I01/I02 pot avansa independent. I03 așteaptă exclusiv furnizorul/accesul/contractul API.
5. N03/N04 se leagă de M2; A01/A02 combină M2 cu GPS/rutare validate. A03 shadow precede orice activare reală.
6. O01/O02 folosesc evenimentele stabile; P01/P02 protejează fiecare increment. P03 se execută după adoptarea profilului și pragurilor.
7. L01/L02 urmează acceptării funcționale, probelor fizice, gate-urilor financiare/operaționale și autorizărilor reale de pilot/release.

Un gate extern blochează numai loturile dependente de el. Codul poate fi pregătit pe fixture-uri separate; o probă sintetică nu închide acceptarea comercială, fizică sau live. Nu se invocă OpenClaw/Claude Code/servicii AI plătite și nu se modifică Agent Hub. Codex coordonează, cu owner, reviewer și QA interni OpenAI pe scope-uri distincte, modele moștenite. Nu se lansează toate loturile simultan.

## Informații și autorizări care trebuie rezolvate înaintea lotului dependent

| Gate | Ce lipsește | Loturi afectate |
| --- | --- | --- |
| Reguli financiare | Remunerație, cash insuficient, livrare eșuată/retur, rotunjire, cutoff și modificarea adresei după sosire | G02 și porțiunile financiare R05/O02/L01; close-day operațional rămâne separat |
| Conector | Restaurant/furnizor, documentație/versiune, sandbox, auth, IDs/sequence, limite/costuri, contract outbound | I03 |
| Operare și rutare | Capacitate fizică, ferestre/timpi, expirarea ofertelor, politica offline și provider/ETA/cost aprobat | N04/A01–A03/L01; M2 folosește politici sintetice declarate până la confirmare |
| Dispozitive și nativ | Android+iPhone, tester/consimțământ, conturi/provisioning iOS și probe fizice autorizate | N01/N02/N05, acceptarea M4/M5/L01 |
| Date și infrastructură reale | Hosting, acces, backup/retention, migrare/indexuri/TTL/topologie și praguri de încărcare | P02/P03/A03/L01 |
| Publicare | Ținte și conturi de deploy/magazine, servicii cu plată și acces necesar | L02 și orice activare live |

Nu se solicită reconfirmarea lucrurilor deja autorizate. Nu se cer secrete în chat. Gate-urile se cer concret când lotul dependent este pregătit și revizuibil.

## Cum se închide un lot și cum se estimează timpul

Un lot este închis numai cu rezultat pentru utilizator + probe adecvate + review separat + checkpoint al sursei finale. Pentru cod: backup înaintea editării, testele protejate intacte, regresie relevantă și adiacentă, hash/dovezi, raport exact de PASS/FAIL/SKIP și cleanup exclusiv al runtime-ului propriu, cu date păstrate. Build/lint nu înlocuiesc fluxul real. QA nu „înverzește” oracolele vechi.

Raportul scurt de final de lot conține: ce s-a schimbat, criteriile dovedite, ce rămâne deschis, rezultatul review/QA și lotul următor executabil. Se continuă loturile autorizate fără oprire la fiecare subpas; un blocaj real este explicat și lucrările independente continuă.

Cele 32 de loturi descriu volum și dependențe, nu 32 intervale egale. Cele 10 ore discutate anterior nu reprezintă durata întregului roadmap și nu sunt un timp minim de consumat. Estimarea se face înaintea fiecărui lot după verificarea lacunei și se corectează după timpii observați; nu se umplu ore dacă acceptarea este atinsă mai repede. Ținta comercială de trei luni rămâne condiționată de probele și dependențele deja documentate, fără termen nou garantat.

## Surse și dovada pregătirii planului

- .ifrim/EXECUTION_PLAN_2026-09-26.md — plan comercial, platforme, zece etape, 10 comenzi, OCR/API, dependențe și limite.
- .ifrim/SPECIFICATIONS/PD-DISPATCH-01.md v0.3 — autoritate/cotă/rută/custody/compatibilitate; propunere, fără migrare activată.
- .ifrim/TASK_PACKETS/2026-10-07-stage2-3-expanded-backlog.md — S3-01…06 și gate-uri pentru etapele ulterioare; headerul istoric nu substituie starea curentă.
- .ifrim/TASK_PACKETS/2026-10-10-next-plan-close-day.md — incrementul S3-04 deja revizuit; acest document îl include, fără să îl suprascrie.
- .ifrim/TASK_PACKETS/2026-10-10-stage2-boost-handoff.md — autoritatea Stage2 și regulile operaționale confirmate.
- .ifrim/NEXT_SESSION.md, OPEN_ISSUES.md și LOOP_REPORTS/2026-10-10-stage2-boost-03.md — baseline și gate-uri actuale.
- .ifrim/LOOP_REPORTS/2026-10-10-honor-gps-retest.md — limitele probei GPS, inclusiv FAIL Stop.
- Cod actual citit focalizat: backend/utils/order_assignment.py, backend/utils/order_status.py, backend/routers/drivers.py, backend/routers/restaurants.py și frontend/src/pages/DriverApp.jsx/RestaurantApp.jsx.
- Pregătire: ROOT coordonator; advisory read-only backend_mixed_races pentru modelul multi și independent_review pentru scope/dependențe. Review al documentului final urmează separat.
- Git verificat înainte de salvare: main...origin/main, modificări preexistente păstrate. Acest task adaugă numai documentul nou de plan; fără modificări de aplicație, Git, runtime, dispozitive sau date.

## Închiderea review-ului documentar

independent_review: PASS pe conținutul corectat, 22949 bytes, SHA256 DD68B77368552B2F3220D87C31DF03ECAB30BB757DF73CE163A82C10F2B4A5BD. Harta admin/livrator are criterii explicite; pregătirea după asignare și progresia sintetică 1/2/5/10 cu gate de compatibilitate înaintea activării sunt clarificate. Niciun blocker documentar rămas. Verificarea structurală ROOT: 32 loturi distincte, UTF-8 fără caractere de înlocuire. Niciun test de aplicație nou, runtime sau dispozitiv pornit în acest task de planificare.

Instrucțiune umană curentă: „înainte să te apuci îmi spui planul și ce etape se includ în el”. Planul și etapele se prezintă înaintea implementării. Documentul rămâne propunere; acest addendum consemnează review-ul și nu activează lucrările.

## Prioritate actualizată după corecția utilizatorului — 2026-10-10

Instrucțiunea curentă este să închidem Etapele 1 și 2 înaintea noului milestone restaurant. Această secțiune înlocuiește prioritatea anterioară R01 → R02–R06 din „Ordinea practică”; restul roadmapului rămâne pentru mai târziu. G01/G02 sunt primul obiectiv. Închiderea celor două etape se împarte în pachete finite, prezentate înaintea implementării, fără un buget fix care ar garanta toate gate-urile.

Ordinea imediată:
1. Matrice finală Etapa 1/2: sursa BOOST03, cerințe, dovezi deja satisfăcute, defecte și gate-uri rămase; nu refacem probele verzi fără motiv.
2. Etapa 1, fezabilitate nativă: investigarea și închiderea criteriului Stop FAIL, completarea probei Android pentru offline local/revenire/baterie și proba fizică Android/iOS cerută de packetul Stage1. Stop trebuie să oprească tracking-ul nativ și să respingă callbackurile tardive; UI idle, force-stop sau JS bundle nu închid criteriul. Accesul la iPhone/build/provisioning/tester este o dependență concretă. Nu se cere aici aplicația completă, fleet GPS, upload/sync server ori magazine.
3. Etapa 2, S2-05B: incidente/refaceri/custody și efectele financiare după tabelul driverpay, procedura cash insuficient, retur/refuz, rotunjire/cutoff și adresa post-sosire. Se folosesc răspunsurile deja primite; se cer numai deciziile exact lipsă, fără chestionar duplicat sau formule inventate.
4. Defecte și acceptare Etapa 2: triere a celor 15 FAIL frontend / 5 FAIL backend istorice și 1 SKIP, după contractul curent; remedierea implementării pentru criteriile aplicabile, teste protejate păstrate. Close-day rămâne clasificat S3-04/Etapa 3. Dacă este indispensabil unui criteriu de închidere S2-08, fixul restrâns apare explicit ca dependență între etape în pachetul propus; nu este ascuns sub altă numerotare și nu începe automat milestone-ul complet Etapa 3.
5. Raport final de acceptare separat pentru fiecare etapă: probe fizice Stage1 și fluxul complet Stage2 creare → pregătire → alocare → acceptare → READY → pickup → livrare → istoric, plus anulare/incident/refacere, duplicate/conflicte/recovery, review și QA pe sursa finală. Gate-urile și limitele live sunt explicite; activarea/deploy-ul nu sunt deduse din acceptarea tehnică.

Etapa 1 cere fezabilitate și raportul ei de acceptare; API-ul neidentificat poate rămâne blocker explicit pentru conectorul ulterior. Etapa 2 se închide numai cu toate loturile necesare verificate și raportul de acceptare al scope-ului. Nu bifăm o etapă cu criterii restante și nu repetăm BOOST drept lot nou.

Surse pentru această reprioritizare: TASK_PACKETS/2026-10-02-stage1-attack-plan.md și 2026-10-02-stage1-mobile-probe.md; TASK_PACKETS/2026-10-07-stage2-closure-plan.md; LOOP_REPORTS/2026-10-10-honor-gps-retest.md și 2026-10-10-stage2-boost-03.md. independent_review a verificat read-only delimitarea criteriilor Stage1 față de Etapele5/6. ROOT a verificat planul Stage2 și checkpointurile actuale. Au fost modificate numai documentele de plan; implementarea, runtime-urile și dispozitivele nu au fost pornite.
