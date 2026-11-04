@echo off
REM ===== STARLINK NETVISION PRO - build do executavel no Windows 11 =====
REM Requisitos: Python 3.11+ (64 bits) instalado e no PATH.
setlocal
cd /d "%~dp0"
if not exist .venv (
  echo [1/4] Criando ambiente virtual...
  py -3 -m venv .venv || python -m venv .venv || goto :erro
)
call .venv\Scripts\activate.bat || goto :erro
echo [2/4] Instalando dependencias...
python -m pip install --upgrade pip >nul
pip install -r requirements-dev.txt || goto :erro
echo [3/4] Rodando testes...
python -m pytest tests -q || goto :erro
echo [4/4] Gerando executavel...
pyinstaller build\netvision.spec --noconfirm --distpath dist --workpath build\work || goto :erro
echo.
echo Pronto: dist\StarlinkNetVisionPro.exe
exit /b 0
:erro
echo.
echo FALHOU. Veja as mensagens acima.
exit /b 1
