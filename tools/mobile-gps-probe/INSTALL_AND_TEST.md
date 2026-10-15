# ProDelivery GPS: proba Android locala

Aceasta este proba tehnica GPS, NU aplicatia completa a livratorului.
Pachet separat: `ro.ifrimdigital.prodelivery.gpsprobe`.
Nu transmite pozitii la ProDelivery, nu modifica comenzi si nu necesita Metro.
Varianta `diagnostic` este pentru un telefon de test autorizat, nu pentru magazine.

## Inainte de colectare

1. Pastreaza telefonul conectat prin USB si deblocheaza-l manual.
2. Deschide `ProDelivery GPS Probe`. Pornirea aplicatiei nu porneste GPS.
3. Fara acord si fara Start, nu trebuie sa existe sesiune sau observatii GPS.
4. Nu folosi date ale clientilor. Proba pastreaza coordonate necriptate in SQLite
   pe telefon. Nu le exporta sau distribui fara acord separat.

## Prima proba cu ecranul blocat

Acesti pasi se executa de proprietar dupa acordul explicit pentru colectare.
Rezultatele nu sunt garantate de build sau de testele software.

1. Selecteaza `Fundal`, inainte de Start. Modul `Prim-plan` are intentionat un
   contract conservator: dupa o tentativa de watch, oprirea senzorului nu poate
   fi confirmata de API-ul Expo si o noua pornire este blocata. Nu sterge datele
   si nu reinstala aplicatia pentru a ocoli acest avertisment.
2. Activeaza acordul pentru stocare GPS locala si apasa Start o singura data.
3. Citeste confirmarea de fundal. Aproba personal permisiunile Android necesare;
   alege locatie precisa. Accesul in fundal poate cere revenirea din Settings.
4. Pentru referinta, tine aplicatia vizibila aproximativ doua minute. Observa
   numarul evenimentelor si varsta observatiei; lipsa semnalului indoors nu este
   dovada ca telefonul sau aplicatia este defecta.
5. Blocheaza ecranul aproximativ cinci minute, apoi deblocheaza manual. Noteaza
   daca numarul evenimentelor a crescut si daca observatiile sunt proaspete.
6. Cu acordul proprietarului, repeta cu o deplasare scurta pe o ruta non-client
   si cu internetul oprit temporar. Proba poate stoca local, dar NU demonstreaza
   sincronizare/reconectare cu serverul.
7. Revino in aplicatie si apasa Stop. Verifica separat sesiunea SQLite inchisa,
   starea opririi native, notificarea serviciului si indicatorul Android de locatie.
   Un raspuns API nu certifica oprirea fizica a senzorului sau consumul bateriei.
8. Daca apare oprire neconfirmata, opreste aplicatia din controalele Android si
   verifica personal indicatorii/permisiunile. Pastreaza dovezile; nu reseta datele.

## Dovezi utile

- Modelul telefonului, versiunea Android si hash-ul APK-ului.
- Modul ales, permisiunile si intervalul aproximativ al testului.
- Numere de evenimente, intarzieri si precizie raportata, fara adrese/coordonate
  in rapoarte publice, loguri sau Git.
- Erori vizibile si observatia dupa Stop, separat de ceea ce spun API-urile.

Nu dezactivam automat protectiile bateriei si nu acordam permisiuni prin ADB.
Transferul datelor GPS de pe telefon necesita un acord separat, cu scope clar.
Testele pe alte Android-uri si iPhone raman distincte.
