import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JARVIS_HOME", tempfile.mkdtemp(prefix="jarvis_test_"))


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    return tmp_path


class MemorySecrets:
    def __init__(self):
        self.data = {}

    def get(self, name):
        return self.data.get(name)

    def set(self, name, value):
        self.data[name] = value

    def delete(self, name):
        self.data.pop(name, None)

    def has(self, name):
        return bool(self.data.get(name))

    backend_name = "memória (teste)"


@pytest.fixture
def services(home):
    import jarvis.actions  # noqa: F401 - registra as ações
    from jarvis.actions.reminders import ReminderService
    from jarvis.brain.services import Services
    from jarvis.core.config import Settings
    from jarvis.core.events import EventBus
    from jarvis.core.storage import Storage
    from jarvis.notifications.center import NotificationCenter

    settings = Settings(home / "settings.json")
    storage = Storage(home / "jarvis.db")
    bus = EventBus()
    svc = Services(settings=settings, storage=storage, bus=bus, secrets=MemorySecrets())
    svc.reminders = ReminderService(storage, bus)
    svc.notifications = NotificationCenter(settings, storage, bus, svc.state)
    svc.opened = []
    svc.open_url = svc.opened.append
    yield svc
    storage.close()
