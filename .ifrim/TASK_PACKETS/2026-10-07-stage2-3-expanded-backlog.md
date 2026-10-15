# ProDelivery - Plan extins de lucru dupa S2-01

Data: 2026-10-07. Tip: plan de executie, nu raport de implementare.
Proiect: C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery

## 1. Autoritate, stare si rezultat urmarit

Acest document detaliaza planul comercial cu zece etape din
`.ifrim/EXECUTION_PLAN_2026-09-26.md`. Nu renumeroteaza etapele, nu
reporneste proiectul si nu inlocuieste rapoartele sau lucrarile existente.

Sursa curenta de stare este antetul din NEXT_SESSION.md datat 2026-10-07:

- Etapa 1: in_progress; probele native si pe telefoane raman deschise.
- Etapa 2: in_progress; S2-01 este complete pentru contracte si teste.
- Contractele noi NU sunt conectate la endpointuri sau interfata.
- Idempotenta durabila, recuperarea crearii si revizia comuna tuturor
  scriitorilor sunt lucrari de facut, nu rezultate ale unui hash de payload.
- Aplicatia pastreaza `current_order_id` singular; multi-comanda si
  repartizarea automata nu sunt active.

Catalin a aprobat lucrul pe comenzi/admin independent de probele fizice GPS.
Aceasta decizie inlocuieste numai vechiul blocaj global de pornire a Etapei 2
din planul 2026-10-02, nu declara Etapa 1 terminata.

Tinta imediata: un flux demonstrabil in care adminul creeaza o comanda,
poate recupera rezultatul dupa raspuns pierdut, o corecteaza in limitele
permise, intervine manual la asignare si vede istoricul coerent. Restaurantul
si livratorul isi pastreaza fluxurile actuale.

Aceasta cerere produce numai planul. Nu autorizeaza prin ea insasi activarea
unei etape noi, mutatii pe date reale, indexuri/topologie live, servicii
platite, schimbari env/secrete, commit, push sau deploy.

## 2. Organizarea executiei

- Codex coordoneaza. Numai Codex si subagenti interni; fara OpenClaw/Claude.
- Ownerul backend si ownerul frontend pot lucra in paralel pe fisiere
  disjuncte si numai dupa stabilizarea contractului comun.
- Reviewerul si QA sunt separate de implementer. Nu se lanseaza toata
  echipa pentru fiecare modificare mica.
- Un singur owner scrie in orders.py la un moment dat. Lucrarile concurente
  folosesc scope/lock explicit; nu se concureaza pe acelasi router.
- Fiecare sublot are task packet, backup/hash pentru fisierele atinse,
  cazuri de acceptare, review si raport cu limitele dovezilor.
- Nu copiem o proba izolata direct in productie fara integrare async,
  autentificare, compatibilitate si verificari pe consumatorii existenti.

Regula de inchidere a unui sublot: teste relevante executate pe sursa
integrata, review fara probleme blocking si QA pentru fluxurile afectate.
Un build verde nu inlocuieste interactiunile in browser. Testele fizice GPS
blocheaza livrarea GPS, nu contractele sau formularul de comenzi independente.

## 3. Valul A - Creare recuperabila si compatibilitate

### S2-02A - Inventar al scriitorilor si alegerea protocolului

Depinde de S2-01. Owner: backend; review: backend/data; QA: contracte.

- Mapam create, edit, assign/reassign, preparing, ready, accept, pickup,
  deliver, cancel, probleme/refaceri si orice scriere indirecta.
- Documentam ce colectii si efecte modifica fiecare actiune, inclusiv
  driver, audit, numerotare si contori.
- Alegem protocolul atomic pe baza topologiei demonstrate in mediul
  sintetic, nu presupunem tranzactii disponibile in baza curenta.
- Definim timpul maxim, rezultatele aplicat/reluat/in curs/respins si
  responsabilul pentru recuperarea unei operatii intrerupte.
- Modulul comun nou se introduce numai daca elimina duplicarea reala.

