@echo off
REM Run from within the extracted project folder.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (python -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m scripts.verify_local
pause
