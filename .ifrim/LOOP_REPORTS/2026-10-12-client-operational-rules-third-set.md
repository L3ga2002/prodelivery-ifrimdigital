# ProDelivery reguli client și ordinea lucrărilor

Răspunsurile primite la 12 octombrie 2026 clarifică circuitul numerarului, kilometrii, incidentele, schimbarea adresei și obligația de a executa alocările. Grilele și câteva condiții financiare rămân de precizat. Etapele 1 și 2 sunt deschise; lucrul continuă în ordinea 1, 2, 3.

Numerotarea Q1–Q11 aparține chestionarului furnizat în acest mesaj. Este al treilea set de clarificări și nu se mapează după număr la cele 15 întrebări din 8 octombrie sau la cele 11 din raportul din 9 octombrie. Textul sursă este păstrat separat în arhiva acestui intake.

## Reguli confirmate și puncte de completat

| Întrebare | Regula clientului | Ce mai trebuie definit |
| --- | --- | --- |
| Q1 Plata livratorului | Remunerația diferă între restaurante. | Sumele pe restaurant și zonă, în afara zonelor și la retur. Sensul referinței la zona 1 pentru retur: plata livratorului, transportul restaurantului sau ambele. |
| Q2 Kilometri | Rotunjire în jos: 15,3 km devin 15 km. | Regula privește kilometrii; rotunjirea sumelor monetare rămâne distinctă. |
| Q3 Numerar insuficient | Livratorul folosește bani personali. La ridicare marchează că nu a achitat din lipsă de fonduri; restaurantul aprobă evidențierea. Este cerut un buton în aplicația livratorului. | Legătura exactă dintre aprobarea restaurantului și ridicare, evidența sumei restante și momentul achitării ei. Aprobarea evidențierii nu este dovada unei plăți. |
| Q4 Refuz sau client absent | Restaurantul restituie avansul la următoarea ridicare sau la finalul programului. Restaurantul decide: retur imediat sau produsele rămân la livrator. | Plata livratorului și taxarea restaurantului pentru cursa inițială nereușită. Restituirea efectivă se consemnează separat de obligația de rambursare și de decizia asupra produselor. |
| Q5 Anulare înainte de ridicare | Dacă distanța parcursă depășește 50% din distanța punct de plecare–restaurant, livratorul primește jumătate din valoarea prețului pentru zona 1. | Cine suportă suma și ce preț de zona 1 este baza: remunerația livratorului sau transportul restaurantului. Trebuie stabilite măsurarea și dovezile distanței. |
| Q6 Adresă după sosire | Distanță rutieră între adresa inițială și cea nouă; restaurantul suportă transportul; sunt permise maximum două schimbări. | Supliment unic sau per schimbare eligibilă; referința distanței la a doua schimbare; tratamentul deplasărilor de cel mult 2 km. Regula anterioară pentru peste 2 km se păstrează. |
| Q7 Decontări | Întrebarea este retrasă. | Nu este o regulă nouă de scadență, confirmare sau compensare. Funcțiile de decontare se păstrează și întrebarea nu se retrimite automat. |
| Q8 Închiderea zilei | Întrebarea este retrasă. | Închiderea zilei și continuarea comenzilor se păstrează. Nu este definit un nou cutoff contabil; întrebarea nu se retrimite automat. |
| Q9 Grupare | Mașini și scutere, cu capacități diferite; gruparea comenzilor de la restaurante diferite este permisă. | Limite de încărcare și întârziere acceptată, înainte de activarea grupării în Etapa 7. |
| Q10 Alocări | Orice comandă alocată este obligatorie, fără drept de refuz. | Protocolul tehnic de confirmare a primirii, offline și recuperare trebuie proiectat fără a crea un drept de refuz. Regula comercială este clarificată. |
| Q11 Pauză sau final de tură | Pauza/finalul se amână până după terminarea comenzilor, inclusiv comanda următoare pregătită în condiția descrisă. | Care comenzi intră în lotul obligatoriu și momentul opririi noilor alocări. „Pregătită”, „finalizată” și „urma să o primească” trebuie corelate printr-un exemplu. |

## Corelarea cu regulile anterioare

Grilele sunt configurabile per restaurant, separat pentru transport și remunerația livratorului. Exemplul 16/26/36 RON din raportul din 9 octombrie rămâne un exemplu de transport fără restaurant nominalizat. Nu devine plata livratorului sau grila universală.

