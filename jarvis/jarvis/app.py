"""Inicialização e integração de todos os componentes do JARVIS."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import webbrowser

from . import __version__
from .actions import REGISTRY
from .actions.apps import AppCatalog
from .actions.reminders import ReminderService
from .actions.volume import VolumeController
from .brain.assistant import Assistant, Reply
from .brain.llm import LLMClient
from .brain.services import Services
from .core import paths
from .core.config import Settings
from .core.events import EventBus
from .core.logging_setup import setup_logging
from .core.secrets import SecretStore
from .core.storage import Storage
from .gaming.gamemode import GameModeMonitor
from .gaming.gamepad import GamepadWatcher
from .gaming.hotkeys import HotkeyManager
from .integrations.msgraph.auth import GraphAuth
from .integrations.msgraph.client import GraphClient
from .integrations.msgraph.excel import ExcelService
from .integrations.msgraph.outlook import OutlookService
from .integrations.rota.service import RotaService
from .integrations.spotify import SpotifyService
from .integrations.whatsapp import WhatsAppService
from .notifications.center import NotificationCenter

log = logging.getLogger("jarvis")


class JarvisApp:
    def __init__(self, enable_voice: bool = True) -> None:
        self.quitting = False
        self.window = None
        self.tray = None
        self.qt_app = None
        self._tray_hint_shown = False
        self.speaker = None
        self.pipeline = None

        settings = Settings()
        storage = Storage()
        bus = EventBus()
        secrets = SecretStore()
        self.services = services = Services(settings=settings, storage=storage, bus=bus, secrets=secrets)
        services.open_url = self.open_url
        storage.purge_older_than(int(settings.get("memory.keep_days", 30)))

        services.llm = LLMClient(settings, secrets)
        services.notifications = NotificationCenter(settings, storage, bus, services.state, announce=self._announce)
        services.reminders = ReminderService(storage, bus, on_due=self._reminder_due)
        services.apps = AppCatalog(settings)
        services.volume = VolumeController()
        services.graph = GraphAuth(settings, bus)
        client = GraphClient(services.graph)
        services.outlook = OutlookService(client, services.graph, settings, storage, bus, services.notifications, services.llm)
        services.excel = ExcelService(client, services.graph, settings, storage, bus, services.notifications, services.llm)
        services.whatsapp = WhatsAppService(settings, storage, bus, services.notifications, self.open_url)
        services.extras["spotify"] = SpotifyService(settings, secrets, bus, self.open_url)
        services.extras["rota"] = RotaService(settings, bus)
        self.assistant = Assistant(services)
        self.hotkeys = HotkeyManager()
        self.gamepad = GamepadWatcher(settings)
        self.gamemode = GameModeMonitor(services)
        self.enable_voice = enable_voice
        settings.on_change(self._on_setting)

    # --------------------------------------------------------------- partida
    def start_background(self) -> None:
        s = self.services
        if self.enable_voice:
            try:
                from .audio.speaker import Speaker

                self.speaker = Speaker(s.settings, s.bus, s.state, s.secrets)
                s.speaker = self.speaker
                self.speaker.prewarm_async()
                from .audio.music import MusicPlayer

                s.extras["music"] = MusicPlayer(s.settings, s.bus)
                if s.settings.get("music.play_on_startup", False) and s.settings.get("music.file"):
                    threading.Timer(2.0, lambda: s.state.game_mode or s.extras["music"].play()).start()
            except Exception as exc:  # noqa: BLE001 - sem dispositivo de áudio
                log.exception("Áudio indisponível")
                s.bus.publish("activity", text=f"Áudio indisponível: {exc}", kind="error")
            threading.Thread(target=self._start_voice, name="voice-init", daemon=True).start()
        s.reminders.start()
        s.whatsapp.start()
        if s.settings.get("outlook.enabled", False):
            s.outlook.start_polling()
        s.excel.start_watch()
        self.gamemode.start()
        self._start_inputs()
        cache = paths.cache_dir() / "apps.json"
        if not cache.exists() or time.time() - cache.stat().st_mtime > 86400:
            s.apps.refresh_async()
        self._publish_connections()
        s.activity(f"JARVIS {__version__} iniciado", kind="system")
        if self.enable_voice and not s.storage.kv_get("wake.calibrated"):
            hint = ("Primeiro uso: em Configurações > Ativação, clique em 'Calibrar com a minha voz' para eu "
                    "reconhecer melhor quando você disser Jarvis. Enquanto isso, use Ctrl+Alt+J ou o botão Falar.")
            s.bus.publish("activity", text=hint, kind="system")
            s.bus.publish("toast", title="JARVIS", text=hint)

    def _publish_connections(self) -> None:
        s = self.services
        s.extras["spotify"].publish_status()
        s.extras["rota"].publish_status()
        threading.Thread(target=self._restore_rota, name="rota-restore", daemon=True).start()
        provider = s.settings.get("ai.provider", "none")
        if provider == "none":
            s.bus.publish("connection", service="ai", status="off", detail="Somente comandos locais")
        elif s.llm.available():
            s.bus.publish("connection", service="ai", status="ok", detail=provider)
        else:
            s.bus.publish("connection", service="ai", status="error", detail="Chave não configurada")
        graph = s.graph
        if not graph.configured:
            for service in ("outlook", "excel"):
                s.bus.publish("connection", service=service, status="off", detail="Não configurado")
        else:
            threading.Thread(target=self._check_microsoft, daemon=True).start()

    def _restore_rota(self) -> None:
        """Rota montada salva volta ao abrir (como na ferramenta)."""
        from datetime import date

        rota = self.services.extras["rota"]
        if rota.restore():
            self.services.activity(f"Rota {rota.day_label(date.fromisoformat(rota.result['data']))} "
                                   f"restaurada ({rota.allocated()} notas)", kind="rota")

    def _check_microsoft(self) -> None:
        name = self.services.graph.account_name()
        status = ("ok", f"Conectado: {name}") if name else ("off", "Não conectado")
        for service in ("outlook", "excel"):
            self.services.bus.publish("connection", service=service, status=status[0], detail=status[1])

    def _start_voice(self) -> None:
        try:
            self.pipeline = build_pipeline(self.services, self.speaker, self._voice_handler)
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao iniciar a voz")
            self.services.bus.publish("connection", service="microphone", status="error", detail=str(exc)[:120])
            return
        if self.pipeline is None:
            return
        self.services.pipeline = self.pipeline
        if self.speaker is not None:
            self.speaker.on_idle = self.pipeline._publish_state
        self.pipeline.on_calibrated = lambda words: self.services.storage.kv_set("wake.calibrated", words)
        self.pipeline.start()

    def _start_inputs(self) -> None:
        hk = self.services.settings.get("gaming.hotkeys", {}) or {}
        self.hotkeys.start([
            (hk.get("stop_speech", ""), self.stop_speech),
            (hk.get("push_to_talk", ""), self.push_to_talk),
            (hk.get("toggle_mic", ""), lambda: self.set_mic(not self.services.state.mic_enabled)),
        ])
        if self.hotkeys.errors:
            self.services.bus.publish("activity", text="Atalhos com conflito: " + "; ".join(self.hotkeys.errors), kind="error")
        self.gamepad.stop()
        self.gamepad = GamepadWatcher(self.services.settings)
        self.gamepad.start(on_talk=lambda: self.push_to_talk("gamepad"), on_stop=self.stop_speech)

    # ---------------------------------------------------------------- ações
    def _voice_handler(self, text: str, confidence: float, source: str) -> Reply:
        return self.assistant.handle(text, source=source, confidence=confidence)

    def submit_text(self, text: str) -> None:
        # uma nova interação interrompe a fala anterior
        if self.speaker is not None:
            self.speaker.stop()

        def work() -> None:
            reply = self.assistant.handle(text, source="text")
            if reply.speak and reply.text:
                self.speak(reply.text)
        threading.Thread(target=work, name="text-command", daemon=True).start()

    def run_action(self, name: str, params: dict) -> None:
        def work() -> None:
            result = REGISTRY.run(self.services, name, params)
            self.services.bus.publish("reply", text=result.say, display=result.display, ok=result.ok)
            self.speak(result.say)
            if self.tray is not None:
                self.services.bus.publish("settings", key=name)
        threading.Thread(target=work, daemon=True).start()

    def confirm(self, accepted: bool) -> None:
        self.submit_text("sim" if accepted else "não")

    def speak(self, text: str, force: bool = False) -> None:
        if self.speaker is not None:
            self.speaker.say(text, force=force)

    def stop_speech(self) -> None:
        if self.speaker is not None:
            self.speaker.stop()
        self.services.state.cancel_event.set()

    def push_to_talk(self, source: str = "manual") -> None:
        if self.pipeline is None:
            self.services.bus.publish("activity", text="Reconhecimento de voz não está ativo.", kind="error")
            return
        if not self.services.state.mic_enabled:
            self.set_mic(True)
        self.pipeline.trigger(source if isinstance(source, str) else "manual")

    def set_mic(self, enabled: bool) -> None:
        self.services.state.mic_enabled = enabled
        if self.pipeline is not None:
            self.pipeline.set_mic_enabled(enabled)
        else:
            self.services.bus.publish("state", state="idle" if enabled else "suspended")
        self.services.activity("Microfone " + ("ligado" if enabled else "desligado"), kind="system")
        if self.tray is not None:
            self.services.bus.publish("settings", key="mic")

    def open_url(self, url: str) -> None:
        if sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            webbrowser.open(url)

    # ------------------------------------------------------- notificações
    def _announce(self, text: str, important: bool) -> None:
        state = self.services.state
        if self.window is not None and self.tray is not None and not self.window.isVisible() and not state.game_mode:
            self.services.bus.publish("toast", title="JARVIS", text=text)
        if self.speaker is not None and not self.assistant.pending:
            self.speaker.say(text)

    def _reminder_due(self, item: dict) -> None:
        text = item.get("text", "Lembrete")
        self.services.notifications.add(source="reminder", sender="Lembrete", title=text, body=text, important=True,
                                        key=f"reminder:{item['id']}", announce=False)
        if self.services.state.mic_enabled and not self.services.state.quiet_mode:
            self.speak(f"Lembrete: {text}.")
        self.services.bus.publish("toast", title="Lembrete", text=text)

    # ---------------------------------------------------------- configurações
    def _on_setting(self, key: str, value) -> None:
        self.services.bus.publish("settings", key=key)
        if key in ("voice.profile", "*") and self.speaker is not None:
            self.speaker.prewarm_async()

    def on_settings_saved(self) -> None:
        if self.pipeline is not None:
            self.pipeline.reload_wake()
        self._start_inputs()
        self._publish_connections()

    def on_microsoft_connected(self) -> None:
        self._publish_connections()
        self.services.activity("Conta Microsoft conectada", kind="system")

    # ------------------------------------------------------------ interface
    def run_gui(self, start_minimized: bool | None = None) -> int:
        from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

        from .ui import theme
        from .ui.bridge import EventBridge
        from .ui.main_window import MainWindow
        from .ui.tray import Tray

        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.qt_app.setApplicationName("JARVIS")
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.qt_app.setStyleSheet(theme.STYLESHEET)
        self.bridge = EventBridge(self.services.bus)
        self.window = MainWindow(self)
        self.bridge.event.connect(self.window.handle_event)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(self)
            self.tray.show()

        def on_event(topic: str, payload: dict) -> None:
            if topic == "toast" and self.tray is not None:
                self.tray.showMessage(payload.get("title", "JARVIS"), payload.get("text", ""), self.tray.icon(), 5000)
            elif topic in ("settings", "game_mode", "state") and self.tray is not None:
                self.tray.refresh()
            elif topic == "login_code":
                box = QMessageBox(self.window)
                box.setWindowTitle("Login Microsoft")
                box.setText(f"Acesse {payload.get('url')} e digite o código:\n\n{payload.get('code')}")
                box.setTextInteractionFlags(box.textInteractionFlags())
                box.setModal(False)
                box.show()
                self.open_url(payload.get("url", "https://microsoft.com/devicelogin"))

        self.bridge.event.connect(on_event)
        self.window.load_history(self.services.notifications.recent(50), self.services.storage.recent_activity(30))
        self.start_background()
        minimized = self.services.settings.get("general.start_minimized", True) if start_minimized is None else start_minimized
        if not minimized or self.tray is None:
            self.window.present()
        code = self.qt_app.exec()
        self.shutdown()
        return code

    def show_window(self) -> None:
        if self.window is not None:
            self.window.present()

    def notify_tray_once(self) -> None:
        if self.tray is not None and not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.showMessage("JARVIS", "Continuo ativo na bandeja. Diga \"Jarvis\" quando precisar.",
                                  self.tray.icon(), 4000)

    def open_settings(self) -> None:
        from .ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self, self.window)
        dialog.exec()

    def quit(self) -> None:
        self.quitting = True
        if self.qt_app is not None:
            self.qt_app.quit()

    def shutdown(self) -> None:
        s = self.services
        for stopper in (lambda: self.pipeline and self.pipeline.stop(), self.hotkeys.stop, self.gamepad.stop,
                        self.gamemode.stop, s.reminders.stop, s.whatsapp.stop, s.outlook.stop, s.excel.stop,
                        lambda: s.extras.get("music") and s.extras["music"].stop(fade=False),
                        lambda: s.extras.get("rota") and s.extras["rota"].close(),
                        lambda: self.speaker and self.speaker.shutdown()):
            try:
                stopper()
            except Exception:  # noqa: BLE001
                log.debug("Erro ao encerrar", exc_info=True)
        s.storage.close()

    # ------------------------------------------------------------ modo texto
    def run_cli(self, speak: bool = False) -> int:
        if speak:
            self.start_background()
        else:
            self.services.reminders.start()
            self.services.whatsapp.start()
        name = "FRIDAY" if self.services.settings.get("voice.profile") == "friday" else "JARVIS"
        print(f"{name} em modo texto. Digite um comando (ou 'sair').")
        while True:
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() in ("sair", "exit", "quit"):
                break
            if not text:
                continue
            reply = self.assistant.handle(text, source="text")
            if reply.text:
                print(f"{name}: {reply.text}")
            if reply.display:
                print(reply.display)
            if speak and reply.text:
                self.speak(reply.text)
        self.shutdown()
        return 0


def build_pipeline(services, speaker, handler):
    """Monta detector de ativação + reconhecimento local + microfone."""
    from .audio.capture import MicStream
    from .audio.stt import VoskSTT, WhisperSTT
    from .audio.wakeword import PorcupineWakeDetector, VoskWakeDetector
    from .voice.pipeline import VoicePipeline

    settings, bus = services.settings, services.bus
    if speaker is None:
        bus.publish("connection", service="microphone", status="error", detail="Sem dispositivo de áudio")
        return None
    model_path = paths.models_dir() / settings.get("stt.vosk_model", "vosk-model-small-pt-0.3")
    if not model_path.exists():
        bus.publish("connection", service="microphone", status="error",
                    detail="Modelo de voz ausente: execute scripts\\download_models.py")
        bus.publish("activity", kind="error",
                    text=f"Modelo de voz não encontrado em {model_path}. Execute: python scripts\\download_models.py")
        return None
    from vosk import Model, SetLogLevel

    SetLogLevel(-1)
    model = Model(str(model_path))
    stt = VoskSTT(model)
    if settings.get("stt.engine") == "whisper":
        try:
            stt = WhisperSTT(settings.get("stt.whisper_model", "small"))
        except Exception:  # noqa: BLE001
            log.exception("Whisper indisponível; usando Vosk")
            bus.publish("activity", kind="error", text="Whisper indisponível; usando reconhecimento Vosk.")

    def wake_factory():
        engine = settings.get("wake.engine", "vosk")
        sensitivity = float(settings.get("wake.sensitivity", 0.5))
        if engine == "off":
            return None
        if engine == "porcupine":
            key = services.secrets.get("porcupine_access_key")
            if key:
                try:
                    return PorcupineWakeDetector(key, "jarvis", sensitivity)
                except Exception:  # noqa: BLE001
                    log.exception("Porcupine indisponível; usando Vosk")
                    bus.publish("activity", kind="error", text="Porcupine indisponível; usando detecção Vosk.")
        words = (settings.get("wake.variants", []) or []) + (settings.get("wake.words", []) or [])
        return VoskWakeDetector(model, words, sensitivity)

    return VoicePipeline(settings, bus, services.state, speaker, MicStream(settings.get("audio.input_device")),
                         wake_factory, stt, handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS - assistente pessoal por voz")
    parser.add_argument("--minimized", action="store_true", help="inicia na bandeja do sistema")
    parser.add_argument("--show", action="store_true", help="inicia com a janela aberta")
    parser.add_argument("--cli", action="store_true", help="modo texto no terminal (sem interface)")
    parser.add_argument("--speak", action="store_true", help="no modo texto, também fala as respostas")
    parser.add_argument("--no-voice", action="store_true", help="desativa microfone e voz")
    parser.add_argument("--debug", action="store_true", help="logs detalhados")
    parser.add_argument("--version", action="version", version=f"JARVIS {__version__}")
    args = parser.parse_args(argv)

    setup_logging("DEBUG" if args.debug else "INFO", console=args.cli or args.debug)
    from .core.envfile import load_env

    load_env()  # chaves de API do arquivo .env (ex.: FISH_AUDIO_API_KEY)
    from .platform.windows import SingleInstance

    instance = SingleInstance()
    if instance.already_running:
        print("O JARVIS já está em execução (veja o ícone na bandeja).")
        return 1
    app = JarvisApp(enable_voice=not args.no_voice and (not args.cli or args.speak))
    if args.cli:
        return app.run_cli(speak=args.speak)
    start_minimized = True if args.minimized else (False if args.show else None)
    return app.run_gui(start_minimized)
