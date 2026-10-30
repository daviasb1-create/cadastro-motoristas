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
