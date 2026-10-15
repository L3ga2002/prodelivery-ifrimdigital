# ProDelivery — L1 amendamente aditive propuse

ID: PD-L1-SPEC-ADDITIONS-20261013. Versiune: 1.0-candidate. Aceste blocuri NU au fost inserate în proiectul activ. ROOT deține integrarea, după backup/hashguard și review/QA.

## A. Sarcină obligatorie, ACK tehnic și compatibilitate

Țintă: `.ifrim/SPECIFICATIONS/PD-DISPATCH-01.md`.

Ancoră existentă exactă: `# PD-DISPATCH-01 - specificatie de lucru pentru asignare multipla` (linia 11 la citire). Inserare propusă imediat ÎNAINTE de ancoră, după prependul client din 12 octombrie. Nu se înlocuiește global termenul „refuz”: refuzurile de autorizare/validare/capacitate rămân obligatorii.

Bloc propus:

```markdown
## Amendament de contract Q10 — 13 octombrie 2026

Versiune documentară propusă: PD-DISPATCH-01 v0.4-contract-candidate. Nu este versiune activă de API/DB sau implementare multi. Autoritate comercială: al treilea set de răspunsuri, Q10, `LOOP_REPORTS/2026-10-12-client-operational-rules-third-set.md:20,39`. Acest bloc supersedează numai semantica de acceptare opțională/refuz comercial din corpul istoric v0.3; păstrează restul invariantelor și amendamentele D0/A8.

Orice sarcină alocată valid este obligatorie. Confirmarea livratorului este ACK tehnic de primire; nu reprezintă alegerea de a executa sau refuza comercial. Autentificarea, ownership-ul, versiunile, capacitatea și eligibilitatea rămân verificate. O operație invalidă se respinge tehnic fără efect business; acesta nu este un drept de refuz al sarcinii.

Pentru incrementul viitor separăm două concepte în modelul tehnic propus:

1. Rezervare internă provizorie, înaintea unei sarcini obligatorii comise: consumă un loc rezervat; expirarea poate elibera acel loc numai prin operație atomică/CAS, fără sarcină comisă și fără custodie. Nu este ofertă opțională către driver. Politica și deadline-ul rezervării se fixează în packetul tehnic, fără TTL care șterge dovada.
2. Sarcină obligatorie comisă: `assigned_unacknowledged -> acknowledged -> picked_up -> delivered`, cu identitate și ownership durabile. Numele sunt conceptuale propuse; integrarea stabilește mappingul explicit cu stările legacy. Sarcina ocupă un loc activ din momentul commitului alocării obligatorii. ACK-ul nu creează și nu eliberează loc, nu schimbă proprietarul și nu produce venit sau pickup.

`open_count = reserved_count + active_count <= configured_order_limit` rămâne invariantul comun. Tranziția rezervare internă -> sarcină obligatorie mută reserved -> active în același commit; ACK-ul conservă contoarele. Ordinea de rezervare/commit/ACK și toate proiecțiile trebuie validate într-un singur protocol; nu coexistă două surse de autoritate.

Absența ACK-ului, timeoutul notificării, offline-ul ori pierderea răspunsului NU închid automat sarcina obligatorie comisă, NU eliberează locul și NU reasignează marfa. Starea de neconfirmare și incidentul/escaladarea către operator sunt vizibile. Pragurile și bugetele de retry se declară în packetul tehnic. Notificarea trimisă nu dovedește primirea sau execuția.

GET/replay și confirmarea tehnică a primirii nu autorizează navigarea pe o rută dirty. După ACK, pickup-ul cere în continuare pregătire READY, proprietar curent, versiuni și oprire executabilă. Livrarea fizic efectuată și raportarea incidentului rămân protejate conform regulii de custodie din v0.3; ACK-ul nu este o dovadă fizică.

Nu se implementează ruta/controlul de refuz comercial propus anterior `POST assignments/{id}/refuse`. Un astfel de request nu trebuie să elibereze sarcina/contorul/ruta. Contractul HTTP exact de respingere se fixează în implementare, în acord cu compatibilitatea; nu se inventează aici o rută deja existentă. Ruta accept/confirm, dacă se păstrează numele pentru compatibilitate, este documentată explicit ca ACK tehnic. Un nou nume și aliasul legacy necesită mapping și aceeași identitate semantică.

Reasignarea administrativă rămâne o operație autorizată distinctă, cu guarduri, înainte de pickup și invalidarea ownershipului vechi; nu este refuz comercial mascat. După pickup, nici ACK timeout, nici offline-ul nu transferă custodia. Incidentul și rezoluția fizică explicită rămân necesare.

Cererea de pauză/final de tură nu anulează sarcini. Regula Q11 privind A în curs, B asignată/gata și C gata/neasignată, precum și momentul opririi noilor alocări rămân neclarificate. Nu adoptăm implicit A+B ori A+B+C; fixtures tehnice poartă politica sintetică explicită și nu activează comportamentul comercial.

Corpul istoric de la invariantul 2, invalidarea rutei, stările assignment, API accept/refuse și cursa accept/expire se citește cu aceste amendamente. Cursa tehnică viitoare este rezervare internă/commit/expirare; sarcina comisă/ACK/timeout nu poate folosi expirarea rezervării pentru a elibera obligația. Identitățile, lease/fence, CAS și replay rămân recuperabile.

Compatibilitate: A8 `preparation_status` și pregătirea după asignare sunt păstrate. `current_order_id` rămâne doar proiecție în viitorul multi, nu contor autoritativ. Ledgerul existent `order_operations`, namespace-urile și pending-urile nu sunt rescrise/readmise prin `dispatch_operations`. Un adaptor și o versiune nouă trebuie să dovedească un singur efect logic și recovery pentru intențiile deja admise. Default-disabled și capabilitățile tuturor clienților rămân gate-uri; oprirea admisiilor noi nu abandonează sarcinile existente.

Acceptare de contract pentru viitorul increment: (a) un request de refuz comercial nu eliberează sarcina; (b) actor străin/refuz tehnic are zero writes business; (c) ACK duplicat și ACK pierdut/replay conservă ownership și contoare; (d) timeout/offline păstrează sarcina comisă și o face vizibilă operatorului; (e) două rezervări la ultimul loc au exact un câștigător; (f) expirarea unei rezervări nu poate închide o sarcină deja comisă; (g) reasignarea înainte pickup invalidează ACK-ul actorului vechi; (h) pickup/incident/realocare concurente păstrează custodia; (i) oprirea admisiei păstrează lookup/recovery. Sunt criterii planificate, nu teste executate de acest amendament.

Etapa 7 rămâne neînchisă. A0–A8 sunt loturi restaurant închise local, iar D0 este inventar static; niciunul nu certifică implementarea multi, ruta live sau capacitatea fizică.
```

