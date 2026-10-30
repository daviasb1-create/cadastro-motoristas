# Gera o executável (dist\Jarvis\Jarvis.exe) e, se o Inno Setup estiver instalado, o instalador.
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Rode install.bat antes." }
& $py -m pip install -q "pyinstaller>=6.6"
& $py scripts\make_icon.py | Out-Null
& $py -m PyInstaller jarvis.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "Falha no PyInstaller" }
if (Test-Path "models") {
    Copy-Item -Recurse -Force "models" "dist\Jarvis\models"
}
Write-Host "Executável pronto: dist\Jarvis\Jarvis.exe" -ForegroundColor Green
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc "installer\jarvis.iss"
    Write-Host "Instalador pronto em installer\Output\" -ForegroundColor Green
} else {
    Write-Host "Inno Setup não encontrado: para gerar o instalador, instale com 'winget install JRSoftware.InnoSetup' e rode de novo."
}
