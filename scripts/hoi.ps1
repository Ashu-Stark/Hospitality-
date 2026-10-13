<#
HOI: start, stop or check every service with one command (Windows PowerShell 5.1+).

    .\scripts\hoi.ps1 start            # MongoDB Atlas from .env
    .\scripts\hoi.ps1 start -Offline   # in-memory database, no internet needed (data resets on stop)
    .\scripts\hoi.ps1 status
    .\scripts\hoi.ps1 stop

Logs go to .logs\<service>.log. Needs the root .venv (see README).
#>
param(
    [Parameter(Position = 0)][ValidateSet("start", "stop", "status")][string]$Action = "status",
    [switch]$Offline
)

$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root ".logs"

$Services = @(
    @{ Name = "ops";       Port = 8000; Dir = $Root;                           Args = @("-m", "backend.serve");                                                   Check = "http://127.0.0.1:8000/health" },
    @{ Name = "platform";  Port = 8100; Dir = (Join-Path $Root "platform_api"); Args = @("-m", "uvicorn", "hoi_platform.main:app", "--host", "0.0.0.0", "--port", "8100"); Check = "http://127.0.0.1:8100/ready" },
    @{ Name = "portal";    Port = 8200; Dir = (Join-Path $Root "portal");       Args = @("-m", "uvicorn", "hoi_portal.main:app", "--host", "0.0.0.0", "--port", "8200");    Check = "http://127.0.0.1:8200/ready" },
    @{ Name = "dashboard"; Port = 8501; Dir = (Join-Path $Root "dashboard");    Args = @("-m", "streamlit", "run", "app.py", "--server.port", "8501", "--server.headless", "true"); Check = "http://127.0.0.1:8501/_stcore/health" }
)

function Get-PortPid([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.OwningProcess }
    return $null
}

function Test-Up([string]$Url) {
    try { return (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}

function Show-Status {
    foreach ($s in $Services) {
        $state = if (Test-Up $s.Check) { "up" } elseif (Get-PortPid $s.Port) { "starting" } else { "down" }
        "{0,-10} :{1}  {2}" -f $s.Name, $s.Port, $state
    }
    ""
    "Dashboard   http://localhost:8501"
    "Staff app   http://localhost:8100/worker/"
    "Portal      http://localhost:8200"
    "API docs    http://localhost:8000/docs  http://localhost:8100/docs  http://localhost:8200/docs"
}

if ($Action -eq "status") { Show-Status; return }

if ($Action -eq "stop") {
    foreach ($s in $Services) {
        $procId = Get-PortPid $s.Port
        if ($procId) { Stop-Process -Id $procId -Force -Confirm:$false; "stopped $($s.Name)" } else { "$($s.Name) was not running" }
    }
    return
}

# ---- start ------------------------------------------------------------------
if (-not (Test-Path $Py)) { throw "No .venv found. Create it first (see README, Setup)." }
New-Item -ItemType Directory -Force $Logs | Out-Null

# Load .env into this process (child processes inherit it). Never printed.
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([A-Z_][A-Z0-9_]*)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
    }
}
if ($Offline) {
    $env:MONGODB_URI = "mongomock://"
    $env:PORTAL_WEATHER_ENABLED = "false"
    "Offline mode: in-memory database, demo data is re-seeded on every start."
} elseif (-not $env:MONGODB_URI) {
    "MONGODB_URI is not set: services will use the in-memory database."
}
$env:PORT = "8000"
$env:USE_MOCKS = "false"
$env:API_BASE_URL = "http://127.0.0.1:8000"
$env:PLATFORM_API_URL = "http://127.0.0.1:8100"
if (-not $env:PLATFORM_PUBLIC_URL) { $env:PLATFORM_PUBLIC_URL = "http://localhost:8100" }
if (-not $env:HOI_PUBLIC_BASE_URL) { $env:HOI_PUBLIC_BASE_URL = "http://localhost:8100" }

foreach ($s in $Services) {
    if (Get-PortPid $s.Port) { "$($s.Name) already running on :$($s.Port)"; continue }
    $log = Join-Path $Logs "$($s.Name).log"
    Start-Process -FilePath $Py -ArgumentList $s.Args -WorkingDirectory $s.Dir -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err" | Out-Null
    "starting $($s.Name) on :$($s.Port)"
}

# Wait up to 3 minutes (first start on Atlas seeds demo data).
$deadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 3
    $down = @($Services | Where-Object { -not (Test-Up $_.Check) })
} while ($down.Count -gt 0 -and (Get-Date) -lt $deadline)

""
Show-Status
if ($down.Count -gt 0) { ""; "Not up yet: $($down.Name -join ', '). See .logs\<service>.log.err" }
