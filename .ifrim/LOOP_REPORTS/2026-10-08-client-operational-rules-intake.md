# ProDelivery - Raspunsuri operationale client, 2026-10-08

## Statut si limite

Intake de cerinte, nu implementare, activare sau validare a politicii complete.
Etapa 2 - Comenzi si administrare ramane in_progress, in planul 10.000 EUR /
10 etape. Nu reconstruim S2-01..06. Acest raport clarifica partial dependenta
S2-05B; valorile si cazurile financiare neprecizate raman deschise.

Owner: Codex. Routing: Codex only, conform regulii proiectului. Verificare:
corelare cu mesajul original al celor 15 intrebari, citire captura, transcriere
locala automata si inspectie punctuala a codului. Nu exista review independent
sau QA functional nou in acest intake; nu s-a schimbat aplicatia.

Clasificare: etapa_1_3_core / engineering_support pentru specificatie.
GPS si tarifarea geospatiala raman la etapele si gate-urile lor. Nu modificam
pretul, calendarul comercial sau infrastructura prin primirea raspunsurilor.

## Surse

- Captura furnizata in chat: codex-clipboard-fc074c46-7e9a-416b-825b-e4ed0c1aeacd.png.
  SHA256: 2A334A2F26CF263B45A4D91E3ED840B8751892AFA146DF62A388271F1F10D89C.
- WhatsApp Ptt 2026-10-08 at 16.14.08.ogg, durata detectata 37.9935 secunde.
  SHA256: 04A8AC40BEE29DEDB704A84122FB8C244A297917FF56A04C2257D4C28CF8F49B.
- WhatsApp Ptt 2026-10-08 at 16.14.16.ogg, durata detectata 4.7335 secunde.
  SHA256: 3E41E37C797ADB72F2A7A75C7F948D1D9E408B9193A8B3BD99F4A5652D1DD88E.
- Lista originala regasita in istoricul acestui chat, mesajul assistant din
  2026-10-07T21:38:02.364Z. Numerotarea de mai jos este aceeasi.

Audio procesat numai local cu faster-whisper, modelul small deja in cache,
CPU int8, language=ro, beam_size=5, local_files_only=True si HF_HUB_OFFLINE=1.
Nu s-au descarcat modele si nu s-a trimis audio catre servicii externe.
Nu copiem fisierele audio sau imaginea in repo. Transcrierea automata are
erori lexicale; redam sensul pasajelor clare, nu un citat exact sau o garantie
de transcriere integrala. Prima rulare a esuat la afisarea diacriticelor in
cp1250; rerularea cu JSON ASCII a procesat ambele fisiere pana la exit0.

## Cele 15 raspunsuri corelate

1. Cine achita transportul obisnuit: restaurantul. Nu inseamna ca produsele
   clientului sau incasarile cash sunt venit al livratorului.
2. Tarif transport: pe zone. Audio adauga exceptia pentru comenzi introduse
   manual in afara ariilor stabilite: calcul dupa kilometri restaurant-client,
   cu afisarea automata a tarifului dupa introducerea adresei. Formula lipseste.
3. Remuneratie livrator: suma fixa pe livrare. Valoarea, moneda si eventualele
   diferente pe restaurant/zona nu au fost comunicate. NU procent de 10%.
4. Produs lipsa/neconform: clientul a achitat initial suma de pe bon, daca
   plata este cash; ulterior contacteaza restaurantul, care stabileste rezolvarea.
   Raspunsul NU precizeaza daca refacerea este intotdeauna gratuita, cine aproba
   o eventuala diferenta sau cum se trateaza plata deja efectuata electronic.
5. Transport suplimentar pentru refacere: suportat de restaurant.
6. Livratorul pentru refacere: remunerat ca la o livrare obisnuita. Nu presupunem
   plata zero doar fiindca produsele suplimentare pot fi gratuite.
7. Produse noi solicitate dupa livrare: comanda noua, distincta de original.
   Nu redeschidem originalul DELIVERED si nu il creditam din nou.
8. Client indisponibil/refuz: asteptare 10 minute la adresa, restaurantul este
   informat. Returul sau alta rezolutie sunt decise de administrator impreuna
   cu personalul restaurantului. Nu este retur/anulare automata dupa 10 minute.
   Costurile, plata returului si traseul marfii cand nu se returneaza lipsesc.
9. Adresa schimbata dupa ce livratorul a ajuns la client: daca deplasarea
   relevanta depaseste 2 km, livratorul primeste in plus un transport de zona 1.
   Nu extindem regula la schimbari inainte de sosire. Trebuie confirmate
   punctele masurarii, tipul distantei, platitorul si daca suplimentul este unic.
10. Numerar colectat: valoarea de pe bonul fiscal. Predarea numerarului si
    cazurile preplatite/card nu sunt precizate. Nu adaugam automat transportul
    peste bon si nu echivalam valoarea bonului cu remuneratia livratorului.
11. Aprobare refacere/livrare suplimentara: restaurantul, numai pentru propriile
    comenzi. Intrebarea 11 NU privea corectarea generala a datelor comenzii.
12. Anulare inainte de ridicare: restaurantul propriu sau administratorul.
    Nu acordam livratorului drept de anulare si nu extindem regula post-pickup.
