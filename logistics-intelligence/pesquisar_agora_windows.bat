@echo off
REM Executa uma pesquisa imediatamente (usado tambem pelo Agendador de Tarefas do Windows)
REM Uso: pesquisar_agora_windows.bat            -> pesquisa completa
REM      pesquisar_agora_windows.bat urgente    -> monitor de urgentes
cd /d "%~dp0"
set "LI_VENV=%LOCALAPPDATA%\LogisticsIntelligence\venv"
if not exist "%LI_VENV%\Scripts\python.exe" (
  echo Execute primeiro o iniciar_windows.bat para instalar o sistema.
  exit /b 1
)
if "%1"=="" (
  "%LI_VENV%\Scripts\python.exe" run_pipeline.py --trigger agendado
) else (
  "%LI_VENV%\Scripts\python.exe" run_pipeline.py --mode %1 --trigger agendado
)