Formula comunicată anterior pentru transportul în afara zonelor se păstrează: întreaga distanță rutieră restaurant–client, 3 RON/km, minimum 40 RON. Aplicarea rotunjirii kilometrilor în jos este precizarea nouă. Exemplu aritmetic pentru grila respectivă: 15,3 km → 15 km → max(40, 3 × 15) = 45 RON transport. Acesta nu este calculul remunerației livratorului și nu este o tranzacție activată în aplicație.

Valoarea produselor, suma de colectat de la client, transportul datorat de restaurant, remunerația livratorului, avansul și rambursarea sunt poziții distincte. Aprobarea lipsei de fonduri și acceptarea unei rambursări nu marchează automat o plată ca efectuată. Pentru produse preplătite se păstrează regula existentă de a nu încasa din nou de la client.

Restaurantul decide returul imediat sau păstrarea produselor. În cazul păstrării nu există o cursă de retur efectuată și nu se plătește un retur fictiv. Așteptarea de 10 minute și coordonarea administratorului cu restaurantul din regulile anterioare nu sunt revocate explicit. Custodia și obligația de restituire a avansului nu dispar printr-un simplu status de anulare.

La anularea înainte de ridicare, condiția comunicată este strict „depășește 50%”. Exact 50% nu declanșează această condiție; răspunsul nu stabilește o altă compensație pentru acel caz sau pentru distanțe mai mici. Baza monetară rămâne de confirmat. Distanța de tarif restaurant–client, traseul punct de plecare–restaurant și distanța unei schimbări de adresă sunt măsurători diferite.

Pentru schimbarea înainte de sosire se păstrează regula precedentă: transport conform zonei noi, suportat de restaurant, fără supliment distinct. Răspunsul Q6 tratează schimbarea după sosire. Maximum două schimbări nu confirmă automat două suplimente și nu definește referința celui de-al doilea traseu.

Retragerea Q7 și Q8 se înregistrează ca retragere a întrebărilor. Decontarea, istoricul și închiderea zilei nu sunt eliminate. Comenzile active și noi pot continua după închiderea zilei, conform răspunsurilor deja primite.

Q10 are prioritate față de `reserved → refused` și ruta de refuz planificate în `SPECIFICATIONS/PD-DISPATCH-01.md`. Refuzul comercial al livratorului nu mai este cerință. Confirmarea tehnică a primirii nu este același lucru cu acceptarea opțională. Modelul actual singular și prototipurile nu devin alocare multiplă implementată prin această precizare.

## Clarificările rămase

Pentru închiderea calculelor financiare:

1. Tabel per restaurant cu transport și remunerație pe zone, în afara zonelor și la retur; precizarea referinței la zona 1 pentru retur.
2. Plata livratorului și taxarea restaurantului pentru cursa inițială refuzată; cine suportă anularea înainte de ridicare și baza „jumătate din zona 1”.
3. După ridicarea fără plată aprobată de restaurant, când și cum achită livratorul suma restantă.
4. Suplimentul pentru fiecare schimbare eligibilă sau o singură dată; la a doua schimbare, distanța față de adresa inițială sau ultima adresă; comportamentul de cel mult 2 km.

Pentru pauză, exemplul de clarificat este: A în curs, B deja asignată și gata, C gata la restaurant dar neasignată. După cererea de pauză se execută A+B sau și C? Din ce moment încetează noile alocări?

Capacitatea pe vehicul și întârzierea maximă sunt parametri pentru Etapa 7. Acestea nu blochează integrarea documentară sau pregătirea contractelor independente. Întrebările 7 și 8 retrase nu sunt relansate.

## Diferențe față de implementarea actuală

Acestea sunt puncte de corectat în loturile viitoare, nu funcții declarate implementate:

- `backend/routers/orders.py:452` și `backend/utils/order_status.py:546` folosesc încă remunerație de 10%, incompatibilă cu plata fixă per restaurant și zonă. Nu se recalculează retroactiv istoricul.
- `backend/routers/orders.py:575` și `backend/utils/order_creation.py:458` însumează încă produsele cu transportul. Separarea pozițiilor financiare trebuie realizată în modele, validări, API și interfețe.
- `backend/routers/orders.py:870` pune transportul refacerii legacy la zero; regula clientului cere transport suportat de restaurant și remunerație normală pentru livrator.
- `backend/models/driver.py:33` păstrează `current_order_id` singular; `backend/routers/drivers.py:718` respinge pauza/offline cu comandă activă. O cerere durabilă de pauză după executarea lotului nu este prezentă.
- `frontend/src/pages/DriverApp.jsx:719` are „ACCEPT COMANDA”. Viitorul contract trebuie să distingă confirmarea sarcinii obligatorii de dreptul de refuz.
- Modelele comenzilor nu cuprind încă toate distanțele rutiere, originea deplasării și istoricul schimbărilor de adresă. Adăugarea unor câmpuri numai în DB nu este suficientă: `Order.extra="ignore"` poate pierde date la reserializare.

