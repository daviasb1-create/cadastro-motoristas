@echo off
REM LOGISTICS INTELLIGENCE - abre o painel no navegador
cd /d "%~dp0"
if not exist .venv (
  echo Criando ambiente Python pela primeira vez...
  py -3 -m venv .venv || python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
if not exist .env copy .env.example .env >nul
streamlit run app.py
pause
