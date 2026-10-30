"""Gera assets/jarvis.ico e assets/jarvis.png (ícone do atalho e do executável)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv)
from jarvis.ui.tray import make_icon  # noqa: E402

out = ROOT / "assets"
out.mkdir(exist_ok=True)
icon = make_icon(size=256)
pixmap = icon.pixmap(256, 256)
pixmap.save(str(out / "jarvis.png"), "PNG")
if not pixmap.save(str(out / "jarvis.ico"), "ICO"):
    print("Aviso: formato ICO indisponível; usando apenas PNG.")
print("Ícones gerados em", out)
