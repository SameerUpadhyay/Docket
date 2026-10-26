param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    if (!(Test-Path -LiteralPath 'backend\.venv\Scripts\python.exe')) {
        & $Python -m venv backend/.venv
        if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
    }
    & backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt -r backend/tests/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    & npm.cmd ci --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    Write-Host 'Ready. Run: powershell -ExecutionPolicy Bypass -File scripts/dev.ps1'
} finally { Pop-Location }
