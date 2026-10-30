"""Executa o código da roteirizacao_icaro.html dentro do JARVIS (motor V8, o mesmo do Chrome).

A ferramenta HTML é a fonte da verdade: o JARVIS lê o arquivo, separa o <script> e roda
as mesmas funções (leitura das planilhas com SheetJS, assign, ajustes, exportação do Excel).
Nada da regra de rota é reescrito em Python; quando o HTML for atualizado, basta trocar o arquivo.

O "localStorage" da ferramenta (rota salva do dia, motoristas removidos, telefones) é guardado
num arquivo JSON local, para a rota montada voltar quando o JARVIS abrir de novo.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
from pathlib import Path

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
VENDOR_XLSX = HERE / "vendor" / "xlsx.full.min.js"
VENDOR_JSPDF = HERE / "vendor" / "jspdf.umd.min.js"


class EngineError(Exception):
    pass


def extract_script(html: str) -> str:
    """O maior <script> embutido é o código da ferramenta (o outro é a biblioteca SheetJS)."""
    scripts = [s for s in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I)]
    if not scripts:
        raise EngineError("não encontrei o código da roteirização dentro do HTML")
    code = max(scripts, key=len)
    for needed in ("function assign(", "const DRIVERS=", "function buildMapping(", "function saveDay("):
        if needed not in code:
            raise EngineError(f"o HTML não tem a parte esperada ({needed.strip('(=')}); a ferramenta mudou de formato")
    return code


def input_defaults(html: str) -> tuple[dict[str, str], dict[str, bool]]:
    """Valores padrão dos campos de configuração (<input id=... value=...>) e caixas marcadas."""
    values: dict[str, str] = {}
    checked: dict[str, bool] = {}
    for tag in re.findall(r"<input\b[^>]*>", html, re.I):
        m = re.search(r'\bid="([^"]+)"', tag)
        if not m:
            continue
        v = re.search(r'\bvalue="([^"]*)"', tag)
        values[m.group(1)] = v.group(1) if v else ""
        checked[m.group(1)] = bool(re.search(r"\bchecked\b", tag))
    return values, checked


class RotaJS:
    """Uma instância do motor com a ferramenta carregada. Use sempre de uma thread por vez."""

    def __init__(self, html_path: Path, store_path: Path | None = None) -> None:
        from py_mini_racer import MiniRacer  # instalado com o JARVIS (requirements.txt)

        self.html_path = Path(html_path)
        if not self.html_path.exists():
            raise EngineError(f"arquivo da ferramenta não encontrado: {self.html_path}")
        html = self.html_path.read_text(encoding="utf-8")
        self.store_path = store_path
        self._lock = threading.RLock()
        self.ctx = MiniRacer()
        try:
            self.ctx.eval((HERE / "prelude.js").read_text(encoding="utf-8"))
            if "XLSX" not in html or "xlsx.full.min.js" in html:
                self.ctx.eval(VENDOR_XLSX.read_text(encoding="utf-8"))
            values, checked = input_defaults(html)
            self.ctx.eval(f"__INPUTS={json.dumps(values)};__CHECKED={json.dumps(checked)};"
                          f"__STORE={json.dumps(self._load_store())};")
            self.ctx.eval(extract_script(html))
            self.ctx.eval((HERE / "bridge.js").read_text(encoding="utf-8"))
            self.ctx.eval(VENDOR_JSPDF.read_text(encoding="utf-8"))  # gerador de PDF usado pelo Circuit
        except EngineError:
            self.close()
            raise
        except Exception as exc:  # noqa: BLE001 - erro do JavaScript vira mensagem clara
            self.close()
            raise EngineError(f"o código da ferramenta não rodou no JARVIS: {exc}") from exc

    # ------------------------------------------------------------ util
    def _load_store(self) -> dict:
        if self.store_path and self.store_path.exists():
            try:
                return json.loads(self.store_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("Rota salva ilegível; começando do zero")
        return {}

    def _save_store(self) -> None:
        if not self.store_path:
            return
        data = self.ctx.eval("JSON.stringify(__STORE)")
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(self.store_path)

    def call(self, fn: str, *args, save: bool = False):
        with self._lock:
            payload = ",".join(json.dumps(a, ensure_ascii=False) for a in args)
            try:
                raw = self.ctx.eval(f"JSON.stringify({fn}({payload}))")
            except Exception as exc:  # noqa: BLE001
                raise EngineError(f"falha no código da ferramenta ({fn}): {exc}") from exc
            if save:
                self._save_store()
            return json.loads(raw) if isinstance(raw, str) else None  # função sem retorno

    def logs(self) -> list[str]:
        return json.loads(self.ctx.eval("JSON.stringify(__LOGS.splice(0))"))

    def close(self) -> None:
        try:
            self.ctx.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ uso
    def reset(self) -> None:
        self.call("__jReset")

    def load(self, src: str, files: list[Path]) -> dict:
        payload = [{"name": p.name, "b64": base64.b64encode(p.read_bytes()).decode("ascii")} for p in files]
        return self.call("__jLoad", src, payload)

    def status(self) -> dict:
        return self.call("__jStatus")

    def mapping(self) -> dict:
        return json.loads(self.ctx.eval("JSON.stringify(STATE.mapping)"))

    def assign(self, data_iso: str, fds: bool = False, ausentes: list[str] | None = None) -> dict:
        return self.call("__jAssign", {"data": data_iso, "fds": fds, "ausentes": ausentes or []}, save=True)

    def result(self) -> dict | None:
        return self.call("__jResult")

    def restore_day(self) -> dict | None:
        return self.call("__jRestoreDay")

    def move(self, nf: str, idx: int) -> dict:
        return self.call("__jMove", nf, idx, save=True)

    def remove(self, nf: str) -> dict:
        return self.call("__jRemove", nf, save=True)

    def restore(self, nf: str) -> dict:
        return self.call("__jRestore", nf, save=True)

    def toggle(self, idx: int) -> dict:
        return self.call("__jToggle", idx, save=True)

    def swap(self, a: int, b: int) -> dict:
        return self.call("__jSwap", a, b, save=True)

    def reassign(self, idx: int, regiao: str) -> dict:
        return self.call("__jReassign", idx, regiao, save=True)

    def circuit(self, idx: int | None = None) -> list[tuple[str, str, bytes]]:
        """[(nome do arquivo, motorista, PDF)] para um motorista (idx) ou todos com carga."""
        return [(o["nome"], o["motorista"], base64.b64decode(o["b64"])) for o in self.call("__jCircuit", idx)]

    def excel(self) -> tuple[str, bytes]:
        out = self.call("__jExcel")
        if not out or not out.get("b64"):
            raise EngineError("a exportação do Excel não gerou arquivo")
        return out["nome"], base64.b64decode(out["b64"])
