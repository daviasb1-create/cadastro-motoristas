from datetime import datetime

import pytest

from jarvis.nlu.intents import IntentParser, parse_yes_no
from jarvis.nlu.normalize import normalize, recover_original, similar, strip_wake_words
from jarvis.nlu.numbers import words_to_digits
from jarvis.nlu.timeparse import describe, parse_when

parser = IntentParser()


def parse(text):
    intent = parser.parse(strip_wake_words(normalize(text), ["jarvis"]))
    return (intent.name, intent.params) if intent else (None, {})


# Exemplos literais do documento de requisitos
@pytest.mark.parametrize("text,expected", [
    ("Jarvis.", "ack"),
    ("Jarvis, preciso de você.", "ack"),
    ("Jarvis, o que temos para hoje?", "daily_briefing"),
    ("Jarvis, abre meu Outlook.", "open_target"),
    ("Jarvis, verifica minhas mensagens.", "messages_check"),
    ("Jarvis, abre minha planilha de controle.", "excel_open"),
    ("Jarvis, quem me chamou no WhatsApp?", "whatsapp_senders"),
    ("Jarvis, silencia as notificações.", "notifications_mute"),
    ("Jarvis, pare.", "stop"),
    ("Jarvis, abre o navegador.", "open_target"),
    ("Jarvis, abre o Storm 4.", "open_target"),
    ("Jarvis, aumenta o volume.", "volume_change"),
    ("Jarvis, abre a pasta de downloads.", "open_folder"),
    ("Jarvis, fecha o navegador.", "close_app"),
    ("Jarvis, cancele a última ação.", "undo"),
    ("Jarvis, abre a planilha de pendências.", "excel_open"),
    ("Jarvis, verifica as entregas atrasadas.", "excel_pending"),
    ("Jarvis, procura o registro dessa nota fiscal.", "excel_search"),
    ("Jarvis, resume os dados dessa planilha.", "excel_summary"),
    ("Jarvis, quais são as pendências mais antigas?", "excel_pending"),
    ("Jarvis, localiza o nome de um cliente na planilha.", "excel_search"),
    ("Jarvis, tenho e-mails novos?", "email_unread"),
    ("Jarvis, quem me mandou e-mail hoje?", "email_senders"),
    ("Jarvis, resume os e-mails importantes.", "email_summary"),
    ("Jarvis, procura o último e-mail do meu gestor.", "email_search"),
    ("Jarvis, prepara uma resposta para esse e-mail.", "email_draft_reply"),
    ("Jarvis, quem me mandou mensagem?", "whatsapp_senders"),
    ("Jarvis, chegou alguma mensagem nova?", "messages_check"),
    ("Jarvis, quem falou comigo hoje?", "whatsapp_senders"),
    ("Jarvis, resume minhas mensagens não lidas.", "whatsapp_summary"),
    ("Jarvis, abre a conversa mais recente.", "whatsapp_open_chat"),
    ("Jarvis, prepara uma resposta para esse contato.", "whatsapp_draft_reply"),
    ("Jarvis, o que aconteceu enquanto eu estava ocupado?", "notifications_summary"),
    ("Jarvis, verifica minhas pendências.", "excel_pending"),
])
def test_requirement_examples(text, expected):
    assert parse(text)[0] == expected


