"""Baixa o modelo de reconhecimento de fala em português (Vosk, ~31 MB) para a pasta models/.

Uso:  .venv\\Scripts\\python scripts\\download_models.py [--large]
--large baixa o modelo grande (~1,6 GB, mais preciso, exige ~4 GB de RAM).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
SMALL = ("vosk-model-small-pt-0.3", "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip")
LARGE = ("vosk-model-pt-fb-v0.1.1-20220516_2113",
         "https://alphacephei.com/vosk/models/vosk-model-pt-fb-v0.1.1-20220516_2113.zip")


def download(url: str, target: Path, attempts: int = 4) -> None:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as response, open(target, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                while chunk := response.read(1 << 16):
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r  {done * 100 // total:3d}%  ({done >> 20} de {total >> 20} MB)", end="", flush=True)
            print()
            return
        except OSError as exc:
            print(f"\n  Falha no download ({exc}). Tentativa {attempt}/{attempts}.")
            time.sleep(2 ** attempt)
    raise SystemExit("Não foi possível baixar o modelo. Verifique a internet e tente novamente.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--large", action="store_true")
    args = parser.parse_args()
    name, url = LARGE if args.large else SMALL
    MODELS.mkdir(exist_ok=True)
    final = MODELS / name
    if (final / "am").exists() or (final / "conf").exists():
        print(f"Modelo já instalado: {final}")
        return 0
    archive = MODELS / f"{name}.zip"
    print(f"Baixando {name} de {url}")
    download(url, archive)
    print("  SHA-256:", hashlib.sha256(archive.read_bytes()).hexdigest())
    print("Extraindo…")
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(MODELS)
    except zipfile.BadZipFile:
        archive.unlink(missing_ok=True)
        raise SystemExit("Arquivo corrompido. Rode o script de novo.")
    archive.unlink(missing_ok=True)
    if not final.exists():
        extracted = [p for p in MODELS.iterdir() if p.is_dir() and p.name.startswith("vosk-model")]
        if extracted:
            shutil.move(str(extracted[0]), final)
    print(f"Modelo pronto em {final}")
    if args.large:
        print(f"Em Configurações, o modelo usado é definido por stt.vosk_model = {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
