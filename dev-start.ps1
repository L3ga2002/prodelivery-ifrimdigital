$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $ProjectRoot ".codex-run"
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$mongo = Get-Service -Name MongoDB -ErrorAction SilentlyContinue
if ($mongo -and $mongo.Status -ne "Running") {
    Start-Service -Name MongoDB
}

if (-not (Test-Path -LiteralPath $Python)) {
    Push-Location $ProjectRoot
    python -m venv .venv
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r backend\requirements.txt
    Pop-Location
}

if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "node_modules"))) {
    Push-Location $FrontendDir
    yarn install
    Pop-Location
}

$backendPort = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if (-not $backendPort) {
    Start-Process -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8000", "--reload") `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput (Join-Path $LogDir "backend.out.log") `
        -RedirectStandardError (Join-Path $LogDir "backend.err.log") `
        -WindowStyle Hidden
}

$frontendPort = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if (-not $frontendPort) {
    $env:HOST = "127.0.0.1"
    $env:PORT = "3000"
    $env:BROWSER = "none"
    Start-Process -FilePath "yarn.cmd" `
        -ArgumentList @("start") `
        -WorkingDirectory $FrontendDir `
        -RedirectStandardOutput (Join-Path $LogDir "frontend.out.log") `
        -RedirectStandardError (Join-Path $LogDir "frontend.err.log") `
        -WindowStyle Hidden
}

Write-Host "ProDelivery local preview"
Write-Host "Frontend: http://127.0.0.1:3000"
Write-Host "Backend:  http://127.0.0.1:8000/api/"
Write-Host "Logs:     $LogDir"
