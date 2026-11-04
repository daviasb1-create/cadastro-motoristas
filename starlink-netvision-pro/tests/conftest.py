import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("NETVISION_DATA_DIR", tempfile.mkdtemp(prefix="netvision-test-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

SERVER = Path(__file__).with_name("fake_starlink_server.py")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def fake_dish():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(SERVER), str(port)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "READY"
    yield f"127.0.0.1:{port}"
    proc.terminate()
    proc.wait(5)


@pytest.fixture(scope="module")
def fake_router_no_wifi():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(SERVER), str(port), "--no-wifi"], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "READY"
    yield f"127.0.0.1:{port}"
    proc.terminate()
    proc.wait(5)
