# ProDelivery - pregatire micro-proba mobila si plan Etapa 2

Data: 2026-10-02. Mod: implementare asistata aprobata, strict izolata. Coordonator: Codex. Owner mobil si reviewer/QA: subagenti Codex interni separati. OpenClaw/Claude: skipped, interzise explicit pentru acest proiect de Catalin.

## Stadiu si decizie

Etapa 1: **in_progress**. Etapa 2: **not_started**; planul detaliat este pregatit si verificat. Cererea de continuare este conditionata de inchiderea Etapei 1, nu autorizeaza declararea unui gate netestat ca trecut.

Plan: `.ifrim/TASK_PACKETS/2026-10-02-stage2-execution-plan.md`. Are opt loturi: contracte, creare recuperabila, corectii controlate, alocare/realocare manuala, anulare/custodie, lista/detaliu/istoric, audit transversal, regresie finala. Pastreaza alocarea automata ca cerinta a Etapei 7 si minimum 10 comenzi fezabile pe acelasi livrator. Sursa actuala a aplicatiei ramane singulara.

Review-ul independent al planului a gasit doua P1 si doua P2. Toate patru au fost corectate si inchise documentar: identitate idempotenta exacta, gate de compatibilizare a scriitorilor legacy, dry-run/backfill/restore inainte de migrare, rollback care pastreaza si recuperarea operatiilor create pending/ACK pierdut. Raport cu hash si istoric: `QA_RUNS/2026-10-02-mobile-probe/review/STAGE_2_PLAN_REVIEW.md`. Inchiderea planului nu este test de implementare.

## Ce se pregateste separat

`tools/mobile-gps-probe/` este un recorder tehnic Expo/React Native SDK57 cu identitate separata `ro.ifrimdigital.prodelivery.gpsprobe`, nu aplicatia livratorului din Etapa 5. Nu schimba backend/frontend sau datele ProDelivery.

- Pornire explicita, consimtamant, mod prim-plan/fundal si Stop; fara colectare automata la prima deschidere.
- Colectare nativa configurata, permisiuni si stari de eroare; SQLite local, sesiuni/secventa/timestamp/precizie.
- Limite explicite de stocare, duplicate/date invalide/stale/approximate/mocked; fara stergerea automata a dovezilor.
- Fara upload HTTP, autentificare ProDelivery, comenzi reale, export/share automat sau servicii platite.
- Coordonatele nu sunt afisate in consola/UI, dar raman plaintext in sandboxul SQLite. Android backup este dezactivat; backupul OS/iCloud iOS nu este controlat/demonstrat. Consimtamantul si setarile telefonului se verifica inainte de capturi reale.

## Verificari ale aplicatiei existente in aceasta rulare

| Verificare | Rezultat | Limita |
| --- | --- | --- |
| Backend izolat pe sursa actuala | 672 PASS, 0 FAIL, o deprecare existenta Starlette/httpx | Unit/in-memory; DB inlocuit cu guard, dotenv dezactivat, socketuri externe blocate. Nu este HTTP autentificat sau Mongo real |
| Frontend orderWorkflow | 74 PASS, 0 FAIL | Helper tests, nu click-through/browser |
| GET http://127.0.0.1:3000/login | HTTP 200 | Disponibilitate, nu flux autentificat |
| GET http://127.0.0.1:8000/api/ | HTTP 200 | Health, fara modificari de date |
| Hub continuation read-only | HTTP 200, faza istorica returnata | Nu prevaleaza asupra planului local actual; Hub nu a fost modificat |

Prima tentativa de colectare pytest a esuat inainte de teste: rootdir comun a fost dedus la `C:\Users\mihai`, iar sandboxul a refuzat enumerarea. Am rulat din proiect cu `--rootdir=.` si `--noconftest`, aceleasi teste, fara schimbare de sursa/validare. Rularea corecta a trecut 672 teste in 64.08 s. Nu este o regresie a aplicatiei mascata prin stergerea testelor.

Comanda backend reproductibila din root ProDelivery (alegeti un nume nou pentru rezultat, nu suprascrieti probele anterioare):

```powershell
& .\.venv\Scripts\python.exe -B .\.ifrim\QA_RUNS\2026-10-02-core-fixes\run-tests.py --live-source --noconftest --rootdir=. --junitxml=<cale-rezultat-nou.xml> --tb=short
```

`--live-source` selecteaza fisierele checkoutului, nu baza activa; runnerul inspectat inlocuieste `database`, blocheaza dotenv/helperii de credentiale/conexiunile externe si dezactiveaza bytecode/cache. Frontend: scriptul `frontend-regression.cjs` din dovezile acestei rulari, cu rezultat JSON.

## Verificari ale probei mobile

Ownerul a inghetat sursa/configuratia in SOURCE_HASHES.json. Coordonatorul a rerulat independent cele **58 teste ale implementerului: 58 PASS, 0 FAIL/skipped/cancelled**, exit 0, 3011.9802 ms. Testele ruleaza validarea/controlerul si SQL-ul real prin Node SQLite; permisiunile si serviciile de locatie sunt simulate. Nu este test al bridge-ului Expo sau telefonului. Ownerul a rulat si cele 28 teste ale reviewerului nemodificate: 28 PASS; verificarea finala a reviewerului este consemnata separat in raportul sau.

