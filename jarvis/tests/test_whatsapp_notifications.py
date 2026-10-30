import sqlite3
import time
from datetime import datetime

from jarvis.actions.base import REGISTRY
from jarvis.integrations.whatsapp import WhatsAppService, parse_whatsapp
from jarvis.integrations.winnotify import NotificationDbReader, WinNotification, parse_payload

WA = "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"


def toast(*texts, attribution=""):
    body = "".join(f"<text>{t}</text>" for t in texts)
    if attribution:
        body += f'<text placement="attribution">{attribution}</text>'
    return f'<toast launch="x"><visual><binding template="ToastGeneric">{body}</binding></visual></toast>'.encode()


def make_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE NotificationHandler (RecordId INTEGER PRIMARY KEY, PrimaryId TEXT);
        CREATE TABLE Notification (Id INTEGER PRIMARY KEY, HandlerId INTEGER, Type TEXT, Payload BLOB, ArrivalTime INTEGER);
    """)
    conn.execute("INSERT INTO NotificationHandler VALUES (1, ?)", (WA,))
    conn.execute("INSERT INTO NotificationHandler VALUES (2, 'Microsoft.Teams')")
    conn.commit()
    return conn


def filetime(dt: datetime) -> int:
    return int((dt.timestamp() + 11644473600) * 10_000_000)


def test_parse_payload_and_group_format():
    texts, attribution, launch = parse_payload(toast("Equipe Rota", "Bruno: Saí agora", attribution="web.whatsapp.com"))
    assert texts == ["Equipe Rota", "Bruno: Saí agora"] and attribution == "web.whatsapp.com"
    info = parse_whatsapp(WinNotification(1, WA, datetime.now(), texts))
    assert info == {"sender": "Bruno", "group": "Equipe Rota", "body": "Saí agora", "content_available": True}
    hidden = parse_whatsapp(WinNotification(2, WA, datetime.now(), ["Ana", "Nova mensagem"]))
    assert hidden["sender"] == "Ana" and not hidden["content_available"]


def test_reader_and_service_end_to_end(services, tmp_path):
    db = tmp_path / "wpndatabase.db"
    conn = make_db(db)
    conn.execute("INSERT INTO Notification VALUES (1, 1, 'toast', ?, ?)", (toast("Antiga", "msg antiga"), filetime(datetime.now())))
    conn.commit()
    svc = WhatsAppService(services.settings, services.storage, services.bus, services.notifications, services.open_url)
    svc.reader = NotificationDbReader(db)
    svc.reader.prime()  # o passado não é anunciado
    svc.status = "ok"
    services.whatsapp = svc
    now = filetime(datetime.now())
    conn.execute("INSERT INTO Notification VALUES (2, 1, 'toast', ?, ?)", (toast("Ana", "Chego às 5"), now))
    conn.execute("INSERT INTO Notification VALUES (3, 1, 'toast', ?, ?)", (toast("João", "Nova mensagem"), now))
    conn.execute("INSERT INTO Notification VALUES (4, 2, 'toast', ?, ?)", (toast("Teams", "Reunião"), now))
    conn.commit()
    assert svc.poll_once() == 2
    assert svc.poll_once() == 0  # não repete
    result = REGISTRY.run(services, "whatsapp_unread", {})
    assert result.say == "2 mensagens novas no WhatsApp, de João e Ana."
    summary = REGISTRY.run(services, "whatsapp_summary", {})
    assert "Ana disse: Chego às 5" in summary.say and "sem prévia" in summary.say
    assert REGISTRY.run(services, "whatsapp_unread", {}).say == "Nenhuma mensagem nova no WhatsApp."


def test_compose_never_sends_without_confirmation(services):
    svc = WhatsAppService(services.settings, services.storage, services.bus, services.notifications, services.open_url)
    services.whatsapp = svc
    services.settings.set("whatsapp.prefer_app", False)
    services.settings.set("whatsapp.contacts", {"Ana Souza": "+55 (21) 99999-8888"})
    result = REGISTRY.run(services, "whatsapp_compose", {"contact": "ana", "text": "Chego às 5"})
    assert result.pending and services.opened == []
    assert "+5521999998888" in result.display
    result.pending.execute()
    assert services.opened == ["https://wa.me/5521999998888?text=Chego%20%C3%A0s%205"]


def test_reading_unavailable_is_reported(services):
    svc = WhatsAppService(services.settings, services.storage, services.bus, services.notifications)
    svc.status = "error"
    services.whatsapp = svc
    result = REGISTRY.run(services, "whatsapp_unread", {})
    assert not result.ok and "Não consigo ler" in result.say


def test_notification_dedupe_and_rules(services):
    center = services.notifications
    assert center.add(source="whatsapp", sender="Ana", body="oi", key="a") is not None
    assert center.add(source="whatsapp", sender="Ana", body="oi", key="b") is None  # mesmo texto
    assert center.add(source="whatsapp", sender="Ana", body="oi de novo", key="a") is None  # mesma chave
    services.settings.set("notifications.important_keywords", ["urgente"])
    item = center.add(source="outlook", sender="Chefe", title="URGENTE: contrato", key="c")
    assert item["important"]
    services.settings.set("notifications.sources.excel", False)
    assert center.add(source="excel", sender="x", body="y") is None


def test_should_speak_respects_modes(services):
    center = services.notifications
    assert center.should_speak(False)
    services.state.game_mode = True
    assert not center.should_speak(False) and center.should_speak(True)
    services.state.game_mode = False
    services.settings.set("notifications.muted_until", time.time() + 600)
    assert not center.should_speak(True)
    services.settings.set("notifications.muted_until", None)
    services.settings.set("notifications.quiet_hours", {"enabled": True, "start": "22:00", "end": "07:00"})
    night = datetime(2026, 10, 29, 23, 30).timestamp()
    assert not center.should_speak(False, night) and center.should_speak(True, night)


def test_summary_uses_only_available_content(services):
    center = services.notifications
    start = time.time() - 5
    center.add(source="whatsapp", sender="Ana", body="Chego às 5", key="1")
    center.add(source="whatsapp", sender="João", body="", content_available=False, key="2")
    center.add(source="whatsapp", sender="Bia", body="Ok", key="3")
    center.add(source="outlook", sender="Carlos", title="Relatório", key="4", important=True)
    center.add(source="outlook", sender="RH", title="Ponto", key="5")
    result = center.summary(start)
    assert result.say.startswith("Você recebeu 3 mensagens no WhatsApp e 2 e-mails no Outlook.")
    assert "1 item marcado como importante, o primeiro de Carlos" in result.say
    assert "Em 1 mensagem, o conteúdo não estava disponível" in result.say


def test_batched_announcement_text(services):
    center = services.notifications
    items = [{"source": "whatsapp", "sender": "Ana", "important": False, "title": "", "body": "x"},
             {"source": "whatsapp", "sender": "Bia", "important": False, "title": "", "body": "y"},
             {"source": "outlook", "sender": "Carlos", "important": False, "title": "Relatório", "body": ""}]
    assert center.compose_announcement(items) == "Chegaram 2 mensagens no WhatsApp de Ana, Bia e 1 e-mail de Carlos."
    assert center.compose_announcement(items[2:]) == "Novo e-mail de Carlos: Relatório."
