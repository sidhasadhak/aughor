"""BR-7, joined to BR-9 (2026-09-26): the explorer's findings RE-ASKED for a range, no model.

The user, on the Week view: *"if for the entire range the return rate is at 10%.. then I click
on e.g. Month then I should get return rate based on the last 30 days, right? … and then
re-index on what to show based on the novelty, impact or whatever scorecard mechanism we
already have"*. A finding keeps the explorer's own SQL and the tables it read (measured live
on theLook: 23 findings, every one with both; 7 single-figure, 16 grouped). So it can be
re-asked without a model: its statement is run over the range and over the previous range,
each table with a main date substituted by itself filtered to the window — the one rewrite
that works on any statement (`metric_statement.scoped_statement`) — and the finding's figure
for the range is read from the result: the value when the query returns one row, else the
total (or the mean, for a rate) of its measure column over the rows. The change between the
two ranges is the scorecard for the range; a finding that cannot be re-asked is listed
APART with the reason, about all history, never silently left in the ranked list.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from aughor.semantic.metric_statement import bare, scoped_statement, statement_tables

#: A measure whose rows must be averaged, not summed, when the range returns several.
_RATE_WORDS = re.compile(r"rate|ratio|share|pct|percent|avg|average|mean|per_|margin", re.I)
#: The most findings re-asked for one range (two warehouse queries each); the rest are said.
MAX_REASKED = 40


def grain_for(sql: str, tables: list, profile_entry: dict, dialect: str) -> tuple[Optional[str], str, str]:
    """``(table, column, why_not)``: the first table the statement reads that the profiler
    gave a main date, written as the statement writes it. ``(None, "", why)`` when none has one."""
    from aughor.semantic.metric_time import primary_date

    read = statement_tables(sql, dialect) or [str(t) for t in (tables or []) if str(t).strip()]
    if not read:
        return None, "", "its SQL names no table"
    for t in read:
        col = primary_date(profile_entry or {}, bare(t))
        if col:
            return t, col, ""
    return None, "", f"no date on {', '.join(bare(t) for t in read)}"


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def figure_of(columns: list, rows: list, measures: list) -> tuple[Optional[float], str, str, int]:
    """``(value, how, measure, n_rows)`` for a re-asked result: the measure column is the first
    declared measure present, else the first numeric column that is not the first column of
    a multi-column result; one row → its value; several → the total, or the mean when the
    measure reads as a rate. ``how`` is "value" | "total" | "mean" | "" (nothing numeric)."""
    cols = [str(c) for c in (columns or [])]
    if not cols or not rows:
        return None, "", "", 0
    declared = [bare(m) for m in (measures or [])]
    idx = next((i for i, c in enumerate(cols) if bare(c) in declared), None)
    if idx is None:
        candidates = range(len(cols)) if len(cols) == 1 else range(1, len(cols))
        idx = next((i for i in candidates if any(_num(r[i]) is not None for r in rows if i < len(r))), None)
    if idx is None:
        return None, "", "", len(rows)
    vals = [x for x in (_num(r[idx]) for r in rows if idx < len(r)) if x is not None]
    if not vals:
        return None, "", cols[idx], len(rows)
    if len(rows) == 1:
        return vals[0], "value", cols[idx], 1
    if _RATE_WORDS.search(cols[idx]):
        return sum(vals) / len(vals), "mean", cols[idx], len(rows)
    return sum(vals), "total", cols[idx], len(rows)


def _rel(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev)


def reask_findings(findings: list[dict], spec: Any, *, run_sql: Callable[[str], tuple], dialect: str,
                   profile_entry: dict) -> dict:
    """Every finding re-asked for ``spec``'s range and its previous range. Returns
    ``{"reasked": [...], "apart": [...], "capped": n, "duplicates": n}``; every distinct finding
    lands in exactly one list, ``reasked`` ordered by the size of the change (unknown change last)."""
    from aughor.briefing.ranges import phrases
    from aughor.semantic.metric_time import window_predicate

    words = phrases(spec)
    reasked: list[dict] = []
    apart: list[dict] = []
    # The aggregate view of a connection lists a pinned finding once per schema it appears in
    # (measured on theLook: `pinned__2` twice); the same statement is re-asked once and said.
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for f in findings:
        key = (str(f.get("id") or ""), str(f.get("sql") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    duplicates = len(findings) - len(unique)
    capped = max(0, len(unique) - MAX_REASKED)
    for f in unique[:MAX_REASKED]:
        fid, domain = str(f.get("id") or ""), str(f.get("domain") or "")
        sql = str(f.get("sql") or "").strip()
        sig = f.get("signature") if isinstance(f.get("signature"), dict) else {}
        tables = list(sig.get("tables") or [])
        measures = list(sig.get("measures") or f.get("measures") or [])
        if not sql:
            apart.append({"id": fid, "domain": domain, "why": "it kept no SQL"})
            continue
        table, col, why = grain_for(sql, tables, profile_entry, dialect)
        if table is None:
            apart.append({"id": fid, "domain": domain, "why": why})
            continue
        got: dict[str, tuple] = {}
        failed = ""
        for label, start, end in (("current", spec.start, spec.end), ("previous", spec.previous_start, spec.previous_end)):
            scoped, why, _ = scoped_statement(sql, table, window_predicate(col, start, end), dialect=dialect)
            if scoped is None:
                failed = why
                break
            try:
                columns, rows, err = run_sql(scoped)
            except Exception as exc:  # noqa: BLE001 — a query that fails is said on the finding, never raised over the list
                columns, rows, err = [], [], f"{type(exc).__name__}: {exc}"
            if err:
                failed = f"its query failed for {label}: {str(err)[:160]}"
                break
            got[label] = (columns, rows, scoped)
        if failed:
            apart.append({"id": fid, "domain": domain, "why": failed})
            continue
        cur, how, measure, n_cur = figure_of(*got["current"][:2], measures)
        prev, _, _, n_prev = figure_of(*got["previous"][:2], measures)
        if cur is None and prev is None:
            apart.append({"id": fid, "domain": domain, "why": "its data has no rows in this range or the previous one"})
            continue
        reasked.append({
            "id": fid, "domain": domain, "grain": f"{table}.{col}", "measure": measure, "how": how,
            "current": cur, "previous": prev, "rel": _rel(cur, prev),
            "rows_current": n_cur, "rows_previous": n_prev, "sql": got["current"][2],
        })
    reasked.sort(key=lambda r: (r["rel"] is None, -abs(r["rel"] or 0.0)))
    return {"covers": words["covers"], "compared_with": words["compared_with"], "key": spec.key,
            "reasked": reasked, "apart": apart, "capped": capped, "duplicates": duplicates}
