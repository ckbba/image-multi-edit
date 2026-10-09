$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.env')) { throw 'Copy .env.example to .env and configure it first.' }
New-Item -ItemType Directory -Force -Path 'data' | Out-Null
$pythonCommand = (Get-Command python).Source
$editorProcess = Start-Process -FilePath $pythonCommand -ArgumentList @('-X', 'faulthandler', '-u', 'run.py') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'data/server.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data/server.stderr.log') -PassThru
$editorReady = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if ($editorProcess.HasExited) { throw 'Editor exited during startup. See data/server.stderr.log.' }
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/api/health' -TimeoutSec 1
        if ($health.ok) { $editorReady = $true; break }
    } catch { Start-Sleep -Milliseconds 200 }
}
if (-not $editorReady) { throw 'Editor health check did not succeed. See data/server.stderr.log.' }
Write-Output "Editor started. PID: $($editorProcess.Id). Open http://127.0.0.1:8787 . Login details: LOCAL_ACCESS.md"
