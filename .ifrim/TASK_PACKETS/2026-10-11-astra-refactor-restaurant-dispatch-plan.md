# ProDelivery — propunere pentru următoarea sesiune Astra

Data: 11 octombrie 2026, Europe/Bucharest. Stare: DRAFT PENTRU REVIEW ȘI APROBAREA PLANULUI. Niciun lot de mai jos nu este declarat implementat sau autorizat prin existența acestui document.

Proiectul rămâne `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`. Continuăm aplicația existentă. Propunerea urmărește să simplifice câteva zone cu duplicare reală, apoi să îmbunătățească operarea restaurantului și să pregătească protocolul pentru mai multe comenzi. Nu presupune terminarea tuturor celor zece etape comerciale într-o singură sesiune.

## Ce închidem înainte de schimbarea contului

Pe contul curent terminăm proba fizică Android aflată în lucru, verificarea Stop și a stării finale a telefonului, review-ul dovezilor și raportul aferent. Rezultatul probei se scrie după colectare și verificare; durata de așteptare, mesajul „gata” ori pornirea workerului nu sunt dovadă de PASS. Limitele probei de baterie se păstrează în raport.

Închiderea software pentru Etapele 1–2 are deja dovezi separate, cu 294 legături de integritate și 140 fișiere protejate. Planul de față nu redeschide loturile închise și nu schimbă sursa congelată în timpul probei fizice. Orice condiție offline încă nedovedită rămâne explicită în raport, fără a împiedica planificarea independentă.

iOS și răspunsurile clientului rămân la final, conform instrucțiunii utilizatorului. Accesul la un iPhone nu înlocuiește traseul de build/provisioning, iar lipsa unui Mac rămâne o dependență de rezolvat atunci. Nu inventăm furnizorul unui API, reguli financiare sau acceptări comerciale.

## Model, viteză și estimare

