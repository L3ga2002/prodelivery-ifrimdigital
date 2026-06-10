# Claude Code Integration

Claude Code is configured here as an external IfrimDigital engineering specialist coordinated by Codex.

## Default Routing

- Default model: `sonnet`
- Fallback chain: `opus`, then `haiku`
- Deep architecture/security: `opus`
- Hardest long-running investigations: `fable`
- Simple summaries/log triage: `haiku`

## Local Runner

Use:

```powershell
.\tools\claude-review.ps1 -Profile quick
.\tools\claude-review.ps1 -Profile security
.\tools\claude-review.ps1 -Profile backend
.\tools\claude-review.ps1 -Profile frontend
.\tools\claude-review.ps1 -Profile qa
.\tools\claude-review.ps1 -Profile architect
.\tools\claude-review.ps1 -Profile fable -Task "Investigate the hardest unresolved issue."
```

Reports are saved under `.ifrim/AGENT_REPORTS/`.

## Safety

Review profiles are read-only. Claude must not read `.env` files, private memory, uploaded files, or test credential notes.
