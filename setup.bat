@echo off
rem One-time setup on Windows: finds Python 3.9 or newer, creates a private environment in .venv
rem and installs the required packages there. Afterwards start the program with run.bat.
setlocal
cd /d "%~dp0"

set "PY="
rem Prefer the Python launcher (py), which can pick a specific version even if an older Python is first on PATH.
for %%v in (3.14 3.13 3.12 3.11 3.10 3.9) do (
    if not defined PY (
        py -%%v -c "" >nul 2>&1 && set "PY=py -%%v"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo Python 3.9 or newer was not found.
    echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
    echo then open a new window and run setup.bat again.
    exit /b 1
)

echo Using:
%PY% --version
echo Creating the environment in .venv ...
%PY% -m venv .venv || goto :failed
echo Installing packages ^(this can take a few minutes^) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :failed

echo.
echo Setup complete. Start the program with:  run.bat
exit /b 0

:failed
echo.
echo Setup failed; see the messages above.
exit /b 1
