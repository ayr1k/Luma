param([string]$Python = "$PSScriptRoot\..\.venv-client\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path "$PSScriptRoot\..")
& $Python -m local_agent serve
exit $LASTEXITCODE
