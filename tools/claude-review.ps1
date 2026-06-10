[CmdletBinding()]
param(
    [ValidateSet("quick", "security", "backend", "frontend", "qa", "architect", "fable")]
    [string]$Profile = "quick",

    [string]$Task = "Review the current ProDelivery project and report the most important actionable issues.",

    [switch]$NoReport
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

$claudeCommand = Get-Command claude -ErrorAction Stop

$profiles = @{
    quick = @{
        Agent = "ifrim-claude-code-reviewer"
        Model = "sonnet"
        Effort = "medium"
        Label = "claude-quick-review"
    }
    security = @{
        Agent = "ifrim-claude-security-auditor"
        Model = "opus"
        Effort = "high"
        Label = "claude-security-audit"
    }
    backend = @{
        Agent = "ifrim-claude-backend-reviewer"
        Model = "sonnet"
        Effort = "medium"
        Label = "claude-backend-review"
    }
    frontend = @{
        Agent = "ifrim-claude-frontend-reviewer"
        Model = "sonnet"
        Effort = "medium"
        Label = "claude-frontend-review"
    }
    qa = @{
        Agent = "ifrim-claude-qa-runner"
        Model = "sonnet"
        Effort = "low"
        Label = "claude-qa-run"
    }
    architect = @{
        Agent = "ifrim-claude-architect"
        Model = "opus"
        Effort = "high"
        Label = "claude-architecture-review"
    }
    fable = @{
        Agent = "ifrim-claude-fable-principal"
        Model = "fable"
        Effort = "high"
        Label = "claude-fable-principal"
    }
}

$selected = $profiles[$Profile]

$prompt = @"
You are being invoked by Codex for IfrimDigital ProDelivery.

Task:
$Task

Operating rules:
- Read CLAUDE.md and the relevant .ifrim memory files before non-trivial conclusions.
- Do not edit files.
- Do not read .env, .env.*, *.env, memory/test_credentials.md, .ifrim/private/**, .ifrim/tmp/**, or backend/uploads/**.
- Do not commit, push, create remotes, or run GitHub auth/repo commands.
- Return a concise report with severity, file/line, evidence, impact, fix recipe, and verification command.
"@

$allowedTools = @(
    "Read",
    "Grep",
    "Glob",
    "Bash(git status *)",
    "Bash(git diff *)",
    "Bash(git log *)",
    "Bash(rg *)",
    "Bash(yarn build)",
    "Bash(yarn test *)",
    "Bash(.\\.venv\\Scripts\\python.exe backend_test.py)",
    "Bash(.\\.venv\\Scripts\\python.exe -m compileall *)",
    "Bash(pytest *)"
)

$claudeArgs = @(
    "--agent", $selected.Agent,
    "--model", $selected.Model,
    "--effort", $selected.Effort,
    "-p", $prompt,
    "--output-format", "json",
    "--allowedTools", ($allowedTools -join ",")
)

$rawOutput = & $claudeCommand.Source @claudeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Claude Code exited with status $LASTEXITCODE"
}

$resultText = $rawOutput
try {
    $parsed = $rawOutput | ConvertFrom-Json
    if ($parsed.result) {
        $resultText = $parsed.result
    }
}
catch {
    $resultText = $rawOutput
}

if (-not $NoReport) {
    $reportDir = Join-Path $projectRoot ".ifrim\AGENT_REPORTS"
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

    $timestamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
    $reportPath = Join-Path $reportDir "$timestamp-$($selected.Label).md"

    $metadata = @"
# $($selected.Label)

- Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
- Profile: $Profile
- Agent: $($selected.Agent)
- Model: $($selected.Model)
- Effort: $($selected.Effort)
- Task: $Task

---

"@

    Set-Content -Path $reportPath -Value ($metadata + $resultText) -Encoding UTF8
    Write-Output "Report saved: $reportPath"
}

Write-Output $resultText
