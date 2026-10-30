"""Autenticação Microsoft (MSAL) com cache de tokens criptografado.

* Fluxo oficial OAuth 2.0 com PKCE no navegador do sistema (ou código de
  dispositivo como alternativa). O JARVIS nunca vê a sua senha.
* Tokens ficam em arquivo protegido pela DPAPI do Windows (msal-extensions),
  legível apenas pela sua conta de usuário.
* Escopos mínimos por funcionalidade habilitada.
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import Callable

from ...core import paths

log = logging.getLogger(__name__)

AUTHORITY = "https://login.microsoftonline.com/{tenant}"

FEATURE_SCOPES = {
    "base": ["User.Read"],
    "mail": ["Mail.ReadWrite"],  # leitura + criação de rascunhos (não envia)
    "send_mail": ["Mail.Send"],
    "calendar": ["Calendars.Read"],
    "excel": ["Files.ReadWrite.All"],  # planilhas próprias e compartilhadas com você
}


class AuthError(Exception):
    pass


def scopes_for(features: dict) -> list[str]:
    scopes = list(FEATURE_SCOPES["base"])
    for feature, enabled in features.items():
        if enabled and feature in FEATURE_SCOPES:
            scopes += FEATURE_SCOPES[feature]
    return sorted(set(scopes))


def _build_cache():
    """Cache persistente criptografado; em memória quando não há proteção disponível."""
    import msal

    try:
        from msal_extensions import PersistedTokenCache, build_encrypted_persistence

        if sys.platform == "win32":
            return PersistedTokenCache(build_encrypted_persistence(str(paths.token_cache_path())))
    except Exception:  # noqa: BLE001
        log.warning("Cache criptografado indisponível; tokens ficarão só em memória.", exc_info=True)
    return msal.SerializableTokenCache()


class GraphAuth:
    def __init__(self, settings, bus=None) -> None:
        self.settings = settings
        self.bus = bus
        self._app = None
        self._lock = threading.RLock()
        self._client_id = ""

    # ---------------------------------------------------------------- setup
    @property
    def configured(self) -> bool:
        return bool(self.settings.get("microsoft.client_id"))

    @property
    def scopes(self) -> list[str]:
        return scopes_for(self.settings.get("microsoft.features", {}) or {})

    def _application(self):
        import msal

        client_id = self.settings.get("microsoft.client_id", "")
        if not client_id:
            raise AuthError("Microsoft 365 não configurado: informe o ID do aplicativo em Configurações > Microsoft 365.")
        with self._lock:
            if self._app is None or client_id != self._client_id:
                tenant = self.settings.get("microsoft.tenant", "common") or "common"
                self._app = msal.PublicClientApplication(
                    client_id, authority=AUTHORITY.format(tenant=tenant), token_cache=_build_cache())
                self._client_id = client_id
            return self._app

    def _status(self, status: str, detail: str = "") -> None:
        if self.bus:
            self.bus.publish("connection", service="microsoft", status=status, detail=detail)

    # --------------------------------------------------------------- tokens
    def account_name(self) -> str | None:
        try:
            accounts = self._application().get_accounts()
        except AuthError:
            return None
        except Exception:  # noqa: BLE001 - sem internet a MSAL falha ao descobrir o locatário
            log.warning("Não foi possível consultar a conta Microsoft (sem conexão?)")
            with self._lock:
                self._app = None  # tenta de novo na próxima consulta
            return None
        return accounts[0].get("username") if accounts else None

    def is_signed_in(self) -> bool:
        return self.account_name() is not None

    def get_token(self, force_refresh: bool = False) -> str:
        try:
            app = self._application()
            accounts = app.get_accounts()
        except AuthError:
            raise
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._app = None
            raise AuthError("Sem conexão com a Microsoft no momento. Verifique a internet.") from exc
        if not accounts:
            self._status("off", "Não conectado")
            raise AuthError("Conta Microsoft não conectada. Use Configurações > Microsoft 365 > Conectar.")
        result = app.acquire_token_silent(self.scopes, account=accounts[0], force_refresh=force_refresh)
        if not result or "access_token" not in result:
            detail = (result or {}).get("error_description", "sessão expirada")
            self._status("error", "Reconecte sua conta")
            raise AuthError(f"Sua sessão Microsoft expirou ou perdeu permissões. Reconecte a conta. ({detail[:120]})")
        self._status("ok", accounts[0].get("username", ""))
        return result["access_token"]

    def sign_in_interactive(self) -> str:
        """Abre o navegador do sistema na página oficial de login da Microsoft."""
        app = self._application()
        self._status("pending", "Aguardando login no navegador")
        result = app.acquire_token_interactive(self.scopes, prompt="select_account", timeout=300)
        return self._finish(result)

    def sign_in_device_code(self, show: Callable[[dict], None]) -> str:
        """Alternativa: código exibido na tela para digitar em microsoft.com/devicelogin."""
        app = self._application()
        flow = app.initiate_device_flow(scopes=self.scopes)
        if "user_code" not in flow:
            raise AuthError(f"Não foi possível iniciar o login: {flow.get('error_description', flow)}")
        show({"message": flow.get("message", ""), "url": flow.get("verification_uri", ""),
              "code": flow.get("user_code", "")})
        self._status("pending", "Aguardando código de dispositivo")
        result = app.acquire_token_by_device_flow(flow)
        return self._finish(result)

    def _finish(self, result: dict) -> str:
        if "access_token" not in result:
            error = result.get("error_description") or result.get("error") or "falha desconhecida"
            self._status("error", "Falha no login")
            if "AADSTS65001" in error or "consent" in error.lower():
                raise AuthError("A organização exige aprovação de um administrador para estas permissões. "
                                "Veja docs/INTEGRACOES.md, seção 'Consentimento do administrador'.")
            raise AuthError(f"Login não concluído: {error[:200]}")
        username = (result.get("id_token_claims") or {}).get("preferred_username", "")
        self._status("ok", username)
        log.info("Conta Microsoft conectada")
        return username

    def sign_out(self) -> None:
        try:
            app = self._application()
            for account in app.get_accounts():
                app.remove_account(account)
        except Exception:  # noqa: BLE001 - mesmo offline, o cache local é apagado abaixo
            log.warning("Desconexão sem acesso à Microsoft; apagando o cache local")
        try:
            paths.token_cache_path().unlink(missing_ok=True)
        except OSError:
            pass
        with self._lock:
            self._app = None
        self._status("off", "Desconectado")
