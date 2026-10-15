## Clarificări client primite la 12 octombrie 2026

Cele 11 răspunsuri din al treilea set sunt integrate în `LOOP_REPORTS/2026-10-12-client-operational-rules-third-set.md`. Numerotarea acestui set este distinctă de cele două chestionare anterioare. Q7/Q8 retrag întrebările; decontările și închiderea zilei se păstrează. Q10 stabilește alocări obligatorii, fără drept de refuz comercial; confirmările tehnice și refuzurile pentru autorizare, capacitate ori date invalide rămân necesare.

Intake-ul documentar este închis după verificări independente de consistență și impact. Grilele și excepțiile financiare, plus exemplul pauzei A/B/C, rămân de completat. Reguli salvate nu înseamnă funcții implementate. Etapele 1 și 2 rămân deschise; ordinea este 1 → 2 → 3, cu loturile exacte din raport.

Răspunsurile clientului nu mai sunt amânate sau absente. Proba Android a8c este încheiată INCOMPLETE/heartbeat_gap, HONOR este restaurat și serviciile proprii sunt absente în dovada de recuperare. Vechile instrucțiuni PENDING, restaurare pending sau scoatere USB din corp sunt istorice și nu se execută. Restanțe Etapa 1: baterie, precizie în exterior, offline complet și clarificări; iOS fără Mac rămâne amânat.

Răspunsul Q10 supersedează refuzul comercial prevăzut în specificația de dispatch. Prototipurile și testele istorice sunt păstrate; schimbarea de contract trebuie verificată în lotul său. Hashurile și stările din tabelul istoric de mai jos sunt dovezi ale citirilor anterioare, nu hashuri ale fișierelor după acest prepend.

# ProDelivery D0 — diferențe față de PD-DISPATCH-01 v0.3

Data: 2026-10-11. Statut: addendum de inventar static pentru Etapa 1, corelat cu inventarele backend/frontend; propunerile pentru increment sunt încă propuneri. Nu este implementare, activare, migrare sau închiderea Etapei 7. Proba fizică lungă de baterie și restaurarea politicii temporare HONOR au prioritate.

Specificația originală `PD-DISPATCH-01.md` din 2026-10-02 rămâne păstrată. Modelele, API-urile și tranzacțiile descrise acolo sunt propuneri. Citirea sursei actuale nu certifică mediul live sau un flux executat.

## Clarificare de continuitate — 13 octombrie 2026

D0 este închis ca inventar static conform `LOOP_REPORTS/2026-10-11-stage1-d0-inventory.md`; formulările de mai jos despre ieșirea de produs a lui D0 rămân istoric și nu cer reconstruirea lui. D0 nu este D1 sau probă de implementare 1/2/5/10. Hashurile din tabel sunt cele ale citirii istorice, nu hashurile actuale după prependuri.

La următorul increment se aplică amendamentul Q10 v0.4-contract-candidate din `PD-DISPATCH-01.md`: sarcină obligatorie comisă și ACK tehnic, fără refuz comercial. Timeoutul ACK nu eliberează implicit sarcina. Parametrii Q11 pentru pauză și A/B/C rămân deschiși; compatibilitatea ledgerului, pregătirea A8 și guardurile inventariate rămân baza.

Proba a8c este INCOMPLETE/heartbeat_gap, HONOR restaurat și servicii proprii absente conform începutului actual `NEXT_SESSION.md`; vechile instrucțiuni de baterie/restaurare pending nu se execută din acest addendum. Instrucțiunea curentă de campanie permite loturi independente după epuizarea lucrului disponibil din etapa curentă, cu acceptanțele externe păstrate deschise. Nu certifică etapele 1/2/7 și nu activează telefonul, dispatch-ul, baza reală sau serviciile externe.

## Ce trebuie reconciliat înainte de un increment

