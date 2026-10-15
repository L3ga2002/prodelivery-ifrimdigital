# ProDelivery — răspunsuri client, grila de 18 întrebări

Data intake: 14 octombrie 2026, conform datei clientului aplicației. Aceasta nu stabilește data mesajului original al firmei. Sursa este grila exactă atașată în conversație și răspunsurile 1–18 ale utilizatorului; clarificarea ulterioară a întrebării 7 este inclusă separat. Acest document actualizează cerințele și ordinea lucrărilor; nu implementează sau activează funcții.

## Situația verificată înaintea acestui intake

Checkpointul `2026-10-13-campaign-final.md` este citit din proiectul activ. L1 documentar, corecția software L2, nucleul financiar L3 și refacerea atomică L5A sunt integrate local. Etapele comerciale 1 și 2 sunt deschise. Noul protocol financiar/refacere nu este activat comercial; formularele și unele fluxuri legacy mai trebuie migrate. Regresia extinsă păstrează eșecuri/blocaj istorice, iar proba bateriei rămâne INCOMPLETE. Acest intake nu transformă rezultate istorice în verificări executate astăzi.

Sursele financiare citite confirmă snapshotul imuabil și câmpurile `advance_paid_bani`, `refund_due_bani`, `refund_paid_bani` exclusiv null (`backend/models/order_finance.py:102–107`). Evidența operațiilor/plăților va fi registru separat. Modelul livratorului încă are `current_order_id` singular (`backend/models/driver.py:33`), iar disponibilitatea refuză pauza/offline cu sarcină activă (`backend/routers/drivers.py:718–719`). A+B+C, volumul și gruparea nu sunt deja implementate prin aceste răspunsuri.

## Matricea răspunsurilor

Numerotarea de mai jos aparține EXCLUSIV noii grile de 18. Nu se confundă cu seturile anterioare de 11/15 întrebări. Retragerea 11/12 din grila curentă și retragerea 7/8 din setul anterior sunt decizii distincte.

