@echo off
REM ===================================================================
REM  update.bat  -  MAIN daily updater
REM  Imports the newest Tradovate CSV, auto-tags, refreshes the
REM  dashboard + reports, and opens it. AI coaching is OPTIONAL — it is
REM  included automatically if a Claude backend is available (Claude Code
REM  login OR ANTHROPIC_API_KEY), and skipped cleanly if not.
REM  Press Ctrl+C at any time to stop and exit.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo  ==================================================
echo    TRADE JOURNAL - full update
echo  ==================================================
echo.
echo  Close "ZTH Trade Tracker - AB.xlsx" in Excel first.
echo  Press Ctrl+C at any time to stop and exit.
echo.

REM --- Non-blocking Claude check (never prompts a login) --------------
set "AISTATE=off"
where claude >nul 2>&1 && (
    claude auth status 2>nul | findstr /C:"loggedIn" | findstr /C:"true" >nul && set "AISTATE=on"
)
if "%AISTATE%"=="on" (
    echo  Claude Code: logged in - AI coaching will be included.
) else (
    echo  Claude Code not logged in - the tool will auto-skip AI coaching
    echo    ^(unless ANTHROPIC_API_KEY is set^). Everything else still runs.
    echo    To enable AI: run "claude" once to log in, or set ANTHROPIC_API_KEY.
)
echo.

where py >nul 2>&1 && ( py -m journal all --open ) || ( python -m journal all --open )
if errorlevel 130 goto :aborted
echo.
pause
goto :end

:aborted
echo.
echo  Stopped (Ctrl+C). Exiting.

:end
endlocal
