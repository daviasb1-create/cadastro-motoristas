"""Inicialização do aplicativo."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys

from netvision import APP_ID, APP_NAME, __version__
from netvision.core import paths


def setup_logging(verbose: bool = False) -> None:
    handler = logging.handlers.RotatingFileHandler(paths.log_path(), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handlers: list[logging.Handler] = [handler]
    if sys.stderr is not None and not paths.is_frozen():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s")
    logging.getLogger("scapy").setLevel(logging.ERROR)


def main(argv: list[str] | None = None) -> int:
    import os
    if sys.stdout is None:  # executável sem console (PyInstaller --windowed)
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    ap = argparse.ArgumentParser(prog=APP_ID)
    ap.add_argument("--minimized", action="store_true", help="abre na bandeja do sistema")
    ap.add_argument("--verbose", action="store_true")
    args, _qt = ap.parse_known_args(argv)
    setup_logging(args.verbose)
    log = logging.getLogger("netvision")
    log.info("%s %s iniciando", APP_NAME, __version__)

    if paths.is_windows():
        import ctypes
        try:  # ícone próprio na barra de tarefas
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass

    from PySide6.QtWidgets import QApplication

    from netvision.core.config import Settings
    from netvision.core.database import Database
    from netvision.engine import Engine
    from netvision.ui.main_window import MainWindow
    from netvision.ui.theme import QSS

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)

    settings = Settings.load()
    db = Database(paths.db_path())
    engine = Engine(settings, db)
    win = MainWindow(engine)
    engine.start()
    if args.minimized or settings.start_minimized:
        win.hide()
    else:
        win.show()
    rc = app.exec()
    db.close()
    return rc
