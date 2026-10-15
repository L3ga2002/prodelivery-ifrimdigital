<!-- PD-REFACTOR-A8-CLOSED-2026-10-11:begin -->
## 2026-10-11 — A0–A8 închise local, inclusiv A7 final

Acest checkpoint are prioritate față de istoricul de mai jos. Citește `LOOP_REPORTS/2026-10-11-restaurant-refactor-final.md` și `QA_RUNS/2026-10-11-restaurant-refactor-b5efe45ce9a5/a8-closed/manifest.json`. Toate funcționalitățile restaurantului sunt păstrate; refactorurile A2–A6 și recuperarea pregătire/READY A8 sunt integrate, revizuite independent și testate. A8:96/96 frontend,123/123 backend, build0/0, browser8+8+6 grupe PASS. Nu confunda aceasta cu o suită globală complet verde: rezultatele brute și adaptorul QA pentru mockul vechi Axios sunt explicate în raport.

Nu reface aceste loturi. Markerul order-preparation-v1 este implicit dezactivat și a fost activat numai în QA sintetic. Runtime-urile proprii sunt închise, datele și probele păstrate. Fără acces la .env/private, baze reale, ADB, Git writes sau deploy. Manifestul final înlocuiește hashurile surselor modificate, fără a rescrie dovezile istorice.140 înregistrări protejate înseamnă76 fișiere unice. Backlog: D0 contract/inventar dispatch înainte de implementarea multiplă; iOS și clientul la urmă, bateria fizică INCOMPLETE separat.
<!-- PD-REFACTOR-A8-CLOSED-2026-10-11:end -->

<!-- PD-REFACTOR-A2-A6-2026-10-11:begin -->
## 2026-10-11 — A0–A6 închise; A8 în lucru

Acest checkpoint are prioritate față de istoricul de mai jos. Utilizatorul a autorizat începerea refactorului cu păstrarea tuturor funcționalităților. Citește `LOOP_REPORTS/2026-10-11-restaurant-refactor-a2-a6.md` și manifestul `QA_RUNS/2026-10-11-restaurant-refactor-b5efe45ce9a5/a2-a6-closed-v2/manifest.json`. A2 transport, A3 parser, A4 executor, A5 prezentare și A6 citiri sunt integrate/revizuite/testate; nu le reface. Testele istorice rămân neschimbate, cu eșecurile lor explicate;140 intrări înseamnă76 fișiere unice.

A8 continuă pe contractul `TASK_PACKETS/2026-10-11-preparation-recovery-b5efe45ce9a5.md`; stadiile se află în launcher `refactor-preparation-backend-stage` și `refactor-preparation-frontend-stage`. Nu sunt integrate în acest checkpoint. Verifică manifestele și review-ul final înainte de publicarea locală. Browser QA A2–A6 este oprit; Mongo BE27941 poate aparține încă QA A8 și trebuie identificat înainte de utilizare/oprire. Nu porni servicii/baze reale, nu citi .env/private și nu modifica datele clientului. Fără Git writes/deploy/ADB. iOS și răspunsurile clientului rămân la urmă.
<!-- PD-REFACTOR-A2-A6-2026-10-11:end -->

# Changelog

## 2026-09-27

- Sincronizare Agent Hub cu cerințele la zi. Sursa autoritativă este `EXECUTION_PLAN_2026-09-26.md` și planul client v1.2 din 26 septembrie 2026.
- Noul pachet comercial: 10.000 EUR pentru 10 etape operaționale, suplimentar față de plățile anterioare.
- Structura comercială nouă înlocuiește numerotarea istorică Phase 2–8 cu cele 10 etape din planul operațional. Numerotarea veche rămâne referință istorică pentru munca și plățile deja efectuate.
- Cerințe noi aprobate: alocare multiplă (minimum 10 comenzi pe același livrator), aplicație nativă Android/iOS pentru livrator, OCR cu confirmare umană, conector API inițial pentru un restaurant, GPS real cu confidențialitate, rapoarte, infrastructură și pilot.
- Dovezi din cod la 2026-09-26: `current_order_id` singular în `backend/models/driver.py:33`; conflict la a doua comandă în `backend/routers/orders.py:450`. Cerințele noi sunt planificate, nu implementate.
- Pachet tehnic inițial PD-DISPATCH-01: model și contracte pentru 1/2/5/10 comenzi pe același livrator, cu compatibilitate pentru fluxul singular existent.
- Nu s-au efectuat commit/push/deploy/migrare date reale prin aceste actualizări.
- Fișiere actualizate: `NEXT_SESSION.md`, `PROJECT_STATE.md`, `OPEN_ISSUES.md`, `PHASE_ROADMAP.md`, `AGENT_HUB_RULES.md`, `AGENTS.md`, `CHANGELOG.md`.

