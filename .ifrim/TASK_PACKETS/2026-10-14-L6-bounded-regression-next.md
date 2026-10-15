# L6 — blocaj BFCache: fixture incompatibil cu politica livratorului

Data proiectului: 14 octombrie 2026. Verificările finale au fost executate la `2026-10-13T22:20:53.899Z`–`22:21:26.029Z` (14 octombrie în Europe/Bucharest). Scop finit: exclusiv testul istoric BFCache și protecțiile actor/sesiune/lifecycle pe care trebuie să le verifice.

## Concluzie și propunere concretă

Nu este demonstrat un defect de producție în hook/lifecycle pentru cazul investigat. Blocajul are o cauză reproductibilă: fixture-ul istoric folosește un livrator pentru anulare comercială, acțiune respinsă deliberat înainte de POST. Testul așteaptă apoi fără limită callbackul acelui POST imposibil.

Propunere: păstrarea guardului de autorizare și a produsului; clasificarea exactă a testului protejat drept `INCOMPATIBLE_FIXTURE + UNBOUNDED_WAIT`, păstrarea sa nemodificată și non-PASS, și folosirea dovezii noi finite de mai jos pentru semantica BFCache. O eventuală revizie viitoare a suitei protejate trebuie să schimbe actorul pozitiv în restaurantul propriu, răspunsul `/api/auth/me` în același restaurant și așteptarea într-un semnal finit de intrare în POST. Nu este necesară și nu este propusă relaxarea drepturilor livratorului.

Noul harness: **9/9 PASS pe baseline; 9/9 PASS pe candidatul stage**, cu același fișier de test. Aceste rezultate nu schimbă numărul eșecurilor din regresia istorică și nu închid L6 sau etapa comercială 2.

## Cauza exactă, cu traseu prin cod

Referințele de mai jos sunt relative la proiectul ProDelivery, dacă nu este indicat `stage`.

1. `frontend/src/hooks/useOrderStatusRecovery.test.jsx:8` definește actorul implicit `{id:'actor', role:'driver', driver_id:'driver'}`. Testul numit `BFCache preserves exact cancel draft and permanently fences POST from before suspension` începe la linia 175; la linia **178** apelează `result.submit({order, status:'CANCELLED', ...})` și execută `while (!release) await Promise.resolve()`.
2. `frontend/src/lib/orderStatusRecovery.js:71` refuză `driver + CANCELLED`. În candidatul `stage` este linia **73**, după guardul nou de custody. Comanda fixture are `ASSIGNED`, versiune 4, restaurant/livrator valide; refuzul este determinat de rol și status.
3. `validateIntent` aruncă `STATUS_TRANSITION_INVALID` la linia 234 (stage: 236). `submit` apelează această validare înainte de `capability`, `randomUUID`, stocarea draftului și POST (liniile 260–277; stage: +2).
4. `frontend/src/hooks/useRecoveryAction.js:12` așteaptă controllerul; `catch` de la linia 13 publică eroarea și întoarce `null`. `finally` de la linia 14 eliberează busy. Produsul termină operația finit.
5. `release` este atribuit exclusiv în mockul POST de la linia 176; POST nu este apelat. Bucla de la linia 178 reintroduce permanent microtaskuri și nu ajunge la tranziția `pagehide` de la linia 180. Nici timerul Jest nu are ocazia să întrerupă această buclă; testul istoric nu demonstrează un defect BFCache, deoarece nu ajunge la evenimentul BFCache.

Regula de produs este susținută de intake-ul clientului `.ifrim/LOOP_REPORTS/2026-10-12-client-operational-rules-third-set.md:20` și `:39`: orice alocare este obligatorie și refuzul comercial al livratorului nu mai este cerință. Backendul aplică aceeași limită la `backend/utils/order_status.py:213`–`:223`: livratorul propriu este autorizat numai dacă statusul cerut nu este `CANCELLED`; restaurantul propriu poate anula. Testele backend istorice care așteaptă anularea de către livrator nu sunt criteriu pentru relaxarea acestei reguli.

Severitate: **P2, defect al fixture-ului de regresie care blochează finalizarea suitei**, fără defect de produs demonstrat aici. Owner pentru o revizie ulterioară a testului: QA/frontend owner, cu review independent și păstrarea provenienței testului protejat. Nu a fost editat niciun fișier protejat.

