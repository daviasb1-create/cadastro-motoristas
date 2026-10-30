"""Spotify: tocar músicas, artistas, álbuns e playlists por voz.

Dois níveis:
* Completo (Spotify Premium + app gratuito registrado no Spotify for Developers):
  "toca Back in Black" busca e toca na hora no seu Spotify (PC, celular ou caixa conectada).
* Básico (qualquer conta, sem configurar nada): pausar/continuar/próxima/anterior
  pelas teclas de mídia do Windows, e pedidos de música abrem a busca no app.

Regras atuais do Spotify (fev/2026): o dono do app em modo de desenvolvimento precisa de
Premium, até 5 usuários autorizados, controle de reprodução exige Premium e o retorno do
login deve usar http://127.0.0.1 (não "localhost").
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets as pysecrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import httpx

from ..actions.base import BOOL, INT, STR, ActionResult, ServiceUnavailable, action, props
from ..nlu.normalize import normalize, similar

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
REDIRECT_PORT = 8888
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
REFRESH_SECRET = "spotify_refresh_token"


class PremiumRequired(ServiceUnavailable):
    pass


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(pysecrets.token_bytes(64)).decode().rstrip("=")[:128]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


# --------------------------------------------------------- teclas de mídia
VK_MEDIA = {"next": 0xB0, "previous": 0xB1, "play_pause": 0xB3}


def media_key(name: str) -> bool:
    """Teclas de mídia do Windows: funcionam com Spotify Free, YouTube, players em geral."""
    if sys.platform != "win32":
        return False
    import ctypes

    vk = VK_MEDIA[name]
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 0x0002, 0)
    return True


# ---------------------------------------------------------------- cliente
class SpotifyService:
    def __init__(self, settings, secret_store, bus=None, open_url=None, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.secrets = secret_store
        self.bus = bus
        self.open_url = open_url
        self._http = httpx.Client(timeout=15, transport=transport)
        self._token = ""
        self._expires = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------ estado
    @property
    def client_id(self) -> str:
        return (self.settings.get("spotify.client_id", "") or "").strip()

    def connected(self) -> bool:
        return bool(self.client_id and self.secrets.get(REFRESH_SECRET))

    def _status(self, status: str, detail: str) -> None:
        if self.bus:
            self.bus.publish("connection", service="spotify", status=status, detail=detail)

    def publish_status(self) -> None:
        if self.connected():
            self._status("ok", "Conectado")
        elif self.client_id:
            self._status("off", "Não conectado")
        else:
            self._status("off", "Modo básico (teclas de mídia)")

    # -------------------------------------------------------------- login
    def sign_in(self, timeout: float = 180) -> str:
        """Login oficial no navegador (Authorization Code + PKCE, retorno em 127.0.0.1)."""
        if not self.client_id:
            raise ServiceUnavailable("Informe o Client ID do app Spotify em Configurações > Spotify.")
        verifier, challenge = pkce_pair()
        state = pysecrets.token_urlsafe(16)
        result: dict[str, str] = {}
        done = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if urllib.parse.urlparse(self.path).path == "/callback":
                    result.update({k: v[0] for k, v in query.items()})
                    ok = "code" in result and result.get("state") == state
                    body = ("<h2>JARVIS conectado ao Spotify. Pode fechar esta aba.</h2>" if ok
                            else "<h2>Login não concluído. Volte ao JARVIS e tente de novo.</h2>")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(body.encode("utf-8"))
                    done.set()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):
                pass

        try:
            server = HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
        except OSError as exc:
            raise ServiceUnavailable(f"A porta {REDIRECT_PORT} está ocupada por outro programa.") from exc
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        params = {"client_id": self.client_id, "response_type": "code", "redirect_uri": REDIRECT_URI,
                  "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state}
        self._status("pending", "Aguardando login no navegador")
        self._open(AUTH_URL + "?" + urllib.parse.urlencode(params))
        try:
            if not done.wait(timeout):
                raise ServiceUnavailable("Tempo esgotado aguardando o login do Spotify.")
        finally:
            server.shutdown()
        if result.get("state") != state or "code" not in result:
            self._status("error", "Login recusado")
            raise ServiceUnavailable(f"Login no Spotify não concluído ({result.get('error', 'cancelado')}).")
        self._token_request({"grant_type": "authorization_code", "code": result["code"],
                             "redirect_uri": REDIRECT_URI, "client_id": self.client_id, "code_verifier": verifier})
        self._status("ok", "Conectado")
        return "Spotify conectado."

    def sign_out(self) -> None:
        self.secrets.delete(REFRESH_SECRET)
        self._token, self._expires = "", 0.0
        self.publish_status()

    def _token_request(self, data: dict) -> None:
        try:
            response = self._http.post(TOKEN_URL, data=data)
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("Sem conexão com o Spotify.") from exc
        if response.status_code != 200:
            if data.get("grant_type") == "refresh_token":
                self.secrets.delete(REFRESH_SECRET)
                self._status("error", "Reconecte o Spotify")
                raise ServiceUnavailable("A conexão com o Spotify expirou. Reconecte em Configurações > Spotify.")
            raise ServiceUnavailable(f"O Spotify recusou o login ({response.status_code}).")
        payload = response.json()
        self._token = payload["access_token"]
        self._expires = time.time() + int(payload.get("expires_in", 3600)) - 60
        if payload.get("refresh_token"):  # o Spotify pode trocar o refresh token a cada renovação
            self.secrets.set(REFRESH_SECRET, payload["refresh_token"])

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires:
                return self._token
            refresh = self.secrets.get(REFRESH_SECRET)
            if not (self.client_id and refresh):
                raise ServiceUnavailable("Spotify não conectado.")
            self._token_request({"grant_type": "refresh_token", "refresh_token": refresh, "client_id": self.client_id})
            return self._token

    # ---------------------------------------------------------------- API
    def api(self, method: str, path: str, params: dict | None = None, json: Any = None) -> Any:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            response = self._http.request(method, API + path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("Sem conexão com o Spotify.") from exc
        if response.status_code == 401:
            self._token = ""
            headers = {"Authorization": f"Bearer {self._access_token()}"}
            response = self._http.request(method, API + path, params=params, json=json, headers=headers)
        if response.status_code == 403:
            reason = ""
            try:
                reason = response.json().get("error", {}).get("reason", "")
            except ValueError:
                pass
            if reason == "PREMIUM_REQUIRED" or "premium" in response.text.lower():
                raise PremiumRequired("Controlar a reprodução pelo Spotify exige conta Premium.")
            raise ServiceUnavailable("O Spotify negou esse pedido.")
        if response.status_code == 404 and "NO_ACTIVE_DEVICE" in response.text:
            raise ServiceUnavailable("NO_ACTIVE_DEVICE")
        if response.status_code == 429:
            raise ServiceUnavailable("O Spotify pediu para aguardar um pouco.")
        if response.status_code >= 400:
            raise ServiceUnavailable(f"O Spotify retornou erro {response.status_code}.")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def search(self, query: str, kind: str = "track") -> dict | None:
        data = self.api("GET", "/search", params={"q": query, "type": kind, "limit": 5}) or {}
        items = [i for i in (data.get(f"{kind}s") or {}).get("items", []) if i]
        if not items:
            return None
        if kind == "track":
            # prefere o resultado cujo nome mais se parece com o pedido
            target = normalize(query)
            items.sort(key=lambda i: similar(target, normalize(i["name"] + " " + " ".join(
                a["name"] for a in i.get("artists", [])))), reverse=True)
        return items[0]

    def devices(self) -> list[dict]:
        return (self.api("GET", "/me/player/devices") or {}).get("devices", [])

    def ensure_device(self) -> str | None:
        """Devolve um dispositivo ativo; se nenhum, abre o Spotify do PC e espera ele aparecer."""
        devices = self.devices()
        active = next((d for d in devices if d.get("is_active")), None)
        if active:
            return active["id"]
        if not devices:
            self._open("spotify:")
            for _ in range(16):
                time.sleep(0.5)
                devices = self.devices()
                if devices:
                    break
        if not devices:
            return None
        preferred = next((d for d in devices if d.get("type") == "Computer"), devices[0])
        return preferred["id"]

    def play(self, uri: str | None = None, context: bool = False) -> None:
        device = self.ensure_device()
        if device is None:
            raise ServiceUnavailable("Não encontrei nenhum Spotify aberto. Abra o app do Spotify e tente de novo.")
        body = None
        if uri:
            body = {"context_uri": uri} if context else {"uris": [uri]}
        self.api("PUT", "/me/player/play", params={"device_id": device}, json=body)

    def _open(self, url: str) -> None:
        if self.open_url:
            self.open_url(url)
        else:
            import webbrowser

            webbrowser.open(url)


# ===================================================================== ações
def _svc(services) -> SpotifyService:
    svc = services.extras.get("spotify")
    if svc is None:
        raise ServiceUnavailable("Integração com o Spotify indisponível.")
    return svc


def _describe(item: dict, kind: str) -> str:
    if kind == "track":
        artists = ", ".join(a["name"] for a in item.get("artists", [])[:2])
        return f"{item['name']}, de {artists}" if artists else item["name"]
    if kind == "album":
        artists = ", ".join(a["name"] for a in item.get("artists", [])[:1])
        return f"o álbum {item['name']}" + (f", de {artists}" if artists else "")
    if kind == "playlist":
        return f"a playlist {item['name']}"
    return f"músicas de {item['name']}"


@action("spotify_play", "Toca no Spotify uma música, artista, álbum ou playlist pelo nome.",
        props(["query"], query=STR, kind=STR | {"enum": ["track", "artist", "album", "playlist"]}))
def spotify_play(services, params):
    svc = _svc(services)
    query = (params.get("query") or "").strip()
    kind = params.get("kind") or "track"
    if not query:
        return spotify_resume(services, {})
    if not svc.connected():
        svc._open("spotify:search:" + urllib.parse.quote(query))
        return ActionResult(f"Abri a busca por {query} no Spotify. Para eu tocar direto, conecte o Spotify Premium "
                            "em Configurações.")
    try:
        item = svc.search(query, kind)
        if item is None:
            return ActionResult.fail(f"Não encontrei {query} no Spotify.")
        if kind == "track":
            # "toca Coldplay": o pedido é o nome do artista, não de uma faixa -> toca o artista
            artist = (item.get("artists") or [{}])[0]
            target = normalize(query)
            if artist.get("uri") and similar(target, normalize(artist.get("name", ""))) >= 0.9 and \
                    similar(target, normalize(item["name"])) < 0.6:
                item, kind = artist, "artist"
        svc.play(item["uri"], context=kind != "track")
    except PremiumRequired:
        svc._open("spotify:search:" + urllib.parse.quote(query))
        return ActionResult("Sua conta precisa do Premium para eu tocar direto. Abri a busca no Spotify.")
    services.context.remember(spotify=item.get("name", query))
    services.activity(f"Spotify: {item.get('name', query)}", kind="music")
    return ActionResult(f"Tocando {_describe(item, kind)}.")


def _player_command(services, method: str, path: str, key: str, ok_text: str, params: dict | None = None):
    svc = _svc(services)
    if svc.connected():
        try:
            svc.api(method, path, params=params)
            return ActionResult(ok_text)
        except PremiumRequired:
            pass
        except ServiceUnavailable as exc:
            if "NO_ACTIVE_DEVICE" not in str(exc):
                return ActionResult.fail(str(exc))
    if key and media_key(key):
        return ActionResult(ok_text)
    return ActionResult.fail("Não consegui controlar a reprodução.")


@action("spotify_pause", "Pausa a música (Spotify ou outro player).")
def spotify_pause(services, params):
    return _player_command(services, "PUT", "/me/player/pause", "play_pause", "Pausado.")


@action("spotify_resume", "Continua a música pausada.")
def spotify_resume(services, params):
    return _player_command(services, "PUT", "/me/player/play", "play_pause", "Continuando.")


@action("spotify_next", "Pula para a próxima música.")
def spotify_next(services, params):
    return _player_command(services, "POST", "/me/player/next", "next", "Próxima.")


@action("spotify_previous", "Volta para a música anterior.")
def spotify_previous(services, params):
    return _player_command(services, "POST", "/me/player/previous", "previous", "Voltando.")


@action("spotify_volume", "Ajusta o volume do Spotify (0 a 100) ou muda em pontos (delta).",
        props(level=INT, delta=INT))
def spotify_volume(services, params):
    svc = _svc(services)
    if not svc.connected():
        return ActionResult.fail("Para ajustar o volume do Spotify, conecte-o em Configurações. Posso ajustar o volume do Windows.")
    level = params.get("level")
    if level is None:
        current = (svc.api("GET", "/me/player") or {}).get("device", {}).get("volume_percent", 50)
        level = current + int(params.get("delta", 10))
    level = max(0, min(100, int(level)))
    try:
        svc.api("PUT", "/me/player/volume", params={"volume_percent": level})
    except PremiumRequired as exc:
        return ActionResult.fail(str(exc))
    return ActionResult(f"Spotify em {level} por cento.")


@action("spotify_shuffle", "Liga ou desliga o modo aleatório do Spotify.", props(["active"], active=BOOL))
def spotify_shuffle(services, params):
    active = bool(params.get("active", True))
    return _player_command(services, "PUT", "/me/player/shuffle", "", "Aleatório ligado." if active else "Aleatório desligado.",
                           {"state": "true" if active else "false"})


@action("spotify_now_playing", "Diz qual música está tocando no Spotify.")
def spotify_now_playing(services, params):
    svc = _svc(services)
    if not svc.connected():
        return ActionResult.fail("Para eu saber o que está tocando, conecte o Spotify em Configurações.")
    data = svc.api("GET", "/me/player/currently-playing")
    item = (data or {}).get("item")
    if not item:
        return ActionResult("Nada tocando no Spotify agora.")
    return ActionResult(f"Está tocando {_describe(item, 'track')}.")
