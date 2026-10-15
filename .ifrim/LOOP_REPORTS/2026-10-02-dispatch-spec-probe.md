# PD-DISPATCH-01 - specificatie, proba izolata si QA

Data: 2026-10-02. Proiect: ProDelivery. Etapa: **1 din 10**, pachet operational suplimentar 10.000 EUR. Etapa ramane **in_progress**; acesta nu este raport de lansare sau alocare activata.

## Rezultat concret

1. Matrice cerinta/cod/test pentru fluxurile existente, folosind baseline nou, nu rapoarte istorice.
2. Specificatie PD-DISPATCH-01 v0.3: sursa autoritativa, quota activa+rezervata, capacitate fizica, tranzactii/guard, pending durabil/fencing, idempotenta, ruta dirty/dependente, compatibilitate legacy, incidente si migrare aditiva.
3. Proba OR-Tools 9.15.6755 independenta de aplicatie: 1/2/5/10 comenzi pe acelasi driver, ferestre, load, pickup/dropoff, onboard, input/output invalid si timeout supraveghetor.
4. Review si QA facute de subagenti Codex distincti, findings reparate, teste rerulate, rapoarte initiale pastrate.
5. Cercetarea Glovo ceruta in timpul lucrului, cu surse primare si separarea regulilor publicate de propunerile noastre: `2026-10-02-glovo-dispatch-factors.md`.

## Routing real

- Coordonare/spec/integrarea artefactelor: Codex, chatul principal.
- Implementer si fixer proba: `gpt-6.1-sol`, High, agent `01a0fc69-ff7d-7ef1-9d9e-92193943672c`.
- Review independent specificatie: `gpt-6.1-sol`, Max, agent `01a0fc70-8038-7f73-af90-628dd9f1edd8`.
- QA independent proba: `gpt-6.1-sol`, High, agent `01a0fc76-8648-77d2-9e47-960db61ba635`.
- Invocation: tools native de subagenti, fara OpenClaw/Claude. Scope-uri de scriere distincte; review/QA nu au modificat workerul si nu si-au aprobat propria implementare.

Fara lock pretins in Hub. Endpointul read-only este online, dar continua sa descrie taskul istoric PD-HUB-001/vechea faza. Nu am modificat Hub; planul comercial nou prevaleaza.

## Verificari executate si numar exact

| Executie | Rezultat | Limita |
| --- | --- | --- |
| Baseline main, runner izolat | **18 passed**, 4.58s; JUnit pastrat | Reguli pure/FakeDb, nu Mongo real |
| Proba initiala main | 37 metode trecute, 8.855s | Nu include regresiile adversariale descoperite ulterior |
| QA independent inainte fix | 20 metode: 12 integral trecute, 8 cu probleme; 23 failures + 6 errors | Sunt evenimente de failure/subTest, nu 29 metode distincte; 4 cauze P2 |
| Main dupa fix | **45 metode + 20 independente = 65 trecute**; 207+64 subcazuri, 0 failures/errors/skips | 13.612s si 15.061s pe aceasta masina, nu SLA |
| QA independent dupa fix | **45 + 20 = 65 trecute**; 207+64 subcazuri; zero failures/errors/skips | 13.156s si 13.767s; worker hash stabil |
| QA suplimentar failure normalization | 120 verificari trecute | Verificari separate, nu adaugate fictiv la numarul metodelor |
| Preview HTTP | Login 3000 si API 8000: HTTP 200 | Fara click-through autentificat sau actiuni DB in acest increment |
| Git sursa | `git diff --name-only -- backend frontend`: fara output | Aplicatia nu a fost modificata; dirty documentatie/config preexistent pastrat |

Timeout demonstrat determinist: copil care doarme, supraveghetor 100ms, kill/reap si raspuns fara ruta; QA observa aproximativ 0.13s wall cu overhead OS. Limita nativa de 1ms nu este o garantie end-to-end: import/startup dureaza suplimentar, iar un rezultat lipsa nu dovedeste imposibilitatea matematica. Nu am slabit sau eliminat testele independente.

## Findings rezolvate in acest pachet

