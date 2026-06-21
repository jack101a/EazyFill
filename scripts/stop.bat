@echo off
echo Stopping Unified Platform Backend...
wmic process where "name='python.exe' and CommandLine like '%%uvicorn%%'" delete >nul 2>&1
echo.
echo Backend stopped.
pause
