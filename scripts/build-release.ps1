param([Parameter(Mandatory=$true)][string]$InnoCompiler,
      [Parameter(Mandatory=$true)][string]$LTSDirectory,
      [string]$PythonExe = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$ltsRoot = (Resolve-Path -LiteralPath $LTSDirectory).Path
if (!(Test-Path -LiteralPath (Join-Path $ltsRoot 'packaging\LocalAgent.spec'))) { throw 'LTS source directory is incomplete' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$buildRoot = Join-Path $projectRoot "build\$stamp"
$releaseRoot = Join-Path $projectRoot "dist\$stamp"
# Unique output directories preserve prior artifacts; no cleanup of existing releases.
& $PythonExe -m PyInstaller --noconfirm --distpath (Join-Path $releaseRoot 'latest') --workpath (Join-Path $buildRoot 'latest') (Join-Path $projectRoot 'packaging\LocalAgent.spec')
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
& $PythonExe -m PyInstaller --noconfirm --distpath (Join-Path $releaseRoot 'lts') --workpath (Join-Path $buildRoot 'lts') (Join-Path $ltsRoot 'packaging\LocalAgent.spec')
if ($LASTEXITCODE -ne 0) { throw 'LTS executable build failed' }
& $InnoCompiler ('/DLTSPresetSource=' + $ltsRoot) ('/DSourceDir=' + (Join-Path $releaseRoot 'latest\Luma')) ('/DLTSSourceDir=' + (Join-Path $releaseRoot 'lts\Luma')) ('/DOutputDir=' + $releaseRoot) (Join-Path $projectRoot 'packaging\installer-channels.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
$installers = @(Get-ChildItem -LiteralPath $releaseRoot -Filter 'Luma-Setup-*.exe')
if ($installers.Count -ne 1) { throw 'Expected one combined installer' }
$digest = (Get-FileHash -LiteralPath $installers[0].FullName -Algorithm SHA256).Hash.ToLower()
Set-Content -LiteralPath (Join-Path $releaseRoot 'SHA256SUMS.txt') -Value ($digest + '  ' + $installers[0].Name) -Encoding ascii
Write-Output "Release created in $releaseRoot"
