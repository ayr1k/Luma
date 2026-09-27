@echo off
cd /d "%~dp0"
".venv-client\Scripts\python.exe" -m local_agent desktop
if errorlevel 1 pause
