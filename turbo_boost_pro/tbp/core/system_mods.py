"""Modificações reais do Windows usadas pelo WINDOWS ULTRA LITE:

- Debloat: remove apps nativos dispensáveis APENAS para o usuário atual (Remove-AppxPackage).
  O pacote provisionado do sistema é mantido, então a reinstalação é offline e imediata
  (Add-AppxPackage -Register). Se não houver cópia local, a página do app na Microsoft Store é aberta.
- Recursos opcionais: Disable-WindowsOptionalFeature SEM -Remove (os arquivos ficam no disco;
  reativar é offline). Capacidades (WordPad, Steps Recorder...) são reinstaláveis via Windows Update.
- Tarefas agendadas de telemetria: Disable-ScheduledTask / Enable-ScheduledTask.
- CS2: prioridade de CPU/E-S permanente (IFEO PerfOptions), GPU de alto desempenho e autoexec.cfg.

Toda entrada que vira comando PowerShell é validada por expressão regular (sem injeção).
"""
from __future__ import annotations

import os
import re
import shutil
import time

from ..config import BACKUP_DIR, IS_WINDOWS
from ..utils import log, powershell, powershell_json
from . import registry as reg
from .journal import Journal

_SAFE_PKG = re.compile(r"^[A-Za-z0-9._\-~]+$")
_SAFE_FEATURE = re.compile(r"^[A-Za-z0-9._\-~]+$")
_SAFE_TASK = re.compile(r"^[A-Za-z0-9 _\\.\-()]+$")


def _check(pattern, value, what):
    if not value or not pattern.match(value):
        raise ValueError(f"{what} inválido: {value!r}")
    return value


