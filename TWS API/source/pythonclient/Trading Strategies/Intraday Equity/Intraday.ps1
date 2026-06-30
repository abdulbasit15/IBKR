<#
.SYNOPSIS
Build and deploy the Intraday Equity strategy bundle on Windows. 

.DESCRIPTION
This script creates or reuses a local Python virtual environment, installs
requirements, builds the one-file executable with PyInstaller, and copies
`equity.json` into the generated `dist` folder.

It assumes the script is executed from the `Intraday Equity` folder.
#>

param(
    # Explicit PyPI index URL. If omitted, the script AUTO-tries pip's default index
    # (pypi.org) first, then automatically falls back to the Aliyun mirror -- so the SAME
    # script works on open networks AND on networks where pypi.org is blocked (HTTP 403).
    # Pass a value to force one specific index/mirror.
    [string]$IndexUrl = '',

    # Mirror tried automatically when the default index fails and no -IndexUrl was given.
    # Set to '' to disable the automatic fallback.
    [string]$FallbackIndexUrl = 'https://mirrors.aliyun.com/pypi/simple/'
)

$ErrorActionPreference = 'Stop'
# pip signals failure via a non-zero exit code; handle it through $LASTEXITCODE rather than
# exceptions so the index-fallback works on BOTH Windows PowerShell 5.1 and PowerShell 7.x
# (7.4+ would otherwise throw on a native non-zero exit under ErrorActionPreference=Stop).
$PSNativeCommandUseErrorActionPreference = $false

function Write-Info($msg) {
    Write-Host "[INFO] $msg"
}

function Write-ErrorAndExit($msg) {
    Write-Host "[ERROR] $msg" -ForegroundColor Red
    exit 1
}

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
        } catch {
        }
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
    if ($LASTEXITCODE -ne 0) {
        Write-ErrorAndExit 'Failed to create virtual environment.'
    }
}

if (-not (Test-Path $venvPython)) {
    Write-ErrorAndExit 'Local virtual environment could not be initialized.'
}

# Ordered list of indexes to try. An explicit -IndexUrl wins; otherwise try the default
# PyPI first, then the Aliyun fallback -- so the same script works on open networks and on
# networks where pypi.org is blocked.
if ($IndexUrl) {
    $indexCandidates = @($IndexUrl)
} else {
    $indexCandidates = @('')                       # '' = pip's default index (pypi.org)
    if ($FallbackIndexUrl) { $indexCandidates += $FallbackIndexUrl }
}

Write-Info 'Upgrading pip and installing requirements...'
$installed = $false
foreach ($idx in $indexCandidates) {
    $pipIndexArgs = @()
    if ($idx) { $pipIndexArgs = @('-i', $idx); Write-Info "Trying package index: $idx" }
    else      { Write-Info 'Trying default PyPI (pypi.org)...' }
    & $venvPython -m pip install --upgrade pip @pipIndexArgs
    & $venvPython -m pip install -r requirements.txt @pipIndexArgs
    if ($LASTEXITCODE -eq 0) { $installed = $true; break }
    Write-Info 'That index failed; trying the next one...'
}
if (-not $installed) {
    Write-ErrorAndExit 'Failed to install requirements from all indexes. Re-run with -IndexUrl <your-mirror>.'
}

$distDir = Join-Path $scriptDir 'dist'
$buildDir = Join-Path $scriptDir 'build_pi'

if (Test-Path $distDir) {
    Write-Info 'Removing existing dist folder...'
    Remove-Item -Recurse -Force $distDir
}

if (Test-Path $buildDir) {
    Write-Info 'Removing existing build_pi folder...'
    Remove-Item -Recurse -Force $buildDir
}

Write-Info 'Building intraday_equity.exe with PyInstaller...'
$pyInstallerArgs = @(
    '--clean',
    '--onefile',
    '--name', 'intraday_equity',
    '--collect-all', 'ib_async',
    '--copy-metadata', 'ib_async',
    '--copy-metadata', 'aeventkit',
    '--collect-all', 'tzdata',
    '--collect-all', 'openpyxl',
    '--distpath', '.\dist',
    '--workpath', '.\build_pi',
    '--specpath', '.\build_pi',
    'runner.py'
)

& $venvPython -m PyInstaller @pyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    Write-ErrorAndExit 'PyInstaller build failed. See the output above for details.'
}

if (-not (Test-Path (Join-Path $distDir 'intraday_equity.exe'))) {
    Write-ErrorAndExit 'Build finished, but intraday_equity.exe was not found in dist.'
}

Write-Info 'Copying equity.json into dist...'
Copy-Item -Force 'equity.json' (Join-Path $distDir 'equity.json')

Write-Info 'Build and deploy complete.'
Write-Host "Executable available in: $distDir\intraday_equity.exe"
Write-Host "Config copy in: $distDir\equity.json"
Write-Host 'Run from the dist folder using .\intraday_equity.exe'
