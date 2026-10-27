"""Making a sheet: a file read as written, its kinds checked, its rows kept typed (Arc SH, SH-1).

A file is read with **every value as text** first — what was written — and each column is measured against each kind
(``kinds.fit_sql``). A person chooses among the kinds every value fits; the import then writes the rows typed, and checks
that no filled value became empty on the way (the lossless rule, applied a second time where it could still go wrong).
The typed rows are kept as ``source.parquet`` beside the original file, each with ``_row`` — its row in the file, which
is what a cell's history says it was imported from.

The same path takes a query's rows (kept frozen, the statement saved beside them) and a blank sheet.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Optional

import duckdb

from aughor.sheets import files, kinds

#: Formats a sheet can be made from. Excel's old binary ``.xls`` is not read: DuckDB reads ``.xlsx`` only.
READERS = {".csv": "csv", ".tsv": "csv", ".txt": "csv", ".parquet": "parquet", ".parq": "parquet",
           ".json": "json", ".xlsx": "xlsx"}

#: The most common values kept per column, for a Choice's chips and the import's preview.
TOP_VALUES = 12

#: The most rows a query's result is kept to. More is said, never silently cut.
MAX_KEPT_ROWS = 200_000


class ImportRefused(ValueError):
    """Why a file cannot become a sheet, in a sentence a person can act on."""


def _q(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def tabs(path: Path) -> list[str]:
    """The tabs of an Excel workbook, in order (read from the workbook's own index — no reader library needed)."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("xl/workbook.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile, OSError) as exc:
        raise ImportRefused(f"{path.name} is not an Excel workbook that can be read ({exc})") from None
    return [re.sub(r"&amp;", "&", m) for m in re.findall(r"<(?:\w+:)?sheet\b[^>]*\bname=\"([^\"]+)\"", xml)]


def _raw_select(path: Path, tab: str = "") -> str:
    """The table function that reads ``path`` with every value as text."""
    kind = READERS.get(path.suffix.lower())
    if kind is None:
        hint = " Save it as .xlsx." if path.suffix.lower() == ".xls" else ""
        raise ImportRefused(f"{path.name}: a sheet is made from CSV, TSV, Parquet, JSON or an Excel .xlsx file.{hint}")
    if kind == "csv":
        sep = ", delim='\\t'" if path.suffix.lower() == ".tsv" else ""
        return f"read_csv('{_q(path)}', all_varchar=true, header=true{sep})"
    if kind == "xlsx":
        sheet = f", sheet='{tab.replace(chr(39), chr(39) * 2)}'" if tab else ""
        return f"read_xlsx('{_q(path)}', all_varchar=true, header=true{sheet})"
    if kind == "parquet":
        return f"read_parquet('{_q(path)}')"
    return f"read_json_auto('{_q(path)}')"


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    from aughor.connectors.file.local_upload import ensure_excel_extension
    ensure_excel_extension(con)
    return con


def load_raw(con: duckdb.DuckDBPyConnection, path: Path, tab: str = "") -> list[str]:
    """Read a file into ``raw`` — every value as text, plus ``_row``, its row in the file — and name its columns."""
    select = _raw_select(path, tab)
    try:
        con.execute(f"CREATE OR REPLACE TEMP TABLE _read AS SELECT * FROM {select}")
    except duckdb.Error as exc:
        if "not utf-8" in str(exc).lower() and READERS.get(path.suffix.lower()) == "csv":
            from aughor.connectors.file.local_upload import fallback_encoding
            enc = fallback_encoding(path)
            con.execute(f"CREATE OR REPLACE TEMP TABLE _read AS SELECT * FROM "
                        f"read_csv('{_q(path)}', all_varchar=true, header=true, encoding='{enc}')")
        else:
            raise ImportRefused(f"{path.name} could not be read: {str(exc).splitlines()[0][:300]}") from None
    columns = [r[0] for r in con.execute("DESCRIBE _read").fetchall()]
    if not columns:
        raise ImportRefused(f"{path.name} holds no columns")
    if "_row" in columns:
        raise ImportRefused(f"{path.name} has a column named _row, which a sheet keeps for each row's number")
    texts = ", ".join(f"CAST({ident(c)} AS VARCHAR) AS {ident(c)}" for c in columns)
    con.execute(f"CREATE OR REPLACE TEMP TABLE raw AS SELECT row_number() OVER () AS _row, {texts} FROM _read")
    con.execute("DROP TABLE _read")
    return columns


def measure(con: duckdb.DuckDBPyConnection, columns: list[str]) -> dict[str, kinds.Fit]:
    """How each column of ``raw`` fits each kind."""
    out: dict[str, kinds.Fit] = {}
    for c in columns:
        cur = con.execute(f"SELECT {kinds.fit_sql(ident(c))} FROM raw")
        names = [d[0] for d in cur.description]
        row = dict(zip(names, cur.fetchone()))
        top = con.execute(
            f"SELECT TRIM({ident(c)}) AS v, COUNT(*) AS n FROM raw WHERE NULLIF(TRIM({ident(c)}), '') IS NOT NULL "
            f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {TOP_VALUES}").fetchall()
        first = con.execute(f"SELECT {ident(c)} FROM raw WHERE NULLIF(TRIM({ident(c)}), '') IS NOT NULL "
                            "ORDER BY _row LIMIT 1").fetchone()
        out[c] = kinds.fit_from_row(row, [(str(v), int(n)) for v, n in top], first[0] if first else None)
    return out


def describe(path: Path, tab: str = "") -> dict:
    """What a file would become: its rows, and per column the kinds every value fits, the one offered first, how many
    are empty, its first value and its most common values."""
    con = _connect()
    try:
        columns = load_raw(con, path, tab)
        rows = int(con.execute("SELECT COUNT(*) FROM raw").fetchone()[0])
        fits = measure(con, columns)
    finally:
        con.close()
    return {"rows": rows, "columns": [_column_report(c, fits[c]) for c in columns]}


def _column_report(name: str, fit: kinds.Fit) -> dict:
    suggested = kinds.suggest(name, fit)
    near = {k: n for k, n in fit.misfits.items() if 0 < n <= max(1, fit.filled // 50) and k != kinds.CHOICE}
    note = ""
    if suggested == kinds.DATE and fit.midnight:
        note = "Every value is midnight, so it is a date — compared by day, never by time."
    elif suggested == kinds.DATETIME and kinds.DATE in near:
        # Olist's review dates: 85 of 99,224 read 01:00 on 2017-10-15, the night Brazil's clocks skipped midnight
        n = near[kinds.DATE]
        note = (f"{n:,} value{'s' if n != 1 else ''} {'are' if n != 1 else 'is'} not at midnight, so it stays a "
                "Date & time rather than a date.")
    elif near and suggested == kinds.TEXT:
        k, n = min(near.items(), key=lambda kv: kv[1])
        note = f"{n:,} value{'s' if n != 1 else ''} do not read as {kinds.LABELS[k]}, so it stays Text."
    return {"name": name, "suggested": suggested, "offered": fit.offered(), "filled": fit.filled, "empty": fit.empty,
            "integer": fit.integer, "first": fit.first, "values": fit.values if suggested == kinds.CHOICE else [],
            "distinct": fit.distinct, "misfits": {k: v for k, v in fit.misfits.items() if v}, "note": note}


def write_source(sheet_id: str, con: duckdb.DuckDBPyConnection, plan: list[dict]) -> int:
    """Write ``raw`` typed, as the sheet's ``source.parquet``: per column of ``plan`` (``{id, raw, kind, integer}``) the
    raw text cast to its kind, named by the column's id. Refuses — and writes nothing — when a filled value would be
    empty once typed, so no import ever loses a value to its kind. Returns the rows written."""
    selects = ["_row"]
    checks = []
    for p in plan:
        cast = kinds.cast_sql(p["kind"], ident(p["raw"]), integer=bool(p.get("integer")))
        selects.append(f"{cast} AS {ident(p['id'])}")
        checks.append(f"COUNT(NULLIF(TRIM({ident(p['raw'])}), '')) - COUNT(TRY({cast})) AS {ident(p['id'])}")
    try:
        lost = con.execute(f"SELECT {', '.join(checks)} FROM raw").fetchone() if checks else ()
    except duckdb.Error as exc:
        raise ImportRefused(f"the values could not be read as the kinds chosen: {str(exc).splitlines()[0][:300]}") \
            from None
    for p, n in zip(plan, lost or ()):
        if n:
            raise ImportRefused(f"{n:,} value{'s' if n != 1 else ''} in {p['raw']} do not read as "
                                f"{kinds.LABELS.get(p['kind'], p['kind'])}; choose Text for that column")
    target = files.source_parquet(sheet_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT {', '.join(selects)} FROM raw ORDER BY _row) TO '{_q(target)}' (FORMAT PARQUET)")
    return int(con.execute("SELECT COUNT(*) FROM raw").fetchone()[0])


def rows_to_raw(con: duckdb.DuckDBPyConnection, columns: list[str], rows: list[list[Any]]) -> list[str]:
    """A query's rows as ``raw`` — each value as the engine wrote it, as text — so a kept result is measured and typed
    exactly as a file is."""
    names = _unique(columns)
    con.execute(f"CREATE OR REPLACE TEMP TABLE raw (_row BIGINT, {', '.join(f'{ident(n)} VARCHAR' for n in names)})")
    if rows:
        con.executemany(f"INSERT INTO raw VALUES (?, {', '.join('?' for _ in names)})",
                        [[i + 1, *[None if v is None else _text(v) for v in r]] for i, r in enumerate(rows)])
    return names


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ") if hasattr(value, "hour") else value.isoformat()
    return str(value)


def _unique(names: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        base = str(n or "column").strip() or "column"
        name, k = base, 2
        while name.lower() in seen or name == "_row":
            name, k = f"{base}_{k}", k + 1
        seen.add(name.lower())
        out.append(name)
    return out


def open_file(path: Path, tab: str = "") -> tuple[duckdb.DuckDBPyConnection, list[str]]:
    """A connection holding ``raw`` for a file, and its columns. The caller closes it."""
    con = _connect()
    try:
        return con, load_raw(con, path, tab)
    except Exception:
        con.close()
        raise


def currency_for(upload: Optional[dict], *, connection_id: str = "", schema: str = "") -> str:
    """The currency a Money column is in: the one a person confirmed for the dataset the rows came from — "" when none
    did, and the column then reads as plain amounts, never under a guessed symbol (the 2026-10-23 decisions: a currency
    is per dataset, and the organisation's labels no figure)."""
    from aughor.orgsettings.store import figure_currency
    if upload and upload.get("schema"):
        from aughor.db.registry import WORKSPACE_ID
        return figure_currency(WORKSPACE_ID, upload.get("schema"))
    return figure_currency(connection_id, schema or None) if connection_id else ""