## De ce protecția curentă a lifecycle-ului funcționează în scenariul permis

- `useOrderStatusRecovery.js:89`–`:95`: `pagehide` invalidează generația hookului și capabilitatea, suspendă UI și apelează `deactivate({preserveDraft:true})`. `pageshow` persistat cere revalidarea sesiunii.
- `orderStatusRecovery.js:241`–`:257`: `deactivate` crește epochul controllerului și păstrează draftul numai la această suspendare; `restoreSession` verifică prin `/api/auth/me` ID, rol, resource ID și cont activ înainte de reactivare. Epochul vechi nu este restaurat.
- `orderStatusRecovery.js:156`–`:167` și `:151`–`:154`: cererea veche verifică epochul după response/rejection și înainte de `save`. După restaurarea sesiunii, răspunsul vechi tot nu poate modifica receiptul, șterge draftul sau declanșa retry din generația veche.
- `useRecoveryAction.js:12`–`:14`: generația veche întoarce `null`; eroarea veche nu suprascrie starea sesiunii restaurate. Busy este eliberat pentru recuperarea explicită a aceleiași operații.
- `orderStatusRecovery.js:181`–`:205`: după un lookup `404 OPERATION_NOT_FOUND`, recuperarea poate retrimite o singură dată aceeași intenție și același motiv din draft. UUID și versiune sunt păstrate; receiptul terminal valid elimină draftul.

Aceasta blochează efectele locale ale răspunsurilor vechi. Nu afirmă că BFCache anulează sau face rollback unei cereri care a ajuns deja la server; recuperarea aceleiași identități este necesară tocmai pentru această incertitudine.

Schimbarea numai a rolului în test nu este suficientă: stubul global `/api/auth/me` returnează actorul driver. Dacă testul pozitiv montează restaurantul, `/api/auth/me` trebuie să întoarcă același restaurant; altfel `SESSION_CHANGED` este comportamentul corect.

## Harness nou, finit și independent de testul protejat

Fișiere noi, numai în acest director:

- `BFCACHE.bounded.test.jsx` — importă hookul real din baseline sau candidat și simulează exclusiv transportul, storage-ul jsdom și evenimentele `pagehide/pageshow`.
- `run-bounded.cjs` — selectează sursa, folosește dependențele Jest existente în frontendul activ, păstrează stdout/stderr/JSON/hashuri și verifică identitatea fișierelor înainte/după.

Controlul așteptării: semnal explicit la intrarea în mockul POST, cursă contra terminării anticipate a `submit`, **deadline 1.500 ms** pentru fiecare boundary, **6.000 ms** per test, **45.000 ms** proces Jest. Nu există polling sau `while` microtask. Procesul folosește numai un director temporar propriu; nu modifică `.env` sau setări persistente ale sistemului.

Cele nouă cazuri:

| Caz | Criteriu verificat |
| --- | --- |
| Livrator + CANCELLED | `STATUS_TRANSITION_INVALID`, `null`, busy eliberat; zero GET/POST/PUT, zero UUID, storage gol. |
| Restaurant propriu + răspuns POST vechi | Draft exact și metadata păstrate la suspendare/restaurare; late success fără efect; lookup 404 retrimite exact același body/UUID; draft eliminat numai după receipt nou valid. |
| Restaurant propriu + eroare POST veche | Aceleași garanții; eroarea veche nu produce retry automat și nu suprascrie starea restaurată. |
| Livrator + ACCEPTED | Confirmarea tehnică permisă păstrează aceeași identitate la BFCache și recover, fără motiv/draft de anulare. |
| `/auth/me` cu alt account ID | Sesiunea rămâne suspendată, draft/metadata păstrate, acțiuni blocate. |
| `/auth/me` cu alt rol | Aceleași garanții. |
| `/auth/me` cu alt restaurant ID | Aceleași garanții. |
| `/auth/me` cu `is_disabled:true` | Aceleași garanții. |
| `/auth/me` cu `account_disabled:true` | Aceleași garanții. |

Comenzi finite, din acest director:

```powershell
node .\run-bounded.cjs baseline
node .\run-bounded.cjs stage
```

## Dovezi de execuție și identitate

