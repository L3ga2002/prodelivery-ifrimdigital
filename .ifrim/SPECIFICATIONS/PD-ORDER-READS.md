# S2-06 - Contract citiri comenzi

2026-10-08. Scope: API aditiv si panou administrativ paginat, fara mutatii
de business, markeri, indexuri, migrari, env/secrets sau deploy.

## API

- GET /api/orders/read/page: view active/history/all, status enumerat optional,
  restaurant_id/driver_id optionale, from_date inclusiv si to_date exclusiv
  (ISO UTC), limit1..100 implicit25, cursor optional.
- GET /api/orders/read/detail/{order_id}: history_before index exclusiv,
  history_limit1..50 implicit25. Audit canonical embedded, newest-first.
  Ruta foloseste convertor path pentru ID-ul intreg, inclusiv slash codificat;
  validarea/scope-ul exact raman identice. Rutele legacy nu sunt extinse.
- Envelopes explicite: items/next_cursor/has_more/limit/data_warnings; respectiv
  order/history/next_history_before/history_has_more/data_warnings.
- Query/path stricte, identificatori1..120 Unicode code points, controale si
  spatii marginale refuzate. Cursor base64url <=4096, structura/checksum/binding
  verificate. Checksum nu este MAC si cursorul nu confera autorizare.
- Auth revalidat: admin; restaurant numai restaurantul propriu; driver din
  drivers.user_id cu driver_id optional consistent. Missing/array ownership,
  disabled account, duplicari/ambiguitati si actor schimbat sunt fail-closed.
- X-Expected-Actor-ID este comparatie de cont curent, NU credential sau rol.
- 401/403 auth/scope, foreign detail404, request invalid422, ID ambigu409,
  indisponibilitate/deadline503. Cache-Control no-store si erori sanitizate.
- Auth si service au bugete separate8s; aggregate maxTimeMS3000 si cleanup250ms.
  Nu promitem SLA total3s: auth+service pot depasi timeoutul UI15s.

## Paginare si date

Sortare descendent dupa created_at normalizat, apoi business ID si _id unic.
Date legacy string/BSON sunt normalizate; datele invalide/lipsa sunt incluse
determinist null-last, cu warning, fara timestamp inventat. Output explicit
bounded; max101 documente pagina, max2 detail matches, max200 produse, max50
evenimente. Asta NU demonstreaza scan/index/load performant in productie.

Cursorul este legat de actor/rol/resource/filtre/limit. Primare BSON ObjectId,
string bounded si int/long sunt suportate; tipuri neacceptate esueaza sigur,
nu trunchiaza identitatea. Pe colectii mutate concurent nu promitem snapshot
global al tuturor paginilor. Refresh manual reancoreaza prima pagina.

Istoricul paginat foloseste indexul original exclusiv: append-only nu deplaseaza
paginile vechi. Rescrierea/stergerea auditului NU este snapshot-stabila.
Nu unim audit_logs cu audit_trail si nu inventam evenimente lipsa.

Campurile sensibile/raw/ledger sunt excluse. Scalar invalid este omis/warned,
nu afisat ca stergere; numai null explicit inseamna eliminat. Revizie lipsa
ramane lipsa, revizie prezenta invalida ramane blocker. Metadata multislot si
coruptia semantica sunt pastrate ca prezenta/read_actions_unavailable: nu
transformam o comanda nesigura intr-o actiune permisa prin sanitizare.

## UI administrativ

OrdersTab nou foloseste readContext; modul prezentational vechi ramane pentru
compatibilitate. Active/Istoric/Toate, status, restaurant, livrator, date UTC,
pagina urmatoare/precedenta si refresh manual. Numarul pe pagina nu este total
global. Eticheta tabului nu mai pretinde ca lista legacy plafonata este completa.

Eye citeste detail proaspat, separa pregatire/custodie, sursa, versiune, actor,
ora si schimbari. Corectia existenta primeste snapshotul proaspat numai daca
este eligibil. Actiunile necunoscute raman text sigur; lookup-urile labels au
Object.hasOwn si string guard, inclusiv __proto__/constructor/toString.

Timeout15s, abort, epoch/actor/token/query/unmount fences, StrictMode cleanup,
loading/disabled/error/offline/empty explicite. Retry numai GET manual finit;
niciun replay write sau fallback legacy din intentie incerta. Poll revalidates
pagina curenta, fara sa reseteze filtrele/istoricul; mutatia invalideaza ancorele
pastrand filtrele. Fara refresh queued in eroare/offline/busy.

## Compatibilitate si limite

Writer contracts si recovery helpers existente nu sunt rescrise. Formatterul
legacy date primeste numai guard local pentru timestamp corupt -> null.
Helper-ele de mutatie pot refuza conservator ID-uri acceptate de read path;
paritatea citirii nu autorizeaza largirea contractelor writer mostenite.
Fleet/map/analytics si UI restaurant/driver pastreaza consumatorii legacy
plafonati; nu sunt declarati paginati sau statistici globale certificate.
Regresia verifica fluxurile adiacente separat de noua listare.

Activarea protocoalelor create/edit/assign/status ramane distincta, default-
disabled; S2-06 este read-only si nu activeaza aceste mutatii. Single-slot
existent NU indeplineste minimum10/auto-dispatch. Etapa2 nu se inchide din
acest lot. Native/GPS/OCR/API/store/physical devices/PWA/load au gate-uri separate.

