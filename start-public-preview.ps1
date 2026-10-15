param(
    [string]$Hostname = "demo.prodeliverybacau.com",
    [string]$TunnelConfig = "$env:USERPROFILE\.cloudflared\prodelivery-demo.yml"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $ProjectRoot ".codex-run"
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BackendLogOut = Join-Path $LogDir "backend-public.out.log"
$BackendLogErr = Join-Path $LogDir "backend-public.err.log"
$FrontendLogOut = Join-Path $LogDir "frontend-public.out.log"
$FrontendLogErr = Join-Path $LogDir "frontend-public.err.log"
$TunnelLogOut = Join-Path $LogDir "cloudflared-public.out.log"
$TunnelLogErr = Join-Path $LogDir "cloudflared-public.err.log"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Get-CloudflaredPath {
    $command = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $wingetPackage = Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Recurse -Filter "cloudflared.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($wingetPackage) {
        return $wingetPackage.FullName
    }

    throw "cloudflared.exe was not found. Install Cloudflare cloudflared first."
}

function Get-ProcessInfoById {
    param([int]$ProcessId)
    Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Stop-ProjectProcess {
    param(
        [int]$ProcessId,
        [string]$Reason
    )

    if (-not $ProcessId -or $ProcessId -eq $PID) {
        return
    }

    $processInfo = Get-ProcessInfoById -ProcessId $ProcessId
    if (-not $processInfo) {
        return
    }

    $commandLine = [string]$processInfo.CommandLine
    $isProjectProcess = $commandLine.Contains($ProjectRoot) -or
        $commandLine.Contains($TunnelConfig) -or
        $commandLine.Contains("prodelivery-demo.yml")

    if (-not $isProjectProcess) {
        throw "Port is already used by a non-ProDelivery process: PID $ProcessId. Stop it manually, then rerun this script."
    }

    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped PID $ProcessId ($Reason)"
}

function Stop-PortOwners {
    param([int]$Port)

    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($processId in $processIds) {
        Stop-ProjectProcess -ProcessId $processId -Reason "port $Port"
    }
}

function Stop-MatchingProjectProcesses {
    $patterns = @(
        "*$ProjectRoot*uvicorn*server:app*",
        "*$ProjectRoot*craco*start*",
        "*$ProjectRoot*react-scripts*start*",
        "*$TunnelConfig*"
    )

    foreach ($pattern in $patterns) {
        $matches = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like $pattern }
        foreach ($match in $matches) {
            Stop-ProjectProcess -ProcessId $match.ProcessId -Reason "preview restart"
        }
    }
}

function Wait-ForHttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                return
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for $Url"
}

function Start-ProcessWithEnvironment {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$RedirectStandardOutput,
        [string]$RedirectStandardError,
        [hashtable]$Environment
    )

    $previousValues = @{}
    foreach ($key in $Environment.Keys) {
        $previousValues[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }

    try {
        Start-Process -FilePath $FilePath `
            -ArgumentList $ArgumentList `
            -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $RedirectStandardOutput `
            -RedirectStandardError $RedirectStandardError `
            -WindowStyle Hidden
    } finally {
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previousValues[$key], "Process")
        }
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtualenv was not found at $Python. Run .\dev-start.ps1 first to create dependencies."
}

if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "node_modules"))) {
    throw "Frontend node_modules was not found. Run yarn install in the frontend folder first."
}

if (-not (Test-Path -LiteralPath $TunnelConfig)) {
    throw "Cloudflare tunnel config was not found at $TunnelConfig."
}

$mongo = Get-Service -Name MongoDB -ErrorAction SilentlyContinue
if ($mongo -and $mongo.Status -ne "Running") {
    Start-Service -Name MongoDB
}

$cloudflared = Get-CloudflaredPath

Stop-PortOwners -Port 8000
Stop-PortOwners -Port 3000
Stop-MatchingProjectProcesses
Start-Sleep -Seconds 2

$backendEnv = @{
    CORS_ORIGINS = "http://127.0.0.1:3000,http://localhost:3000,https://$Hostname"
}

Start-ProcessWithEnvironment `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*") `
    -WorkingDirectory $BackendDir `
    -RedirectStandardOutput $BackendLogOut `
    -RedirectStandardError $BackendLogErr `
    -Environment $backendEnv

$frontendEnv = @{
    HOST = "127.0.0.1"
    PORT = "3000"
    BROWSER = "none"
    DANGEROUSLY_DISABLE_HOST_CHECK = "true"
    REACT_APP_BACKEND_URL = "https://$Hostname"
}

Start-ProcessWithEnvironment `
    -FilePath "yarn.cmd" `
    -ArgumentList @("start") `
    -WorkingDirectory $FrontendDir `
    -RedirectStandardOutput $FrontendLogOut `
    -RedirectStandardError $FrontendLogErr `
    -Environment $frontendEnv

Start-Process -FilePath $cloudflared `
    -ArgumentList @("tunnel", "--config", $TunnelConfig, "run") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $TunnelLogOut `
    -RedirectStandardError $TunnelLogErr `
    -WindowStyle Hidden

Wait-ForHttpOk -Url "http://127.0.0.1:8000/api/" -TimeoutSeconds 45
Wait-ForHttpOk -Url "http://127.0.0.1:3000/login" -TimeoutSeconds 90
Wait-ForHttpOk -Url "https://$Hostname/api/" -TimeoutSeconds 45
Wait-ForHttpOk -Url "https://$Hostname/login" -TimeoutSeconds 90

Write-Host "ProDelivery public preview is running."
Write-Host "Public app: https://$Hostname/login"
Write-Host "Public API: https://$Hostname/api/"
Write-Host "Local frontend: http://127.0.0.1:3000"
Write-Host "Local backend: http://127.0.0.1:8000/api/"
Write-Host "Logs: $LogDir"
