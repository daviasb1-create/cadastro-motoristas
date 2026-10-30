import json
import zipfile
from datetime import date
from io import BytesIO

import httpx
import pytest

from jarvis.brain.assistant import Assistant
from jarvis.integrations.excel_analysis import Table, col_index, col_letter, guess_columns, parse_address, to_date, to_number
from jarvis.integrations.msgraph.client import GraphClient
from jarvis.integrations.msgraph.excel import ExcelService, minimal_xlsx, share_id

VALUES = [
    ["Controle de entregas", "", "", "", ""],
    ["NF", "Cliente", "Status", "Prazo", "Valor"],
    [1001, "Mercado Sol", "Pendente", 46300, "1.250,00"],
    [1002, "Farmácia Luz", "Entregue", "05/10/2026", 300],
    [1003, "Padaria Pão", "pendente", "01/10/2026", 80.5],
    [1004, "Mercado Sol", "Em rota", "", 99],
    ["", "", "", "", ""],
]


def table():
    return Table.from_values(VALUES, "Planilha1!B2:F8")


def test_addresses():
    assert col_letter(0) == "A" and col_letter(25) == "Z" and col_letter(27) == "AB"
    assert col_index("AB") == 27
    assert parse_address("'Minha aba'!C5:H9") == ("Minha aba", 5, 2)


def test_conversions():
    assert to_date(46300) == date(2026, 10, 5)
    assert to_date("05/10/2026") == date(2026, 10, 5)
    assert to_date("2026-10-05T00:00:00") == date(2026, 10, 5)
    assert to_number("1.250,00") == 1250.0 and to_number("abc") is None


def test_header_detection_and_cells():
    t = table()
    assert t.headers == ["NF", "Cliente", "Status", "Prazo", "Valor"]
    assert [r.index for r in t.rows] == [4, 5, 6, 7]
    assert t.cell_address(t.rows[0], 2) == "D4"


def test_pending_overdue_oldest():
    t = table()
    pending = t.pending("status", ["pendente"])
    assert [r.get(0) for r in pending] == [1001, 1003]
    done_based = t.pending("Status", done_values=["entregue"])
    assert [r.get(0) for r in done_based] == [1001, 1003, 1004]
    overdue = t.overdue(pending, "prazo", today=date(2026, 10, 2))
    assert [r.get(0) for r in overdue] == [1003]
    oldest = t.sort_by_date(pending, "Prazo")
    assert oldest[0].get(0) == 1003
    with pytest.raises(ValueError):
        t.pending("inexistente")


def test_search_and_summary_and_inconsistencies():
    t = table()
    assert [r.get(0) for r in t.search("mercado sol")] == [1001, 1004]
    assert [r.get(0) for r in t.search("nota fiscal 1003")] == [1003]
    info = t.summary("Status", "Prazo")
    assert info["rows"] == 4 and ("Valor", pytest.approx(1729.5)) in info["totals"]
    issues = t.inconsistencies(["Cliente"], "Prazo")
    assert any("repetido" in i for i in issues)


def test_guess_columns_only_suggests():
    guesses = guess_columns(["NF", "Cliente", "Situação", "Data de entrega"])
    assert guesses["status"] == ["Situação"] and guesses["date"] == ["Data de entrega"]


def test_minimal_xlsx_is_valid_zip():
    data = minimal_xlsx(["Nome", "Status"])
    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert "xl/workbook.xml" in zf.namelist()
        assert "Status" in zf.read("xl/worksheets/sheet1.xml").decode()


def test_share_id():
    assert share_id("https://x.sharepoint.com/a").startswith("u!") and "=" not in share_id("https://a")


class FakeAuth:
    configured = True

    def is_signed_in(self):
        return True

    def get_token(self, force_refresh=False):
        return "token"


def make_service(services, handler):
    client = GraphClient(FakeAuth(), transport=httpx.MockTransport(handler))
    svc = ExcelService(client, FakeAuth(), services.settings, services.storage, services.bus)
    services.excel = svc
    services.settings.set("excel.workbooks", [{
        "alias": "entregas", "name": "Entregas.xlsx", "drive_id": "d1", "item_id": "i1", "web_url": "https://x/e",
        "sheet": "Planilha1", "header_row": None, "status_column": "Status", "pending_values": ["pendente"],
        "done_values": [], "date_column": "Prazo", "key_columns": ["NF", "Cliente"], "watch": False}])
    return svc


def test_service_pending_search_and_write_with_confirmation(services):
    writes = []
    cell = {"D7": "Em rota"}

    def handler(request: httpx.Request):
        path = request.url.path
        if "usedRange" in path:
            return httpx.Response(200, json={"address": "Planilha1!B2:F8", "values": VALUES})
        if "range(address='D7')" in path and request.method == "GET":
            return httpx.Response(200, json={"values": [[cell["D7"]]]})
        if "range(address='D7')" in path and request.method == "PATCH":
            body = json.loads(request.content)
            writes.append(body)
            cell["D7"] = body["values"][0][0]
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": {"code": "itemNotFound"}})

    make_service(services, handler)
    assistant = Assistant(services)
    reply = assistant.handle("verifica minhas pendências", source="text")
    assert reply.text.startswith("2 pendências na planilha entregas")
    reply = assistant.handle("quais delas são mais antigas?", source="text")
    assert "mais antigas" in reply.text and reply.text.index("1003") < reply.text.index("1001")
    reply = assistant.handle("procura a nota fiscal 1004", source="text")
    assert "Linha 7" in reply.text

    from jarvis.actions.base import REGISTRY

    result = REGISTRY.run(services, "excel_set_value", {"row_query": "1004", "column": "status", "value": "Entregue"})
    assert result.pending and writes == []  # nada gravado antes da confirmação
    assert "Em rota" in result.display and "Entregue" in result.display
    done = result.pending.execute()
    assert done.ok and writes == [{"values": [["Entregue"]]}]
    audit = services.storage.query("SELECT * FROM excel_audit")
    assert audit[0]["address"] == "D7" and audit[0]["status"] == "ok"
    assert done.undo() == "Alteração desfeita na planilha." and cell["D7"] == "Em rota"


def test_service_requires_configuration(services):
    make_service(services, lambda r: httpx.Response(500))
    services.settings.set("excel.workbooks", [])
    reply = Assistant(services).handle("verifica minhas pendências", source="text")
    assert "Nenhuma planilha configurada" in reply.text