# ============================================================================ DEBLOAT
# nome do pacote (prefixo) -> (nome amigável, descrição, nível) | nível: "recomendado" ou "opcional"
APPS = {
    "Microsoft.BingNews": ("Notícias", "App de notícias do Bing.", "recomendado"),
    "Microsoft.BingWeather": ("Clima", "App de previsão do tempo.", "opcional"),
    "Microsoft.BingSearch": ("Pesquisa do Bing", "Integração de pesquisa web do Bing.", "recomendado"),
    "Microsoft.GetHelp": ("Obter Ajuda", "Central de suporte online.", "recomendado"),
    "Microsoft.Getstarted": ("Dicas", "App de dicas do Windows.", "recomendado"),
    "Microsoft.MicrosoftSolitaireCollection": ("Solitaire Collection", "Jogos de cartas com anúncios.",
                                               "recomendado"),
    "Microsoft.MicrosoftOfficeHub": ("Microsoft 365 (Office Hub)", "Atalho/propaganda do Microsoft 365. "
                                     "Não remove o Office instalado.", "recomendado"),
    "Microsoft.People": ("Pessoas", "App de contatos legado.", "recomendado"),
    "Microsoft.PowerAutomateDesktop": ("Power Automate", "Automação de tarefas.", "recomendado"),
    "Microsoft.Todos": ("Microsoft To Do", "Lista de tarefas.", "opcional"),
    "Microsoft.WindowsFeedbackHub": ("Hub de Comentários", "Envio de feedback à Microsoft.", "recomendado"),
    "Microsoft.WindowsMaps": ("Mapas", "App de mapas offline.", "recomendado"),
    "Microsoft.ZuneMusic": ("Media Player / Groove", "Player de música. Remova se usa outro player.",
                            "opcional"),
    "Microsoft.ZuneVideo": ("Filmes e TV", "Player de vídeo legado.", "recomendado"),
    "Microsoft.YourPhone": ("Vincular ao Celular", "Integração com celular; roda em segundo plano.",
                            "recomendado"),
    "MicrosoftCorporationII.QuickAssist": ("Assistência Rápida", "Suporte remoto.", "opcional"),
    "Microsoft.MicrosoftStickyNotes": ("Notas Autoadesivas", "Notas na área de trabalho.", "opcional"),
    "Microsoft.WindowsAlarms": ("Relógio e Alarmes", "Alarmes, timer e foco.", "opcional"),
    "Microsoft.WindowsSoundRecorder": ("Gravador de Som", "Gravação de áudio.", "opcional"),
    "Microsoft.549981C3F5F10": ("Cortana", "Assistente descontinuada.", "recomendado"),
    "Microsoft.Windows.DevHome": ("Dev Home", "Painel para desenvolvedores.", "recomendado"),
    "MicrosoftTeams": ("Teams (pessoal)", "Chat do Teams pessoal; inicia com o Windows.", "recomendado"),
    "MSTeams": ("Microsoft Teams", "Teams novo. Remova só se não usa no trabalho.", "opcional"),
    "Microsoft.OutlookForWindows": ("Outlook (novo)", "Novo cliente de e-mail web.", "opcional"),
    "microsoft.windowscommunicationsapps": ("Email e Calendário (legado)", "Substituído pelo novo Outlook.",
                                            "recomendado"),
    "Microsoft.Copilot": ("Copilot", "Assistente de IA em WebView.", "recomendado"),
    "Microsoft.Windows.Ai.Copilot.Provider": ("Copilot (provedor)", "Componente do Copilot.", "recomendado"),
    "MicrosoftWindows.Client.WebExperience": ("Widgets", "Painel de Widgets/notícias (~200 MB em idle).",
                                              "recomendado"),
    "Microsoft.MixedReality.Portal": ("Portal de Realidade Misturada", "Só para óculos VR WMR.", "recomendado"),
    "Microsoft.SkypeApp": ("Skype", "Descontinuado.", "recomendado"),
    "Microsoft.Office.OneNote": ("OneNote (Store)", "Versão Store do OneNote.", "opcional"),
    "Microsoft.Clipchamp": ("Clipchamp", "Editor de vídeo online.", "recomendado"),
    "Clipchamp.Clipchamp": ("Clipchamp", "Editor de vídeo online.", "recomendado"),
    "Microsoft.Wallet": ("Carteira", "Pagamentos legados.", "recomendado"),
    "Microsoft.Messaging": ("Mensagens", "App legado.", "recomendado"),
    "Microsoft.OneConnect": ("Planos Móveis", "Dados móveis/eSIM.", "recomendado"),
    "Microsoft.Print3D": ("Print 3D", "Impressão 3D legada.", "recomendado"),
    "Microsoft.3DBuilder": ("3D Builder", "Modelagem 3D legada.", "recomendado"),
    "Microsoft.Microsoft3DViewer": ("Visualizador 3D", "Visualização de modelos 3D.", "recomendado"),
    "Microsoft.MSPaint": ("Paint 3D", "Editor 3D legado (o Paint clássico é outro app).", "opcional"),
    "Microsoft.Windows.Photos": ("Fotos", "Visualizador de imagens padrão. Mantenha se não tem outro.",
                                 "opcional"),
    "Microsoft.WindowsCamera": ("Câmera", "App de câmera.", "opcional"),
    "Microsoft.XboxApp": ("Xbox Console Companion", "App antigo do Xbox.", "recomendado"),
    "Microsoft.GamingApp": ("Xbox", "Necessário para Game Pass no PC. Mantenha se usa.", "opcional"),
    "Microsoft.Xbox.TCUI": ("Xbox TCUI", "Interface social Xbox usada por alguns jogos.", "opcional"),
    "Microsoft.XboxGamingOverlay": ("Xbox Game Bar", "Sobreposição Win+G (gravação, FPS). Opcional.",
                                    "opcional"),
    "Microsoft.Advertising.Xaml": ("Microsoft Advertising SDK", "Biblioteca de anúncios em apps.",
                                   "recomendado"),
    "SpotifyAB.SpotifyMusic": ("Spotify (pré-instalado)", "Atalho pré-instalado do Spotify.", "opcional"),
    "Disney.37853FC22B2CE": ("Disney+ (pré-instalado)", "Atalho promocional.", "recomendado"),
    "BytedancePte.Ltd.TikTok": ("TikTok (pré-instalado)", "Atalho promocional.", "recomendado"),
    "Facebook.InstagramBeta": ("Instagram (pré-instalado)", "Atalho promocional.", "recomendado"),
    "AmazonVideo.PrimeVideo": ("Prime Video (pré-instalado)", "Atalho promocional.", "recomendado"),
    "king.com.CandyCrushSaga": ("Candy Crush", "Jogo promocional.", "recomendado"),
    "king.com.CandyCrushSodaSaga": ("Candy Crush Soda", "Jogo promocional.", "recomendado"),
    "Microsoft.Family": ("Microsoft Family", "Controle parental.", "opcional"),
    "Microsoft.Windows.DevHomeAzureExtension": ("Dev Home (Azure)", "Extensão do Dev Home.", "recomendado"),
}

