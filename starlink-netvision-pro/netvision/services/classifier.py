"""Classificação ESTIMADA de serviços por nome de domínio (DNS/SNI) e de aplicativos por processo.

Importante: a identificação por domínio é uma estimativa. CDNs compartilhadas (ex.: fbcdn.net
atende Facebook e Instagram; googleusercontent.com atende vários serviços Google) e conexões
reaproveitadas podem gerar atribuições imprecisas. Nenhum conteúdo é decifrado.
"""
from __future__ import annotations

from dataclasses import dataclass

# (sufixo de domínio, serviço, categoria, confiança)
# confiança: "alta" = domínio exclusivo do serviço; "média" = CDN compartilhada/ambígua
DOMAIN_RULES: list[tuple[str, str, str, str]] = [
    # vídeo
    ("googlevideo.com", "YouTube", "Vídeo", "alta"),
    ("youtube.com", "YouTube", "Vídeo", "alta"),
    ("youtubei.googleapis.com", "YouTube", "Vídeo", "alta"),
    ("ytimg.com", "YouTube", "Vídeo", "alta"),
    ("yt3.ggpht.com", "YouTube", "Vídeo", "alta"),
    ("netflix.com", "Netflix", "Vídeo", "alta"),
    ("nflxvideo.net", "Netflix", "Vídeo", "alta"),
    ("nflximg.net", "Netflix", "Vídeo", "alta"),
    ("nflxso.net", "Netflix", "Vídeo", "alta"),
    ("nflxext.com", "Netflix", "Vídeo", "alta"),
    ("primevideo.com", "Prime Video", "Vídeo", "alta"),
    ("aiv-cdn.net", "Prime Video", "Vídeo", "alta"),
    ("aiv-delivery.net", "Prime Video", "Vídeo", "alta"),
    ("disneyplus.com", "Disney+", "Vídeo", "alta"),
    ("bamgrid.com", "Disney+", "Vídeo", "alta"),
    ("dssott.com", "Disney+", "Vídeo", "alta"),
    ("max.com", "Max", "Vídeo", "alta"),
    ("hbomaxcdn.com", "Max", "Vídeo", "alta"),
    ("globoplay.globo.com", "Globoplay", "Vídeo", "alta"),
    ("globo.com", "Globo", "Vídeo", "média"),
    ("twitch.tv", "Twitch", "Vídeo", "alta"),
    ("ttvnw.net", "Twitch", "Vídeo", "alta"),
    ("jtvnw.net", "Twitch", "Vídeo", "alta"),
    ("kick.com", "Kick", "Vídeo", "alta"),
    # redes sociais
    ("tiktok.com", "TikTok", "Rede social", "alta"),
    ("tiktokcdn.com", "TikTok", "Rede social", "alta"),
    ("tiktokcdn-us.com", "TikTok", "Rede social", "alta"),
    ("tiktokv.com", "TikTok", "Rede social", "alta"),
    ("tiktokv.us", "TikTok", "Rede social", "alta"),
    ("byteoversea.com", "TikTok", "Rede social", "média"),
    ("ibytedtos.com", "TikTok", "Rede social", "média"),
    ("ibyteimg.com", "TikTok", "Rede social", "média"),
    ("muscdn.com", "TikTok", "Rede social", "média"),
    ("instagram.com", "Instagram", "Rede social", "alta"),
    ("cdninstagram.com", "Instagram", "Rede social", "alta"),
    ("facebook.com", "Facebook", "Rede social", "alta"),
    ("fbcdn.net", "Meta (Facebook/Instagram)", "Rede social", "média"),
    ("fbsbx.com", "Meta (Facebook/Instagram)", "Rede social", "média"),
    ("whatsapp.net", "WhatsApp", "Mensagens", "alta"),
    ("whatsapp.com", "WhatsApp", "Mensagens", "alta"),
    ("x.com", "X (Twitter)", "Rede social", "alta"),
    ("twitter.com", "X (Twitter)", "Rede social", "alta"),
    ("twimg.com", "X (Twitter)", "Rede social", "alta"),
    ("kwai.com", "Kwai", "Rede social", "alta"),
    ("kwai.net", "Kwai", "Rede social", "alta"),
    ("kwaicdn.com", "Kwai", "Rede social", "alta"),
    ("snapchat.com", "Snapchat", "Rede social", "alta"),
    ("pinterest.com", "Pinterest", "Rede social", "alta"),
    ("pinimg.com", "Pinterest", "Rede social", "alta"),
    ("reddit.com", "Reddit", "Rede social", "alta"),
    ("redd.it", "Reddit", "Rede social", "alta"),
    ("telegram.org", "Telegram", "Mensagens", "alta"),
    ("t.me", "Telegram", "Mensagens", "alta"),
    ("discord.com", "Discord", "Mensagens", "alta"),
    ("discord.gg", "Discord", "Mensagens", "alta"),
    ("discordapp.com", "Discord", "Mensagens", "alta"),
    ("discordapp.net", "Discord", "Mensagens", "alta"),
    ("discord.media", "Discord", "Mensagens", "alta"),
    # música
    ("spotify.com", "Spotify", "Música", "alta"),
    ("scdn.co", "Spotify", "Música", "alta"),
    ("spotifycdn.com", "Spotify", "Música", "alta"),
    ("deezer.com", "Deezer", "Música", "alta"),
    ("dzcdn.net", "Deezer", "Música", "alta"),
    # jogos
    ("steampowered.com", "Steam", "Jogos", "alta"),
    ("steamcontent.com", "Steam (downloads)", "Jogos", "alta"),
    ("steamserver.net", "Steam", "Jogos", "alta"),
    ("steamstatic.com", "Steam", "Jogos", "alta"),
    ("steamcommunity.com", "Steam", "Jogos", "alta"),
    ("valvesoftware.com", "Valve / CS2", "Jogos", "alta"),
    ("riotgames.com", "Riot Games (LoL/Valorant)", "Jogos", "alta"),
    ("leagueoflegends.com", "League of Legends", "Jogos", "alta"),
    ("epicgames.com", "Epic Games / Fortnite", "Jogos", "alta"),
    ("epicgames.dev", "Epic Games / Fortnite", "Jogos", "alta"),
    ("fortnite.com", "Fortnite", "Jogos", "alta"),
    ("xboxlive.com", "Xbox Live", "Jogos", "alta"),
    ("playstation.net", "PlayStation Network", "Jogos", "alta"),
    ("playstation.com", "PlayStation Network", "Jogos", "alta"),
    ("roblox.com", "Roblox", "Jogos", "alta"),
    ("rbxcdn.com", "Roblox", "Jogos", "alta"),
    ("ea.com", "EA", "Jogos", "alta"),
    ("garena.com", "Free Fire (Garena)", "Jogos", "alta"),
    ("freefiremobile.com", "Free Fire (Garena)", "Jogos", "alta"),
    ("minecraft.net", "Minecraft", "Jogos", "alta"),
    ("battle.net", "Battle.net", "Jogos", "alta"),
    ("blizzard.com", "Battle.net", "Jogos", "alta"),
    ("ubisoft.com", "Ubisoft", "Jogos", "alta"),
    ("supercell.com", "Supercell", "Jogos", "alta"),
    ("pubgmobile.com", "PUBG Mobile", "Jogos", "alta"),
    # trabalho / sistema
    ("zoom.us", "Zoom", "Videochamada", "alta"),
    ("teams.microsoft.com", "Microsoft Teams", "Videochamada", "alta"),
    ("meet.google.com", "Google Meet", "Videochamada", "alta"),
    ("windowsupdate.com", "Windows Update", "Sistema", "alta"),
    ("delivery.mp.microsoft.com", "Windows Update", "Sistema", "alta"),
    ("update.microsoft.com", "Windows Update", "Sistema", "alta"),
    ("icloud.com", "iCloud", "Nuvem", "alta"),
    ("apple.com", "Apple", "Sistema", "média"),
    ("dropbox.com", "Dropbox", "Nuvem", "alta"),
    ("onedrive.live.com", "OneDrive", "Nuvem", "alta"),
    ("drive.google.com", "Google Drive", "Nuvem", "alta"),
    ("starlink.com", "Starlink", "Sistema", "alta"),
    ("google.com", "Google", "Web", "média"),
    ("googleapis.com", "Google", "Web", "média"),
    ("gstatic.com", "Google", "Web", "média"),
    ("microsoft.com", "Microsoft", "Sistema", "média"),
    ("amazonaws.com", "Amazon AWS (genérico)", "Web", "baixa"),
    ("cloudfront.net", "Amazon CloudFront (genérico)", "Web", "baixa"),
    ("akamaized.net", "Akamai CDN (genérico)", "Web", "baixa"),
]
# o sufixo mais longo vence (ex.: youtubei.googleapis.com antes de googleapis.com)
_RULES = sorted(DOMAIN_RULES, key=lambda r: -len(r[0]))


