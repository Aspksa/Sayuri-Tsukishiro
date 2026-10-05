@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Sayuri Tsukishiro

echo.
echo  Sayuri Tsukishiro - local launcher
echo  ---------------------------------
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_windows.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [SAYURI] Launch failed with exit code %EXIT_CODE%.
  echo [SAYURI] Check logs\launcher.log and ERRORS.md.
  echo.
  pause
)

exit /b %EXIT_CODE%
