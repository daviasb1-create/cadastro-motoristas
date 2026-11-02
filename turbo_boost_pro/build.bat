@echo off
chcp 65001 >nul
title TURBO BOOST PRO - Build
echo ============================================
echo   TURBO BOOST PRO - gerando executavel
echo ============================================
where python >nul 2>nul || (echo [ERRO] Python nao encontrado. Instale o Python 3.11+ em python.org & pause & exit /b 1)

if not exist .venv (
  echo [1/4] Criando ambiente virtual...
  python -m venv .venv || (echo [ERRO] Falha ao criar venv & pause & exit /b 1)
)
call .venv\Scripts\activate.bat

echo [2/4] Instalando dependencias...
python -m pip install --upgrade pip >nul
pip install -r requirements-build.txt || (echo [ERRO] Falha nas dependencias & pause & exit /b 1)

echo [3/4] Baixando PresentMon (benchmark de FPS, licenca MIT)...
if not exist tools mkdir tools
if not exist tools\PresentMon.exe powershell -NoProfile -Command "$r = Invoke-RestMethod https://api.github.com/repos/GameTechDev/PresentMon/releases; $a = $r | Where-Object { -not $_.prerelease } | ForEach-Object { $_.assets } | Where-Object { $_.name -match '^PresentMon-[0-9.]+-x64\.exe$' } | Select-Object -First 1; Invoke-WebRequest $a.browser_download_url -OutFile tools\PresentMon.exe; Invoke-WebRequest https://raw.githubusercontent.com/GameTechDev/PresentMon/main/LICENSE.txt -OutFile tools\PresentMon-LICENSE.txt"

echo Gerando icone e executavel...
python assets\make_icon.py
pyinstaller --noconfirm --clean turbo_boost_pro.spec || (echo [ERRO] PyInstaller falhou & pause & exit /b 1)

echo [4/4] Gerando instalador (se o Inno Setup estiver instalado)...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% installer\turbo_boost_pro.iss && echo Instalador: installer\Output\TurboBoostPro_Setup_1.2.0.exe
) else (
  echo Inno Setup 6 nao encontrado: instale em https://jrsoftware.org/isdl.php para gerar o Setup.exe
)
echo.
echo Pronto! Executavel: dist\TurboBoostPro\TurboBoostPro.exe
pause
