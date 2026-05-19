<# AI Validation Pipeline – Local Launcher (Windows) #>
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  =======================================" -ForegroundColor Cyan
Write-Host "  AI Validation Pipeline - Local Edition" -ForegroundColor Cyan
Write-Host "  =======================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.\d+") {
            $python = $cmd
            Write-Host "  [OK] $ver" -ForegroundColor Green
            break
        }
    } catch {}
}
if (-not $python) {
    Write-Host "  [ERROR] Python 3.10+ is required but not found." -ForegroundColor Red
    Write-Host "  Install from https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# 2. Check/create venv
$venvDir = Join-Path $PSScriptRoot "backend\.venv"
if (-not (Test-Path "$venvDir\Scripts\python.exe")) {
    Write-Host "  Creating virtual environment..." -ForegroundColor Yellow
    & $python -m venv $venvDir
}
$python = "$venvDir\Scripts\python.exe"
$pip = "$venvDir\Scripts\pip.exe"

# 3. Install dependencies
Write-Host "  Installing dependencies..." -ForegroundColor Yellow
& $pip install -q -r (Join-Path $PSScriptRoot "backend\requirements.txt")

# 4. Check .env
$envFile = Join-Path $PSScriptRoot "backend\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "  [WARN] .env not found. Copying from .env.example" -ForegroundColor Yellow
    Copy-Item (Join-Path $PSScriptRoot "backend\.env.example") $envFile
    Write-Host "  Please edit backend\.env with your API keys." -ForegroundColor Yellow
}

# 5. Launch
Write-Host ""
Write-Host "  Starting server on http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop." -ForegroundColor Gray
Write-Host ""

Set-Location (Join-Path $PSScriptRoot "backend")
Start-Process "http://127.0.0.1:8000" # open browser
& $python main.py
