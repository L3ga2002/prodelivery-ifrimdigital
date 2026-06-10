# Changelog

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
