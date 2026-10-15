# PD-DISPATCH-01-SPEC-PROBE - pachet de lucru

Data: 2026-10-02. Proiect: ProDelivery. Etapa 1 a pachetului operational suplimentar de 10.000 EUR.

## Autorizare si rezultat

Catalin a cerut inceperea lucrului si folosirea exclusiva Codex + subagenti interni `gpt-6.1-sol`, High/Max. Nu se invoca OpenClaw sau Claude. Lucram pe inventarul/specification/probele timpurii din Etapa 1, nu activam Etapa 7 pe date reale.

Rezultate cerute: specificatie multi-comanda bazata pe contractele existente; proba izolata OR-Tools; review independent; rezultate reproductibile si handoff. Minimum 10 comenzi active pe acelasi livrator atunci cand sunt fezabile.

## Routing

- Owner/coordonare si specificatie: Codex, in acest chat.
- Implementer proba: subagent `gpt-6.1-sol`, High; numai directorul `optimizer-worker` din staging.
- Reviewer: subagent separat `gpt-6.1-sol`, Max; contracte, concurenta si proba. Raporteaza, nu modifica aplicatia.
- QA: verificari executate local si verificari independente ale probei; delimiteaza ce nu a fost testat.
- Invocation: tools interne Codex. Nicio lansare prin infrastructura externa.

## Suprafata de scriere si protectie

Staging: `C:\Users\mihai\.codex\visualizations\2026\06\09\019eae21-cb0d-7bf0-b6a5-ab4d21ab781f\prodelivery-stage1-completion-20261002`.

In proiect se publica numai fisiere aditive sub `.ifrim/TASK_PACKETS`, `.ifrim/LOOP_REPORTS`, `.ifrim/SPECIFICATIONS` si `.ifrim/QA_RUNS/2026-10-02-dispatch-probe`. Handoff poate primi o completare mica, cu backup si verificare hash. Nu suprascriem rapoarte existente. Nu modificam sursa aplicatiei, requirements, lockfile-urile sau documentul client.

Nu citim `.env`, credentiale, `.ifrim/private`, `.ifrim/tmp`, uploads. Nu efectuam scrieri Mongo, indexuri, conversie replica set, migrari, env/secrete, commit/push/deploy, servicii platite ori trimiteri externe. Dependenta solverului se instaleaza intr-un target temporar separat; nu in mediul aplicatiei.

Lock: write scopes disjuncte in staging; fara writer pe aplicatie/DB. Nu pretindem obtinerea unui lock Agent Hub. Endpointul read-only returneaza inca taskul istoric `PD-HUB-001`; planul comercial curent prevaleaza, fara editarea Hub.

## Verificare

1. Citire focalizata statusuri/roluri/asignare/pregatire si consumatori singulari.
2. Preview local HTTP; fara actiuni mutante pe conturi sau DB.
3. Proba matematica 1/2/5/10, precedent, ferestre, capacitate, input invalid, comenzi ridicate, buget finit.
4. Reviewer independent; fiecare finding valid se rezolva in document/proba si se reruleaza testul relevant.
5. Raport cu numarul exact al testelor, timp, versiuni si limite. Nici FakeDb, nici solverul nu dovedesc tranzactii reale, GPS fizic sau performanta 50/100.

## Gate de inchidere

Pachetul poate fi complet pentru specificatie de lucru + proba sintetica. Etapa 1 ramane `in_progress` daca protocolul nu a fost dovedit in Mongo separat sau mobil/GPS pe telefoane reale ramane neverificat. Nu declararea automata a intregii aplicatii gata.