# Nunca removidos (Store, frameworks, segurança, shell, Xbox Identity/Gaming Services usados por jogos)
PROTECTED_APPS = (
    "Microsoft.WindowsStore", "Microsoft.StorePurchaseApp", "Microsoft.DesktopAppInstaller", "Microsoft.VCLibs",
    "Microsoft.UI.Xaml", "Microsoft.NET.", "Microsoft.WindowsAppRuntime", "Microsoft.Services.Store",
    "Microsoft.SecHealthUI", "Microsoft.Windows.ShellExperienceHost", "Microsoft.Windows.StartMenuExperienceHost",
    "MicrosoftWindows.Client.CBS", "MicrosoftWindows.Client.Core", "Microsoft.Windows.CloudExperienceHost",
    "Microsoft.AAD.BrokerPlugin", "Microsoft.AccountsControl", "Microsoft.LockApp", "Microsoft.Win32WebViewHost",
    "Microsoft.XboxIdentityProvider", "Microsoft.GamingServices", "Microsoft.XboxSpeechToTextOverlay",
    "Microsoft.Windows.Search", "Microsoft.Windows.SecHealthUI", "windows.immersivecontrolpanel",
    "Microsoft.WindowsTerminal", "Microsoft.WindowsNotepad", "Microsoft.Paint", "Microsoft.WindowsCalculator",
    "Microsoft.ScreenSketch", "Microsoft.HEIFImageExtension", "Microsoft.HEVCVideoExtension",
    "Microsoft.VP9VideoExtensions", "Microsoft.WebMediaExtensions", "Microsoft.WebpImageExtension",
    "Microsoft.RawImageExtension", "Microsoft.AV1VideoExtension", "Microsoft.MPEG2VideoExtension",
    "Microsoft.Windows.Apprep.ChxApp", "Microsoft.BioEnrollment", "Microsoft.CredDialogHost",
    "Microsoft.Windows.OOBENetwork", "Microsoft.Windows.PeopleExperienceHost", "NVIDIACorp.", "AdvancedMicroDevicesInc",
    "AppUp.Intel", "RealtekSemiconductorCorp", "DolbyLaboratories", "Microsoft.Edge", "Microsoft.MicrosoftEdge",
    "Microsoft.OneDriveSync", "Microsoft.WidgetsPlatformRuntime", "Microsoft.ApplicationCompatibilityEnhancements",
)


def _match(name: str, table) -> str | None:
    for key in table:
        if name == key or name.startswith(key + ".") or name.startswith(key):
            return key
    return None


def list_apps() -> list[dict]:
    """Apps instalados para o usuário atual, classificados (recomendado/opcional/outro)."""
    if not IS_WINDOWS:
        return []
    rows = powershell_json("Get-AppxPackage | Where-Object { -not $_.IsFramework -and -not $_.NonRemovable } | "
                           "Select-Object Name,PackageFullName,PackageFamilyName,InstallLocation,"
                           "@{n='Sig';e={[string]$_.SignatureKind}},Version", timeout=120)
    out, seen = [], set()
    for r in rows:
        name = r.get("Name") or ""
        if not name or name in seen or _match(name, PROTECTED_APPS):
            continue
        seen.add(name)
        key = _match(name, APPS)
        sig = str(r.get("Sig"))
        if key:
            label, desc, level = APPS[key]
        elif sig == "Store":  # app da Store instalado: lista como "outro", nunca pré-selecionado
            label, desc, level = name.split(".")[-1], "App da Microsoft Store instalado.", "outro"
        else:
            continue  # apps de sistema fora do catálogo nunca são listados
        out.append({"name": name, "full": r.get("PackageFullName"), "family": r.get("PackageFamilyName"),
                    "location": r.get("InstallLocation") or "", "label": label, "desc": desc, "level": level,
                    "version": r.get("Version")})
    order = {"recomendado": 0, "opcional": 1, "outro": 2}
    out.sort(key=lambda a: (order[a["level"]], a["label"].lower()))
    return out


