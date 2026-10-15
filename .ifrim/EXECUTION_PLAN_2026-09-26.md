## Clarificări client primite la 12 octombrie 2026

Cele 11 răspunsuri din al treilea set sunt integrate în `LOOP_REPORTS/2026-10-12-client-operational-rules-third-set.md`. Numerotarea acestui set este distinctă de cele două chestionare anterioare. Q7/Q8 retrag întrebările; decontările și închiderea zilei se păstrează. Q10 stabilește alocări obligatorii, fără drept de refuz comercial; confirmările tehnice și refuzurile pentru autorizare, capacitate ori date invalide rămân necesare.

Intake-ul documentar este închis după verificări independente de consistență și impact. Grilele și excepțiile financiare, plus exemplul pauzei A/B/C, rămân de completat. Reguli salvate nu înseamnă funcții implementate. Etapele 1 și 2 rămân deschise; ordinea este 1 → 2 → 3, cu loturile exacte din raport.

Răspunsurile clientului nu mai sunt amânate sau absente. Proba Android a8c este încheiată INCOMPLETE/heartbeat_gap, HONOR este restaurat și serviciile proprii sunt absente în dovada de recuperare. Vechile instrucțiuni PENDING, restaurare pending sau scoatere USB din corp sunt istorice și nu se execută. Restanțe Etapa 1: baterie, precizie în exterior, offline complet și clarificări; iOS fără Mac rămâne amânat.

# ProDelivery Plan de executie operational 2026-09-26

## Statut si autoritate

Decizie confirmata de Catalin: el actualizeaza Agent Hub; Codex continua pregatirea ProDelivery. Acest document sincronizeaza cerintele aprobate si defineste executia incrementala. Nu este raport de functionalitati terminate. Nu repornim proiectul de la zero si nu stergem lucrarile existente.

Plan client curent: `C:\Users\mihai\OneDrive\Desktop\ProDelivery_Plan_operational_10000_EUR_v1_2_2026-09-26.docx`. Originalul `ProDelivery_Plan_operational_10000_EUR_REVIZUIT.docx` se pastreaza nemodificat. Numerotarea celor zece etape de mai jos este a pachetului operational nou; vechea Phase 2 / Stage 1 ramane referinta istorica pentru munca si platile deja facute, nu o lista noua de lucrari executate.

Taskul de sincronizare/documentare nu autorizeaza commit/push/deploy, migrari de date reale, schimbari de secrete, servicii cu plata sau lucru in sursa Agent Hub. Pentru fiecare increment de cod se formuleaza un pachet ingust cu dovezi de regresie. Nu se cere din nou aprobarea intregului plan deja confirmat; se clarifica numai deciziile realmente lipsa sau actiunile cu risc si autorizare separata.

## Cerinte ferme si limite

- 10.000 EUR pentru noul pachet, suplimentar fata de platile anterioare documentate. 26.000 EUR este reper istoric, nu pret fix pentru restul versiunii complete. TVA se confirma contabil; nu se deduce regimul fiscal din existenta unui PFA.
- Admin web; restaurant PWA; aplicatie livrator Android/iOS. Nu promitem aplicatii native de restaurant/admin.
- Introducere manuala, OCR cu confirmare umana si integrare API initiala pentru un restaurant. Fara POS. Furnizorul si schimbul exact de date al conectorului nu sunt inca stabilite.
- Alocare automata pentru mai multe comenzi, inclusiv minimum 10 active pe acelasi livrator, nu limita de doua. Plafon configurabil, verificari de capacitate fizica, pregatire, ferestre de timp, GPS si ordine a opririlor. Suportul pentru 10 nu obliga alocarea a 10 comenzi incompatibile.
- Nu promitem optim matematic global, GPS perfect, extragere perfecta din orice bon sau aprobarea garantata de magazine la o data fixa.
- Profilul propus este 50 restaurante si 100 livratori, cu scenariu de varf 1.000 comenzi alocate plus 200 in asteptare. Acesta nu este un rezultat de benchmark; necesita infrastructura, durata si praguri confirmate, apoi teste.
- Tinta trei luni, revalidata prin probe timpurii pentru mobil, GPS, conector si planificare multipla. 90 zile garantie pentru defectele din scop; depunerea in magazine nu echivaleaza cu aprobarea lor.
- Buget intern AI vizat de Catalin: 1.000-1.500 EUR. Este tinta urmarita, nu garantie de consum. Nu apare ca obligatie a clientului in documentul comercial. OCR/rutare/hosting/store sunt costuri distincte de dezvoltarea asistata de AI.

## Rutare si responsabilitati

