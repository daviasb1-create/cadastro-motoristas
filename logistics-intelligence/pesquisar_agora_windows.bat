@echo off
REM Executa uma pesquisa completa imediatamente (usado também pelo Agendador de Tarefas do Windows)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
if not "%1"=="" python run_pipeline.py --mode %1 --trigger agendado
if "%1"=="" python run_pipeline.py --trigger agendado