def remove_app(app: dict, journal: Journal) -> str:
    full = _check(_SAFE_PKG, app["full"], "pacote")
    name = _check(_SAFE_PKG, app["name"], "nome")
    family = _check(_SAFE_PKG, app["family"], "família")
    if _match(name, PROTECTED_APPS):
        raise ValueError(f"{name} é protegido.")
    gid = f"appx:{name}"
    journal.group(gid, f"App removido: {app['label']}", "debloat")
    journal.add_action(gid, {"kind": "appx", "name": name, "family": family,
                             "desc": f"Reinstalar {app['label']}"})
    r = powershell(f"Remove-AppxPackage -Package '{full}' -ErrorAction Stop", timeout=300)
    if r.returncode != 0:
        journal.data["groups"].pop(gid, None)
        journal.save()
        err = (r.stderr or r.stdout or "falha ao remover").strip().splitlines()
        raise RuntimeError(err[0][:200] if err else "falha ao remover")
    log.info("APPX removido: %s", full)
    return f"✔ {app['label']} removido (reinstalável)"


def reinstall_app(name: str, family: str) -> str:
    name = _check(_SAFE_PKG, name, "nome")
    family = _check(_SAFE_PKG, family, "família")
    script = (
        f"$n='{name}'; "
        "$m = $null; "
        "$p = Get-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue | Where-Object DisplayName -eq $n | "
        "Select-Object -First 1; "
        "if ($p -and $p.InstallLocation) { $m = [Environment]::ExpandEnvironmentVariables($p.InstallLocation) }; "
        "if (-not $m) { $a = Get-AppxPackage -AllUsers -Name $n -ErrorAction SilentlyContinue | Select-Object "
        "-First 1; if ($a) { $m = Join-Path $a.InstallLocation 'AppxManifest.xml' } }; "
        "if ($m -and (Test-Path $m)) { Add-AppxPackage -DisableDevelopmentMode -Register $m -ErrorAction Stop; "
        "'OK' } else { 'STORE' }")
    r = powershell(script, timeout=300)
    if "OK" in r.stdout:
        return "reinstalado"
    if IS_WINDOWS:
        os.startfile(f"ms-windows-store://pdp/?PFN={family}")  # noqa: S606
    return "Store aberta para reinstalar"


# ============================================================================ RECURSOS OPCIONAIS
# nome -> (rótulo, descrição, nível)
FEATURES = {
    "Printing-XPSServices-Features": ("Serviços XPS", "Impressão/visualização de documentos XPS (legado).",
                                      "recomendado"),
    "FaxServicesClientPackage": ("Fax e Scanner do Windows", "Envio de fax pelo modem.", "recomendado"),
    "WorkFolders-Client": ("Pastas de Trabalho", "Sincronização com servidores corporativos.", "recomendado"),
    "MicrosoftWindowsPowerShellV2Root": ("PowerShell 2.0", "Versão obsoleta; desativar também aumenta a "
                                         "segurança. O PowerShell 5/7 continua.", "recomendado"),
    "MicrosoftWindowsPowerShellV2": ("PowerShell 2.0 (motor)", "Motor obsoleto do PowerShell 2.0.",
                                     "recomendado"),
    "SMB1Protocol": ("SMB 1.0", "Compartilhamento de rede obsoleto e inseguro.", "recomendado"),
    "Internet-Explorer-Optional-amd64": ("Internet Explorer 11", "Navegador legado.", "recomendado"),
    "MSRDC-Infrastructure": ("Compressão Diferencial Remota", "Usada por replicação de servidores.",
                             "recomendado"),
    "Printing-Foundation-InternetPrinting-Client": ("Impressão via Internet (IPP)",
                                                    "Imprimir em impressoras pela internet.", "opcional"),
    "Recall": ("Recall", "Linha do tempo de capturas por IA (PCs Copilot+).", "recomendado"),
    "MediaPlayback": ("Recursos de Mídia (WMP legado)", "Alguns jogos/apps antigos exigem. Deixe ativo se "
                      "algum jogo reclamar de 'Media Feature Pack'.", "opcional"),
    "VirtualMachinePlatform": ("Plataforma de Máquina Virtual", "Desativar libera recursos, mas QUEBRA WSL2, "
                               "Docker e emuladores Android. Alguns anti-cheats exigem desativado/ativado.",
                               "opcional"),
    "Microsoft-Hyper-V-All": ("Hyper-V", "Máquinas virtuais. Desativar reduz overhead se você não usa VMs.",
                              "opcional"),
}

