"""Gera assets/icon.ico (multi-resolução) a partir do ícone vetorial da interface."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from netvision.ui.main_window import render_icon_pixmap  # noqa: E402

app = QApplication([])
png = ROOT / "assets" / "icon.png"
render_icon_pixmap(256).save(str(png))
Image.open(png).save(ROOT / "assets" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok:", ROOT / "assets" / "icon.ico")
