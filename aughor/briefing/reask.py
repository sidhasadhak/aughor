"""BR-7, joined to BR-9 (2026-09-26): the explorer's findings RE-ASKED for a range, no model.

The user, on the Week view: *"if for the entire range the return rate is at 10%.. then I click
on e.g. Month then I should get return rate based on the last 30 days, right? … and then
re-index on what to show based on the novelty, impact or whatever scorecard mechanism we
already have"*. A finding keeps the explorer's own SQL and the tables it read (measured live
on theLook: 23 findings, every one with both; 7 single-figure, 16 grouped). So it can be
re-asked without a model: its statement is run over the range and over the previous range,
each table with a main date substituted by itself filtered to the window — the one rewrite
that works on any statement (`metric_statement.scoped_statement`) — and the finding's figure
for the range is read from the result: the value when the query returns one row, and when its
rows are labelled — a status, a category, a department — the ROW THE FINDING'S STATEMENT NAMES,
read the same way for both ranges. A result whose rows are dates is a series over the range,
and reads as the total (or the mean, for a rate) of its measure column. The change between the
two ranges is the scorecard for the range; a finding that cannot be re-asked is listed
APART with the reason, about all history, never silently left in the ranked list.

The figure of a labelled result used to be its total or mean too, and the Briefing's tiles read
"35.18 — mean of percentage_share" (two departments' shares averaged) and "99.8 — total of m_age"
(two average ages added) over a statement about one of them (the user, 2026-10-09: "fix the tile
to show the row the finding is about"). Across labels a total is rarely what the finding means
and a mean almost never is; across days it is the range.
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


#: A value that says WHEN, not which: a range's rows are read across it, never named by it.
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([ T]\d{2}:\d{2}.*)?$")


def _is_date(v: Any) -> bool:
    from datetime import date
    return isinstance(v, date) or (isinstance(v, str) and bool(_DATE_LIKE.match(v.strip())))


def measure_index(cols: list[str], rows: list, measures: list) -> Optional[int]:
    """The column a finding's figure is read from: the first declared measure present, else the
    last numeric column of a multi-column result (never its first, the dimension)."""
    declared = [bare(m) for m in (measures or [])]
    idx = next((i for i, c in enumerate(cols) if bare(c) in declared), None)
    if idx is None:
        # No declared measure names a column: the LAST numeric column, never the first — the
        # derived figure a finding is about comes last (`category, sold_lines, returned_lines,
        # return_rate`; measured live on theLook, where the first numeric was `sold_lines`).
        candidates = range(len(cols)) if len(cols) == 1 else range(len(cols) - 1, 0, -1)
        idx = next((i for i in candidates if any(_num(r[i]) is not None for r in rows if i < len(r))), None)
    return idx


def label_columns(cols: list[str], rows: list, idx: Optional[int], dimensions: list) -> list[int]:
    """The columns that say WHICH thing a row is about: the finding's declared dimensions when the
    result has them, else every text column — never the measure, a number or a date."""
    def labelling(i: int) -> bool:
        vals = [r[i] for r in rows if i < len(r) and r[i] is not None]
        return bool(vals) and all(_num(v) is None and not _is_date(v) for v in vals)
    declared = {bare(d) for d in (dimensions or [])}
    named = [i for i, c in enumerate(cols) if i != idx and bare(c) in declared and labelling(i)]
    return named or [i for i in range(len(cols)) if i != idx and labelling(i)]


def _key(row: list, labels: list[int]) -> tuple[str, ...]:
    return tuple(str(row[i]).strip() for i in labels if i < len(row) and row[i] is not None)


def _said_at(statement: str, label: str) -> Optional[int]:
    """Where a statement says a label as a whole word ("Men" in "Men's", never in "Women"); None
    when it does not. A one-letter code ("M", "a") is never taken as said."""
    if len(label) < 2:
        return None
    m = re.search(r"(?<![A-Za-z0-9])" + re.escape(label) + r"(?![A-Za-z0-9])", statement or "", re.I)
    return m.start() if m else None


def named_row(statement: str, results: list[tuple[list, list]], measures: list,
              dimensions: list) -> tuple[bool, Optional[tuple[str, ...]]]:
    """``(labelled, row)``: whether either range's result labels its rows, and the row the
    finding's statement is about — one whose every label the statement says, the one it says
    first ("Shipped leads with 37,483 orders, followed by Complete…" is about Shipped), the
    longer on a tie ("Pants & Capris" over "Pants"). The range is searched first, then the
    compared range: a row the range has no data for is still the row the finding is about."""
    labelled = False
    for columns, rows in results:
        cols = [str(c) for c in (columns or [])]
        if not cols or not rows:
            continue
        labels = label_columns(cols, rows, measure_index(cols, rows, measures), dimensions)
        if not labels:
            continue
        labelled = True
        best: Optional[tuple[tuple[int, int], tuple[str, ...]]] = None
        for r in rows:
            key = _key(r, labels)
            at = [_said_at(statement, k) for k in key]
            if not key or any(a is None for a in at):
                continue
            rank = (min(a for a in at if a is not None), -sum(len(k) for k in key))
            if best is None or rank < best[0]:
                best = (rank, key)
        if best:
            return True, best[1]
    return labelled, None


def figure_of(columns: list, rows: list, measures: list, *, row: Optional[tuple[str, ...]] = None,
              dimensions: list = ()) -> tuple[Optional[float], str, str, int]:
    """``(value, how, measure, n_rows)`` for a re-asked result. ``how`` is "value" (one row, no
    labels), "row" (the labelled row ``row`` — see :func:`named_row`), "total" or "mean" (a
    series of dates over the range: the total, or the mean when the measure reads as a rate),
    "unnamed" (labelled rows and no row named: there is no one figure to read), or "" (nothing
    numeric). The rows of a named row are combined the way a series is when a date splits it."""
    cols = [str(c) for c in (columns or [])]
    if not cols or not rows:
        return None, "row" if row else "", "", 0
    idx = measure_index(cols, rows, measures)
    if idx is None:
        return None, "", "", len(rows)
    labels = label_columns(cols, rows, idx, dimensions)
    if labels and row is None:
        return None, "unnamed", cols[idx], len(rows)
    if labels:
        wanted = tuple(k.casefold() for k in row or ())
        rows_read = [r for r in rows if tuple(k.casefold() for k in _key(r, labels)) == wanted]
    else:
        rows_read = rows
    vals = [x for x in (_num(r[idx]) for r in rows_read if idx < len(r)) if x is not None]
    how = "row" if labels else ("value" if len(rows) == 1 else "")
    if not vals:
        return None, how, cols[idx], len(rows)
    if len(vals) == 1:
        return vals[0], how or "value", cols[idx], len(rows)
    if _RATE_WORDS.search(cols[idx]):
        return sum(vals) / len(vals), how or "mean", cols[idx], len(rows)
    return sum(vals), how or "total", cols[idx], len(rows)


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
        dims = list(f.get("dimensions") or sig.get("dimensions") or [])
        labelled, row = named_row(str(f.get("finding") or ""), [got["current"][:2], got["previous"][:2]],
                                  measures, dims)
        if labelled and row is None:
            apart.append({"id": fid, "domain": domain,
                          "why": "its statement names none of the rows its query returns, so no one row is its figure"})
            continue
        cur, how, measure, n_cur = figure_of(*got["current"][:2], measures, row=row, dimensions=dims)
        prev, _, _, n_prev = figure_of(*got["previous"][:2], measures, row=row, dimensions=dims)
        if cur is None and prev is None:
            apart.append({"id": fid, "domain": domain, "why": "its data has no rows in this range or the previous one"})
            continue
        reasked.append({
            "id": fid, "domain": domain, "grain": f"{table}.{col}", "measure": measure, "how": how,
            # The labels of the row the finding names ("Shipped"), when its result has labelled rows.
            "row": list(row) if row else None,
            "current": cur, "previous": prev, "rel": _rel(cur, prev),
            "rows_current": n_cur, "rows_previous": n_prev, "sql": got["current"][2],
            # Both statements the figures were read from, so a reader can be shown the rows
            # behind each: "217 vs 184" over the finding's all-history chart could not be
            # connected to either (the user, 2026-10-09).
            "sql_previous": got["previous"][2],
        })
    reasked.sort(key=lambda r: (r["rel"] is None, -abs(r["rel"] or 0.0)))
    return {"covers": words["covers"], "compared_with": words["compared_with"], "key": spec.key,
            "reasked": reasked, "apart": apart, "capped": capped, "duplicates": duplicates}
