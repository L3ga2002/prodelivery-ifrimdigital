# Demonstrație pregătită; pauză pentru tur, 14 octombrie 2026

Utilizatorul a cerut oprirea dezvoltării când demonstrația este pregătită, pentru a urmări simultan administratorul, restaurantul și livratorul pe ecranul ultrawide. Aceasta are prioritate față de continuarea campaniei până la rezerva cotei. Resetarea a fost verificată; observația ulterioară este 3% utilizat / 97% disponibil, istorică la acest checkpoint.

## Demonstrație deschisă

Campanie izolată: `C:/Users/mihai/OneDrive/Documente/Mutare Proiecte de pe Emergent/pd-demo-20261014-7df921a3`.

Trei ferestre Chromium headed separate, cu autentificare efectivă prin interfață și sesiuni independente:

- `pd-demo-20261014`: administrator, `s12-admin1@example.invalid`, `/admin`, fereastra stângă.
- `pd-demo-restaurant-20261014`: restaurant, `s12-restaurant1@example.invalid`, `/restaurant`, fereastra centrală.
- `pd-demo-driver-20261014`: livrator, `s12-driver1@example.invalid`, `/driver`, fereastra dreaptă.

Parola exclusiv sintetică: `Synthetic-Stage12-QA-only-20261010!`. URL local comun `http://127.0.0.1:57881`; conturile rămân separate deoarece ferestrele folosesc contexte de browser distincte. Trei taburi în același context nu păstrează trei utilizatori diferiți.

Comanda `S.0101`, ID `c67bebf7-8ca3-5e13-9200-4f9b2030ac7e`, este NEW, nealocată. Creată prin serviciul real recuperabil OrderCreationService în DB sintetică, nu prin scriere directă a comenzii. Nu au fost pregătite/asignate/acceptate/ridicate/livrate artificial etapele ulterioare. Conturile, restaurantul, zona și grila sunt date sintetice. Valorile 52,50 lei produse, 23 lei transport și 14,37 lei remunerație sunt numai date demonstrative, fără validitate comercială.

Verificat efectiv: login la cele trei roluri, afișarea aceleiași comenzi NEW la admin/restaurant, livrator fără comandă. Capturi inspectate vizual în `browser/output/playwright/*-ready.png`; snapshoturi în `browser/.playwright-cli`. Nu se declară un nou PASS pentru ciclul complet al comenzii: acesta urmează în tur. Consola conține refuzuri CSP/endpointuri auxiliare indisponibile în harness; nu se pretinde zero erori sau configurație de producție completă.

Buildul este copia exactă a FE6 verificat anterior; 117 intrări și sursa activă au fost comparate înainte de pregătire. Backendul este copia finită a sursei active. Nu s-a făcut build nou și nu se substituie QA istoric cu afirmații noi.

## Runtime-uri păstrate pentru tur

Mongo izolat 27953 / replica-set `pd_demo_20261014`, DB `pd_demo_browser_b456bb2d384e486da33bcb8f1d53899e`, date păstrate sub campania demonstrației. Manifest `runtime/runtime-state.json`, verificare prin `runtime/runtime.py`. Proxy ASGI/static exclusiv loopback 57881; manifestele `browser/proxy-process-*.json`, fixture `browser/fixture-b456bb2d384e486da33bcb8f1d53899e.json`. Sunt intenționat active pentru utilizator. Verifică întotdeauna identitatea, sursa, DB path și manifestul actual; nu reutiliza PID-uri din rapoarte.

Pentru oprire după tur: închide numai cele trei sesiuni CLI nominalizate, apoi `python -B browser/control.py stop proxy`, apoi `python -B runtime/runtime.py stop`, folosind Pythonul proiectului. Helperii validează proprietatea înainte de oprire. Nu închide ferestre, servicii sau DB-uri străine. În caz de reluare după shutdown, runtime-ul trebuie verificat/pornit controlat; proxy-ul suportă `--reuse-fixture` numai cu proprietate și sursă exactă. Nu repeta seed_demo.py: o singură comandă este deja creată și scriptul respinge repetarea.

## Dezvoltare suspendată

L5C1 este numai draft neintegrat în `C:/Users/mihai/OneDrive/Documente/Mutare Proiecte de pe Emergent/pd-l5c1-20261014-83bc01ed/stage`. Modele/evaluator/teste noi; teste/importuri neexecutate, review final și QA pending. Advisory separat în `contract-review/CONTRACT.md`; status reviewer în `review/STATUS.md`; checkpoint implementator în `implementation/`. Nu publica draftul ca lot terminat și nu integra înainte de review/QA. Sursa activă a produsului nu a fost schimbată prin acest draft.

Etapele comerciale 1/2 rămân DESCHISE. L5B operațional integrat rămâne checkpointul software anterior. Fără telefon, Git writes, deploy, servicii plătite, date reale sau modificare a memoriei globale.

Pasul următor este turul: explicarea rolurilor, pregătire restaurant → READY → alocare manuală administrator → confirmare livrator → ridicare → livrare; apoi istoricul și evidențele financiare. Rulează mutațiile numai după reluarea turului de către utilizator. După tur și reluarea dezvoltării, continuă draftul L5C1 cu review/QA, apoi lotul independent următor; nu continua în această pauză consumul cotei.
