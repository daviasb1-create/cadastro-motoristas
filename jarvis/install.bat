@echo off
REM Instala o JARVIS (sem administrador). Opcoes: -Optional -Autostart
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
pause
