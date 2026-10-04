"""Arc CP · CP-5 — the ONE reader-facing exhibit formatter, consumed by every door.

CP-0's census (ROADMAP §3.22) counted three answers to "show a table" and none shared: the
model's prose, `gfmTable` in the TypeScript Slack bot, and `Block("table")` in the export —
and by the time this was built the Teams door (AO-5) had grown a fourth. None of them
formatted a cell, so a grid reached its reader as `54496.64009666443` on every door.

This module is the table half of CP-5. A door calls it with its own ENCODINGS — how many
columns before a table stops reading, how many rows before it becomes a preview, what the
caption says about where the rest went — and gets back cells formatted by one rule. The
decisions (how a number, a share, an amount or a date reads) are made here, once.

THE RULE is the web's data table, ported field for field so a figure reads the same in the
app, in a thread, in a deck and in a Teams reply (`web/components/AugTable.tsx` `fmt`,
`web/lib/format.ts`, `web/lib/orgSettings.ts`):

    null                         → "—"
    a share/percent/rate column  → "12.3%"     (|v| ≤ 1 is a ratio, ×100; else already a percent)
    a money column               → "$1,820,497.55"  (to the cent; the column's own ISO suffix wins)
    an id or a period key        → as stored   (a year is not "2,024", a month is not a measure)
    any other number             → "54,496.64" (the FULL number, grouped; ≤2 dp from 1,000, else ≤4)
    a midnight timestamp         → "2025-04-01"
    anything else                → as stored

The web is a door that formats in the browser; it is held to this rule by the parity test, not
by calling it. Change one, change both.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

# ── The column classes — `AugTable.tsx` and `orgSettings.ts`, verbatim ──────────────────

SHARE_COL = re.compile(r"pct|percent|share|rate|ratio|proportion", re.I)
ORDINAL_COL = re.compile(r"\bid\b|_id$|^id$|id$|Id$|ID$", re.I)
DIMENSION_KEY_COL = re.compile(
    r"(?<![a-z])(?:year|quarter|qtr|month|week|weekday|dow|day_of_week|hour|fiscal_period|period_no)(?![a-z])",
    re.I)
_CURRENCY_SUFFIX = (r"(?:usd|eur|gbp|chf|jpy|cny|inr|aud|cad|sek|nok|dkk|sgd|hkd|nzd|brl|zar|mxn"
                    r"|pln|aed)$")
CURRENCY_SUFFIX_RE = re.compile(_CURRENCY_SUFFIX, re.I)
MONEY_RE = re.compile(
    r"(?<![a-z])(?:revenues?|sales|gmv|prices?|pricing|costs?|amounts?|spend|spent|profits?|payments?"
    r"|fees?|charges?|balances?|budget|income|expenses?|turnover|takings|payout|aov|arpu|mrr|arr|ltv"
    r"|cac|gross)(?![a-z])"
    + "|" + _CURRENCY_SUFFIX + r"|net_(?:sales|revenue|profit)", re.I)
NOT_MONEY_RE = re.compile(
    r"(?<![a-z])(?:counts?|qty|quantity|numbers?|num|rate|ratio|pct|percent|share|proportion|rank"
    r"|index|score|days?|months?|years?|weeks?|hours?|minutes?|age|id)(?![a-z])", re.I)
_ABBREVS = re.compile(
    r"^(usd|id|uk|us|eu|vat|sku|url|api|crm|gmv|mrr|arr|ltv|cac|ctr|aov|roi|pnl|gp|kpi|cogs|nps|arpu"
    r"|cpa|cpc|cpm|sla|sql|etl|csv|upc|ean|gtin|ytd|mtd|qtd|yoy)$", re.I)
_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]00:00:00(?:\.0+)?$")


def is_money_column(column: str) -> bool:
    return bool(MONEY_RE.search(column or "")) and not NOT_MONEY_RE.search(column or "")


def column_currency_symbol(column: str, default_symbol: str) -> str:
    """The column's OWN currency (`refund_chf` → CHF) wins over the organisation's."""
    m = CURRENCY_SUFFIX_RE.search((column or "").lower())
    if m:
        from aughor.orgsettings.store import currency_symbol
        return currency_symbol(m.group(0).upper())
    return default_symbol


def clean_label(column: str) -> str:
    """A header for a reader: `total_revenue` → `Total Revenue`, `aov` → `AOV`."""
    return re.sub(r"\b\w+", lambda m: (m.group(0).upper() if _ABBREVS.match(m.group(0))
                                       else m.group(0)[:1].upper() + m.group(0)[1:].lower()),
                  (column or "").replace("_", " "))


# ── One value ────────────────────────────────────────────────────────────────────────────

def _number(v: Any) -> Optional[float]:
    """The value as a number when it is one — a float, a Decimal, or a numeric string (DuckDB
    hands DECIMAL columns back as either). A bool is text here, not 1."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    if isinstance(v, str) and v.strip():
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def format_table_number(n: float) -> str:
    """`formatTableNumber`: the full number, grouped — never K/M/B, which re-scales per row."""
    if n != n or n in (float("inf"), float("-inf")):
        return str(n)
    if float(n).is_integer():
        return f"{int(n):,}"
    digits = 2 if abs(n) >= 1e3 else 4
    out = f"{n:,.{digits}f}".rstrip("0").rstrip(".")
    return "0" if out in ("-0", "") else out


