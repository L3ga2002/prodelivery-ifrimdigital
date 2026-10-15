# S2-05B - Incidente si refaceri partiale

Plan intern de continuare, nu implementare si nu activare. Etapa2 in_progress.
Prerechizit: S2-05A integrat cu review independent si regresie pe sursa actuala.

## De ce urmeaza

Ruta legacy /orders/{id}/problem creeaza separat refacerea si flag-ul pe original.
Pentru o comanda versionata refuza explicit; nu eliminam acest refuz inainte de
protocolul tranzactional. Noul status S2-05A refuza anularea simpla dupa pickup.
Aceste limite nu sunt indeplinite de acceptare/ridicare/livrare recuperabile.

## Lucrari si invarianti

1. Inventar strict al datelor ProblemOrderCreate/Order, cheilor de legatura,
   writerilor si citirilor existente. Cazuri DELIVERED/produs lipsa/produs nou,
   original strain, followup existent, restaurant in pauza/inchis, date invalide.
2. Comanda stricta actor-bound cu expected_order_version si client_operation_id.
   Niciun patch arbitrar, schimbare de restaurant, plata sau stare a originalului.
3. O tranzactie: fence actor/restaurant, CAS original, un followup legat,
   numar unic de comanda, audit embedded/global si receipt durabil. Dublu-click,
   timeout, ACKlost si retry cu acelasi ID nu creeaza a doua refacere.
4. Originalul DELIVERED ramane livrat. Nu il resetam la NEW si nu acordam a doua
   oara creditul lui, nu rescriem suma/clientul/produsele sau istoricul lui.
5. Pret/quantity cu validari stricte. Pastram formula legacy subtotal=price*quantity,
   delivery_fee=0 si total=subtotal pentru followup, fara debit/credit nou inventat.
   Identificam separat cazul produsului lipsa gratuit; orice regula noua de
   compensatie/incasare/taxa se confirma explicit inainte de activare.
6. Incident dupa pickup: raportare separata de mutarea custodiei. Marfa/driverclaim
   nu dispar prin CANCELLED. Rezolutiile care transfera marfa sau bani au contract
   explicit si criteriu operational, nu un buton administrativ de bypass.
7. Lookup/resume/bodyless recuperabile, finitudine, validare receipts, pending
   versus terminal, proprietar actual pentru pending; marker separat default-deny.
8. UI existent restaurant/admin conectat incremental: motiv/produs/cantitate/pret,
   loading/disabled, intentie stabila, erori clare, recovery/reload si refresh fenced.
9. Review backend/frontend/security dupa risc; owner separat de reviewer. QA Mongo
   izolat si browser admin/restaurant/driver, inclusiv fluxul followup pana la livrare.

## Dovezi obligatorii

- Concurenta doi operatori/aceeasi comanda, numar unic, duplicate si rollback
  la fiecare limita order/followup/counter/audit/ledger.
- React: doua taburi, offline, cookie/account switch, reload, bad API receipts,
  acces strain, callback GET vechi si fallback legacy interzis pentru versiuni.
- Refacere gratuita si produs nou, fara recalcul retroactiv; evenimente si
  raportare separate pentru original/refacere. Nu certificam o politica neaprobata.
- Desktop/mobil, formulare valide/invalide, vecinatati pregatire/alocare/custodie.

## Siguranta si ce NU include

Codex + subagenti interni numai. Fara OpenClaw/Claude/Hub mutations, date reale,
markeri/index/migrari/env/secrets/Git/deploy. Backup/hashguard la integrare.
Nu implementam automat minimum10, OCR/API, GPS/native sau Etapa3+ in acest lot.
S2-06 paginare/liste/detaliu/istoric si S2-07/08 whole-day acceptance urmeaza dupa.
Activarea reala ramane gate separat: excludere scriitori, reconciliere, retentie,
backup/restore demonstrat si aprobare punctuala. Planul nu declara Etapa2 inchisa.
