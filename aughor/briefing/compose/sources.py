"""Arc BC-1 · what a block may read (ROADMAP §3.67).

A block never holds a number of its own: it names a SOURCE, and the source is a governed query with its rows, its
SQL, what the guards did and its status. Three kinds, each measured by the platform rather than told by the model:

* **check** — one of the guide's checks as Arc BG measured it: the range and the ranges before it, with its usual
  range, change and streak;
* **breakdown** — a check broken down by any low-cardinality column of the table it is dated by, each segment against
  its own usual range — compiled by `metric_time.run_measure(by=…)`, no model and no hand-written SQL;
* **query** — a SELECT the model wrote while investigating, run through the same guarded door the Data Canvas uses
  (`agent/converse_tools.run_sql`: the guard battery, the declared metric filters, the reader's policies, the guard
  receipts). A refusal is kept and said — with the repair the door suggests — never read as an empty result.

Rows are made JSON-safe here once (dates as ISO days, decimals as floats), so the page, the number gate and a send
read the same values.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

#: The most rows a source keeps. A block draws a handful; the evidence panel shows them all.
MAX_ROWS = 200
#: A segment behind fewer rows than this is too few to call — drawn grey, never headlined.
MIN_CELL_ROWS = 30
#: How many segments a breakdown keeps, furthest from usual first.
MAX_SEGMENTS = 12


class Source(BaseModel):
    id: str
    label: str
    kind: Literal["check", "breakdown", "query", "drill", "answer"]
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    sql: str = ""
    #: final | provisional | to_date | refused — said beside every block that reads it
    status: str = "final"
    #: A check's own figures: current, previous, last_year, usual_mean/low/high, z, streak, rel, rel_last_year …
    facts: dict = Field(default_factory=dict)
    receipts: list[dict] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    #: How it was measured, in words a reader can check ("the 8 weeks before as the usual range").
    note: str = ""
    error: str = ""
    #: What the guarded door suggests when a SELECT failed — handed back to the model, never shown as a result.
    repair: dict = Field(default_factory=dict)
    unit: str = ""
    better: str = "none"


def cell(v: Any) -> Any:
    """A value as JSON carries it: an ISO day, a float, a string, or None."""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()[:10] if isinstance(v, date) and not isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def _rows(rows: list) -> list[list[Any]]:
    out = []
    for r in rows[:MAX_ROWS]:
        cells = list(r.values()) if isinstance(r, dict) else list(r)
        out.append([cell(c) for c in cells])
    return out


# ── check ────────────────────────────────────────────────────────────────────────────────────

def from_check(fig: dict, *, period_word: str = "range") -> Source:
    """A measured check (`edition.measure_check`) as a source: one row per range read, the range itself last."""
    u = fig.get("usual") or {}
    facts = {k: fig.get(k) for k in ("current", "previous", "last_year", "rel", "rel_last_year", "z", "streak", "n")}
    facts.update({"usual_mean": u.get("mean"), "usual_low": u.get("low"), "usual_high": u.get("high"),
                  "usual_n": u.get("n")})
    for k in ("current_text", "previous_text", "last_year_text"):
        facts[k] = fig.get(k)
    facts.update({f"usual_{k}_text": u.get(f"{k}_text") for k in ("mean", "low", "high")})
    if fig.get("extreme"):
        facts["extreme"] = fig["extreme"]
    rows = [[p["start"], cell(p["value"]), p["label"] == "current"] for p in fig.get("series") or []]
    note = (f"the {u.get('n')} {period_word}s before as the usual range" if u else "") + \
           (f"; a year earlier read {fig['like_for_like']}" if fig.get("like_for_like") else "")
    return Source(id=fig["id"], label=fig["label"], kind="check", columns=["start", "value", "this_range"], rows=rows,
                  sql=fig.get("sql") or "", status=fig.get("status") or "final", facts=facts, note=note.strip("; "),
                  unit=fig.get("unit") or "", better=fig.get("better") or "none")


# ── breakdown ────────────────────────────────────────────────────────────────────────────────

def segment_rows(m: Any, column: str, windows: list, run_sql, dialect: str) -> tuple[list[list[Any]], str, str]:
    """Each segment of ``column`` for the range (``windows[0]``) against its own mean over the usual windows:
    ``(rows, sql, why)``; rows are ``[segment, this_range, usual, change, change_pct, rows, thin]``, furthest from
    usual first, too-few segments last."""
    from aughor.semantic import metric_time as mt

    if not column.replace("_", "").isalnum():
        return [], "", f"{column!r} is not a column name"
    got, why = mt.run_measure(m, windows, run_sql, dialect=dialect, by=column)
    if why:
        return [], "", why
    sql, _ = mt.measure_sql(m, windows, dialect=dialect, by=column)
    current = windows[0].label
    by_group: dict[Any, dict] = {}
    for r in got:
        g = by_group.setdefault(r["group"], {"now": None, "n": 0, "usual": []})
        if r["window"] == current:
            g["now"], g["n"] = r["value"], r["n"]
        elif r["value"] is not None:
            g["usual"].append(r["value"])
    rows = []
    for group, g in by_group.items():
        if g["now"] is None:
            continue
        usual = statistics.fmean(g["usual"]) if g["usual"] else None
        change = None if usual is None else g["now"] - usual
        pct = None if not usual else change / abs(usual)
        rows.append([cell(group), g["now"], usual, change, pct, g["n"], g["n"] < MIN_CELL_ROWS])
    rows.sort(key=lambda r: (r[6], -abs(r[3] or 0)))
    return rows[:MAX_SEGMENTS], sql or "", ""


BREAKDOWN_COLUMNS = ["segment", "this_range", "usual", "change", "change_pct", "rows", "too_few"]


def breakdown(source_id: str, label: str, m: Any, column: str, spec, *, usual_n: int, run_sql, dialect: str,
              unit: str = "", better: str = "none", kind: str = "breakdown", check_id: str = "",
              within: Optional[dict] = None) -> Source:
    """A check broken down by ``column``, each segment against its own usual range. ``check_id`` and ``within``
    (the segment a drill narrowed to) are kept in its facts, so a drill can go one level deeper from it."""
    from aughor.briefing.edition import usual_windows

    windows = [spec.windows()[0]] + usual_windows(spec, usual_n)
    rows, sql, why = segment_rows(m, column, windows, run_sql, dialect)
    if why:
        return Source(id=source_id, label=label, kind=kind, status="refused", error=why, unit=unit, better=better)
    word = spec.period if spec.period in ("day", "week", "month", "year") else "range"
    facts = {"check": check_id, "by": column, "within": dict(within or {})}
    return Source(id=source_id, label=label, kind=kind, columns=BREAKDOWN_COLUMNS, rows=rows, sql=sql, facts=facts,
                  note=f"each {column.replace('_', ' ')} against its own usual: the mean of the {usual_n} {word}s "
                       f"before; under {MIN_CELL_ROWS} rows is too few to call",
                  unit=unit, better=better)


# ── query ────────────────────────────────────────────────────────────────────────────────────

def query(source_id: str, label: str, conn_id: str, sql: str, *, purpose: str, schema: Optional[str] = None,
          run=None) -> Source:
    """A SELECT the model wrote, run through the Data Canvas's guarded door (`converse_tools.run_sql`)."""
    if run is None:
        from aughor.agent.converse_tools import run_sql as run
    out = run(conn_id, {"sql": sql}, user_question=purpose, schema_scope=schema, max_rows=MAX_ROWS)
    if out.get("error"):
        return Source(id=source_id, label=label, kind="query", sql=sql, status="refused", error=str(out["error"]),
                      repair=dict(out.get("repair") or {}), receipts=list(out.get("guard_receipts") or []))
    return Source(id=source_id, label=label, kind="query", columns=[str(c) for c in out.get("columns") or []],
                  rows=_rows(list(out.get("rows") or [])), sql=str(out.get("sql") or sql),
                  receipts=list(out.get("guard_receipts") or []), caveats=[str(c) for c in out.get("caveats") or []],
                  note=purpose + (" (more rows than shown)" if out.get("truncated") else ""))


def for_model(src: Source, *, max_rows: int = 25) -> dict:
    """What the investigating model is shown of a source: its shape, its first rows, what the guards said."""
    out: dict = {"id": src.id, "label": src.label, "kind": src.kind, "status": src.status}
    if src.error:
        out["error"] = src.error
        if src.repair:
            out["repair"] = src.repair.get("instruction") or src.repair
        return out
    out["columns"] = src.columns
    out["rows"] = src.rows[:max_rows]
    if len(src.rows) > max_rows:
        out["rows_not_shown"] = len(src.rows) - max_rows
    if src.facts:
        out["facts"] = {k: v for k, v in src.facts.items() if v is not None and not k.endswith("_text")}
    if src.caveats:
        out["caveats"] = src.caveats
    if src.note:
        out["note"] = src.note
    return out
