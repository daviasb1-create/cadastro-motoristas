import json

import httpx

from jarvis.actions.base import REGISTRY
from jarvis.integrations.msgraph.auth import scopes_for
from jarvis.integrations.msgraph.client import GraphClient, GraphError
from jarvis.integrations.msgraph.outlook import Mail, OutlookService


class FakeAuth:
    configured = True

    def __init__(self):
        self.refreshes = 0

    def is_signed_in(self):
        return True

    def get_token(self, force_refresh=False):
        if force_refresh:
            self.refreshes += 1
        return "novo" if force_refresh else "velho"


MSG = {
    "id": "m1", "subject": "Prazo do relatório", "from": {"emailAddress": {"name": "Carlos Lima", "address": "carlos@empresa.com"}},
    "receivedDateTime": "2026-10-29T13:05:00Z", "bodyPreview": "Preciso até amanhã", "isRead": False,
    "importance": "high", "hasAttachments": True, "webLink": "https://outlook/m1", "flag": {"flagStatus": "notFlagged"},
}


def test_scopes_are_minimal():
    assert scopes_for({"mail": True, "send_mail": False, "calendar": False, "excel": False}) == ["Mail.ReadWrite", "User.Read"]


def test_client_refreshes_on_401_and_retries_429(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    auth = FakeAuth()
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        if len(seen) == 1:
            return httpx.Response(401)
        if len(seen) == 2:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"ok": True})

    client = GraphClient(auth, transport=httpx.MockTransport(handler))
    assert client.get("/me") == {"ok": True}
    assert seen[0] == "Bearer velho" and seen[1] == "Bearer novo" and auth.refreshes >= 1


def test_client_network_error_message(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def handler(request):
        raise httpx.ConnectError("offline")

    client = GraphClient(FakeAuth(), transport=httpx.MockTransport(handler))
    try:
        client.get("/me")
    except GraphError as exc:
        assert "internet" in str(exc)
    else:
        raise AssertionError("deveria falhar")


def test_403_is_friendly():
    client = GraphClient(FakeAuth(), transport=httpx.MockTransport(
        lambda r: httpx.Response(403, json={"error": {"code": "Forbidden"}})))
    try:
        client.get("/me/messages")
    except GraphError as exc:
        assert "negou acesso" in str(exc) and exc.status == 403


def make(services, handler):
    client = GraphClient(FakeAuth(), transport=httpx.MockTransport(handler))
    svc = OutlookService(client, FakeAuth(), services.settings, services.storage, services.bus, services.notifications)
    services.outlook = svc
    return svc


def test_unread_and_importance(services):
    def handler(request):
        if request.url.path.endswith("/mailFolders/inbox"):
            return httpx.Response(200, json={"unreadItemCount": 3})
        return httpx.Response(200, json={"value": [MSG]})

    svc = make(services, handler)
    assert svc.is_important(Mail.from_graph(MSG))
    result = REGISTRY.run(services, "email_unread", {})
    assert result.say == "Você tem 3 e-mails não lidos. Os mais recentes são de Carlos."
    assert services.context.get("emails")[0]["id"] == "m1"


def test_draft_reply_needs_confirmation_before_send(services):
    sent = []

    def handler(request):
        path = request.url.path
        if path.endswith("/createReply"):
            body = json.loads(request.content)
            return httpx.Response(201, json={"id": "draft1", "webLink": "https://o/d", "comment": body["comment"]})
        if path.endswith("/send"):
            sent.append(path)
            return httpx.Response(202)
        return httpx.Response(404)

    make(services, handler)
    services.context.remember(email=Mail.from_graph(MSG).__dict__)
    result = REGISTRY.run(services, "email_draft_reply", {"instructions": "Combinado, envio amanhã cedo."})
    assert result.pending is not None and sent == []
    assert "carlos@empresa.com" in result.display and "Combinado" in result.display
    assert result.pending.execute().say == "Resposta enviada."
    assert sent == ["/v1.0/me/messages/draft1/send"]


def test_draft_without_instructions_asks(services):
    make(services, lambda r: httpx.Response(404))
    services.context.remember(email=Mail.from_graph(MSG).__dict__)
    result = REGISTRY.run(services, "email_draft_reply", {})
    assert result.follow_up is not None and "O que devo responder" in result.say


def test_send_disabled_by_setting(services):
    svc = make(services, lambda r: httpx.Response(202))
    services.settings.set("microsoft.features.send_mail", False)
    try:
        svc.send_draft("x")
    except Exception as exc:  # noqa: BLE001
        assert "desativado" in str(exc)
    else:
        raise AssertionError("envio deveria estar bloqueado")


def test_not_configured_message(services):
    class NoAuth(FakeAuth):
        configured = False

    client = GraphClient(NoAuth(), transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    services.outlook = OutlookService(client, NoAuth(), services.settings, services.storage, services.bus)
    result = REGISTRY.run(services, "email_unread", {})
    assert not result.ok and "Configurações > Microsoft 365" in result.say
