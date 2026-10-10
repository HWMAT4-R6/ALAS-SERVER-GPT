$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Push-Location $taskRoot
try {
    & '.venv/Scripts/python.exe' -m src.runtime pause
    if ($LASTEXITCODE -ne 0) { throw 'Pause request failed' }
    Write-Output 'PAUSE set. Supervisor stops its child before exiting; observer may await its current API timeout. Verify events and process exit. Do not delete PAUSE until explicit resume.'
} finally { Pop-Location }
