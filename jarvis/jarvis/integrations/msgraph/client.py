"""Cliente HTTP do Microsoft Graph com tratamento de erros, limites e quedas de internet."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ...actions.base import ServiceUnavailable
from .auth import AuthError

log = logging.getLogger(__name__)
GRAPH = "https://graph.microsoft.com/v1.0"


class GraphError(ServiceUnavailable):
    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class GraphClient:
    def __init__(self, auth, transport: httpx.BaseTransport | None = None, timeout: float = 20.0) -> None:
        self.auth = auth
        self._http = httpx.Client(base_url=GRAPH, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                headers: dict | None = None, retries: int = 3) -> Any:
        refreshed = False
        attempt = 0
        while True:
            attempt += 1
            try:
                token = self.auth.get_token(force_refresh=refreshed)
            except AuthError as exc:
                raise GraphError(str(exc), 401, "auth") from exc
            all_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
            try:
                response = self._http.request(method, path, params=params, json=json, headers=all_headers)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
                if attempt < retries:
                    time.sleep(1.5 * attempt)
                    continue
                raise GraphError("Sem conexão com a Microsoft no momento. Verifique a internet.", 0, "network") from exc
            if response.status_code == 401 and not refreshed:
                refreshed = True
                continue
            if response.status_code in (429, 503, 504) and attempt < retries:
                wait = float(response.headers.get("Retry-After", 2 * attempt))
                time.sleep(min(wait, 15))
                continue
            if response.status_code >= 400:
                raise _error_from(response)
            if response.status_code == 204 or not response.content:
                return None
            if "json" in response.headers.get("content-type", ""):
                return response.json()
            return response.content

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, json: Any = None, **kw) -> Any:
        return self.request("POST", path, json=json, **kw)

    def patch(self, path: str, json: Any = None, **kw) -> Any:
        return self.request("PATCH", path, json=json, **kw)

    def get_all(self, path: str, params: dict | None = None, limit: int = 200, **kw) -> list:
        """Segue @odata.nextLink até ``limit`` itens."""
        items: list = []
        data = self.get(path, params=params, **kw)
        while data:
            items += data.get("value", [])
            next_link = data.get("@odata.nextLink")
            if not next_link or len(items) >= limit:
                break
            data = self.get(next_link.replace(GRAPH, ""), **kw)
        return items[:limit]


def _error_from(response: httpx.Response) -> GraphError:
    try:
        body = response.json().get("error", {})
    except ValueError:
        body = {}
    code = body.get("code", "")
    message = body.get("message", "")
    status = response.status_code
    log.warning("Graph %s %s: %s %s", response.request.method, response.request.url.path, status, code)
    if status == 403:
        return GraphError("A Microsoft negou acesso a esse recurso. Pode faltar permissão ou licença da sua conta.", status, code)
    if status == 404:
        return GraphError("Não encontrei esse item na sua conta Microsoft.", status, code)
    if status == 429:
        return GraphError("A Microsoft pediu para aguardar um pouco antes de novas consultas.", status, code)
    if code in ("MailboxNotEnabledForRESTAPI", "MailboxNotHostedInExchangeOnline"):
        return GraphError("Sua caixa de e-mail não está disponível para a API do Microsoft Graph.", status, code)
    return GraphError(f"Erro do Microsoft Graph ({status}): {message[:150]}", status, code)
