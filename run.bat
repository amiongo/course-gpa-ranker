@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 app.py
) else (
  python app.py
)
if errorlevel 1 (
  echo.
  echo Failed to start. Install Python 3.10 or newer, then run this file again.
  pause
)
