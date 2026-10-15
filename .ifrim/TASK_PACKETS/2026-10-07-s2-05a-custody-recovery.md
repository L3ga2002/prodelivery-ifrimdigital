# ProDelivery S2-05A - Custodie si anulare recuperabile

2026-10-07. Etapa2 in_progress. Catalin a cerut planul de inchidere si executia.
Continuare din S2-04, nu reconstructie. Planul complet ramane stage2-closure-plan.

## Scope
- Acceptare/ridicare/livrare si anulare pre-pickup versionate cu intentie durabila.
- Tranzactie unica orderCAS, resursa driver, contori delivery/earnings, audit si receipt.
- Roluri/owner verificati pe contul real; header comparativ nu este credential.
- UI actual admin/restaurant/driver cu pending, disabled, recovery, error si refresh sigur.
- Fara anulare simpla dupa pickup: refuz explicit pana la incident/resolutie S2-05B.
- Formula existenta total_amount * 0.1 pastrata; nicio politica financiara inventata.

## Routing si siguranta
Owner backend: Codex. Owner frontend: Euler (subagent intern).
Teste backend independente: Galileo. Review independent: agent separat read-only.
QA: Mongo izolat27941, HTTP/roluri sintetice, browser si regresie sursa integrata.
Fara OpenClaw/Claude/Hub mutations, live DB/env/secrets/index/migration/Git/deploy.
Lock scope: backend/order_status si routers numai Codex; frontend3pages numai Euler;
teste noi numai Galileo. Actual root read-only pana la integrare guardata.
Snapshot original: original-manifest.json. Backup in proiect numai la integrare,
fiecare hash original verificat inaintea scrierii. Fara revert la dirty changes.

## Acceptare
- Double click/concurenta nu dubleaza statusul, eliberarea sau veniturile.
- Pickup necesita READY si driverclaim corelat; tranzitii sarite/straine refuzate.
- Cancel elibereaza numai propria rezervare; postpickup necesita incident.
- SameID lookup/resume/replay dupa restart/ACKlost/reload/disablemarker.
- Partialwrite/driver/audit/ledger failure rollback; finite retries/deadline.
- Nicio promovare legacy, fallback din incertitudine sau log PII.
- Independent review + regression + desktop/mobile browser pe date sintetice.

## Nu este finalizat de acest sublot
S2-05B incident/refacere, S2-06 liste/detaliu/istoric, S2-07/08 regresie totala si
gate live de backup/restore/migrare/retentie/activare. Minimum10/auto si Etapa3+
raman scope separat. Nu declara Etapa2 complete din acest lot.
