# Thread Prompt - ProDelivery

## Actualizare prioritara 2026-09-26

La reluare, citeste mai intai `EXECUTION_PLAN_2026-09-26.md` si blocurile datate din memorie. Nu reporni proiectul si nu reveni la ipoteza de maximum doua comenzi. Pastreaza codul existent; Codex lucreaza la ProDelivery, Catalin la Hub; fara OpenClaw/Claude.

Sursa curenta: `EXECUTION_PLAN_2026-09-26.md` si planul client v1.2 din 26 septembrie 2026. Notele de mai jos raman istoric; nu prevaleaza asupra acestei decizii. Autorizarea curenta nu include commit/push/deploy, schimbari de secrete, baze de date sau lansarea agentilor externi. Cerintele noi sunt planificate, nu implementate prin actualizarea documentelor.

## Istoric pastrat

You are the dedicated Codex project thread for `ProDelivery - IfrimDigital`.

## Project Path

`C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`

## Read First

1. `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\PROJECTS.md`
2. `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\.ifrim-system\THREAD_BOOTSTRAP.md`
3. `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\.ifrim-system\DATA_PROTECTION.md`
4. `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\.ifrim-system\AGENT_ROUTING_PROTOCOL.md`
5. `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\.ifrim-system\REGRESSION_QA.md`
6. `.ifrim/NEXT_SESSION.md`
7. `.ifrim/PROJECT_STATE.md`
8. `.ifrim/OPEN_ISSUES.md`
9. `.ifrim/PREVIEW.md`
10. `.ifrim/AGENTS.md`
11. `.ifrim/OPENCLAW.md`
12. `CLAUDE.md` if present

After reading memory, state:

- Active project
- Project path
- Memory read
- Agent routing
- Preview plan
- Git state
- Execution plan

## Regression QA Rule

After any non-trivial feature, optimization, refactor, UI change, API/data change, or bug fix, apply `REGRESSION_QA.md`.

Do not mark work complete only because build/lint passes. Verify the affected ProDelivery route in live preview, click related restaurant/admin/login/order flows when relevant, check readable text/buttons/layout, verify loading/error/empty states, duplicate-request protection, and confirm shared frontend/API behavior was not broken.

## Production Rule

Do not implement as a demo. Implement production-quality changes with validations, edge cases, error handling, loading states, duplicate-request protection, useful logs, and without breaking existing flows.
