"""What the data holds, for the tables a question was given — PENDING item 19 (`grounding.data_profiles`).

An ML engineer's review (docs/ENGINE_REVIEW_ANSWERS_2026-09-24.md §3) named the gap: the model
writing SQL attends to the warehouse's SCHEMA and to five head rows per table, never to its data.
The profiler has measured the data all along — row counts, date ranges, distinct counts, null
rates, ranges and medians, the values a low-cardinality column takes — and cached it
(`tools/profile_cache.py`); the Data Catalog replaced the schema string those numbers would have
ridden, and they reached no SQL prompt.

This renders them for the LINKED tables only, from the cache only (a question never pays for
profiling), under a character budget, key columns left out. A table the budget cannot fit is
named as left out rather than dropped in silence. Off by default: it changes the prompt, and a
prompt change ships on a measurement (kernel/flags.py EXPERIMENT).
"""
from __future__ import annotations

from typing import Optional

FLAG = "grounding.data_profiles"

#: Enough for the linked tables of a typical question (≈4 tables × a dozen columns worth
#: showing), small against the 20k/60k schema budgets the linker packs to.
DEFAULT_BUDGET = 2400

_TOP_VALUES = 6


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def _bare(name: str) -> str:
    return str(name or "").rsplit(".", 1)[-1].lower()


def _num(value) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f.is_integer() and abs(f) < 1e15:
        return f"{int(f):,}"
    return f"{f:,.2f}"


def _column_line(d: dict) -> Optional[str]:
    """One column's measured facts, or None when there is nothing worth a line."""
    kind = (d.get("semantic_type") or "").lower()
    if kind == "key" or d.get("is_fk"):
        return None
    name = d.get("column") or ""
    null = float(d.get("null_rate") or 0.0)
    parts: list[str] = []
    top = [str(v) for v in (d.get("top_values") or [])][:_TOP_VALUES]
    vr = d.get("value_range")
    if top:
        # The profiler's distinct count is an ESTIMATE on most engines (DuckDB's SUMMARIZE,
        # Postgres' n_distinct) and can undercount — "5 values:" above a list of six, measured on
        # the samples warehouse — and a short list is not proof of a complete one (Postgres'
        # most_common_vals is never complete). So the list is only ever "most frequent", and a
        # count appears only as "about", when it exceeds what is listed.
        distinct = int(d.get("distinct_count") or 0)
        values = ", ".join(f"'{v}'" for v in top)
        if distinct > len(top):
            parts.append(f"about {_num(distinct)} values, most frequent: {values}…")
        else:
            parts.append(f"most frequent values: {values}")
    elif kind == "measure" and vr and len(vr) == 2:
        rng = f"{_num(vr[0])} to {_num(vr[1])}"
        if d.get("p50") is not None:
            rng += f", median {_num(d['p50'])}"
        unit = d.get("unit") or d.get("value_interpretation")
        parts.append(rng + (f" ({unit})" if unit else ""))
    elif vr and len(vr) == 2 and ("date" in str(d.get("dtype", "")).lower()
                                   or "time" in str(d.get("dtype", "")).lower()):
        parts.append(f"{vr[0]} to {vr[1]}")
    if null >= 0.2:
        parts.append(f"{null:.0%} null")
    if not parts:
        return None
    return f"  {name}: " + "; ".join(parts)


def _table_line(table: str, profile: dict) -> str:
    line = f"{table}"
    if profile.get("row_count") is not None:
        line += f": {_num(profile['row_count'])} rows"
    dr = profile.get("date_range")
    if dr and len(dr) == 2:
        line += f", {dr[0]} to {dr[1]}"
        if profile.get("primary_timestamp"):
            line += f" (by {profile['primary_timestamp']})"
    return line


def render(connection_id: str, tables: list[str], *, budget: int = DEFAULT_BUDGET) -> str:
    """The DATA PROFILE block for ``tables``, or ``""`` when the cache holds nothing for them.

    Read-only against the profile cache: nothing here runs SQL. Tables in the order given (the
    linker's rank), each whole or not at all."""
    from aughor.tools.profile_cache import latest_profile_entry
    entry = latest_profile_entry(connection_id) or {}
    table_profiles = {_bare(t): d for t, d in (entry.get("tables") or {}).items()
                      if isinstance(d, dict)}
    by_table: dict[str, list[dict]] = {}
    for d in (entry.get("columns") or {}).values():
        if isinstance(d, dict) and d.get("table"):
            by_table.setdefault(_bare(d["table"]), []).append(d)

    header = ("DATA PROFILE — measured by the profiler over the whole table, not a sample. Filter "
              "on the values shown; check a result's magnitude against the ranges:")
    lines, used, left_out = [header], len(header) + 1, []
    for table in tables:
        key = _bare(table)
        if key not in table_profiles and key not in by_table:
            continue
        block = [_table_line(table, table_profiles.get(key, {}))]
        block += [line for d in by_table.get(key, []) if (line := _column_line(d))]
        text = "\n".join(block)
        if used + len(text) + 1 > budget:
            left_out.append(table)
            continue
        lines.append(text)
        used += len(text) + 1
    if len(lines) == 1:
        return ""
    if left_out:
        lines.append(f"(profiles for {', '.join(left_out)} are left out to keep this block under "
                     f"{budget:,} characters)")
    return "\n".join(lines)