| Nr. | Răspuns primit | Comportament confirmat / dependență |
| --- | --- | --- |
| 1 | A | Referința „zona 1” pentru retur înseamnă plata livratorului pentru zona 1, specifică restaurantului. Din regulile anterioare, restaurantul suportă returul și confirmă primirea. Valoarea suplimentară facturată restaurantului nu rezultă din această referință și trebuie indicată separat. |
| 2 | A | Cursa inițială nereușită: plata normală a livratorului și transport normal datorat de restaurant. Răspunsul este păstrat exact, însă politica finală a acestui calcul este în așteptare din cauza 3D. |
| 3 | D | Clientul va comunica două grile după soarta produselor: returnate sau păstrate. Lipsesc grilele și relația lor cu 2A. Nu adoptăm unilateral prioritatea unei variante și nu activăm un calcul pentru acest caz. |
| 4 | A | Anulare înainte de ridicare, strict peste 50% din traseul punct de plecare–restaurant: jumătate din remunerația livratorului pentru zona 1, suportată de restaurant. Aceasta nu este jumătate din tariful restaurantului și nu stabilește marjă comercială suplimentară. |
| 5 | A | Anulare înainte de ridicare, cel mult 50% din acel drum: zero compensație. Exact 50% intră aici. Distanța eligibilă, originea și dovezile trebuie păstrate; datele absente/incerte nu devin distanță zero sau eligibilitate. |
| 6 | A | Livratorul poate ridica fără plata produselor numai după aprobarea restaurantului în aplicație. Declarația singură nu autorizează excepția. Aprobarea autorizează ridicarea fără plată, dar nu consemnează fictiv o plată. |
| 7 | B sau C; clarificat ulterior | Utilizatorul a ales explicit: „La următoarea ridicare de la același restaurant; dacă nu există, la finalul programului.” Termenul comercial este confirmat. Programul relevant și dovada primirii banilor se explicitează în contractul operației; nu se reinventează o decontare generală sau un cutoff contabil. |
| 8 | A | Pentru maximum două schimbări după sosire: supliment pentru fiecare schimbare eligibilă strict peste 2 km. Nu se cumulează distanțele a două schimbări mici pentru a inventa eligibilitate. |
| 9 | A | La schimbarea a doua, distanța rutieră se măsoară de la adresa primei schimbări la noua adresă. Prima schimbare se măsoară de la adresa inițială. Istoricul ambelor adrese și dovezi rămâne distinct. |
| 10 | A | Schimbare de adresă de cel mult 2 km: zero supliment pentru livrator, inclusiv exact 2 km. Din regulile anterioare, suplimentul eligibil pentru livrator este remunerația zonei 1 și restaurantul suportă transportul. Tariful suplimentar facturat restaurantului este distinct de plata livratorului. |
| 11 | Întrebare anulată | Nu se mai solicită alegerea din această grilă. Nu înseamnă eliminarea corectărilor sau adoptarea unor permisiuni noi. Protocolul actual de corectare admin se păstrează; alte drepturi nu sunt confirmate prin retragere. |
| 12 | Întrebare anulată | Nu se mai solicită alegerea din această grilă. Nu înseamnă corectări nelimitate după ridicare. Validările și condițiile implementate se păstrează; nu se relaxează prin această retragere. |
| 13 | B | Exemplul de pauză: A în curs, B alocată/gata și C gata/nealocată trebuie terminate; după includerea lui C nu mai primește alte comenzi. Alegerea clientului include C, dar nu stabilește includerea tuturor comenzilor gata din toate restaurantele sau selecția lui C și cazul în care nu încape. |
| 14 | A | B deja alocată rămâne de terminat inclusiv dacă se pregătește la cererea de pauză. Nu se redistribuie automat pentru simplul motiv al cererii de pauză. Politicile de incident/realocare rămân distincte. |
| 15 | B | Capacitatea de transport se bazează pe volumul încărcăturii, nu numai pe numărul comenzilor. Lipsesc capacitățile reale și metoda de declarare/estimare a volumului. 1→2→5→10 sunt trepte de verificare tehnică, nu o limită comercială de zece impusă clientului. |
| 16 | C | Limite diferite după tipul produselor. Se așteaptă tabelul: tip de produs, așteptare maximă, întârziere suplimentară prin grupare, interval ridicare–livrare. Nu deducem minute din alegerea C. |
| 17 | D | „Altă procedură”, fără textul procedurii, este incomplet. Lipsește cine semnalează/contactează/decide și condiția/timpul realocării înainte de ridicare. Nu inventăm timeout sau realocare automată. |
| 18 | C | Zonele stabilite; fiecare livrare în afara lor cere aprobarea administratorului. Cotarea exteriorului și aprobarea geografică sunt reguli separate. Alegerea nu stabilește un număr maxim de km sau momentul exact al aprobării în flux. Propunerea tehnică este ca executarea unei livrări exterioare neaprobate să fie blocată, cu intenție/decizie auditată; momentul se definește explicit în contract. |

Întrebarea 7 a fost completată după reviewul inițial. Cele două răspunsuri încă incomplete sunt 3D și 17D. Alegerea 16C este clară, dar tabelul lipsește. Alegerea 13B este clară pentru exemplu, dar regula generală de selectare a lotului și capacitatea necesită completare. Se păstrează explicit aceste diferențe; nu toate alegerile reprezintă politici complet parametrizate.

## Clarificări care chiar influențează dezvoltarea

1. **Grila finală pentru primele 2–3 restaurante:** transport și remunerație separat, pe zone/exterior; cursa inițială nereușită cu produse returnate și cu produse păstrate; remunerația returului și transportul suplimentar facturat restaurantului; suplimentul restaurantului pentru schimbarea eligibilă a adresei. Precizare asociată: 2A este regula ambelor cazuri sau grilele din 3D o înlocuiesc?
2. **Procedura 17D:** cine sesizează absența, cine încearcă contactarea, după ce interval/condiție și cine realocă înainte de ridicare. Aceasta nu creează un drept comercial de refuz al sarcinii.
3. **C după cererea de pauză:** exact o comandă deja gata, aleasă de administrator sau de alocarea automată, ori alt lot finit explicit? Ce se întâmplă dacă nu încape în capacitatea disponibilă? Nu înlocuim răspunsul A+B+C cu A+B în lipsa acestei clarificări.
4. **Date de volum și limite pe produse:** capacități reale scuter/mașină, modul în care restaurantul declară încărcătura și tabelul de minute de la 16. Nu impunem unități arbitrare sau limite comerciale prin alegerea tehnică a algoritmului.
5. **Confirmarea primirii banilor:** cine confirmă achitarea restanței/rambursarea și ce se face dacă cele două părți contestă înregistrarea. Aprobarea neachitării de la 6A nu răspunde acestei întrebări. Este o decizie operațională pentru activarea plăților efective, distinctă de întrebările 11/12 retrase.

