"""Motor da ferramenta HTML rodando dentro do JARVIS.

Usa a ferramenta real (referencia/roteirizacao_icaro.html), que fica só no PC do usuário
porque tem dados da filial; sem ela, os testes são pulados.
"""
from pathlib import Path

import openpyxl
import pytest

pytest.importorskip("py_mini_racer")
from jarvis.integrations.rota.jsengine import EngineError, RotaJS, extract_script, input_defaults  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "referencia" / "roteirizacao_icaro.html"
needs_tool = pytest.mark.skipif(not TOOL.exists(), reason="ferramenta da filial não está neste computador")

HEAD = ["Notas Fiscais", "N° CT-e", "Região de entrega", "CEP Destinatário", "Peso real", "Peso cubado", "Prazo entrega",
        "Remetente", "Cidade Destinatário", "Bairro Destinatário", "Endereço Destinátario", "Total Frete", "Volumes",
        "Destinatário", "Última ocorrência"]


def test_extract_and_defaults():
    html = ('<input id="fPeso" value="500"><input id="x" type="checkbox" checked><script src="lib.js"></script>'
            '<script>const DRIVERS=[];function assign(){}function buildMapping(){}function saveDay(){}</script>')
    assert "function assign(" in extract_script(html)
    values, checked = input_defaults(html)
    assert values["fPeso"] == "500" and checked["x"]
    with pytest.raises(EngineError):
        extract_script("<script>var a=1;</script>")


@needs_tool
def test_tool_runs_inside_jarvis(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEAD)
    ws.append(["100001", 1, "RIO-TJC-1", "20510000", 5, 5, "03/11/2026", "LOJA A", "Rio de Janeiro", "Tijuca", "Rua A, 1", 300, 1, "Ana", ""])
    ws.append(["100002", 2, "RIO-INTERIOR", "27000000", 5, 5, "03/11/2026", "LOJA A", "Volta Redonda", "Centro", "Rua B, 2", 50, 1, "Bia", ""])
    ws.append(["100003", 3, "RIO-NOR-3", "26530000", 5, 5, "03/11/2026", "LOJA A", "Nilópolis", "Centro", "Rua C, 3", 50, 1, "Caio", ""])
    path = tmp_path / "fretes.xlsx"
    wb.save(path)
    store = tmp_path / "store.json"
    engine = RotaJS(TOOL, store)
    try:
        assert engine.load("no_rj", [path])["ok"] and engine.status()["ok"]
        result = engine.assign("2026-11-03")
        cargas = {m["nome"]: [n["nf"] for n in m["notas"]] for m in result["manifests"] if m["notas"]}
        assert ["100001"] in cargas.values()
        assert {n["nf"] for n in result["foraFilial"]} == {"100002", "100003"}
        nome, data = engine.excel()
        assert data[:2] == b"PK" and nome.endswith(".xlsx")
        pdfs = engine.circuit()
        assert pdfs and pdfs[0][2][:5] == b"%PDF-"
        assert engine.logs() == []
    finally:
        engine.close()
    again = RotaJS(TOOL, store)
    try:
        restored = again.restore_day()
        assert restored and restored["data"] == "2026-11-03"
    finally:
        again.close()


# ------------------------------------------------------------- comandos de voz
def test_parse_day_next_business_day():
    from datetime import date

    from jarvis.integrations.rota.service import next_business_day, parse_day

    assert next_business_day(date(2026, 10, 30)) == date(2026, 11, 2)  # sexta -> segunda
    assert parse_day("monta a rota", date(2026, 10, 29)) == date(2026, 10, 30)
    assert parse_day("monta a rota de hoje", date(2026, 10, 29)) == date(2026, 10, 29)
    assert parse_day("rota de segunda", date(2026, 10, 29)) == date(2026, 11, 2)