Codex coordoneaza si implementeaza; OpenClaw si Claude Code nu se invoca, conform instructiunii explicite. Catalin se ocupa de actualizarea Agent Hub. In acest task: owner Codex; review de consistenta si QA document separat, efectuate tot de Codex, fara pretentia de audit independent. Subagenti OpenAI se pot atribui punctual numai prin mecanisme disponibile/aprobate, fara lansarea automata a intregii echipe.

Pentru cod, verificarea separata trebuie sa caute concurenta, autorizare si regresii, nu doar build. Preview: `http://127.0.0.1:3000`; backend `http://127.0.0.1:8000/api/`. Foloseste `PREVIEW.md` pentru pornire, fara citirea/afisarea secretelor. Acest task documentar nu necesita pornirea sau publicarea aplicatiei.

## Cele zece etape ale noului pachet

| Etapa | Rezultat | Dovada ceruta |
| --- | --- | --- |
| 1 | Inventar actual, reguli si specificatie inchisa | Harta cerinta-cod-test; API nominalizat sau blocaj explicit; probe mobile si dispatch |
| 2 | Comenzi si administrare | Creare, modificare, autorizare, conflicte, duplicate si audit verificate |
| 3 | Panou restaurant | Acceptare, pregatire, gata, pauza, inchidere zi si incidente fara pierderi |
| 4 | OCR si conector API initial | Confirmare OCR; import autentificat, deduplicare si recuperare; manual disponibil |
| 5 | Aplicatie livrator | Android/iOS pe dispozitive; sarcini multiple, offline/revenire, ecran blocat |
| 6 | GPS si harta | Pozitii cu varsta/precizie, eligibilitate, teren/baterie si confidentialitate |
| 7 | Alocare si ordinea opririlor | 1/2/5/10 comenzi, restrictii, concurenta, expirare si replanificare controlata |
| 8 | Notificari, exceptii, rapoarte simple | Oferte si incidente vizibile; livrare notificari testata pe telefoane |
| 9 | Infrastructura si securitate | Restore demonstrat; roluri/date/limite; benchmark conform profilului adoptat |
| 10 | Pilot, publicare, instruire, predare | Zi reala de operare, dovezi finale; depunere magazine distincta de aprobare |

Lucrarile se suprapun tehnic. Nu asteptam etapa 7 pentru a descoperi ca modelul de date accepta o singura comanda sau ca GPS in fundal nu functioneaza.

## Dovezi din cod citit la 26 septembrie

- `backend/models/driver.py:33`: `current_order_id` singular.
- `backend/routers/orders.py:450`: o alta comanda curenta produce conflict la alocare.
- `backend/routers/orders.py:462`: rezervare atomica pentru modelul singular; trebuie pastrata protectia la concurenta.
- `backend/routers/orders.py:291` si fluxul terminal de la linia 746: eliberarea asignarii poate elibera intregul livrator; incompatibil cu 10 comenzi daca se modifica doar un camp.
- `backend/routers/drivers.py:674`, `:697`, `:711`: disponibilitatea, pauza/offline si datele livratorului depind de acelasi camp.
- `backend/models/order.py`: stari de pregatire si livrare in enum comun; adaptarea trebuie sa pastreze contractele deja folosite, fara reinterpretarea tacita a comenzilor existente.
- Exista teste de autorizare, hardening si fluxuri critice in `backend/tests`. Nu au fost executate in acest task documentar. Rezultatele istorice nu sunt dovada curenta.
- Inspectia a fost focalizata, nu audit exhaustiv de productie. Nu declaram OCR, conector, nativ mobil sau 10 comenzi terminate pe baza planului ori a unui ecran web.

## Pachetul tehnic initial PD-DISPATCH-01

### Rezultat

Model si contracte pentru 1/2/5/10 comenzi pe acelasi livrator, cu compatibilitate pentru fluxul singular existent si teste care detecteaza pierderea asignarilor. Nu activa repartizarea automata pe date reale la finalul unei simple schimbari de schema.

### Invarianti obligatorii

1. O comanda are cel mult o asignare activa sau rezervare validata pentru acelasi moment; o oferta invalida nu poate fi acceptata dupa expirare/realocare.
2. Comenzile si ofertele care rezerva locuri sunt numarate impreuna. Doua cereri concurente pentru ultimul loc nu pot depasi plafonul.
3. Finalizarea/anularea unei comenzi elibereaza numai resursele ei; celelalte asignari si opriri raman intacte.
4. Ridicarea precede livrarea pentru fiecare comanda. Opririle deja executate nu se reordoneaza; comenzile ridicate nu se transfera automat altui livrator.
5. Disponibilitatea livratorului, GPS proaspat, capacitatea, pregatirea, ferestrele si versiunea rutei se reverifica la rezervare/acceptare, nu doar la calcul.
6. Rolul si restaurantul/livratorul sunt validate server-side pentru fiecare actiune. Actiunile administrative manuale nu ocolesc neobservat invariantii.
7. Timeout, restart sau raspuns pierdut nu dubleaza comenzi, oferte sau livrari; reluarea aceleiasi operatii returneaza rezultatul identificabil.
8. Auditul pastreaza actor, sursa, operation_id, versiune, tranzitia si motivul. Fara adrese/telefoane/secrete in loguri inutile.

