# S1 — recuperarea statusului cu autorizare pe rol, închis local

Integrat local și verificat independent după integrare la 2026-10-15T01:07:31.174258+00:00. Etapele comerciale 1 și 2 și acceptarea L6 rămân DESCHISE. F3B și P1 erau deja închise local și sunt păstrate.

## Comportament

Recuperarea după întrerupere verifică rolul și statusul cerut înaintea POST inițial/repetat sau resume: admin cele patru statusuri; livrator ACCEPTED/PICKED_UP/DELIVERED; restaurant CANCELLED. Perechile interzise păstrează ID-ul, metadata, receiptul pending valid și draftul privat al anulării. GET terminal și ACK rămân posibile. Lipsa draftului de anulare păstrează OPERATION_UNCERTAIN; cleanup la terminal/deactivate rămâne valid. Nu se fabrică rezultat financiar ori refuz terminal local.

Scope: orderStatusRecovery.js existent și orderStatusRecoveryRolePolicy.test.js nou. Baseline319,318 surse în afara schimbării,320 în candidat; protecții140 intrări/76 fișiere; integrări precedente F2B12/F3A6/F3B13/P1exact13 intacte. Un backup al sursei vechi și un test nou; arhivă finită 87 probe/2200924 octeți. Publisher cu hashuri și verificări înainte/după fiecare schimbare; nu este tranzacție atomică între cele două fișiere.

## Dovezi și limite

Owner55/55 noi PASS; review Astra47/47; QA independent69/69. Suita protejată89: baseline81PASS/8FAIL, candidat80PASS/9FAIL;89 apariții corespondente și88 statusuri identice. Singura diferență: testul driver/CANCELLED admitted bodyless resume cere o operație nepermisă de rol. Conflictul este ratificat și păstrat FAIL, fără edit/skip/fakeadmin. Cele opt eșecuri istorice rămân FAIL. Acesta nu este verdict de regresie globală verde.

Probe JS/controller cu API/storage sintetice, fără S1 auth/HTTP/Mongo/Brave/build/telefon. GET202 pe pereche interzisă este frontieră adversarială sintetică; serverul nu este afirmat că o admite. Dovezile reale Mongo/Brave/build din P1 sunt anterioare S1 și nu înlocuiesc o nouă acceptare completă. Nu există Git, deploy, serviciu plătit, bani reali ori modificare de setări HONOR în acest lot.

Integrare SHA 3a1d41f8f9dfa9eed243c9d571db02f82bf48b958e193db5fce70164270c491b; post independent SHA 3a1e9527a7a941eeb49c351614478a17a20f65fff6d63dda49e3b109e3b293f5. Rapoarte și raw în .ifrim/QA_RUNS/2026-10-15-s1-status-recovery-authority; copia izolată completă la C:\Users\mihai\OneDrive\Documente\Mutare Proiecte de pe Emergent\pd-status-recovery-authority-20261015-48c35118.

## Restanțe și următorul lot

Etapa1: clarificările comerciale restante și probele fizice Android/iOS/offline/exterior/baterie sunt amânate explicit la urmă. Etapa2: L4B achitări/rambursări efective și autoritatea client13/14 din grila NOUĂ; L5C2 persistența anulării/adresei cu dovezi rutiere autorizate, grilă zona1 și rotunjirea banilor; L6 zi completă și recuperare. Cele18 răspunsuri vechi/Q7 confirmat nu reprezintă răspunsuri la grila nouă.

Următorul lot independent propus: L6A, zi completă cu trei roluri folosind alocarea reală și lifecycle complet, probe fără duplicate după răspuns pierdut/restart și autorizare incidente. Avertismentul403 driver din P1 provine din fixture-ul schimbat manual, fără current_order_id/driver_status delivery; diagnosticul nu dovedește defect de produs. Nu reconstrui A0–A8, D0inventar sau close-day și nu porni proba lungă pe telefon fără defect/schimbare justificată.

Planul L6A detaliat, cu12scenarii finite, este în .ifrim/TASK_PACKETS/2026-10-15-L6A-next.md. Auditul Astra explică gates E1/E2 și limitele de execuție; statusul S1 candidat menționat acolo este supersedat de această integrare și dovada post. L6A nu a fost executat. Nu are nevoie de reguli comerciale noi pentru verificarea contractelor deja existente.

Ultima cotă citită pentru acest checkpoint: 13% disponibil. Păstrăm rezerva aproximativ10%; starea este reluabilă. Preview-ul vechi57881 nu este revendicat drept sursă finală. Nu sunt pornite runtime-uri noi de S1; cele proprii P1/Brave au fost închise anterior, Mongo comun27953/datele sintetice păstrate.
