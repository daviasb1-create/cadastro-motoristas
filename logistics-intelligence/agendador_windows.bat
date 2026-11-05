@echo off
REM LOGISTICS INTELLIGENCE - agendador local (07:00, 12:00, 17:00 e monitor de urgentes)
REM Deixe esta janela aberta, ou registre no Agendador de Tarefas (ver docs/INSTALACAO_WINDOWS.md)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python scheduler_service.py
