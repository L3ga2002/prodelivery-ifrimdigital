# ProDelivery - Clarificari client, 2026-10-09

## Statut

Intake documentar al celui de-al doilea set de raspunsuri, nu implementare,
activare, migrare sau certificare financiara. Etapa 2 ramane in_progress.
Pachetul comercial ramane 10.000 EUR / 10 etape. S2-01..06 nu se reconstruiesc.

Owner: Codex. Routing: Codex only conform instructiunii proiectului; fara
OpenClaw, Claude sau Agent Hub mutations. Review: corelare manuala cu captura
si cele 11 intrebari din mesajul anterior, nu review independent. QA: integritate
documente/istoric si hashguard, fara teste functionale sau browser in acest intake.
Clasificare: etapa_1_3_core / engineering_support pentru specificatie. Nu exista
aprobare implicita pentru date reale, calculuri activate sau noi servicii platite.

Sursa: captura furnizata de Catalin in acest chat la 2026-10-09:
codex-clipboard-12c8a831-7bfe-43bc-8b8e-dbea1b6e4e42.png.
SHA256: DA7332634B8CDD1548F17CA72D99BB120128B90FB87BAC55D7D8F47948847323.
Ora vizibila 23:16 nu stabileste data mesajului clientului. Imaginea nu este
copiata in repo si nu este trimisa unui serviciu extern. Nu exista audio nou.

Referinta anterioara, pastrata integral:
LOOP_REPORTS/2026-10-08-client-operational-rules-intake.md.
Numerotarea de mai jos corespunde celui de-al doilea chestionar, NU primului.

## Raspunsuri 1-11 corelate

1. Transport pe zone, in RON: zona 1 = 16, zona 2 = 26, zona 3 = 36 in exemplul
   comunicat. Clientul precizeaza explicit ca tarifele difera de la restaurant
   la restaurant. Nu avem restaurantul caruia i se aplica exemplul si nu il
   transformam intr-o grila universala. In afara zonelor: 3 RON/km restaurant-client.
2. Remuneratia livratorului difera atat intre restaurante, cat si intre zone.
   Sumele efective NU sunt comunicate. 16/26/36 sunt tarife de transport ale
   restaurantului, nu plata livratorului si nici profitul firmei.
3. Pentru cotarea in afara zonelor se foloseste TOATA distanta restaurant-client
   inmultita cu 3 RON/km, nu numai kilometrii dupa limita zonei si nu tarif de
   zona plus kilometri, in lipsa unei alte confirmari.
4. Distanta este rutiera, cu pret minim 40 RON pentru acea cotare in afara zonelor.
   Interpretare combinata a raspunsurilor 1/3/4: transport_outside_zone =
   max(40 RON, 3 RON/km * route_km). Minimul de40 NU se aplica tarifelor zonale
   16/26/36. Rotunjirea kilometrilor/banilor si distanta maxima nu sunt precizate.
5. Schimbare adresa INAINTE de sosire: fara un supliment distinct, tarif conform
   zonei de livrare, suportat de restaurant. Nu inseamna transport gratuit sau
   pastrarea automata a tarifului vechii zone. Nu adunam doua transporturi.
   Acest raspuns NU revoca regula anterioara pentru schimbare DUPA sosire,
   peste2km -> supliment zona1 pentru driver. Detaliile acelui supliment raman
   partial deschise: distanta exacta, platitor si numarul de suplimente.
6. Produse lipsa/neconforme si eventuala plata a refacerii: clientul spune ca
   firma de livrari nu gestioneaza decizia respectiva. Responsabilitatea
   comerciala ramane la restaurant; nu impunem gratuitate, refund sau pret nou.
   Operational trebuie cunoscuta suma indicata de restaurant pentru colectare,
   inclusiv0 explicit, fara a confunda lipsa sumei cu gratuitatea.
7. Restaurantul suporta returul si confirma primirea produselor inapoi.
   Raspunsul mentioneaza pretul unei curse de zona1 pentru retur; contextul
   intrebarii este remuneratia livratorului, dar pronumele "acesta" este ambiguu.
   Retinem referinta la zona1 si cerem matricea de remuneratii, nu atribuim16RON
   automat livratorului. Daca se decide sa nu existe retur, comanda/produsele
   raman la livrator si nu se plateste transport de retur care nu a avut loc.
   Plata cursei initiale nereusite si restituirea banilor avansati lipsesc.
8. Flux CASH: livratorul achita produsele restaurantului la ridicare si incaseaza
   cash de la client. Plata la ridicare este conditionata de suficienti bani
   disponibili la livrator. Procedura in caz de numerar insuficient nu este data.
   Nu presupunem fond de rulment, credit, plata ulterioara sau blocare automata.
9. Comanda deja platita online/card: livratorul nu mai incaseaza nimic de la client.
   Nu adaugam transportul la suma clientului preplatit. Raspunsul8 este despre
   cash; nu il extindem la o a doua plata catre restaurant pentru produse preplatite.
