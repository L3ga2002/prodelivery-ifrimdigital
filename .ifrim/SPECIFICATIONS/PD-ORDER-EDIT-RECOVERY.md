# PD-ORDER-EDIT-RECOVERY

S2-03,2026-10-07. Contract aditiv implementat, default-disabled; nu live activation.

## Transport

- GET `/api/orders/operations/edit/capabilities`: admin curent,
  `{edit_recovery_enabled:boolean}`; separat de capability create existenta.
- POST `/api/orders/operations/edit/{order_id}`: strict `EditOrderCommand`:
  `client_operation_id`, `expected_order_version`, `changes` explicit presente.
- GET `/api/orders/operations/edit/{order_id}/{client_operation_id}`: read-only.
- POST acelasi path + `/resume`: fara body; numai intentie deja admisa.
- 200 applied/replayed cu id si revizie istorica n+1;202 pending cu Retry-After;
  404/409 business receipt rejected stabil;422 request invalid privat;
  401/403 auth;503 configuratie/DB/ledger indisponibil. No-store peste tot in router.

## Invarianti

Adminul trebuie sa existe si sa fie enabled la fiecare actiune; rolul curent este
verificat iar scrierea fence in aceeasi tranzactie serializeaza schimbarea lui.
Comanda: revizie business scalar int/Int64 in interval, exact expected, increment
fara overflow; numai NEW/PREPARING/READY neasignate, fara custodie/anulare.
Missing revision este legacy, nu0. Receiptul create0 nu activeaza o revizie.

Fields allowlist: customer_name,customer_phone,customer_address,notes,
customer_latitude/customer_longitude ca pereche. Adresa schimbata nu retine GPS
vechi prin retrimiterea aceleiasi perechi. Fara recalculare financiara implicita.
Intention identity actor/edit/clientID; digest leaga target+expected+patch explicit,
inclusiv distinctia omitted/null. Admission digest leaga tenantul server-side si
envelope-ul; nu reprezinta criptare/protectie impotriva accesului privilegiat DB.

Admitere ledger majority, apoi tranzactie snapshot pentru patch/revizie/audituri/
outcome. Nicio modificare counter/driver/status/tarif. CAS comuna S2-COMPAT.
Retries finite; commit unknown se reia pe aceeasi tranzactie, nu dubleaza efectul.
Cancellation nu inseamna ca workerul Motor s-a oprit: worker -> abort -> end.
GET nu scrie; resume poate recupera dupa disable, nu admite o intentie noua.
Business rejection stabil; ledger corupt503 fara reparare automata sau efecte.

## UI Si Activare

Admin details Eye -> corectii; formular separat, fara redesign. Web Lock + mutex,
storage before send, timeout15s, max3 recovery reads, sameID fara fallback legacy.
PII numai draft temporar sessionStorage/memorie; metadata durabila privata fara
valori client. Rejected pastreaza draft; noua incercare cere refresh explicit si
rebase numai campuri editate. Receipt successful curata payloadul si in alte taburi
prin storage event validat; acknowledge identitate necesita Web Lock.

Nu provisiona markerul `order-edit-v1`. Activarea asteapta assign/status v2,
migrare/excludere/restore, retention payload si aprobarea politicii adresa/tarif.
Probe native/GPS, cache PWA si productie reale raman separate. Vezi raportul
`LOOP_REPORTS/2026-10-07-s2-03-operational-corrections.md` pentru dovezi/limite.
