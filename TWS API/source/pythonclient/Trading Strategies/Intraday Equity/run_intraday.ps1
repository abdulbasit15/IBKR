<#
  Supervisor for the Intraday Equity bot — keeps it running continuously.
  Launches dist\intraday_equity.exe and relaunches it if it ever exits (crash, kill, or a
  Gateway outage the bot couldn't recover from). The bot itself already auto-reconnects across
  IB Gateway restarts (fast-then-backoff, until the EOD flatten time) and stays dormant on
  non-trading days; this wrapper is the outer safety net so it's ALWAYS running.

  Run manually:   .\run_intraday.ps1
  Or schedule at logon (see setup notes). Stop it by closing the window, or create a file named
  STOP.txt in this folder (checked between relaunches).
#>
$ErrorActionPreference = 'Continue'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir
$exe = Join-Path $scriptDir 'dist\intraday_equity.exe'
$log = Join-Path $scriptDir 'dist\supervisor.log'
if (-not (Test-Path $exe)) { Write-Host "Bot exe not found: $exe  (build it with .\Intraday.ps1)"; exit 1 }

while ($true) {
    if (Test-Path (Join-Path $scriptDir 'STOP.txt')) { "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  STOP.txt present — supervisor exiting" | Tee-Object -Append $log; break }
    "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  launching intraday_equity.exe" | Tee-Object -Append $log
    & $exe
    $code = $LASTEXITCODE
    "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  bot exited (code $code) — restarting in 10s" | Tee-Object -Append $log
    Start-Sleep -Seconds 10
}
