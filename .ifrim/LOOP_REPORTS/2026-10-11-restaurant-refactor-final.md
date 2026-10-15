# ProDelivery — refactor restaurant A0–A8 închis local

Data: 11 octombrie 2026. Autorizare: «incepe», cu păstrarea tuturor funcționalităților cerute de client. A7 reprezintă review-ul, QA și handoff-ul final pentru A0–A6 și sublotul funcțional A8.

Codul duplicat de transport, parserul de pregătire și executarea unei singure acțiuni au fost extrase. Cardul, cele șase dialoguri și citirile restaurantului sunt componente separate. RestaurantApp are acum 618 linii față de 933 înainte, inclusiv integrarea noului panou de recuperare. Inventarul de paritate acoperă 17 suprafețe; programul pe șapte zile, cele șase durate, listele, detaliile, istoricul, căutarea, ambele tipuri de comandă legată, analytics, anularea și fluxul până la livrare sunt păstrate.

Pregătirea și READY au identitate durabilă comună, rezultat original verificabil și recuperare explicită după răspuns pierdut. O încercare de 5 minute nu atribuie succesul altei încercări de 15 minute. Montarea, reload, reconectarea și revenirea din BFCache fac numai citiri; retrimiterea și continuarea necesită acțiune explicită. Confirmarea rezultatului păstrează blocajul până la recitirea comenzii actuale. Schimbările de actor, token, restaurant, rol, dezactivare și suspendarea paginii invalidează publicarea întârziată. Backendul păstrează atomic comanda, istoricul/auditul și rezultatul operației; comenzile legacy nu sunt promovate automat la o revizie nouă.

Noua admitere este implicit dezactivată prin markerul `order-preparation-v1`. A fost activată numai în fixture-ul QA sintetic. La valoarea verificată false rămâne fluxul legacy; indisponibilitatea sau o operație incertă nu declanșează fallback. Operațiile deja admise rămân recuperabile după dezactivarea admisiei. Această închidere este implementare și validare locală, fără activare sau lansare în producție.

## Verificare și limite

- A8 pe sursa integrată: 96/96 teste frontend și 123/123 teste backend PASS; build 0 erori și 0 avertismente, cu 106 surse.
- Browser cu autentificare reală și date sintetice: 8/8 grupuri A8, 8/8 grupuri de regresie existente și 6/6 grupuri de păstrare a funcțiilor restaurantului. Sunt acoperite desktop 1440 și mobil 390, fără erori de pagină. Capturile și hashurile bundle-ului servit sunt în dovezile QA.
- Regresia protejată restaurant, rulată brut, este 96 PASS / 10 FAIL: mockul Axios dintr-o suită veche nu are factory-ul create, iar cele zece cazuri se opresc la mount. Rezultatul brut este păstrat. Un adaptor numai în harness completează factory-ul lipsă, fără schimbarea testelor/aserțiunilor, fără răspuns capability inventat și fără fallback în produs. Cu adaptorul, toate cele 106 nume, stări și mesaje sunt identice cu baseline-ul A6: 104 PASS / 2 FAIL istorice. Nu declarăm rularea brută neschimbată sau întreaga suită globală verde.
- Cele două eșecuri istorice restaurant cer self-pause, în timp ce contractul actual lasă controlul dispeceratului. Milestone-ul A2–A6 păstrează separat 221 PASS / 5 FAIL istorice / 1 SKIP pentru recuperările anterioare, plus 172 cazuri backend pure și 56 cu Mongo PASS. Aceste rezultate sunt dovezi ale loturilor respective, nu rerulări globale A8.
- Review independent pe cele 14 fișiere A8 și cele 27 fișiere schimbate în total. Toate constatările aplicabile au fost închise. Manifestul final leagă sursa, testele, review-ul și QA; sursele existente în afara listei permise nu s-au schimbat.
- Backup inițial: 226 fișiere; backupuri incrementale înainte de A8. Manifestul istoric de protecție are 140 înregistrări pentru 76 căi unice, toate păstrate. Istoricul proiectului și probele nereușite sunt conservate.

Runtime-urile QA proprii sunt oprite după verificarea identității proceselor; datele și dovezile lor sunt păstrate. Nicio bază a clientului, secret, telefon sau configurație de producție nu a fost modificată. Nu s-au făcut commit, push sau deploy. Browserul sintetic nu certifică telefonul fizic, Safari, iOS sau acceptarea comercială.

## Reluare

Manifest curent: `QA_RUNS/2026-10-11-restaurant-refactor-b5efe45ce9a5/a8-closed/manifest.json`. Milestone-ul A2–A6 rămâne istoric verificat; pentru hashurile actuale folosește manifestul final. Nu reface loturile închise și nu porni dev-start pe baza reală. Comenzile, adaptoarele QA și rezultatele brute sunt arhivate în directorul evidence; căile originale sunt păstrate în manifest pentru reluarea locală.

Următorul lot din backlog este D0: contractul dispatch și inventarul consumatorilor current_order_id, înainte de implementarea sarcinilor multiple. D1–D4, OCR și furnizorii externi nu au fost începuți în acest packet. iOS și răspunsurile financiare ale clientului rămân la final. Bateria fizică fără USB rămâne INCOMPLETE conform raportului Android existent; această sesiune nu a repetat proba și nu îi schimbă verdictul.
