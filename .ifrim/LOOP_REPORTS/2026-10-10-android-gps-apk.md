# ProDelivery: APK de proba GPS instalat pe HONOR

Data locala: 2026-10-10. Coordonare Codex, implementer/reviewer/QA OpenAI
separati. Fara OpenClaw, Claude, servicii platite sau publicare.

## Rezultat si limite

Instrumentul separat `ro.ifrimdigital.prodelivery.gpsprobe` este instalat si
porneste pe HONOR 600 Lite, model LNA-NX1, Android16/API36, arm64-v8a.
NU este aplicatia completa a livratorului. NU comunica cu backendul, nu modifica
comenzi si nu certifica etapa comerciala curenta sau GPS-ul de productie.

APK instalat verificat prin `pm path` si `sha256sum`, identic cu candidatul:
`C9EFFFD782B5FF0EC31E235F350C4724E186838F8906C752B9829F571B8E42FD`.
33,844,909bytes; diagnostic debuggable/debug-signed, numai test local autorizat.
Nu distribui in magazine sau productie. Bundle embedded1,717,124bytes,
SHA256 `752BC7126438445293C4AFC4B6FCE81AC7FD8C954FF6CC7BA3048B95B857828B`.

## Verificari efective pe telefon

| Scenariu | Rezultat observat |
| --- | --- |
| Deschidere dupa instalare | Ecranul propriu se afiseaza, fara eroare vizibila |
| Consimtamant implicit | Oprit; Start dezactivat, nicio cerere GPS |
| Selectare Fundal | Modul se schimba, fara colectare sau permisiuni cerute |
| Apasare Start dezactivat | Nu deschide sesiune si nu solicita permisiuni |
| Stop repetat in idle | Stare inchisa, fara eroare sau sesiune noua |
| Derulare pana la detalii | Texte lizibile, fara overlap observat; evenimente0/1000, sesiuni0/100 |
| Redeschidere proces propriu | Consimtamant oprit, Prim-plan implicit, Start disabled; fara auto-GPS |
| Runtime permissions | Fine/coarse/background granted=false in fiecare verificare |
| Serviciu location al pachetului | Nu este listat in dumpul scoped; nu este certificare hardware universala |

Capturile contin numai instrumentul propriu de pe telefonul deblocat. Nu s-au
citit coordonate, baze de date sau fisiere personale de pe telefon. Consent/Start
nu au fost activate. Setari/permisiuni, GPS/background/route/battery/offline si
server replay raman NEVERIFICATE. Lipsa unei observatii nu demonstreaza un bug.
Stop idle nu echivaleaza cu verificarea Stop dupa tracking real.

QA UI independent: PASS scoped idle/unconsented. Cele4perechi captura/JSON
au fost inspectate separat; fara blocker. Note minore: `unknown` nelocalizat,
Stop rosu disponibil in idle, accesibilitate nemasurata. QA a verificat dovezile,
nu a executat interactiunile sau tracking pe telefon. Vezi DEVICE-UI-QA-REPORT.md.

## Instalare: istoric pastrat, fara succes inventat

Prima comanda ADB streaming a ramas fara raspuns final; clientul local precis
identificat a fost oprit. Reincercarea non-streaming a transferat33,844,909bytes
in1.482s,21.8MB/s, dar nici acest client nu a returnat succes final. Catalin a
confirmat personal instalarea pe telefon. Pachetul a aparut instalat, iar hash-ul
binarei si pornirea activitatii au fost verificate independent. Al doilea client
local a fost inchis separat dupa acele dovezi. Nu declara `adb install: Success`.
Serverul ADB si aplicatiile nelegate de test nu au fost oprite. Nu s-au acordat
permisiuni cu `-g`, nu s-au sters date si nu s-a inlocuit o aplicatie existenta.

Parserul ferestrei active necesita `dumpsys window`, nu subcomanda `windows`
pe acest Android16. Prima captura a fost refuzata, fara imagine de alta aplicatie;
parserul de verificare a fost corectat, fara modificarea APK-ului.

## Teste si review

