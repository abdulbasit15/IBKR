@echo off
REM ===================================================================
REM  update-no-ai.bat  -  full update WITHOUT AI (fast, no login needed)
REM  Imports the newest Tradovate CSV, auto-tags, refreshes the
REM  dashboard + reports, and opens it. Skips the Claude coaching call.
REM  Press Ctrl+C at any time to stop and exit.
REM ===================================================================
setlocal
cd /d "%~dp0"
echo.
echo  =====================================================
echo    TRADE JOURNAL - full update (NO AI, fast)
echo  =====================================================
echo.
echo  Close "ZTH Trade Tracker - AB.xlsx" in Excel first.
echo  Press Ctrl+C at any time to stop and exit.
echo.
where py >nul 2>&1 && ( py -m journal all --open --no-ai ) || ( python -m journal all --open --no-ai )
if errorlevel 130 goto :aborted
echo.
pause
goto :end

:aborted
echo.
echo  Stopped (Ctrl+C). Exiting.

:end
endlocal
