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
        Write-Host "创建 Python 虚拟环境 (.venv)..."
        Push-Location $backendDir
        try {
            py -3.11 -m venv .venv
        } finally {
            Pop-Location
        }
    }

    Write-Host "安装/更新后端依赖..."
    & $venvPython -m pip install -r $requirementsFile
}

function Ensure-NodeModules {
    if (-not (Test-Path $nodeModules)) {
        Write-Host "安装前端依赖..."
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
    Write-Host "`n依赖安装完成，可以使用 -InstallOnly 以外的方式启动服务。"
    exit 0
}

Write-Host "启动 FastAPI 后端..."
Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location -LiteralPath '$backendDir'; & '$venvPath\Scripts\Activate.ps1'; uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
) | Out-Null

Write-Host "启动 React 前端..."
Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location -LiteralPath '$frontendDir'; npm run dev"
) | Out-Null

Write-Host "`n后端监听 http://localhost:8000 ，前端监听 http://localhost:5173 。"
Write-Host "两个终端已打开，可按 Ctrl+C 停止各自进程。"
