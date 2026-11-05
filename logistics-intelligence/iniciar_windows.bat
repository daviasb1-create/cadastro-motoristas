@echo off
REM LOGISTICS INTELLIGENCE - abre o painel no navegador
REM O ambiente Python fica em %LOCALAPPDATA%\LogisticsIntelligence (caminho curto),
REM evitando o limite de 260 caracteres do Windows.
cd /d "%~dp0"
set "LI_VENV=%LOCALAPPDATA%\LogisticsIntelligence\venv"
if not exist "%LI_VENV%\Scripts\python.exe" (
  echo Criando ambiente Python pela primeira vez em %LI_VENV% ...
  if not exist "%LOCALAPPDATA%\LogisticsIntelligence" mkdir "%LOCALAPPDATA%\LogisticsIntelligence"
  py -3 -m venv "%LI_VENV%" || python -m venv "%LI_VENV%"
  if not exist "%LI_VENV%\Scripts\python.exe" (
    echo ERRO: Python nao encontrado. Instale o Python 3.12 marcando "Add python.exe to PATH".
    pause
    exit /b 1
  )
  "%LI_VENV%\Scripts\python.exe" -m pip install --upgrade pip
  "%LI_VENV%\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo ERRO na instalacao. Apague a pasta %LI_VENV% e tente novamente.
    pause
    exit /b 1
  )
)
if not exist .env copy .env.example .env >nul
"%LI_VENV%\Scripts\python.exe" -m streamlit run app.py --server.address localhost
pause
