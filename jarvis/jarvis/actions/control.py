"""Controle do próprio assistente: microfone, modo jogo, notificações, memória e comandos personalizados."""
from __future__ import annotations

import time

from ..nlu.normalize import normalize, similar
from .base import BOOL, INT, REGISTRY, STR, ActionResult, PendingAction, action, props


@action("mic_off", "Desliga o microfone do assistente (reativação pela bandeja, atalho ou controle).", llm=False)
def mic_off(services, params):
    if services.pipeline:
        services.pipeline.set_mic_enabled(False)
    services.state.mic_enabled = False
    services.state.busy_since = services.state.busy_since or time.time()
    return ActionResult("Microfone desligado. Para me reativar, use o ícone na bandeja ou o atalho de teclado.")


@action("sleep", "Coloca o assistente em espera: só responde a 'Jarvis, acorda'.", llm=False)
def sleep(services, params):
    if services.pipeline:
        services.pipeline.set_sleeping(True)
    services.state.sleeping = True
    services.state.busy_since = services.state.busy_since or time.time()
    return ActionResult("Entrando em espera. Diga Jarvis, acorda, quando precisar.")


@action("wake_up", "Sai do modo de espera.", llm=False)
def wake_up(services, params):
    if services.pipeline:
        services.pipeline.set_sleeping(False)
    services.state.sleeping = False
    return ActionResult("De volta. Às suas ordens.")


@action("game_mode", "Ativa ou desativa o modo jogo (respostas curtas, notificações silenciosas, interface pausada).",
        props(["active"], active=BOOL))
def game_mode(services, params):
    active = bool(params.get("active", True))
    services.state.game_mode_manual = active
    set_game_mode(services, active, "manual")
    return ActionResult("Modo jogo ativado. Boa partida." if active else "Modo jogo desativado.")


def set_game_mode(services, active: bool, reason: str) -> None:
    state = services.state
    if state.game_mode == active:
        return
    state.game_mode = active
    state.game_mode_reason = reason
    if active:
        state.busy_since = state.busy_since or time.time()
    services.bus.publish("game_mode", active=active, reason=reason)
    services.activity("Modo jogo " + ("ativado" if active else "desativado") + f" ({reason})", kind="system")


@action("quiet_mode", "Ativa ou desativa o modo silencioso (só fala quando chamado).", props(["active"], active=BOOL))
def quiet_mode(services, params):
    active = bool(params.get("active", True))
    services.state.quiet_mode = active
    if active:
        services.state.busy_since = services.state.busy_since or time.time()
    return ActionResult("Modo silencioso ativado. Só falo quando chamado." if active else "Modo silencioso desativado.")


@action("notifications_mute", "Silencia os avisos falados de notificações (opcionalmente por N minutos).",
        props(minutes=INT))
def notifications_mute(services, params):
    minutes = params.get("minutes")
    until = time.time() + int(minutes) * 60 if minutes else None
    services.settings.set("notifications.muted_until", until if until else -1)
    services.state.busy_since = services.state.busy_since or time.time()
    if minutes:
        return ActionResult(f"Notificações silenciadas por {minutes} minutos. Continuo registrando tudo.")
    return ActionResult("Notificações silenciadas. Continuo registrando tudo; peça um resumo quando quiser.")


@action("notifications_unmute", "Reativa os avisos falados de notificações.")
def notifications_unmute(services, params):
    services.settings.set("notifications.muted_until", None)
    return ActionResult("Notificações reativadas.")


@action("notifications_summary", "Resume o que chegou (WhatsApp, Outlook, planilhas, lembretes) desde que o usuário ficou ocupado.")
def notifications_summary(services, params):
    if services.notifications is None:
        return ActionResult.fail("A central de notificações não está ativa.")
    since = services.state.busy_since or services.state.last_summary_at
    if time.time() - since < 120:
        since = time.time() - 3 * 3600
    result = services.notifications.summary(since)
    services.state.busy_since = None
    services.state.last_summary_at = time.time()
    return result


@action("notifications_history", "Mostra o histórico recente de notificações.")
def notifications_history(services, params):
    if services.notifications is None:
        return ActionResult.fail("A central de notificações não está ativa.")
    items = services.notifications.recent(30)
    if not items:
        return ActionResult("Nenhuma notificação registrada.")
    return ActionResult(f"Mostrando as {len(items)} notificações mais recentes na tela.",
                        display="\n".join(services.notifications.format_line(n) for n in items))


