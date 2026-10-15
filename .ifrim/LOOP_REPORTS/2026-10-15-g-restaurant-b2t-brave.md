# Restaurant G, două taburi și schimbare cont în Brave — 15 octombrie 2026

Codul produsului și testele protejate rămân identice cu baza de 322 fișiere `2fc239d4bec3b25fa7ea1f566d068bf9b1dfb000`. Se folosește exclusiv executabilul Brave verificat, buildul înghețat și API-ul local cu autentificare/routere reale, pe namespace-uri sintetice distincte.

## G — fluxurile restaurantului

În namespace-ul `pd_l6a_04579e99eecf46419e97a34bf45750b7`, clickurile reale în Brave au verificat pregătirea cu estimare de 15 minute și READY, anularea cu motiv obligatoriu, aprobarea declarației de avans neplătit, raportarea unui incident, refacerea cu cotație și confirmare explicită, anularea copilului și închiderea zilei. Acțiunile admin/curier de setup și livrare au fost efectuate prin API și sunt delimitate de clickurile restaurantului.

Reconciliere finală: trei comenzi, contor 103; una DELIVERED și două CANCELLED, un singur copil legat de părinte, un incident, trei evenimente L4A, zero evenimente de custodie, un singur credit curier de 10,37 lei și claim eliberat. Snapshoturile financiare inițiale sunt păstrate. Închiderea zilei persistă. Auditul QA independent are 40 verificări PASS; acesta confirmă efectele cumulate, fără a transforma fiecare execuție a harnessului în PASS.

Trei eșecuri de harness sunt păstrate: URL relativ invalid înainte de mutație; așteptare greșită200 pentru crearea refacerii care a răspuns corect201; capturarea corpului răspunsului după navigare. Refacerea, anularea și close-day deja aplicate nu au fost repetate. Continuarea și citirile separate au reconciliat efectele. Captura inițială a detaliului mobil era în animație; captura stabilă ulterioară este cea utilizabilă. Captura desktop a pregătirii nu arată integral timerul aflat mai jos în pagină.

Cele patru verificări lipsă sunt acoperite cumulativ de suplimentul separat: ACK local al incidentului, GET istoric după trimitere, ACK local close-day și GET dedicat al receiptului close-day. Namespace-ul `pd_l6a_dd9ba07bef74427a8ae1c77d886f4223` conține exact o comandă NEW/v1, contor 101, un incident și o închidere de zi; fără curier, livrări, credite sau evenimente financiare/custodie. Comanda rămâne activă, accepting_orders=true/pause_until=null și proiecția UI rămân după reload. Nu s-a creat o a doua comandă pentru a proba o nouă admisie.

Suplimentul R1 a comis incidentul și s-a oprit înainte de ACK: harnessul citea localStorage, deși hookul folosește sessionStorage. Review-ul static a ratat adaptorul; omisiunea este documentată. R2 continuă strict receiptul existent, fără al doilea incident: patru subprobe PASS, cu singura mutație nouă PATCH close-day. Durata totală măsurată de watchdog este 4,319s, iar proba raportează 3,072s. Ambele ACK elimină doar cheile sessionStorage potrivite; starea serverului rămâne exactă. GET close-day este o citire HTTP autentificată în contextul Brave, nu un click pe un buton inexistent. Istoricul incidentului este verificat în DOM în spatele modalului, fără afirmație de captură neacoperită. Audit independent: 41 verificări PASS; cele trei FAIL G și FAIL-ul GS R1 rămân păstrate.

API-ul și sesiunea Brave ale acestui namespace sunt oprite verificat; datele sintetice sunt păstrate.

## B2T — recuperare în două taburi

Namespace separat `pd_l6a_ed3b8886f11e4a73b42fe63dc5786422`, o comandă pregătită prin API până la PICKED_UP/v5, contor 101. Proba folosește două pagini reale în același context Brave și Web Locks real. Metadata pending este o fixture client explicită, fără receipt; nu dovedește o pierdere anterioară de răspuns.

Prima execuție a eșuat înainte de crearea tabului B, metadata sau mutații: validatorul de nume de dovezi respingea extensia lowercase `.json`. CLI exit0 nu a fost considerat PASS. R2 corectează exclusiv whitelistul de fișiere; primul FAIL și template-ul R1 rămân păstrate.

Prima regenerare offline a fost refuzată de egalitatea strictă a stării: PowerShell reserializase46 timestampuri UTC în ora locală, inclusiv o fracțiune cu zerouri finale eliminate. Citirile HTTP brute coincid exact cu baza. Regeneratorul și oracolul au rămas neschimbate; comanda nu a fost recreată. O verificare intermediară a reviewerului a semnalat diferența LF/CRLF; comparația finală confirmă exact substituțiile template-ului și serializarea Windows, fără alte schimbări.

