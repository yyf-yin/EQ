@echo off
setlocal EnableExtensions

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "exitCode=%ERRORLEVEL%"

if not "%exitCode%"=="0" (
    echo.
    echo Startup failed. Exit code: %exitCode%
    pause
)

exit /b %exitCode%
