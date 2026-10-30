"""Excel Online (Microsoft Graph + Excel REST API).

* Trabalha direto nos arquivos reais do OneDrive/SharePoint, sem cópias.
* Leitura: intervalo usado da aba configurada (cache de 60 s).
* Escrita: somente após confirmação, com prévia "antes -> depois" e registro
  em auditoria (tabela excel_audit), permitindo desfazer.
* Novas planilhas só são criadas quando o usuário pede.
"""
from __future__ import annotations

import base64
import io
import logging
import threading
import time
import zipfile

from typing import Any
from xml.sax.saxutils import escape

from ...actions.base import STR, ActionResult, PendingAction, ServiceUnavailable, action, props
from ...nlu.normalize import normalize, similar
from ..excel_analysis import Table, _fmt, guess_columns

log = logging.getLogger(__name__)
EXCEL_EXT = (".xlsx", ".xlsm", ".xlsb")


def share_id(url: str) -> str:
    """Codifica um link de compartilhamento no formato exigido por /shares/{id}."""
    encoded = base64.urlsafe_b64encode(url.strip().encode("utf-8")).decode("ascii").rstrip("=")
    return "u!" + encoded


class ExcelService:
    def __init__(self, client, auth, settings, storage, bus, notifications=None, llm=None) -> None:
        self.client = client
        self.auth = auth
        self.settings = settings
        self.storage = storage
        self.bus = bus
        self.notifications = notifications
        self.llm = llm
        self._cache: dict[str, tuple[float, Table]] = {}
        self._stop = threading.Event()

    # ---------------------------------------------------------- disponibilidade
    def _require(self) -> None:
        if not self.auth.configured:
            raise ServiceUnavailable("O Excel Online ainda não foi configurado. Abra Configurações > Microsoft 365.")
        if not self.settings.get("microsoft.features.excel", True):
            raise ServiceUnavailable("A integração com planilhas está desativada nas configurações.")
        if not self.auth.is_signed_in():
            raise ServiceUnavailable("Sua conta Microsoft não está conectada. Use Configurações > Microsoft 365 > Conectar.")

    def workbooks(self) -> list[dict]:
        return self.settings.get("excel.workbooks", []) or []

    # -------------------------------------------------------------- descoberta
    def discover(self, limit: int = 60) -> list[dict]:
        """Planilhas acessíveis: pesquisa no OneDrive, recentes e compartilhadas comigo."""
        self._require()
        found: dict[str, dict] = {}

        def add(item: dict) -> None:
            remote = item.get("remoteItem") or {}
            name = item.get("name") or remote.get("name") or ""
            if not name.lower().endswith(EXCEL_EXT):
                return
            ref = (remote.get("parentReference") or item.get("parentReference") or {})
            drive_id = ref.get("driveId")
            item_id = remote.get("id") or item.get("id")
            if not drive_id or not item_id:
                return
            found[f"{drive_id}:{item_id}"] = {
                "name": name, "drive_id": drive_id, "item_id": item_id,
                "web_url": item.get("webUrl") or remote.get("webUrl", ""),
                "modified": item.get("lastModifiedDateTime") or remote.get("lastModifiedDateTime", ""),
                "location": ref.get("path", "").replace("/drive/root:", "") or "Compartilhado",
            }

        for path in ("/me/drive/root/search(q='.xlsx')", "/me/drive/recent"):
            try:
                for item in self.client.get_all(path, limit=limit):
                    add(item)
            except ServiceUnavailable as exc:
                log.info("Busca de planilhas em %s falhou: %s", path, exc)
        try:
            for item in self.client.get_all("/me/drive/sharedWithMe", limit=limit):
                add(item)
        except ServiceUnavailable:
            log.info("sharedWithMe indisponível para esta conta")
        return sorted(found.values(), key=lambda w: w.get("modified", ""), reverse=True)

    def resolve_url(self, url: str) -> dict:
        """Aceita o link 'Compartilhar/Copiar link' de uma planilha."""
        self._require()
        item = self.client.get(f"/shares/{share_id(url)}/driveItem")
        return {"name": item.get("name", "Planilha"), "drive_id": item["parentReference"]["driveId"],
                "item_id": item["id"], "web_url": item.get("webUrl", url)}

    def add_workbook(self, info: dict, alias: str = "") -> dict:
        entry = {
            "alias": alias or info["name"].rsplit(".", 1)[0], "name": info["name"],
            "drive_id": info["drive_id"], "item_id": info["item_id"], "web_url": info.get("web_url", ""),
            "sheet": "", "header_row": None, "status_column": "", "pending_values": [], "done_values": [],
            "date_column": "", "key_columns": [], "watch": False,
        }
        books = [w for w in self.workbooks() if w.get("item_id") != entry["item_id"]]
        books.append(entry)
        self.settings.set("excel.workbooks", books)
        return entry

    def update_workbook(self, item_id: str, changes: dict) -> None:
        books = self.workbooks()
        for book in books:
            if book.get("item_id") == item_id:
                book.update(changes)
        self.settings.set("excel.workbooks", books)
        self._cache.pop(item_id, None)

    def remove_workbook(self, item_id: str) -> None:
        self.settings.set("excel.workbooks", [w for w in self.workbooks() if w.get("item_id") != item_id])

    def find_workbook(self, name: str, strict: bool = False, context=None) -> dict | None:
        books = self.workbooks()
        if not books:
            return None
        target = normalize(name or "")
        if target:
            scored = []
            for book in books:
                score = max(similar(target, normalize(book.get("alias", ""))),
                            similar(target, normalize(book.get("name", "").rsplit(".", 1)[0])))
                scored.append((score, book))
            scored.sort(key=lambda s: s[0], reverse=True)
            if scored[0][0] >= (0.75 if strict else 0.6):
                return scored[0][1]
            if strict:
                return None
        if context is not None:
            last = context.get("workbook")
            if last:
                for book in books:
                    if book.get("item_id") == last.get("item_id"):
                        return book
        if not strict and len(books) == 1:
            return books[0]
        return None

    # ---------------------------------------------------------------- leitura
    def _base(self, wb: dict) -> str:
        return f"/drives/{wb['drive_id']}/items/{wb['item_id']}"

    def worksheets(self, wb: dict) -> list[str]:
        self._require()
        data = self.client.get(f"{self._base(wb)}/workbook/worksheets", params={"$select": "name,visibility"})
        return [w["name"] for w in data.get("value", []) if w.get("visibility", "Visible") == "Visible"]

    def table(self, wb: dict, sheet: str | None = None, fresh: bool = False) -> Table:
        self._require()
        sheet = sheet or wb.get("sheet") or ""
        key = f"{wb['item_id']}|{sheet}"
        cached = self._cache.get(key)
        if cached and not fresh and time.time() - cached[0] < 60:
            return cached[1]
        if not sheet:
            sheets = self.worksheets(wb)
            if not sheets:
                raise ServiceUnavailable("Essa planilha não tem abas visíveis.")
            sheet = sheets[0]
        quoted = sheet.replace("'", "''")
        data = self.client.get(f"{self._base(wb)}/workbook/worksheets('{quoted}')/usedRange(valuesOnly=true)",
                               params={"$select": "address,values"})
        table = Table.from_values(data.get("values") or [], data.get("address", "A1"), sheet, wb.get("header_row"))
        self._cache[key] = (time.time(), table)
        return table

    def read_cell(self, wb: dict, sheet: str, address: str) -> Any:
        quoted = sheet.replace("'", "''")
        data = self.client.get(f"{self._base(wb)}/workbook/worksheets('{quoted}')/range(address='{address}')",
                               params={"$select": "values"})
        values = data.get("values") or [[None]]
        return values[0][0] if values and values[0] else None

    # ---------------------------------------------------------------- escrita
    def write_range(self, wb: dict, sheet: str, address: str, values: list[list[Any]], before: Any) -> None:
        self._require()
        quoted = sheet.replace("'", "''")
        status = "ok"
        try:
            self.client.patch(f"{self._base(wb)}/workbook/worksheets('{quoted}')/range(address='{address}')",
                              json={"values": values})
        except Exception:
            status = "erro"
            raise
        finally:
            self.storage.execute(
                "INSERT INTO excel_audit(ts, workbook, sheet, address, before, after, status) VALUES (?,?,?,?,?,?,?)",
                (time.time(), wb.get("name", ""), sheet, address, repr(before), repr(values), status))
            self._cache.clear()

    def create_workbook(self, name: str, headers: list[str]) -> dict:
        self._require()
        if not name.lower().endswith(".xlsx"):
            name += ".xlsx"
        return self._upload(name, minimal_xlsx(headers))

    def _upload(self, name: str, content: bytes) -> dict:
        token = self.auth.get_token()
        response = self.client._http.put(
            f"/me/drive/root:/{name}:/content", params={"@microsoft.graph.conflictBehavior": "fail"},
            content=content, headers={"Authorization": f"Bearer {token}",
                                      "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
        if response.status_code == 409:
            raise ServiceUnavailable(f"Já existe um arquivo chamado {name}. Nada foi substituído.")
        if response.status_code >= 400:
            raise ServiceUnavailable(f"Não consegui criar a planilha (erro {response.status_code}).")
        return response.json()

    # ----------------------------------------------------------- abrir / vigiar
    def open_workbook(self, wb: dict, services=None) -> ActionResult:
        url = wb.get("web_url")
        if not url:
            return ActionResult.fail("Não tenho o endereço dessa planilha.")
        opener = getattr(services, "open_url", None) if services else None
        if opener:
            opener(url)
        else:
            import webbrowser

            webbrowser.open(url)
        if services is not None:
            services.context.remember(workbook=_wb_ref(wb))
        return ActionResult(f"Abrindo a planilha {wb.get('alias') or wb.get('name')}.")

    def start_watch(self) -> None:
        threading.Thread(target=self._watch_loop, name="excel-watch", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _watch_loop(self) -> None:
        while not self._stop.wait(max(2, int(self.settings.get("excel.watch_minutes", 10))) * 60):
            for wb in self.workbooks():
                if not wb.get("watch") or not wb.get("status_column"):
                    continue
                try:
                    table = self.table(wb, fresh=True)
                    count = len(table.pending(wb["status_column"], wb.get("pending_values"), wb.get("done_values")))
                    key = f"excel.pending.{wb['item_id']}"
                    previous = self.storage.kv_get(key)
                    self.storage.kv_set(key, count)
                    if previous is not None and count > previous and self.notifications:
                        self.notifications.add(
                            source="excel", app="Excel", sender=wb.get("alias", ""),
                            title=f"{count - previous} nova(s) pendência(s)",
                            body=f"A planilha {wb.get('alias')} agora tem {count} pendências.",
                            key=f"excel:{wb['item_id']}:{count}:{int(time.time() // 3600)}", link=wb.get("web_url"))
                    self.bus.publish("connection", service="excel", status="ok", detail="Conectado")
                except ServiceUnavailable as exc:
                    self.bus.publish("connection", service="excel", status="error", detail=str(exc)[:80])
                except Exception:  # noqa: BLE001
                    log.exception("Falha ao vigiar planilha")


def _wb_ref(wb: dict) -> dict:
    return {k: wb.get(k) for k in ("alias", "name", "item_id", "drive_id", "web_url")}


def minimal_xlsx(headers: list[str]) -> bytes:
    """Gera um .xlsx válido mínimo (uma aba, cabeçalho opcional) só com a biblioteca padrão."""
    cells = "".join(
        f'<c r="{chr(65 + i)}1" t="inlineStr"><is><t>{escape(h)}</t></is></c>' for i, h in enumerate(headers[:26]))
    sheet_data = f'<row r="1">{cells}</row>' if headers else ""
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Planilha1" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{sheet_data}</sheetData></worksheet>'),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


# ===================================================================== ações
def _svc(services) -> ExcelService:
    if services.excel is None:
        raise ServiceUnavailable("Integração com o Excel indisponível.")
    return services.excel


def _pick(services, name: str) -> dict:
    svc = _svc(services)
    svc._require()
    if not svc.workbooks():
        raise ServiceUnavailable("Nenhuma planilha configurada. Em Configurações > Planilhas, escolha quais devo usar.")
    wb = svc.find_workbook(name, context=services.context)
    if wb is None:
        names = ", ".join(w.get("alias", "") for w in svc.workbooks()[:5])
        raise ServiceUnavailable(f"Qual planilha? As configuradas são: {names}.")
    services.context.remember(workbook=_wb_ref(wb))
    return wb


def _rows_listing(table: Table, rows, wb: dict, limit: int = 15) -> str:
    out = []
    for row in rows[:limit]:
        out.append(f"Linha {row.index}: " + " | ".join(f"{k}: {_fmt(v)}" for k, v in list(row.as_dict().items())[:6]))
    if len(rows) > limit:
        out.append(f"… e mais {len(rows) - limit} linhas.")
    return "\n".join(out)


def _remember_rows(services, table: Table, rows) -> None:
    services.context.remember(rows=[{"linha": r.index, **{k: _fmt(v) for k, v in r.as_dict().items()}} for r in rows[:15]],
                              sheet=table.sheet)


@action("excel_list", "Lista as planilhas configuradas para uso do assistente.")
def excel_list(services, params):
    books = _svc(services).workbooks()
    if not books:
        return ActionResult("Nenhuma planilha configurada ainda. Em Configurações > Planilhas, escolha as que devo usar.")
    names = [b.get("alias") or b.get("name") for b in books]
    return ActionResult(f"{len(books)} planilhas configuradas: {', '.join(names[:6])}.", display="\n".join(names))


@action("excel_open", "Abre no navegador uma planilha configurada (ou a planilha em contexto).",
        props(workbook=STR | {"description": "Apelido ou nome da planilha; vazio = planilha em contexto."}))
def excel_open(services, params):
    svc = _svc(services)
    wb = svc.find_workbook(params.get("workbook", ""), context=services.context)
    if wb is None:
        if not svc.workbooks():
            if services.open_url:
                services.open_url("https://www.office.com/launch/excel")
            return ActionResult("Abrindo o Excel Online. Para eu abrir planilhas pelo nome, configure-as em Configurações > Planilhas.")
        return ActionResult.fail(f"Não encontrei a planilha {params.get('workbook', '')} entre as configuradas.")
    return svc.open_workbook(wb, services)


@action("excel_pending", "Lista pendências (linhas com status pendente) de uma planilha; pode filtrar atrasadas ou ordenar pelas mais antigas.",
        props(workbook=STR, oldest={"type": "boolean"}, overdue={"type": "boolean"}))
def excel_pending(services, params):
    svc = _svc(services)
    wb = _pick(services, params.get("workbook", ""))
    if not wb.get("status_column"):
        return ActionResult.fail(
            f"Ainda não sei qual coluna indica pendência na planilha {wb.get('alias')}. Configure em Configurações > Planilhas.")
    table = svc.table(wb)
    rows = table.pending(wb["status_column"], wb.get("pending_values"), wb.get("done_values"))
    label = "pendências"
    if params.get("overdue"):
        if not wb.get("date_column"):
            return ActionResult.fail("Para saber o que está atrasado, configure a coluna de prazo dessa planilha.")
        rows = table.overdue(rows, wb["date_column"])
        label = "pendências atrasadas"
    if params.get("oldest") or params.get("overdue"):
        rows = table.sort_by_date(rows, wb.get("date_column"), ascending=True)
    _remember_rows(services, table, rows)
    services.context.set_intent("excel_pending", params)
    if not rows:
        return ActionResult(f"Nenhuma {label[:-1] if label.endswith('s') else label} na planilha {wb.get('alias')}.")
    keys = wb.get("key_columns")
    top = "; ".join(table.label(r, keys) for r in rows[:3])
    prefix = "As mais antigas são" if params.get("oldest") else "Primeiras"
    return ActionResult(f"{len(rows)} {label} na planilha {wb.get('alias')}. {prefix}: {top}.",
                        display=_rows_listing(table, rows, wb))


@action("excel_search", "Procura linhas que contenham um texto ou número (nota fiscal, cliente, placa...) nas planilhas configuradas.",
        props(["query"], query=STR, workbook=STR))
def excel_search(services, params):
    svc = _svc(services)
    query = (params.get("query") or "").strip()
    if not query or normalize(query) in ("nota fiscal", "cliente", "nf", "pedido", "um cliente"):
        return ActionResult("Qual número ou nome devo procurar?", expects_reply=True,
                            follow_up=lambda text: excel_search(services, {**params, "query": text}))
    books = [_pick(services, params["workbook"])] if params.get("workbook") else (
        [svc.find_workbook("", context=services.context)] if services.context.get("workbook") else svc.workbooks())
    books = [b for b in books if b]
    if not books:
        raise ServiceUnavailable("Nenhuma planilha configurada. Em Configurações > Planilhas, escolha quais devo usar.")
    for wb in books:
        table = svc.table(wb)
        rows = table.search(query)
        if rows:
            services.context.remember(workbook=_wb_ref(wb))
            _remember_rows(services, table, rows)
            first = table.label(rows[0], wb.get("key_columns"))
            details = "; ".join(f"{k}: {_fmt(v)}" for k, v in list(rows[0].as_dict().items())[:5])
            say = (f"Encontrei {len(rows)} registro{'s' if len(rows) > 1 else ''} na planilha {wb.get('alias')}. "
                   + (f"Linha {rows[0].index}: {details}." if len(rows) == 1 else f"O primeiro: {first}."))
            return ActionResult(say, display=_rows_listing(table, rows, wb))
    return ActionResult.fail(f"Não encontrei {query} nas planilhas configuradas.")


@action("excel_summary", "Resume uma planilha: quantidade de linhas, status, período e totais.", props(workbook=STR))
def excel_summary(services, params):
    svc = _svc(services)
    wb = _pick(services, params.get("workbook", ""))
    table = svc.table(wb)
    info = table.summary(wb.get("status_column"), wb.get("date_column"))
    parts = [f"A planilha {wb.get('alias')}, aba {info['sheet']}, tem {info['rows']} linhas"]
    if info.get("status"):
        parts.append("status: " + ", ".join(f"{n} {s}" for s, n in info["status"][:4]))
    if info.get("date_range"):
        start, end = info["date_range"]
        parts.append(f"datas de {start:%d/%m/%Y} a {end:%d/%m/%Y}")
    for header, total in info.get("totals", []):
        parts.append(f"total de {header}: {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    display = "\n".join([f"Colunas: {', '.join(info['columns'])}"] + parts[1:])
    services.context.remember(summary=display)
    return ActionResult(". ".join(parts) + ".", display=display)


@action("excel_check", "Procura inconsistências: chaves repetidas ou vazias e datas inválidas.", props(workbook=STR))
def excel_check(services, params):
    svc = _svc(services)
    wb = _pick(services, params.get("workbook", ""))
    if not wb.get("key_columns") and not wb.get("date_column"):
        return ActionResult.fail("Configure as colunas-chave e de data dessa planilha para eu verificar inconsistências.")
    issues = svc.table(wb).inconsistencies(wb.get("key_columns"), wb.get("date_column"))
    if not issues:
        return ActionResult(f"Não encontrei inconsistências na planilha {wb.get('alias')}.")
    return ActionResult(f"Encontrei {len(issues)} possíveis inconsistências. A lista está na tela.",
                        display="\n".join(issues[:50]))


@action("excel_set_value", "Altera UMA célula: localiza a linha pelo texto 'row_query' e muda a coluna indicada. Sempre pede confirmação.",
        props(["row_query", "column", "value"], workbook=STR, row_query=STR, column=STR, value=STR))
def excel_set_value(services, params):
    svc = _svc(services)
    wb = _pick(services, params.get("workbook", ""))
    table = svc.table(wb, fresh=True)
    rows = table.search(params.get("row_query", ""))
    if not rows:
        return ActionResult.fail(f"Não encontrei a linha de {params.get('row_query')}.")
    if len(rows) > 1:
        return ActionResult.fail(f"Encontrei {len(rows)} linhas para {params.get('row_query')}. Seja mais específico.",
                                 display=_rows_listing(table, rows, wb))
    col = table.find_column(params.get("column"))
    if col is None:
        return ActionResult.fail(f"Não encontrei a coluna {params.get('column')}.")
    row = rows[0]
    address = table.cell_address(row, col)
    before = svc.read_cell(wb, table.sheet, address)
    value = params.get("value")
    preview = (f"Planilha: {wb.get('alias')} / aba {table.sheet}\nLinha {row.index} ({table.label(row, wb.get('key_columns'))})\n"
               f"Coluna {table.headers[col]} (célula {address}): '{_fmt(before) if before is not None else ''}' → '{value}'")
    question = f"Vou mudar {table.headers[col]} de {_fmt(before) or 'vazio'} para {value} na linha {row.index}. Confirma?"

    def execute() -> ActionResult:
        current = svc.read_cell(wb, table.sheet, address)
        if current != before:
            return ActionResult.fail("A célula foi alterada por outra pessoa enquanto eu aguardava. Nada foi gravado.")
        svc.write_range(wb, table.sheet, address, [[value]], before)
        services.activity(f"Excel: {wb.get('alias')} {table.sheet}!{address} '{before}' -> '{value}'", kind="excel")

        def undo() -> str:
            svc.write_range(wb, table.sheet, address, [[before if before is not None else ""]], value)
            return "Alteração desfeita na planilha."

        return ActionResult("Alteração gravada.", undo=undo, undo_label="alteração na planilha")

    return ActionResult(question, display=preview, expects_reply=True,
                        pending=PendingAction(question=question, execute=execute, details=preview))


@action("excel_add_row", "Adiciona uma linha ao final da tabela da planilha. 'values' = objeto {coluna: valor}. Sempre pede confirmação.",
        props(["values"], workbook=STR, values={"type": "object", "additionalProperties": {"type": "string"}}))
def excel_add_row(services, params):
    svc = _svc(services)
    wb = _pick(services, params.get("workbook", ""))
    table = svc.table(wb, fresh=True)
    values = params.get("values") or {}
    row_values: list[Any] = [""] * len(table.headers)
    unknown = []
    for column, value in values.items():
        col = table.find_column(column)
        if col is None:
            unknown.append(column)
        else:
            row_values[col] = value
    if unknown:
        return ActionResult.fail(f"Colunas não encontradas: {', '.join(unknown)}.")
    next_row = (table.rows[-1].index if table.rows else table.header_row) + 1
    from ..excel_analysis import col_letter

    address = f"{col_letter(table.first_col)}{next_row}:{col_letter(table.first_col + len(row_values) - 1)}{next_row}"
    preview = (f"Planilha: {wb.get('alias')} / aba {table.sheet}, nova linha {next_row}:\n"
               + "\n".join(f"{table.headers[i]}: {v}" for i, v in enumerate(row_values) if v != ""))
    question = f"Vou adicionar uma linha na planilha {wb.get('alias')}. Os dados estão na tela. Confirma?"

    def execute() -> ActionResult:
        svc.write_range(wb, table.sheet, address, [row_values], None)
        services.activity(f"Excel: linha adicionada em {wb.get('alias')} ({address})", kind="excel")
        return ActionResult("Linha adicionada.",
                            undo=lambda: (svc.write_range(wb, table.sheet, address, [[""] * len(row_values)], row_values),
                                          "Linha removida.")[1], undo_label="nova linha")

    return ActionResult(question, display=preview, expects_reply=True,
                        pending=PendingAction(question=question, execute=execute, details=preview))


@action("excel_create", "Cria uma NOVA planilha no OneDrive. Só use quando o usuário pedir explicitamente.",
        props(["name"], name=STR, headers={"type": "array", "items": {"type": "string"}}))
def excel_create(services, params):
    svc = _svc(services)
    name = (params.get("name") or "").strip()
    if not name:
        return ActionResult.fail("Qual o nome da nova planilha?")
    headers = params.get("headers") or []
    question = f"Criar a planilha {name} no seu OneDrive" + (f" com as colunas {', '.join(headers)}" if headers else "") + "?"

    def execute() -> ActionResult:
        item = svc.create_workbook(name, headers)
        entry = svc.add_workbook({"name": item.get("name", name), "drive_id": item["parentReference"]["driveId"],
                                  "item_id": item["id"], "web_url": item.get("webUrl", "")}, alias=name)
        services.activity(f"Planilha criada: {entry['name']}", kind="excel")
        return ActionResult(f"Planilha {name} criada e adicionada à lista.")

    return ActionResult(question, expects_reply=True, pending=PendingAction(question=question, execute=execute))


__all__ = ["ExcelService", "share_id", "minimal_xlsx", "guess_columns"]