### Model incremental propus

- Asignari cu ID, order_id, driver_id, stare, lease/expirare, versiune; ruta cu opriri ordonate pickup/dropoff si versiune; capacitate pe livrator/vehicul.
- Sursa autoritativa a rezervarii trebuie aleasa explicit. Nu implementa doar `current_order_ids` plus increment/decrement neatomic in colectii diferite.
- Verifica intai topologia MongoDB: tranzactiile multi-document necesita suport real. Alege tranzactie suportata sau protocol de rezervare atomica plus reconciliere crash-safe demonstrata. Nu presupune replica set si nu modifica baza reala pentru a-l obtine.
- Pastreaza temporar un adaptor pentru `current_order_id` cat timp consumatorii existenti sunt actualizati controlat; campul legacy nu mai decide independent capacitatea. Raporteaza discrepantele, nu sterge automat asignari.
- Idempotenta durabila cu cheie scoped pe actor/operatie, hash payload si rezultat; reutilizarea cheii cu payload diferit produce conflict. Indexuri unice si CAS pentru versiuni unde modelul o cere.
- Modelarea pregatirii restaurantului ramane distincta logic de oferta/asignare/executie. Orice schimbare a starilor publice necesita mapare, teste de compatibilitate si migrare aprobata.
- Plan de migrare aditiv, dry-run pe fixture/copie autorizata, rapoarte de numar/integritate si restore verificat. Fara conversie sau rollback orb pe date live.

### Calculul rutei

- Reguli de eligibilitate si validare finale in backend, fara LLM in bucla de alocare. Costurile AI nu cresc cu fiecare decizie a dispeceratului.
- Candidat pentru nucleul de optimizare: OR-Tools, evaluat pe fixture-uri reproductibile inainte de alegerea definitiva. Nu instalat/integrat prin acest document.
- Perechi pickup/dropoff, precedenta, capacitate pe parcurs, timpi de pregatire/serviciu, ferestre, destinatii si opriri executate fixe.
- Filtrare locala a candidatilor si buget CPU finit; pastreaza cea mai buna solutie fezabila gasita, nu promite optim global. La timeout foloseste ruta valida existenta sau coada manuala, nu o solutie neverificata.
- Distanta in linie dreapta poate prefiltra, dar ETA foloseste drum/timp de calatorie cand exista sursa aprobata. Cache, rate limits, timeout si costuri pentru furnizorul de rutare.
- Test de 10 fezabil plus test de 10 nefezabil. Un esec de fezabilitate trebuie explicat, nu mascat drept lipsa generica a livratorilor.

Referinte tehnice primare consultate: https://developers.google.com/optimization/routing/pickup_delivery ; https://developers.google.com/optimization/routing/vrptw ; https://developers.google.com/optimization/routing/cvrp ; https://developers.google.com/optimization/routing/routing_options . Exemplele bibliotecii nu demonstreaza performanta acestui proiect.

## Pachet PD-API-01 si informatii lipsa

Un restaurant nu implica automat un singur furnizor: trebuie identificata sursa exacta. Nu presupune existenta API-ului sau drepturi de acces. Nu cere credentiale in document/chat.

Fișa de completat: restaurant; furnizor/produs; documentatie si versiune; persoana tehnica; acces autorizat/sandbox; metoda de autentificare; identificator local/extern restaurant; webhook sau polling; order/event IDs; timestamp/sequence; adresa/telefon/coordonate/produse/plata; anulare/modificare; confirmari de import; statusuri outbound solicitate; limite/taxe; retentie si date de test.

Contractul intern foloseste o sursa si identitate externa stabile. Evenimentele sunt validate si persistate intr-un inbox durabil inaintea confirmarii; procesarea este idempotenta. Cheile unice includ tenant, furnizor, restaurant si ID extern potrivit. Evenimentele vechi nu regreseaza statusul; lipsa secventei impune reconciliere documentata. Retry finit cu backoff/jitter si Retry-After, limita de incercari/timp, coada de erori vizibila. Recuperarea nu inventeaza evenimente pe care API-ul nu le poate furniza.

Separa ingestia, normalizarea, confirmarea, crearea comenzii si eventualele statusuri trimise inapoi. Deduplicarea intre OCR/API/manual foloseste identitate demonstrabila; potrivirea probabilistica produce avertizare/verificare, nu stergere automata. Anularea dupa pickup devine incident controlat. Lipsa furnizorului blocheaza conectorul specific, nu testele si modelul independent pentru dispatch.

