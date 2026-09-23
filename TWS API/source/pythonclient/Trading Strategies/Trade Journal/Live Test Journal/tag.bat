@echo off
REM ===================================================================
REM  tag.bat  -  import newest trades, then open the live tagging server.
REM  AI coaching in the Notebook is OPTIONAL — included automatically if a
REM  Claude backend is available (Claude Code login OR ANTHROPIC_API_KEY),
REM  and skipped cleanly if not. No blocking login prompt.
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

REM --- Non-blocking Claude check (never prompts a login) --------------
set "AISTATE=off"
where claude >nul 2>&1 && (
    claude auth status 2>nul | findstr /C:"loggedIn" | findstr /C:"true" >nul && set "AISTATE=on"
)
if "%AISTATE%"=="on" (
    echo  Claude Code: logged in - AI coaching will be included.
) else (
    echo  Claude Code not logged in - AI coaching auto-skipped
    echo    ^(unless ANTHROPIC_API_KEY is set^). Everything else still runs.
)
echo.

echo  [1/3] Importing newest orders CSV...
%PY% -m journal import
if errorlevel 130 goto :aborted
echo.
echo  [2/3] Auto-tagging setups + mistakes + economic news + indicators...
%PY% -m journal tag
if errorlevel 130 goto :aborted
echo.
echo  [3/3] Starting the live tagging server (AI coaching if available)...
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
