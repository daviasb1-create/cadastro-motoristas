import time
from types import SimpleNamespace

from jarvis.actions.base import ActionResult, PendingAction
from jarvis.brain.llm import LLMClient
from jarvis.brain.services import RuntimeState
from jarvis.core.config import Settings
from jarvis.core.events import EventBus
from jarvis.voice.pipeline import VoicePipeline

from fakes import FakeMic, FakeSpeaker, FakeSTT, FakeWake, silence_frame, speech_frame

MARKER = speech_frame(4001)


def run_pipeline(home, text, frames, after=1, expects_reply=False, speaking=False):
    settings = Settings(home / "s.json")
    mic, speaker, got = FakeMic(realtime=True), FakeSpeaker(), []
    if speaking:
        speaker.speaking.set()

    def handler(t, conf, source):
        got.append(t)
        return SimpleNamespace(text="resposta", speak=True, expects_reply=expects_reply)

    pipeline = VoicePipeline(settings, EventBus(), RuntimeState(), speaker, mic, lambda: FakeWake(MARKER),
                             FakeSTT(text, after_frames=after), handler)
    pipeline.start()
    mic.push(frames)
    time.sleep(len(frames) * 0.05 + 1.2)
    pipeline.stop()
    return got, speaker


def test_continuous_command_without_pause(home):
    frames = [silence_frame()] * 4 + [speech_frame()] * 6 + [MARKER] + [speech_frame()] * 12 + [silence_frame()] * 25
    got, speaker = run_pipeline(home, "jarvis abre o navegador", frames)
    assert got == ["abre o navegador"]
    assert speaker.said == ["resposta"]  # sem "Às suas ordens" no meio


def test_wake_word_alone_acknowledges(home):
    frames = [silence_frame()] * 4 + [speech_frame()] * 6 + [MARKER] + [silence_frame()] * 150
    got, speaker = run_pipeline(home, "", frames)
    assert got == [] and len(speaker.said) == 1
    assert speaker.said[0] in Settings(home / "s.json").get("profiles.jarvis.acks")


def test_barge_in_stops_speech(home):
    frames = [speech_frame()] * 6 + [MARKER] + [speech_frame()] * 6 + [silence_frame()] * 25
    got, speaker = run_pipeline(home, "pare", frames, speaking=True)
    assert speaker.stops >= 1 and got == ["pare"]


def test_mic_disabled_ignores_audio(home):
    settings = Settings(home / "s.json")
    mic, speaker, got = FakeMic(), FakeSpeaker(), []
    pipeline = VoicePipeline(settings, EventBus(), RuntimeState(), speaker, mic, lambda: FakeWake(MARKER),
                             FakeSTT("abre"), lambda *a: got.append(a))
    pipeline.set_mic_enabled(False)
    pipeline.start()
    mic.push([speech_frame()] * 5 + [MARKER] + [speech_frame()] * 5 + [silence_frame()] * 20)
    time.sleep(1.5)
    pipeline.stop()
    assert got == []


# ------------------------------------------------------------------ IA
class Block(SimpleNamespace):
    pass


