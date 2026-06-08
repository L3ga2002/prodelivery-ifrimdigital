# Decisions

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
