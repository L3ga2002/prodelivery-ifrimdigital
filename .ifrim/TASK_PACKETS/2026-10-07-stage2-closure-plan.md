# ProDelivery - Plan pentru inchiderea Etapei 2

Data: 2026-10-07. Aprobare: Catalin a cerut planul si executia.
Etapa comerciala: 2 - Comenzi si administrare, din pachetul cu zece etape.
Nu renumerotam etapele si nu refacem de la zero lucrarile existente.

## Ce avem deja

- S2-01: contractele stricte pentru operatii si rezultate.
- S2-02: creare recuperabila backend si integrarea formularului admin.
- S2-COMPAT: revizie comuna; pregatire/gata cu CAS; refuz explicit pentru
  writerii versionati inca neconvertiti; mentenanta distructiva default-deny.
- S2-03: corectii operationale admin, conflicte, audit si recovery.

Acestea sunt implementari verificate in mediul sintetic documentat. Nu sunt
activate implicit pe date reale; rezultatele istorice nu sunt teste ale lotului nou.

## 1. S2-04 - Alocare si realocare manuala

- O tranzactie leaga comanda, rezervarea livratorului, eliberarea rezervarii
  anterioare, rezultatul recuperabil si auditul.
- Revizia asteptata si disponibilitatea se verifica la executie; doua persoane
  nu pot castiga aceeasi comanda sau acelasi ultim loc.
- Pastram pregatirea si timerul restaurantului; nu mutam automat custodia.
- Identitatea intentiei se pastreaza dupa timeout, raspuns pierdut, reload si
  doua taburi. Un rezultat incert nu genereaza o cerere legacy sau un ID nou.
- Erori explicabile pentru livrator ocupat, pauza, offline, dezactivat, date
  inconsistente si versiune veche. Fara override ascuns al invariantilor.
- Formularul actual ramane, cu loading/disabled/recovery/conflict necesare.
- Compatibilitate singulara pastrata; suportul viitor minimum10 si alocarea
  automata nu sunt prezentate ca terminate prin acest lot.

Dovezi: teste Mongo concurente si fault injection, contracte HTTP/autorizare,
teste frontend, review independent, browser desktop/mobil si fluxuri adiacente.

## 2. S2-05 - Custodie, anulare si incidente/refaceri

- Conversia acceptarii/ridicarii/livrarii la acelasi protocol recuperabil,
  cu revizie, actor, proprietar actual si un singur efect business.
- Anulare eligibila cu motiv si istoric; elibereaza numai resursele comenzii.
- Dupa ridicare pastram incidentul si rezolutia explicita; comanda livrata
  nu este resetata la NEW si marfa nu dispare printr-un update de status.
- Refacere partiala legata de original, fara dublarea contorilor/taxelor/
  incasarilor/creditului livratorului. Pastram regulile financiare existente.
- Daca apare o decizie financiara noua, ambigua, o confirmam punctual inainte
  de activare. Nu inventam politica clientului.

Dovezi: cancel versus pickup/deliver, duplicate, ACK pierdut, restart, comanda
straina, produs lipsa/refacere, rollback la audit si contori; QA admin/driver.

## 3. S2-06 - Liste complete, detaliu si istoric

- Paginare server-side cu limite, sortare stabila si tie-breaker.
- Active/istoric si filtre restaurant/livrator/status/data conform rolului.
- Detaliu autorizat cu pregatire distincta de executie, sursa si audit.
- Citirile vechi nu suprascriu rezultatele noi; pastram filtrele dupa actiuni.
- Loading/empty/offline/error explicite; retry finit numai pentru citiri.
- Datele incomplete nu produc status fictiv sau un crash de afisare.

Dovezi: peste limita actuala, timestamp egal, ultima pagina, schimbare filtru,
out-of-order GET, reload, acces strain, refresh esuat dupa mutatie confirmata.

## 4. S2-07/08 - Audit si regresia finala

- Audit critic legat de commit, corelat prin actor/operation_ref/request_id/
  versiuni si ora serverului; replay nu dubleaza evenimentul.
- Diagnostic fara parole/tokenuri/telefon/adresa sau GPS brut in loguri inutile.
- Flux complet: creare -> pregatire -> alocare -> acceptare -> gata -> ridicare
  -> livrare -> istoric, plus realocare, anulare si incident/refacere.
- Verificam roluri straine, doi admini, dublu-click, pauza/inchidere restaurant,
  timeout, offline/revenire, reload si erori de backend.
- Review separat de implementer, teste pe sursa integrata si QA in browser.
  Defectele blocking mentin lotul deschis; nu slabim/stergeam teste.

## Gate distinct pentru activare

Scopul tehnic si activarea reala sunt statusuri distincte. Inainte de live:

- Inventar dry-run al versiunilor invalide, duplicatelor/orfanilor si legaturilor.
- Migrare cu excluderea scriitorilor, reconciliere si rollback conservator.
- Backup/restore demonstrat separat, retentie ledger si payload temporar,
  politica financiara pentru destinatii corectate.
- Aprobare explicita pentru date reale, markeri, indexuri/topologie si deploy.
- Lookup/replay/recovery continua pentru intentiile deja admise la disable;
  rollback-ul nu readuce writeri legacy peste comenzi versionate active.

Nu activam aceste setari printr-un test si nu pretindem certificare de productie
din numarul testelor. Etapa 2 se declara inchisa numai cu raport de acceptare
al scope-ului, toate loturile necesare verificate si limitele live explicite.
Etapa 3+ nu incepe prin acest plan. OCR/API/GPS/native/auto-dispatch/store/load
50restaurante/100livratori au propriile etape si dovezi, nu sunt omise din plan.

## Executie si siguranta

Numai Codex si subagenti interni: owneri backend/frontend pe fisiere disjuncte,
reviewer si QA separati. Catalin gestioneaza Agent Hub. Fara OpenClaw/Claude,
mutatii Hub, commit/push/deploy, secrete sau baza aplicatiei. Backup/hashguard
inainte de integrare; toate modificarile preexistente si istoricul sunt pastrate.
Preview: http://127.0.0.1:3000/login, API: http://127.0.0.1:8000/api/.
Nu fixam termenul inchiderii inainte de masurarea defectelor din loturile ramase.
