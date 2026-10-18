@echo off
rem Sets up a Python environment the first time (and adds anything new after an update),
rem then starts the tracker.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
    py -3 -m venv .venv 2>/dev/null || python -m venv .venv || goto :error
)
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt || goto :error
start "" .venv\Scripts\pythonw.exe -m maple_tracker
exit /b 0
:error
echo Setup failed. Install Python 3.10 or newer from python.org (tick "Add python.exe to PATH") and try again.
pause
