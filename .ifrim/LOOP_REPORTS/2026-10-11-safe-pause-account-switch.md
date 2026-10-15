# ProDelivery — pauză sigură pentru schimbarea profilului

Stare: **PAUSED la cererea explicită a utilizatorului.** Nicio probă și niciun agent nu trebuie relansate înainte de mesajul «reia» / «reia ProDelivery». Acest handoff are prioritate față de vechea notă despre workerul de baterie încă activ.

Proiect: `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`.
Launcherul cu helper-ele și dovezile originale: `C:\Users\mihai\OneDrive\Documente\Mutare Proiecte de pe Emergent`.
Schimbarea contului nu este executată de agent. Reluarea se bazează pe fișierele locale și bootstrapul proiectului, fără să presupună că istoricul chatului va fi disponibil noului cont.

## Siguranța verificată înainte de pauză

ROOT a executat o singură inspecție finită, cu GO static independent pentru helperul `stage12-phone-safe-pause-inspect.py`, SHA `8822507B644EA454A865884B305F6379799A680DFC0BA8C1AF7A4542CB4D94C5`.
Dovada: `stage12-phone-safe-pause-8f5daf42ecaf4d899df3ae0b3570fced.json`, SHA `FC4C9EBEE496A0FD1034F7E13959EBB7203179978D258F9EBB4E18C893C0FC43`.
Observată la **2026-10-10 23:46:27 UTC / 11 octombrie 02:46:27 București** pe același HONOR LNA-NX1 / Android 16, probe `ro.ifrimdigital.prodelivery.gpsprobe`, vc3:

- Serviciul propriu absent, cu header și toate ServiceRecord-urile complete; sesiune UI închisă, recorder inactiv, SQLite închis în UI.
- Contoare păstrate: 171 evenimente mixte / 5 sesiuni; duplicate/respinse/tardive 0/0/4. Nu sunt exportate coordonate sau baza de date.
- Wi-Fi 1 / date mobile 0; proprietățile ADB TCP/TLS dezactivate, ADB Wi-Fi dezactivat și listenerul temporar 48273 absent.
- PID-urile originale ale celor trei workers exact cunoscuți sunt absente. Toate sesiunile host ale probelor executate au returnat exit; nicio probă V4 inspect/run nu a fost executată.
- Nu s-au lansat GPS, worker sau Stop și nu s-au schimbat radiourile în această inspecție. Rămân numai fișiere temporare inerte, cu cleanup exact amânat; nu sunt șterse datele aplicației.

Aceasta este dovada finit observată la pauză, nu certificarea tuturor probelor fizice. La reluare verifică proaspăt identitatea/starea telefonului înainte de orice acțiune.

## Ce este terminat și ce rămâne deschis

Software-ul lotului Etapelor 1/2 este închis în scope-ul raportului `LOOP_REPORTS/2026-10-10-stage12-independent-closure.md`. Manifestul `QA_RUNS/2026-10-10-stage12-closure/closure-manifest.json` are SHA `2C02D15A8937017579FD2B9E560833279363AA4B1B2D0B688F6647F261150236`; 294 legături sursă/dovezi și 140 fișiere protejate sunt reverificate înainte/după salvarea pauzei. Există eșecuri nominale FE/BE documentate; nu declara full suites all-green. Nu relua loturile închise.

**Stop fizic normal: PASS în criteriul finit.** Update compatibil vc2→vc3, fără uninstall/clear-data. Home≈88 s, Stop normal, serviciu absent la 0/30/60/90 s; fereastră măsurată 93,078 s fără modificarea contoarelor după închidere. Redeschiderea proprie Home→launch a păstrat local 171/5. Nu extinde acest verdict la baterie, GPS continuu, server-sync, reboot sau alte dispozitive.

**Baterie fără încărcător: INCOMPLETE.** La răspunsul «gata» de reconectare, colecția 43b a avut doar 4 evenimente: inițial, așteptare și două observații fără alimentare separate de 2.090 ms. Fără gate20 s, idle900 s, Start, fundal900 s, Stop sau result.json. PID13646 este absent; cauza dispariției nu este demonstrată. Nu cere din nou scoaterea USB pentru aceeași metodă care nu a rezistat.

Auditorul `stage12-phone-data-audit-battery-43b.json`, SHA `0C2736A60B7768FF1555FCE823F900454209D096AF077E8C8F1EBD8E75894BA4`, și reviewerul independent confirmă INCOMPLETE. Colectare: `stage12-phone-ondevice-evidence/43b67567160a446d93f54f3f64625a82/collected-20261010T225708Z-0f3ff902`. Datele originale sunt păstrate. Cleanup-ul exact al celor 8 fișiere din taskul 43b este deja executat, exit0 în `stage12-phone-cleanup-battery-result.json`; directorul43b absent. Nu relansa vechiul worker și nu repeta acest cleanup.

