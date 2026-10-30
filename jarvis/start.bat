@echo off
REM Inicia o JARVIS com a janela aberta (sem console)
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo JARVIS ainda nao instalado. Rode install.bat primeiro.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0run_jarvis.pyw" --show