@action("messages_check", "Confere mensagens novas no WhatsApp e e-mails não lidos.")
def messages_check(services, params):
    parts = []
    if services.whatsapp is not None:
        wa = services.whatsapp.unread_summary(short=True)
        if wa:
            parts.append(wa)
    if services.outlook is not None and services.outlook.available():
        try:
            parts.append(services.outlook.unread_sentence())
        except Exception as exc:  # noqa: BLE001
            parts.append(str(exc))
    if not parts:
        return ActionResult("Nenhuma integração de mensagens está conectada ainda. Veja Configurações.")
    return ActionResult(" ".join(parts))


# ------------------------------------------------------------- memória
@action("memory_add", "Guarda uma informação sobre o usuário na memória local (ex.: 'meu gestor é o Carlos').",
        props(["fact"], fact=STR))
def memory_add(services, params):
    fact = (params.get("fact") or "").strip()
    if not fact:
        return ActionResult.fail("O que devo guardar?")
    facts = services.settings.get("memory.facts", []) or []
    facts.append(fact)
    services.settings.set("memory.facts", facts)
    return ActionResult("Anotado. Você pode ver e apagar o que guardei em Privacidade e memória.")


@action("memory_forget", "Remove uma informação da memória local.", props(["fact"], fact=STR))
def memory_forget(services, params):
    target = normalize(params.get("fact", ""))
    facts = services.settings.get("memory.facts", []) or []
    keep = [f for f in facts if similar(target, normalize(f)) < 0.6]
    if len(keep) == len(facts):
        return ActionResult.fail("Não encontrei essa informação na memória.")
    services.settings.set("memory.facts", keep)
    return ActionResult("Esquecido.")


@action("memory_list", "Lista o que o assistente guardou sobre o usuário.")
def memory_list(services, params):
    facts = services.settings.get("memory.facts", []) or []
    if not facts:
        return ActionResult("Não tenho nada guardado sobre você.")
    say = ("Tenho 1 informação guardada. Está na tela." if len(facts) == 1
           else f"Tenho {len(facts)} informações guardadas. Estão na tela.")
    return ActionResult(say,
                        display="\n".join(f"• {f}" for f in facts))


# ---------------------------------------------------- comandos personalizados
def _custom_confirm(services, command: dict) -> str:
    return command.get("confirm_text") or f"Executar a sequência {command.get('phrases', ['personalizada'])[0]}?"


@action("custom_command", "Executa um comando personalizado do usuário pelo índice.", props(["index"], index=INT),
        llm=False)
def custom_command(services, params):
    commands = services.settings.get("custom_commands", []) or []
    index = int(params.get("index", -1))
    if not (0 <= index < len(commands)):
        return ActionResult.fail("Comando personalizado não encontrado.")
    command = commands[index]
    if command.get("confirm") and not params.get("_confirmed"):
        question = _custom_confirm(services, command)
        return ActionResult(question, expects_reply=True, pending=PendingAction(
            question=question, execute=lambda: custom_command(services, {**params, "_confirmed": True})))
    return run_sequence(services, command.get("actions", []), command.get("response"))


def run_sequence(services, steps: list[dict], final_response: str | None = None) -> ActionResult:
    """Executa uma sequência de ações permitidas. Ações de risco exigem confirmação própria."""
    spoken: list[str] = []
    undos = []
    services.state.cancel_event.clear()
    for step in steps:
        if services.state.cancel_event.is_set():
            services.state.cancel_event.clear()
            return ActionResult("Sequência interrompida.")
        name = step.get("action", "")
        if name == "wait":
            time.sleep(min(30, float(step.get("seconds", 1))))
            continue
        spec = REGISTRY.get(name)
        if spec is None or name == "custom_command":
            spoken.append(f"Ação {name} desconhecida, pulando.")
            continue
        params = {k: v for k, v in step.items() if k != "action"}
        result = REGISTRY.run(services, name, params)
        if result.pending:
            return ActionResult(" ".join(spoken + [result.say]), pending=result.pending, expects_reply=True)
        if result.undo:
            undos.append(result.undo)
        if not final_response:
            spoken.append(result.say)
    undo = None
    if undos:
        def undo() -> str:
            for fn in reversed(undos):
                fn()
            return "Sequência desfeita."
    return ActionResult(final_response or " ".join(spoken) or "Pronto.", undo=undo, undo_label="sequência")


@action("cancel_task", "Interrompe a tarefa em execução (sequências e consultas longas).", llm=False)
def cancel_task(services, params):
    services.state.cancel_event.set()
    if services.speaker:
        services.speaker.stop()
    return ActionResult("Tarefa interrompida.")
