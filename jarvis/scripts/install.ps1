# Instalação do JARVIS (não precisa de administrador)
#   - cria o ambiente Python isolado (.venv)
#   - instala as dependências
#   - baixa o modelo de voz em português
#   - cria atalhos no Menu Iniciar e na Área de Trabalho
param(
    [switch]$Optional,     # instala também Porcupine e faster-whisper
    [switch]$NoShortcuts,
    [switch]$Autostart     # já liga a inicialização com o Windows
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
Write-Host "== Instalação do JARVIS em $Root ==" -ForegroundColor Cyan

# 1. Python
$pyExe = $null; $pyArgs = @(); $version = ""
$candidates = @(@("py", "-3.12"), @("py", "-3.13"), @("py", "-3.11"), @("python"))
foreach ($c in $candidates) {
    $exe = $c[0]
    $extra = @($c | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try {
        $v = & $exe @extra -c "import sys; print(str(sys.version_info[0]) + '.' + str(sys.version_info[1]))" 2>$null
    } catch { continue }
    if ($LASTEXITCODE -eq 0 -and "$v" -match '^3\.(11|12|13)$') { $pyExe = $exe; $pyArgs = $extra; $version = "$v"; break }
}
if (-not $pyExe) {
    Write-Host "Python 3.11-3.13 não encontrado." -ForegroundColor Red
    Write-Host "Instale o Python 3.12 em https://www.python.org/downloads/ (marque 'Add python.exe to PATH') ou rode:"
    Write-Host "  winget install Python.Python.3.12"
    exit 1
}
Write-Host "Usando Python $version"

# 2. Ambiente virtual e dependências
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o ambiente virtual" }
}
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip --disable-pip-version-check -q
& $venvPy -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências" }
if ($Optional) {
    & $venvPy -m pip install -r requirements-optional.txt --disable-pip-version-check
}

# 3. Modelo de voz
& $venvPy scripts\download_models.py
if ($LASTEXITCODE -ne 0) { throw "Falha ao baixar o modelo de voz" }

# 4. Arquivo .env para chaves de API (criado vazio a partir do exemplo)
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Arquivo .env criado. Abra-o no Bloco de Notas e cole sua chave da Fish Audio em FISH_AUDIO_API_KEY."
}

# 5. Ícone e atalhos
& $venvPy scripts\make_icon.py | Out-Null
if (-not $NoShortcuts) {
    $shell = New-Object -ComObject WScript.Shell
    $targets = @(
        (Join-Path ([Environment]::GetFolderPath("Programs")) "JARVIS.lnk"),
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "JARVIS.lnk")
    )
    foreach ($path in $targets) {
        $lnk = $shell.CreateShortcut($path)
        $lnk.TargetPath = Join-Path $Root ".venv\Scripts\pythonw.exe"
        $lnk.Arguments = "`"$Root\run_jarvis.pyw`" --show"
        $lnk.WorkingDirectory = $Root
        if (Test-Path "$Root\assets\jarvis.ico") { $lnk.IconLocation = "$Root\assets\jarvis.ico" }
        $lnk.Description = "JARVIS - assistente pessoal"
        $lnk.Save()
    }
    Write-Host "Atalhos criados no Menu Iniciar e na Área de Trabalho."
}

# 6. Inicialização com o Windows (HKCU, sem administrador)
if ($Autostart) {
    $cmd = "`"$Root\.venv\Scripts\pythonw.exe`" `"$Root\run_jarvis.pyw`" --minimized"
    Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "JarvisAssistente" -Value $cmd
    Write-Host "Inicialização com o Windows ativada."
}

Write-Host ""
Write-Host "Instalação concluída." -ForegroundColor Green
Write-Host "Inicie pelo atalho JARVIS ou com: start.bat"
