@echo off
cd /d "%~dp0"
.\venv\Scripts\python voice_type_lite.py
if errorlevel 1 pause