Acceptare: harta tuturor scriitorilor si un protocol testabil; niciun writer
legacy ignorat. Fisiere probabile: orders.py, drivers.py, models/order.py,
utils relevante; modificarea lor se stabileste prin inspectie focalizata.

### S2-02B - Admitere durabila si o singura creare logica

Depinde de S2-02A. Owner: backend; review: concurenta/security; QA: Mongo.

- Persistam intentia cu identitatea (actor, tip, client_operation_id).
- Targetul si payloadul semantic sunt imuabile in digest; reutilizarea
  cheii pentru alte date produce conflict, nu o noua comanda.
- Legam efectul business, rezultatul si auditul critic prin protocolul ales.
- Pastram regulile actuale pentru restaurant, taxa, numerotare si bani.
- Revalidam rolul, contul si disponibilitatea restaurantului la executie.
- Unicitatea este impusa durabil, nu printr-un lock intr-un singur proces.

Acceptare: cereri simultane din doua procese produc un singur efect;
payload diferit este respins; erorile nu lasa o comanda fara rezultat
recuperabil. Testele ruleaza separat de baza aplicatiei.

### S2-02C - Recuperare dupa timeout, crash sau raspuns pierdut

Depinde de S2-02B. Owner: backend; reviewer: data; QA: fault injection.

- Lookup/replay autorizat dupa operation_id; actorul nu vine din payload.
- Deadline, numar de incercari si backoff finite; fara bucla infinita.
- Distingem crash inainte de commit, dupa commit si inainte de ACK.
- O operatie in curs ramane vizibila; nu mintim ca a esuat sau a reusit.
- Cont dezactivat sau rol schimbat: accesul la rezultat este reevaluat.
- Replay este dovada operatiei anterioare, nu snapshot garantat actual.

Acceptare: reluarea aceleiasi intentii recupereaza comanda originala,
inclusiv dupa restart; niciun duplicat sau efect secundar repetat.

### S2-02D - Integrare in formularul admin

Depinde de contractul S2-02B/C. Owner: frontend; review: frontend; QA: browser.

- Generam o identitate per intentie, pastrata pentru reluarea ei.
- Blocare sincrona la submit plus loading/disabled; dublu-click acoperit.
- Timeout-ul mutatiei porneste recuperarea, nu retrimiterea cu o cheie noua.
- Definim recuperarea dupa reload fara stocarea inutila a datelor personale.
- Schimbarea datelor unei intentii deja admise cere rezolvarea ei, nu
  reutilizarea aceleiasi chei cu alt payload.
- Succesul crearii si esecul refreshului sunt mesaje distincte.
- Pastram designul; modificam doar controalele/states necesare.

Fisiere probabile: AdminDashboard.jsx, api.js, orderWorkflow.js si helper
mic pentru intentii daca se justifica. Acceptare: create valid/invalid,
double-click, doua taburi, reload, offline/revenire, timeout, 401/403/409/5xx.

Rezultatul vizibil al Valului A: adminul poate crea si regasi aceeasi comanda
fara duplicare. Endpointurile testate izolat nu inseamna activare live.

### S2-COMPAT - Revizie comuna tuturor scriitorilor

Obligatoriu inainte de S2-03. Poate fi pregatit in paralel cu S2-02D,
dar modificarile aceluiasi router se serializeaza.

- Toti writerii folosesc aceeasi revizie/CAS sau refuza explicit v2.
- Prepararea, statusul, asignarea si problemele nu suprascriu o editare noua.
- Mapare explicita legacy/v2; fara versiune inventata de client.
- Testam edit versus preparing/ready/accept/pickup/cancel.

Acceptare: un castigator sau refuz explicit, fara update pierdut. Protectia
nu se amana pana la alocarea multipla si nu se limiteaza la endpointul edit.

## 4. Valul B - Control operational in admin

### S2-03A/B - Corectii permise, API si formular

Depinde de S2-02 si PASS S2-COMPAT. Owneri: backend/frontend separat.

- Campuri initiale: nume, telefon, adresa, coordonate pereche, observatii.
- Identitatea comenzii/restaurantul/sursa/statusul nu sunt patch generic.
- Modificarile produselor, platii si taxelor necesita regula separata;
  nu schimbam tacit semantica financiara actuala.