**Offline manual: neconfirmat.** Utilizatorul a spus explicit «Nu pot confirma toate condițiile» privind cele2 minute fără internet și încărcător.
**USB V3: INCOMPLETE înainte de Start.** Task `a82f2f469f054364ac6dc6a4e2c8e0f6`, run SHA `D8FAC2CF7BE870E69FB87B16DDDB64A7F4E28F6E98DAB1A79B9CD3E75072BF6E`: criteriul zero agenți nu a fost atins, niciun Start, radiouri restaurate1/0. Păstrează istoricul, fără reinterpretare retroactivă ca PASS.

Diagnosticele au observat no-default și un agent CELLULAR/IMS; nu au găsit tokenul INTERNET în whitelist, dar aceasta nu este dovada parserului pozitiv V4. V4 este o probă nouă declarată, cu criteriul `NO_DEFAULT_AND_NO_DECLARED_INTERNET_CAPABILITY`, USB alimentat real/ecran Awake, 13 observații la10 s/span≥120000 ms și Stop normal plus stabilitate90 s. IMS este permis; nu certifică zero packets/toate transporturile, GPS continuu sau bateria. **V4 nu a accesat telefonul și are HOLD de review.**

## Primul lucru la reluare: P2 parser, fără ADB

Nu executa V4 până nu este închis acest finding independent. Freeze actual:

| Fișier launcher | SHA256 actual | Stare |
| --- | --- | --- |
| stage12-phone-usb-offline-network-v4.py | A30BB668C3AC6400908DA245BAD013A495C88E105E8502554B1BA06A27D999B5 | HOLD P2 |
| stage12-phone-usb-offline-run-v4.py | E474E57B22070E19661989E42E3E004D475B2DCF74FF03EE4861E81D04F4EA6D | ServiceRecord P2 închis; dependent de parser |
| stage12-phone-usb-offline-check-v4.py | 34542F4401D569F49348541D73DBD5BD80C4541C95E0A80D2CD06898709E51B6 | 85 controale sintetice PASS ROOT pe acest freeze, zero ADB |
| stage12-phone-usb-offline-final-check-v4.py | 85A0673C2A97106EE965FF313B71D738714BC51BF82000B72FE3E7065FF3964F | Parser binding de reînnoit după fix |
| stage12-phone-cleanup-v4.py | 0B89E856FF0C9A64F276124D8A6A4841C2DDB8CC5CCF7AD861AE2BF6E4F1D96B | Logică GO, bindings HOLD |
| stage12-phone-cleanup-check-v4.py | 3CF1B2224CE0DCE81DD363E0844172ADED98498A13043E1BF1EE5A096A8C6F57 | Owner26 sintetice PASS; ROOT sandbox resolve a dat PermissionError |

Finding: liniile102–105 parser, regex `:\s*` pe masca în care quotes/nested sunt înlocuite cu spații poate sări peste valoare și accepta fals IMS. Contraexemplu exact:

```text
nc{[ Transports: CELLULAR Capabilities: "INTERNET" IMS Specifier: bogus ]}
```

Fix minim propus: marker direct numai până la `:`, apoi whitespace consumat din original; refuză valoare quoted/nested. Adaugă negative quoted/nested + IMS ulterior pentru Capabilities și Transports. Păstrează suportul pentru Specifier legitim nested. Nu relaxa criteriul și nu atinge app source/protected tests.

Păstrează actualii bytes ca o nouă copie pre-review înainte de editare. Cele patru copii preliminare `*-v4-pre-review.py`, cleanup `*-prereview-6813.py`, `*-prereview-0B89.py` și checker `*-prereview-3CF1.py` sunt deja păstrate. Nu le suprascrie. Rebind runner/checks/final checker/cleanup/materializer la noile SHA, rulează controls locale și obține GO independent pe bytes finali. Eroarea ROOT26controls este restricția Windows pathlib.resolve în sandbox, nu motiv să schimbi guardurile; rerulează escalated **local-only, zero ADB**.

## Succesiunea rămasă după «reia»

