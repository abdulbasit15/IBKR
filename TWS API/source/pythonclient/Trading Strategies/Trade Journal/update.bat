@echo off
REM ===================================================================
REM  update.bat  -  MAIN daily updater (WITH AI coaching)
REM  Ensures Claude login, imports the newest Tradovate CSV, auto-tags,
REM  refreshes the dashboard + reports (with AI), and opens it.
REM  Press Ctrl+C at any time to stop and exit.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo  ==================================================
echo    TRADE JOURNAL - full update (with AI coaching)
echo  ==================================================
echo.
echo  Close "ZTH Trade Tracker - AB.xlsx" in Excel first.
echo  Press Ctrl+C at any time to stop and exit.
echo.

REM --- Ensure Claude is logged in (needed for AI coaching) -----------
echo  Checking Claude login...
claude auth status 2>nul | findstr /C:"loggedIn" | findstr /C:"true" >nul
if errorlevel 1 (
    echo  Not logged in to Claude. Launching login ^(a browser window opens^)...
    claude auth login
)
if errorlevel 130 goto :aborted
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
