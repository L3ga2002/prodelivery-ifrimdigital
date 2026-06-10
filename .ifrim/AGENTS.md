# Agent Workflow

Codex is the coordinator. OpenClaw agents are IfrimDigital specialist engineers.
Claude Code is an external IfrimDigital specialist used by Codex for independent review, deep audits, and selected implementation.

For the full OpenClaw agent roster, paths, and usage notes, read `OPENCLAW.md`. New Codex threads must not assume the old chat context; `OPENCLAW.md` is the local source of truth for the IfrimDigital OpenClaw team.

## Live Preview Rule

For app/frontend work, Codex should start or verify the local preview whenever practical and check the affected route after visible UI changes. Use `PREVIEW.md` for ports and commands. If preview cannot run, report the blocker and record it in project memory.

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
- `fable`: hardest unresolved investigations on `fable`

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