R2 runtime: **PASS pentru exclusivitate și efect unic**. Watchdogul de 90s măsoară 7,757s total, iar proba raportează 6,591s. GET-ul real de recuperare al tabului A a fost ținut 1165ms, timp în care tabul B a afișat BUSY și nu a trimis cereri către operația de status țintă; B a trimis GET pentru capabilități. După eliberare,404 OPERATION_NOT_FOUND a fost urmat de exact un POST al produsului,200. Ambele taburi au afișat același receipt terminal. Final: DELIVERED/v6, contor 101, o singură operație nouă, un audit nou și un credit de 1037 bani; claim eliberat, snapshot financiar și datele neafectate păstrate. Niciun resume POST sau PUT legacy. Scriptul R2 executat are SHA256 `d749a008051e6ace4cacd202c829c3f7f07636b3a07a1caedcefca9efc2089da`.

**Defect vizibil separat:** tabul B păstrează mesajul BUSY „Statusul este procesat in alt tab.” alături de „Status confirmat.” și butonul ACK. Captura terminală îl arată explicit; oracolul de exclusivitate nu cerea dispariția acestui mesaj. Nu declarăm interfața complet corectă. Diagnosticul și o eventuală corecție focalizată C sunt un lot separat. API-ul B2T și ambele taburi sunt închise verificat, cu datele păstrate.

Auditul independent QA B2T are 33 verificări PASS pentru date/efect unic, iar reviewerul 32; ambele păstrează explicit defectul UX. Regresia nouă externă pentru C reproduce problema:21 cazuri, 15 PASS și 6 FAIL așteptate pe sursa veche. Nu s-au schimbat teste pentru a elimina aceste eșecuri.

## AS — răspuns întârziat după schimbarea contului

Namespace separat `pd_l6a_83e207cf5843495eb2be9e7ebfb82a59`: setup prin API real creează o singură comandă DELIVERED/v6 și operația terminală autentică. Fixture-ul client pending are receipt null și referă această identitate reală; nu pretinde pierderea efectivă a unui ACK.

În Brave, login A și logout/login B au folosit UI. CDP a suspendat unicul răspuns real 200/no-store al lui A la stadiul Response și l-a eliberat cu `Fetch.continueResponse({requestId})`, fără înlocuirea corpului, statusului sau headerelor. Body-ul și requestfinished au fost observate după login B. Rezultat runtime: **PASS — răspuns autentic întârziat ignorat de controllerul retras**; zero mutații de status, zero ACK vechi, metadata A byte-identică, scope B absent, stare completă și contor identice. Watchdogul măsoară 3,658s total, iar proba raportează 2,470s. Nu este doar dovadă de anulare a cererii.

Review-ul AS R1 a oprit execuția pentru clasificarea expirării timerului după anulare; R2 corectează cele două puncte și păstrează R1. Captura AS-04 a apărut aproape neagră la inspecția root și nu este folosită drept dovadă vizuală stabilă. Citirea UI și captura suplimentară AS-05-B-STABLE, fără reluarea fluxului, arată contul B fără panoul/ACK-ul/comanda lui A, cu zero livrări și0,00. API-ul și Brave AS sunt oprite verificat, datele păstrate.

Audit independent AS: **28/28 verificări PASS**, 21 artefacte fixate prin hash. QA confirmă starea completă neschimbată până la oprire și exclude AS-04 din dovada vizuală. Raport: `qa/AS-R2-INDEPENDENT-FINAL-AUDIT.md` și `.json`.

## Limite

Aceste probe nu închid E1/E2/L6 general și nu schimbă cele 9 FAIL protejate statusRecovery, autoritățile L4B/noile13–14, gate-urile L5C2 traseu/zone/tarif/rotunjire, furnizorii sau probele fizice. Nu demonstrează BFCache, PWA, telefon, GPS, baterie, producție ori plăți reale. Restricțiile CSP ale mediului QA blochează intenționat fonturi externe și Posthog; erorile401 înainte de login și404 de recuperare sunt clasificate separat. Nu există afirmație de consolă fără erori.

Dovezile originale sunt în `C:\Users\mihai\OneDrive\Documente\Mutare Proiecte de pe Emergent\pd-l6a-20261015-campaign`, sub `evidence/g-*`, `evidence/b2t-*`, `evidence/account-switch-*`, `qa/G-*`, `qa/AS-*`, `review/two-tabs-*`, `review/account-switch-*` și `implementation/d-preparation`. Handofful C și cele 21 teste externe sunt în `implementation/c-busy`; candidatul nu este aplicat, construit sau verificat în Brave. Rezerva de cotă impune continuarea C într-un lot ulterior.

Arhivă finală verificată: `.ifrim/QA_RUNS/2026-10-15-l6a-campaign/closed-g-b2t`, 252 artefacte; SHA256 manifest `440c34bcbd473c643f2172f730a49b34d937484c34e903cae456ca0c52f80a88`. Sursa322 și cele76 căi unice protejate sunt neschimbate. Arhiva include handofful C, fără patch aplicat.
