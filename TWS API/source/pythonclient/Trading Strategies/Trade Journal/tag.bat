@echo off
REM ===================================================================
REM  tag.bat  -  import newest trades, ensure Claude login, then open
REM  the live tagging server (with AI coaching in the Notebook).
REM  Press Ctrl+C at any time to stop and exit.
REM ===================================================================
setlocal
cd /d "%~dp0"

where py >nul 2>&1 && (set "PY=py") || (set "PY=python")

echo.
echo  ==================================================
echo    TRADE JOURNAL - import + live tagging server
echo  ==================================================
echo.
echo  Keep "ZTH Trade Tracker - AB.xlsx" CLOSED (import + saves need it closed).
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

echo  [1/3] Importing newest orders CSV...
%PY% -m journal import
if errorlevel 130 goto :aborted
echo.
echo  [2/3] Auto-tagging setups + mistakes + economic news...
%PY% -m journal tag
if errorlevel 130 goto :aborted
echo.
echo  [3/3] Generating AI coaching + starting tagging server...
echo        (the AI step can take up to ~1 min; the browser opens after.)
echo        Press Ctrl+C to stop the server and exit.
%PY% -m journal serve
if errorlevel 130 goto :aborted
goto :end

:aborted
echo.
echo  Stopped (Ctrl+C). Exiting.
endlocal
exit /b 0

:end
endlocal
