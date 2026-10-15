# ProDelivery - cercetare componente reutilizabile

Data: 2026-10-02
Tip: cercetare publica + inspectie statica locala, fara implementare.
Coordonator si autor: Codex. Routing: Codex only, conform cererii lui Catalin.
Nu s-au invocat OpenClaw, Claude Code sau alte modele externe.

## 1. Decizia propusa

Putem reutiliza motoare de optimizare, rutare, OCR si componente mobile. Nu recomand copierea unei aplicatii complete de delivery si nici rescrierea ProDelivery. Prima optiune de evaluat pentru optimizare este OR-Tools, cu VROOM ca alternativa serioasa. Alegerea finala necesita un benchmark comun cu restrictiile noastre.

Aceasta este o recomandare inginereasca rezultata din documentatie si compatibilitatea cu backendul Python existent, nu o demonstratie de performanta. Niciun motor nu a fost instalat sau rulat in acest task.

Scopul comercial ramane pachetul suplimentar de 10.000 EUR, cu 10 etape. Restaurantul ramane web/PWA, aplicatia mobila este pentru livrator. Nu sunt incluse POS-uri. Integrarea initiala pentru un restaurant ramane dependenta de identificarea furnizorului, documentatie si acces. Nu exista documentatie suficienta pentru implementarea acelui conector acum.

Cerintele de proiect: minimum 10 comenzi active per livrator, cu limite configurabile si restrictii operationale; profil initial 50 restaurante/100 livratori. Acestea sunt tinte de verificat, nu rezultate demonstrate prin aceasta cercetare. Cercetarea nu activeaza Etapa 4-10 si nu modifica termenul contractual de trei luni.

## 2. Ce am gasit la platformele mari

### Glovo