class FakeAnthropic:
    """Simula respostas do Messages API (blocos text/tool_use)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        return self.responses.pop(0)


def response(stop, *blocks):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


def test_llm_tool_loop_with_confirmation_resume(home):
    from tests_secrets import MemorySecrets

    settings = Settings(home / "s.json")
    settings.set("ai.provider", "anthropic")
    secrets = MemorySecrets()
    secrets.set("anthropic_api_key", "sk-test")
    client = LLMClient(settings, secrets)
    fake = FakeAnthropic([
        response("tool_use", Block(type="text", text="Vou verificar."),
                 Block(type="tool_use", id="t1", name="time", input={}),
                 Block(type="tool_use", id="t2", name="danger", input={"x": 1})),
        response("end_turn", Block(type="text", text="Pronto, enviado.")),
    ])
    client._anthropic_create = fake
    executed = []

    def execute(name, params):
        executed.append(name)
        if name == "danger":
            return ActionResult("Confirma?", pending=PendingAction("Confirma?", lambda: ActionResult("ok")))
        return ActionResult("São 10 horas.")

    outcome = client.chat("faz algo", "contexto", [{"name": "time"}], execute)
    assert outcome.pending is not None and outcome.text == "Confirma?" and executed == ["time", "danger"]
    client.resolve_pending_tool("Usuário confirmou. Resultado: enviado")
    outcome = client.chat("sim", "contexto", [], execute)
    assert outcome.text == "Pronto, enviado."
    # a 2ª requisição começa com os tool_results das duas ferramentas, na ordem
    second = fake.requests[1]["messages"][-1]["content"]
    assert [c.get("tool_use_id") for c in second[:2]] == ["t1", "t2"]
    assert "confirmou" in second[1]["content"]
    # histórico só cresce (nenhuma mensagem anterior foi alterada)
    assert fake.requests[1]["messages"][0] is fake.requests[0]["messages"][0]


def test_llm_refusal_and_unavailable(home):
    from tests_secrets import MemorySecrets

    settings = Settings(home / "s.json")
    client = LLMClient(settings, MemorySecrets())
    assert not client.available() and client.complete("x") is None
    settings.set("ai.provider", "anthropic")
    client.secrets.set("anthropic_api_key", "k")
    client._anthropic_create = FakeAnthropic([response("refusal")])
    assert client.chat("x", "", [], lambda *a: None).text == "Não posso ajudar com esse pedido."


def test_non_streaming_stt_keeps_command_said_in_one_breath(home):
    """Whisper não tem parciais: a fala após a ativação deve contar como comando (sem 'Às suas ordens')."""
    settings = Settings(home / "s.json")
    mic, speaker, got = FakeMic(realtime=True), FakeSpeaker(), []
    stt = FakeSTT("abre o navegador", after_frames=1)
    stt.streaming = False
    original = stt.session

    def session():
        s = original()
        s.partial = lambda: ""  # sem resultados parciais
        return s

    stt.session = session
    pipeline = VoicePipeline(settings, EventBus(), RuntimeState(), speaker, mic, lambda: FakeWake(MARKER), stt,
                             lambda t, c, src: got.append(t) or SimpleNamespace(text="", speak=False, expects_reply=False))
    pipeline.start()
    frames = [speech_frame()] * 4 + [MARKER] + [silence_frame()] * 4 + [speech_frame()] * 14 + [silence_frame()] * 30
    mic.push(frames)
    time.sleep(len(frames) * 0.05 + 1.2)
    pipeline.stop()
    assert got == ["abre o navegador"] and speaker.said == []


def test_voice_loop_survives_exceptions_and_dead_mic(home):
    settings = Settings(home / "s.json")

    class FlakyWake(FakeWake):
        def __init__(self):
            super().__init__(MARKER)
            self.calls = 0

        def process(self, frame):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("falha simulada")
            return super().process(frame)

    class DeadMic(FakeMic):
        def read(self, timeout=0.5):
            return None if self.opened == 1 else super().read(timeout)

    mic, got = DeadMic(realtime=True), []
    pipeline = VoicePipeline(settings, EventBus(), RuntimeState(), FakeSpeaker(), mic, FlakyWake, FakeSTT("que horas sao"),
                             lambda t, c, src: got.append(t) or SimpleNamespace(text="", speak=False, expects_reply=False))
    pipeline.start()
    time.sleep(1.0)  # ~10 leituras vazias: o microfone é reaberto
    assert mic.opened >= 2
    frames = [speech_frame()] * 4 + [speech_frame()] + [speech_frame()] * 2 + [MARKER] + [speech_frame()] * 10 + [silence_frame()] * 25
    mic.push(frames)
    time.sleep(len(frames) * 0.05 + 1.5)
    pipeline.stop()
    assert got == ["que horas sao"]


def test_general_question_uses_web_search_and_resumes_pause(home):
    from tests_secrets import MemorySecrets

    settings = Settings(home / "s.json")
    settings.set("ai.provider", "anthropic")
    client = LLMClient(settings, MemorySecrets())
    client.secrets.set("anthropic_api_key", "k")
    fake = FakeAnthropic([
        response("pause_turn", Block(type="server_tool_use", id="s1", name="web_search", input={"query": "dólar hoje"})),
        response("end_turn", Block(type="text", text="O dólar fechou a 5 reais, segundo o Banco Central.")),
    ])
    client._anthropic_create = fake
    outcome = client.chat("quanto está o dólar hoje?", "", [{"name": "time"}], lambda *a: None)
    assert outcome.text.startswith("O dólar fechou")
    tools = fake.requests[0]["tools"]
    assert tools[-1]["type"] == "web_search_20260209" and tools[-1]["user_location"]["country"] == "BR"
    assert len(fake.requests) == 2  # retomou após pause_turn sem nova mensagem do usuário
    assert fake.requests[1]["messages"][-1]["role"] == "assistant"
    settings.set("ai.anthropic_model", "claude-haiku-5-5")
    assert client._server_tools()[0]["type"] == "web_search_20250305"
    settings.set("ai.web_search", False)
    assert client._server_tools() == []
