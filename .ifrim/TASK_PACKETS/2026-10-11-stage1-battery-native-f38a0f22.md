# ProDelivery — Etapa 1: instrumentare nativa baterie Android

Lot: 2026-10-11-stage1-battery-native-f38a0f22. Ordinea ceruta de Catalin este Etapa 1 -> Etapa 2 -> Etapa 3 si apoi restul, pe rand. Loturile tehnice A0-A8 anterioare nu inseamna etape comerciale inchise. iOS fizic si raspunsurile clientului sunt amanate explicit pentru final.

Scope autorizat: recorderul separat ro.ifrimdigital.prodelivery.gpsprobe, actualizare compatibila vc4/0.1.3 si proba finita baterie. ROOT controleaza telefonul; specialistii Codex fac implementare, review si QA distincte. AGENTS.md specific pastreaza Codex only. Fara Hub, OpenClaw, Claude, Git writes, deploy sau baze comerciale. Telefonul este eliberat de Catalin; nu se reia vechiul worker shell sau ADB Wi-Fi.

Surse integrate: 17 fisiere, din care App.tsx si app.json sunt originale modificate cu backup hash-verificat; restul sunt aditive. RecorderController, native.ts, dependentele si pluginurile GPS existente sunt pastrate. integration-manifest.json si build-input-manifest.json sunt in QA_RUNS/2026-10-11-stage1-battery-native-f38a0f22. Backup: BACKUPS/2026-10-11-stage1-battery-native-f38a0f22.

Review independent: GO_SOURCE. QA: TypeScript strict exit0; 134/134 =126 existente +8 noi; 29/29 protocol Kotlin; 25/25 jurnal real Kotlin cu stubs QA; 50/50 verificari TS independente includ2 bridge KotlinJSON->TS. Categoriile nu se aduna cu rerularile ca teste noi. 140 intrari din manifestul protejat au ramas neschimbate. Aceste probe host nu certifica Android framework sau telefon.

Protocol: gate continuu20s real fara alimentare, pilot30s faraGPS. Daca pilotul trece: idle900s, apoi Start/Continua explicit cu acordul existent, GPS900s si Stop serializat. checkGpsStart observa durabil un snapshot actual dupa prompturile OS, inaintea pornirii GPS. ownGpsServiceStarted observa serviciul propriu, fara coordonate/identificatori externi. Nu certifica fix-uri sau consum zero. Fiecare fereastra are propriile endpointuri; pauza pentru Start este jurnalizata dar nu amestecata in ferestre.

Observatorul nu porneste, reia sau opreste GPS. In cazul suspendarii JS, la awaiting_stop sau eroare utilizatorul revine in aplicatie pentru Stop. Deadline45min se verifica la observatii; revenirea tarzie si gap>25s lasa INCOMPLETE. Nu folosim wakelock, simulare unplug sau reset baterie. Reconectarea USB dupa inchiderea durabila a ferestrei nu rescrie dovada.

Starea acestui checkpoint: source/review/QA PASS; build Android in curs; APK neinstalat; GPS nepornit in acest lot; proba fizica NOT_RUN. Urmatorul pas: finalizare si verificare APK, update -r fara -g/uninstall/reset, UI propriu, pilot scurt, apoi masurarea lunga doar pe rezultat valid. Stop/offline vc3 istorice raman dovezi separate; bateria43b istorica INCOMPLETE ramane in istoric.