| Subiect | Specificația v0.3 | Sursa actuală / consecință pentru următorul pachet |
| --- | --- | --- |
| Pregătire independentă | Secțiunea 1 descrie pregătirea după ASSIGNED ca blocată; secțiunea 5 ține pregătirea/asignarea simultană închisă până la v2. | Inventarul frontend/backend trebuie să păstreze A8: pregătirea separată deja implementată. Nu reintroducem blocajul vechi și nu prezentăm simpla decuplare ca funcție viitoare. |
| Numele câmpurilor | Modelul propus folosește `preparation_state`. | Sursa A8 folosește contractul `preparation_status`; maparea explicită este necesară înainte de a propune încă un câmp. Nu deducem READY din ASSIGNED/ACCEPTED. |
| Feed-ul livratorului | Secțiunea 1 spune că feed-ul exclude DELIVERED, dar nu CANCELLED, și numește defectul `PD-CORE-CANCELLED-01`. | `backend/routers/orders.py:472-481` exclude deja ambele stări terminale. Inventarul păstrează corecția existentă; filtrul nu reprezintă ledger-ul sau capacitatea multi. |
| Ledger și identitate | Propune `dispatch_operations`, `operation_ref` UUID, lease/fence și GET unic. | Asignarea actuală folosește `order_operations`, cheie `assign:` + SHA256(actor, tip, cheia clientului), digest de admisie și lookup scoped. O intenție în curs nu poate fi readmisă prin două protocoale și aplicată de două ori. Noul pachet trebuie să definească adaptorul, deduplicarea și recovery-ul în ambele versiuni. |
| Gate-uri | Propune feature gate v2 și capabilități ale tuturor clienților. | `assign_recovery_enabled` autorizează recuperarea asignării singulare, nu mai multe comenzi. Markerul și topologia sunt verificate pentru admisii noi; lookup/resume al intenției existente sunt distincte de admisia nouă. Oprirea admisiilor nu trebuie să abandoneze operațiile pending. |
| Gardă de livrator | Propune `driver_dispatch_state`, contoare reserved/active și rută versionată. | Asignarea actuală validează claim-ul singular și comenzile neînchise; câmpurile multi sunt respinse. Acesta este un contract intenționat. Nu înlocuim doar pointerul cu o listă și nu tratăm replay-ul singular drept probă de capacitate multi. |
| Topologie | Raportează `hello` Single la 2026-10-02; propune replica set separat. | Observația este istorică. Codul recuperabil actual verifică replica set/mongos prin `hello` și refuză mediul incompatibil. D0 nu citește baza reală și nu afirmă topologia curentă sau activarea markerelor. |
| Incident și bani | Propune rezoluții post-pickup, custody și efecte financiare. | Raportarea actuală folosește ledger-ul separat `operational_operations`; pentru driver, verifică exact o comandă activă. Adminul și restaurantul au verificări de scope proprii. Nu transformăm propunerile în politici aprobate de client; rezoluțiile financiare/custody cer contract și dovezi distincte. |
| Clienți și rollback | Oprirea gate-ului oprește ofertele noi; operațiile deja active continuă prin v2. | Backend `safe_order` marchează deja reprezentările multi cunoscute prin `ORDER_ASSIGNMENT_UNSUPPORTED` și `read_actions_unavailable`, iar sanitizerul frontend păstrează flag-ul. Noul contract trebuie să păstreze această protecție și să includă noile marker-e/reprezentări. Inventarul include admin, restaurant, driver, hartă și scrierile legacy. Pointerul singular nu poate ascunde alte comenzi unui client vechi; nu revenim la cod singular cât timp există operații multi active. |

## Ancore statice verificate de coordonator

