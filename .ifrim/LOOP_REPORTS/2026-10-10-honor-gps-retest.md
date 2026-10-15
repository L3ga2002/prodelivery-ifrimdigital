# ProDelivery - reluare proba GPS pe HONOR, 2026-10-10

Verdict: PASS software scoped, revenire/Stop UI/contor stabil observate fizic.
Gate-ul strict `serviciu absent dupa Stop UI`: FAIL; obiectul
serviciului ramane listat cu `startRequested=false`. Hardware-ul global nu este
certificat. Nu se declara GPS production-ready sau etapa comerciala incheiata.

Owner: Codex. QA independent: Avicenna, subagent intern OpenAI, fara ADB.
Routing Codex only conform regulii proiectului; fara OpenClaw/Claude/Hub.
Instrument: ro.ifrimdigital.prodelivery.gpsprobe, nu aplicatia completa livrator.
HONOR LNA-NX1/Android16/API36, stationar, alimentat USB. Date locale neexportate.
APK0.1.1/vc2 SHA256036E70306029A52774B00C4ECDF5B52931C6DCAD1971F13ED6E5099B9ED7D0E0,
reverificat la fiecare captura acceptata. Nu s-a reinstalat sau schimbat codul.

## Istoric si reluare

Raportul 2026-10-10-honor-gps-runtime.md ramane intact si partial pentru proba
precedenta. Force-stop-ul precedent nu devine retroactiv un Stop UI reusit.
Catalin a deblocat telefonul si a confirmat din nou controlul pentru teste.
Nu s-a folosit, salvat sau repetat PIN-ul. Scope numai pachetul propriu.

23:30:56UTC: UI sesiune inchisa, interrupted_session vizibil, SQLite inchis,
API Stop confirmat/hardware neverificat, permisiuni neacordate, serviciu absent.
Aceasta inchidere a sesiunii intrerupte precede noul Start explicit.
Reacordate exclusiv fine/coarse/background. Fundal -> acord local -> Start ->
Continua. Start aproximativ23:32:41UTC; UI recording, SQLite activ, Start disabled.

## Proba ecran stins si revenire

- 23:33:12UTC:88evenimente globale/3sesiuni,0duplicate/0respinse/2tardive,
  observatie2s, mostre background cu precizie20m raportata de sistem.
- 23:33:57UTC:92evenimente, varsta7s, criterii locale indeplinite.
- 23:34:00UTC: ecran stins, Dozing/AOD, USB-powered, serviciu propriu listat.
- 23:36:09UTC: Dozing, keyguard blocat, serviciu propriu listat.
- 23:39:14UTC: Dozing, keyguard blocat, serviciu listat; minimum311.9s fata de
  checkpointul de inceput. Trezire23:39:16UTC, deblocare manuala apoi confirmata.
- 23:40:26UTC:135evenimente,3sesiuni,0/0/2, varsta10s, eligibilitate locala.
  UI arata background/sample si lifecycle active la02:40:04 ora telefonului.
  Cresterea92->135 inseamna43evenimente MIXTE, nu43puncte GPS certificate.
  Mostrele vizibile recente au ore02:39:54,02:40:04,02:40:14; ultimele sunt
  dupa trezire. Nu dovedesc singure continuitate completa in toate cele5minute.

Nicio captura a lockscreenului, coordonata sau baza SQLite transferata.
Dozing/AOD nu demonstreaza OFF complet/deepDoze. Telefonul nu a fost deplasat.
Precizia20m este raportata, nu eroare masurata fata de ground truth.

## Stop normal din aplicatie

Butonul Stop propriu apasat aproximativ23:41:25UTC (stare ADB23:41:27UTC).
23:41:31UTC: UI idle, nicio sesiune activa, SQLite inchis, API Stop confirmat /
hardware neverificat;143evenimente globale si3sesiuni. Serviciu inca listat.
23:42:11UTC:143evenimente,0/0/2, nicio observatie curenta, neeligibil.
23:43:04UTC: aceleasi143evenimente; peste90s dupa prima captura Stop.
Stop repetat de doua ori in idle:23:44:26UTC ramane idle/inchis/APIconfirmat;
23:44:33UTC contoare143/3/0/0/2, fara crestere si fara sesiune noua.