CAPABILITIES = {
    "App.StepsRecorder": ("Gravador de Passos", "Ferramenta de gravação de passos (descontinuada).",
                          "recomendado"),
    "MathRecognizer": ("Reconhecedor Matemático", "Painel de entrada de fórmulas.", "recomendado"),
    "Microsoft.Windows.WordPad": ("WordPad", "Editor descontinuado.", "recomendado"),
    "Browser.InternetExplorer": ("Modo IE", "Componente do Internet Explorer.", "recomendado"),
    "Media.WindowsMediaPlayer": ("Windows Media Player legado", "Player antigo (o novo Media Player é outro "
                                 "app).", "opcional"),
    "Microsoft.Windows.PowerShell.ISE": ("PowerShell ISE", "Editor de scripts legado.", "opcional"),
    "Print.Fax.Scan": ("Fax e Digitalização", "Componentes de fax.", "recomendado"),
    "App.Support.QuickAssist": ("Assistência Rápida (legado)", "Versão antiga do suporte remoto.",
                                "recomendado"),
}


def list_features() -> list[dict]:
    if not IS_WINDOWS:
        return []
    names = ",".join(f"'{n}'" for n in FEATURES)
    rows = powershell_json(f"Get-WindowsOptionalFeature -Online | Where-Object FeatureName -in @({names}) | "
                           "Select-Object FeatureName,@{n='State';e={[string]$_.State}}", timeout=300)
    out = []
    for r in rows:
        n = r.get("FeatureName")
        if n in FEATURES:
            label, desc, level = FEATURES[n]
            out.append({"type": "feature", "name": n, "label": label, "desc": desc, "level": level,
                        "enabled": r.get("State") in ("Enabled", "EnablePending")})
    pattern = "|".join(re.escape(c) for c in CAPABILITIES)
    rows = powershell_json(f"Get-WindowsCapability -Online | Where-Object {{ $_.Name -match '^({pattern})~' }} | "
                           "Select-Object Name,@{n='State';e={[string]$_.State}}", timeout=300)
    for r in rows:
        full = r.get("Name") or ""
        key = full.split("~")[0]
        if key in CAPABILITIES:
            label, desc, level = CAPABILITIES[key]
            out.append({"type": "capability", "name": full, "label": label, "desc": desc + " (reinstalação "
                        "requer internet)", "level": level, "enabled": r.get("State") == "Installed"})
    return out


def disable_feature(item: dict, journal: Journal) -> str:
    name = _check(_SAFE_FEATURE, item["name"], "recurso")
    gid = f"{item['type']}:{name}"
    if item["type"] == "feature":
        if name not in FEATURES:
            raise ValueError("recurso fora do catálogo")
        r = powershell(f"Disable-WindowsOptionalFeature -Online -FeatureName '{name}' -NoRestart "
                       "-ErrorAction Stop | Out-Null", timeout=1800)
    else:
        if name.split("~")[0] not in CAPABILITIES:
            raise ValueError("capacidade fora do catálogo")
        r = powershell(f"Remove-WindowsCapability -Online -Name '{name}' -ErrorAction Stop | Out-Null",
                       timeout=1800)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "falha").strip()[:200])
    journal.group(gid, f"Recurso desativado: {item['label']}", "recursos")
    journal.add_action(gid, {"kind": item["type"], "name": name, "desc": f"Reativar {item['label']}"})
    return f"✔ {item['label']} desativado (reinício pode ser necessário)"


