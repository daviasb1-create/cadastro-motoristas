"""Ações da música de fundo."""
from __future__ import annotations

from .base import INT, ActionResult, ServiceUnavailable, action, props


def _player(services):
    player = services.extras.get("music")
    if player is None:
        raise ServiceUnavailable("A música de fundo não está disponível (sem dispositivo de áudio).")
    return player


@action("music_play", "Toca a música de fundo escolhida pelo usuário (modo Homem de Ferro).")
def music_play(services, params):
    url = (services.settings.get("music.url", "") or "").strip()
    if not services.settings.get("music.file") and url:
        # sem arquivo: abre a música no Spotify/YouTube (o volume fica por conta do app)
        if not url.startswith(("https://", "spotify:")):
            return ActionResult.fail("O link da música precisa começar com https:// ou spotify:.")
        if services.open_url:
            services.open_url(url)
        services.activity("Trilha aberta: " + url[:80], kind="music")
        return ActionResult("Abrindo a trilha." if "spotify" not in url else "Abrindo a trilha no Spotify.")
    error = _player(services).play()
    if error:
        return ActionResult.fail(error)
    services.activity("Música de fundo iniciada", kind="music")
    return ActionResult("Com trilha sonora.", undo=lambda: (_player(services).stop(), "Música parada.")[1],
                        undo_label="música")


@action("music_stop", "Para a música de fundo.")
def music_stop(services, params):
    player = services.extras.get("music")
    if (player is None or not player.playing) and services.extras.get("spotify") is not None:
        from ..integrations.spotify import spotify_pause

        return spotify_pause(services, {})
    player = _player(services)
    if not player.playing:
        return ActionResult("Não há música tocando.")
    player.stop()
    return ActionResult("Música parada.")


@action("music_volume", "Aumenta ou diminui o volume da música de fundo.", props(["delta"], delta=INT))
def music_volume(services, params):
    player = services.extras.get("music")
    spotify = services.extras.get("spotify")
    if (player is None or not player.playing) and spotify is not None and spotify.connected():
        from ..integrations.spotify import spotify_volume

        return spotify_volume(services, {"delta": int(params.get("delta", 10))})
    volume = max(5, min(100, services.settings.get("music.volume", 30) + int(params.get("delta", 10))))
    services.settings.set("music.volume", volume)
    return ActionResult(f"Música em {volume} por cento.")
