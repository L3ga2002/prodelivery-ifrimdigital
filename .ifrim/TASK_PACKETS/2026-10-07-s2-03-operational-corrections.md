# S2-03 - Corectii operationale: urmatorul lot aprobat

2026-10-07. Plan de executie intern, NU implementare sau activare live.
Depinde de S2-COMPAT scoped PASS integrat. Etapa2 ramane in_progress.
Sursa comerciala: EXECUTION_PLAN_2026-09-26.md, backlog extins 2026-10-07.
S2-01, S2-02 backend/UI si S2-COMPAT NU se refac de la zero.

## Scope si rutare

Codex owner backend; owner frontend separat numai dupa API stabil; reviewer
backend/data independent; QA cu teste disjuncte. Numai Codex/subagenti interni,
fara OpenClaw/Claude/Hub mutation. S2-03A service sintetic, apoi transport
default-disabled, apoi S2-03B UI. Nu cerem reaprobarea lucrului intern.
Fara date reale/index/topologie/marker/env/commit/push/deploy.

## Primul sublot: API/domain sigur

1. Refoloseste `EditOrderCommand`, serializer present-fields, MutationIntent,
   fingerprint si MutationResult din models/order_mutation.py; modele protejate.
2. Nou `utils/order_editing.py`: actor admin curent revalidat din users, order
   versionat strict, neasignat NEW/PREPARING/READY, fara dovezi de pickup.
   ASSIGNED/ACCEPTED/pickup/terminal/date inconsistente sunt refuzate initial.
3. Revizia trebuie sa EXISTE si sa egaleze expected_order_version; missing ->
   ORDER_VERSION_REQUIRED, niciodata promovare lazy/zero inventat. Creatiile
   actuale raman legacy business, chiar daca receiptul spune version0.
4. Patch doar nume/telefon/adresa/coordonate pereche/notes explicit prezente.
   Nu status/restaurant/sursa/produse/plata/taxe. Schimbarea adresei cu coordonate
   vechi necesita pereche noua sau ambele null; no-op stabil -> NO_CHANGES.
5. Foloseste order_operations, `_id=edit:` plus hash identitate actor/edit/ID;
   targetul este in digest, nu in identitate. Persisted command, actor/target,
   restaurant legat server-side, versiune/digest/stare sunt revalidate integral.
6. Admitere pending majority/primary. Aceeasi cheie cu alte date/target/versiune
   ->409; business rejection admisa devine rezultat terminal stabil.
7. Tranzactie: actor authority fence + patch CAS + increment1 + embedded audit
   + audit critic + ledger result. Fara driver/counter/repricing. Receiptul edit
   contine n+1 real, replay acel receipt istoric, nu snapshotul actual.
8. Refoloseste lifecycle testat worker -> abort -> end, finit10s/3 body/3 commit
   attempts. Extragere minima `utils/order_operation_runtime.py` numai daca
   elimina duplicarea reala; nu framework nou si nu rewrite order_creation.py.
   Wrapper-ele/constantele existente si testele protejate isi pastreaza semantica.
9. Unknown commit retry aceeasi tranzactie; cancellation/timeout nu resping o
   operatie incerta. Motor workers observati si sesiunea nu este folosita
   concurent dupa cancellation. Lookup/resume pentru intentii deja admise.

## Transport ulterior

- POST /api/orders/operations/edit/{order_id}, body EditOrderCommand.
- GET /edit/{order_id}/{client_operation_id}, actor-bound read-only.
- POST aceeasi cale + /resume, fara body, numai intentie existenta.
- 200 applied/replayed, 202 pending + Retry-After, 409/404 rejection business,
  503 unavailable. Target nepotrivit la lookup/resume ->404.
- PrivateOperationRoute/no-store si validarea stricta a receipturilor refolosite.
- Marker separat propus order-edit-v1, default-disabled, fara provisioning.
  Create capability nu autorizeaza edit. Disable opreste admiterea, nu lookup/
  recovery pentru intentii existente. Nu kill switch instantaneu.

## Audit si confidentialitate

Audit cu actor/rol/order/operation/request/changed-field-names/revizii/timp server.
Fara valori before/after de telefon/adresa/coordonate/nume/notes in audit/logs/
erori. Ledger pending are PII necesar recovery; acces restrans si retention gate.
Nu TTL care sterge identitatea si permite reaplicarea. UI nu trimite patch la
client/driver extern pana nu exista regula operationala aprobata.

## UI dupa stabilizarea protocolului

Formular conservator pe order detail, fara redesign. Intentie actor/target-scoped,
expected version real de la GET, ID stabil, double-click protection, loading,
draft pastrat la409, reload/recovery, fara fallback legacy sau ID nou la timeout.
GET404 dupa submit incert nu dovedeste esecul. Refresh esuat dupa commit este
distinct de mutatie esuata. Browser desktop/mobile/valid-invalid/adjacent flows.

## Acceptare si dovezi

Teste noi independente: omission/null, address-coordinate coupling, role change/
disable, legacy/malformed/MAX, doi admini, edit versus prepare/ready, v2 fences,
rollback la audit failure, admission/commit ACK lost, cancellation fiecare faza,
restart, corrupt ledger, foreign target/actor, disable with pending, PII absence.
Mongo real separat pentru CAS/commit/recovery, HTTP pentru transport, frontend
unit/integration si browser pentru UI. Reruleaza create/recovery protejate dupa
orice extragere runtime. Build/lint nu inchid singure S2-03.

## Decizii de confirmat numai inainte de extindere/activare

- Destinatie schimbata: tariful/zonele initiale pastrate versus repricing; nu
  modificam tacit regula financiara. Testarea interna nu autorizeaza politica live.
- Editari dupa asignare/acceptare si notificarea driverului; dupa pickup incident.
- Retentie PII, adoptarea reviziei pe date existente, excludere de migrare/restore
  si activare live. Acestea sunt gate-uri distincte, nu motiv sa oprim codul intern.

Pachet derivat din analiza read-only independenta Darwin dupa S2-COMPAT.
Nu exista inca OrderEditingService, ruta edit activa sau formular corectie prin
acest document. Urmatoarea sesiune incepe cu contractele/lifecycle existente,
task packet disjunct si testele RED, nu cu rescrierea aplicatiei.
