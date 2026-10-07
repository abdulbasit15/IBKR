<#
.SYNOPSIS
Build and deploy the Qullamaggie LONG-only bot on Windows.

.DESCRIPTION
Creates or reuses a local Python virtual environment, installs requirements,
builds the one-file executable (qm_bot.exe) with PyInstaller, and copies
qm_bot.json into the generated dist folder. Mirrors the sibling supertrend
build script.

The bot itself is stdlib + ib_async; the broad daily scan pulls Yahoo/Stooq via
urllib and the universe list from api.nasdaq.com (no PyPI needed at runtime).
PyInstaller bundles the local helper modules (universe.py, qm_long_backtest.py)
automatically because qm_bot.py imports them.

Assumes it is executed from the Qullamaggie folder.

.EXAMPLE
.\qm.ps1
    Build the exe. Auto: tries default PyPI, then the Aliyun mirror fallback.

.EXAMPLE
.\qm.ps1 -Run
    Build (if needed) and then launch the bot from dist (foreground).

.EXAMPLE
.\qm.ps1 -IndexUrl https://mirrors.aliyun.com/pypi/simple/
    Force one specific package index/mirror.
#>

param(
    # Explicit PyPI index URL. If omitted, tries pip's default index (pypi.org) first,
    # then automatically falls back to the Aliyun mirror -- so the same script works on
    # open networks AND on networks where pypi.org is blocked (HTTP 403).
    [string]$IndexUrl = '',

    # Mirror tried automatically when the default index fails and no -IndexUrl was given.
    # Set to '' to disable the automatic fallback.
    [string]$FallbackIndexUrl = 'https://mirrors.aliyun.com/pypi/simple/',

    # After building, launch dist\qm_bot.exe (foreground) instead of just exiting.
    [switch]$Run
)

$ErrorActionPreference = 'Stop'
# pip signals failure via a non-zero exit code; handle it through $LASTEXITCODE rather than
# exceptions so the index-fallback works on BOTH Windows PowerShell 5.1 and PowerShell 7.x.
$PSNativeCommandUseErrorActionPreference = $false

function Write-Info($msg) { Write-Host "[INFO] $msg" }
function Write-ErrorAndExit($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red; exit 1 }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

function Get-SystemPython {
    $candidates = @('python', 'py')
    foreach ($candidate in $candidates) {
        try {
            $versionText = & $candidate --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $versionText -match 'Python (\d+)\.(\d+)\.(\d+)') {
                return @{ Path = (Get-Command $candidate).Source; Version = $Matches[1] + '.' + $Matches[2] + '.' + $Matches[3] }
            }
        } catch {}
    }
    return $null
}

$pythonInfo = Get-SystemPython
if (-not $pythonInfo) {
    Write-ErrorAndExit 'Python 3.12+ is required. Install Python and ensure python or py is on PATH.'
}
$versionParts = $pythonInfo.Version.Split('.') | ForEach-Object { [int]$_ }
if ($versionParts[0] -lt 3 -or ($versionParts[0] -eq 3 -and $versionParts[1] -lt 12)) {
    Write-ErrorAndExit "Python 3.12+ is required. Found Python $($pythonInfo.Version)."
}
Write-Info "Using Python $($pythonInfo.Version) at $($pythonInfo.Path)"

$venvPath = Join-Path $scriptDir '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    Write-Info 'Creating local virtual environment...'
    & $pythonInfo.Path -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { Write-ErrorAndExit 'Failed to create virtual environment.' }
}
if (-not (Test-Path $venvPython)) { Write-ErrorAndExit 'Local virtual environment could not be initialized.' }

# Ordered list of indexes to try. Explicit -IndexUrl wins; otherwise default PyPI then the mirror.
if ($IndexUrl) { $indexCandidates = @($IndexUrl) }
else {
    $indexCandidates = @('')                         # '' = pip's default index (pypi.org)
    if ($FallbackIndexUrl) { $indexCandidates += $FallbackIndexUrl }
}

Write-Info 'Upgrading pip and installing requirements...'
$pipNetArgs = @('--timeout', '120', '--retries', '5')
$installed = $false
foreach ($idx in $indexCandidates) {
    $pipIndexArgs = @()
    if ($idx) { $pipIndexArgs = @('-i', $idx); Write-Info "Trying package index: $idx" }
    else      { Write-Info 'Trying default PyPI (pypi.org)...' }
    & $venvPython -m pip install @pipNetArgs --upgrade pip @pipIndexArgs
    & $venvPython -m pip install @pipNetArgs -r requirements.txt @pipIndexArgs
    if ($LASTEXITCODE -eq 0) { $installed = $true; break }
    Write-Info 'That index failed; trying the next one...'
}
if (-not $installed) {
    Write-ErrorAndExit 'Failed to install requirements from all indexes. Re-run with -IndexUrl <your-mirror>.'
}

$distDir = Join-Path $scriptDir 'dist'
$buildDir = Join-Path $scriptDir 'build_pi'
if (Test-Path $distDir)  { Write-Info 'Removing existing dist folder...';     Remove-Item -Recurse -Force $distDir }
if (Test-Path $buildDir) { Write-Info 'Removing existing build_pi folder...'; Remove-Item -Recurse -Force $buildDir }

Write-Info 'Building qm_bot.exe with PyInstaller...'
# tzdata is REQUIRED on Windows for the ET (zoneinfo) clock. ib_async + aeventkit need their
# package metadata. The local helper modules (universe.py, qm_long_backtest.py) are picked up
# automatically from this folder because qm_bot.py imports them; --paths . makes that explicit.
$pyInstallerArgs = @(
    '--clean',
    '--onefile',
    '--name', 'qm_bot',
    '--collect-all', 'ib_async',
    '--copy-metadata', 'ib_async',
    '--copy-metadata', 'aeventkit',
    '--collect-all', 'tzdata',
    '--paths', '.',
    '--distpath', '.\dist',
    '--workpath', '.\build_pi',
    '--specpath', '.\build_pi',
    'qm_bot.py'
)
& $venvPython -m PyInstaller @pyInstallerArgs
if ($LASTEXITCODE -ne 0) { Write-ErrorAndExit 'PyInstaller build failed. See the output above for details.' }
if (-not (Test-Path (Join-Path $distDir 'qm_bot.exe'))) {
    Write-ErrorAndExit 'Build finished, but qm_bot.exe was not found in dist.'
}

Write-Info 'Copying qm_bot.json into dist...'
Copy-Item -Force 'qm_bot.json' (Join-Path $distDir 'qm_bot.json')
if (Test-Path 'qm_live.json') {
    Write-Info 'Copying qm_live.json into dist...'
    Copy-Item -Force 'qm_live.json' (Join-Path $distDir 'qm_live.json')
}

Write-Info 'Build and deploy complete.'
Write-Host "Executable available in: $distDir\qm_bot.exe"
Write-Host "Config copy in: $distDir\qm_bot.json  (edit this one; it sits next to the exe)"
Write-Host ''
Write-Host 'Sanity-check the build (no IB needed):'
Write-Host "  cd `"$distDir`";  .\qm_bot.exe --check"
Write-Host "  .\qm_bot.exe --scan-only"
Write-Host 'Then, with IB Gateway running (paper 4002):  .\qm_bot.exe --once'

if ($Run) {
    Write-Info 'Launching qm_bot.exe (foreground)...'
    Set-Location $distDir
    & (Join-Path $distDir 'qm_bot.exe')
}