Articolul propriei echipe, publicat in 2023, descrie gruparea mai multor comenzi, inclusiv din locuri diferite, estimari de pregatire/deplasare, restrictii de vehicul si selectarea grupurilor fara conflicte. Separarea propunerii de validarea si aplicarea deciziei este relevanta pentru noi. Este o descriere istorica, nu codul complet si nici dovada regulilor exacte folosite azi. [Sursa Glovo](https://medium.com/glovo-engineering/inside-glovos-deliveries-optimization-7609f3f86586)

Un preprint din 2024 trateaza reglarea parametrilor motorului prin simulare si evaluare. Concluzia mea pentru ProDelivery: ponderile trebuie calibrate pe operatiunile clientului, nu prezentate drept o formula universala. [Preprint al autorilor](https://easychair.org/publications/preprint/w5L8)

### DoorDash

Articolul tehnic din 2021 separa estimarile, generarea variantelor de alocare si optimizarea. Prezinta si simularea pentru evaluare. Referinta lor la Gurobi nu obliga ProDelivery sa cumpere acel solver. Preluam principii, nu sistemul complet si nu promitem aceeasi performanta. [Sursa DoorDash](https://careersatdoordash.com/blog/using-ml-and-optimization-to-solve-doordashs-dispatch-problem/)

### Foodpanda si cod proprietar

Nu am identificat in sursele cercetate un repository public verificabil care sa ofere motorul complet de alocare Glovo sau Foodpanda, cu drepturi clare de reutilizare. Aceasta este limita cautarii, nu afirmatia ca un astfel de repository nu poate exista.

Nu vom folosi cod privat obtinut fara drepturi, surse scurse sau un repository care doar pretinde ca este algoritmul unei platforme. Codul vizibil pe GitHub nu este automat reutilizabil comercial. [Documentatia GitHub despre licente](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)

## 3. Motoare si proiecte candidate

Licentele de mai jos sunt cele afisate de proiectele principale la cercetare. Auditul dependintelor, versiunii instalate, modelelor si datelor ramane obligatoriu inainte de integrare.

| Componenta / sursa | Ce putem prelua | Licenta / limita | Verdict pentru ProDelivery |
| --- | --- | --- | --- |
| [Google OR-Tools](https://github.com/google/or-tools) | Motor de optimizare cu interfata Python | Apache-2.0 | Primul candidat: se potriveste backendului existent; nu inlocuieste logica de persistenta si statusuri. |
| [VROOM](https://github.com/VROOM-Project/vroom) | Optimizare VRP, expedieri pickup/delivery, capacitati si ferestre de timp | BSD-2-Clause | Alternativa de comparat; integrare prin serviciu/CLI C++, cu cost operational separat. |
| [jsprit](https://github.com/graphhopper/jsprit) | Biblioteca Java pentru probleme de rutare cu restrictii | Apache-2.0 | Utila, dar adauga alt runtime. Nu este prima alegere pentru actualul backend Python. |
| [Rust VRP](https://github.com/reinterpretcat/vrp) | Motor pentru probleme complexe de rutare | Apache-2.0 | Alternativa de studiu; integrarea si modelarea cerintelor noastre nu sunt verificate. |
| [FoodMatch](https://github.com/idea-iitd/FoodMatch) | Implementare academica dedicata grupurilor si alocarii pentru food delivery | Nu am verificat o licenta explicita in pagina/rootul consultat | Studiu si inspiratie. Nu copiem cod comercial pana la clarificarea permisiunilor si dependintelor. |
| [Grubhub MDRP](https://github.com/grubhub/mdrplib) | 240 instante anonimizate si instrumente de evaluare | Termenii pentru cod/date necesita verificare separata | Referinta pentru scenarii; nu reprezinta un dispecerat gata de productie. |
| [MDRP simulator](https://github.com/sebastian-quintero/mdrp-sim) | Simulator de evenimente pentru livrari | Licenta nu a fost confirmata in pagina consultata | Studiu; nu distribuim sau integram pana la verificarea drepturilor. |
| [Alibaba EasyDispatch](https://github.com/alibaba/easydispatch) | Idei de reguli si planificare pentru field service | Apache-2.0; stack cu Postgres, Redis, Kafka | Nu recomand adoptarea platformei: ar introduce o schimbare mare de arhitectura si nu este specifica produsului nostru. |
| [OSRM](https://github.com/Project-OSRM/osrm-backend) | Rute pe drum, matrice timp/distanta, map matching | BSD-2-Clause; datele au termeni separati | Candidat pentru informatia geografica. Nu aloca singur comenzile. |
| [Valhalla](https://github.com/valhalla/valhalla) | Rutare, matrice timp/distanta, map matching | MIT; date OSM sub ODbL; suport Windows incomplet documentat | Alternativa pentru serviciul de rutare, de evaluat pe infrastructura tinta. |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Extragerea textului si structurii documentelor | Apache-2.0 pentru cod; verificare distincta pentru modele | Candidat OCR local; necesita masurare pe bonurile reale si cost CPU/GPU. |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Motor OCR | Apache-2.0 | Baseline OCR de comparat. Nu presupunem acuratete suficienta pe poze termice neclare. |

[Lucrarea FoodMatch](https://arxiv.org/abs/2008.12905) descrie gruparea si matching-ul in retele dinamice. Este mai apropiata de domeniul nostru decat un exemplu simplu de ordonare a adreselor, dar cercetarea academica nu demonstreaza integrarea sau fiabilitatea in ProDelivery.

### OR-Tools: restrictii pe care le putem modela

Documentatia include perechi ridicare/livrare, acelasi vehicul pentru pereche si precedenta ridicarii. [Pickup and delivery](https://developers.google.com/optimization/routing/pickup_delivery)

Ferestrele de timp pot exprima disponibilitatea si termenele; dimensionarea concreta a timpului de pregatire si stationare ramane modelarea noastra. [Time windows](https://developers.google.com/optimization/routing/vrptw)

Capacitatea vehiculului poate fi modelata distinct de numarul de comenzi active. [Capacity constraints](https://developers.google.com/optimization/routing/cvrp)

Trebuie stabilita o limita de calcul si tratate rezultatele fara solutie/timeout. [Routing options](https://developers.google.com/optimization/routing/routing_options)

La verificarea catalogului PyPI, OR-Tools 9.15.6755 avea un wheel Windows x64 pentru CPython 3.14. Compatibilitatea intregului mediu ProDelivery nu a fost testata. [Pachete publicate](https://pypi.org/project/ortools/)

### VROOM: diferenta dintre comanda, oprire si capacitate

API-ul separa `shipments`, `jobs`, capacitati, ferestre, `skills`, prioritati si limite de sarcini. O pereche pickup/delivery nu trebuie confundata cu o singura oprire. `max_tasks` si capacitatea fizica nu asigura automat limita noastra de comenzi active, care trebuie verificata separat. [API VROOM](https://github.com/VROOM-Project/vroom/blob/master/docs/API.md)

## 4. Mobil si GPS in fundal

| Optiune / sursa | Ce este confirmat | Ce ramane de demonstrat |
| --- | --- | --- |
| [Expo Location](https://docs.expo.dev/versions/latest/sdk/location/) | Exista suport documentat pentru background location cu configurare si permisiuni native; iOS cere development build pentru verificarea respectiva | Telefoane fizice, ecran blocat, consum baterie, offline, oprirea aplicatiei. Nu presupunem GPS continuu dupa terminarea aplicatiei. |
| [Capacitor Geolocation](https://capacitorjs.com/docs/apis/geolocation) | Pluginul standard nu suporta direct geolocatie in fundal | Este necesara o integrare separata; un wrapper web simplu nu demonstreaza cerinta GPS. |
| [Capacitor community background geolocation](https://github.com/capacitor-community/background-geolocation) | Plugin public sub MIT pentru Android/iOS | Validare pe versiunile OS si dispozitivele tinta, permisiuni si cerinte de publicare. |
| [Transistorsoft React Native background geolocation](https://github.com/transistorsoft/react-native-background-geolocation) | Wrapperul este MIT, dar SDK-ul inclus cere licenta comerciala pentru release pe Android si iOS in documentatia v5 | Oferta si termenii trebuie verificati inainte de alegere. Nu a fost cumparata nicio licenta. |

Propunere: experiment tehnic mic pe telefon fizic pentru Expo/React Native versus Capacitor, inainte sa alegem solutia aplicatiei de livrator. Nu alegem exclusiv dupa cat cod React putem copia: componentele DOM existente nu se transforma automat in componente React Native.

## 5. Algoritmul propus pentru ProDelivery

Aceasta sectiune este proiectare proprie, nu descrierea algoritmului secret al unei platforme. Implementarea necesita aprobare si verificare in etapele corespunzatoare.

1. Preluam un snapshot versionat al comenzilor active, rutelor si livratorilor. Verificam coordonate, roluri, disponibilitate, ultima pozitie GPS si acuratetea acesteia.
2. Excludem variantele imposibile: livrator in pauza/offline, GPS prea vechi, vehicul incompatibil, lipsa capacitatii sau interval imposibil.
3. Restrangem candidatii geografic si calculam matrice de timp rutier cu cache, deadline si limite de volum. Distanta in linie dreapta poate filtra candidati, dar nu trebuie confundata cu ETA rutier.
4. Modelam fiecare comanda ca ridicare apoi livrare, cu timp de pregatire, stationare si termene. Protectia alimentelor si limitele de abatere necesita praguri convenite cu clientul.
5. Pastram opririle deja executate si proprietarul comenzilor ridicate. O comanda aflata fizic la un livrator nu se muta automat la altul.
6. Suportam cel putin 10 comenzi active la acelasi livrator atunci cand exista o ruta fezabila. Cota de comenzi active, inclusiv rezervari/oferte, este separata de capacitatea bagajului si de numarul de opriri.
7. Comparam variante dupa timpul suplimentar, intarzieri, asteptare la restaurant, kilometri inutili si incarcarea livratorilor. Ponderile vor fi reglate pe operatiuni si simulari, nu inventate ca formula Glovo.
8. Rulam optimizarea cu buget limitat de timp/CPU, fara blocarea request-urilor FastAPI. Cand nu exista solutie fezabila sau serviciul nu raspunde, comanda ramane vizibila pentru interventie manuala; nu fortam o alocare incorecta.
9. Revalidam starea si aplicam decizia atomic, cu versiuni, idempotenta si controlul rezervarilor. Solverul propune; nu scrie direct statusuri in baza de date. O stare modificata intre calcul si aplicare invalideaza propunerea.
10. Publicam actualizarile si notificarile numai dupa confirmarea deciziei. Salvam motivul, versiunea, durata calculului si rezultatul pentru debugging si audit, fara date personale inutile in loguri.

Nu propun un LLM pentru fiecare alocare. Pentru acest nucleu folosim optimizare matematica si reguli operationale; estimarile avansate pot fi imbunatatite ulterior cu date, daca exista nevoie demonstrata. Nu promitem optimul matematic global sau 10 comenzi indiferent de distante si termene.

## 6. Ce nu rezolva o biblioteca pentru codul actual

Inspectie statica revalidata in acest task:

| Evidenta locala | Implicatie pentru implementare |
| --- | --- |
| [driver.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/models/driver.py:33>) - `current_order_id` singular | Modelul actual nu reprezinta o ruta cu multiple comenzi. Adaptarea trebuie incrementala, cu compatibilitate. |
| [orders.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/orders.py:450>) - conflict pentru o alta comanda activa; claim atomic la linia 462 | Suportul multi-comanda trebuie sa pastreze protectia concurenta, nu sa elimine pur si simplu conflictul. |
| [orders.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/orders.py:291>) - curatarea comenzii la anulare; si la livrare, linia 308 | Finalizarea unei comenzi trebuie sa elibereze numai acea comanda/rezervare, nu toata activitatea livratorului. |
| [DriverApp.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/DriverApp.jsx:177>) - selectia unei singure comenzi curente | Sunt necesare lista si ordinea opririlor, actiuni individuale si recuperare dupa refresh/offline. |
| [AdminDashboard.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:734>) si [LiveMapPanel.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/admin/LiveMapPanel.jsx:147>) | Disponibilitatea si afisarea rutelor folosesc modelul singular; un solver nu actualizeaza singur aceste ecrane. |
| [orders.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/orders.py:321>) - limite de feed 1000/100/100 | Optimizatorul necesita un snapshot complet al comenzilor active, paginat/limitat explicit. Nu poate presupune ca feedul dashboardului include toate comenzile. |

Nu am modificat aceste fisiere. Cercetarea nu certifica securitatea, concurenta sau capacitatea actualei aplicatii.

## 7. Harta si geocodare: atentie la servicii publice

Componenta [LocationAutocomplete.jsx](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/LocationAutocomplete.jsx>) trimite cautari pe masura tastarii, cu debounce. Backendul [geocoding.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/geocoding.py>) foloseste un URL din mediu si un limiter/cache local procesului.

Nu am citit `.env`, deci nu afirm ca acel URL este serverul public OSM. Daca este `nominatim.openstreetmap.org`, autocomplete-ul nu este permis de politica acestuia, iar limita de 1 request/sec este agregata la nivelul aplicatiei, nu per worker. Proxy-ul/debounce-ul nu transforma autocomplete-ul intr-o utilizare permisa. [Politica Nominatim](https://operations.osmfoundation.org/policies/nominatim/)

Codul hartii referentiaza tile-urile publice OSM. Serviciul public are resurse limitate si nu ofera SLA. Pentru exploatare comerciala trebuie stabilit un furnizor compatibil sau hosting propriu, cu cache si atribuire corecte. Nu inseamna ca orice folosire actuala este interzisa. [Politica tile OSM](https://operations.osmfoundation.org/policies/tiles/)

Un router open-source nu aduce automat trafic live. ETA trebuie evaluat pentru profilul de vehicul si zona, iar sursele de trafic au cerinte distincte.

## 8. OCR: motorul este doar o parte

Propun compararea PaddleOCR/Tesseract cu un serviciu comercial pe 30-50 de bonuri oferite legal de client si anonimizate unde este necesar. Aceasta este o verificare viitoare, nu efectuata acum.

Testam fotografii inclinate, blur, bonuri lungi, caractere similare si date absente. Masuram separat adresa, telefonul, suma si identificatorul comenzii. Textul recunoscut trebuie validat, prezentat pentru corectie/confirmare si protejat la duplicate. Nicio solutie nu garanteaza ca orice bon va fi recunoscut corect.

Codul/modelul self-hosted reduce dependenta de taxa per scanare, dar are cost de hosting, resurse, mentenanta si testare. Serviciul comercial poate fi mai convenabil, in functie de volume si rezultate. Alegerea nu se face doar dupa numele bibliotecii.

## 9. Verificare propusa inainte de adoptare

1. Facem review de licenta pentru versiunea exacta, dependinte, modele si date; pastram atribuirile si notificarile cerute. Licentele MIT/BSD/Apache nu inseamna lipsa obligatiilor. [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0)
2. Comparam OR-Tools si VROOM pe aceleasi cazuri sintetice: 1/2/5/10 comenzi per livrator; a 11-a comanda la cota plina; restaurante diferite; pregatire intarziata; lipsa pozitiei; ruta fezabila si ruta imposibila.
3. Verificam anulare, refuz, realocare, comanda ridicata, doua actiuni admin simultane, doua executii ale optimizatorului si schimbarea starii intre calcul si salvare.
4. Injectam timeout pentru solver/router, date geografice incomplete, restart si lipsa internetului. Verificam fallback-ul si sa nu existe alocari duplicate sau bucle infinite.
5. Masuram p50/p95/p99, proportia timeout, comenzi nealocate, intarzieri, timp cu mancarea in transport, latenta API si numarul apelurilor de matrice.
6. Testam profilul 50 restaurante/100 livratori si varful propus de 1000 comenzi alocate + 200 in asteptare. Profilul nu este o garantie pana nu exista dovezi pe infrastructura tinta.
7. Verificam fizic Android/iOS: permisiuni, background, ecran blocat, economisire baterie, mod avion si revenire. Emulatorul si build-ul nu sunt suficiente.
8. Introducem optimizatorul mai intai in mod de propuneri/simulare, apoi intr-un pilot autorizat. Activarea alocarii reale necesita aprobarea lui Catalin.

## 10. Cost, timp si ce NU s-a facut

Concluzie: reutilizarea acestor componente evita reconstruirea matematicii, a OCR-ului si a anumitor integrari native de la zero. Nu elimina modelarea comenzilor multiple, securitatea, idempotenta, persistenta, UI-ul operational si testarea reala.

Nu garanteaza singura livrarea intregului plan intr-o luna sau incadrarea exacta in 1000-1500 EUR pentru AI. Alocarea matematica nu necesita tokeni AI la fiecare comanda, dar hostingul, hartile/geocodarea, OCR-ul si eventualele SDK-uri pot avea costuri distincte. Nu a fost aprobat sau cumparat nimic.

Verificari efectuate acum: consultarea surselor primare, inspectie statica a fisierelor mentionate, Git status; frontend `http://127.0.0.1:3000/login` HTTP 200 si backend `http://127.0.0.1:8000/api/` HTTP 200. Aceste verificari HTTP nu certifica fluxuri functionale.

Nu s-au efectuat in acest task: clone/install, benchmark, teste automate de aplicatie, click-through QA, schimbari de cod/UI/env/baza de date, commit, push sau deploy. Nu s-au citit secrete, `.env`, `.ifrim/private`, `.ifrim/tmp` sau uploads.

Urmatorul pas tehnic recomandat: inchiderea criteriilor de alocare si a modelului multi-comanda, urmata de un benchmark izolat OR-Tools/VROOM cand este aprobat. Nu incepem prin activarea unui algoritm pe comenzile reale.