Metadate scoped23:43:00UTC: LocationTaskService record present,
startRequested=false. Parserul nu a gasit camp foregroundState; lista vida
NU este dovada foreground=false. Prezenta clasei != dovada locatie activa;
absenta mostrelor locale != certificare oprire hardware. Nu eliminam acest
detaliu sau nu reformulam retrospectiv criteriul original ca PASS complet.
Review independent in retest-qa/physical-review.md explica limita si sursa.
QA a inspectat31dovezi noi (13PNG/18JSON), nu toate34fisierele din manifestul
owner final. Idle-controls si containment final sunt verificate separat de owner.
Inferenta din sursa Expo instalata: serviciul este bind-uit cu BIND_AUTO_CREATE,
Stop apeleaza stopForeground/stopSelf, iar cererile de locatie sunt anulate
separat. Acesta este motivul plauzibil al recordului ramas; nu este demonstratie
ca toate solicitarile native s-au oprit efectiv pe telefon. Fara patch framework.

Exit-info al pachetului la23:44:33UTC:5crash-uri vechi pana la01:08 ora telefonului,
niciun APP_CRASH nou in intervalul acestei reluari. Istoricul este pastrat.

## Sfarsit sigur, separat de Stop UI

23:45:44UTC: dupa probele UI, force-stop numai pachet propriu si revocare numai
fine/coarse/background. Serviciu absent verificat si toate3perms GPS denied.
Datele nu au fost sterse, app-ul nu a fost dezinstalat. Aceasta containment
finala este separata de Stop UI; nu este folosita pentru a demonstra acel gate.
Reacordarea permisiunilor si Start explicit sunt necesare la urmatoarea proba.
Localizarea Android globala si alte aplicatii au ramas neschimbate.

## Teste proaspete independente

Avicenna a executat o singura data testele sursei reale la23:38:57-23:38:59UTC:
106PASS/0FAIL/0SKIP, exit proces0.16/16hash-uri protejate identice pre/post;
total22/22fisiere sursa/test/config neschimbate. Nu sunt rezultate istorice.
Typecheck/build nu au fost rerulate in aceasta reluare; rezultatele precedente
raman istorice. SQLite ExperimentalWarning pastrat in stdout.

Agregatorul QA initial exit1 astepta TAP, iar Node a emis spec. Procesul de
teste a avut exit0. Dovezile initiale sunt pastrate; parser separat verifica
hashul outputului,106liniiPASS si sumarul, exit0, fara rerulare sau schimbare
teste. Git read-only al QA a fost blocat de sandbox; owner a verificat Git
escaladat read-only: main...origin/main, multe schimbari preexistente pastrate.

## Modificari si ce ramane

Niciun cod, config, test, dependenta, backend sau UI comercial editat acum.
Adaugate doar raport, task packet, dovezi si checkpointuri de memorie cu backup,
pastrand integral istoricul vechi. Fara commit/push/deploy/Hub/env/date reale.

Deschise: verificare independenta provider/native stop, reboot/headless/update/
no-auto-GPS, traseu in miscare, internet-off/server-sync, baterie fara USB,
deepDoze, kill-process, alte Androiduri/Android36.1/iOS, release magazine.
Etapa2 in_progress, S2-05B/07/08 separate. Aceasta proba nu le inchide.

## Dovezi

TASK_PACKET_RETEST.md; evidence/resume-unlocked-initial.* si toate noile
evidence/retest-* listate in evidence-manifest.json; retest-qa/raport-qa.md,
qa-validated-result.json, stdout/exits/hash-uri originale si physical-review.md.
Nu se copiaza evidenta invalida/veche after-owner-permissions.png.
