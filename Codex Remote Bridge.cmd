@echo off
cd /d "%~dp0"
if not exist "%~dp0config\.env" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
  if errorlevel 1 pause
  if not errorlevel 1 start "" "http://127.0.0.1:8765/"
  exit /b %errorlevel%
)
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0tray.ps1"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/"
