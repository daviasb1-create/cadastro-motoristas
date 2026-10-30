"""Inicia o JARVIS sem janela de console (usado pelo atalho e pela inicialização com o Windows)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis.app import main  # noqa: E402

sys.exit(main())