Nu se repetă întrebarea 7 rezolvată sau întrebările retrase. Configurația pentru pilot poate fi furnizată per restaurant, fără să așteptăm toate restaurantele viitoare. Valorile de test rămân sintetice, iar lipsa unui tarif nu devine zero/10%.

## Planul de continuare în etapele comerciale

| Ordine | Lot / etapă | Livrabil și criteriu |
| --- | --- | --- |
| 1 | Intake L1 / etapa 1 | Această matrice și checkpointul aditiv. Cerințele confirmate sunt separate de tabele/neclarități; retragerile și proveniența sunt păstrate. Etapa 1 rămâne deschisă pentru clarificările și probele fizice restante. |
| 2 | L4A / etapa 2 | Registru financiar separat, declarația lipsei de numerar, aprobarea restaurantului și autorizarea excepției de ridicare numai după aprobare. Identitate de operație, concurență, retry/restart/răspuns pierdut fără efect dublu; aprobare fără plată fictivă. Primul pas: schema și matricea actor–operație–stare, proiecția pură, apoi operațiile durabile și UI. |
| 3 | L4B / etapa 2 | Suma restantă, termenul de la 7 și achitarea efectivă. Necesită matricea confirmării banilor. O datorie achitată nu poate fi plătită din nou prin retry; snapshotul inițial nu este rescris. |
| 4 | L5B / etapa 2 | Restaurantul decide retur/păstrare; custodia, recepția, avansul efectiv, obligația și plata rambursării sunt operații distincte. Returul plătește livratorului zona 1; lipsa returului nu creează cursă fictivă. Tarifele dependente de 2/3 și sumele restaurantului așteaptă grilele. |
| 5 | L5C / etapa 2 | Anulare înainte de ridicare (>50% și <=50%) și până la două schimbări după sosire (>2 km și <=2 km), cu distanțe/proveniență, bani exacți și istoric. Verifică anulare–pickup concurent, aceeași schimbare repetată și respingerea celei de-a treia fără scrieri. |
| 6 | L6 / etapa 2 | Zi completă, drepturi, concurență și recuperare, pe sursa finală. Investigarea eșecurilor/blocajului istorice și acceptare explicită; existența pe baseline nu echivalează cu acceptare finală. Etapa 2 se închide numai după criteriile îndeplinite. |
| 7 | L7 / etapa 3 | Integrarea completă în restaurant: aprobări, decizii, sume/restanțe, formulare financiare/refacere recuperabile și regresia funcțiilor existente. A0–A8 și close-day nu se reconstruiesc. |
| 8 | L8 / etapa 4 | OCR cu verificare umană, draft editabil și import fără duplicate; API real după identificarea furnizorului și acces. |
| Ulterior | Etapele 5–7 | Livrator, GPS și alocare multiplă: cerere durabilă de pauză, lot A+B+C finit, volum, limite pe tip de produs și aprobare exterior. Pregătirea contractelor poate avansa acum; implementarea/probele rămân în loturile aferente. |
| Ulterior | Etapele 8–10 | Notificări/rapoarte, infrastructură și restaurare, pilot gradual cu 2–3 restaurante și publicare conform planului aprobat. |

Un blocaj comercial suspendă numai calculul/operația dependentă. Nu blochează schema și operațiile confirmate din L4A sau testele sintetice ale contractelor. Probele Android/iOS amânate rămân vizibile; acest plan nu le declară trecute.

## Review și verificare documentară

Review independent: agent intern `client_answers_review`, citirea grilei originale, checkpointului L3/L5A și pachetului L4. Reviewul a semnalat 2A/3D, prețul restaurantului distinct de remunerație, limita generalizării lui C, lipsa tabelului 16C și lipsa procedurii 17D. Punctul 7 a fost clarificat ulterior de utilizator și nu mai este blocajul inițial.

Git a fost citit cu optional locks dezactivate: `main...origin/main`, cu modificările preexistente păstrate. Publicarea acestui intake verifică hashul sursei, răspunsurile 1–18, backupul și păstrarea byte-exact a istoricului NEXT_SESSION, plus hashurile testelor protejate. Fără teste de aplicație, build, preview sau probe fizice executate în acest intake. Fără modificări de cod, baze de date, markeri, Git sau activări de servicii.