Ancore istorice de reconciliat la integrarea tehnică, fără ștergerea istoriei: `DISPATCH:37` (accept/expire/refuse), `:65–67` (invalidare/dirty), `:114–116` (stări), `:144–149` (API), `:179` (accept/expire). Amendamentul trebuie citit înaintea lor; validarea actuală a topologiei și a markerelor se face în lotul de implementare, nu se deduce din vechiul `hello`.

## B. Delta D0 după închiderea inventarului

Țintă: `.ifrim/SPECIFICATIONS/2026-10-11-PD-DISPATCH-01-current-addendum.md`.

Ancoră exactă: `## Ce trebuie reconciliat înainte de un increment` (linia 17). Inserare propusă înainte de ancoră:

```markdown
## Clarificare de continuitate — 13 octombrie 2026

D0 este închis ca inventar static conform `LOOP_REPORTS/2026-10-11-stage1-d0-inventory.md`; formulările de mai jos despre ieșirea de produs a lui D0 rămân istoric și nu cer reconstruirea lui. D0 nu este D1 sau probă de implementare 1/2/5/10. Hashurile din tabel sunt cele ale citirii istorice, nu hashurile actuale după prependuri.

La următorul increment se aplică amendamentul Q10 v0.4-contract-candidate din `PD-DISPATCH-01.md`: sarcină obligatorie comisă și ACK tehnic, fără refuz comercial. Timeoutul ACK nu eliberează implicit sarcina. Parametrii Q11 pentru pauză și A/B/C rămân deschiși; compatibilitatea ledgerului, pregătirea A8 și guardurile inventariate rămân baza.

Proba a8c este INCOMPLETE/heartbeat_gap, HONOR restaurat și servicii proprii absente conform începutului actual `NEXT_SESSION.md`; vechile instrucțiuni de baterie/restaurare pending nu se execută din acest addendum. Instrucțiunea curentă de campanie permite loturi independente după epuizarea lucrului disponibil din etapa curentă, cu acceptanțele externe păstrate deschise. Nu certifică etapele 1/2/7 și nu activează telefonul, dispatch-ul, baza reală sau serviciile externe.
```

## C. Contract financiar aditiv pentru următorul increment

Țintă: `.ifrim/SPECIFICATIONS/PD-ORDER-MUTATION-CONTRACTS.md`.

Ancoră exactă: `## Before any activation` (linia 49). Inserare propusă imediat înainte; evităm alterarea contractelor/receipturilor vechi sub aceeași versiune.

```markdown
## Financial contract boundary — client rules received 12 October 2026

The existing command/receipt schemas describe implemented behavior at their documented versions. They are not authority for a 10% driver remuneration policy or for collecting restaurant transport charges from the recipient. The confirmed rules and open decisions are in `LOOP_REPORTS/2026-10-12-client-operational-rules-third-set.md`, read together with the 8/9 October reports and their explicit supersession rules.

The next financial increment must represent separately: product amount, recipient amount still to collect, restaurant transport charge, driver remuneration, driver advance to restaurant, outstanding amount and actual reimbursement/payment. Approval of insufficient cash is not payment; an obligation to reimburse is not reimbursement; a decision to return is not receipt of products. Explicit zero differs from missing/unknown. Prepaid products are not collected again from the recipient.

Tariff configuration is restaurant-specific and versioned; transport and driver remuneration remain separate. Each admitted operation captures the applicable rule snapshot and currency/rounding semantics. New settings do not recalculate historical operations. Unknown tariffs or exception rules block the dependent new calculation; they do not fall back to zero, 10%, or the unnamed 16/26/36 example. Kilometer floor rounding is confirmed; monetary rounding is not established by that answer.

The new financial schema/version must cover models, validation, API serialization, persistence and UI. Adding ignored fields to documents is insufficient. Existing pending operation identity, expected revisions, semantic digest and lookup/replay remain unchanged; no readmission through a second protocol and no silent historical conversion. Activation remains default-disabled until the concrete schema, compatibility, policy and data gates are verified. Synthetic test prices/policies are explicitly labeled and cannot activate live tariffs.

Insufficient-cash payment timing, exception payers/rate bases, second-address supplement semantics and the A/B/C break boundary remain open. Only independent contracts, fixtures and functionality advance until the relevant answer is received. Close-day and factual incident recovery already have local closure evidence; preserve them and extend only demonstrated gaps.
```

Acest bloc nu modifică schema de comandă, formula din produs sau markerii și nu acceptă anticipat schema viitoare. ROOT poate integra blocul ori îl poate transforma într-o specificație financiară separată, păstrând ancorele și versiunile existente. Nu se scrie un amendament în `NEXT_SESSION.md` de către ownerul L1.
