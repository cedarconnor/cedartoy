@echo off
echo ================================================
echo   CedarToy Web UI Startup
echo ================================================
echo.
echo Starting server on http://localhost:8080
echo Press Ctrl+C to stop the server
echo.
echo ================================================
echo.

cd /d "%~dp0"
python -m cedartoy.cli ui

pause
