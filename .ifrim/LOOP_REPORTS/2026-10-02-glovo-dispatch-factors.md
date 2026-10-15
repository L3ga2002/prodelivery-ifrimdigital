# ProDelivery - factori de alocare: dovezi Glovo si propunerea noastra

Data cercetarii: 2026-10-02. Cerere Catalin: inspiratie din algoritmii Glovo pentru distanta, vreme, ora si activitatea livratorului. Cercetare publica; fara cod proprietar, API privat sau modificarea algoritmului aplicatiei. Rutare: Codex, surse primare; subagentii interni continua separat review/QA al probei.

## Ce este confirmat si ce nu

Blogul tehnic Glovo din 10 martie 2023 descrie alegerea curierilor si gruparea comenzilor folosind pregatirea, deplasarea, deadline-uri, vehicule si restrictii. Prezinta si grupuri cu numar nelimitat conceptual, nu o regula universala de maximum doua comenzi. Este explicatia arhitecturala de atunci, nu formula completa sau codul actual din 2026. [Inside Glovo's deliveries optimization](https://medium.com/glovo-engineering/inside-glovos-deliveries-optimization-7609f3f86586)

Pagina oficiala actuala pentru curieri din Maroc enumera disponibilitatea, pozitia geografica, distantele spre ridicare/livrare, asteptarea la partener si durata estimata. Nu generalizam configuratia acelei tari la Romania. [Criterii de distribuire - Glovo Maroc](https://riderhub.glovoapp.com/ma/wiki/%D9%85%D8%B9%D8%A7%D9%8A%D9%8A%D8%B1-%D8%AA%D9%88%D8%B2%D9%8A%D8%B9-%D8%A7%D9%84%D8%B7%D9%84%D8%A8%D8%A7%D8%AA-%D8%A3%D8%AB%D9%86%D8%A7%D8%A1-%D8%AA%D8%B9%D8%A7%D9%88%D9%86%D9%83/)

Articolul Glovo din 30 decembrie 2021 discuta vremea si traficul ca influente ale experimentelor si folosirea simularii pentru calibrare. Nu publica ponderi de tip rain_weight in alocare. [Simulatorul Glovo](https://medium.com/glovo-engineering/how-to-simulate-a-global-delivery-platform-7aa5fa475d88)

Pagina oficiala actuala Romania despre plati mentioneaza bonusuri legate de vreme, cerere si sarbatori. Portugalia mentioneaza si ore tarzii. Acestea sunt informatii despre remunerare, nu dovada ca aceiasi factori intra direct in scorul de alocare. [Castiguri si plati - Romania](https://riderhub.glovoapp.com/ro/wiki/earnings-payments/), [Earnings and payouts - Portugalia](https://riderhub.glovoapp.com/pt/en/wiki/earnings-and-payouts/).

Pagina curenta Romania descrie niveluri de Scor calculate pe indicatorii saptamanii precedente pentru acces mai devreme la rezervarea sesiunilor. Descrie si comenzi combinate, cu ordinea clientilor calculata automat. **Nu demonstreaza prioritate directa la fiecare alocare sau o penalizare dupa N comenzi azi**. [Utilizarea aplicatiei - Glovo Romania](https://riderhub.glovoapp.com/ro/wiki/using-the-app/).

Materialele vechi romanesti indexate despre Scorul de Excelenta, zone si plati redirectioneaza acum la noul wiki. Nu le tratam ca reguli active in 2026. Am urmat linkurile actuale, nu doar snippet-urile istorice din cautare. [Wiki curent Romania](https://riderhub.glovoapp.com/ro/wiki/).

Nu am confirmat public o formula actuala bazata pe numarul comenzilor terminate astazi, ploaie sau ora ca ponderi directe independente. Lipsa dovezii publice nu inseamna ca nu exista; nu inventam detalii si nu promitem algoritm identic Glovo.

## Propunere proprie pentru ProDelivery - nu politica Glovo

Separare obligatorie: eligibilitate, estimarea timpilor, fezabilitatea rutei, scorul dintre alternativele fezabile si commit concurent. Niciun scor bun nu poate ocoli capacitatea, ownership-ul, pickup inainte de dropoff sau un GPS invalid.

| Factor propriu propus | Cum il tratam | Date si fallback |
| --- | --- | --- |
| Pozitie GPS | Varsta/accuracy si disponibilitate sunt filtre; calculam de la urmatoarea pozitie relevanta a rutei | Timestamp server, accuracy, sample sequence; GPS vechi -> neeligibil pentru auto, incident vizibil |
| Distanta/timp pe drum | Folosim ETA si timpul incremental, nu doar km in linie dreapta | Matrice directionata si sursa aprobata; geometria numai prefiltru |
| Pregatire restaurant | Sincronizam sosirea cu ready estimat; evitam asteptarea inutila fara a intarzia excesiv mancarea | Timer/actual ready si istoric calibrat; actual ready ramane confirmare umana |
| Comenzi curente | Evaluam toate opririle, incarcare si termenele pe ruta existenta | Asignari authoritative active+rezervate; nu current_order_id singular |
| Comenzi multiple | Minimum 10 active pe acelasi driver daca ruta si vehiculul permit; quota distincta de load | Pickup/dropoff, capacitate fizica si service durations; niciun drop implicit al comenzilor |
| Ora/zi si cerere | Afecteaza estimarea traficului/pregatirii si numarul candidatilor; nu prioritate magica dupa ora | Initial configuratie transparenta, apoi date masurate; lipsa trafic live etichetata, nu pretentie de ETA live |
| Ploaie/vreme | Optional ajusteaza estimarile de deplasare si marjele de siguranta, diferentiat pe vehicul | Provider/cache/TTL si cost aprobate separat; lipsa meteo -> profil conservator explicit; nu penalizare personala |
| Vehicul/volum/zone | Restrictii dure pe acces/transport si capacitate | Configuratie per vehicul/restaurant; nu inventam ca zece pizza incap intr-un scuter |
| Vechimea/urgenta comenzii | Aging pentru a nu lasa mereu comenzile dificile in coada | Deadline si marja; infezabilitate/overdue sunt exceptii vizibile, nu mutarea deadline-ului pe ascuns |
| Activitate si echitate | Tie-break numai intre rute comparabile, configurabil de client | Minute ocupate/asteptare si timp disponibil in tura; numarul brut zilnic singur nu e suficient |
| Conectivitate/cont/pauza | Eligibilitate clara; delivery cu loc liber poate primi, break/offline/disabled nu | Guard comun pe server; oferta expirata, disconnect, revalidare la acceptare |
| Cash/limite operationale | Numai daca politica clientului si evidenta financiara sunt stabilite | Nu copiem reguli de remunerare straine in alocare; nu introducem limite de cash implicite |

Concept de obiectiv: intre alternativele fezabile minimizam timpul de drum suplimentar si asteptarea evitabila, protejam livrarile existente si folosim echitatea ca tie-break controlat. Ponderile si tolerantele se calibreaza pe scenarii, nu se aleg arbitrar si nu promitem optim global. Plafonul de 10 este capacitate configurabila demonstrata pe fixture, nu obligatia de a umple fiecare driver.

Exemplu propriu: A este la 2 minute, B la 6; bonul va fi gata peste 6 minute. B poate elimina asteptarea si pastra A pentru o comanda deja gata. Dar daca ruta lui B ar intarzia o comanda ridicata sau ar depasi capacitatea, B devine nefezabil indiferent de avantajul noii comenzi. Nu presupunem ca B castiga universal.

Pentru echitate, zece livrari scurte intr-o tura de opt ore nu sunt echivalente cu trei livrari lungi intr-o tura de doua ore. Clientul trebuie sa confirme politica; nu adaugam automat un ranking care pedepseste performanta sau ignora calitatea livrarii.

## Ce facem tehnic, in ordinea potrivita

1. Inchidem modelul 10-comenzi si contractele de concurenta in PD-DISPATCH-01; proba curenta este numai un driver cu timpi sintetici.
2. Completam setul de scenarii: rush hour, ploaie ca perturbare ETA, restaurante lente/rapide, GPS stale, 10 active, coada aging si distributie echitabila normalizata pe tura.
3. Comparam reguli nearest-only cu ruta fezabila/asteptare/timp incremental pe aceleasi fixture-uri. Raportam on-time, asteptare, km/minute, comenzi nealocate, CPU si starvation, nu doar numarul de comenzi.
4. Cu GPS si rutare aprobate, implementam estimarile reale si alegerea intre mai multi driveri. Vremea live si traficul extern nu sunt instalate sau cumparate prin aceasta cercetare.
5. Propunerile sunt revalidate la commit pe stare curenta; logul deciziei pastreaza motive tehnice fara adrese/telefon/CNP. Dispeceratul manual ramane disponibil pentru exceptii.

Nu clonam infrastructura de amploarea Glovo doar fiindca un articol foloseste anumite servicii. Biblioteca matematica si reguli transparente sunt suficiente ca punct de pornire; scaling/concurenta si calitatea ETA trebuie masurate in proiectul nostru. Cercetarea nu autorizeaza activarea Etapei 7 sau schimbarea contractului clientului.
