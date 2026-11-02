"""Catálogo de otimizações de Registro: todas reversíveis via Journal.

Cada Tweak descreve exatamente quais valores serão alterados (exibidos antes da execução),
se exige administrador/reinício e qual o benefício esperado, com observações honestas
sobre quando a otimização pode NÃO ajudar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import registry as reg
from .journal import Journal
from .registry import REG_BINARY, REG_DWORD, REG_SZ
from . import winapi


@dataclass
class RegChange:
    hive: str
    path: str
    name: str
    typ: int
    value: object

    def current(self):
        return reg.read_value(self.hive, self.path, self.name)

    def is_applied(self) -> bool:
        exists, _typ, val = self.current()
        if not exists:
            return False
        if self.typ in (REG_SZ, reg.REG_EXPAND_SZ):
            return str(val) == str(self.value)
        return val == self.value

    def describe(self) -> str:
        _e, _t, cur = self.current()
        return (f"{self.hive}\\{self.path}\\{self.name}  [{reg.type_name(self.typ)}]  "
                f"{reg.display(cur)} → {reg.display(self.value)}")


@dataclass
class Tweak:
    id: str
    category: str
    title: str
    description: str
    changes: list[RegChange] | Callable[[], list[RegChange]] = field(default_factory=list)
    benefit: str = ""
    note: str = ""
    risk: str = "Baixo"
    reboot: bool = False
    after: Callable[[], None] | None = None
    turbo: bool = False      # incluído no TURBO MODE / Máximo Desempenho
    gamer: bool = False      # incluído no Modo Gamer / Gaming Boost / Gaming Edition
    lite: bool = False       # incluído no WINDOWS ULTRA LITE
    min_build: int = 0       # build mínima do Windows (22000 = Windows 11)

    @property
    def gid(self) -> str:
        return f"tweak:{self.id}"

    def get_changes(self) -> list[RegChange]:
        return self.changes() if callable(self.changes) else list(self.changes)

    def requires_admin(self) -> bool:
        return any(c.hive == "HKLM" for c in self.get_changes())

    def status(self) -> str:
        ch = self.get_changes()
        if not ch:
            return "indisponivel"
        n = sum(1 for c in ch if c.is_applied())
        return "aplicado" if n == len(ch) else ("parcial" if n else "nao")

    def preview_lines(self) -> list[str]:
        lines = [c.describe() for c in self.get_changes()]
        if self.reboot:
            lines.append("⚠ Requer reinício do Windows para efeito completo.")
        return lines

    def apply(self, journal: Journal):
        journal.group(self.gid, self.title, self.category)
        for c in self.get_changes():
            journal.reg_set(self.gid, c.hive, c.path, c.name, c.typ, c.value)
        if self.after:
            self.after()

    def revert(self, journal: Journal) -> list[str]:
        errors = journal.revert_group(self.gid)
        if self.after:
            self.after()
        return errors


# ======================================================================== helpers
def D(hive, path, name, value) -> RegChange:
    return RegChange(hive, path, name, REG_DWORD, value)


def S(hive, path, name, value) -> RegChange:
    return RegChange(hive, path, name, REG_SZ, value)


_MM = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
_GAMES = _MM + r"\Tasks\Games"
_TCPIP_IF = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
_DX_PREF = r"Software\Microsoft\DirectX\UserGpuPreferences"
_ADV = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
_CDM = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"


def _nagle_changes() -> list[RegChange]:
    """Desativa o algoritmo de Nagle somente nas interfaces de rede com IP configurado."""
    out = []
    for guid in reg.list_subkeys("HKLM", _TCPIP_IF):
        path = f"{_TCPIP_IF}\\{guid}"
        vals = {n.lower(): v for n, v, _t in reg.list_values("HKLM", path)}
        ip = vals.get("dhcpipaddress") or vals.get("ipaddress")
        if isinstance(ip, list):
            ip = ip[0] if ip else ""
        if ip and ip not in ("0.0.0.0", ""):
            out += [D("HKLM", path, "TcpAckFrequency", 1), D("HKLM", path, "TCPNoDelay", 1)]
    return out


def _windowed_games_changes() -> list[RegChange]:
    """Ativa 'Otimizações para jogos em janela' e VRR preservando outras chaves do valor."""
    _e, _t, cur = reg.read_value("HKCU", _DX_PREF, "DirectXUserGlobalSettings")
    pairs = {}
    for part in str(cur or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            pairs[k.strip()] = v.strip()
    pairs["SwapEffectUpgradeEnable"] = "1"
    pairs["VRROptimizeEnable"] = "1"
    value = "".join(f"{k}={v};" for k, v in pairs.items())
    return [S("HKCU", _DX_PREF, "DirectXUserGlobalSettings", value)]


# ======================================================================== catálogo
TWEAKS: list[Tweak] = [
    # ---------------------------------------------------------------- JOGOS
    Tweak("game_mode", "gaming", "Ativar Game Mode do Windows",
          "Prioriza o jogo em execução e evita que o Windows Update instale drivers/reinicie durante a partida.",
          [D("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1),
           D("HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode", 1)],
          benefit="FPS mais estável, menos interrupções.", turbo=True, gamer=True),
    Tweak("game_dvr_off", "gaming", "Desativar gravação em segundo plano (Game DVR)",
          "A Xbox Game Bar grava continuamente em segundo plano, consumindo GPU e disco.",
          [D("HKCU", r"System\GameConfigStore", "GameDVR_Enabled", 0),
           D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0)],
          benefit="Ganho de 2-10% de FPS em GPUs modestas.",
          note="Você perde o recurso 'Gravar o que aconteceu' (Win+Alt+G).", turbo=True, gamer=True),
    Tweak("hags", "gaming", "Agendamento de GPU acelerado por hardware (HAGS)",
          "Deixa a própria GPU gerenciar sua fila de trabalho, reduzindo latência de CPU→GPU.",
          [D("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 2)],
          benefit="Menor latência; necessário para DLSS Frame Generation.",
          note="Requer GPU compatível (NVIDIA GTX 10+, AMD RX 5000+) e driver WDDM 2.7+.",
          reboot=True, gamer=True),
    Tweak("windowed_opt", "gaming", "Otimizações para jogos em janela + VRR",
          "Usa o modelo de apresentação 'flip' em jogos DX10/11 em janela/borderless: menor latência e "
          "suporte a G-Sync/FreeSync.",
          _windowed_games_changes, benefit="Input lag de borderless próximo ao de tela cheia.",
          turbo=True, gamer=True),
    Tweak("fse_exclusive", "gaming", "Forçar tela cheia exclusiva (desativar FSO global)",
          "Desativa as 'Otimizações de tela cheia' para todos os jogos, usando o modo exclusivo clássico.",
          [D("HKCU", r"System\GameConfigStore", "GameDVR_FSEBehaviorMode", 2),
           D("HKCU", r"System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", 1),
           D("HKCU", r"System\GameConfigStore", "GameDVR_FSEBehavior", 2),
           D("HKCU", r"System\GameConfigStore", "GameDVR_DXGIHonorFSEWindowsCompatible", 1)],
          benefit="Pode reduzir input lag em jogos DX9/DX11 antigos.",
          note="No Windows 11 o FSO normalmente já é eficiente e o Auto HDR depende dele. Teste com e sem.",
          risk="Médio"),
    Tweak("mmcss_games", "gaming", "Prioridade máxima de CPU/GPU para jogos (MMCSS)",
          "Ajusta o agendador multimídia para dar prioridade de CPU, GPU e E/S às tarefas de jogo e "
          "reduz a reserva de CPU para tarefas de fundo de 20% para 10%.",
          [D("HKLM", _MM, "SystemResponsiveness", 10),
           D("HKLM", _GAMES, "GPU Priority", 8), D("HKLM", _GAMES, "Priority", 6),
           S("HKLM", _GAMES, "Scheduling Category", "High"), S("HKLM", _GAMES, "SFIO Priority", "High")],
          benefit="Menos micro-travamentos com programas em segundo plano.", turbo=True, gamer=True),
    Tweak("priority_sep", "gaming", "Priorizar o programa em primeiro plano",
          "Win32PrioritySeparation=0x26: quantum curto e variável com boost para a janela ativa.",
          [D("HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation", 0x26)],
          benefit="Jogo/app ativo recebe mais tempo de CPU.", turbo=True, gamer=True),
    Tweak("mouse_raw", "gaming", "Desativar aceleração do mouse (precisão do ponteiro)",
          "Movimento 1:1 do mouse, essencial para mira consistente em jogos de tiro.",
          [S("HKCU", r"Control Panel\Mouse", "MouseSpeed", "0"),
           S("HKCU", r"Control Panel\Mouse", "MouseThreshold1", "0"),
           S("HKCU", r"Control Panel\Mouse", "MouseThreshold2", "0")],
          benefit="Mira consistente; menor sensação de input lag.",
          after=winapi.apply_mouse_settings_live, gamer=True),
    Tweak("network_throttling", "gaming", "Remover limitação de rede multimídia",
          "NetworkThrottlingIndex=FFFFFFFF: o Windows deixa de limitar pacotes de rede durante reprodução "
          "multimídia.",
          [D("HKLM", _MM, "NetworkThrottlingIndex", 0xFFFFFFFF)],
          benefit="Latência de rede mais estável em jogos online.", turbo=True, gamer=True),

    # ---------------------------------------------------------------- REDE
    Tweak("nagle_off", "rede", "Desativar algoritmo de Nagle (TCP NoDelay)",
          "Envia pacotes TCP imediatamente em vez de agrupá-los. Aplicado nas placas de rede ativas.",
          _nagle_changes, benefit="Reduz latência em jogos que usam TCP (MMOs, alguns MOBAs).",
          note="Jogos que usam UDP (maioria dos FPS) não são afetados.", gamer=True),

    # ---------------------------------------------------------------- ENERGIA / PROCESSADOR
    Tweak("power_throttling_off", "energia", "Desativar Power Throttling",
          "Impede o Windows de reduzir a frequência de CPU de processos em segundo plano.",
          [D("HKLM", r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling", "PowerThrottlingOff", 1)],
          benefit="CPU sempre em desempenho total.", note="Em notebooks na bateria aumenta o consumo.",
          turbo=True, gamer=True),

    # ---------------------------------------------------------------- RESPONSIVIDADE
    Tweak("menu_delay", "responsividade", "Menus instantâneos",
          "Reduz o atraso de abertura de menus e submenus de 400 ms para 0 ms.",
          [S("HKCU", r"Control Panel\Desktop", "MenuShowDelay", "0")],
          benefit="Interface mais rápida.", turbo=True),
    Tweak("startup_delay", "responsividade", "Remover atraso de apps na inicialização",
          "O Windows espera alguns segundos antes de abrir os apps de inicialização; isso remove a espera.",
          [D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize", "StartupDelayInMSec", 0)],
          benefit="Área de trabalho utilizável mais cedo.", turbo=True),
    Tweak("hover_time", "responsividade", "Resposta rápida ao passar o mouse",
          "Reduz o tempo de hover (miniaturas da barra de tarefas, dicas) de 400 ms para 100 ms.",
          [S("HKCU", r"Control Panel\Mouse", "MouseHoverTime", "100"),
           D("HKCU", _ADV, "ExtendedUIHoverTime", 100)],
          benefit="Interface mais responsiva."),
    Tweak("app_shutdown", "responsividade", "Encerramento mais rápido de apps travados",
          "Reduz o tempo que o Windows espera por apps que não respondem ao desligar (sem forçar fechamento "
          "automático, para não perder dados).",
          [S("HKCU", r"Control Panel\Desktop", "HungAppTimeout", "3000"),
           S("HKCU", r"Control Panel\Desktop", "WaitToKillAppTimeout", "5000")],
          benefit="Desligamento/reinício mais rápido."),

    # ---------------------------------------------------------------- EFEITOS VISUAIS
    Tweak("visual_anim", "visual", "Desativar animações de janelas e barra de tarefas",
          "Remove animações de minimizar/maximizar e da barra de tarefas.",
          [S("HKCU", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", "0"),
           D("HKCU", _ADV, "TaskbarAnimations", 0),
           D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", 3)],
          benefit="Janelas abrem instantaneamente; menos carga na GPU integrada.",
          after=winapi.apply_visual_settings_live, turbo=True),
    Tweak("visual_transparency", "visual", "Desativar transparência (efeito acrílico)",
          "Remove o desfoque/transparência do Iniciar, barra de tarefas e janelas.",
          [D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 0)],
          benefit="Menor uso de GPU pelo DWM, útil em GPUs integradas.",
          after=winapi.broadcast_settings_change),
    Tweak("visual_misc", "visual", "Desativar sombras, Aero Peek e seleção translúcida",
          "Remove efeitos secundários do Explorer.",
          [D("HKCU", _ADV, "ListviewAlphaSelect", 0), D("HKCU", _ADV, "ListviewShadow", 0),
           D("HKCU", r"Software\Microsoft\Windows\DWM", "EnableAeroPeek", 0)],
          benefit="Explorer mais leve.", after=winapi.broadcast_settings_change),

    # ---------------------------------------------------------------- SEGUNDO PLANO
    Tweak("bg_apps", "segundo_plano", "Bloquear apps da Store em segundo plano",
          "Impede que apps da Microsoft Store fiquem rodando em segundo plano (notificações de apps "
          "UWP podem atrasar).",
          [D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications",
             "GlobalUserDisabled", 1),
           D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Search", "BackgroundAppGlobalToggle", 0)],
          benefit="Menos RAM e CPU usadas por apps ocultos.", turbo=True),
    Tweak("suggestions_off", "segundo_plano", "Desativar sugestões, dicas e apps instalados automaticamente",
          "Desliga as dicas do Windows, sugestões no Iniciar e a instalação silenciosa de apps promocionais.",
          [D("HKCU", _CDM, "SubscribedContent-338389Enabled", 0),
           D("HKCU", _CDM, "SubscribedContent-338388Enabled", 0),
           D("HKCU", _CDM, "SubscribedContent-353698Enabled", 0),
           D("HKCU", _CDM, "SystemPaneSuggestionsEnabled", 0),
           D("HKCU", _CDM, "SilentInstalledAppsEnabled", 0),
           D("HKCU", _CDM, "SoftLandingEnabled", 0)],
          benefit="Menos processos e downloads em segundo plano.", turbo=True),
    Tweak("telemetry_min", "segundo_plano", "Telemetria no nível mínimo permitido",
          "Reduz a coleta de dados de diagnóstico para o mínimo suportado pela sua edição do Windows.",
          [D("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", 1)],
          benefit="Menos uso de disco/rede pelo serviço de telemetria."),
    Tweak("delivery_opt", "segundo_plano", "Desativar envio de atualizações para outros PCs (P2P)",
          "O Windows Update continua funcionando normalmente; apenas deixa de usar sua internet para "
          "enviar atualizações a outros computadores.",
          [D("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization", "DODownloadMode", 0)],
          benefit="Libera banda de upload (menor ping em jogos).", turbo=True),
    Tweak("edge_bg", "segundo_plano", "Impedir o Edge de rodar em segundo plano",
          "Desativa o 'Aumento de inicialização' e a execução do Edge depois de fechado.",
          [D("HKLM", r"SOFTWARE\Policies\Microsoft\Edge", "StartupBoostEnabled", 0),
           D("HKLM", r"SOFTWARE\Policies\Microsoft\Edge", "BackgroundModeEnabled", 0)],
          benefit="Economiza 100-400 MB de RAM.", turbo=True),
    Tweak("widgets_off", "segundo_plano", "Desativar Widgets da barra de tarefas",
          "Os Widgets mantêm um processo WebView com notícias sempre carregado.",
          [D("HKLM", r"SOFTWARE\Policies\Microsoft\Dsh", "AllowNewsAndInterests", 0)],
          benefit="Economiza 150-300 MB de RAM.", turbo=True),
]

def _svchost_changes() -> list[RegChange]:
    """Agrupa serviços em menos processos svchost (limite = RAM total em KB)."""
    try:
        import psutil
        kb = int(psutil.virtual_memory().total // 1024)
    except Exception:
        return []
    return [D("HKLM", r"SYSTEM\CurrentControlSet\Control", "SvcHostSplitThresholdInKB", min(kb, 0xFFFFFFFF))]


_POL = r"SOFTWARE\Policies\Microsoft\Windows"
_HKCU_POL = r"Software\Policies\Microsoft\Windows"

TWEAKS += [
    # ---------------------------------------------------------------- JOGOS (Gaming Edition)
    Tweak("keyboard_fast", "gaming", "Teclado com resposta máxima",
          "Atraso de repetição mínimo e velocidade de repetição máxima do teclado.",
          [S("HKCU", r"Control Panel\Keyboard", "KeyboardDelay", "0"),
           S("HKCU", r"Control Panel\Keyboard", "KeyboardSpeed", "31")],
          benefit="Movimentação e comandos repetidos respondem mais rápido.",
          after=winapi.apply_keyboard_settings_live, gamer=True),
    Tweak("gamebar_tips_off", "gaming", "Desativar painel e dicas da Game Bar",
          "Impede a Game Bar de abrir painéis e dicas ao iniciar jogos (o Game Mode continua ativo).",
          [D("HKCU", r"Software\Microsoft\GameBar", "ShowStartupPanel", 0),
           D("HKCU", r"Software\Microsoft\GameBar", "UseNexusForGameBarEnabled", 0)],
          benefit="Sem sobreposições inesperadas no início da partida.", gamer=True),
    Tweak("cpu_priority_games_io", "gaming", "Prioridade de E/S e memória para jogos (MMCSS)",
          "Garante que tarefas de jogo do agendador multimídia não sejam rebaixadas (Affinity/Background Only).",
          [D("HKLM", _GAMES, "Affinity", 0), S("HKLM", _GAMES, "Background Only", "False"),
           D("HKLM", _GAMES, "Clock Rate", 10000)],
          benefit="Agendamento consistente das threads de áudio/jogo.", gamer=True),

    # ---------------------------------------------------------------- EFEITOS VISUAIS
    Tweak("visual_best", "visual", "Efeitos visuais: melhor desempenho (mantendo fontes suaves)",
          "Equivale a 'Ajustar para obter melhor desempenho', mas mantém o ClearType e as miniaturas.",
          [RegChange("HKCU", r"Control Panel\Desktop", "UserPreferencesMask", REG_BINARY,
                     bytes.fromhex("9012038010000000")),
           S("HKCU", r"Control Panel\Desktop", "DragFullWindows", "0"),
           S("HKCU", r"Control Panel\Desktop", "FontSmoothing", "2"),
           D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", 3)],
          benefit="Interface mais leve; menos trabalho para o DWM durante jogos.",
          note="Efeito completo após sair e entrar novamente na conta.",
          after=winapi.apply_visual_settings_live, lite=True, gamer=True),

    # ---------------------------------------------------------------- PRIVACIDADE / RECURSOS DE IA
    Tweak("copilot_off", "privacidade", "Desativar Copilot do Windows",
          "Remove o Copilot da barra de tarefas e impede sua execução em segundo plano.",
          [D("HKCU", _HKCU_POL + r"\WindowsCopilot", "TurnOffWindowsCopilot", 1),
           D("HKLM", _POL + r"\WindowsCopilot", "TurnOffWindowsCopilot", 1),
           D("HKCU", _ADV, "ShowCopilotButton", 0)],
          benefit="Menos um processo WebView carregado (~100-200 MB).", lite=True, min_build=22621),
    Tweak("recall_off", "privacidade", "Desativar Recall (capturas de tela por IA)",
          "Impede o Windows de salvar instantâneos da tela para a linha do tempo de IA (PCs Copilot+).",
          [D("HKCU", _HKCU_POL + r"\WindowsAI", "DisableAIDataAnalysis", 1),
           D("HKLM", _POL + r"\WindowsAI", "DisableAIDataAnalysis", 1)],
          benefit="Elimina gravação contínua em disco e uso de NPU/CPU.", lite=True, min_build=22621),
    Tweak("web_search_off", "privacidade", "Pesquisa do Iniciar somente local (sem Bing)",
          "A busca do menu Iniciar deixa de consultar a internet a cada tecla digitada.",
          [D("HKCU", _HKCU_POL + r"\Explorer", "DisableSearchBoxSuggestions", 1),
           D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Search", "BingSearchEnabled", 0)],
          benefit="Busca do Iniciar mais rápida e sem tráfego de rede.", lite=True),
    Tweak("activity_off", "privacidade", "Desativar histórico de atividades",
          "Para de registrar e enviar a linha do tempo de apps e arquivos abertos.",
          [D("HKLM", _POL + r"\System", "EnableActivityFeed", 0),
           D("HKLM", _POL + r"\System", "PublishUserActivities", 0),
           D("HKLM", _POL + r"\System", "UploadUserActivities", 0)],
          benefit="Menos escrita em disco e tarefas de fundo.", lite=True),
    Tweak("ads_off", "privacidade", "Desativar ID de publicidade e experiências personalizadas",
          "Apps deixam de usar um identificador de anúncios; o Windows para de personalizar dicas com seus dados.",
          [D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", 0),
           D("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Privacy",
             "TailoredExperiencesWithDiagnosticDataEnabled", 0),
           D("HKCU", r"Software\Microsoft\Siuf\Rules", "NumberOfSIUFInPeriod", 0)],
          benefit="Menos rastreamento e solicitações de feedback.", lite=True),
    Tweak("start_clean", "privacidade", "Iniciar e barra de tarefas mais limpos",
          "Remove recomendações/dicas do Iniciar, rastreamento de apps abertos e o botão de Chat/Teams.",
          [D("HKCU", _ADV, "Start_IrisRecommendations", 0), D("HKCU", _ADV, "Start_TrackProgs", 0),
           D("HKCU", _ADV, "TaskbarMn", 0)],
          benefit="Iniciar abre mais rápido; Teams pessoal não pré-carrega.", lite=True, min_build=22000),
    Tweak("cortana_off", "privacidade", "Desativar Cortana",
          "Impede a Cortana de rodar (já descontinuada no Windows 11).",
          [D("HKLM", _POL + r"\Windows Search", "AllowCortana", 0)], benefit="Menos um processo de fundo.",
          lite=True),
    Tweak("wer_off", "privacidade", "Desativar envio de relatórios de erro",
          "Falhas de apps deixam de gerar e enviar relatórios para a Microsoft (o log de eventos continua).",
          [D("HKLM", r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "Disabled", 1)],
          benefit="Sem picos de CPU/disco após travamentos de jogos.", lite=True),

    # ---------------------------------------------------------------- MEMÓRIA EM IDLE
    Tweak("svchost_split", "segundo_plano", "Agrupar serviços do Windows (menos processos svchost)",
          "Faz o Windows hospedar serviços em menos processos svchost.exe. Reduz a contagem de processos em "
          "30-50% e um pouco a RAM em idle.",
          _svchost_changes, benefit="Menos processos e trocas de contexto.",
          note="Se um serviço do grupo falhar, os outros do mesmo processo reiniciam juntos. Reversível.",
          risk="Médio", reboot=True, lite=True),
]

TWEAKS_BY_ID = {t.id: t for t in TWEAKS}

# Otimizações já existentes que também fazem parte do WINDOWS ULTRA LITE
for _tid in ("visual_anim", "visual_transparency", "visual_misc", "bg_apps", "suggestions_off", "telemetry_min",
             "delivery_opt", "edge_bg", "widgets_off", "menu_delay", "startup_delay", "hover_time",
             "power_throttling_off", "priority_sep", "game_dvr_off"):
    TWEAKS_BY_ID[_tid].lite = True
TWEAKS_BY_ID["widgets_off"].min_build = 22000
TWEAKS_BY_ID["windowed_opt"].min_build = 22000

CATEGORIES = {
    "gaming": "Jogos",
    "rede": "Rede",
    "energia": "Energia e processador",
    "responsividade": "Responsividade",
    "visual": "Efeitos visuais",
    "segundo_plano": "Segundo plano",
    "privacidade": "Privacidade, telemetria e IA",
}


def by_category(cat: str) -> list[Tweak]:
    return [t for t in TWEAKS if t.category == cat]
