"""Diário de alterações: backup de valores originais e reversão de TUDO que o app modifica.

Cada otimização pertence a um *grupo* (ex.: "tweak:game_mode", "session:turbo").
- Valores de registro: o valor ORIGINAL é guardado uma única vez, com a lista de grupos
  que dependem da alteração. Só é restaurado quando nenhum grupo ativo precisa mais dele.
- Ações (serviços, plano de energia, DNS, comandos): guardam o comando de reversão.
O arquivo é salvo a cada alteração (escrita atômica), sobrevivendo a falhas e reinícios.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time

from ..config import BACKUP_DIR, JOURNAL_FILE
from ..utils import log, powershell, run
from . import registry as reg


ALLOWED_CMDS = {"fsutil", "fsutil.exe", "sc.exe", "powercfg", "powercfg.exe"}
ALLOWED_PS = ("Set-DnsClientServerAddress ",)


def _key(hive, path, name) -> str:
    return f"{hive}\\{path}\\\\{name}".lower()


class Journal:
    def __init__(self, path=JOURNAL_FILE):
        self.path = path
        self._lock = threading.RLock()
        self.data = {"version": 1, "created": time.time(), "originals": {}, "groups": {}}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:  # arquivo corrompido: preserva cópia e recomeça
                log.error("Journal corrompido (%s); criando novo", e)
                shutil.copy(path, str(path) + f".corrompido.{int(time.time())}")

    # ------------------------------------------------------------ persistência
    def save(self):
        with self._lock:
            tmp = str(self.path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)

    def export_copy(self) -> str:
        dst = BACKUP_DIR / f"backup_{time.strftime('%Y%m%d_%H%M%S')}.json"
        self.save()
        shutil.copy(self.path, dst)
        return str(dst)

    # ------------------------------------------------------------ grupos
    def group(self, gid: str, title: str = "", category: str = "geral") -> dict:
        with self._lock:
            g = self.data["groups"].get(gid)
            if g is None:
                g = {"title": title or gid, "category": category, "time": time.time(),
                     "reg": [], "actions": [], "meta": {}}
                self.data["groups"][gid] = g
            elif title and g["title"] == gid:
                g["title"], g["category"] = title, category
            return g

    def has_group(self, gid: str) -> bool:
        g = self.data["groups"].get(gid)
        return bool(g and (g["reg"] or g["actions"] or g["meta"].get("keep")))

    def groups(self, prefix: str = "") -> dict:
        return {k: v for k, v in self.data["groups"].items() if k.startswith(prefix)}

    def set_meta(self, gid: str, key: str, value):
        with self._lock:
            self.group(gid)["meta"][key] = value
            self.save()

    # ------------------------------------------------------------ registro
    def _snapshot(self, gid, hive, path, name):
        k = _key(hive, path, name)
        orig = self.data["originals"].get(k)
        if orig is None:
            existed, typ, value = reg.read_value(hive, path, name)
            orig = {"hive": hive, "path": path, "name": name, "existed": existed,
                    "type": typ, "value": reg.encode(typ, value), "owners": []}
            self.data["originals"][k] = orig
        if gid not in orig["owners"]:
            orig["owners"].append(gid)
        g = self.group(gid)
        if k not in g["reg"]:
            g["reg"].append(k)

    def reg_set(self, gid, hive, path, name, typ, value):
        with self._lock:
            self._snapshot(gid, hive, path, name)
            self.save()  # salva o backup ANTES de escrever
            reg.write_value(hive, path, name, typ, value)
            log.info("REG SET %s\\%s [%s] = %r (%s)", hive, path, name, value, gid)

    def reg_delete(self, gid, hive, path, name):
        with self._lock:
            self._snapshot(gid, hive, path, name)
            self.save()
            reg.delete_value(hive, path, name)

    # ------------------------------------------------------------ ações
    def add_action(self, gid: str, action: dict):
        with self._lock:
            self.group(gid)["actions"].append(action)
            self.save()
        log.info("AÇÃO registrada [%s] %s", gid, action.get("desc") or action.get("kind"))

    # ------------------------------------------------------------ reversão
    def revert_group(self, gid: str) -> list[str]:
        errors: list[str] = []
        with self._lock:
            g = self.data["groups"].get(gid)
            if not g:
                return errors
            for action in reversed(g["actions"]):
                try:
                    self._revert_action(action)
                except Exception as e:
                    errors.append(f"{action.get('desc', action.get('kind'))}: {e}")
            for k in reversed(g["reg"]):
                orig = self.data["originals"].get(k)
                if not orig:
                    continue
                if gid in orig["owners"]:
                    orig["owners"].remove(gid)
                if orig["owners"]:
                    continue  # outro grupo ainda depende desta alteração
                try:
                    if orig["existed"]:
                        reg.write_value(orig["hive"], orig["path"], orig["name"], orig["type"],
                                        reg.decode(orig["type"], orig["value"]))
                    else:
                        reg.delete_value(orig["hive"], orig["path"], orig["name"])
                    del self.data["originals"][k]
                except PermissionError:
                    orig["owners"].append(gid)
                    errors.append(f"Sem permissão para restaurar {orig['hive']}\\{orig['path']}\\{orig['name']}")
                except Exception as e:
                    orig["owners"].append(gid)
                    errors.append(f"{orig['name']}: {e}")
            if not errors:
                del self.data["groups"][gid]
            self.save()
        log.info("REVERT %s erros=%s", gid, errors)
        return errors

    def revert_all(self, prefix: str = "") -> list[str]:
        errors = []
        gids = sorted(self.groups(prefix), key=lambda g: self.data["groups"][g]["time"], reverse=True)
        for gid in gids:
            errors += self.revert_group(gid)
        return errors

    def _revert_action(self, a: dict):
        kind = a["kind"]
        # O diário fica na pasta do usuário: só executa comandos de reversão conhecidos, para que um arquivo
        # adulterado não consiga rodar comandos arbitrários quando o app estiver como administrador.
        if kind == "cmd" and (not a.get("cmd") or str(a["cmd"][0]).lower() not in ALLOWED_CMDS):
            raise ValueError(f"comando de reversão não permitido: {a.get('cmd')}")
        if kind == "ps" and not any(a.get("script", "").startswith(p) for p in ALLOWED_PS):
            raise ValueError("script de reversão não permitido")
        if kind == "cmd":
            r = run(a["cmd"])
            if r.returncode not in (0, *a.get("ok_codes", [])):
                raise RuntimeError(r.stderr.strip() or r.stdout.strip() or f"código {r.returncode}")
        elif kind == "ps":
            r = powershell(a["script"])
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip()[:200])
        elif kind == "service_start":
            r = run(["sc.exe", "config", a["name"], "start=", a["start"]])
            if r.returncode != 0:
                raise RuntimeError(r.stdout.strip()[:200])
        elif kind == "service_running":
            run(["sc.exe", "start", a["name"]])  # se já estiver rodando, ignora
        elif kind == "power":
            if a.get("previous"):
                run(["powercfg", "/setactive", a["previous"]])
            if a.get("created"):
                run(["powercfg", "/delete", a["created"]])
        elif kind == "relaunch":
            exe = a.get("exe")
            if exe and os.path.isfile(exe) and exe.lower().endswith(".exe"):
                from .winapi import is_admin
                if is_admin():
                    # reabre pelo Explorer para o app NÃO herdar privilégios de administrador
                    subprocess.Popen(["explorer.exe", exe], close_fds=True)
                else:
                    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                    subprocess.Popen(a.get("cmdline") or [exe], close_fds=True, creationflags=flags,
                                     cwd=os.path.dirname(exe))
        elif kind in ("appx", "feature", "capability", "task"):
            from . import system_mods
            system_mods.revert_action(a)
        elif kind == "file":
            target, backup = a["path"], a.get("backup")
            if not target.lower().endswith(".cfg"):
                raise ValueError("arquivo de reversão não permitido")
            if backup and os.path.exists(backup) and os.path.dirname(os.path.abspath(backup)) == \
                    os.path.abspath(str(BACKUP_DIR)):
                shutil.copy2(backup, target)
            elif not backup and os.path.exists(target):
                os.remove(target)
        else:
            raise ValueError(f"tipo desconhecido {kind}")

    # ------------------------------------------------------------ resumo
    def describe(self) -> list[dict]:
        out = []
        for gid, g in sorted(self.data["groups"].items(), key=lambda kv: kv[1]["time"]):
            out.append({"id": gid, "title": g["title"], "category": g["category"], "time": g["time"],
                        "reg": len(g["reg"]), "actions": len(g["actions"])})
        return out


journal = Journal()