## Ordinea de lucru pe etape

| Ordine | Lot | Rezultat și criteriu de închidere |
| --- | --- | --- |
| 1A | Etapa 1, acest intake | Cele 11 răspunsuri corelate, reguli confirmate separate de restanțe, întrebările retrase și impactul pe etape salvate. Intake documentar închis după review și verificarea păstrării istoricului. |
| 1B | Restanțele Etapei 1 | Clarificările financiare/pauză și verificările Android restante: bateria, precizia în exterior și proba offline completă. Proba a8c rămâne INCOMPLETE, cu HONOR restaurat și serviciile proprii absente. iOS fără Mac rămâne amânat explicit; nu se reînarmează automat telefonul. |
| 2A | S2-05B, sume și tarife | Contracte distincte produse/client/restaurant/livrator/avans, grile versionate, snapshot pe operație și rotunjiri explicite. Valori sintetice declarate pentru QA; grilele incomplete nu sunt activate și nu primesc fallback 0 sau 10%. |
| 2B | S2-05B, lipsă numerar | Declarația livratorului și aprobarea restaurantului propriu, sumă restantă, audit, recuperare și protecție la duplicate. Plata efectivă rămâne distinctă de aprobare. |
| 2C | S2-05B, retur și excepții | Rambursare avans, decizia retur/păstrare, confirmarea returului, refacere, anulare înainte de ridicare și schimbare de adresă pe regulile completate. Custodia și efectele financiare trebuie verificate împreună. |
| 2D | Acceptarea Etapei 2 | S2-07/08 și regresie pe sursa finală: roluri, concurență, audit, retries, pierdere răspuns și recuperare. Loturile deja închise nu se reconstruiesc. |
| 3A | Etapa 3 restaurant | Aprobările și deciziile noi în panoul restaurantului, păstrând lista, pregătirea, READY, programul, incidentele și close-day. Refactorurile A0–A8 închise rămân păstrate. |
| Ulterior | Etapele 5–7 | Livrator, GPS și alocare multiplă: sarcini obligatorii, vehicule/capacitate, grupare, pauză după lotul definit. Specificația se actualizează acum; implementarea și acceptarea rămân în etapele lor. |

Ordinea este Etapa 1, apoi Etapa 2, apoi Etapa 3. Interfețele și contractele necesare altor roluri se includ în lotul aferent; aceasta nu marchează închisă etapa comercială a acelui rol. Răspunsurile clientului nu închid automat acceptanțele Android sau etapele comerciale.

## Verificări pentru implementarea viitoare

La implementare trebuie verificate separat autorizarea restaurantului propriu și a livratorului, concurența, aceeași intenție la retry, prevenirea plăților duble și recuperarea după răspuns pierdut. Schimbarea grilei nu modifică retrospectiv operațiile înregistrate. O distanță lipsă sau incertă rămâne vizibilă și nu devine zero sau eligibilitate fictivă.

Cazurile de acceptanță includ 15,3 km rotunjiți în jos; pragurile exact și peste 50%; distanțele la pragul de 2 km după clarificare; a doua și a treia schimbare de adresă; retur decis versus primit efectiv; păstrarea produselor fără retur fictiv; aprobarea numerarului fără plată fictivă; pauza cerută cu A/B/C. Aceste cazuri sunt planificate și nu reprezintă teste executate.

## Proveniență și continuitate

Autoritate: mesajul furnizat de utilizator în acest chat la 12 octombrie 2026, cu chestionarul și răspunsurile clientului. Rapoartele `2026-10-08-client-operational-rules-intake.md` și `2026-10-09-client-operational-rules-followup.md` se păstrează integral; noul set supersedează numai punctele explicate aici. Retragerile Q7/Q8 și obligația Q10 sunt menținute explicit.

Rutare: Codex-only, conform `.ifrim/AGENTS.md`; verificări independente de consistență și impact pe etape efectuate de doi agenți Codex. Clasificare: `etapa_1_3_core`, specificație. Acest lot salvează cerințele și continuitatea proiectului. Acceptarea funcțională rămâne în loturile de implementare, iar calculele live depind de regulile și tarifele complete.
