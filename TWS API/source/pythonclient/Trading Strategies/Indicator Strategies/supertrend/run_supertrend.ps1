<#
.SYNOPSIS
Supervisor / keep-alive launcher for the Supertrend bot.

.DESCRIPTION
Complements the IB Gateway built-in "Auto Restart" (Configure -> Lock and Exit). This script:
  1. Launches dist\supertrend_bot.exe and RESTARTS it automatically if it ever exits
     (with a crash-loop guard so a hard-failing exe can't hot-loop).
  2. Watches the bot's own logs (dist\logs\*.log) for the "DATA FARM STUCK" alert the bot
     raises when client-side reconnects can't clear a GATEWAY-level HMDS data-farm zombie,
     and pops a desktop message box so you know to RESTART / RE-LOGIN IB Gateway.

It does NOT (and cannot) restart IB Gateway itself or re-login for you -- that needs the
Gateway's Auto Restart setting (session reused, ~1 re-auth/week) or IBC. See the chat notes.

.EXAMPLE
.\run_supertrend.ps1
    Supervise the PAPER bot (dist\supertrend.json).

.EXAMPLE
.\run_supertrend.ps1 -Config supertrend.live.json
    Supervise using a different config that sits next to the exe in dist\.
#>

param(
    # Config file name (resolved next to the exe in dist\) or an absolute path. The exe reads
    # dist\supertrend.json when no arg is given; pass supertrend.live.json to run live.
    [string]$Config = "supertrend.json",

    # Folder holding supertrend_bot.exe (and its logs\ subfolder). Defaults to .\dist next to this script.
    [string]$ExeDir = "",

    # How often (seconds) to check the process is alive and scan logs for the stuck-farm alert.
    [int]$PollSeconds = 30,

    # Crash-loop guard: if the exe exits more than this many times within CrashWindowMin minutes,
    # pause for CrashWindowMin minutes (and alert) instead of restarting immediately.
    [int]$MaxRestarts = 5,
    [int]$CrashWindowMin = 10
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if ([string]::IsNullOrWhiteSpace($ExeDir)) { $ExeDir = Join-Path $scriptDir "dist" }
$exe    = Join-Path $ExeDir "supertrend_bot.exe"
$logDir = Join-Path $ExeDir "logs"
$supLog = Join-Path $ExeDir ("supervisor_{0:yyyyMMdd}.log" -f (Get-Date))

if (-not (Test-Path $exe)) { Write-Host "[ERROR] exe not found: $exe  (run supertrend.ps1 to build)" -ForegroundColor Red; exit 1 }
# Resolve the config path the same way the exe does (relative = next to the exe).
$cfgPath = if ([System.IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $ExeDir $Config }
if (-not (Test-Path $cfgPath)) { Write-Host "[ERROR] config not found: $cfgPath" -ForegroundColor Red; exit 1 }

function Write-Sup([string]$msg, [string]$color = "Gray") {
    $line = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $msg
    Write-Host $line -ForegroundColor $color
    Add-Content -Path $supLog -Value $line -Encoding UTF8
}

# Non-blocking desktop alert. msg.exe ships on Windows Pro/Enterprise and pops a box in the
# user's session without a message loop; fall back to a console beep if it's unavailable.
function Show-Alert([string]$text) {
    try { & msg.exe * /TIME:600 $text 2>$null } catch { }
    try { [console]::Beep(880, 600) } catch { }
}

Write-Sup "supervisor starting | exe=$exe | config=$cfgPath" "Cyan"

$restartTimes = New-Object System.Collections.Generic.List[datetime]
$lastAlert    = [datetime]::MinValue       # throttle the stuck-farm popup
$proc         = $null

# Only scan log lines written AFTER the supervisor starts, so we don't re-alert on history.
$scanFrom = Get-Date

while ($true) {
    # --- (1) keep the bot alive -------------------------------------------------------------
    $running = Get-Process -Name "supertrend_bot" -ErrorAction SilentlyContinue
    if (-not $running) {
        # crash-loop guard: count restarts inside the rolling window
        $cutoff = (Get-Date).AddMinutes(-$CrashWindowMin)
        $restartTimes = [System.Collections.Generic.List[datetime]]($restartTimes | Where-Object { $_ -gt $cutoff })
        if ($restartTimes.Count -ge $MaxRestarts) {
            Write-Sup "CRASH LOOP: $($restartTimes.Count) restarts in $CrashWindowMin min -> pausing $CrashWindowMin min" "Red"
            Show-Alert "Supertrend bot is crash-looping ($($restartTimes.Count)x in $CrashWindowMin min). Check dist\logs. Paused."
            Start-Sleep -Seconds ($CrashWindowMin * 60)
            $restartTimes.Clear()
            continue
        }
        Write-Sup "bot not running -> launching" "Yellow"
        # Start in $ExeDir so logs/state/CSVs resolve next to the exe.
        $proc = Start-Process -FilePath $exe -ArgumentList "`"$cfgPath`"" -WorkingDirectory $ExeDir -PassThru
        $restartTimes.Add((Get-Date))
        Start-Sleep -Seconds 5
    }

    # --- (2) watch for the stuck-farm alert in the bot's logs -------------------------------
    try {
        $logs = Get-ChildItem -Path $logDir -Filter "*.log" -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -gt $scanFrom.AddMinutes(-1) }
        foreach ($lf in $logs) {
            # tail only; the bot throttles the alert to every 10 min so a few lines is plenty
            $hits = Get-Content -Path $lf.FullName -Tail 40 -ErrorAction SilentlyContinue |
                    Where-Object { $_ -match "DATA FARM STUCK" }
            if ($hits -and ((Get-Date) - $lastAlert).TotalMinutes -ge 10) {
                $lastAlert = Get-Date
                $msg = "IB DATA FARM STUCK -- the bot cannot get fresh bars. RESTART / RE-LOGIN IB GATEWAY. (positions are held by native stops; no new trades until data is current)"
                Write-Sup $msg "Red"
                Show-Alert $msg
            }
        }
    } catch { Write-Sup "log-scan error: $($_.Exception.Message)" "DarkYellow" }

    Start-Sleep -Seconds $PollSeconds
}
