# Instalação

## Requisitos

| Item | Mínimo | Recomendado |
|---|---|---|
| Sistema | Windows 10 22H2 ou Windows 11 | Windows 11 |
| Python | 3.11 | 3.12 (64 bits) |
| Memória livre | 300 MB para o JARVIS | 500 MB (com Whisper: +1 GB) |
| Disco | 600 MB (dependências + modelo pequeno) | 1 GB |
| Microfone | Qualquer | Headset (evita que o som do jogo dispare a escuta) |
| Internet | Opcional | Necessária para vozes neurais, Microsoft 365 e IA na nuvem |

Nenhuma etapa exige administrador.

## Passo a passo

1. **Python**: instale o 3.12 em <https://www.python.org/downloads/> marcando *Add python.exe to PATH*, ou no terminal: `winget install Python.Python.3.12`.
2. **Copie a pasta** `jarvis` para um local fixo, por exemplo `C:\Users\SEU_USUARIO\Jarvis`. Evite pastas sincronizadas que mudam de lugar.
3. **Instale**: dois cliques em `install.bat`. Opções (pelo terminal):
   - `install.bat -Autostart` já liga a inicialização com o Windows;
   - `install.bat -Optional` instala também Porcupine e faster-whisper.
4. **Inicie**: atalho *JARVIS* no Menu Iniciar/Área de Trabalho, ou `start.bat`.

O instalador:
- cria `.venv` (ambiente isolado; não mexe no Python do sistema);
- instala `requirements.txt`;
- baixa `models/vosk-model-small-pt-0.3` (reconhecimento local pt-BR);
- gera `assets/jarvis.ico` e os atalhos.

## Arquivos de inicialização

| Arquivo | Uso |
|---|---|
| `start.bat` | Abre o JARVIS com a janela visível, sem console. |
| `start_debug.bat` | Abre com console e logs detalhados (diagnóstico). |
| `jarvis_cli.bat` | Modo texto no terminal (útil para testar comandos). `jarvis_cli.bat --speak` também fala. |
| `run_tests.bat` | Roda os testes automatizados. |

Parâmetros de `python -m jarvis`: `--minimized`, `--show`, `--cli`, `--speak`, `--no-voice`, `--debug`.

## Iniciar com o Windows

Configurações > Geral > **Iniciar com o Windows**. Grava em `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (somente seu usuário). O JARVIS sobe minimizado na bandeja.

## Onde ficam os dados

`%APPDATA%\Jarvis\`:

| Arquivo | Conteúdo |
|---|---|
| `settings.json` | Preferências (sem segredos). Exemplo comentado em `config/settings.example.json`. |
| `jarvis.db` | Histórico, notificações, lembretes, auditoria do Excel (SQLite local). |
| `msal_token_cache.bin` | Tokens Microsoft, criptografados com DPAPI (só sua conta do Windows abre). |
| `cache\` | Frases de voz pré-geradas e índice de programas. |
| `logs\jarvis.log` | Registro técnico com rotação (5 × 1 MB); tokens são mascarados. |

Chaves de API ficam no **Gerenciador de Credenciais do Windows** (serviço `Jarvis-Assistente`).

## Modelo de voz maior (opcional)

`.venv\Scripts\python scripts\download_models.py --large` baixa o modelo completo (~1,6 GB, mais preciso, ~4 GB de RAM). Depois ajuste `stt.vosk_model` em `settings.json` para `vosk-model-pt-fb-v0.1.1-20220516_2113`. Alternativa mais leve para precisão: **Whisper** em Configurações > Ativação (baixa o modelo no primeiro uso).

## Gerar executável e instalador

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

- Gera `dist\Jarvis\Jarvis.exe` (pasta portátil, com o modelo de voz copiado).
- Se o **Inno Setup 6** estiver instalado (`winget install JRSoftware.InnoSetup`), gera também `installer\Output\JarvisSetup-1.0.0.exe`, que instala por usuário, cria atalhos e oferece inicialização com o Windows.

Observação: o empacotamento foi configurado mas só pode ser validado num Windows. Se o PyInstaller acusar módulo faltando, rode `start_debug.bat` pela versão em Python (que é a referência) e reporte o nome do módulo.

## Atualizar

Substitua os arquivos do projeto (mantendo `.venv` e `models`) e rode `install.bat` de novo. Suas configurações em `%APPDATA%\Jarvis` são preservadas.

## Desinstalar

1. Configurações > Privacidade e memória > **Apagar TUDO** (remove histórico, segredos e tokens).
2. Desligue *Iniciar com o Windows*.
3. Apague a pasta do projeto e `%APPDATA%\Jarvis`.
