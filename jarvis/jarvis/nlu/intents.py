"""Interpretador local de comandos (sem IA na nuvem, sem custo por chamada).

Cada regra transforma uma frase normalizada em ``Intent(name, params)``.
A ordem das regras importa: as mais específicas vêm primeiro. Frases que
nenhuma regra reconhece seguem para o provedor de IA (se configurado).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .normalize import normalize, similar
from .numbers import first_number, words_to_digits
from .timeparse import parse_when


@dataclass
class Intent:
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    text: str = ""


Rule = Callable[[str], "Intent | None"]

OPEN_VERBS = r"(?:abre|abra|abrir|inicia|iniciar|inicie|executa|executar|execute|roda|rodar|liga|ligar|lanca|bota|coloca|entra no|entra na|entrar no|acessa|acessar|joga|jogar|vamos jogar|quero jogar|carrega|carregar)"
CLOSE_VERBS = r"(?:fecha|fechar|feche|encerra|encerrar|encerre|finaliza|finalizar|sai do|sair do|mata|matar|termina|terminar)"
SEARCH_VERBS = r"(?:procura|procure|procurar|pesquisa|pesquise|pesquisar|busca|busque|buscar|encontra|encontre|encontrar|acha|ache|achar|localiza|localize|localizar)"
ARTICLES = r"(?:o|a|os|as|um|uma|meu|minha|meus|minhas|no|na|do|da|de)"

YES_WORDS = {
    "sim", "pode", "confirmo", "confirma", "confirmado", "isso", "claro", "positivo", "manda",
    "envia", "pode enviar", "pode mandar", "pode fazer", "faz", "faca", "ok", "okay", "certo",
    "correto", "afirmativo", "com certeza", "pode sim", "sim pode", "isso mesmo", "executa",
}
NO_WORDS = {
    "nao", "cancela", "cancelar", "cancele", "negativo", "deixa", "deixa pra la", "esquece",
    "nao precisa", "nao quero", "para", "pare", "nada", "melhor nao", "agora nao", "nao obrigado",
}


def parse_yes_no(text: str) -> bool | None:
    t = normalize(text)
    if not t:
        return None
    if t in YES_WORDS or t.startswith(("sim ", "pode ", "confirmo", "confirma ")):
        return True
    if t in NO_WORDS or t.startswith(("nao ", "cancela", "negativo")):
        return False
    return None


def _strip_articles(text: str) -> str:
    text = re.sub(rf"^(?:{ARTICLES}\s+)+", "", text.strip())
    return text.strip()


def _rx(pattern: str, name: str, builder: Callable[[re.Match], dict] | None = None) -> Rule:
    compiled = re.compile(pattern)

    def rule(text: str) -> Intent | None:
        match = compiled.search(text)
        if not match:
            return None
        params = builder(match) if builder else {}
        if params is None:
            return None
        return Intent(name, params)

    return rule


# ------------------------------------------------------------------ regras
def _volume_rule(text: str) -> Intent | None:
    t = words_to_digits(text)
    if not re.search(r"\b(volume|som|audio|alto|baixo|mudo|mute|muta|desmuta)\b", t):
        return None
    if re.search(r"\b(fala|falar|sua voz|tua voz|voce)\b.*\b(mais alto|mais baixo)\b", t):
        return None  # ajuste da voz do assistente, tratado em outra regra
    if re.search(r"\b(tira do mudo|desmuta|desmutar|ativa o som|liga o som|volta o som|reativa o som)\b", t):
        return Intent("volume_mute", {"mute": False})
    if re.search(r"\b(muta|mutar|mudo|mute|silencia o (som|audio|computador|pc)|desliga o som|corta o som)\b", t):
        return Intent("volume_mute", {"mute": True})
    amount = None
    m = re.search(r"\b(\d{1,3})\s*(?:%|por cento)?", t)
    if m:
        amount = min(100, int(m.group(1)))
    if re.search(r"\b(aumenta|aumentar|aumente|sobe|subir|suba|mais alto|eleva|levanta)\b", t):
        return Intent("volume_change", {"delta": amount or 10})
    if re.search(r"\b(diminui|diminuir|diminua|abaixa|abaixar|abaixe|baixa|baixar|reduz|reduzir|mais baixo)\b", t):
        return Intent("volume_change", {"delta": -(amount or 10)})
    if amount is not None and re.search(r"\b(volume|som)\b.*\b(em|para|pra|no|a)\b|\b(coloca|deixa|ajusta|poe|bota)\b", t):
        return Intent("volume_set", {"level": amount})
    if re.search(r"\b(qual|como esta|quanto esta)\b.*\bvolume\b", t):
        return Intent("volume_get")
    return None


def _speech_rule(text: str) -> Intent | None:
    t = text
    if re.search(r"\b(fala|falar|fale)\b.*\bmais (devagar|lento)\b", t):
        return Intent("speech_rate", {"delta": -10})
    if re.search(r"\b(fala|falar|fale)\b.*\bmais (rapido|depressa)\b", t):
        return Intent("speech_rate", {"delta": 10})
    if re.search(r"\b(fala|falar|fale)\b.*\bmais alto\b|\baumenta (a )?(sua|tua) voz\b", t):
        return Intent("speech_volume", {"delta": 10})
    if re.search(r"\b(fala|falar|fale)\b.*\bmais baixo\b|\b(abaixa|diminui) (a )?(sua|tua) voz\b", t):
        return Intent("speech_volume", {"delta": -10})
    m = re.search(r"\b(muda|mude|troca|troque|alterna|alterne|usa|use|ativa|ative|chama|chame)\b.*\b(friday|fraide|fraidei|sexta feira|jarvis)\b", t)
    if m:
        profile = "jarvis" if m.group(2) == "jarvis" else "friday"
        return Intent("set_profile", {"profile": profile})
    if re.search(r"\b(respostas|resposta|responde|fala)\b.*\b(curtas?|resumid[ao]s?|breves?)\b", t):
        return Intent("set_verbosity", {"verbosity": "short"})
    if re.search(r"\b(respostas|resposta|responde|fala)\b.*\b(detalhad[ao]s?|complet[ao]s?|long[ao]s?)\b", t):
        return Intent("set_verbosity", {"verbosity": "detailed"})
    if re.search(r"\b(desativa|desliga|para de responder|sem) (as )?(respostas faladas|voz|resposta falada)\b", t):
        return Intent("spoken_replies", {"enabled": False})
    if re.search(r"\b(ativa|liga|volta) (as )?(respostas faladas|voz|resposta falada)\b", t):
        return Intent("spoken_replies", {"enabled": True})
    return None


def _control_rule(text: str) -> Intent | None:
    t = text
    if re.fullmatch(r"(pare|para|parar|chega|silencio|cala a boca|fica quieto|fique quieto|quieto|stop|shh+|psiu|ja chega|pode parar|para de falar|pare de falar)", t):
        return Intent("stop")
    if re.search(r"\b(cancela|cancele|cancelar|desfaz|desfaca|desfazer)\b.*\b(ultima|ultimo)\b.*\b(acao|comando|coisa)\b|\bdesfaz(er)?( isso)?$", t):
        return Intent("undo")
    if re.search(r"\b(interrompe|interromper|cancela|cancele|aborta|abortar)\b.*\b(tarefa|execucao|operacao)\b", t):
        return Intent("cancel_task")
    if re.search(r"\b(desliga|desligue|desativa|pausa|pause|fecha)\b.*\bmicrofone\b|\bpara de (me )?(ouvir|escutar)\b|\bmodo privado\b", t):
        return Intent("mic_off")
    if re.search(r"\b(dorme|dormir|durma|vai dormir|suspende|suspender|suspenda|descansa|hiberna|modo de espera)\b", t):
        return Intent("sleep")
    if re.fullmatch(r"(acorda|acordar|acorde|desperta|reativa|reativar|volta a (me )?ouvir|volte a (me )?ouvir|pode voltar|modo ativo)( jarvis)?", t):
        return Intent("wake_up")
    return None


def _game_rule(text: str) -> Intent | None:
    t = text
    if re.search(r"\bmodo (de )?(jogo|gamer|gaming|game)\b", t):
        off = re.search(r"\b(desativa|desliga|sai|sair|encerra|termina|desligar|desativar)\b", t)
        return Intent("game_mode", {"active": not off})
    if re.search(r"\bmodo silencioso\b", t):
        off = re.search(r"\b(desativa|desliga|sai|sair|encerra)\b", t)
        return Intent("quiet_mode", {"active": not off})
    return None


def _notifications_rule(text: str) -> Intent | None:
    t = words_to_digits(text)
    if re.search(r"\b(silencia|silenciar|silencie|desativa|desliga|pausa|bloqueia|mute)\b.*\bnotificac", t):
        minutes = None
        m = re.search(r"\b(\d+)\s*(minutos?|min|horas?)\b", t)
        if m:
            minutes = int(m.group(1)) * (60 if m.group(2).startswith("h") else 1)
        return Intent("notifications_mute", {"minutes": minutes})
    if re.search(r"\b(ativa|reativa|liga|volta|retoma)\b.*\bnotificac", t):
        return Intent("notifications_unmute")
    if re.search(
        r"o que (aconteceu|rolou|houve|chegou|perdi)|alguma novidade|tem novidade|quais (as )?novidades|"
        r"resumo (das|de) notificac|resume (as )?notificac|me atualiza|o que eu perdi|novidades", t):
        return Intent("notifications_summary")
    if re.search(r"\b(historico|ultimas) (das |de )?notificac", t):
        return Intent("notifications_history")
    return None


def _agenda_rule(text: str) -> Intent | None:
    t = text
    if re.search(r"o que (temos|tenho|tem) (pra|para) (hoje|amanha|agora)|como (esta|e) (o )?meu dia|resumo do dia|bom dia", t):
        day = "amanha" if "amanha" in t else "hoje"
        return Intent("daily_briefing", {"day": day})
    if re.search(r"\b(agenda|compromissos?|reunio(es|ao)|calendario|eventos?)\b", t) and not re.search(OPEN_VERBS, t):
        day = "amanha" if "amanha" in t else "hoje"
        return Intent("calendar", {"day": day})
    return None


def _time_rule(text: str) -> Intent | None:
    t = text
    if re.search(r"\b(que horas|qual (e )?a hora|hora atual|horas sao|me (diz|diga|fala) a hora)\b", t):
        return Intent("time")
    if re.search(r"\b(que dia|qual (e )?a data|data de hoje|dia (e )?hoje|que data)\b", t):
        return Intent("date")
    return None


def _system_rule(text: str) -> Intent | None:
    t = text
    if re.search(r"\bbateria\b", t):
        return Intent("battery")
    if re.search(r"\b(status|estado|situacao|desempenho|uso)\b.*\b(sistema|computador|pc|maquina|cpu|processador|memoria)\b|\bcomo (esta|ta) (o )?(pc|computador|sistema)\b", t):
        return Intent("system_status")
    return None


def _reminder_rule(text: str) -> Intent | None:
    t = text
    if re.search(r"\b(quais|meus|lista|listar|mostra)\b.*\blembretes\b|\btenho (algum )?lembrete", t):
        return Intent("reminder_list")
    if re.search(r"\b(cancela|cancelar|apaga|apagar|remove|remover|exclui)\b.*\blembretes?\b", t):
        return Intent("reminder_cancel", {"all": bool(re.search(r"\b(todos|os lembretes)\b", t))})
    m = re.search(r"\b(?:me lembra|me lembre|lembre me|lembra me|me avisa|me avise|cria (um )?lembrete|criar (um )?lembrete|lembrete|alarme|timer|temporizador|cronometro)\b(.*)", t)
    if not m:
        return None
    rest = m.group(0)
    due, remaining = parse_when(rest)
    message = re.sub(
        r"^(me lembra|me lembre|lembre me|lembra me|me avisa|me avise|cria um lembrete|cria lembrete|"
        r"criar um lembrete|criar lembrete|lembrete|alarme|timer|temporizador|cronometro)\s*", "", remaining)
    message = re.sub(r"^(de|para|pra|que|para que|pra que|sobre)\s+", "", message).strip()
    if not message:
        message = "Seu lembrete"
    return Intent("reminder_create", {"when": due.isoformat() if due else None, "text": message})


def _memory_rule(text: str) -> Intent | None:
    t = text
    m = re.match(r"^(?:lembra que|lembre que|lembre se que|guarda que|anota que|grava que|memoriza que|saiba que)\s+(.+)$", t)
    if m:
        return Intent("memory_add", {"fact": m.group(1)})
    m = re.match(r"^(?:esquece|esqueca|apaga da memoria|remove da memoria)\s+(?:que\s+|o que\s+)?(.+)$", t)
    if m and not re.search(r"\b(isso|deixa)\b", m.group(1)):
        return Intent("memory_forget", {"fact": m.group(1)})
    if re.search(r"o que (voce )?(sabe|lembra) (sobre|de) mim|o que (voce )?tem (guardado|na memoria)", t):
        return Intent("memory_list")
    return None


def _email_rule(text: str) -> Intent | None:
    t = text
    if not re.search(r"\b(emails?|correio|caixa de entrada|outlook|mensagem do gestor|meu gestor|meu chefe)\b", t):
        return None
    if re.search(rf"^{OPEN_VERBS}\s+(o\s+)?(meu\s+)?(outlook|email|correio)$", t):
        return Intent("open_target", {"target": "outlook"})
    if re.search(r"\b(prepara|prepare|escreve|escreva|redige|redija|faz|faca|cria|crie|rascunho)\b.*\b(resposta|responder)\b", t):
        m = re.search(r"\b(dizendo|falando|que diz|com o texto|informando|avisando)\s+(?:que\s+)?(.+)$", t)
        return Intent("email_draft_reply", {"instructions": m.group(2) if m else ""})
    if re.search(r"\b(responde|responda)\b", t):
        m = re.search(r"\b(dizendo|falando|que|com)\s+(.+)$", t)
        return Intent("email_draft_reply", {"instructions": m.group(2) if m else ""})
    m = re.search(r"\b(manda|mande|envia|envie|escreve|escreva)\b.*\bemail\b\s+(?:para|pra)\s+(.+?)(?:\s+(?:dizendo|falando|sobre|com o assunto)\s+(.+))?$", t)
    if m:
        return Intent("email_compose", {"to": m.group(2).strip(), "instructions": (m.group(3) or "").strip()})
    if re.search(r"\b(anexo|anexos)\b", t):
        return Intent("email_attachments")
    m = re.search(rf"\b{SEARCH_VERBS}\b.*?\bemails?\b\s*(?:(?:do|da|de)\s+(?P<from>.+?)|sobre\s+(?P<about>.+?)|com\s+(?:o\s+)?(?:assunto|palavra)\s+(?P<subject>.+?))?$", t)
    if m:
        sender = m.group("from") or ""
        if re.search(r"\b(meu gestor|meu chefe|minha gestora|minha chefe)\b", t):
            sender = "@manager"
        return Intent("email_search", {
            "sender": sender.strip(), "query": (m.group("about") or m.group("subject") or "").strip(),
            "latest": bool(re.search(r"\bultimo\b", t)),
        })
    if re.search(r"\b(ultimo|ultima)\b.*\b(email|mensagem)\b.*\b(meu gestor|meu chefe|minha gestora|minha chefe)\b", t):
        return Intent("email_search", {"sender": "@manager", "query": "", "latest": True})
    if re.search(r"\b(le|leia|ler|lê|abre|abra|mostra|mostre)\b.*\b(esse|este|ultimo|primeiro|o)\s+email\b", t):
        action = "email_open" if re.search(r"\b(abre|abra|mostra|mostre)\b", t) else "email_read"
        index = 1 if re.search(r"\bsegundo\b", t) else (2 if re.search(r"\bterceiro\b", t) else 0)
        return Intent(action, {"index": index})
    if re.search(r"\b(resume|resuma|resumir|resumo)\b", t):
        return Intent("email_summary", {"important_only": bool(re.search(r"\b(importantes?|urgentes?)\b", t))})
    if re.search(r"\b(importantes?|urgentes?)\b", t):
        return Intent("email_summary", {"important_only": True})
    if re.search(r"\bquem\b.*\b(mandou|enviou|escreveu)\b", t):
        return Intent("email_senders", {"day": "hoje" if "hoje" in t or "ontem" not in t else "ontem"})
    if re.search(r"\b(novos?|nao lidos?|chegou|chegaram|tenho|recebi|verifica|verificar|confere|checa)\b", t):
        return Intent("email_unread")
    return None


def _whatsapp_rule(text: str) -> Intent | None:
    t = text
    wa = re.search(r"\b(whatsapp|whats|zap|zapzap|wpp)\b", t)
    msg = re.search(r"\b(mensage(m|ns)|conversas?|contato|chamou|chamaram|falou comigo|falaram comigo|me mandou|me mandaram)\b", t)
    if not (wa or msg):
        return None
    if re.search(r"\bemails?\b", t):
        return None
    m = re.search(r"\b(manda|mande|envia|envie|escreve|escreva|prepara|prepare)\b\s+(?:uma\s+)?(?:mensagem|msg|zap|whatsapp)\s+(?:no whatsapp\s+)?(?:para|pra|pro)\s+(?:o\s+|a\s+)?(.+?)(?:\s+(?:dizendo|falando|que diz|com o texto|avisando|informando)\s+(?:que\s+)?(.+))?$", t)
    if m:
        return Intent("whatsapp_compose", {"contact": m.group(2).strip(), "text": (m.group(3) or "").strip()})
    if re.search(r"\b(prepara|prepare|escreve|escreva|faz|faca)\b.*\bresposta\b", t):
        m = re.search(r"\b(?:para|pra|pro)\s+(?:o\s+|a\s+)?(?!esse|essa|este|esta)(\w+(?:\s\w+)?)", t)
        m2 = re.search(r"\b(dizendo|falando|que diz|avisando|informando)\s+(?:que\s+)?(.+)$", t)
        return Intent("whatsapp_draft_reply", {"contact": m.group(1) if m else "", "text": m2.group(2) if m2 else ""})
    m = re.search(rf"\b{OPEN_VERBS}\b.*\bconversa\b(?:\s+(?:com|do|da|de)\s+(?:o\s+|a\s+)?(.+))?", t)
    if m:
        contact = (m.group(1) or "").strip()
        if not contact or re.search(r"\b(mais recente|ultima)\b", t):
            return Intent("whatsapp_open_chat", {"contact": "", "latest": True})
        return Intent("whatsapp_open_chat", {"contact": contact, "latest": False})
    if re.search(rf"^{OPEN_VERBS}\s+(o\s+)?(meu\s+)?(whatsapp|whats|zap|wpp)(\s+business)?$", t):
        return Intent("open_target", {"target": "whatsapp"})
    if re.search(r"\b(resume|resuma|resumir|resumo)\b", t):
        return Intent("whatsapp_summary")
    if re.search(r"\bquem\b", t):
        return Intent("whatsapp_senders", {"today": "hoje" in t})
    if re.search(r"\b(chegou|chegaram|tem|tenho|recebi|novas?|nao lidas?|alguma|verifica|verificar|confere|checa)\b", t):
        # "verifica minhas mensagens" sem citar o app: confere WhatsApp e e-mail juntos
        return Intent("whatsapp_unread" if wa else "messages_check")
    return None


def _excel_rule(text: str) -> Intent | None:
    t = text
    sheet_word = re.search(r"\b(planilhas?|tabelas?|excel)\b", t)
    pend = re.search(r"\b(pendencias?|pendentes?|atrasad[ao]s?|em aberto|vencid[ao]s?)\b", t)
    if not (sheet_word or pend):
        return None
    if re.search(r"\b(lista|listar|quais|mostra)\b.*\bplanilhas\b", t):
        return Intent("excel_list")
    m = re.search(rf"\b{OPEN_VERBS}\b\s+(?:a\s+|minha\s+|a minha\s+)*(?:planilha|tabela)\s*(?:de\s+|do\s+|da\s+|dos\s+|das\s+)?(.*)$", t)
    if m:
        name = m.group(1).strip()
        if re.fullmatch(r"(correspondente|dessa|desta|essa|esta|mesma)", name or "x"):
            name = ""
        return Intent("excel_open", {"workbook": name})
    if pend:
        oldest = bool(re.search(r"\b(antigas?|antigos?|mais velh)", t))
        overdue = bool(re.search(r"\b(atrasad[ao]s?|vencid[ao]s?)\b", t))
        wb = re.search(r"\b(?:na|da)\s+planilha\s+(?:de\s+|do\s+|da\s+)?(.+)$", t)
        return Intent("excel_pending", {"oldest": oldest, "overdue": overdue, "workbook": wb.group(1) if wb else ""})
    if re.search(r"\b(resume|resuma|resumo|resumir)\b", t):
        wb = re.search(r"\bplanilha\s+(?:de\s+|do\s+|da\s+)?(?!dessa|desta|essa|esta)(.+)$", t)
        return Intent("excel_summary", {"workbook": wb.group(1) if wb else ""})
    m = re.search(rf"\b{SEARCH_VERBS}\b\s+(.+?)(?:\s+(?:na|da)\s+planilha(?:\s+(?:de\s+|do\s+|da\s+)?(.+))?)?$", t)
    if m:
        query = re.sub(r"^(o registro|o cadastro|a linha|o nome|a informacao|os dados)\s+(da|do|de)\s+", "", m.group(1)).strip()
        query = re.sub(r"^(registro|cadastro|nome|cliente|nota fiscal|nota)\s+", lambda mm: mm.group(0), query)
        return Intent("excel_search", {"query": query, "workbook": (m.group(2) or "").strip()})
    if re.search(r"\b(inconsistencias?|erros?|problemas?|duplicad)", t):
        return Intent("excel_check")
    return None


_RECORD_SEARCH = re.compile(
    rf"\b{SEARCH_VERBS}\b\s+(?:o\s+|a\s+)?(?:registro|cadastro|linha|informacao|dados)?\s*(?:dess[ae]|dest[ae]|da|do|de)?\s*"
    r"(?P<q>(?:nota fiscal|nf|cliente|pedido|entrega|motorista|placa|cnpj|cpf|codigo)\b.*)$"
)


def _record_search_rule(text: str) -> Intent | None:
    """"procura a nota fiscal 1234" sem citar planilha: busca nas planilhas configuradas."""
    m = _RECORD_SEARCH.search(text)
    if m:
        return Intent("excel_search", {"query": m.group("q").strip(), "workbook": ""})
    return None


def _file_rule(text: str) -> Intent | None:
    t = text
    m = re.search(rf"\b{SEARCH_VERBS}\b\s+(?:o\s+|um\s+|meu\s+)?(?:arquivo|documento|pdf|planilha local)\s+(?:chamado\s+|de nome\s+|com nome\s+|sobre\s+)?(.+)$", t)
    if m:
        return Intent("file_search", {"query": m.group(1).strip()})
    m = re.search(rf"\b{OPEN_VERBS}\b\s+(?:a\s+)?(?:minha\s+)?pasta\s+(?:de\s+|do\s+|da\s+|dos\s+|das\s+)?(.+)$", t)
    if m:
        return Intent("open_folder", {"folder": m.group(1).strip()})
    return None


def _window_rule(text: str) -> Intent | None:
    t = text
    m = re.search(r"\b(?:muda|mude|troca|troque|alterna|alterne|vai|va|volta|volte)\s+(?:para|pra|pro)\s+(?:a\s+janela\s+(?:do\s+|da\s+|de\s+)?|o\s+|a\s+)?(.+)$", t)
    if m:
        return Intent("switch_window", {"target": m.group(1).strip()})
    m = re.search(r"\b(?:mostra|mostre|traz|traga)\s+(?:a\s+)?janela\s+(?:do\s+|da\s+|de\s+)?(.+)$", t)
    if m:
        return Intent("switch_window", {"target": m.group(1).strip()})
    if re.search(r"\b(minimiza|minimizar)\b.*\b(tudo|todas)\b|\bmostra a area de trabalho\b", t):
        return Intent("show_desktop")
    return None


def _open_close_rule(text: str) -> Intent | None:
    t = text
    m = re.search(rf"^(?:.*\s)?{CLOSE_VERBS}\s+(.+)$", t)
    if m:
        target = _strip_articles(m.group(1))
        force = bool(re.search(r"\b(forca|forcado|forcar|na marra)\b", target))
        target = re.sub(r"\s*\b(a forca|na forca|forcado|forcando|na marra)\b", "", target).strip()
        if target in ("isso", "essa janela", "esta janela", "janela atual", "a janela"):
            target = "@foreground"
        return Intent("close_app", {"target": target, "force": force})
    m = re.search(rf"^(?:.*\s)?{OPEN_VERBS}\s+(.+)$", t)
    if m:
        target = _strip_articles(m.group(1))
        target = re.sub(r"^(o jogo|jogo|o programa|programa|o aplicativo|aplicativo|o app|app|o site|site)\s+", "", target)
        if target:
            return Intent("open_target", {"target": words_to_digits(target)})
    return None


def _help_rule(text: str) -> Intent | None:
    if re.search(r"o que (voce )?(sabe|pode|consegue) fazer|\bajuda\b|\bcomandos\b|\bcomo (te|voce) uso\b", text):
        return Intent("help")
    return None


def _greeting_rule(text: str) -> Intent | None:
    t = text
    if t in ("", "oi", "ola", "ei", "hey", "e ai", "alo"):
        return Intent("ack")
    if re.fullmatch(r"(preciso de voce|esta ai|ta ai|voce esta ai|esta me ouvindo|ta me ouvindo|esta acordado|tudo bem|me ouve)", t):
        return Intent("ack")
    if re.fullmatch(r"(obrigad[oa]|valeu|muito obrigad[oa]|obrigad[oa] jarvis|brigad[oa])", t):
        return Intent("thanks")
    if re.fullmatch(r"(boa noite|boa tarde)", t):
        return Intent("greeting")
    return None


RULES: list[Rule] = [
    _greeting_rule,
    _control_rule,
    _speech_rule,
    _game_rule,
    _notifications_rule,
    _reminder_rule,
    _memory_rule,
    _time_rule,
    _system_rule,
    _volume_rule,
    _email_rule,
    _whatsapp_rule,
    _excel_rule,
    _record_search_rule,
    _agenda_rule,
    _file_rule,
    _window_rule,
    _help_rule,
    _open_close_rule,
]


class IntentParser:
    def __init__(self, custom_commands: list[dict] | None = None):
        self.custom_commands = custom_commands or []

    def parse(self, text: str) -> Intent | None:
        t = normalize(text)
        custom = self._match_custom(t)
        if custom:
            custom.text = t
            return custom
        for rule in RULES:
            intent = rule(t)
            if intent:
                intent.text = t
                return intent
        return None

    def _match_custom(self, t: str) -> Intent | None:
        best: tuple[float, dict] | None = None
        for index, command in enumerate(self.custom_commands):
            for phrase in command.get("phrases", []):
                score = similar(normalize(phrase), t)
                if score >= 0.88 and (best is None or score > best[0]):
                    best = (score, {"index": index})
        if best:
            return Intent("custom_command", best[1], confidence=best[0])
        return None
