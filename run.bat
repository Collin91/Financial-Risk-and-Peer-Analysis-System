@echo off
rem Starts the program with the environment created by setup.bat. Any options are passed through,
rem e.g.  run.bat --industry automotive --target Tesla --peers Ford Toyota --years 2021-2025
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" main.py %*