def format_percent(n: float, digits: int = 1) -> str:
    return f"{(n * 100 if abs(n) <= 1 else n):.{digits}f}%"


def format_money(n: float, symbol: str) -> str:
    return f"{'-' if n < 0 else ''}{symbol}{abs(n):,.2f}"


def format_cell(column: str, value: Any, *, money_symbol: str = "") -> str:
    """One cell, for a reader, by the rule in this module's docstring."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    text = str(value)
    n = _number(value)
    if n is not None:
        if SHARE_COL.search(column or ""):
            return format_percent(n, 1)
        if is_money_column(column):
            return format_money(n, column_currency_symbol(column, money_symbol))
        if not ORDINAL_COL.search(column or "") and not DIMENSION_KEY_COL.search(column or ""):
            return format_table_number(n)
    m = _MIDNIGHT.match(text)
    return m.group(1) if m else text


def positional(row: Any, columns: list) -> list:
    """A row as one cell per column, in column order: a list is padded or cut to the
    columns, a dict is read by column name, a bare value is a one-cell row."""
    if isinstance(row, dict):
        return [row.get(c) for c in columns]
    cells = list(row) if isinstance(row, (list, tuple)) else [row]
    return [cells[i] if i < len(cells) else None for i in range(len(columns))]


def format_rows(columns: list, rows: list, *, money_symbol: str = "") -> list[list[str]]:
    """Every cell of a grid, formatted; short rows are padded so a column never shifts."""
    cols = [str(c) for c in (columns or [])]
    return [[format_cell(c, v, money_symbol=money_symbol) for c, v in zip(cols, positional(r, cols))]
            for r in (rows or [])]


# ── One table ────────────────────────────────────────────────────────────────────────────

def worth_showing(columns: list, rows: list) -> bool:
    """A one-number result is already in the sentence above it; a grid earns an exhibit by
    having a shape — more than one row, or enough columns to be a breakdown."""
    return bool(columns) and bool(rows) and (len(rows) > 1 or len(columns) > 2)


def to_csv(columns: list, rows: list) -> str:
    """RFC 4180, with the values AS STORED — a CSV is for the reader's own tools, and a
    rounded figure there is a figure they cannot recompute."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([str(c) for c in columns])
    for r in rows:
        w.writerow(["" if v is None else (json.dumps(v, default=str) if isinstance(v, (dict, list))
                                          else v) for v in positional(r, list(columns))])
    return buf.getvalue().rstrip("\n")


def _gfm(columns: list[str], rows: list[list[str]]) -> str:
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    head = "| " + " | ".join(esc(c) for c in columns) + " |"
    rule = "| " + " | ".join("---" for _ in columns) + " |"
    return "\n".join([head, rule, *("| " + " | ".join(esc(c) for c in r) + " |" for r in rows)])


@dataclass
class TableExhibit:
    """A grid as one door will show it. ``markdown`` is the GFM table (or the caption alone
    when the grid is too wide to read); ``shown``/``total`` say how much of it that is —
    whatever is trimmed says so, in ``caption``."""
    markdown: str
    shown: int
    total: int
    wide: bool
    caption: str
    columns: list[str]
    rows: list[list[str]]


def reader_table(columns: list, rows: list, *, max_cols: int, max_rows: int,
                 preview_rows: int, rest: str, money_symbol: str = "",
                 headers: str = "label") -> TableExhibit:
    """THE table builder. The door supplies its encodings — ``max_cols`` (past it the table
    does not read at all), ``max_rows`` (past it a preview), ``preview_rows`` and ``rest``
    (where the full result went: "attached as CSV", "in the report") — and gets back one
    of three outcomes, each captioned:

    narrow and short → the whole table · narrow but long → a preview + "Showing k of n rows"
    · wide → no table, only "n rows × m columns".
    """
    cols = [str(c) for c in (columns or [])]
    all_rows = list(rows or [])
    n, m = len(all_rows), len(cols)
    head = [clean_label(c) for c in cols] if headers == "label" else cols
    if not cols or not all_rows:
        return TableExhibit("", 0, n, False, "", head, [])
    if m > max_cols:
        caption = f"_{n} row{'' if n == 1 else 's'} × {m} columns — {rest}._"
        return TableExhibit(caption, 0, n, True, caption, head, [])
    shown = n if n <= max_rows else min(preview_rows, n)
    body = format_rows(cols, all_rows[:shown], money_symbol=money_symbol)
    table = _gfm(head, body)
    if shown == n:
        return TableExhibit(table, n, n, False, "", head, body)
    caption = f"_Showing {shown} of {n} rows — {rest}._"
    return TableExhibit(f"{table}\n\n{caption}", shown, n, False, caption, head, body)
