# ProDelivery Agent Hub Rules

## Actualizare prioritara 2026-09-26

Catalin detine actualizarea Agent Hub; acest fisier consemneaza doar contextul ProDelivery. Nu modifica sursa/configuratia Hub si nu transforma starea istorica returnata de Hub in dovada curenta. In acest proiect se lucreaza Codex only, fara OpenClaw/Claude. Nu s-a actualizat Hub prin acest task.

Sursa curenta: `EXECUTION_PLAN_2026-09-26.md` si planul client v1.2 din 26 septembrie 2026. Notele de mai jos raman istoric; nu prevaleaza asupra acestei decizii. Autorizarea curenta nu include commit/push/deploy, schimbari de secrete, baze de date sau lansarea agentilor externi. Cerintele noi sunt planificate, nu implementate prin actualizarea documentelor.

## Context curent (din 2026-09-26)

This file defines ProDelivery-specific rules for the IfrimDigital Agent Hub.

### Pachet comercial activ

Pachet: 10.000 EUR, 10 etape operaționale, confirmat de Catalin pe 2026-09-26.

Referință plan: `EXECUTION_PLAN_2026-09-26.md` și planul client v1.2.

Numerotarea historică Phase 2–8 rămâne referință pentru munca și plățile anterioare; noua numerotare este Etapele 1–10 din planul operațional nou.

### Cele 10 etape aprobate

| Etapă | Rezultat |
| --- | --- |
| 1 | Inventar actual, reguli și specificație închisă |
| 2 | Comenzi și administrare |
| 3 | Panou restaurant |
| 4 | OCR și conector API inițial |
| 5 | Aplicație livrator Android/iOS |
| 6 | GPS și hartă |
| 7 | Alocare și ordinea opririlor (min. 10 comenzi/livrator) |
| 8 | Notificări, excepții, rapoarte simple |
| 9 | Infrastructură și securitate |
| 10 | Pilot, publicare, instruire, predare |

### Prioritate hub

Hub-ul trebuie să protejeze:

- contextul de produs
- limitele etapelor comerciale aprobate
- fluxurile existente (restaurant panel, auth, order lifecycle)
- preview-ul local
- hardening-ul de securitate deja finalizat
- deciziile din `.ifrim/DECISIONS.md`

### Ce nu este autorizat

- commit/push/deploy pe date reale
- migrări de date live
- schimbări de secrete
- lansarea agenților externi
- pornirea etapelor 5–10 fără aprobare explicită Catalin

### Etapa curentă de lucru tehnic

Etapa 1 (inventar) și pregătirea PD-DISPATCH-01 (model asignare multipă). Etapa 3 (panou restaurant) este adiacentă și poate fi paralelizată.

## Required Context Before ProDelivery Work

Read:

- central `.ifrim-system/AGENT_HUB.md`
- central `.ifrim-system/LOOP_ENGINEERING.md`
- central `.ifrim-system/REGRESSION_QA.md`
- `.ifrim/NEXT_SESSION.md`
- `.ifrim/PROJECT_STATE.md`
- `.ifrim/OPEN_ISSUES.md`
- `.ifrim/PHASE_ROADMAP.md`
- `.ifrim/PREVIEW.md`
- `.ifrim/AGENTS.md`
- `.ifrim/OPENCLAW.md`
- latest `.ifrim/LOOP_REPORTS/*.md`

## ProDelivery Task Gates

Before a ProDelivery task starts, the coordinator must classify it:

- `etapa_1_3_core` — inventar, comenzi/admin, panou restaurant: poate proceda
- `etapa_4_7_core` — OCR/conector, aplicație livrator, GPS, alocare: necesită specificație închisă și aprobare Catalin înainte de implementare pe date reale
- `etapa_8_10_core` — notificări, infrastructură, pilot/lansare: necesită aprobare explicită Catalin
- `engineering_support` — calitate cod, teste, securitate, preview, regresii: poate proceda când susține etapele active
- `unclear_scope` — cere Catalin A/B/C înainte de implementare

Reguli:

- `etapa_1_3_core`: poate proceda cu fluxul normal de implementare.
- `etapa_4_7_core`: specificație și inventar mai întâi; nu implementa pe date reale fără gate explicit.
- `etapa_8_10_core`: oprire și aprobare Catalin înainte.
- `engineering_support`: poate proceda dacă susține etapele active fără risc de regresie.
- `unclear_scope`: cere Catalin înainte.

## Required Task Packet Fields

Every non-trivial ProDelivery task must include:

- commercial phase classification
- affected role: admin / restaurant / driver / dispatcher / public
- affected route/screen/API
- owner agent
- reviewer agent
- QA path
- preview URL/check
- regression risk
- acceptance criteria
- whether Catalin approval is required

## Default Agent Routing

Restaurant panel UI:

- owner: `ifrim-frontend`
- reviewer: `ifrim-frontend-reviewer`
- QA: `ifrim-qa`

Order status/API:

- owner: `ifrim-backend`
- reviewer: `ifrim-backend-reviewer`
- QA: `ifrim-qa`

Auth/security/session:

- owner: `ifrim-backend`
- reviewer: `ifrim-security-reviewer`
- QA: `ifrim-qa`

Preview/dev scripts:

- owner: `ifrim-devops`
- reviewer: `ifrim-devops-reviewer`
- QA: `ifrim-qa`

Broad production readiness:

- reviewer: `ifrim-quality-reviewer`
- QA: `ifrim-qa`

## Lock Rules

Use advisory locks for:

- restaurant panel workflow
- order status transitions
- auth/session/CORS/security
- admin/dispatcher workflow
- preview/dev server scripts

Use exclusive locks for:

- schema changes
- auth changes
- order lifecycle changes
- deployment/release work
- broad refactors touching multiple roles

## QA Standard

For visible changes, verify preview:

- frontend: `http://127.0.0.1:3000`
- backend: `http://127.0.0.1:8000/api/`

QA minim pentru etapele 1–3 (curent activ):

- restaurant login și acces securizat
- restaurant vede comenzile active proprii (nu ale altui restaurant)
- accept/pregătire unde există fluxul
- timp de pregătire unde disponibil
- marcare gata de ridicat
- protecție la click dublu
- stare eroare/loading
- refresh după schimbare de status
- vizualizare comenzi trecute/problematice dacă există

QA suplimentar pentru dispatch multiplu (etapa 7, planificat):

- matrix D01–D20 și A01–A08 din `EXECUTION_PLAN_2026-09-26.md`

## Snapshot Rule

When Catalin likes a ProDelivery version, create a snapshot note under:

- `.ifrim/CHECKPOINTS/`
- or `.ifrim/LOOP_REPORTS/` if it is part of a loop run

Snapshot must include:

- date/time
- git state
- preview route
- what Catalin liked
- verified workflow
- known limitations

## Stop Rules

Stop and ask Catalin before:

- implementarea etapelor 4–10 fără specificație închisă și gate explicit
- migrarea datelor reale sau schema changes pe date live
- ștergerea de features sau module
- schimbarea deployment/remotes
- schimbarea credențialelor/secretelor de producție
- modificarea destructivă a bazei de date
- ship-uirea comportamentului demo drept producție
- refactor larg pe admin/restaurant/driver fără QA path clar
- orice cost extern nou (OCR, rutare, hosting, store)
