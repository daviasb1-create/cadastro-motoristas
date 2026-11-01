"""TURBO BOOST PRO - ponto de entrada."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _check_platform():
    if sys.platform != "win32" and "--dev" not in sys.argv:
        print("TURBO BOOST PRO foi feito para Windows 10/11. Use --dev para abrir a interface em modo de "
              "desenvolvimento (as otimizações ficam inativas).")
        sys.exit(1)


if __name__ == "__main__":
    _check_platform()
    from tbp.ui.app import main
    main()
