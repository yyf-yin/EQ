@echo off
REM Run backend tests in mock mode; output goes to work\test-latest.log
setlocal
cd /d "%~dp0.."
set CDR_MODE=mock
if not exist work mkdir work
echo RUNNING > work\test-latest.status
".venv\Scripts\python.exe" -m pytest backend/tests -q -p no:cacheprovider --basetemp=work/pytest-latest > work\test-latest.log 2>&1
echo EXIT %ERRORLEVEL% > work\test-latest.status
