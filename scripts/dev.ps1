$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'tools-env.ps1')
$inboundConfig = Join-Path $repoRoot '.secrets\inbound.env'
if (Test-Path -LiteralPath $inboundConfig) {
    foreach ($entry in Get-Content -LiteralPath $inboundConfig) {
        if ($entry -match '^(INBOUND_EMAIL_PROVIDER|INBOUND_AGENTMAIL_ADDRESS|AGENTMAIL_API_KEY|AGENTMAIL_INBOX_ID)=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
        }
    }
}
$python = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath (Join-Path $repoRoot 'frontend\node_modules\next'))) {
    throw 'Install dependencies first using scripts/setup.ps1.'
}
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
foreach ($port in @(8000, 3000)) {
    $portClient = [System.Net.Sockets.TcpClient]::new()
    $occupied = $false
    try {
        $portClient.Connect('127.0.0.1', $port)
        $occupied = $true
    } catch {
        if ($_.Exception.InnerException.SocketErrorCode -ne [System.Net.Sockets.SocketError]::ConnectionRefused) { throw }
    } finally { $portClient.Dispose() }
    if ($occupied) {
        throw "Port $port is already in use. Stop the existing server before starting another copy."
    }
}
$logDir = Join-Path $repoRoot '.tools'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$backend = Start-Process -FilePath $python -ArgumentList @('-X', 'utf8', '-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'backend.stdout.log') -RedirectStandardError (Join-Path $logDir 'backend.stderr.log')
try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $backend.Refresh()
        if ($backend.HasExited) {
            throw "Backend failed to start. See $logDir\backend.stderr.log."
        }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (!$ready) { throw 'Backend did not become ready. Check .tools/backend.stderr.log.' }
    Write-Host 'Open http://127.0.0.1:3000. Press Ctrl+C to stop.'
    Push-Location $repoRoot
    try {
        & $npm --prefix frontend run dev
        if ($LASTEXITCODE -ne 0) { throw "Frontend exited with code $LASTEXITCODE." }
    } finally { Pop-Location }
} finally {
    if (!$backend.HasExited) { Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue }
}