| Problema | Cauza | Reparatie | Fisiere |
| --- | --- | --- | --- |
| R1 High spec: pending fara recuperare durabila completa | Commit incert/restart nu avea intentie/claim definit | Admisie durabila, operation_ref, lease/fence, committed/rejected si arbitrare pe acelasi document | PD-DISPATCH-01.md; review follow-up/closure |
| R2 High spec: ruta stale dupa pregatire | Recalcul asincron fara invalidare atomica explicita | Dirty + dependency_versions + CAS; distinctie navigare stale versus livrare fizica confirmata | PD-DISPATCH-01.md |
| R3 Medium spec: lookup/digest ambiguu | Cheie scoped actor/tip, dar GET incomplet si target URI nedefinit | operation_ref server unic; digest include target/tip/payload/expected_versions | PD-DISPATCH-01.md |
| R4 Medium spec: retur/incident fara rezolutie in stari | Doar delivered era terminal dupa picked_up | Incident ortogonal, returned real/receipt si restrictii; handover generic fail-closed | PD-DISPATCH-01.md |
| R2-F1 Medium spec: tabel deliver contradictoriu | Rand API cerea stop executabil pe ruta dirty | Randurile deliver/GET aliniate cu exceptia de inregistrare fizica | PD-DISPATCH-01.md |
| P2 partial failure route | accept_result returna failure envelope necuratat | Boundary comun; orice failure are route[], verified=false, no optimum claim | optimizer_worker.py, test_optimizer_worker.py |
| P2 status/envelope invalid | Membership pe tip nehashabil sau dict absent | Type/schema validation fail-closed fara exceptie expusa | Aceleasi |
| P2 solver_status NaN/invalid | Metadata propagata putea rupe JSON CLI | Enum versionat strict, parser finite, serializare defensiva; exit2 JSON, fara traceback | Aceleasi |
| P2 duplicate JSON output keys | Parser child permitea last-value-wins | Parser strict si pentru output, duplicate/nonfinite respinse | Aceleasi |

Inchiderile spec sunt **DOCUMENTARE**, nu dovada ca protocolul a fost implementat sau ca atomicitatea este demonstrata. SHA256 spec final verificat de reviewer: `13589B13B1B328252112DEE38A7DE2355A89CB372605917AC5965F3116C8ED63`.

Worker final SHA256: `42c22a11b656ac645e3f5a58e1b080a28306144b28e090045d12a4a809293118`. Fixture-urile si testele QA au ramas neschimbate in timpul fixului. 37 teste proprii originale au fost pastrate, 8 regresii proprii adaugate; 20 independente au ramas intacte.

## Exemple executate, numai sintetice

- 10 active, un driver, capacitate fizica 1: feasible, peak_load1, 22 noduri inclusiv depot start/end, toate cele 20 opriri pickup/dropoff verificate.
- 10 active, pickup-uri inaintea tuturor livrarilor, capacitate10: feasible, peak_load10, 22 noduri.
- Aceeasi situatie cu capacitate9: infeasible prin certificat simplu, zero ruta expusa.
- Comanda deja ridicata + una noua: doar dropoff pentru onboard, initial_load valid, feasible.

Timpii/main metrics sunt in `main-samples.json`, executati inainte de output-hardening. Suitele finale reexecuta cazurile pe workerul reparat. Matricile sunt artificiale, nu minute sau kilometri reali in Bacau; nu sunt benchmark 50 restaurante/100 driveri.

## Ce a ramas neschimbat

Nu am modificat `backend/`, `frontend/`, requirements aplicatiei, lockfiles, documentul client, DB/topologie/indexuri, env/secrete, conturi sau date client. Nu am facut commit/push/deploy si nu am cumparat hosting/API/meteo/OCR. Nu am invocat OpenClaw sau Claude. Runtime-ul probei a fost instalat cu pip --target numai in staging/deps.

In proiect se publica artefactele noi, scripturile sintetice si completari mici la NEXT_SESSION/PROJECT_STATE/OPEN_ISSUES, cu backup al originalelor, hash guard pentru editari concurente si verificare SHA256. Istoricul si rapoartele initiale se pastreaza.

## Etapa si urmatorul pas

Complete in acest pachet: inventar focalizat, spec de lucru reviewed, proba un-driver si QA adversarial, cercetare factori si handoff.

Incomplete: probe reale Mongo/concurenta/crash (M3), fluxuri multi-comanda browser (M4), mobil Android/iOS/GPS fizic (M5), benchmark (M6), politica vehicul/ferestre/offline si gate-uri operationale. Nu certificam M1/M2 pentru intreaga aplicatie printr-un worker sintetic.

Blocked extern: documentatie/furnizor/acces API al restaurantului; dispozitive/conturi pentru probe native; infrastructura de test tranzactionala separata si hosting public de stabilit. Niciunul nu impune reluarea proiectului de la zero.

Next best task: **PD-CORE-CANCELLED-01**, fix ingust feed driver + selectie UI + regresii, apoi PD-CORE-PREP-DISPATCH-01. In paralel pregatim aprobarea mediului Mongo sintetic separat si proba fizica GPS. Owner Codex; reviewer intern separat pentru API/stare; QA intern + teste locale/browser pe date sintetice. Nu activam etapele viitoare sau alocarea pe DB actual printr-o simpla schema.

Preview local verificat HTTP: `http://127.0.0.1:3000/login`, backend `http://127.0.0.1:8000/api/`. Deschiderea panelului Codex a fost solicitata; user ambient context confirma URL login. Nu s-a efectuat QA vizual pe dashboardurile autentificate in acest task fara schimbari UI.