Reviewerul a verificat apoi independent **34/34 PASS**: cele 28 teste initiale nemodificate plus sase cazuri tintite, fara FAIL/skipped/cancelled. Toate cele 23 fisiere din manifest au ramas stabile. Verdict strict **APPROVED_SOURCE_CHECKPOINT_ONLY**: R1-R3 inchise, R5 tratat explicit prin diagnostic conservator, fara constatare noua in aria verificata. Nu se extinde la instalare/typecheck/bundle/native build sau hardware. Dovezi: `QA_RUNS/2026-10-02-mobile-probe/review/NATIVE_FINAL_REVIEW.md` si `native-results-final.json`.

Total distinct pentru logica probei: 58 + 34 = 92 teste trecute. Cele 28 rerulate de owner sunt acelasi subset si NU se aduna inca o data. Snapshotul mic `QA_RUNS/2026-10-02-mobile-probe/probe` pastreaza sursa necesara reproducerii testelor independente; modulul de lucru este `tools/mobile-gps-probe`, iar snapshotul QA nu se editeaza ca a doua implementare.

Review preliminar: R1/P1 oprire nativa omisa dupa eroare SQLite in initializare; R2/P2 callback vechi inchide sesiunea noua; R3/P2 trecere in fundal pierduta in timpul Start prim-plan. Teste independente initiale: 28 total, 24 PASS, 4 FAIL. Patru teste esuate corespund celor trei constatari; corectiile nu pot sterge/slabi aceste teste. Rularea preliminara a observat surse in schimbare si nu constituie aprobare finala.

R5/P2 este o constatare statica suplimentara la limita adaptorului SDK: expo-location 57.0.20 returneaza void pentru watch.remove(), iar apelul nativ intern removeWatchAsync nu este asteptat/returnat de acel API public. Nu rezolvam prin await pe void si nu modificam dependenta. Recorderul trebuie sa distinga oprirea callbackurilor/sesiunii locale de confirmarea opririi native. Nu este un defect reprodus pe telefon si nu este unul dintre cele patru teste initiale esuate.

Implementerul a corectat R1/R2/R3 cu cleanup independent de SQLite, bariera durabila pentru Stop si invalidarea Start prim-plan la schimbarea lifecycle. R5 este tratat conservator: intentia foreground si oprirea neconfirmata persista, UI nu pretinde confirmare hardware, iar restartul nu deblocheaza tacit colectarea. Procedura de recuperare cere interventia proprietarului la nivel OS si reconciliere ulterioara autorizata cu dovezile pastrate. Nu este un fix al SDK-ului si nici o garantie a opririi fizice.

### Blocaj intern de build, separat de dispozitive

Trei instalari npm complete nu s-au incheiat si au fost intrerupte individual de owner; nicio sesiune nu a fost lasata deliberat activa. Nu s-a stabilit cauza radacina si nu atribuim generic esecul retelei/permisunilor. Lockfile-only a trecut, 13/13 pin-uri directe concorda; aceasta NU este o instalare valida a tuturor modulelor.

- Typecheck final: exit 1, patru diagnostice, inclusiv `Cannot find module 'react-native'` si erori de tip dependente. Full typecheck **NOT_PASSED**; alte erori nu pot fi excluse pana la instalarea completa.
- Android JS export si iOS JS export: ambele exit 1 inainte de bundling, `Cannot find module '@expo/cli'`; **BLOCKED**.
- Fara APK/IPA, native build, native configuration generation sau QA vizual/fizic.
- Comenzi/sesiuni/loguri: `tools/mobile-gps-probe/VERIFICATION.md`. Logurile brute si dependentele partiale raman in stagingul original, nu sunt copiate in proiect: `C:\Users\mihai\.codex\visualizations\2026\06\09\019eae21-cb0d-7bf0-b6a5-ab4d21ab781f\prodelivery-stage1-mobile-20261002\probe`.

Urmatoarea lucrare interna este diagnosticarea instalarii incomplete si apoi typecheck/exporturi/native build; nu presupunem ca singurul blocaj ramas este disponibilitatea telefoanelor. Nu lansam un al patrulea install identic fara diagnostic.

## Limite care raman obligatorii

Nu exista proba pe Android/iPhone fizic in aceasta rulare. Nu au fost instalate SDK-uri globale, aplicatii pe telefoane sau facut pairing; nicio permisiune GPS ceruta proprietarului, nicio colectare reala, niciun build cloud sau cont accesat. Bundle JavaScript, daca trece, nu este APK/IPA si nu dovedeste restrictiile OS, lockscreen, bateria sau bridge-ul nativ SQLite.

Recorderul local nu contine transport/sink: offline capture nu demonstreaza sincronizarea la revenirea internetului sau D20 actiuni de comanda offline. Aceste probe raman distincte. Nici sursa, nici teste Node cu SQLite real si porturi native simulate nu inchid M5. M3 complet, migrarea live, benchmarkul 50/100 si productia nu sunt certificate aici.

Pentru continuare: cale build Android verificata, cale iOS Mac/Xcode/provisioning sau build semnat valid, Android si iPhone fizice si tester cu consimtamant. Intrebarea despre disponibilitate este deja trimisa lui Catalin; niciun raspuns nu este inventat. Pregatirea interna este deja aprobata, nu necesita reaprobarea planului.

## Protectia proiectului

Publicare numai prin manifest si hash guards, fisiere noi pentru probe/plan/review; pentru NEXT_SESSION/PROJECT_STATE/OPEN_ISSUES se adauga o sectiune noua dupa backup verificat, pastrand istoricul. Fara modificarea sursei existente a aplicatiei, bazei Mongo, env/secrete, Agent Hub, Git history sau deploy. Staging si dependentele/probele sintetice nu sunt copiate in masa in proiect.

Urmatorul lot de Etapa 2 este S2-01, doar dupa raportul de inchidere a Etapei 1. Nu s-a inceput implicit prin scrierea acestui plan.