- Revizie obligatorie, audit al modificarilor si mesaj clar de conflict.
- La conflict pastram textul introdus si afisam starea actualizata.
- Regula conservatoare: corectii operationale inainte de pickup; dupa
  pickup, schimbarea destinatiei devine incident controlat.

Acceptare: doi admini, versiune veche, camp gol, lungimi maxime, coordonate
incomplete, alt rol, terminal/pickup concurent, timeout si reluare.
Vizibil: formular de corectie fara pierderea modificarilor utilizatorului.

### S2-04A/B - Alocare si realocare manuala sigure

Depinde de protocolul comun si S2-COMPAT. Owner: backend, apoi frontend.

- Revendicare consistenta comanda/asignare/driver/rezultat/audit.
- Disponibilitate si capacitate reverificate la commit, nu doar in dialog.
- Realocarea invalideaza vechea oferta si pastreaza pregatirea restaurantului.
- Vechiul livrator nu poate accepta/ridica dupa o realocare valida.
- Dupa pickup nu transferam automat custodia la alt livrator.
- Motive operationale clare pentru refuz; manualul nu ocoleste invariantii.
- Pregatim compatibilitatea multi fara activarea incompleta a zece comenzi.

Acceptare: doi admini, accept versus reassign, doua cereri pentru ultimul
loc, driver dezactivat/pauza, pregatire schimbata, raspuns pierdut.
Fixture-urile multi verifica eliberarea unei singure asignari; ele nu
constituie demonstratie ca UI/runtime live accepta deja zece.
Vizibil: alocare manuala cu rezultat si conflicte explicate.

### S2-05A/B - Anulare, custodie si problema/refacere

Depinde de S2-04. Owneri: backend/frontend; review: data; QA: flux complet.

- Anulare eligibila cu motiv, actor, revizie si istoric, fara stergere.
- Cleanup strict pentru resursele comenzii afectate.
- Dupa pickup: incident si rezolutie explicita, nu disparitia marfii.
- Refacere partiala legata de comanda initiala, fara dublarea accidentala
  a taxelor, contorilor ori creditului livratorului.
- O comanda livrata nu este resetata silentios la NEW.
- Urmam regulile financiare existente; orice regula noua ambigua se
  confirma punctual inainte de activare.

Acceptare: cancel repetat, cancel versus deliver/pickup, status terminal,
produs lipsa, refacere partiala, acces restaurant/driver strain.
Vizibil: motivul si legatura incidentului, fara centru complex de exceptii.

## 5. Valul C - Liste complete si inchiderea Etapei 2

### S2-06A - Citiri, filtre si paginare server-side

- Liste active si istoric separate, filtrate conform rolului.
- Ordine stabila cu tie-breaker; paginare cu limite explicite.
- Filtre restaurant, driver, status si data fara pierderea comenzilor.
- Detaliu autorizat cu pregatire distincta de executie si asignare.
- Contract pentru date lipsa/invalid; nu afisam status inventat.

Acceptare: timestamp egal, ultima pagina, filtru schimbat, volum peste
limita veche, date incomplete, acces neautorizat. Owner: backend; QA: API.

### S2-06B - Detaliu, istoric si refresh sigur in UI

- Integram API-ul fara redesign; respectam filtrele dupa mutatii.
- Raspuns GET vechi nu suprascrie rezultatul mai nou.
- Loading/empty/offline/eroare vizibile; retry numai pentru citiri eligibile.
- Detaliu cu timpi, driver, sursa si istoric autorizat.
- Pe mobil: texte lizibile, butoane accesibile, fara overlap.

Acceptare: navigare lista/detaliu/inapoi, reload, offline/revenire,
refresh esuat dupa succes si raspunsuri sosite in ordine inversa.
Owner: frontend; reviewer: frontend; QA: browser desktop/mobil emulat.

### S2-07 - Audit si diagnostic, inclus in fiecare val

