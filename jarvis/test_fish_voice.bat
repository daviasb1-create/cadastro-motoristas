@echo off
REM Testa a voz Fish Audio configurada (chave no arquivo .env)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\test_fish_voice.py"
pause
