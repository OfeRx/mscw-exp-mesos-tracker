@echo off
rem Sets up a Python 3.14 environment the first time (or after moving to a newer Python),
rem adds anything new after an update, then starts the tracker.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -c "import sys; sys.exit(sys.version_info < (3, 14))" || rmdir /s /q .venv
)
if not exist .venv\Scripts\pythonw.exe (
    py -3.14 -m venv .venv 2>nul || python -m venv .venv || goto :error
)
.venv\Scripts\python.exe -c "import sys; sys.exit(sys.version_info < (3, 14))" || goto :old
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt || goto :error
start "" .venv\Scripts\pythonw.exe -m maple_tracker
exit /b 0
:old
rmdir /s /q .venv
echo This needs Python 3.14 or newer. Install it from python.org (tick "Add python.exe to PATH") and try again.
pause
exit /b 1
:error
echo Setup failed. Install Python 3.14 or newer from python.org (tick "Add python.exe to PATH") and try again.
pause
exit /b 1
