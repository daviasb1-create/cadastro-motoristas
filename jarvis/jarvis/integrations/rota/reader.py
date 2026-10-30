"""Leitura das planilhas da pasta de roteirização (xlsx, xls, csv).

Imita a leitura da ferramenta no navegador: primeira aba, primeira linha como
cabeçalho, linhas vazias ignoradas, cabeçalho vazio vira __EMPTY e repetido
ganha sufixo _1, _2.
"""
from __future__ import annotations

import csv
import io
import time
from pathlib import Path

from .engine import Report, digits, norm

EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".csv"}

# Subpastas criadas na pasta de roteirização (uma por campo de upload da ferramenta)
FOLDERS = {
    "chegando": "1 - Fretes chegando",
    "no_rj": "2 - Cargas ja no Rio",
    "agendado": "3 - Agendamentos",
    "depara": "De-para CEP (opcional)",
    "saida": "Rotas geradas",
}


def ensure_folders(base: Path) -> None:
    for name in FOLDERS.values():
        (base / name).mkdir(parents=True, exist_ok=True)


def recent_files(folder: Path, max_age_hours: float) -> tuple[list[Path], list[Path]]:
    """(planilhas recentes, planilhas antigas ignoradas). Ignora temporários do Excel (~$)."""
    if not folder.exists():
        return [], []
    files = sorted(p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in EXTENSIONS and not p.name.startswith("~$"))
    if not max_age_hours:
        return files, []
    limit = time.time() - max_age_hours * 3600
    return [p for p in files if p.stat().st_mtime >= limit], [p for p in files if p.stat().st_mtime < limit]


def _headers(raw: list) -> list[str]:
    headers: list[str] = []
    counts: dict[str, int] = {}
    empty = 0
    for value in raw:
        name = "" if value is None else str(value).strip()
        if not name:
            name = "__EMPTY" if empty == 0 else f"__EMPTY_{empty}"
            empty += 1
        if name in counts:
            counts[name] += 1
            name = f"{name}_{counts[name]}"
        else:
            counts[name] = 0
        headers.append(name)
    return headers


def _rows_from_matrix(matrix: list[list]) -> tuple[list[str], list[dict]]:
    if not matrix:
        return [], []
    headers = _headers(matrix[0])
    rows = []
    for line in matrix[1:]:
        if all(v is None or str(v).strip() == "" for v in line):
            continue
        rows.append({h: (line[i] if i < len(line) and line[i] is not None else "") for i, h in enumerate(headers)})
    return headers, rows


def read_matrix(path: Path) -> list[list]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.worksheets[0]
            return [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    if suffix == ".xls":
        try:
            import xlrd  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f"{path.name}: planilha .xls antiga. Salve como .xlsx ou instale o pacote xlrd.") from exc
        book = xlrd.open_workbook(str(path))
        sheet = book.sheet_by_index(0)
        matrix = []
        for i in range(sheet.nrows):
            line = []
            for j, cell in enumerate(sheet.row(i)):
                if cell.ctype == xlrd.XL_CELL_DATE:
                    line.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
                else:
                    line.append(cell.value)
            matrix.append(line)
        return matrix
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def read_report(paths: list[Path]) -> Report:
    headers: list[str] = []
    rows: list[dict] = []
    for path in paths:
        h, r = _rows_from_matrix(read_matrix(path))
        for name in h:
            if name not in headers:
                headers.append(name)
        rows.extend(r)
    return Report(rows=rows, headers=headers, files=[p.name for p in paths])


def read_depara(path: Path) -> list[tuple[str, str]]:
    """De-para CEP -> região: procura nas 30 primeiras linhas um cabeçalho com CEP e Região."""
    matrix = read_matrix(path)
    for i, line in enumerate(matrix[:30]):
        cells = [norm(c) for c in line]
        if any("cep" in c for c in cells) and any("regiao" in c for c in cells):
            ci = next(k for k, c in enumerate(cells) if "cep" in c)
            ri = next(k for k, c in enumerate(cells) if "regiao" in c)
            entries = []
            for row in matrix[i + 1:]:
                cep_raw = str(row[ci] if ci < len(row) and row[ci] is not None else "")
                if "exemplo" in cep_raw.lower():
                    continue
                if isinstance(row[ci], float) and row[ci].is_integer():
                    cep_raw = str(int(row[ci]))
                prefix = digits(cep_raw)
                reg = str(row[ri] if ri < len(row) and row[ri] is not None else "").strip()
                if prefix and reg:
                    entries.append((prefix, reg))
            return entries
    raise RuntimeError(f"{path.name}: não achei o cabeçalho CEP/Região no de-para.")
