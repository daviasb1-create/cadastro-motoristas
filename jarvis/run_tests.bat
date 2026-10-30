@echo off
REM Roda os testes automatizados
"%~dp0.venv\Scripts\python.exe" -m pip install -q pytest
"%~dp0.venv\Scripts\python.exe" -m pytest
pause
