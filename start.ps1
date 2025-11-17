param(
    [switch]$InstallOnly
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$venvPath = Join-Path $backendDir ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$requirementsFile = Join-Path $backendDir "requirements.txt"
$nodeModules = Join-Path $frontendDir "node_modules"

function Ensure-Venv {
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating Python virtual environment (.venv)..."
        Push-Location $backendDir
        try {
            py -3.11 -m venv .venv
        } finally {
            Pop-Location
        }
    }

    Write-Host "Installing/updating backend dependencies..."
    & $venvPython -m pip install -r $requirementsFile
}

function Ensure-NodeModules {
    if (-not (Test-Path $nodeModules)) {
        Write-Host "Installing frontend dependencies..."
        Push-Location $frontendDir
        try {
            npm install
        } finally {
            Pop-Location
        }
    }
}

Ensure-Venv
Ensure-NodeModules

if ($InstallOnly) {
    Write-Host "`nDependencies installed. Re-run without -InstallOnly to start the servers."
    exit 0
}

Write-Host "Launching FastAPI backend..."
Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location -LiteralPath '$backendDir'; & '$venvPath\Scripts\Activate.ps1'; uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
) | Out-Null

Write-Host "Launching React frontend..."
Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location -LiteralPath '$frontendDir'; npm run dev"
) | Out-Null

Write-Host "`nBackend listening at http://localhost:8000 and frontend at http://localhost:5173."
Write-Host "Two terminals were opened; press Ctrl+C in each to stop the processes."