## Matrice de teste pentru primele incremente

Toate cazurile de mai jos sunt planificate, nu executate. Q01-Q30 din documentul client raman criterii de verificare end-to-end.

| ID | Caz | Asertiune care trebuie sa detecteze regresia |
| --- | --- | --- |
| D01 | 1, 2, 5, 10 comenzi fezabile | Toate asignarile si opririle exista; niciuna nu suprascrie alta |
| D02 | Noua active si doua oferte concurente | Exact un loc rezervat; total activ plus rezervat <= 10 |
| D03 | A unsprezecea la plafon 10 | Conflict explicabil, fara scrieri partiale |
| D04 | Limita pe vehicul mai mica | Limita fizica respectata chiar daca numarul maxim este 10 |
| D05 | Livrare una din zece | Celelalte noua raman asignate si ordonate |
| D06 | Anulare una nepreluata | Se elibereaza numai comanda si opririle afectate |
| D07 | Anulare dupa ridicare | Incident; fara realocare automata sau disparitia comenzii |
| D08 | Acceptare repetata/raspuns pierdut | Un rezultat idempotent si o singura asignare |
| D09 | Ridicat/livrat repetat | Niciun decrement dublu sau efect extern duplicat |
| D10 | Oferta expirata sau retrasa | Acceptare respinsa si stare actuala returnata |
| D11 | Doi admini realoca simultan | Un castigator; versiunea veche nu modifica ruta |
| D12 | GPS vechi intre calcul si commit | Eligibilitate reverificata; motiv vizibil |
| D13 | Pregatire modificata | Ruta reevaluata fara rescrierea opririlor executate |
| D14 | Zece comenzi nefezabile | Nu forteaza traseu invalid; exceptia ramane vizibila |
| D15 | Restart dupa rezervare inainte de raspuns | Recuperare fara loc pierdut, asignare orfana sau duplicat |
| D16 | Timeout solver/rutare | Revine limitat la ruta valida sau manual; fara bucla infinita |
| D17 | Pauza/offline cu comenzi active | Regula convenita aplicata tuturor asignarilor, nu doar legacy |
| D18 | Restaurant/driver strain | 403/404 dupa contract, zero modificari neautorizate |
| D19 | Comanda legacy singulara | Fluxul existent continua si nu apare numarare dubla |
| D20 | Mobil pierde internet, revine/refresh | Actiunile nesincronizate nu apar finalizate fictiv; conflict vizibil |
| A01 | Webhook autentic plus replay | O procesare; audit cu aceeasi identitate |
| A02 | Semnatura/tenant invalid | Respins; zero persistenta de comanda neautorizata |
| A03 | Payload incomplet/limita depasita | Eroare structurata sau inbox de verificare, fara crash |
| A04 | Evenimente in ordine inversa | Nicio regresie a statusului |
| A05 | 429, timeout, 5xx | Retry limitat si recuperare identificabila |
| A06 | API plus OCR cu acelasi ID | O comanda; cazurile ambigue necesita om |
| A07 | Crash dupa persistare inainte de procesare | Inbox reluat o singura data logic |
| A08 | Anulare externa dupa pickup | Incident, nu stergere sau livrare fantoma |

Niveluri: teste pure fara DB pentru reguli; integrare Mongo intr-un mediu separat cu topologie cunoscuta pentru concurenta; contracte API cu fixture-uri, apoi sandbox autorizat; browser pentru admin/restaurant; telefoane fizice pentru GPS/push/fundal. Nu folosi numai fake DB ca dovada a atomicitatii Mongo.

## Ordine de executie si gate-uri

1. Inventar focalizat al consumatorilor `current_order_id`, testelor si starilor; rulat baseline relevant pe mediu izolat. Nicio presupunere bazata pe rapoarte vechi.
2. Specificatie de asignare/capacitate/ruta si testele D01-D20. Aleasa sursa autoritativa si protocolul de concurenta dupa validarea Mongo.
3. Proba OR-Tools si proba Android/iOS GPS/push, cu timpi/costuri/limitari masurate. Alegerea bibliotecii native se justifica pe codul existent.
4. Implementare backend incrementala cu compatibilitate; apoi consumatorii admin/restaurant/driver. O functie nu e gata daca doar schema/buildul trece.
5. Conectorul API porneste dupa fisa completata; OCR/manual raman independente. Accesul real si costurile se aproba distinct.
6. Review de riscuri plus regresie live pe fluxuri afectate si adiacente; capturi, console/API errors si rezultate exact numarate. Pilot si publicare doar autorizate.

Nu exista blocaj pentru pregatirea testelor/dispatch din cauza Hub. Sunt blocate numai detaliile furnizorului API si orice promisiune de cost/timp/capacitate nevalidata.