# ============================================================================ TAREFAS AGENDADAS
TASKS = {
    r"\Microsoft\Windows\Application Experience\Microsoft Compatibility Appraiser":
        "Analisa compatibilidade e envia telemetria (picos de CPU/disco).",
    r"\Microsoft\Windows\Application Experience\ProgramDataUpdater": "Coleta dados de programas para telemetria.",
    r"\Microsoft\Windows\Application Experience\MareBackup": "Backup de dados de compatibilidade.",
    r"\Microsoft\Windows\Application Experience\PcaPatchDbTask": "Atualiza base do Assistente de Compatibilidade.",
    r"\Microsoft\Windows\Autochk\Proxy": "Envia dados do Autochk ao programa de experiência.",
    r"\Microsoft\Windows\Customer Experience Improvement Program\Consolidator": "Programa de experiência (CEIP).",
    r"\Microsoft\Windows\Customer Experience Improvement Program\UsbCeip": "Telemetria de dispositivos USB.",
    r"\Microsoft\Windows\DiskDiagnostic\Microsoft-Windows-DiskDiagnosticDataCollector":
        "Coleta diagnóstico de disco para a Microsoft.",
    r"\Microsoft\Windows\Feedback\Siuf\DmClient": "Solicitações de feedback.",
    r"\Microsoft\Windows\Feedback\Siuf\DmClientOnScenarioDownload": "Solicitações de feedback.",
    r"\Microsoft\Windows\Windows Error Reporting\QueueReporting": "Envio de relatórios de erro em fila.",
    r"\Microsoft\Windows\Maps\MapsUpdateTask": "Atualização de mapas offline.",
    r"\Microsoft\Windows\Maps\MapsToastTask": "Notificações do app Mapas.",
    r"\Microsoft\Windows\CloudExperienceHost\CreateObjectTask": "Sugestões de configuração da conta.",
    r"\Microsoft\Windows\Flighting\FeatureConfig\UsageDataReporting": "Relatório de uso de recursos.",
    r"\Microsoft\Office\OfficeTelemetryAgentLogOn": "Telemetria do Office ao entrar.",
    r"\Microsoft\Office\OfficeTelemetryAgentFallBack": "Telemetria do Office.",
}


def _split_task(full: str) -> tuple[str, str]:
    path, name = full.rsplit("\\", 1)
    return path + "\\", name


def list_tasks() -> list[dict]:
    if not IS_WINDOWS:
        return []
    rows = powershell_json("Get-ScheduledTask -ErrorAction SilentlyContinue | Select-Object TaskPath,TaskName,"
                           "@{n='State';e={[string]$_.State}}", timeout=180)
    wanted = {k.lower(): k for k in TASKS}
    out = []
    for r in rows:
        full = f"{r.get('TaskPath', '')}{r.get('TaskName', '')}"
        key = wanted.get(full.lower())
        if key:
            out.append({"full": key, "name": key.rsplit("\\", 1)[1], "desc": TASKS[key],
                        "enabled": r.get("State") != "Disabled"})
    return out


def disable_task(full: str, journal: Journal) -> str:
    if full not in TASKS:
        raise ValueError("tarefa fora do catálogo")
    path, name = _split_task(_check(_SAFE_TASK, full, "tarefa"))
    r = powershell(f"Disable-ScheduledTask -TaskPath '{path}' -TaskName '{name}' -ErrorAction Stop | Out-Null")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "falha").strip()[:200])
    gid = f"task:{full}"
    journal.group(gid, f"Tarefa desativada: {name}", "tarefas")
    journal.add_action(gid, {"kind": "task", "name": full, "desc": f"Reativar tarefa {name}"})
    return f"✔ Tarefa '{name}' desativada"


