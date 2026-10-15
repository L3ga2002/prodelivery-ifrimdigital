# Agent Workflow

## Actualizare prioritara 2026-09-26

Rutare activa: Codex only conform instructiunii explicite a lui Catalin; nu invoca OpenClaw sau Claude Code. Catalin actualizeaza Agent Hub. Review si QA raman obligatorii ca verificari distincte; nu declara review independent daca l-a facut acelasi agent. Nu exista autorizare pentru servicii AI platite.

Sursa curenta: `EXECUTION_PLAN_2026-09-26.md` si planul client v1.2 din 26 septembrie 2026. Notele de mai jos raman istoric; nu prevaleaza asupra acestei decizii. Autorizarea curenta nu include commit/push/deploy, schimbari de secrete, baze de date sau lansarea agentilor externi. Cerintele noi sunt planificate, nu implementate prin actualizarea documentelor.

## Istoric pastrat

Codex is the coordinator. OpenClaw agents are IfrimDigital specialist engineers.
Claude Code is an external IfrimDigital specialist used by Codex for independent review, deep audits, and selected implementation.

For the full OpenClaw agent roster, paths, and usage notes, read `OPENCLAW.md`. New Codex threads must not assume the old chat context; `OPENCLAW.md` is the local source of truth for the IfrimDigital OpenClaw team.

Also read the central agent catalog before assigning, skipping, or describing agent roles:

`C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\.ifrim-system\AGENT_CATALOG.md`

That catalog defines what `ifrim-backend`, `ifrim-frontend`, `ifrim-qa`, each reviewer, and each specialist agent is responsible for.

## Live Preview Rule

For app/frontend work, Codex should start or verify the local preview whenever practical and check the affected route after visible UI changes. Use `PREVIEW.md` for ports and commands. If preview cannot run, report the blocker and record it in project memory.

## Regression QA Rule

After any non-trivial feature, optimization, refactor, UI change, API/data change, or bug fix, read and apply:

`C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\.ifrim-system\REGRESSION_QA.md`

Do not mark work complete only because the edited file looks right. Verify the affected ProDelivery route in live preview, click through the related restaurant/admin/login/order flows when relevant, check readable text/buttons/layout, verify loading/error/empty states, and confirm shared frontend/API behavior was not broken.

Use the relevant reviewer (`ifrim-frontend-reviewer`, `ifrim-backend-reviewer`, `ifrim-quality-reviewer`, `ifrim-security-reviewer`) and `ifrim-qa` for important changes.

## Production Implementation Rule

Before any implementation task, read and apply this rule:

Do not implement as a demo. Implement as a real production feature, with validations, edge cases, error handling, loading states, duplicate-request protection, useful logs, and without breaking existing flows.

## Data Protection Rule

Do not delete, overwrite, wipe, reset, truncate, or mass-replace important project data without Catalin's explicit approval.

Normal small code edits are allowed. Ask before destructive or broad changes that may remove features, source modules, project memory, reports, uploads, databases, Git history, deployment settings, or client/user data.

This applies to Codex, OpenClaw implementation agents, and Claude Code when implementation is explicitly requested.

## Review Flow

1. `ifrim-reviewer` plans or synthesizes review.
2. Specialist reviewers run as needed:
   - `ifrim-backend-reviewer`
   - `ifrim-frontend-reviewer`
   - `ifrim-security-reviewer`
   - `ifrim-devops-reviewer`
   - `ifrim-quality-reviewer`
3. Reviewers report findings only.
4. Codex assigns fixes to:
   - `ifrim-backend`
   - `ifrim-frontend`
   - `ifrim-devops`
   - `ifrim-design`
   - `ifrim-integrations`
5. `ifrim-qa` verifies after fixes.

## Claude Code Flow

Use Claude Code through `tools/claude-review.ps1` when Codex wants a second technical opinion or deeper analysis.

Profiles:

- `quick`: general code quality review on `sonnet`
- `backend`: FastAPI/MongoDB/backend review on `sonnet`
- `frontend`: React/frontend review on `sonnet`
- `qa`: verification summary on `sonnet`
- `security`: auth/tenant/secrets audit on `opus`
- `architect`: cross-layer architecture analysis on `opus`
- `opus`: hardest unresolved investigations and high-effort independent review on `opus`

Claude review agents report findings only. The implementer agent exists only for explicit Codex/user-approved implementation tasks.

## Required Finding Shape

Each finding should include:

- severity
- file/line
- evidence
- impact
- owner/fixer agent
- fix recipe
- verification command

## Project Context To Pass Agents

Always include:

- Project path: `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`
- Stack: FastAPI/MongoDB backend, React frontend
- Current preview URLs from `PREVIEW.md`
- Relevant open issues from `OPEN_ISSUES.md`
