from jarvis.actions.base import REGISTRY, ActionResult, PendingAction, action
from jarvis.brain.assistant import Assistant
from jarvis.brain.llm import AgentOutcome

calls = []


@action("test_risky", "Ação de teste que exige confirmação.", risk="confirm", llm=False,
        confirm_text=lambda p: "Confirma o teste?")
def _risky(services, params):
    calls.append("risky")
    return ActionResult("Teste executado.")


def test_confirmation_yes_and_no(services):
    assistant = Assistant(services)
    calls.clear()
    result = REGISTRY.run(services, "test_risky", {})
    assert result.pending and calls == []
    assistant._finish(result, "test_risky")
    assert assistant.handle("não", source="text").text == "Cancelado. Nada foi feito."
    assert calls == []
    assistant._finish(REGISTRY.run(services, "test_risky", {}), "test_risky")
    reply = assistant.handle("sim, pode", source="text")
    assert reply.text == "Teste executado." and calls == ["risky"]


def test_low_confidence_voice_asks_before_acting(services):
    assistant = Assistant(services)
    reply = assistant.handle("muda para a friday", source="voice", confidence=0.3)
    assert reply.intent == "confirm_low_confidence" and reply.expects_reply
    assert services.settings.get("voice.profile") == "jarvis"
    reply = assistant.handle("sim", source="voice", confidence=0.9)
    assert services.settings.get("voice.profile") == "friday"


def test_low_confidence_read_only_runs(services):
    assistant = Assistant(services)
    assert assistant.handle("que horas são", source="voice", confidence=0.2).intent == "time"


def test_undo_restores(services):
    assistant = Assistant(services)
    assistant.handle("muda para a friday", source="text")
    assert services.settings.get("voice.profile") == "friday"
    reply = assistant.handle("cancele a última ação", source="text")
    assert services.settings.get("voice.profile") == "jarvis"
    assert "restaurado" in reply.text
    assert "Não há ação" in assistant.handle("desfaz", source="text").text


def test_follow_up_receives_next_utterance(services):
    assistant = Assistant(services)
    received = []
    assistant._finish(ActionResult("O que devo responder?", follow_up=lambda t: (received.append(t),
                                                                                   ActionResult("Ok"))[1]), "x")
    reply = assistant.handle("Diga que chego amanhã", source="text")
    assert received == ["Diga que chego amanhã"] and reply.text == "Ok"


def test_reminder_flow_and_undo(services):
    assistant = Assistant(services)
    reply = assistant.handle("me lembra de beber água em 10 minutos", source="text")
    assert "beber água" in reply.text
    assert len(services.reminders.pending()) == 1
    assistant.handle("desfaz", source="text")
    assert services.reminders.pending() == []


def test_unknown_without_ai(services):
    reply = Assistant(services).handle("qual a capital da mongólia", source="text")
    assert not reply.ok and "Não reconheci" in reply.text


def test_unknown_goes_to_llm_and_pending_from_tool(services):
    class FakeLLM:
        def available(self):
            return True

        def chat(self, text, context, tools, execute_tool):
            assert any(t["name"] == "time" for t in tools)
            result = execute_tool("test_risky_llm", {})
            return AgentOutcome(text=result.say, pending=result.pending, expects_reply=True)

        def resolve_pending_tool(self, text):
            self.resolved = text

    @action("test_risky_llm", "teste", risk="confirm", confirm_text=lambda p: "Posso?")
    def _x(services, params):
        return ActionResult("feito pela IA")

    services.llm = FakeLLM()
    assistant = Assistant(services)
    reply = assistant.handle("faz aquela coisa complicada", source="text")
    assert reply.text == "Posso?" and assistant.pending is not None
    reply = assistant.handle("sim", source="text")
    assert reply.text == "feito pela IA"
    assert "confirmou" in services.llm.resolved


def test_ordinal_opens_file_from_context(services, tmp_path):
    target = tmp_path / "contrato.pdf"
    target.write_text("x")
    services.context.remember(files=[str(target)])
    reply = Assistant(services).handle("abre o primeiro", source="text")
    assert reply.ok and services.opened == [str(target)]


def test_change_of_subject_drops_pending(services):
    assistant = Assistant(services)
    assistant.pending = PendingAction(question="Enviar?", execute=lambda: ActionResult("enviado"))
    reply = assistant.handle("que horas são agora mesmo", source="text")
    assert assistant.pending is None and reply.intent == "time"


def test_game_mode_shortens_replies(services):
    assistant = Assistant(services)
    services.state.game_mode = True
    reply = assistant.handle("ativa o modo silencioso", source="text")
    assert reply.text == "Modo silencioso ativado."
