# Ifrim Project Memory

This folder is the durable memory for ProDelivery.

Read order at the start of a future session:

1. `NEXT_SESSION.md`
2. `PROJECT_STATE.md`
3. `OPEN_ISSUES.md`
4. latest file in `CHECKPOINTS/`
5. relevant files in `AGENT_REPORTS/`

Rules:

- Keep project facts here, not only in chat.
- Do not store production secrets here.
- Keep demo credentials in local env/README only if needed for local testing.
- After meaningful work, update `CHANGELOG.md`, `OPEN_ISSUES.md`, and a checkpoint.