13. Pauza restaurant: restaurantul nu se poate pune singur in pauza, momentan.
    Nu presupunem din asta ca administratorul nu poate suspenda o locatie.
    Nu stergem feature-ul existent; politica si aplicarea ei necesita un lot distinct.
14. Inchidere zi: comenzile continua. Este clar ca nu trebuie anulate sau
    pierdute comenzile active. Raspunsul nu confirma explicit admiterea sau
    refuzul comenzilor noi dupa inchidere; cerem precizarea, nu o inventam.
15. GPS: pe intreaga perioada in care livratorul este disponibil pentru serviciu,
    cu sau fara comanda. Nu este autorizare de urmarire 24/7 ori in afara
    serviciului. Pauza, iesirea din tura si permisiunile se definesc la etapa GPS.

## Diferente confirmate fata de codul actual

- backend/utils/order_status.py, _delivery_totals: return amount * 0.1;
  backend/routers/orders.py, efectul legacy DELIVERED: total_amount * 0.1.
  Ambele sunt incompatibile cu remuneratia fixa comunicata. Nu le schimbam
  intr-o suma presupusa si nu recalculam retroactiv total_earnings.
- backend/routers/orders.py, creare legacy: total_amount=subtotal_amount+
  delivery_fee. Aceasta reprezentare nu distinge suficient suma datorata de
  client, transportul datorat de restaurant si plata livratorului. Sunt sume
  diferite; nu presupunem ca livratorul incaseaza de la client si delivery_fee.
- backend/routers/orders.py, /problem: delivery_fee=0 pe followup, total=subtotal.
  Nu reprezinta noua regula prin care restaurantul plateste transportul
  refacerii, iar livratorul este platit normal. S2-05B era deja neimplementat
  pentru comenzi versionate; refuzul de compatibilitate ramane intact.
- Packetul S2-05B existent prevedea conservator pastrarea formulelor legacy.
  Noua sursa de cerinte cere revizuirea acelei parti inainte de implementarea
  financiara. Nu tratam packetul vechi ca politica clientului aprobata.
- Pauza restaurant, continuarea dupa inchidere, cotarea in afara zonelor,
  suplimentul de adresa si GPS trebuie auditate/implementate in loturile lor;
  nu sunt declarate gata prin acest raport.

## Contract tehnic de pregatit, nu implementat aici

Separare explicita intre valoarea bonului/produselor, suma ramasa de colectat,
transportul facturabil restaurantului, remuneratia livratorului si suplimente.
Tarife configurabile, moneda si rotunjire explicite, calcul server-side,
snapshot al regulii aplicate pe fiecare livrare; fara recalcul istoric tacit.
Tarif incert/adresa ambigua necesita confirmare, nu cost zero implicit.

Refacere legata de original, originalul ramane livrat, remuneratie si transport
distincte pentru noua deplasare. Incidente post-pickup pastreaza custodia pana
la rezolutie explicita. Operatii recuperabile, CAS, audit si ledger, idempotenta
la retries/dublu-click si teste concurente raman cerinte ale S2-05B.

GPS live al livratorului NU este aceeasi distanta cu restaurant-client folosita
pentru tarif. Rutarea/masurarea si costul unui furnizor necesita decizie separata;
nu alegem sau activam un API platit in acest intake.

## Clarificari necesare, fara a repeta cele 15 intrebari

1. Valori exacte si moneda: transport pe fiecare zona, plata fixa a livratorului,
   inclusiv eventuale diferente pe restaurant/zona. Doua exemple complete:
   livrare obisnuita si refacere, bon, numerar, transport restaurant, plata driver.
2. In afara zonelor: tarif/km, toti kilometrii sau numai partea suplimentara,
   distanta rutiera sau alta masura, tarif minim/rotunjire si limita acceptata.
3. Schimbarea adresei: cei 2 km sunt vechea adresa -> noua adresa? Cine suporta
   suplimentul, ce inseamna exact transport de zona 1 ca plata driver si se
   acorda o singura data? Nu avem reguli pentru schimbare inainte de sosire.
4. Produs lipsa/neconform deja platit: clientul achita 0 la refacere sau pot
   exista diferente aprobate de restaurant? Cum se deosebeste de produse noi?
5. Dupa asteptarea de 10 minute: cine suporta returul, cum este platit driverul
   si cum se confirma predarea marfii sau alta rezolutie fara retur?
6. Numerar: cui si cand este predat, bon deja platit/card -> suma de colectat,
   eventuale plati partiale. Nu punem incasare automata pe comenzi preplatite.
7. Dupa inchiderea zilei: doar comenzile existente continua, iar cele noi sunt
   blocate, sau se permite si introducerea de comenzi noi? Cine poate redeschide?

## Continuare si siguranta

S2-05B nu mai asteapta toate raspunsurile de la zero; avem reguli importante,
dar nu o formula financiara completa. Codex poate pregati contractul si cazurile
de test in scope-ul intern deja aprobat; nu activeaza calcule sau date reale
pe ipoteze. Owner backend/frontend intern, reviewer independent si QA distinct
la implementare; backup/hashguard si mediu sintetic pentru verificari.

S2-07/08, etapa restaurant si gates live raman distincte. Fara modificari
backend/frontend/teste/runtime/DB/env/secrete/Hub, fara commit/push/deploy,
mesaje externe sau servicii platite. Nu s-au rulat teste, build ori browser QA
in acest intake documentar; rezultatele S2-06 sunt dovezi din taskul anterior.