# ============================================================================ REVERSÃO (chamada pelo Journal)
def revert_action(a: dict):
    kind = a["kind"]
    if kind == "appx":
        reinstall_app(a["name"], a["family"])
    elif kind == "feature":
        name = _check(_SAFE_FEATURE, a["name"], "recurso")
        if name not in FEATURES:
            raise ValueError("recurso fora do catálogo")
        r = powershell(f"Enable-WindowsOptionalFeature -Online -FeatureName '{name}' -All -NoRestart "
                       "-ErrorAction Stop | Out-Null", timeout=1800)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "falha").strip()[:200])
    elif kind == "capability":
        name = _check(_SAFE_FEATURE, a["name"], "capacidade")
        if name.split("~")[0] not in CAPABILITIES:
            raise ValueError("capacidade fora do catálogo")
        r = powershell(f"Add-WindowsCapability -Online -Name '{name}' -ErrorAction Stop | Out-Null", timeout=3600)
        if r.returncode != 0:
            raise RuntimeError("Reinstalação requer internet/Windows Update: " + (r.stderr or "").strip()[:150])
    elif kind == "task":
        full = a["name"]
        if full not in TASKS:
            raise ValueError("tarefa fora do catálogo")
        path, name = _split_task(_check(_SAFE_TASK, full, "tarefa"))
        powershell(f"Enable-ScheduledTask -TaskPath '{path}' -TaskName '{name}' -ErrorAction SilentlyContinue | "
                   "Out-Null")


# ============================================================================ HIBERNAÇÃO
def hibernation_enabled() -> bool:
    ok, _t, v = reg.read_value("HKLM", r"SYSTEM\CurrentControlSet\Control\Power", "HibernateEnabled")
    return bool(ok and v)


def disable_hibernation(journal: Journal) -> str:
    from ..utils import run
    if not hibernation_enabled():
        return "Hibernação já estava desativada."
    r = run(["powercfg", "/hibernate", "off"])
    if r.returncode != 0:
        raise RuntimeError(r.stdout.strip()[:150] or "falha")
    gid = "power:hibernate"
    journal.group(gid, "Hibernação desativada (hiberfil.sys removido)", "energia")
    journal.add_action(gid, {"kind": "cmd", "cmd": ["powercfg", "/hibernate", "on"], "desc": "Reativar hibernação"})
    return "✔ Hibernação desativada: espaço do hiberfil.sys liberado"


# ============================================================================ CS2
CS2_APPID = "730"
_IFEO = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
CS2_LAUNCH_OPTIONS = "-novid -nojoy +exec autoexec.cfg"
CS2_AUTOEXEC = """// ===== TURBO BOOST PRO - autoexec CS2 (gerado automaticamente) =====
// Removido/restaurado ao reverter no TURBO BOOST PRO. Para carregar: opção de inicialização +exec autoexec.cfg
rate 786432                                      // taxa máxima de rede permitida (evita perda de pacotes)
fps_max 0                                        // FPS sem limite (use o limitador do driver se preferir)
fps_max_ui 120                                   // limita FPS nos menus (menos calor/consumo fora da partida)
engine_low_latency_sleep_after_client_tick true  // reduz latência de entrada entre ticks
r_player_visibility_mode 1                       // aumenta contraste dos jogadores
cl_hud_telemetry_frametime_show 0
echo "TURBO BOOST PRO: autoexec carregado"
"""
CS2_VIDEO_TIPS = [
    "Modo de exibição: Tela cheia · Taxa de atualização: a máxima do monitor",
    "NVIDIA Reflex: Ativado + Boost (ou AMD Anti-Lag 2 ativado)",
    "Multisampling: 2x MSAA ou CMAA2 (4x/8x custa FPS em GPUs médias)",
    "Qualidade de sombras globais: Média/Alta (Baixa esconde jogadores em algumas áreas)",
    "Detalhes de modelos/texturas: Baixa · Filtragem: Bilinear ou Anisotrópica 4x",
    "Shader / Partículas: Baixa · Oclusão de ambiente: Desativada · HDR: Desempenho",
    "FidelityFX Super Resolution: Desativado (ative só se faltar FPS; reduz nitidez)",
    "V-Sync: Desativado no jogo; com G-Sync/FreeSync limite o FPS 3 abaixo da taxa do monitor",
]


