# ProDelivery - urmatorul plan: close-day operational, S3-04

Data: 2026-10-10, Europe/Bucharest. Task ID: PD-S3-04-CLOSE-01.
Stare: PROPUNERE pregatita prin citire de cod/documente. Implementarea, testele noi si runtime-ul acestui packet nu sunt pornite prin intrebarea despre plan.
Etapa actuala: Etapa2 in_progress. Loturile BOOST02/BOOST03 sunt incheiate in scope local/sintetic; nu se repeta ca lucrari noi. Acest packet propune un increment ingust din Etapa3, nu acceptarea intregii etape.

## Rezultatul pentru utilizator

Actiunea de inchidere a zilei nu opreste comenzile si nu anuleaza o pauza existenta. Restaurantul activ continua sa primeasca comenzi noi si sa proceseze comenzile active. Pauza/revenirea sunt actiuni administrative distincte; restaurantul nu primeste drept nou de a se pune singur in pauza.

Se corecteaza exclusiv comportamentul operational confirmat. Cutoff-ul contabil, decontarea, remuneratia, retururile, rotunjirea si raportarea financiara finala necesita regulile clientului; nu se implementeaza formule sau o noua zi contabila presupusa la miezul noptii.

## Dovezi de pornire si autoritate

- NEXT_SESSION.md: ultimul checkpoint BOOST03; source15, protected65 si backups8 verificate, runtime propriu STOPPED.
- EXECUTION_PLAN_2026-09-26.md: Etapa3 panou restaurant, incremente inguste si verificare de regresie; planul comercial general nu trebuie reconfirmat integral.
- TASK_PACKETS/2026-10-10-stage2-boost-handoff.md:17-19: packetul anterior autorizeaza Etapa2 si exclude trecerea in Etapa3+. Acest plan nou nu pretinde ca autorizarea veche incepe automat noua implementare.
- Acelasi packet:368-377: restaurantul nu se pune singur in pauza; inchiderea zilei pastreaza comenzile existente si noi; cutoff-ul contabil este lipsa.
- TASK_PACKETS/2026-10-07-stage2-3-expanded-backlog.md:250-266: S3-04, comenzi active pastrate, review si QA distincte.
- backend/routers/restaurants.py:249-272: PATCH status scrie accepting_orders din payload, reseteaza pause_until/closed_today si, la closed_today cu accepting_ordersFalse, pune pauza pana la midnight. Aceasta este frontiera de separat.
- frontend/src/pages/RestaurantApp.jsx:303-323: status PATCH, UI aplica accepting din request si afiseaza inchidere ca offline. UI trebuie sa reconcilieze starea reala returnata de server, inclusiv la raspuns pierdut.
- Git verificat read-only: main...origin/main, dirty preexistent pastrat. Primul git sub sandbox a fost refuzat de filesystem; citirea scoped escalated a trecut. Nicio comanda Git de mutatie.

## Loturi finite - aproximativ 10 ore, estimare

| Lot | Buget | Rezultat si acceptare |
| --- | --- | --- |
| 1. Contract si baseline | 1h30 | Matrice close-day/pauza/admin/restaurant, payload legacy si conflicte; clasificarea celor15FAILfrontend/5FAILbackend istorice si1SKIP fata de reguli. Testele protejate raman intacte; cazuri de acceptare NOI, finite, numai pentru comportamentul confirmat. |
| 2. Backend operational | 3h | Separare close-day de accepting_orders/pause_until, compatibilitate explicita pentru payloadul vechi; tenant/rol/context curent, validari, double-click/raspuns pierdut/replay, conflict close-day versus adminpause fara lost update. Activele, ledgerul comenzilor si regulile financiare nu sunt mutate de close-day. |
| 3. Restaurant PWA | 2h30 | Actiune close-day cu semantica corecta, stare returnata de server, mesaje clare, loading/eroare/offline si recuperare explicita. Rolul restaurant nu are control de pauza administrativ. Reload/sesiune schimbata nu aplica rezultatul vechi. Actiunile existente de acceptare/pregatire/gata sunt verificate ca adiacente, nu refacute. |
| 4. Review si QA | 3h | Review independent cod/date/securitate; integrare Mongo sintetica si browser admin/restaurant la1440/390. Close-day -> comanda noua reala prin ruta aplicatiei, comanda activa continua, restaurant deja pausat ramane pausat; actor strain403 fara efect; duplicate/concurenta/timeout. Build/lint, regresie relevanta, dovezi/hash/checkpoint si stop numai runtimeowned cu date retinute. |

