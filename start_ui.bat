@echo off
setlocal
set PORT=8080

echo ================================================
echo   CedarToy Web UI Startup
echo ================================================
echo.
echo Killing any process listening on port %PORT% ...

REM netstat lists LISTENING sockets; the last column is the PID. Some rows
REM (UDP, no-PID) get skipped by checking the PID is numeric.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo   - PID %%P
    taskkill /F /PID %%P >nul 2>&1
)

echo Starting server on http://localhost:%PORT%
echo Press Ctrl+C to stop the server
echo.
echo ================================================
echo.

cd /d "%~dp0"
python -m cedartoy.cli ui

pause
