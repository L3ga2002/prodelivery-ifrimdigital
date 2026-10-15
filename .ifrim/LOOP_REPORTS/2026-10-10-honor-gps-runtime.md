# ProDelivery: proba GPS HONOR 600 Lite, 2026-10-10

Verdict: PASS software/packaging si callbackuri vizibile scoped; proba fizica
completa BLOCKED de deblocarea manuala. Recorder oprit in siguranta, date pastrate.
Owner Codex; reviewer Feynman; QA independent Copernicus. Numai subagenti
interni OpenAI, fara OpenClaw/Claude/Hub, abonament extern sau deploy.

## Scope si acord

Instrument separat `ro.ifrimdigital.prodelivery.gpsprobe`, nu aplicatia driver
completa. HONOR LNA-NX1, Android16/API36, USB conectat, telefon de teste.
Catalin a aprobat controlul app-ului si acordarea permisiunilor relevante prin
ADB. Acordul nu implica modificarea altor aplicatii sau a securitatii globale.
Fara PIN/identificator USB in raport, fara coordonate/SQLite exportate.

Etapa comerciala2 ramane in_progress; S2-05B/07/08 si portile production sunt
separate. Nu activam GPS in backend/dispatch, formule financiare sau Etapa3+.
Preview verificat aici este APK-ul embedded pe telefon, nu serverul web.

## Problema reala si remediu

Prima tentativa: localizarea Android oprita, UI `background_unavailable`.
Nu era dovada de incompatibilitate HONOR. Proprietarul a activat localizarea
si permisiunile, dupa care callbackurile GPS au produs crash-uri native.
Stiva scoped: TaskBroadcastReceiver -> LocationTaskConsumer -> TaskManagerUtils
-> JobScheduler. Expo instalat foloseste `setPersisted(true)`; APK0.1.0 nu declara
`RECEIVE_BOOT_COMPLETED`. Android cere aceasta permisiune pentru joburi persistente:
https://developer.android.com/reference/android/app/job/JobInfo.Builder#setPersisted(boolean)

Fix incremental, fara rescriere:
- `tools/mobile-gps-probe/app.json`: permisiunea BOOT, versiune0.1.1/versionCode2.
- `tools/mobile-gps-probe/tests/android-packaging.test.ts`:5regresii de packaging.
Modulele, lockfile-ul si16surse/teste preexistente verificate raman neschimbate.
Backup config: `.ifrim/BACKUPS/2026-10-10-honor-gps-runtime/app.json.before`.

## Verificari software fresh

- Testul nou pe config vechi:3PASS/2FAIL (permisiune absenta, versionCode absent).
- Candidate complet:106PASS/0FAIL/0SKIP; strictTypeScript exit0 in buildroot.
- Sursa reala integrata:106PASS/0FAIL/0SKIP, fara slabirea/stergerea testelor.
- QA independent:5/5config +probe focus sintetice, apoi106/106teste executate pe
  sursa reala, strictTypeScript exit0,22/22hash-uri proiect/buildroot identice
  inainte/dupa.16/16protejat corespunde. Detalii in qa-integrated-verification.md.
- Build nativ final:SUCCESS1m50,184tasks,40executate/144up-to-date.
- APK:036E70306029A52774B00C4ECDF5B52931C6DCAD1971F13ED6E5099B9ED7D0E0,
  33,844,945bytes, diagnostic/debug-signed, arm64, min24/target36.
- Manifest final:BOOT este singura permisiune adaugata, nimic eliminat.
  Aceeasi semnatura; backup false +resurse de excludere; bundle1717124bytes.
  OTA ramane dezactivat; nu reprezinta un binar pregatit pentru magazine.

## Blocaje intalnite si pastrate

Doua builduri FAIL Windows/Ninja260. Junctionul `C:\pdg1009` nu scurta calea
canonica. Cache fizic nou `C:\pd-gps-g2`, copii publice dedicate doar acestei
probe; copia PowerShell lenta a fost oprita strict pe helperul propriu, dupa
identificare, si completata cu Robocopy fara delete/mirror. Originalul pastrat.
Metadatele CMake noi aveau calea scurta, dar `.ninja_deps` vechi o pastra pe cea
lunga. Numai acel fisier generat a fost mutat in backup hash-verificat, in
rootul de build verificat. Frameworkul/C++/SDK-ul nu au fost editate.