Bugetele includ repro, implementare si verificare si se pot suprapune prin agenti. Nu sunt timp minim de consumat, garantie de10ore neintrerupte sau acceptare implicita a unei implementari financiare. Se inchide fiecare lot cand criteriile sale sunt dovedite.

## Ownership si verificare

ROOT coordonator si owner frontend/integrarii. Owner backend intern pe fisier/scope disjunct; reviewer independent_review read-only si QA qa_discovery separat. Numai Codex si agenti interni OpenAI, model mostenit, conform AGENTS.md actual. Fara OpenClaw/Claude/AgentHubmutations sau serviciiAI platite.

Inaintea codului: packet de executie ingust confirmat, backup al surselor atinse si baseline hash/protected inventory incluzand noile teste BOOST03. Sunt pastrate rapoartele/sourcefreezes/indexurile BOOST01-03 ca snapshoturi istorice; nu se suprascriu outputs/taguri vechi.

Runtime: numai fixture nou, DBnonce nou si porturi loopback verificate libere, build separat cu dotenv dezactivat. Nu se porneste preview normal cu configDBreal, nu se restarteaza vechiul runtime BOOST03, nu se sterg sau reseed datele retinute. Viewport390 nu este telefon fizic/Safari; acestea raman gate separat.

## Criterii de inchidere si limite

1. Inchiderea operationala nu schimba accepting_orders/pause_until curente; un restaurant activ continua, unul deja pausat ramane pausat pana la actiunea administrativa conform politicii existente.
2. Nicio comanda activa dispare, se anuleaza sau se finalizeaza artificial. Niciun contor/sold/tarif/decont nu se recalcula prin acest increment.
3. Acelasi intent/retry nu produce efecte sau audituri duplicate; concurrencia cu pauza admin are rezultat explicabil fara pierderea starii. Mecanismul concret se alege dupa baseline, nu se declara deja implementat.
4. Raspunsul pierdut, actorul strain/inactiv si reload-ul pastreaza un rezultat verificabil, fara succes fictiv sau POST orb nou.
5. Review si QA distincte pe bytes finali, protected tests intacte. Failures istorice/filtrate sunt raportate separat; nu se modifica oracolele pentru verde si nu se promite green global anticipat.
6. Cleanupowned si checkpoint aditiv, cu date pastrate; fara commit/push/deploy, date reale/env/secrete, GPS/ADB/store, schimbari liveindexTTL/topologie, auto-dispatch/multislot sau finanteS2-05B.

Urmatorul pas sigur pregatit in aceasta conversatie este specificatia read-only de mai sus. Pornirea modificarilor S3-04 foloseste acest packet nou ca scope explicit; intre timp gates financiare si acceptarea Etapei2/S2-08 raman deschise.

## Review independent al propunerii

independent_review a verificat read-only packetul initial si liniile de cod: PASS factual/scope, fara runtime/tests sau scrieri. SHA initial7F03E311319A75A959330828EC6A9B844B0C91E26E6888F87D6EDCD85B4B7719, prefix pastrat.

Precizari de acceptare compatibile cu loturile de mai sus:
- Interzicerea self-pause se verifica prin API direct pentru rol restaurant, cu403 si zero writes, pe langa UI.
- Close-day modifica atomic numai campurile proprii; accepting_orders si deadline-ul exact al pauzei administrative raman intacte inclusiv la concurenta.
- Dupa ACK pierdut, clientul citeste starea reala si permite retry explicit al aceleiasi intentii; nu admite automat o mutatie noua. Gardurile de sesiune existente din RestaurantApp298-300/314/320-322 sunt pastrate.

Aceasta este clarificare aditiva de plan, nu schimbare de cod sau incepere a Etapei3.