- `backend/utils/order_assignment.py:91-107`: identitatea operației și digestul admisiei.
- `backend/utils/order_assignment.py:159-160`: colecția `order_operations`.
- `backend/utils/order_assignment.py:242-263`: marker pentru admisii noi, verificare de topologie, capabilitatea singulară.
- `backend/utils/order_assignment.py:268-295`: lookup/resume păstrează intenția și au verificări distincte de admisia nouă.
- `backend/utils/order_assignment.py:442-468`: corelarea claim/order și refuzul livratorului deja ocupat.
- `backend/utils/order_assignment.py:534-547` și `backend/utils/order_status.py:607-618`: CAS și efecte pe pointerul singular.
- `backend/utils/order_preparation_operations.py:85-103,153`: namespace propriu de pregătire și același ledger `order_operations`.
- `backend/models/order_mutation.py:87-106,180-204`: cheie client, versiune așteptată și digest semantic. Versiunea așteptată face parte din intenție; retry-ul unui rezultat incert nu o schimbă sub aceeași cheie.
- `backend/utils/order_operation_runtime.py:94-104,113-127`: retry de commit cu plafon și cleanup serializat față de worker. Acest helper nu implementează de unul singur lease/fence-ul multi propus în v0.3.
- `backend/routers/orders.py:472-481`: feed-ul livratorului exclude deja DELIVERED și CANCELLED.
- `backend/utils/order_reads.py:231-242`: reprezentările multi cunoscute blochează acțiunile incompatibile prin flag-ul proiectat.

Referințele actuale la „fence”/CAS nu sunt dovada unui lease/worker epoch multi. De asemenea, nu generalizăm refuzul multi din asignare/status la orice writer: preparing/ready și schimbarea disponibilității livratorului trebuie inventariate separat, deoarece nu au toate un refuz general al reprezentărilor multi. Guard-ul comun de cutover trebuie să includă și aceste căi.

SHA256 la citire:

| Fișier | SHA256 |
| --- | --- |
| `.ifrim/SPECIFICATIONS/PD-DISPATCH-01.md` | `13589B13B1B328252112DEE38A7DE2355A89CB372605917AC5965F3116C8ED63` |
| `backend/utils/order_assignment.py` | `5B60208103FDC117DD335190EC9EAD0658D84EF28FF428B69541D70E4B06BC7C` |
| `backend/utils/order_status.py` | `CC314C60A14C07B46818414DC27C1A373C2F935C2361A9BF624EF75B34057CA4` |
| `backend/utils/order_preparation_operations.py` | `7CE77194D9EF78029F20A6E57CBF4875692791BF99C9FAE201A36A38394D68E3` |
| `backend/utils/order_operation_runtime.py` | `E4D67C7C77A58B29651DAFBADF3DB5396F068F13FD46A5DC201D183F7393C077` |
| `backend/models/order_mutation.py` | `E1E74B5411B6A38E30278F3E9CC8FADA088A961951C47B3CA7B5C698ED49E966` |
| `backend/routers/orders.py` | `8F215AE7C2B6D9336A029EE52C96BCDED91D23A0B1D94FE51E7DE3FA403ABD7F` |
| `backend/utils/order_reads.py` | `27D3743CF8DAFBAABD3427DC92A0900B4058798B192B63F35DA86CDF2812CAC0` |

O căutare statică limitată la fișierele aplicației Python/JS/JSX, excluzând testele, nu a găsit șirurile exacte `dispatch/v2`, `dispatch_assignments`, `driver_dispatch_state`, `dispatch_schema_version` în backend și frontend/src. Aceasta limitează afirmația la acele șiruri și acel domeniu; nu dovedește absența oricărei logici echivalente sau starea mediului live.

## Ieșirea D0 și pașii viitori

D0 trebuie să producă inventarul cu scriitori/cititori, capabilități, identități de operații, tranziții, fluxuri de pregătire și teste relevante nominale, plus diferențele față de v0.3. Existența unui test nu este un rezultat PASS din acest lot. D0 nu execută teste sau runtime, nu citește DB/secrete și nu modifică aplicația.

Următorul pachet de implementare se decide numai după inventar și review. Ordinea de verificare propusă rămâne 1, apoi 2, apoi 5, apoi 10 comenzi pe același livrator, cu probe separate de concurență, recovery și consumatori. Aceasta nu mută automat proiectul în Etapa 7 și nu închide etapele comerciale. iOS fizic și răspunsurile clientului rămân la urmă conform instrucțiunii utilizatorului.
