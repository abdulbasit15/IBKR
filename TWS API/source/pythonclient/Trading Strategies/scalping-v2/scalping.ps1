<#
.SYNOPSIS
One script for the Scalping v2 bot (NQ / ES / GC intraday): build the exe if needed, then run it
under a supervisor that relaunches it if it ever exits.

.DESCRIPTION
  * Build  : creates/reuses .venv, installs requirements.txt (default PyPI, then the Aliyun mirror
             fallback), builds dist\scalping_v2_bot.exe with PyInstaller and self-tests it (--check).
             Runs automatically when the exe is missing, or when you pass -Build.
             The dist folder is NOT wiped: your logs, trade CSVs, state and edited configs in dist survive.
             Configs are copied into dist only if they are not there yet (-ResetConfig overwrites them).
  * Run    : supervisor loop. Launches the exe, relaunches 10 s after any exit (crash, Gateway outage).
             The bot keeps its own schedule (09:00 init, 09:35-16:00 ET decisions) and re-syncs its own
             trades from IB executions on every start, so a relaunch never double-enters.
             Stop: close the window, or create STOP.txt in this folder (checked between relaunches).
  * Reports: -Reports rebuilds dist\reports\eod_report_<date>.html + performance_report.html from the
             per-strategy trade CSVs (the bot writes them automatically after each session).
  * Live   : -Live uses dist\scalping_v2_live.json + --i-understand-live (REAL MONEY). You must type LIVE
             to confirm. Set "account" (U...) in dist\scalping_v2_live.json first.

.EXAMPLE
.\scalping.ps1
    Paper trading: build if needed, then run (supervised).

.EXAMPLE
.\scalping.ps1 -Build
    Rebuild the exe (after a code change), then run on paper.

.EXAMPLE
.\scalping.ps1 -Build -NoRun
    Rebuild only.

.EXAMPLE
.\scalping.ps1 -Live
    LIVE trading (asks for confirmation).

.EXAMPLE
.\scalping.ps1 -Reports [-Date 2026-10-12]
    Rebuild dist\reports\eod_report_<date>.html + performance_report.html (the bot also does this itself ~16:05 ET).

.EXAMPLE
.\scalping.ps1 -IndexUrl https://mirrors.aliyun.com/pypi/simple/ -Build
    Force one specific package index/mirror for the build.
#>

param(
    [switch]$Build,           # force a rebuild of dist\scalping_v2_bot.exe
    [switch]$NoRun,           # build only, do not start the bot
    [switch]$Live,            # run the LIVE config (real money) instead of paper
    [switch]$ResetConfig,     # overwrite dist\*.json with the source configs
    [switch]$Reports,         # (re)build dist\reports\eod_report_<date>.html + performance_report.html and exit
    [string]$Date = '',       # report date YYYY-MM-DD for -Reports (default today)
    [string]$IndexUrl = '',
    [string]$FallbackIndexUrl = 'https://mirrors.aliyun.com/pypi/simple/'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false     # pip/exe failures via $LASTEXITCODE (PS 5.1 + 7.x)

function Write-Info($msg) { Write-Host "[INFO] $msg" }
function Write-ErrorAndExit($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red; exit 1 }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir
$distDir  = Join-Path $scriptDir 'dist'
$buildDir = Join-Path $scriptDir 'build_pi'
$exe      = Join-Path $distDir 'scalping_v2_bot.exe'
$configs  = @('scalping_v2.json', 'scalping_v2_live.json')

# ─────────────────────────────── build ───────────────────────────────
function Get-SystemPython {
    foreach ($candidate in @('python', 'py')) {
        try {
            $versionText = & $candidate --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $versionText -match 'Python (\d+)\.(\d+)\.(\d+)') {
                return @{ Path = (Get-Command $candidate).Source; Version = $Matches[1] + '.' + $Matches[2] + '.' + $Matches[3] }
            }
        } catch {}
    }
    return $null
}

function Invoke-PyInstaller($venvPython) {
    if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }
    if (Test-Path $exe)      { Remove-Item -Force $exe }
    # tzdata is REQUIRED on Windows for the ET (zoneinfo) clock; ib_async + aeventkit need their metadata.
    # scalping_v2_core.py is bundled automatically because scalping_v2_bot.py imports it.
    $pyInstallerArgs = @('--clean', '--onefile', '--name', 'scalping_v2_bot',
        '--collect-all', 'ib_async', '--copy-metadata', 'ib_async', '--copy-metadata', 'aeventkit',
        '--collect-all', 'tzdata', '--paths', '.', '--distpath', '.\dist', '--workpath', '.\build_pi',
        '--specpath', '.\build_pi', 'scalping_v2_bot.py')
    & $venvPython -m PyInstaller @pyInstallerArgs
    if ($LASTEXITCODE -ne 0) { Write-ErrorAndExit 'PyInstaller build failed. See the output above.' }
    if (-not (Test-Path $exe)) { Write-ErrorAndExit 'Build finished, but scalping_v2_bot.exe was not found in dist.' }
}

function Test-Exe {
    Start-Sleep -Seconds 5                  # let antivirus finish scanning the fresh one-file exe
    $out = & $exe --check --config (Join-Path $scriptDir 'scalping_v2.json') 2>&1 | Out-String
    return ($out -match 'check complete')
}

