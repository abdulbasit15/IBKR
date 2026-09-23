@echo off
REM ===================================================================
REM  update.bat  (Backtest Journal)
REM  Scans every strategy subfolder for *_trades.csv, builds a per-strategy
REM  analytics dashboard + AI analysis, and a comparison index across all
REM  strategies. AI is OPTIONAL — included if a Claude backend is available
REM  (Claude Code login OR ANTHROPIC_API_KEY), skipped cleanly if not.
REM  Press Ctrl+C at any time to stop and exit.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo  ==================================================
echo    BACKTEST JOURNAL - build strategy dashboards
echo  ==================================================
echo.

REM --- Non-blocking Claude check (never prompts a login) --------------
set "AISTATE=off"
where claude >nul 2>&1 && (
    claude auth status 2>nul | findstr /C:"loggedIn" | findstr /C:"true" >nul && set "AISTATE=on"
)
if "%AISTATE%"=="on" (
    echo  Claude Code: logged in - AI analysis will be included.
) else (
    echo  Claude Code not logged in - AI analysis auto-skipped
    echo    ^(unless ANTHROPIC_API_KEY is set^). Dashboards still build.
)
echo.

where py >nul 2>&1 && ( py -m journal backtest --open ) || ( python -m journal backtest --open )
if errorlevel 130 goto :aborted
echo.
pause
goto :end

:aborted
echo.
echo  Stopped (Ctrl+C). Exiting.

:end
endlocal
