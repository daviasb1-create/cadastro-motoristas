@echo off
REM LOGISTICS INTELLIGENCE - agendador local (07:00, 12:00, 17:00 e monitor de urgentes)
REM Deixe esta janela aberta, ou registre no Agendador de Tarefas (ver docs/INSTALACAO_WINDOWS.md)
cd /d "%~dp0"
set "LI_VENV=%LOCALAPPDATA%\LogisticsIntelligence\venv"
if not exist "%LI_VENV%\Scripts\python.exe" (
  echo Execute primeiro o iniciar_windows.bat para instalar o sistema.
  pause
  exit /b 1
)
"%LI_VENV%\Scripts\python.exe" scheduler_service.py