Pentru execuția viitoare, alegerea utilizatorului este Astra, efort de raționament Ultra și modul Fast. Ultra este nivelul efortului de raționament; Fast este o setare distinctă de viteză. Fast consumă 2,5× din cota inclusă, conform [documentației oficiale despre viteză](https://learn.chatgpt.com/docs/agent-configuration/speed). Înaintea primului lot verificăm setările efectiv disponibile pe contul folosit; acest draft nu le schimbă.

Prima fereastră propusă este de aproximativ **8–12 ore de lucru**, presupunând un mediu local funcțional și lipsa unui defect structural nou. Este o estimare pentru câteva loturi delimitate, cu review, verificare și checkpointuri. Nu este o garanție de durată, de consum exact al cotei sau de închidere a tuturor etapelor. Estimările individuale includ verificarea focalizată, dar nu o investigație neprevăzută de amploare.

Ordinea urmărește rezultate utile. Nu așteptăm epuizarea cotei pentru a continua sau pentru a face handoff. Utilizatorul spune că Tibo a anunțat un reset până la finalul zilei PST: resetul anunțat poate apărea, dar nu garantăm ora și nu activăm noi nimic. Schimbarea contului se face la un checkpoint complet sau după oprirea controlată a lotului, fără a pierde proveniența lucrărilor.

## Prima fereastră: loturi mici, în această ordine

| Lot | Rezultat concret | Fereastră orientativă | Condiția de închidere |
| --- | --- | --- | --- |
| A0. Preluare și baseline nou | Sursa curentă, rezultatul raportului fizic, istoricul Stage1/2 și limitele lotului sunt legate într-un packet nou | 30–45 min | Inventar și snapshot înainte de editare; owner, reviewer și QA au aceeași versiune a contractului |
| A1. Contract restaurant R02/R03/R04/R06 | Matrice scurtă cu comportamentul existent, dovada reutilizabilă și lacuna rămasă | 45–75 min | Fiecare lacună are un caz observabil și un lot; comportamentele deja demonstrate nu sunt reimplementate |
| A2. Transport recovery comun | Un adaptor HTTP mic, folosit de cele patru hookuri existente | 1–1,5 h | Politica de sesiune, token, actor, timeout și durata controllerelor rămâne identică |
| A3. Parser pregătire comun | Un helper pur pentru datele și starea de pregătire folosit de assignment și status | 45–75 min | Aceleași acceptări și refuzuri, inclusiv cazurile BSON, fără schimbarea tranzacțiilor |
| A4. Executor comun pentru o singură acțiune | Extragerea blocului duplicat `perform`, fără unificarea întregului lifecycle | 1,25–2 h | Acțiunile concurente și rezultatele unei sesiuni retrase sunt blocate exact ca înainte |
| A5. Prezentarea RestaurantApp | Componente de afișare extrase, cu date și callbacks primite explicit | 1–1,75 h | Aceleași cozi, detalii, butoane și confirmări; nicio mutație nouă și nicio schimbare de sesiune |
| A6. Citirile RestaurantApp | Extragerea focalizată a citirilor după stabilizarea prezentării | 1,5–2,25 h | Polling, refresh, loading și erori aparțin numai cererii și sesiunii curente |
| A7. Integrare și handoff | Review pe sursa finală, QA relevantă și checkpoint complet | 45–75 min | Rezultate cu comenzi și artefacte identificabile; niciun defect aplicabil ascuns sub „refactor” |

Intervalele nu se însumează într-o promisiune. După A0–A3 alegem următorul lot pe baza matricei: dacă recuperarea pregătire/READY este lacuna cu impact mai mare, **prioritizăm A8 în aceeași primă fereastră**, iar A4–A6 trec în backlog. Astfel, fereastra poate livra direct recuperarea unei acțiuni restaurant în locul celorlalte extrageri. Dacă matricea nu arată această prioritate, continuăm A4 și admitem A5/A6 numai după închiderea lotului precedent și reevaluarea timpului rămas. A7 închide fereastra pe oricare traseu. Dacă timpul se scurtează, închidem loturile începute și păstrăm restul în backlog. Nu comprimăm owner, review și QA într-un singur verdict pentru a ajunge la un număr de ore.

## Cele trei refactoruri sunt ancorate în codul actual

**A2 — transport recovery comun, risc redus spre mediu.** În [useOrderCreationRecovery.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/hooks/useOrderCreationRecovery.js:16>), [useOrderEditingRecovery.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/hooks/useOrderEditingRecovery.js:14>), [useOrderAssignmentRecovery.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/hooks/useOrderAssignmentRecovery.js:12>) și [useOrderStatusRecovery.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/hooks/useOrderStatusRecovery.js:21>) există același model de client Axios izolat, cu `withCredentials`, `Authorization` și `X-Expected-Actor-ID`. Extragerea acoperă numai adaptorul GET/POST/PUT.

Păstrăm anularea explicită a unui header Authorization moștenit când tokenul lipsește. Crearea continuă să citească tokenul proaspăt prin `tokenRef`, cu controller stabil la schimbarea tokenului. Editing, assignment și status își păstrează dependențele și regulile proprii de recreare. Clientul recovery nu intră în interceptorul global de refresh/replay din AuthContext. Rezultatul este întreținerea într-un singur loc a transportului comun, fără schimbarea autentificării ori retry-urilor.

Verificarea reutilizează testele protejate `stage2-boost-actor-hooks.test.jsx`, `orderCreationRecovery.integration.test.js`, `useOrderEditingRecovery.test.jsx`, `useOrderAssignmentRecovery.test.jsx` și `useOrderStatusRecovery.test.jsx`. Cazurile relevante sunt schimbarea actorului din cookie, tokenul actual, blocarea fallbackului legacy și aceeași intenție la recovery. Ownerul execută cazurile focalizate; QA verifică separat comportamentul pe sursa finală.

**A3 — parser pregătire comun, risc mediu.** Funcțiile `_date` și `_preparation` din [order_assignment.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/utils/order_assignment.py:147>) și [order_status.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/utils/order_status.py:151>) au același corp în sursa citită. Propunerea este un helper pur cu fabrica de eroare transmisă explicit, astfel încât `AssignmentError` și `StatusError`, codurile și mesajele lor să rămână neschimbate.

Păstrăm NEW/PREPARING/READY, validarea timestampurilor, limitele numerice actuale, suportul BSON `Int64`, refuzul valorilor bool și interpretarea strictă a câmpurilor lipsă sau contradictorii. Nu atingem `_execute`, filtrele CAS, digesturile de admisie, schema receipturilor sau regulile financiare. Testele protejate relevante sunt `test_order_assignment_recovery.py`, `test_order_status_recovery.py` și `test_stage2_boost_mixed_services.py`: pregătire/timer păstrate după assignment, pickup refuzat înainte de READY, stări malformate respinse, ultima revizie BSON și concurența dintre pregătire și asignare. Rezultatul este eliminarea duplicării parserului, cu aceeași semantică.

**A4 — executor comun al acțiunii, risc mediu.** Blocul `perform` este duplicat în [useRecoveryControllerLifecycle.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/hooks/useRecoveryControllerLifecycle.js:20>) și [useOrderStatusRecovery.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/hooks/useOrderStatusRecovery.js:50>). Extragem numai admiterea unei acțiuni, capturarea generației, executarea și finalizarea ei.

Păstrăm o singură acțiune în curs per controller, ignorarea rezultatului vechi după schimbarea sesiunii, curățarea numai a jobului propriu și rezolvarea promisiunii de finalizare în toate ramurile. `pagehide` retrage generația; o sesiune cu același actor nu reînvie o continuare veche. Nu mutăm statusul complet în lifecycle-ul generic: capability probe, rolurile, driver/restaurant, storage și regulile legacy au diferențe deliberate.

QA se bazează pe testele protejate `useRecoveryLifecycle.boost02.test.jsx`, `recoveryEpoch.boost02.test.js` și `useOrderStatusRecovery.test.jsx`: double-click, StrictMode, offline, deadline de auth, pagehide repetat, lookup 404 cu același UUID/payload și răspuns POST întârziat. Rezultatul este un bloc comun scurt; politica fiecărui controller rămâne lizibilă.

`backend/utils/order_operation_runtime.py` este deja comun pentru cele patru mutații. Ordinea worker → abort → end-session, deadline-urile și commitul incert rămân în afara acestor refactoruri. Coada schimburilor de cookie și interceptorii care verifică actorul/generația din `AuthContext.js` rămân, de asemenea, în afara lor. O rescriere generală a tranzacțiilor sau a autentificării ar cere un packet distinct și nu ajută această primă fereastră.

## Restaurant: contract întâi, apoi afișare și comportament nou

A1 verifică numai lacunele rămase din roadmapul existent:

| Contract | Ce verificăm și păstrăm |
| --- | --- |
| R02 — liste, detaliu, istoric propriu | Comanda apare în coada corectă; restaurantul străin este refuzat; răspunsurile vechi nu ajung în UI după schimbarea sesiunii |
| R03 — acceptare și pregătire | Timp validat, acțiune explicită, dublu click și ACK pierdut cu un singur efect; conflictul este vizibil |
| R04 — READY și timer | READY este confirmare explicită; expirarea timerului semnalează întârziere; asignarea nu blochează pregătirea |
| R06 — PWA și flux complet | Loading/eroare/offline/revenire/reload; creare → pregătire → READY, compatibilitate cu close-day; browser 1440/390, cu dovada fizică separată |

În [RestaurantApp.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/RestaurantApp.jsx:265>), `fetchOrders` verifică deja requestId, sesiunea, mounted, `isCurrent` și `statusMutationRef`. Citirile statusului restaurantului, disponibilității și analytics au propriile garduri; close-day folosește și lease-ul controllerului. A5 extrage numai prezentarea. A6 păstrează fiecare gard, intervalul de polling și politica toast/loading; nu le înlocuiește cu o abstracție care publică orice răspuns sosit ultimul. Invarianții se verifică prin cereri întârziate și schimbarea actorului/restaurantului, nu numai prin snapshoturi de componente.

**A8 — recuperare vizibilă pentru pregătire și READY, lot funcțional prioritizabil după A0–A3, orientativ 2–4 ore după contract.** În sursa actuală, `setPreparationTime` și `markAsReady` folosesc PUT explicit cu timeout și actor așteptat. După o eroare se recitește starea; aceasta nu reprezintă deja un panou durabil complet de recovery. Implementarea propusă prezintă clar „în curs”, „rezultat incert”, „aplicat” sau conflictul și oferă acțiunea potrivită pentru reconciliere.

Nu există PUT automat la expirarea timerului, la montarea paginii, la reconectare sau dintr-un răspuns vechi. Orice operație incertă păstrează identitatea și payloadul original; un GET de reconciliere nu admite o intenție nouă. Protocolul concret se decide după citirea writerilor existenți din `backend/routers/orders.py`, înainte de cod. Dacă protocolul actual nu suportă recuperarea cerută, partea backend este un sublot explicit, cu propriile cazuri de concurență și zero scrieri parțiale; nu se declară rezolvată printr-un toast.

Acceptarea cere controale valide și invalide: timp invalid fără schimbări, timp valid păstrat după reload, ACK pierdut reconciliat cu un efect, pregătire după asignare, READY explicit și pickup refuzat înainte de READY. Reutilizăm `test_order_dispatch_preparation_regression.py` și testele de status/assignment; adăugăm separat cazurile care lipsesc pentru noua interfață. Testele protejate nu se modifică pentru a ascunde diferențe de contract.

## Fundația dispatch: după contract și compatibilitate, în incrementuri

**D0 — actualizarea PD-DISPATCH-01 și inventarul consumatorilor, orientativ 1–2 ore pentru contract.** Specificația [PD-DISPATCH-01.md](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/.ifrim/SPECIFICATIONS/PD-DISPATCH-01.md>) v0.3 este punctul de pornire, nu dovadă că asignarea multiplă este implementată. Adaptăm contractul la sursa finală și inventariem writerii și consumatorii `current_order_id`. Alegem explicit cum se păstrează ledgerul durabil existent; nu admitem aceeași intenție prin două protocoale.

`dispatch_assignments` ar decide ownership-ul și rezervarea, iar `driver_dispatch_state` ar serializa cota/disponibilitatea/ruta. `current_order_id` devine proiecție de compatibilitate, fără a fi folosit pentru a deduce numărul sarcinilor. Pregătirea rămâne independentă de asignare. Acestea sunt cerințe pentru viitorul packet, nu colecții/indexuri create de acest plan.

| Increment viitor | Proba de închidere |
| --- | --- |
| D1 — o comandă | Paritate cu fluxul manual pe date sintetice și topologie cunoscută; guard, rezultat, audit și proiecții atomice; restart și commit fără ACK nu dublează |
| D2 — două comenzi | Livrarea/anularea uneia păstrează cealaltă; pregătire → READY după asignare; admin, restaurant și driver au consumatori compatibili |
| D3 — cinci comenzi | Opriri versionate, pickup înainte de dropoff, capacitate pe segment, prefix executat păstrat și calcul stale refuzat prin CAS |
| D4 — zece comenzi | Caz fezabil și nefezabil; la nouă ocupate și două rezervări concurente câștigă exact una; plafonul și eliberarea selectivă sunt demonstrate |

Compatibilitatea începe în D0 și este verificată în fiecare increment. Dezactivarea admisiei noi trebuie să păstreze execuția și recovery pentru sarcinile deja admise. Un driver cu mai multe sarcini nu poate fi operat printr-un client vechi care cunoaște numai câmpul singular. Testarea sintetică 1/2/5/10 nu certifică dispatch live sau capacitatea fizică a transportului.

D1–D4 vor avea estimări proprii după D0. Nu sunt incluse ca patru rezultate garantate în fereastra de 8–12 ore. Planul nu autorizează migrarea bazei actuale, indexuri live, deploy, activare, schimbări Git sau un provider extern de rutare/API. Nu se presupune o formulă financiară și nu se schimbă plata/decontul prin această fundație.

## Cum închidem și reluăm fiecare lot

Ownerul primește o listă scurtă de fișiere editabile, contractul și criteriile de închidere. Reviewerul citește independent implementarea finală și scenariile de eroare. QA verifică separat comportamentul, cu teste potrivite riscului; testele noi trebuie să observe un efect ori un refuz semnificativ, nu să copieze implementarea. Nu lansăm simultan mutații asupra acelorași fișiere. Folosim owner/reviewer/QA interni OpenAI; OpenClaw, Claude Code și servicii AI plătite rămân excluse de regula actuală a proiectului.

Un lot închis are snapshotul înainte, lista exactă a fișierelor schimbate, hashurile sursei finale, review-ul, comenzile executate cu rezultate și limite, probele relevante și checkpointul de reluare. Un build sau un test static nu certifică telefonul, Safari ori producția. Un FAIL/SKIP existent rămâne identificat; orice defect aplicabil nou împiedică verdictul verde al lotului.

Refactorurile autorizate ulterior vor schimba intenționat hashurile fișierelor din lista permisă. Fiecare lot primește **snapshot și manifest noi**; păstrăm istoricul Stage1/2 cu cele 294 legături și 140 fișiere protejate, rapoartele și dovezile originale. Nu cerem ca sursa modificată printr-un refactor autorizat să mai corespundă tuturor hashurilor vechi. Fișierele de teste protejate rămân neschimbate; integritatea lor se verifică și față de baseline-ul nou.

Checkpointul spune ce este CLOSED, ce este în lucru și ce urmează, cu packet ID, sursa exactă, dovezile și motivul oricărei limitări. Dacă se schimbă contul/modelul sau se întrerupe sesiunea, următorul agent citește bootstrapul și checkpointul, verifică proveniența și continuă din ultimul rezultat închis. Nu reface un lot închis numai pentru a genera activitate.

## Backlog după prima fereastră

Dacă A8 a avut prioritate în prima fereastră, backlogul începe cu A4–A6; dacă a fost ales traseul A4–A6, backlogul începe cu A8. După acestea urmează D0 și D1; D2/D3/D4 se admit numai după acceptarea incrementului anterior. Incidentele/refacerea R05 intră într-un packet separat dacă matricea arată lacune. OCR cu confirmare umană, conectorul unui furnizor nominalizat, GPS live, push, benchmark, pilot, magazine și predare rămân în roadmapul extins, fiecare cu dependențele și autorizările proprii. Răspunsurile clientului și iOS se rezolvă la finalul lucrărilor independente, conform ordinii cerute.

Propunerea pentru review este aprobarea ordinii și a limitelor primei ferestre. După review, primul packet concret va spune exact ce fișiere intră în A0–A2 și ce probe trebuie să treacă; alegerea unui model sau aprobarea acestui draft nu reprezintă acceptarea anticipată a loturilor viitoare.
