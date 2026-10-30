"""Teste real da voz Fish Audio configurada (usa a chave do .env e gasta poucos créditos).

Uso:  .venv\Scripts\python scripts\test_fish_voice.py
Confere: chave no .env, ID da voz, modelo, streaming. Salva o resultado em fish_teste.wav e toca.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.audio.fish_check import check_fish_voice  # noqa: E402
from jarvis.core.config import Settings  # noqa: E402
from jarvis.core.envfile import load_env  # noqa: E402


def main() -> int:
    files = load_env()
    print("Arquivos .env lidos:", ", ".join(str(f) for f in files) or "nenhum")
    settings = Settings()
    report = check_fish_voice(settings, profile="jarvis")
    print(report.text())
    if not report.ok:
        print("\nTESTE FALHOU. Veja docs/INTEGRACOES.md, seção Fish Audio.")
        return 1
    out = ROOT / "fish_teste.wav"
    out.write_bytes(report.clip.to_wav())
    print(f"\nÁudio salvo em {out}")
    try:
        from jarvis.audio.player import Player

        Player(settings).play(report.clip)
    except Exception as exc:  # noqa: BLE001
        print(f"(não foi possível tocar aqui: {exc})")
    print("TESTE OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