1. Citește bootstrapul, `.ifrim/AGENTS.md`, acest handoff și `NEXT_SESSION.md`; verifică Git status. Rutare Codex-only conform instrucțiunii active; fără OpenClaw/Claude/Hub/AI plătit. Folosește agenți Codex pentru helper/review/QA; ROOT singurul operator ADB. Agenții vechi sunt opriți.
2. Închide P2 și toate bindings, apoi independent GO; nu porni alte loturi de software înainte de încheierea/persistarea lotului fizic curent.
3. Verifică proaspăt același telefon autorizat USB. CLI după GO: `python stage12-phone-usb-offline-run-v4.py inspect`, apoi `run <exact-new-inspect.json>` doar dacă inspection_supported=true și bytes identici. Nu relansa un run existent; folosește jurnalele exclusiv nou create. Nicio operație ADB concurentă cu run. Durata finisată a probei≈4–6 minute. Timeout/query/gap negative opresc proba.
4. La orice eșec citește jurnalul: normal Stop numai dacă sesiune activă/pending, apoi radiouri originale1/0 restaurate. Nu force-stop/revoke/kill/clear-data și nu declara PASS din cleanup. Verifică direct prin finalchecker V4 cu `inspect <run.json> --reviewed-runner-sha256 <newSHA>`; fișier final cu nonce nou. Reviewer verifică separat runul real și scrie JSON sanitizat nou cu `run_SHA256`, `final_check_SHA256`, `finite_run_supported`.
5. Cleanup exact numai după dovada ROOT proaspătă≤300 s și host sessions ended: două prototipuri inerte +126e V2inspect+a82 V3run+noua sarcină V4 (5 directoare exacte). În V4 rămâne doar ui.awk; V2/V3 au ui+connectivity. Inspect→manifestSHA review→run individual rm/rmdir numai pe fișiere proprii hash/stat-verificate. Unknown/symlink/hardlink/late file/PID reutilizat/serviciu necunoscut refuză fără kill/recursive delete. 43b este deja curățat. Helperul original4DB și V3/F1 sunt înghețate.
6. Materializează report/summary/notes/prefix doar din actualrun+freshfinal+actualcleanup+review. `stage12-phone-materialize-final.py` SHA actual `B71DCFB7CA33227E92B4E4061EBBED5A72544B685F50574B7FBDE7041D2D6B77` are încă bindingsE474/A30B; reînnoiește și dă delta review. Contoarele171/5 de la începutul raportului trebuie etichetate istorice dacă noua probă le schimbă. Battery rămâne INCOMPLETE. Dacă cleanup refuză, adaptează adevărat pending în raport; nu forța sau falsifica completion.
7. Configurare allowlist locală → audit fără `--require-completed` pentru bateria43b → review final → review_approved=true numai după GO → Git status proaspăt → publisher → verifier. Configul actual este **review_approved=false și stale**; raportul/summary/prefix local sunt drafturi nepublicate și au câmpuri cleanup pending. Nu le considera raport final. Adaugă toate copiile pre-review, prooful de pauză și reviewul actual în allowlist explicită. Publisher trebuie să păstreze întregul istoric al celor4 checkpointuri, inclusiv noul prefix de pauză.
8. După lotul fizic, planul Astra se află deja în `.ifrim/TASK_PACKETS/2026-10-11-astra-refactor-restaurant-dispatch-plan.md`, SHA `B1FE75AD9F49A86791F86A9BC8995C2D3CD91D45CD8F0E6B11C3057ABB271515`. DRAFT, plan mare8–12 h cu loturi mici și review. Ordine A0 baseline nou, A1 contract restaurant, A2 transport, A3 parsere backend; apoi A8 READY recovery dacă e cea mai utilă schimbare vizibilă, altfel A4/A5/A6; dispatch D0–D4 până la10. Nu implementezi întregul plan prin simpla reluare a probei. iOS fizic (fără Mac) și răspunsurile financiare ale clientului rămân ultimele; nu inventa reguli și nu repeta întrebările deja date.

## Limite și păstrare

ADB exact: `C:\Users\mihai\AppData\Local\Android\Sdk\platform-tools\adb.exe`; PowerShell `login:false`, acțiunile efective telefon/proiect necesită `require_escalated`. Nu publica fișiere `private`, route/config identity, serial/IP/PIN, rawGPS/rawSQLite sau dumpsys. Fișierele private originale de identificare rămân numai în launcher; arhiva de pauză nu le copiază. Dacă lipsesc, nu reconstitui identitatea din presupuneri.

Nicio construcție nativă, modificare app source, deploy, commit/push, API/Mongo/browser runtime, scanare rețea, ADB serverkill/globaldisconnect/root/reboot/reinstalare/clear-data, simulare baterie, setări globale de GPS sau schimbare timeout. Nu lansa workers autonomi fără USB în această metodă.

Arhiva `.ifrim/QA_RUNS/2026-10-11-phone-safe-pause-<token>` are copia acestui handoff, dovezi sanitizate, helper-e și `pause-manifest.json` cu hashuri reale. Backupul întregului NEXT_SESSION anterior este salvat separat; prefixul de pauză este adăugat fără ștergerea istoriei. Nicio automatizare de reluare nu este creată. După răspunsul final de pauză nu continua până la instrucțiunea utilizatorului.
