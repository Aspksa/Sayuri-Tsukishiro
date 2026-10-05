@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Саюри Цукисиро

echo.
echo  Саюри Цукисиро - локальный запуск
echo  ---------------------------------
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_windows.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [САЮРИ] Запуск завершился с ошибкой, код %EXIT_CODE%.
  echo [САЮРИ] Проверьте logs\launcher.log и ERRORS.md.
  echo.
  pause
)

exit /b %EXIT_CODE%
