<#
  Generates the two HTML reports from the bot's trade logs. Schedule this DAILY after the
  session close (e.g. 17:15 local, a bit after the 17:00 ET Globex/COMEX daily settlement).
  reports.py is pure stdlib and auto-finds the trade CSVs in .\dist and writes .\dist\reports\:
     - eod_report_<YYYYMMDD>.html   (today, per instrument)
     - performance_report.html      (cumulative to date, per instrument)
  Run manually anytime:  .\daily_reports.ps1
#>
$ErrorActionPreference = 'Continue'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir
$py = 'py'; $pyArgs = @('-3.12')
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { $py = 'python'; $pyArgs = @() }
& $py @pyArgs (Join-Path $scriptDir 'reports.py') --capital 100000
Write-Host "Reports written to $(Join-Path $scriptDir 'dist\reports')"
