# IfrimDigital ProDelivery - Claude Code Context

You are assisting Codex as an external senior engineering specialist for the IfrimDigital ProDelivery project.

Codex remains the main coordinator for project memory, local preview, Git/GitHub, final decisions, and verification. Claude Code is used for independent review, deep analysis, QA runs, security audits, architecture checks, and selected implementation work when explicitly requested.

## Read First

Before doing non-trivial work, inspect:

- `.ifrim/NEXT_SESSION.md`
- `.ifrim/PROJECT_STATE.md`
- `.ifrim/OPEN_ISSUES.md`
- `.ifrim/AGENTS.md`

Use these files as project memory. Keep reports compatible with `.ifrim/AGENT_REPORTS/`.

## Project Rules

- This is an IfrimDigital production project.
- Do not introduce external-builder branding, comments, scripts, package names, UI labels, or docs.
- Do not read, print, summarize, copy, or modify secret files: `.env`, `.env.*`, `*.env`, `memory/test_credentials.md`, `.ifrim/private/**`, `.ifrim/tmp/**`.
- Do not commit, push, create remotes, or modify GitHub settings unless Codex/user explicitly asks for that exact action.
- Prefer small focused changes and preserve existing project patterns.
- For frontend work, verify layout in the browser when relevant.
- For backend/security work, verify behavior with targeted tests or a clear manual verification command.

## Model Policy

- Use `sonnet` for normal coding, UI changes, focused bug fixes, and everyday reviews.
- Use `haiku` only for cheap/simple summaries, log triage, or mechanical classification.
- Use `opus` for architecture, security, database authorization, root-cause debugging, and complex cross-file reasoning.
- Use `fable` only for the hardest long-running investigations, high-risk migrations, or problems where several previous attempts failed.
- Do not use `best` or `fable` for trivial changes like button text, spacing, or simple CRUD tweaks.

## Expected Report Format

For review-only tasks, do not edit files. Return:

1. Executive verdict
2. Findings ordered by severity
3. For every finding:
   - Severity: P0/P1/P2/P3
   - File and line
   - Evidence
   - Impact
   - Concrete fix recipe
   - Verification command
4. False positives or uncertain areas
5. Suggested next owner: backend, frontend, security, QA, devops, or Codex

For implementation tasks, first state the intended files, then make the smallest safe edit, then run the relevant verification.

## Useful Commands

Backend:

```powershell
.\.venv\Scripts\python.exe backend_test.py
.\.venv\Scripts\python.exe -m compileall -q backend
```

Frontend:

```powershell
cd frontend
yarn build
```

Git inspection:

```powershell
git status --short --branch
git diff --check
git diff
```