| Verificare | Rezultat |
| --- | --- |
| TypeScript strict, candidat final | PASS exit0 |
| Teste recorder, candidat si sursa integrata |101PASS,0FAIL,0SKIP; rerularile nu se aduna |
| Teste originale protejate |58incluse in101, neschimbate |
| Regresii watchdog noi |43incluse in101 |
| Reproducer independent latch/read/late cleanup |8/8PASS, coldStarts=0 |
| QA R2 sursa nativa |60PASS,8SKIP,0FAIL; rezultat separat de APK |
| QA R2 config plugins |24PASS,0FAIL |
| QA APK compilat, bounded gate |20PASS,0FAIL,3SKIP; limitele in raportul QA |

Rerularea initiala pe sursa integrata in sandbox:99PASS,2FAIL exclusiv EPERM la
crearea fixture-urilor SQLite `.tmp`. Rerularea autorizata in acelasi folder:
101PASS; niciun test sau validator nu a fost schimbat. Logul TAP este pastrat.
Cele4regresii de fault durabil au fost RED inainte de fix si sunt documentate.
Review independent a aprobat numai instalarea locala, nu productie/magazine.

## Fisiere modificate si motiv

Toate se afla in `tools/mobile-gps-probe`; frontendul/backendul principal intacte.

| Fisier | Motiv |
| --- | --- |
| App.tsx | Diagnostic explicit pending/unconfirmed, fallback Stop bounded |
| src/controller.ts | Watchdog nativ15s, race/cancel/late cleanup si fault durabil pastrat |
| tests/watchdog.test.ts |43regresii de storage, permission prompts si cleanup |
| app.json | Registreaza pluginurile locale, identitate si flux permisiuni pastrate |
| plugins/android-backup-protection.cjs | Excluderi explicite legacy/cloud/Android D2D |
| plugins/android-diagnostic-build.cjs | Bundle embedded, dev support off si ABI Release compatibil |
| INSTALL_AND_TEST.md | Procedura manuala de acord, colectare si verificare Stop |
| NATIVE_BUILD_2026-10-10.md | SDK, builduri, hashuri, review, avertismente si limite |

Backup22fisiere originale in `.ifrim/BACKUPS/2026-10-10-gps-native-apk`;
6fisiere sursa integrate,19originale din afara delta verificate identice.
Rapoarte/dovezi/APK in `.ifrim/QA_RUNS/2026-10-10-native-probe`, fara date GPS.
Checkpoint NEXT_SESSION aditiv, cu backup si hash guard; istoria pastrata integral.

## Riscuri ramase si urmatorul pas

1. GPS real, ecran blocat, deplasare, lipsa internet si baterie nu au fost testate.
   Proprietarul selecteaza Fundal, consimte la stocarea locala, apasa Start si
   aproba personal permisiunile. Datele sunt SQLite plaintext, numai pe telefon.
   Transferul lor catre laptop necesita acord separat. Fara clienti/date reale.
2. API acknowledge nu certifica oprirea hardware. Contractul conservator
   Prim-plan ramane: intent/shutdown neconfirmat poate bloca restartul. Nu reseta
   datele/reinstala pentru ocolirea barierei; foloseste controalele Android.
3. Incremental Windows rebuild/path-length nu este certificat. Junctionul
   are0referinte prefab scurte/70lungi; buildul final reusit nu este fix universal.
4. Transfer Android36.1/iOS si backup/restore fizic nu sunt certificate. Nu se
   inventeaza Apple teamId. Excluderile XML nu garanteaza orice comportament OEM.
5. Alti Android/iPhone, aplicatia completa driver, GPS server, alocarea10comenzi,
   OCR/API/stores/load raman in etapele lor. Etapa2/S2-05B ramane deschisa.
6. Preview web3000/login si API8000/api/ erau oprite la health check; nu au fost
   necesare/pornite pentru recorderul nativ offline. Nu s-au schimbat env, Hub,
   baze de date client, markeri, Git, deploy sau date de productie.

## Corectii de cerinte, fara activare financiara

Catalin a corectat intake-ul anterior:16/26/36RON pentru TOATE restaurantele;
configurarea zonelor/hartii/tarifelor exista deja; km se rotunjesc si nu exista
limita maxima de distanta. Metoda rotunjirii, plata driverului, cash insuficient
si decontarea unor refuzuri/retururi raman deschise. Istoricul09oct este pastrat,
dar aceasta corectie ulterioara are prioritate. Nicio formula noua nu s-a activat.