@pytest.mark.parametrize("text,name,params", [
    ("abre o storm quatro", "open_target", {"target": "storm 4"}),
    ("volume em cinquenta por cento", "volume_set", {"level": 50}),
    ("diminui o volume em vinte", "volume_change", {"delta": -20}),
    ("muta o som", "volume_mute", {"mute": True}),
    ("tira do mudo", "volume_mute", {"mute": False}),
    ("muda para a voz da Friday", "set_profile", {"profile": "friday"}),
    ("volta pro jarvis", "set_profile", {"profile": "jarvis"}),
    ("fala mais devagar", "speech_rate", {"delta": -10}),
    ("fala mais alto", "speech_volume", {"delta": 10}),
    ("ativa o modo jogo", "game_mode", {"active": True}),
    ("desativa o modo jogo", "game_mode", {"active": False}),
    ("silencia as notificações por trinta minutos", "notifications_mute", {"minutes": 30}),
    ("volta pro chrome", "switch_window", {"target": "chrome"}),
    ("procura o arquivo contrato de aluguel", "file_search", {"query": "contrato de aluguel"}),
    ("fecha o chrome à força", "close_app", {"target": "chrome", "force": True}),
])
def test_parameters(text, name, params):
    got_name, got_params = parse(text)
    assert got_name == name
    for key, value in params.items():
        assert got_params[key] == value


def test_wake_up_does_not_capture_navigation():
    assert parse("volta pro chrome")[0] == "switch_window"
    assert parse("acorda")[0] == "wake_up"


def test_whatsapp_compose():
    name, params = parse("manda uma mensagem para a Ana dizendo que chego às cinco")
    assert name == "whatsapp_compose"
    assert params == {"contact": "ana", "text": "chego as cinco"}


def test_reminder_extracts_text_and_time():
    name, params = parse("me lembra de ligar para o João em dez minutos")
    assert name == "reminder_create"
    assert params["text"] == "ligar para o joao"
    assert params["when"]


def test_memory_vs_reminder():
    assert parse("lembra que meu gestor é o Carlos")[0] == "memory_add"
    assert parse("me lembra de pagar a conta amanhã às 9")[0] == "reminder_create"


def test_custom_command_has_priority():
    custom = IntentParser([{"phrases": ["modo trabalho"], "actions": []}])
    intent = custom.parse("modo trabalho")
    assert intent.name == "custom_command" and intent.params == {"index": 0}


def test_unknown_returns_none():
    assert parse("qual a capital da mongólia") == (None, {})


@pytest.mark.parametrize("text,expected", [
    ("sim", True), ("pode enviar", True), ("confirmo", True), ("não", False), ("cancela", False),
    ("talvez", None),
])
def test_yes_no(text, expected):
    assert parse_yes_no(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("vinte e cinco", "25"), ("as quinze e trinta", "as 15 e 30"), ("cento e vinte e tres", "123"),
    ("dois mil e quinhentos", "2500"), ("cem por cento", "100 por cento"), ("abre um arquivo", "abre um arquivo"),
])
def test_numbers(text, expected):
    assert words_to_digits(text) == expected


NOW = datetime(2026, 10, 29, 14, 0)


@pytest.mark.parametrize("text,expected", [
    ("em dez minutos", datetime(2026, 10, 29, 14, 10)),
    ("daqui a meia hora", datetime(2026, 10, 29, 14, 30)),
    ("daqui a uma hora e meia", datetime(2026, 10, 29, 15, 30)),
    ("as tres e meia", datetime(2026, 10, 29, 15, 30)),
    ("amanha as oito da manha", datetime(2026, 10, 30, 8, 0)),
    ("as 15:45", datetime(2026, 10, 29, 15, 45)),
    ("as 9 da noite", datetime(2026, 10, 29, 21, 0)),
    ("ao meio dia", datetime(2026, 10, 30, 12, 0)),
])
def test_parse_when(text, expected):
    assert parse_when(text, NOW)[0] == expected


def test_describe():
    assert describe(datetime(2026, 10, 29, 14, 10), NOW) == "em 10 minutos"
    assert describe(datetime(2026, 10, 30, 8, 0), NOW) == "amanhã às 08:00"


def test_recover_original_keeps_accents():
    assert recover_original("Jarvis, me lembra de ligar pro João", "ligar pro joao") == "ligar pro João"


def test_similar():
    assert similar("storm 4", "naruto shippuden ultimate ninja storm 4") > 0.8
    assert similar("excel", "steam") < 0.6