@pytest.mark.parametrize("phrase,name,params", [
    ("monta a rota", "rota_montar", None),
    ("o Ronald não vai hoje", "rota_ausente", {"driver": "ronald"}),
    ("move a nota 55501234 para o Deusereis", "rota_mover_nota", {"nf": "55501234", "driver": "deusereis"}),
    ("troca a rota do Marcos com a do Ronald", "rota_trocar", {"a": "marcos", "b": "ronald"}),
    ("realoca o Jeferson para OES 1", "rota_realocar", {"driver": "jeferson", "region": "oes 1"}),
    ("gera os PDFs do Circuit", "rota_circuit", {"driver": ""}),
    ("gera o excel da rota", "rota_excel", {}),
    ("abre o mapa da rota", "rota_abrir", {"what": "ferramenta"}),
])
def test_rota_phrases(phrase, name, params):
    from jarvis.nlu.intents import IntentParser

    intent = IntentParser().parse(phrase)
    assert intent is not None and intent.name == name
    if params is not None:
        assert intent.params == params


@needs_tool
def test_voice_flow_with_tool(services, tmp_path, monkeypatch):
    from jarvis.actions.base import REGISTRY
    from jarvis.integrations.rota import service as rota_service
    from jarvis.integrations.rota.reader import FOLDERS

    folder = tmp_path / "rotas"
    services.settings.set("rota.folder", str(folder))
    svc = rota_service.RotaService(services.settings, services.bus)
    services.extras["rota"] = svc
    try:
        res = REGISTRY.run(services, "rota_montar", {})
        assert not res.ok and "Não encontrei planilhas" in res.say
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(HEAD)
        ws.append(["100001", 1, "RIO-TJC-1", "20510000", 5, 5, "03/11/2026", "LOJA A", "Rio de Janeiro", "Tijuca", "Rua A, 1", 900, 2, "Ana", ""])
        ws.append(["100002", 2, "RIO-SUL-1", "22041000", 5, 5, "03/11/2026", "LOJA B", "Rio de Janeiro", "Copacabana", "Rua B, 2", 900, 1, "Bia", ""])
        (folder / FOLDERS["no_rj"]).mkdir(parents=True, exist_ok=True)
        wb.save(folder / FOLDERS["no_rj"] / "fretes.xlsx")
        res = REGISTRY.run(services, "rota_montar", {"day": "terça"})
        assert res.ok, res.say
        assert "2 notas em 2 rotas" in res.say and "Motorista · Região" in res.display
        tjc = next(m for m in svc.result["manifests"] if m["notas"] and m["notas"][0]["nf"] == "100001")
        sul = next(m for m in svc.result["manifests"] if m["notas"] and m["notas"][0]["nf"] == "100002")
        nome_tjc, nome_sul = tjc["nome"].split()[0].lower(), sul["nome"].split()[0].lower()
        res = REGISTRY.run(services, "rota_motorista", {"driver": nome_tjc})
        assert res.ok and "1 nota" in res.say and "% do frete" in res.say
        assert REGISTRY.run(services, "rota_mover_nota", {"nf": "100001", "driver": nome_sul}).ok
        assert len(svc.manifest(sul["idx"])["notas"]) == 2
        assert REGISTRY.run(services, "rota_ausente", {"driver": nome_sul}).ok
        assert len(svc.result["fora"]) == 2
        assert REGISTRY.run(services, "rota_ausente", {"driver": nome_sul, "present": True}).ok
        assert REGISTRY.run(services, "rota_remover_nota", {"nf": "100002"}).ok
        assert REGISTRY.run(services, "rota_remover_nota", {"nf": "100002", "restore": True}).ok
        res = REGISTRY.run(services, "rota_excel", {})
        assert res.ok and svc.excel_path.exists() and services.opened[-1] == str(svc.excel_path)
        res = REGISTRY.run(services, "rota_circuit", {})
        assert res.ok and list(svc.circuit_dir.glob("*.pdf"))
        assert not REGISTRY.run(services, "rota_motorista", {"driver": "fulano"}).ok
    finally:
        svc.close()
    again = rota_service.RotaService(services.settings, services.bus)
    try:
        assert again.restore() and again.allocated() == 2  # rota do dia volta ao abrir
    finally:
        again.close()
