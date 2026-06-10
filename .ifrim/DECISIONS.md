# Decisions

## 2026-06-09

- Claude Code is added as an external IfrimDigital engineering specialist coordinated by Codex.
- Codex remains the main coordinator for memory, preview, Git/GitHub, final decisions, and verification.
- OpenClaw remains the local IfrimDigital agent team for routine specialist work.
- Claude Code is used for independent review, deeper security/architecture analysis, QA summaries, and selected implementation only when explicitly requested.
- Default Claude model is `sonnet`; use `opus` for architecture/security/deep debugging, `haiku` only for simple summaries, and `fable` only for the hardest long-running investigations.
- Review-oriented Claude agents are read-only and must not inspect env files, private memory, uploads, or test credential notes.

## 2026-06-08

- Codex remains the main coordinator/technical brain.
- OpenClaw agents are IfrimDigital specialist engineers used for focused review, implementation, QA, DevOps, design, migration, and integrations.
- Reviewer agents do not edit files. They report actionable findings with owner and fix recipe.
- Fixer agents receive reviewer findings and implement changes.
- QA verifies after fixes.
- For multiple projects, use one project folder, one `.ifrim/` memory folder, and preferably one Codex thread per project.
- ProDelivery gets durable project memory in `.ifrim/` plus a central registry in `..\PROJECTS.md`.
- Git should be initialized locally for history, but production secrets and local env files must stay ignored.
- Do not create the first baseline commit until demo credentials and local-only testing files are reviewed.
