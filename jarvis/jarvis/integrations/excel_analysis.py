"""Análise de tabelas de planilhas (funções puras, testáveis sem internet).

Nada aqui presume nomes de colunas: as colunas de status e data vêm da
configuração do usuário. ``guess_columns`` apenas SUGERE candidatos para a
tela de configuração.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from ..nlu.normalize import normalize, similar

EXCEL_EPOCH = datetime(1899, 12, 30)


def col_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def col_index(letters: str) -> int:
    value = 0
    for ch in letters.upper():
        value = value * 26 + (ord(ch) - 64)
    return value - 1


def parse_address(address: str) -> tuple[str, int, int]:
    """'Planilha1!B3:H40' -> ('Planilha1', linha_inicial=3, coluna_inicial=1)."""
    sheet = ""
    if "!" in address:
        sheet, address = address.rsplit("!", 1)
        sheet = sheet.strip("'")
    first = address.split(":")[0]
    match = re.match(r"\$?([A-Za-z]+)\$?(\d+)", first)
    if not match:
        return sheet, 1, 0
    return sheet, int(match.group(2)), col_index(match.group(1))


def to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and 20000 < float(value) < 80000:
        return (EXCEL_EPOCH + timedelta(days=float(value))).date()
    text = str(value).strip()
    for candidate in dict.fromkeys((text, text[:19], text[:16], text[:10])):
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S",
                    "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    if re.fullmatch(r"\d{5}(\.\d+)?", text):
        return to_date(float(text))
    return None


def to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace("R$", "").replace(" ", "")
    if not text:
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})*(,\d+)?|-?\d+(,\d+)?", text):
        return float(text.replace(".", "").replace(",", "."))
    try:
        return float(text)
    except ValueError:
        return None


def is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


@dataclass
class Row:
    index: int  # número da linha na planilha (1 = primeira linha)
    values: list[Any]
    headers: list[str] = field(default_factory=list)

    def get(self, column: int) -> Any:
        return self.values[column] if 0 <= column < len(self.values) else None

    def as_dict(self) -> dict[str, Any]:
        return {h or col_letter(i): v for i, (h, v) in enumerate(zip(self.headers, self.values)) if not is_empty(v)}


@dataclass
class Table:
    sheet: str
    headers: list[str]
    rows: list[Row]
    first_col: int = 0  # índice da primeira coluna do intervalo usado
    header_row: int = 1

    # ---------------------------------------------------------- construção
    @classmethod
    def from_values(cls, values: list[list[Any]], address: str = "A1", sheet: str = "",
                    header_row: int | None = None) -> "Table":
        addr_sheet, start_row, start_col = parse_address(address)
        sheet = sheet or addr_sheet
        if header_row is not None:
            h_offset = max(0, header_row - start_row)
        else:
            h_offset = detect_header(values)
        headers = [str(v).strip() if not is_empty(v) else "" for v in (values[h_offset] if values else [])]
        rows = []
        for offset, raw in enumerate(values[h_offset + 1:], start=h_offset + 1):
            if all(is_empty(v) for v in raw):
                continue
            rows.append(Row(start_row + offset, list(raw), headers))
        return cls(sheet, headers, rows, start_col, start_row + h_offset)

    # ------------------------------------------------------------- colunas
    def find_column(self, name: str | None) -> int | None:
        if not name:
            return None
        if re.fullmatch(r"[A-Za-z]{1,3}", name.strip()) and not any(normalize(h) == normalize(name) for h in self.headers):
            idx = col_index(name.strip()) - self.first_col
            return idx if 0 <= idx < len(self.headers) else None
        target = normalize(name)
        best = (0.0, None)
        for i, header in enumerate(self.headers):
            score = similar(target, normalize(header))
            if score > best[0]:
                best = (score, i)
        return best[1] if best[0] >= 0.75 else None

    def cell_address(self, row: Row, column: int) -> str:
        return f"{col_letter(self.first_col + column)}{row.index}"

    def label(self, row: Row, key_columns: list[str] | None = None) -> str:
        parts = []
        for name in key_columns or []:
            col = self.find_column(name)
            if col is not None and not is_empty(row.get(col)):
                parts.append(f"{self.headers[col]} {_fmt(row.get(col))}")
        if not parts:
            parts = [_fmt(v) for v in row.values if not is_empty(v)][:2]
        return ", ".join(parts)

    # ------------------------------------------------------------- análises
    def pending(self, status_column: str | None, pending_values: list[str] | None = None,
                done_values: list[str] | None = None) -> list[Row]:
        col = self.find_column(status_column)
        if col is None:
            raise ValueError("Coluna de status não configurada ou não encontrada.")
        pend = [normalize(v) for v in pending_values or [] if v]
        done = [normalize(v) for v in done_values or [] if v]
        result = []
        for row in self.rows:
            value = normalize(str(row.get(col) or ""))
            if pend:
                if any(p == value or (p and p in value) for p in pend):
                    result.append(row)
            elif done:
                if not any(d == value or (d and d in value) for d in done):
                    result.append(row)
            elif not value:
                result.append(row)  # sem regra: status vazio = pendente
        return result

    def sort_by_date(self, rows: list[Row], date_column: str | None, ascending: bool = True) -> list[Row]:
        col = self.find_column(date_column)
        if col is None:
            return rows
        dated = [(to_date(r.get(col)), r) for r in rows]
        with_date = sorted([d for d in dated if d[0]], key=lambda d: d[0], reverse=not ascending)
        without = [r for d, r in dated if not d]
        return [r for _, r in with_date] + without

    def overdue(self, rows: list[Row], date_column: str | None, today: date | None = None) -> list[Row]:
        col = self.find_column(date_column)
        if col is None:
            raise ValueError("Coluna de data/prazo não configurada ou não encontrada.")
        today = today or date.today()
        return [r for r in rows if (d := to_date(r.get(col))) and d < today]

    def search(self, query: str, limit: int = 20) -> list[Row]:
        tokens = [t for t in normalize(query).split() if t not in {"o", "a", "de", "da", "do", "e", "um", "uma"}]
        if not tokens:
            return []
        digits = re.sub(r"\D", "", query)
        results = []
        for row in self.rows:
            cells = [normalize(str(v)) for v in row.values if not is_empty(v)]
            joined = " ".join(cells)
            if all(t in joined for t in tokens) or (len(digits) >= 3 and any(digits == re.sub(r"\D", "", c) for c in cells)):
                results.append(row)
            if len(results) >= limit:
                break
        if not results and len(tokens) > 1:
            # tolera palavras genéricas faladas ("nota fiscal 1234" -> procura "1234")
            specific = [t for t in tokens if any(ch.isdigit() for ch in t)] or tokens[-1:]
            for row in self.rows:
                joined = " ".join(normalize(str(v)) for v in row.values if not is_empty(v))
                if all(t in joined for t in specific):
                    results.append(row)
                if len(results) >= limit:
                    break
        return results

    def summary(self, status_column: str | None = None, date_column: str | None = None) -> dict[str, Any]:
        info: dict[str, Any] = {"sheet": self.sheet, "rows": len(self.rows),
                                "columns": [h for h in self.headers if h]}
        col = self.find_column(status_column)
        if col is not None:
            counter = Counter(str(r.get(col) or "(vazio)").strip() or "(vazio)" for r in self.rows)
            info["status"] = counter.most_common(8)
        dcol = self.find_column(date_column)
        if dcol is not None:
            dates = [d for r in self.rows if (d := to_date(r.get(dcol)))]
            if dates:
                info["date_range"] = (min(dates), max(dates))
        numeric = []
        for i, header in enumerate(self.headers):
            values = [to_number(r.get(i)) for r in self.rows]
            nums = [v for v in values if v is not None]
            if header and len(nums) >= max(3, len(self.rows) // 2) and not re.search(r"(codigo|cod|id|nf|nota|cep|cpf|cnpj|telefone|numero|n[ºo°])", normalize(header)):
                numeric.append((header, sum(nums)))
        info["totals"] = numeric[:3]
        return info

    def inconsistencies(self, key_columns: list[str] | None = None, date_column: str | None = None) -> list[str]:
        issues: list[str] = []
        for name in key_columns or []:
            col = self.find_column(name)
            if col is None:
                continue
            seen: dict[str, int] = {}
            for row in self.rows:
                value = normalize(str(row.get(col) or ""))
                if not value:
                    issues.append(f"Linha {row.index}: {self.headers[col]} vazio")
                elif value in seen:
                    issues.append(f"Linha {row.index}: {self.headers[col]} '{row.get(col)}' repetido (linha {seen[value]})")
                else:
                    seen[value] = row.index
        dcol = self.find_column(date_column)
        if dcol is not None:
            for row in self.rows:
                value = row.get(dcol)
                if not is_empty(value) and to_date(value) is None:
                    issues.append(f"Linha {row.index}: data inválida '{value}' em {self.headers[dcol]}")
        return issues


def detect_header(values: list[list[Any]]) -> int:
    """Primeira linha (entre as 10 primeiras) com ao menos 2 textos não numéricos."""
    for i, row in enumerate(values[:10]):
        texts = [v for v in row if isinstance(v, str) and v.strip() and to_number(v) is None]
        if len(texts) >= 2:
            return i
    return 0


def guess_columns(headers: list[str]) -> dict[str, list[str]]:
    patterns = {
        "status": r"(status|situac|andamento|pendenc|estado|etapa|concluid|resolvid|baixa)",
        "date": r"(prazo|vencim|previs|entrega|data|dt\b|agendad|limite)",
        "key": r"(nota|nf|pedido|cliente|nome|codigo|cod|id\b|placa|motorista|cte|documento)",
    }
    return {kind: [h for h in headers if h and re.search(rx, normalize(h))] for kind, rx in patterns.items()}


def _fmt(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
