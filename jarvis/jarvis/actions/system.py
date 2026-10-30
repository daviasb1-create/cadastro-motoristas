"""Ações de sistema: hora, data, bateria, estado do computador e ajuda."""
from __future__ import annotations

from datetime import datetime

from .base import ActionResult, action

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]


def spoken_time(now: datetime) -> str:
    if now.minute == 0:
        return f"{now.hour} hora{'s' if now.hour != 1 else ''}"
    return f"{now.hour} e {now.minute:02d}" if now.minute < 10 else f"{now.hour} e {now.minute}"


def spoken_date(now: datetime) -> str:
    return f"{WEEKDAYS[now.weekday()]}, {now.day} de {MONTHS[now.month - 1]} de {now.year}"


@action("time", "Informa a hora atual.")
def time_now(services, params):
    now = datetime.now()
    return ActionResult(f"São {spoken_time(now)}.", display=now.strftime("%H:%M"))


@action("date", "Informa a data de hoje.")
def date_today(services, params):
    now = datetime.now()
    return ActionResult(f"Hoje é {spoken_date(now)}.", display=now.strftime("%d/%m/%Y"))


@action("battery", "Informa o nível da bateria do computador, se houver bateria.")
def battery(services, params):
    import psutil

    info = psutil.sensors_battery()
    if info is None:
        return ActionResult("Este computador não informa bateria; parece estar ligado direto na tomada.")
    plugged = "carregando" if info.power_plugged else "na bateria"
    extra = ""
    if not info.power_plugged and info.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
        hours, minutes = divmod(int(info.secsleft) // 60, 60)
        extra = f" Restam cerca de {hours} hora{'s' if hours != 1 else ''} e {minutes} minutos." if hours else f" Restam cerca de {minutes} minutos."
    return ActionResult(f"Bateria em {int(info.percent)} por cento, {plugged}.{extra}")


@action("system_status", "Informa uso de processador, memória e disco do computador.")
def system_status(services, params):
    import psutil

    cpu = psutil.cpu_percent(interval=0.4)
    mem = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage("C:\\" if psutil.WINDOWS else "/")
        disk_text = f" Disco com {int(disk.percent)} por cento ocupado."
    except OSError:
        disk_text = ""
    say = (f"Processador em {int(cpu)} por cento e memória em {int(mem.percent)} por cento."
           f"{disk_text}")
    top = []
    if cpu > 60 or mem.percent > 80:
        procs = sorted(psutil.process_iter(["name", "memory_info"]),
                       key=lambda p: (p.info.get("memory_info").rss if p.info.get("memory_info") else 0),
                       reverse=True)[:3]
        top = [p.info["name"] for p in procs if p.info.get("name")]
        if top:
            say += f" Os programas que mais usam memória são: {', '.join(top)}."
    return ActionResult(say)


HELP_TEXT = """Exemplos do que posso fazer:
• "Jarvis, abre o navegador" / "fecha o navegador" / "abre o Storm 4"
• "aumenta o volume", "volume em 30", "muta o som"
• "abre a pasta de downloads", "procura o arquivo contrato"
• "me lembra de ligar para o João em 10 minutos"
• "tenho e-mails novos?", "resume os e-mails importantes", "procura o último e-mail do meu gestor"
• "quem me chamou no WhatsApp?", "abre a conversa com Ana", "manda mensagem para Ana dizendo ..."
• "verifica minhas pendências", "procura a nota fiscal 1234", "abre a planilha de controle"
• "o que aconteceu enquanto eu estava ocupado?", "silencia as notificações por 30 minutos"
• "ativa o modo jogo", "muda para a Friday", "fala mais devagar", "pare", "cancele a última ação"
• "desliga o microfone", "dorme" (reativação: "Jarvis, acorda")"""


@action("help", "Explica o que o assistente sabe fazer.", llm=False)
def help_action(services, params):
    return ActionResult(
        "Posso controlar o Windows, abrir programas e jogos, ajustar o volume, criar lembretes, "
        "acompanhar e-mails, WhatsApp e planilhas. A lista de exemplos está na tela.",
        display=HELP_TEXT,
    )