def find_cs2() -> dict | None:
    """Localiza o CS2 nas bibliotecas da Steam (appmanifest_730.acf)."""
    if not IS_WINDOWS:
        return None
    steam = None
    for hive, path, val in (("HKCU", r"Software\Valve\Steam", "SteamPath"),
                            ("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
        ok, _t, v = reg.read_value(hive, path, val)
        if ok and v and os.path.isdir(v):
            steam = os.path.normpath(v)
            break
    if not steam:
        return None
    libs = [os.path.join(steam, "steamapps")]
    try:
        txt = open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="ignore").read()
        libs += [os.path.join(m.replace("\\\\", "\\"), "steamapps") for m in re.findall(r'"path"\s*"([^"]+)"', txt)]
    except OSError:
        pass
    for lib in libs:
        if os.path.exists(os.path.join(lib, f"appmanifest_{CS2_APPID}.acf")):
            base = os.path.join(lib, "common", "Counter-Strike Global Offensive")
            exe = os.path.join(base, "game", "bin", "win64", "cs2.exe")
            if os.path.exists(exe):
                return {"exe": exe, "cfg_dir": os.path.join(base, "game", "csgo", "cfg"), "steam": steam}
    return None


def cs2_status() -> dict:
    cs = find_cs2()
    st = {"found": bool(cs), "priority": False, "gpu": False, "autoexec": False}
    if not cs:
        return st
    ok, _t, v = reg.read_value("HKLM", _IFEO + r"\cs2.exe\PerfOptions", "CpuPriorityClass")
    st["priority"] = ok and v == 3
    ok, _t, v = reg.read_value("HKCU", r"Software\Microsoft\DirectX\UserGpuPreferences", cs["exe"])
    st["gpu"] = ok and "GpuPreference=2" in str(v)
    path = os.path.join(cs["cfg_dir"], "autoexec.cfg")
    st["autoexec"] = os.path.exists(path) and "TURBO BOOST PRO" in open(path, encoding="utf-8", errors="ignore").read()
    st.update(cs)
    return st


def apply_cs2(journal: Journal, priority=True, gpu=True, autoexec=True) -> list[str]:
    cs = find_cs2()
    if not cs:
        raise RuntimeError("CS2 não encontrado nas bibliotecas da Steam.")
    gid = "game:cs2"
    journal.group(gid, "Otimizações do CS2", "jogos")
    msgs = []
    if priority:  # prioridade Alta de CPU e E/S toda vez que o cs2.exe abrir (sem ferramenta residente)
        journal.reg_set(gid, "HKLM", _IFEO + r"\cs2.exe\PerfOptions", "CpuPriorityClass", reg.REG_DWORD, 3)
        journal.reg_set(gid, "HKLM", _IFEO + r"\cs2.exe\PerfOptions", "IoPriority", reg.REG_DWORD, 3)
        msgs.append("✔ CS2: prioridade Alta de CPU e E/S permanente")
    if gpu:
        journal.reg_set(gid, "HKCU", r"Software\Microsoft\DirectX\UserGpuPreferences", cs["exe"], reg.REG_SZ,
                        "GpuPreference=2;")
        msgs.append("✔ CS2: GPU de alto desempenho")
    if autoexec:
        os.makedirs(cs["cfg_dir"], exist_ok=True)
        target = os.path.join(cs["cfg_dir"], "autoexec.cfg")
        backup = None
        if os.path.exists(target):
            backup = str(BACKUP_DIR / f"cs2_autoexec_{int(time.time())}.cfg")
            shutil.copy2(target, backup)
        journal.add_action(gid, {"kind": "file", "path": target, "backup": backup,
                                 "desc": "Restaurar autoexec.cfg do CS2"})
        with open(target, "w", encoding="utf-8") as f:
            f.write(CS2_AUTOEXEC)
        msgs.append("✔ CS2: autoexec.cfg criado" + (" (anterior salvo no backup)" if backup else ""))
    return msgs
