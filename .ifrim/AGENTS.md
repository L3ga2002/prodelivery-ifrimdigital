# Agent Workflow

Codex is the coordinator. OpenClaw agents are IfrimDigital specialist engineers.

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

- Project path: `C:\Users\mihai\OneDrive\Documente\IfrimDigital Projects\ProDelivery`
- Stack: FastAPI/MongoDB backend, React frontend
- Current preview URLs from `PREVIEW.md`
- Relevant open issues from `OPEN_ISSUES.md`
