param([Parameter(Mandatory=$true)][string]$InnoCompiler)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$pythonExe = Join-Path $projectRoot '.venv-client\Scripts\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$buildRoot = Join-Path $projectRoot "build\$stamp"
$releaseRoot = Join-Path $projectRoot "dist\$stamp"
# Unique output directories preserve prior artifacts; no cleanup of existing releases.
& $pythonExe -m PyInstaller --distpath $releaseRoot --workpath $buildRoot (Join-Path $projectRoot 'packaging\LocalAgent.spec')
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
& $InnoCompiler ('/DSourceDir=' + (Join-Path $releaseRoot 'Luma')) ('/DOutputDir=' + $releaseRoot) (Join-Path $projectRoot 'packaging\installer.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
Write-Output "Release created in $releaseRoot"
