<#
  Supervisor for the Qullamaggie bot — keeps it running continuously.
  Launches dist\qm_bot.exe and relaunches it if it ever exits (crash, kill, or a Gateway
  outage). The bot manages its own daily schedule (entry ~09:40 ET, manage ~15:50 ET) and
  reconciles state with IB on startup, so a relaunch never double-enters. This wrapper is the
  outer safety net so it's ALWAYS running.

  Run manually:   .\run_qm.ps1
  Stop it by closing the window, or create a file named STOP.txt in this folder
  (checked between relaunches).
#>
$ErrorActionPreference = 'Continue'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir
$exe = Join-Path $scriptDir 'dist\qm_bot.exe'
$log = Join-Path $scriptDir 'dist\supervisor.log'
if (-not (Test-Path $exe)) { Write-Host "Bot exe not found: $exe  (build it with .\qm.ps1)"; exit 1 }

while ($true) {
    if (Test-Path (Join-Path $scriptDir 'STOP.txt')) {
        "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  STOP.txt present — supervisor exiting" | Tee-Object -Append $log
        break
    }
    "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  launching qm_bot.exe" | Tee-Object -Append $log
    & $exe
    $code = $LASTEXITCODE
    "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  bot exited (code $code) — restarting in 10s" | Tee-Object -Append $log
    Start-Sleep -Seconds 10
}
