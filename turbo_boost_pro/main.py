"""TURBO BOOST PRO - ponto de entrada."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _check_platform():
    if sys.platform != "win32" and "--dev" not in sys.argv:
        print("TURBO BOOST PRO foi feito para Windows 10/11. Use --dev para abrir a interface em modo de "
              "desenvolvimento (as otimizações ficam inativas).")
        sys.exit(1)


def _selftest() -> int:
    """Importa todos os módulos e páginas (usado pelo build para validar o .exe). Sai sem abrir janela."""
    import importlib
    import traceback
    mods = ["tbp.core." + m for m in ("engine", "ultralite", "system_mods", "services", "snapshot", "diagnostics",
                                      "cleaner", "network", "storage", "gaming", "winver", "monitor", "bench", "analysis2",
                                      "stage2")]
    mods += ["tbp.ui.app"] + ["tbp.ui.pages." + p for p in ("dashboard", "gaming", "cleaner", "performance",
                                                             "advanced", "ultralite", "competitive", "diagnostics",
                                                             "security")]
    out = []
    code = 0
    for m in mods:
        try:
            importlib.import_module(m)
            out.append(f"OK {m}")
        except Exception:
            code = 1
            out.append(f"FALHA {m}\n{traceback.format_exc()}")
    from tbp.core import bench
    out.append(f"PresentMon: {bench.presentmon_path() or 'NAO ENCONTRADO'}")
    from tbp.config import DATA_DIR
    (DATA_DIR / "selftest.txt").write_text("\n".join(out), encoding="utf-8")
    return code


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    _check_platform()
    from tbp.ui.app import main
    main()
