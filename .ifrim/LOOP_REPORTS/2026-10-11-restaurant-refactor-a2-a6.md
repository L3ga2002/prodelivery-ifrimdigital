# ProDelivery — refactor restaurant A0–A6, milestone închis

Data: 11 octombrie 2026, Europe/Bucharest. Continuare autorizată de utilizator; toate funcționalitățile clientului trebuie păstrate.

Transportul comun, parserul pur de pregătire, executorul unei singure acțiuni, cardul/dialogurile și citirile restaurantului sunt integrate și au review independent plus QA. Pagina RestaurantApp a scăzut de la 933 la 578 de linii, prin separarea responsabilităților; nu au fost eliminate câmpuri, butoane sau fluxuri. Inventarul independent acoperă 17 suprafețe și 62 expresii de identificare a controalelor. Detaliile și hashurile finale sunt în `QA_RUNS/2026-10-11-restaurant-refactor-b5efe45ce9a5/a2-a6-closed-v2/manifest.json`.

Backup înainte:226 fișiere. Integritatea istorică verificată înainte:294 legături sursă/dovezi. Precizare de numărare: manifestul numit anterior «140 fișiere protejate» conține140 înregistrări pentru76 căi unice, toate intacte. Hashurile istorice ale surselor refactorizate descriu versiunea anterioară; manifestul acestui lot descrie versiunea curentă.

Verificări independente: recuperare frontend221 PASS/5 eșecuri istorice/1 skip istoric; restaurant104 PASS/2 eșecuri istorice. Toate numele, stările și mesajele eșecurilor sunt identice înainte/după. Backend172 cazuri pure și56 cazuri cu Mongo sintetic PASS. Build0 erori/0 avertismente. Browser cu autentificare reală8/8 grupuri și supliment restaurant6/6, inclusiv șapte zile de program, toate șase opțiuni de pregătire, istoric/căutare/detaliu, ambele comenzi legate, analytics, anulare, close-day/incident recovery, BFCache și offline. Capturi stabile1440/390 inspectate; fără overflow orizontal sau pageErrors.

Eșecurile istorice rămân:3 așteptări editing fără headerul obligatoriu actor;2 teste de anulare de către driver refuzată de contract;2 teste de self-pause ale restaurantului înlocuită de controlul dispeceratului. Un test BFCache vechi de anulare driver este exclus explicit deoarece nu cedează controlul. Nu declarăm întreaga suită globală verde și nu modificăm testele pentru a o face verde.

Runtime-urile browser27945/57270/57271 sunt închise, cu date/dovezi păstrate. Nicio bază reală, secret, telefon, activare producție, commit, push sau deploy. Runtime BE sintetic27941 este încă deținut de QA pentru lotul separat A8; identitatea curentă trebuie reverificată la reluare.

Continuare: A8 pregătire/READY are contract separat în `TASK_PACKETS/2026-10-11-preparation-recovery-b5efe45ce9a5.md`. Codul este încă staged în launcher; nu confunda testele staged cu integrarea sau acceptarea lui. După review, integrare și QA actual-auth se închide A7 pentru sesiunea completă. iOS, bateria fizică nereușită și răspunsurile clientului își păstrează limitele documentate; iOS și clientul rămân la final.