- Actor/rol/actiune/order_id/operation_ref/versiuni/ora server/request_id.
- Audit critic legat de commit; replay fara eveniment business duplicat.
- Loguri fara parole, tokenuri, telefon/adresa sau trasee GPS brute.
- Erori coerente; conflictul nu devine 500 si DB indisponibila nu devine OK.
- Efectele externe viitoare au mecanism durabil; nicio trimitere reala
  email/push in testele acestei etape.

Acceptare: injectie eroare DB/audit, corelare operatie-efect, control acces
la istoric si verificare PII. Owner: backend; review: security/data.

### S2-08 - Regresie si raport de inchidere

Flux obligatoriu: admin creeaza -> restaurant pregateste -> admin aloca ->
driver accepta -> restaurant gata -> pickup -> deliver -> istoric.

Variante obligatorii: roluri straine, double-click, doi admini, reassign,
pauza/inchidere restaurant, timeout/ACK pierdut, restart/reload/offline,
problema/refacere si rollback cu intentie de creare in curs.

- Teste pure pentru reguli; HTTP pentru contracte si roluri; Mongo real
  separat pentru concurenta/recovery; browser pentru interactiuni.
- Auth injectata se eticheteaza; nu este dovada de autentificare E2E.
- Niciun test nu incarca automat .env sau foloseste baza activa.
- Reviewer final si QA separati; rezultate exacte, versiune/hash, capturi
  fara date personale, console/API errors si limite documentate.
- Orice defect blocking mentine sublotul deschis; nu stergem teste.

Etapa 2 se poate inchide numai pentru scopul verificat. Nu certifica
OCR/API, publicarea mobila, GPS, auto-dispatch sau benchmarkul 50/100.

## 6. Urmatoarea etapa functionala - Panou restaurant

Etapa 3 este urmatorul pachet planificat; pornirea respecta aprobarile
curente si inchiderea Etapei 2. Nu refacem functiile care exista deja.

| Lot | Lucrare incrementala | Dovada de acceptare |
| --- | --- | --- |
| S3-01 | Reconciliere lista/detaliu, active si istoric propriu | Nicio comanda straina, liste complete, reload sigur |
| S3-02 | Acceptare si timp de pregatire prin protocolul comun | Double-click, timp invalid/repetat, conflict cu admin |
| S3-03 | Marcare gata si timer coerent | Timer expirat nu declara singur READY; gata repetat sigur |
| S3-04 | Pauza, revenire, inchidere zi cu active pastrate | Nu dispar activele; noile comenzi respecta regula convenita |
| S3-05 | Problema/produs lipsa/refacere legata | Fara reset terminal sau taxe duplicate; roluri verificate |
| S3-06 | Fiabilitate PWA si regresie pe mobil | Offline/revenire, reload, butoane/loading, fara overlap |

Ownerii backend/frontend au scope separat, reviewerii potriviti si QA
independent. Pauza/inchidere zi nu sterg comenzile active. Comportamentul
exact pentru primirea/acceptarea lor se verifica in regulile existente;
o schimbare de politica operationala se confirma, nu se ghiceste.

Restaurantul ramane PWA, nu promitem aplicatie nativa separata.

## 7. Pista nativa independenta si etapele ulterioare

In paralel cu valurile independente se poate continua pregatirea deja
aprobata a micro-probei, fara schimbarea bazei aplicatiei:

1. Investigam cauza instalarilor blocate, nu repetam orb acelasi install.
2. Obtinem instalare/typecheck/bundle reproductibile si documentam toolchain.
3. Build Android/iOS numai pe calea disponibila/autorizata.
4. Pe telefoane: permisiuni, foreground/background, ecran blocat, offline,
   revenire, timestamp/precizie si consum baterie.

Telefon/tester/consimtamant si provisioning iOS raman dependente distincte.
Aceste lucrari nu declara Etapele 5/6 terminate si nu activeaza colectarea
GPS reala de la client fara autorizare.

Cele zece etape raman:

1. Inventar, reguli, specificatie si probe de risc.
2. Comenzi si administrare - planul detaliat de mai sus.
3. Panou restaurant - acceptare, pregatire, gata, operare zilnica.
4. OCR cu confirmare si conector API initial pentru un restaurant.
5. Aplicatia livrator Android/iOS, actiuni si sarcini multiple.
6. GPS si harta cu prospetime, precizie si confidentialitate.
7. Alocare automata si ordinea opririlor, minimum 10 fezabile pe acelasi
   livrator, capacitate/ETA/pregatire/ferestre; interventie manuala permanenta.
8. Notificari, exceptii operationale si rapoarte simple.
9. Infrastructura, securitate, restore si teste de incarcare.
10. Pilot, publicare, instruire si predare.

Documentatia API lipsa blocheaza numai conectorul specific. GPS/rutare sunt
dependente ale alocarii automate reale; nu alocam dupa pozitii inventate.
50 restaurante/100 livratori este profil de test viitor, nu capacitate
demonstrata. Cercetarea factorilor publici nu este algoritmul proprietar
al unei alte platforme. Nu folosim LLM pentru fiecare decizie de dispatch.

## 8. Activare, migrari si rollback

Inainte de orice activare v2 pe date existente este obligatoriu S2-MIGRATION:

- Dry-run pentru versiuni lipsa/null/invalide, duplicate, orfani si conflicte.
- Backfill conservator; cazurile ambigue se raporteaza, nu se sterg.
- Reconciliere counts/legaturi/invarianti inainte si dupa.
- Backup si restore demonstrat in mediu separat.
- Indexurile si topologia se aplica numai cu aprobarea distincta necesara.

Rollback-ul pastreaza lookup/replay/recovery pentru intentiile create in
curs sau cu ACK pierdut. Nu readuce un writer legacy peste date v2 active,
nu sterge asignari si nu elimina outbox-ul necesar recuperarii.

Daca activarea live nu este aprobata, lotul poate fi verificat pe mediu
sintetic si raportat astfel; nu este declarat live sau productie.

## 9. Ordinea imediata si punctele de demonstratie

1. S2-02A/B/C: backend create/recovery, review si teste independente.
2. S2-02D: formular admin, demo browser; S2-COMPAT fara overlap de writers.
3. S2-03: corectii; S2-04: manual assign/reassign dupa contractele comune.
4. S2-05: cancel/incidente; S2-06: liste/detaliu/istoric.
5. S2-08: regresie completa a Etapei 2; apoi pachetul Etapei 3.

Demonstratii pentru Catalin/client, numai dupa verificare:

- A: creare fara duplicate si recuperare dupa raspuns pierdut.
- B: corectie si realocare cu conflicte explicate.
- C: istoric si incident/refacere legata, cu fluxul complet pastrat.
- D: operare zilnica restaurant, dupa S3 si QA.

Nu promitem incheierea a doua etape intr-o zi. Dupa primul increment
integrat reestimam restul folosind timpi si defecte reale, nu numarul de
teste. Obiectivul este un rezultat vizibil verificat la fiecare val.

## 10. Dovezi si limite la data planului

Git verificat in acest task: main...origin/main, modificari si fisiere noi
existente. Nicio schimbare preexistenta nu se revine sau se elimina.

Checkpoint anterior S2-01: 1193 backend + 74 frontend = 1267 teste distincte
trecute, conform LOOP_REPORTS/2026-10-07-s2-01-contracts.md. Aceste teste
NU au fost rerulate pentru redactarea planului. Nu sunt dovada ca rutele
noi sau mutatiile durabile sunt implementate.

Preview documentat: http://127.0.0.1:3000/login
API documentat: http://127.0.0.1:8000/api/
Nu s-a pornit/verificat preview in acest task documentar. Ultima verificare
HTTP200 este in raportul anterior; click-through a avut blocker CDP.
La urmatoarea schimbare UI verificam runtime, ruta afectata si fluxurile
adiacente. Un blocker browser se raporteaza; nu se inventeaza PASS.

Acest plan este un artefact nou. Niciun fisier de cod, configuratie, baza
de date sau raport anterior nu a fost modificat prin redactarea lui.
