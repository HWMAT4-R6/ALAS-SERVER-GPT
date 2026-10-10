param([ValidateSet('supervisor','observer')][string]$Mode = 'supervisor', [switch]$HomeVerified)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create project .venv first (README).' }
$taskSettings = Join-Path $taskRoot 'config/settings.json'
$taskArguments = @('-m', 'src.runtime', $Mode, '--config', $taskSettings)
if ($Mode -eq 'supervisor') {
    if (-not $HomeVerified) { throw 'Fresh screenshot/home verification required: -HomeVerified' }
    $taskArguments += '--home-verified'
}
# Quote arguments for Windows Start-Process; keep the configured working directory.
$taskQuoted = $taskArguments | ForEach-Object { '"' + $_ + '"' }
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList $taskQuoted -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru
Write-Output "Started launcher PID $($taskProcess.Id). Check runtime/events.jsonl for success; launcher creation alone is not success."