| Sursă | Rezultat nou | Dovezi |
| --- | --- | --- |
| Baseline L4A | 1 suită, 9 PASS, 0 FAIL, 0 skip, exit 0 | `results/baseline/1791930053892/jest.json`, `execution.json`, `stderr.log` |
| Candidat L5B stage | 1 suită, 9 PASS, 0 FAIL, 0 skip, exit 0 | `results/stage/1791930073410/jest.json`, `execution.json`, `stderr.log` |

SHA-256 ale harnessului comun executat:

- `BFCACHE.bounded.test.jsx`: `84777fb38a9e8d627b49e993f2f45871a1fe65dd0f4dba46e61185e482ed23ca`
- `run-bounded.cjs`: `1a22590f77d608882ac2552b8b91ce86403385746718e3c5e3f150e765a096d8`

În fiecare execuție finală, cele **15 înregistrări de hash** (5 fișiere × activ/baseline/stage) sunt identice înainte/după. Aceasta este verificare de identitate pentru aceste fișiere, nu un audit nou al întregului proiect.

| Fișier | SHA-256 activ/baseline/stage |
| --- | --- |
| `hooks/useOrderStatusRecovery.test.jsx` | Toate identice: `5f8940801ae5858f8615288d642e4657a1007a6a7d5adb6862b441e76c73fc94` |
| `hooks/useOrderStatusRecovery.js` | Toate identice: `1c6462cc218128f6ac82501ea3f2bbdf7ebd66123010c17cd4790147af1e4deb` |
| `hooks/useRecoveryAction.js` | Toate identice: `7c0ff580d3560f8aa21afe88066e62d0567cfffa41874ae077169ed6a163b13e` |
| `lib/recoveryTransport.js` | Toate identice: `efd9607569d758e1f5bfc5789881f52502c44ff9a30e384a6350eee0b27826ee` |
| `lib/orderStatusRecovery.js` | Activ/baseline: `d1dc06111a6f1150eed5862e8aabf155eb13c0409b3c1358aeb7c18d759f478a`; stage: `6133e9ad1f727d062a79b62895b97682604dd2b06b2d8ecccaa491835aa1df21` |

Diferența existentă de core între baseline și stage este importul/guardul custody și două coduri custody de respingere. Nu modifică interdicția anulării de către livrator; nu a fost introdusă de acest discovery.

Încercări de setup păstrate separat: `results/{baseline,stage}/execution.json` și directoarele `1791929974499` / `1791929974641` au eșuat înainte de încărcarea testelor cu Node/Jest `EPERM realpath` în sandbox. Primele procese escaladate din `1791930000001` / `1791930021365` au executat zero teste din cauza aliasului `@/` omis în harnessul nou. Aliasul a fost completat numai în runnerul nou. Execuțiile finale de mai sus sunt după această corecție; nu există modificare în produs pentru a obține PASS.

## Limite și recepție L6

Citite pentru autoritate/limite: `.ifrim/LOOP_REPORTS/2026-10-14-l4a-safe-pause.md`, `2026-10-13-campaign-final.md`, intake-ul clientului din 12 octombrie și `frontend-qa/FE2/owner-report.json` din această campanie. Ultimul consemnează afectată 432 PASS/12 FAIL/1 exclus identic baseline/candidat; noua probă nu înlocuiește acele rezultate și nu declară celelalte eșecuri rezolvate. Rezultatele FE3/browser/regresie integrală rămân în proprietatea coordonatorului.

Verificarea de aici este React/Jest/jsdom cu transport simulat; evenimentele BFCache sunt injectate explicit. Nu demonstrează eligibilitatea reală BFCache, înghețarea/relansarea unui browser, cookie-uri reale, comportament HTTP/Mongo sau dispozitive Android/iOS. Aceste probe nu au fost pornite. Nu s-au modificat surse de produs, teste protejate, Git, baze de date, secrete, servicii, deploy sau activări plătite.

Pentru cazul investigat, clasificarea incompatibilității este acum susținută de traseu static și de proba finit negativă/pozitivă pe ambele surse. Testul istoric rămâne exclus explicit și non-PASS, iar L6 și etapa comercială 2 rămân deschise până la verdictul de acceptare completă al coordonatorului.
