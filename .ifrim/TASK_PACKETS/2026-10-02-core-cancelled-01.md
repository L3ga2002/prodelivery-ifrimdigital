# PD-CORE-CANCELLED-01 - urmatorul increment ingust

Data: 2026-10-02. Proiect: ProDelivery. Pachet: 10.000 EUR. Etape: 2 / core si suport pentru Etapa 1.

Status: ready for scoped implementation; neimplementat in taskul de inventar.
Owner: Codex backend/frontend. Reviewer: trecere separata Codex; nu auditor independent. QA: teste izolate + browser autorizat. OpenClaw/Claude nu se invoca.

## Evidence si obiectiv

`backend/routers/orders.py:332` include CANCELLED in feed-ul livratorului. `frontend/src/pages/DriverApp.jsx:177` selecteaza prima comanda care nu este DELIVERED. Fixture-ul reproductibil din `.ifrim/QA_RUNS/2026-10-02-stage1/` confirma comportamentul.

Obiectiv: comenzile terminale nu mai blocheaza sarcina curenta; istoricul si auditul raman disponibile. Nu convertim aici modelul de date la 10 comenzi si nu activam dispatch automat.

## Fisiere candidate si limite

- Backend: `backend/routers/orders.py`; helper de stari existent daca este potrivit; testele relevante din `backend/tests`.
- Frontend: `frontend/src/pages/DriverApp.jsx`; verificare adiacenta a listei active admin si a panoului restaurant, fara rescrierea taburilor/istoricului.
- Fara schimbari de DB, secrete, configuratie deploy, roluri, taskuri Hub, commit/push sau stergeri.
- Backup punctual al fisierelor existente inainte de editare, fara capturarea fisierelor excluse.

## Criterii de finalizare

1. Numai starile active cunoscute sunt sarcini curente; CANCELLED/DELIVERED nu sunt selectate accidental.
2. Istoricul comenzilor anulate si auditul nu dispar.
3. Alt livrator/restaurant nu primeste acces suplimentar.
4. Fixture cu CANCELLED prima si ASSIGNED a doua returneaza/prezinta ASSIGNED.
5. Numai terminale returneaza/prezinta empty state; date necunoscute/incomplete nu provoaca crash sau o livrare fictiva.
6. Refresh dupa anulare nu restaureaza comanda anulata in lucru.
7. Cele 18 teste baseline, noile regresii si lint trec; browserul verifica butoane/status/empty/error fara scrieri in baza existenta.

## Gate de QA

API integration si click-urile care modifica o comanda se executa numai pe mediu separat/fixture autorizat. Daca nu exista mediu izolat, raportam exact ce a fost verificat si nu pretindem fluxul real complet.

## Dupa acest fix

Continua `PD-DISPATCH-01` din `.ifrim/EXECUTION_PLAN_2026-09-26.md`: specificatie sursa autoritativa/capacitate/route-version, compatibilitate singulara, verificare read-only a topologiei Mongo pe mediu aprobat, teste D01-D20. Implementarea avansata, migrarile si activarea pe date reale nu sunt presupuse din acest packet.
