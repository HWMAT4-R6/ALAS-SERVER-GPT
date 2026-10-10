$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Push-Location $taskRoot
try {
    Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion
    Get-CimInstance Win32_Processor | Select-Object Name,VirtualizationFirmwareEnabled
    Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber
    & '.venv/Scripts/python.exe' -m src.runtime doctor
    if ($LASTEXITCODE -ne 0) { throw 'Environment checks failed; review output.' }
} finally { Pop-Location }
