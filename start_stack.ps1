param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

function Get-FreePort {
    param([int]$PreferredPort)
    $port = $PreferredPort
    while ($true) {
        $inUse = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $port }
        if (-not $inUse) {
            return $port
        }
        $port++
        if ($port -gt 65535) {
            throw "No available ports."
        }
    }
}

$backendPort = Get-FreePort -PreferredPort $BackendPort
$frontendPort = Get-FreePort -PreferredPort $FrontendPort

function Stop-UvicornProcesses {
    $existing = Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue
    if ($existing) {
        foreach ($proc in $existing) {
            Write-Host "Stopping existing uvicorn process (PID $($proc.Id))"
            Stop-Process -Id $proc.Id -Force
        }
    }
}

Stop-UvicornProcesses

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"

if (-not (Test-Path $backendDir)) {
    throw "Backend directory not found at $backendDir"
}

if (-not (Test-Path $frontendDir)) {
    throw "Frontend directory not found at $frontendDir"
}

$backendCmd = @"
cd "$backendDir"
if (Test-Path ".venv\Scripts\Activate.ps1") {
    . ".venv\Scripts\Activate.ps1"
}
uvicorn app.main:app --reload --port $backendPort
"@

$frontendCmd = @"
cd "$frontendDir"
$env:VITE_API_BASE_URL = "http://localhost:$backendPort"
npm run dev -- --host --port $frontendPort --open
"@

Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", $backendCmd
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", $frontendCmd

Write-Host "Started backend (port $backendPort) and frontend (port $frontendPort) in separate PowerShell windows."
Write-Host "Frontend API base set to http://localhost:$backendPort"