Primul checker APK a interpretat gresit `allowBackup=false` ca asteptarea
`=0x0`. Checkerul corectat cere explicit `=false`; APK-ul nu a fost schimbat.
Toate logurile tentativelor sunt pastrate distinct, fara mascarea FAILurilor.

Captura `after-owner-permissions.png` din staging este INVALIDA: launcher dupa
crash. JSON-ul vechi ownedAppOnly a fost fals pozitiv prin mFocusedApp stale.
Exclusa din QA si din proiect. Guard nou: mCurrentFocus package exact +unlocked
inainte/dupa +hash APK +exitstatus ADB +marcare explicita a capturii invalide.
Pre/postguard nu este atomic; fiecare PNG folosit este inspectat vizual.

Update0.1.1 a avut client Success si hash verificat, apoi APK0.1.0 l-a inlocuit
la01:46:48 ora telefonului. Nu era un crash nou. O instalare veche in coada
este o ipoteza, nu cauza demonstrata. Recorder oprit/perms revocate imediat;
3sesiuni proprii erau istorice/aplicate, niciuna activa si niciun client host
propriu ramas. Update reaplicat fara data-clear; clientSuccess si hash nou
revalidate, versiune stabila apoi pe parcursul probei. Play Protect a cerut
verificare optionala: selectat `Nu trimite` exclusiv pentru APK-ul propriu,
fara upload la Google si fara dezactivarea protectiei globale.

## Dovezi fizice pana la ecran-off

- Dupa update, idle: SQLite inchis, niciun serviciu locatie;1sesiune/2evenimente
  istorice pastrate, fara observatie GPS curenta. Interruperea veche este vizibila.
- Precise/coarse/background acordate pentru acest pachet, localizarea global
  activata de proprietar. Fundal ->acord ->Start ->Continua executate explicit.
- Start aproximativ22:56:16UTC: sesiune activa, Start disabled, serviciu listat.
-22:57:30UTC:11evenimente globale/2sesiuni, duplicate0/reject0/late1,
  varsta7s, eligibilitate locala, mostre background/20m precizie raportata.
-22:58:41UTC:19evenimente, varsta10s, background20m, niciun crash nou in exit-info.
- Ecran stins22:58:51UTC; sistem Dozing la22:58:59 si23:00:16, serviciu listat.
  Dozing/AOD nu este certificare OFF total, lock securizat sau deep Doze.

## Sfarsit proba fizica si containment

-23:04:34UTC: Dozing si serviciu listat; circa335s fata de metadatele de inceput.
-23:04:41UTC: ecran trezit, keyguard blocat. Guardul a refuzat captura; nicio
  imagine de lockscreen si niciun PIN folosit. Deblocare manuala ceruta ownerului.
-23:08:45UTC: fara deblocare, proba a fost incheiata prin force-stop al pachetului
  propriu si revocarea celor3permisiuni GPS. Serviciu absent confirmat, date locale
  intacte. Nu este Stop API din UI si nu dovedeste inchiderea gate-ului SQLite.
-23:08:51UTC: hashul final instalat ramane036E...0E0, versiune0.1.1.

Nu s-au comparat contoarele dupa revenire. Ecran-off5min este observat ca interval
Dozing/AOD cu serviciu prezent, NU un PASS al colectarii continue sau al StopUI.
Deblocarea manuala, redeschiderea pentru inchiderea sesiunii intrerupte si o noua
proba autorizata Fundal ->ecran-off ->StopUI/observatie60s sunt pasii ramasi.
Permisiunile trebuie reacordate pentru aceasta noua proba; nu porni tacit GPS.

## Porti care raman separate

Nu certificam fiecare observatie in interval din simpla crestere a contoarelor.
Reboot/update-restoration/no-auto-GPS, traseu in miscare, internet-off, consum
baterie, proces ucis, productie/server-sync, Android36.1, alte telefoane/iOS
raman neverificate. BOOT permite receiverului Expo deja existent sa restaureze
taskuri; UI initialize nu certifica singur toate caile headless de boot/update.
Nu stergem date pentru a ocoli latch-ul conservator Prim-plan.
