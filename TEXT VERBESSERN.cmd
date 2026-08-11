@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1"
if errorlevel 1 (
  echo.
  echo Der Start ist fehlgeschlagen. Die Fehlermeldung steht oben.
  pause
)