@dataclass(frozen=True)
class ServiceMatch:
    service: str
    category: str
    confidence: str
    domain: str


def classify_domain(domain: str) -> ServiceMatch | None:
    d = (domain or "").lower().rstrip(".")
    if not d:
        return None
    for suffix, service, cat, conf in _RULES:
        if d == suffix or d.endswith("." + suffix):
            return ServiceMatch(service, cat, conf, d)
    return None


# Processos do Windows -> nome amigável
PROCESS_NAMES: dict[str, str] = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "msedgewebview2.exe": "Edge WebView",
    "firefox.exe": "Firefox",
    "opera.exe": "Opera",
    "opera_gx.exe": "Opera GX",
    "brave.exe": "Brave",
    "steam.exe": "Steam",
    "steamwebhelper.exe": "Steam",
    "steamservice.exe": "Steam",
    "cs2.exe": "Counter-Strike 2",
    "csgo.exe": "CS:GO",
    "dota2.exe": "Dota 2",
    "discord.exe": "Discord",
    "spotify.exe": "Spotify",
    "epicgameslauncher.exe": "Epic Games",
    "fortniteclient-win64-shipping.exe": "Fortnite",
    "riotclientservices.exe": "Riot Client",
    "valorant-win64-shipping.exe": "Valorant",
    "league of legends.exe": "League of Legends",
    "battle.net.exe": "Battle.net",
    "eadesktop.exe": "EA App",
    "robloxplayerbeta.exe": "Roblox",
    "whatsapp.exe": "WhatsApp",
    "telegram.exe": "Telegram",
    "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams",
    "zoom.exe": "Zoom",
    "onedrive.exe": "OneDrive",
    "dropbox.exe": "Dropbox",
    "googledrivefs.exe": "Google Drive",
    "qbittorrent.exe": "qBittorrent (downloads)",
    "utorrent.exe": "uTorrent (downloads)",
    "bittorrent.exe": "BitTorrent (downloads)",
    "idman.exe": "Internet Download Manager",
    "fdm.exe": "Free Download Manager",
    "svchost.exe": "Serviços do Windows",
    "mousocoreworker.exe": "Windows Update",
    "wuauclt.exe": "Windows Update",
    "msmpeng.exe": "Microsoft Defender",
    "searchhost.exe": "Pesquisa do Windows",
    "system": "Sistema (kernel)",
    "obs64.exe": "OBS Studio",
    "vlc.exe": "VLC",
    "python.exe": "Python",
    "pythonw.exe": "Python",
}


def friendly_process(name: str | None) -> str:
    if not name:
        return "Desconhecido"
    low = name.lower()
    return PROCESS_NAMES.get(low) or PROCESS_NAMES.get(low + ".exe") or name