## 2026-09-26

- Catalin a confirmat noul pachet operațional 10.000 EUR, plan v1.2. Decizie: el actualizează Agent Hub; Codex continuă pregătirea ProDelivery.
- Adăugat `EXECUTION_PLAN_2026-09-26.md`: cele 10 etape, invarianții obligatorii pentru dispatch multiplu, modelul incremental propus, matricea de teste D01–D20 și A01–A08, ordinea de execuție și gate-urile.
- Adăugat `PHASE_ROADMAP.md` cu actualizare prioritară 2026-09-26 care pointează la noul plan.
- Adăugat `AGENT_HUB_RULES.md` cu actualizare prioritară 2026-09-26.
- Inspecție cod focalizată: `current_order_id` singular și blocarea celei de-a doua comenzi confirmate în sursa activă.
- Nu s-au executat teste în sesiunea de documentare; rezultatele istorice nu sunt dovadă curentă.

## 2026-06-23

- Added mandatory central thread bootstrap and agent routing requirement to `NEXT_SESSION.md`.
- Threads must now state whether they use Codex only, OpenClaw, Claude Code, or a hybrid flow before non-trivial work.
- Sent bootstrap reminder to the known ProDelivery Codex thread.

## 2026-06-09

- Added Claude Code project context in `CLAUDE.md`.
- Added Claude Code settings in `.claude/settings.json`.
- Added IfrimDigital Claude subagents for code review, security, backend, frontend, QA, architecture, fable-level investigation, and explicit implementation.
- Added `tools/claude-review.ps1` to run controlled Claude review profiles and save reports to `.ifrim/AGENT_REPORTS/`.
- Smoke-tested the custom Claude reviewer agent and runner successfully.
- Ran Claude Fable end-to-end security audit and saved the report to `.ifrim/AGENT_REPORTS/2026-06-09-232915-claude-fable-principal.md`.
- Updated open security issues with Fable findings: seed/register/orders/driver/schedule authorization, CSRF, lockout header trust, CORS deployment check, and public avatar/stats decisions.
- Added `.ifrim/OPENCLAW.md` so new ProDelivery threads can recover the IfrimDigital OpenClaw agent roster and usage rules without relying on old conversation context.
- Added live preview rules to project and central memory: app/UI work should start or verify preview, check affected routes after visible changes, and report the exact URL.
- Added production implementation rule to project and central memory: do not implement demo-only behavior; implement real production features with validations, edge cases, error handling, loading states, duplicate-request protection, useful logs, and no broken existing flows.

## 2026-06-08

- Migrated ProDelivery into the IfrimDigital local projects workspace.
- Removed old external-builder artifacts from the active copy.
- Created local backend/frontend env files.
- Added local preview scripts:
  - `dev-start.ps1`
  - `dev-stop.ps1`
- Simplified backend requirements to a maintainable dependency set.
- Verified local backend, frontend build, and preview.
- Created IfrimDigital OpenClaw reviewer/implementation agent team.
- Added `ifrim-quality-reviewer` for scorecard-style static code quality review.
- Added project memory folder `.ifrim/`.
- Added central projects registry at `..\PROJECTS.md`.
- Prepared GitHub-safe baseline by removing hardcoded demo passwords from versionable README/tests/UI code, generating initial driver/restaurant passwords, and ignoring local upload artifacts.