10. Restaurantul achita transporturile separat. Nu compensam automat transportul
    din banii produselor si nu includem decontarea in remuneratia livratorului.
    Frecventa/scadenta/modalitatea decontarii separate nu au fost comunicate.
11. Comenzile NOI sunt permise in continuare dupa inchiderea zilei. Acest raspuns
    inchide neclaritatea de admitere din raportul precedent. Inchiderea zilei
    nu trebuie confundata cu indisponibilitatea restaurantului sau cu anularea
    comenzilor active. Delimitarea zilei de raportare/decont ramane de definit.

## Exemple de calcul, deduse aritmetic, NU facturi reale

Numai transportul in afara zonelor, pentru grila3RON/km si minimum40RON:

| Distanta rutiera | Calcul | Transport restaurant |
| --- | --- | --- |
| 10 km | max(40, 30) | 40 RON |
| 15 km | max(40, 45) | 45 RON |
| 20 km | max(40, 60) | 60 RON |

Aceste valori NU sunt remuneratia driverului. Nu avem reguli de kilometri
rotunjiti, alegerea traseului, furnizor rutare sau geometriile zonelor din poza.
Pretul clientului/bonului si plata soferului nu se deduc din aceasta formula.

## Cerinte operationale clarificate

- Configuratie per restaurant pentru grila de transport si, SEPARAT, matrice
  de remuneratie per restaurant/zona/tip de cursa. Nu hardcodam exemplul global.
- Suma de pe bon, transportul restaurantului, remuneratia driverului, avansul
  cash la restaurant si incasarea de la destinatar sunt pozitii distincte.
- Produse preplatite ->0de colectat de la client. CASH ridicat/refuzat/returnat
  necesita evidenta banilor avansati si o rezolutie explicita, nu pierdere tacita.
- Cursa de retur si confirmarea primirii sunt evenimente distincte. Dublu-click,
  retry, ACK pierdut sau doua persoane nu pot dubla plata/cursa/confirmarea.
- Decizia "fara retur" nu este dovada de predare la restaurant sau livrare la
  client. Custodia reala ramane vizibila pana la rezolutie, fara payout de retur.
- Deciziile comerciale pentru produse apartin restaurantului. Aplicatia de
  delivery transporta suma explicit comunicata, nu decide compensatii/refunduri.
- Inchidere zi si acceptare de comenzi noi sunt concepte distincte. Nu stergem
  programe, stari, API-uri sau istoric pentru a satisface noua regula.

## Ce ramane deschis, fara repetarea celor doua chestionare

Prioritar pentru activarea calculelor:

1. Tabelul initial per restaurant: transport zona1/2/3..., remuneratie driver
   zona1/2/3..., plata in afara zonelor si plata returului. Restaurantul exemplului
   16/26/36 trebuie nominalizat. Valorile pot fi completate operational mai
   tarziu; nu activam o grila incompleta si nu folosim0/10% drept fallback.
2. Cash insuficient la pickup: asteapta bani, fond de rulment, restaurantul
   accepta plata ulterioara sau alta procedura? Cine aproba si ce se inregistreaza?
3. Refuz/retur/no-return dupa avans cash: restaurantul restituie banii produselor
   driverului? Cine suporta diferenta daca nu se returneaza? Plata cursei initiale
   nereusite se acorda sau nu? Nu stergem datoria si nu inventam compensatii.

Detalii de inchis inainte de activarea fluxurilor respective:

- Schimbare adresa post-sosire: regula>2km, platitor, distanta masurata si
  supliment unic versus repetat; raspunsul actual vorbeste doar pre-sosire.
- Distanta rutiera: zone/geometrii, rotunjire/minori monetari, limita acceptata,
  tratare adresa/ruta incerta si alegerea furnizorului, fara activare API platit.
- Decontare transport restaurant: perioada/scadenta si confirmarea platii.
- Inchidere zi: ce interval inchide, ziua atribuita comenzilor ulterioare si
  cine initiaza/confirma decontul. Nu mai intrebam daca sunt permise comenzi noi:
  acest lucru este deja confirmat.

## Continuitate

Acest raport supersedeaza numai punctele clarificate din intake2026-10-08:
formula/minim/metoda distantei, variatia remuneratiei, pre-sosire, retur,
circuit cash/prepaid, transport separat si admiterea dupa inchidere.
Pastreaza regulile anterioare necontrazise: asteptare10min cu decizie admin+
restaurant, drepturi proprii, interdictia pauzei self-service momentan si GPS
pe perioada disponibilitatii pentru serviciu. Nu este autorizare GPS24/7.

S2-05B se pregateste cu contracte si teste pe date sintetice in scope-ul aprobat,
dar nu implementam politici financiare pe presupuneri si nu activam date reale.
Formula legacy10% ramane de inlocuit intr-un lot verificat, nu prin documente.
S2-07/08, etapa restaurant si gates live raman deschise si distincte.

Doar raport nou si checkpoint aditiv NEXT_SESSION, cu backup si hashguard.
Fara modificari cod/teste/DB/env/secrete/markeri/runtime/Hub/Git/deploy.
Nu s-au rulat teste aplicatie, build, preview sau browser QA in acest intake.