function Build-Bot {
    if (Get-Process -Name 'scalping_v2_bot' -ErrorAction SilentlyContinue) {
        Write-ErrorAndExit 'scalping_v2_bot.exe is running. Stop it first (close its window / create STOP.txt), then rebuild.'
    }
    $pythonInfo = Get-SystemPython
    if (-not $pythonInfo) { Write-ErrorAndExit 'Python 3.12+ is required (python or py on PATH).' }
    $v = $pythonInfo.Version.Split('.') | ForEach-Object { [int]$_ }
    if ($v[0] -lt 3 -or ($v[0] -eq 3 -and $v[1] -lt 12)) { Write-ErrorAndExit "Python 3.12+ required, found $($pythonInfo.Version)." }
    Write-Info "Using Python $($pythonInfo.Version) at $($pythonInfo.Path)"

    $venvPython = Join-Path $scriptDir '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        Write-Info 'Creating local virtual environment...'
        & $pythonInfo.Path -m venv (Join-Path $scriptDir '.venv')
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) { Write-ErrorAndExit 'Failed to create the virtual environment.' }
    }
    if ($IndexUrl) { $indexes = @($IndexUrl) } else { $indexes = @(''); if ($FallbackIndexUrl) { $indexes += $FallbackIndexUrl } }
    $installed = $false
    foreach ($idx in $indexes) {
        $ix = @(); if ($idx) { $ix = @('-i', $idx); Write-Info "Trying package index: $idx" } else { Write-Info 'Trying default PyPI (pypi.org)...' }
        & $venvPython -m pip install --timeout 120 --retries 5 --upgrade pip @ix
        & $venvPython -m pip install --timeout 120 --retries 5 -r requirements.txt @ix
        if ($LASTEXITCODE -eq 0) { $installed = $true; break }
        Write-Info 'That index failed; trying the next one...'
    }
    if (-not $installed) { Write-ErrorAndExit 'Failed to install requirements from all indexes. Re-run with -IndexUrl <mirror>.' }

    New-Item -ItemType Directory -Force -Path $distDir | Out-Null
    Write-Info 'Building scalping_v2_bot.exe with PyInstaller...'
    Invoke-PyInstaller $venvPython
    if (-not (Test-Exe)) {                                     # one-file exes occasionally come out corrupt
        Write-Info 'Self-test failed (exe could not start) - rebuilding once...'
        Invoke-PyInstaller $venvPython
        if (-not (Test-Exe)) { Write-ErrorAndExit 'The rebuilt exe still fails --check. See the output above.' }
    }
    Write-Info 'Build OK: dist\scalping_v2_bot.exe passed --check.'
}

if ($Build -or -not (Test-Path $exe)) { Build-Bot }

# configs next to the exe: copy only when missing (keeps your edits) unless -ResetConfig
foreach ($c in $configs) {
    $dst = Join-Path $distDir $c
    if ($ResetConfig -or -not (Test-Path $dst)) {
        Copy-Item -Force (Join-Path $scriptDir $c) $dst
        Write-Info "Config copied to dist\$c"
    } elseif ((Get-FileHash $dst).Hash -ne (Get-FileHash (Join-Path $scriptDir $c)).Hash) {
        Write-Info "dist\$c differs from the source copy - keeping dist\$c (use -ResetConfig to overwrite)."
    }
}

if ($Reports) {
    $rArgs = @('--reports'); if ($Date) { $rArgs += @('--date', $Date) }
    if ($Live) { $rArgs += @('--config', (Join-Path $distDir 'scalping_v2_live.json')) }
    Push-Location $distDir; & $exe @rArgs; Pop-Location
    Write-Host "Reports folder: $(Join-Path $distDir 'reports')"
    exit 0
}

if ($NoRun) {
    Write-Host ''
    Write-Host "Ready: $exe"
    Write-Host 'Settings: dist\scalping_v2.json (paper)  /  dist\scalping_v2_live.json (live)'
    Write-Host "Tools:   cd dist;  .\scalping_v2_bot.exe --status   |   .\scalping_v2_bot.exe --test-orders NQ"
    exit 0
}

# ─────────────────────────────── run (supervised) ───────────────────────────────
$botArgs = @()
$mode = 'PAPER'
$logName = 'supervisor.log'
if ($Live) {
    $liveCfg = Join-Path $distDir 'scalping_v2_live.json'
    if (-not (Test-Path $liveCfg)) { Write-ErrorAndExit "Live config not found: $liveCfg" }
    Write-Host 'LIVE TRADING - REAL MONEY.' -ForegroundColor Yellow
    Write-Host "  Config: $liveCfg  (account must be your U-account; LIVE IB Gateway on port 4001)"
    Write-Host '  No other bot may trade NQ/ES/GC on that account. You validated on paper first.'
    $answer = Read-Host 'Type LIVE to continue'
    if ($answer -ne 'LIVE') { Write-ErrorAndExit 'Not confirmed - exiting.' }
    $botArgs = @('--config', $liveCfg, '--i-understand-live')
    $mode = 'LIVE'
    $logName = 'supervisor_live.log'
}
$log = Join-Path $distDir $logName
Write-Info "Supervisor started [$mode]. Stop: close this window or create STOP.txt in $scriptDir"
while ($true) {
    if (Test-Path (Join-Path $scriptDir 'STOP.txt')) {
        "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  STOP.txt present - supervisor exiting" | Tee-Object -Append $log
        break
    }
    "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  launching scalping_v2_bot.exe [$mode]" | Tee-Object -Append $log
    & $exe @botArgs
    $code = $LASTEXITCODE
    "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  bot exited (code $code) - restarting in 10s" | Tee-Object -Append $log
    Start-Sleep -Seconds 10
}
