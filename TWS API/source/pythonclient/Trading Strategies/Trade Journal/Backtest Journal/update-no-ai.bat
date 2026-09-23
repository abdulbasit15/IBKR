@echo off
REM ===================================================================
REM  update-no-ai.bat  (Backtest Journal)  -  fast, no Claude call.
REM  Builds per-strategy dashboards + comparison index from *_trades.csv,
REM  skipping the AI analysis entirely. Press Ctrl+C to stop and exit.
REM ===================================================================
setlocal
cd /d "%~dp0"
echo.
echo  =====================================================
echo    BACKTEST JOURNAL - build dashboards (NO AI, fast)
echo  =====================================================
echo.
where py >nul 2>&1 && ( py -m journal backtest --open --no-ai ) || ( python -m journal backtest --open --no-ai )
if errorlevel 130 goto :aborted
echo.
pause
goto :end

:aborted
echo.
echo  Stopped (Ctrl+C). Exiting.

:end
endlocal
