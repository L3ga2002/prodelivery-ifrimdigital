# Concurență D, contracte F și pregătire H — 15 octombrie 2026

Loturi delimitate, fără schimbări în codul produsului sau în testele protejate. Baza produsului rămâne cele 322 fișiere ale `2fc239d4bec3b25fa7ea1f566d068bf9b1dfb000`; commitul documentar L6A `b3c6921c1bff58349b621c0cea4d367dde31fec8` este verificat și pe origin privat. E1/E2/L6 general rămân deschise.

## D — HTTP concurent și restart real

Trei probe pe namespace nou, la prima execuție: două cereri cu aceeași identitate de livrare, două identități concurente la aceeași versiune și aceeași identitate de anulare cu două motive diferite. Intervalele HTTP s-au suprapus cu 95,5674 / 67,7295 / 31,8362 ms. Fiecare comandă are un singur efect. Cursa cu identități distincte păstrează legitim două operații (applied/rejected), dar un singur credit, audit și avans de versiune. Nu pretindem o barieră între tranzacțiile Mongo.

După oprirea PID-ului verificat și pornirea unui proces nou cu exact `--reuse-fixture`, patru operații terminale au fost recitite prin GET, după autentificări noi. Starea completă, contorul, sursa și buildul sunt identice; fără POST de reluare sau reseed. D1–D4: PASS; audit independent QA: 58 verificări PASS. Namespace: `pd_l6a_433b01e70b4a4ea3a077b3e1e8dccf5a`, trei comenzi și contor103. API-ul D este oprit; datele sunt păstrate.

Reviewul a oprit harnessul R1 înainte de execuție pentru receipturi, măsurarea suprapunerii și validarea checkpointului. R2 închide aceste lacune; SHA256 runner: `28ca0b606e145e355e164b180c83ed0cc3f3c43e91c7ff39dc8cc430b398e2b8`. Hash checkpoint restart: `823b5b96aa4f2233f00681133384f13ff034ff87c46bce26f8c0f63cf102b6df`. Watchdog extern:300s/90s, execuții încheiate în8,328s/3,317s. Dovada două taburi Brave și schimbarea contului în curs sunt probe separate, neacoperite de acest raport.

## F — contracte financiare pure actuale

Cele două suite întregi existente `test_financial_core.py` și `test_order_exception_policy.py`: **224 PASS**,2,64s în R4. Sursa este fixată înainte/după. HTTP, Mongo și DNS sunt blocate; numai socketpair intern Windows este permis pentru asyncio. Testele verifică sume exacte, snapshot imuabil, bani necunoscuți, lipsa grilei/provenienței și absența unei reguli inventate de rotunjire sau plată. Nu activează L4B/L5C2.

Încercările anterioare rămân păstrate: R1 nu a colectat din cauza unui plugin cerut inutil și absent; R2 are199PASS/25FAIL din blocarea self-pipe de către harness; R3 este TIMEOUT la120,05s, cu17 cazuri terminate, fără rezultat complet. R4 adaugă preflight diagnostic finit și folosește mediul aprobat pentru loopback intern. Nu se schimbă produsul, asyncio sau testele pentru a obține verde. Aceste încercări sunt distincte de cele **9 FAIL protejate** statusRecovery, care rămân FAIL în regresia144=135PASS/9FAIL.

## H — OCR și ingestie

Auditul focalizat confirmă manualul și idempotenta internă actor/operation_id. Nu există încă OCR în draft cu corectare/confirmare umană, inbox durabil sau deduplicare demonstrabilă OCR/API/manual în codul citit. I01/I02 pot avansa independent pe date sintetice; conectorul I03 este blocat de furnizor/documentație/sandbox. Confirmarea umană este obligatorie pentru OCR; politica de import API și statusurile outbound se decid după analiza furnizorului. Etichetele de sursă nu sunt integrare API.

Planurile existente se păstrează. H nu implementează, nu selectează și nu activează furnizori, servicii plătite sau transferuri reale. L4B noile13/14, L5C2 traseu/zone/tarif/rotunjire și probele fizice rămân gate-uri explicite. Niciun defect nou de produs nu a fost demonstrat; C/E nu justifică un patch sau refactor în acest lot.

Dovezi originale în `C:\Users\mihai\OneDrive\Documente\Mutare Proiecte de pe Emergent\pd-l6a-20261015-campaign`: `evidence/d-*`, `evidence/f-pure-*`, `qa/D1-D4-INDEPENDENT-AUDIT.*`, auditurile F și `review/H-ocr-api-audit.*`. Arhiva locală și manifestul cu hashuri sunt în `.ifrim/QA_RUNS/2026-10-15-l6a-campaign/closed-dfh`; fișierele brute nu intră în Git.

Arhivă verificată: 61 artefacte; SHA256 manifest `c8500d858083aa59384826db63144aba3942790ebc1e56f2726fcbf44d5d24f0`.
