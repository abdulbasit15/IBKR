<#
  Supervisor for the QM bot on the LIVE account (REAL MONEY). Relaunches dist\qm_bot.exe on exit.
  Uses qm_live.json (paper:false, port 4001) and passes --i-understand-live (required for a live account).

  BEFORE RUNNING:
    * Set "account" in qm_live.json to your live U-account.
    * Make sure the LIVE IB Gateway is logged in on port 4001.
    * Start small (qm_live.json ships $10k/strategy, 1% risk, 5% daily-loss breaker). Scale up later.
    * You validated on paper first. No live account without LPL pre-clearance.

  Run:   .\run_qm_live.ps1
  Stop:  close the window, or create STOP.txt in this folder (checked between relaunches).
#>
$ErrorActionPreference = 'Continue'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir
$exe = Join-Path $scriptDir 'dist\qm_bot.exe'
$cfg = Join-Path $scriptDir 'dist\qm_live.json'
$log = Join-Path $scriptDir 'dist\supervisor_live.log'
if (-not (Test-Path $exe)) { Write-Host "Bot exe not found: $exe  (build it with .\qm.ps1)"; exit 1 }
if (-not (Test-Path $cfg)) { Write-Host "Live config not found: $cfg  (run .\qm.ps1 to copy qm_live.json into dist)"; exit 1 }

Write-Host "LIVE trading supervisor. Config: $cfg" -ForegroundColor Yellow
while ($true) {
    if (Test-Path (Join-Path $scriptDir 'STOP.txt')) {
        "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  STOP.txt present - supervisor exiting" | Tee-Object -Append $log
        break
    }
    "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  launching qm_bot.exe [LIVE]" | Tee-Object -Append $log
    & $exe --config $cfg --i-understand-live
    $code = $LASTEXITCODE
    "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  bot exited (code $code) - restarting in 10s" | Tee-Object -Append $log
    Start-Sleep -Seconds 10
}
