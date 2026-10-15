# PD-ORDER-REVISION-COMPAT

2026-10-07. Inventar source verificat, nu activare/migrare.
Boundary: fiecare writer modifica prin aceeasi revizie/CAS sau refuza explicit
documentul versionat. Lipsa campului este distincta de orice valoare prezenta.
Receiptul create nu este revizie business. Nu introducem camp in modelul legacy.

## Cele 13 site-uri de scriere

| Fisier/linie la snapshot | Operatie | Protectie si efecte |
| --- | --- | --- |
| routers/orders.py:492 | create legacy insert | Doc nou legacy; fara revizie business; numerotare/audit legacy raman necertificate pentru lostACK |
| routers/orders.py:582 | assign find_one_and_update | Refuz orice prezenta revizie inainte de claim driver; CAS legacy si reread guard; driver si order raman multi-document legacy |
| routers/orders.py:641 | status find_one_and_update | Refuz revizie inainte de efecte si no-op; CAS legacy; cleanup/delivery totals separate, viitor S2-04/05 |
| routers/orders.py:738 | problem child insert | Parent versionat refuzat inainte de numerotare/insert; copil nou legacy; viitor S2-05 pentru atomicitatea parent/child |
| routers/orders.py:740 | problem parent update | ID plus absenta reviziei; matched0 ->409; nu garantam rollback copil legacy |
| routers/orders.py:800 | preparing find_one_and_update | Validare stricta, snapshot tenant/status/driver/preparation/revision, audit embedded, inc1 versionat; missing ramane missing |
| routers/orders.py:861 | ready find_one_and_update | Acelasi protocol atomic; duplicate/reread valideaza revizia; inc si audit numai la efect real |
| routers/drivers.py:611 | hard-delete history update_many | Ruta default-deny; fixture izolat are preflight scope(driver) + final exists:false; dezactivarea nu scrie orders |
| routers/seed.py:121 | demo-order insert | Helper default-deny; preflight version presence; doc nou legacy numai harness autorizat |
| routers/seed.py:182 | demo-map delete | Default-deny; preflight; ID list AND version absent |
| routers/seed.py:187 | demo-map insert | Default-deny; preflight; doc nou legacy |
| routers/seed.py:218 | collection reset delete | Default-deny; preflight orice version presence; order delete numai exists:false |
| utils/order_creation.py:541 | recoverable create insert | Intentie/order/counter/audit/outcome transactional; document nou fara business revision; marker live neinspectat/neprovisionat |

Nu exista ruta generica order edit/delete in snapshot. Auditul global, driver
counter/assignment si restaurant availability sunt efecte adiacente, nu alti
writeri ascunsi ai documentului order. Orice writer nou trebuie adaugat aici.

## Semantica revision helper

- Missing: `$exists:False`, nicio migrare implicita.
- Valid scalar BSON int/long, strict in Python: `int`/`bson.Int64`, 0..2^63-1.
- CAS: egalitate AND tip int/long AND excluziune array. Query `$type` singur poate
  selecta elemente de array, deci nu reprezinta validare scalar.
- Update detached; numai $set/$inc/$push/$unset; modificarea directa a reviziei
  prin caller este refuzata. Incrementul apartine protocolului.
- MAX este citibil dar efectul care necesita increment este refuzat409.
- Invalid/malformed:409, nu coerciune/zero inventat/500 DB.
- Un alt writer care schimba revizia intre citire si commit produce conflict,
  nu overwrite. Vechiul body UI nu devine validare a intentiei stale de client.

## Ce nu garanteaza acest contract

CAS single-document nu transforma legacy multi-document in tranzactie si nu
repara crash windows financiare/custodie. Nicio tranzitie online legacy->v2,
backfill, exclusivitate de migrare sau lock global nu este implementat aici.
Niciun startup/endpoint nu acorda permisul de fixture. Default-deny mentenanta
ramane pana la implementarea controlului sigur separat. Activare v2 interzisa
fara dry-run/reconciliere/restore/excludere/aprobare distincta.

Dovezi: LOOP_REPORTS/2026-10-07-s2-compat.md si QA_RUNS/2026-10-07-s2-compat.
