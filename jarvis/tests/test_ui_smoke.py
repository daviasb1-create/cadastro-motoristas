"""Teste de fumaça da interface (renderização fora da tela)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def test_main_window_and_settings_render(home):
    from jarvis.app import JarvisApp
    from jarvis.ui import theme
    from jarvis.ui.main_window import MainWindow
    from jarvis.ui.settings_dialog import SettingsDialog

    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    qt.setStyleSheet(theme.STYLESHEET)
    app = JarvisApp(enable_voice=False)
    window = MainWindow(app)
    window.show()
    window.handle_event("state", {"state": "listening"})
    window.handle_event("reply", {"text": "Olá", "display": "linha 1"})
    window.handle_event("notification", {"ts": 0, "source": "whatsapp", "app": "WhatsApp", "sender": "Ana",
                                         "title": "Ana", "body": "oi", "content_available": True, "important": True})
    window.handle_event("confirm", {"id": "1", "text": "Confirma?", "details": "x"})
    assert window.confirm_box.isVisible() and window.notes.count() == 1
    qt.processEvents()
    dialog = SettingsDialog(app, window)
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        qt.processEvents()
    dialog._save(close=False)
    assert app.services.settings.get("voice.profile") == "jarvis"
    window.reactor.stop()
    app.shutdown()


def test_fullscreen_default_f11_and_voice(home):
    from jarvis.actions.base import REGISTRY
    from jarvis.app import JarvisApp
    from jarvis.nlu.intents import IntentParser
    from jarvis.ui.main_window import MainWindow

    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app = JarvisApp(enable_voice=False)
    window = MainWindow(app)
    window.present()
    qt.processEvents()
    assert window.isFullScreen()
    window.toggle_fullscreen()  # F11
    qt.processEvents()
    assert not window.isFullScreen() and app.services.settings.get("general.fullscreen") is False
    intent = IntentParser().parse("Jarvis, tela cheia")
    assert intent.name == "ui_fullscreen" and intent.params == {"mode": "on"}
    assert IntentParser().parse("sai da tela cheia").params == {"mode": "off"}
    REGISTRY.run(app.services, intent.name, intent.params)
    window.handle_event("fullscreen", {"mode": "on"})
    qt.processEvents()
    assert window.isFullScreen()
    window.reactor.stop()
    app.shutdown()
