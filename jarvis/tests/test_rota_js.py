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
