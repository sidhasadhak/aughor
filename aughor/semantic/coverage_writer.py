"""Arc MC, MC-5 — the knowledge base's patterns written for this schema, one scoped model call per open area
(ROADMAP §3.62; the user's call, 2026-10-26, §6 item 55(c): automatically when a connection is profiled).

A pattern's template is written against canonical names (`orders o`, `status = 'cancelled'`); a connection's tables and
columns differ. Each area that has data and patterns no metric there computes yet gets ONE call — an area thin on metrics
is as open as one with none: LuxExperience's Traffic & conversion had one metric beside 22 patterns — handed only those
patterns (their definitions, templates and traps), the metrics already measured there, and only that area's tables (with
the tables they join to on a key), with the profiler's statistics, and asked which patterns the data supports and to
write each for these tables. The count follows the patterns the data supports, not a prompt. An area the knowledge base
carries no pattern for, with no working metric, is handed the generic layer's kinds instead, and its proposals say they
came from no pattern.

Code checks what the model wrote before the gates read its figures (MC-5's falsifier):

- **it reads its area** — every table its statement reads is one the call was given;
- **it computes its pattern** — the pattern it cites is one of its area's, and the statement computes that kind of
  figure: a rate divides, a volume counts, a value sums or averages, a duration subtracts two moments.

The model proposes; it never approves, and its words are never a source (`llm_inferred` provenance does not exist): a
proposal is a draft a person adopts through the door that exists, or declines.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: Tables handed to one call, largest first — an area's own and the ones they join to.
MAX_TABLES = 10
#: Columns described per table.
MAX_COLUMNS = 30
#: Patterns handed to one call.
MAX_PATTERNS = 14
#: The fewest rows a table joined on a key must hold to be handed beside an area's own — live 2026-10-26, every call on
#: LuxExperience was handed `financial_summary`, `ownership` and `platforms` (25, 12 and 5 rows, keyed by platform).
NEIGHBOUR_MIN_ROWS = 100


class _Proposal(BaseModel):
    pattern_id: str = Field(description="The id of the pattern this computes, copied exactly; \"\" when it computes "
                                        "none of the patterns given")
    name: str = Field(description="snake_case id for the metric")
    label: str = Field(description="The name a person reads")
    definition: str = Field(description="One sentence: what it measures, over which rows")
    sql: str = Field(description="One runnable SELECT returning ONE row and ONE numeric column, over the tables given")
    time_column: str = Field(description="table.column — the date or timestamp of a table the statement reads, that "
                                         "dates each row the figure is made of")
    unit: str = ""


class _Skipped(BaseModel):
    pattern_id: str
    why: str


class _Written(BaseModel):
    proposals: list[_Proposal] = Field(default_factory=list)
    skipped: list[_Skipped] = Field(default_factory=list)


_SYSTEM = (
    "You write business metrics for ONE area of a business, over the tables you are given and nothing else. You are "
    "handed the area's metric patterns from a curated knowledge base — each with its definition, its canonical "
    "template (written against canonical table names, not these), and its traps — and the area's real tables with "
    "their columns, types, null rates and row counts.\n"
    "For each pattern the data supports, write it for THESE tables: one SELECT statement in the dialect named, "
    "returning ONE row with ONE numeric column, aggregating over all rows (no date filter — the platform windows it "
    "by the time_column you name). Name the pattern you computed by its id, exactly. Keep the pattern's grain and avoid "
    "its traps: a rate keeps its full population in the denominator; pre-aggregate before a join that fans out.\n"
    "Write a pattern only when the columns it needs exist. List every pattern you did not write in `skipped` with why "
    "(the column it needs is missing, the table has no date, …). Never read a table that is not given. Never invent a "
    "column. When no pattern is given, write the metrics a person running this area reads, each citing no pattern."
)


def _computes(kind: str, sql: str, dialect: str) -> str:
    """Why the statement does not compute ``kind`` — or "" when it does."""
    import sqlglot
    from sqlglot import exp

    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception as exc:  # noqa: BLE001 — a statement that does not parse fails the runs gate, said there
        return f"its statement does not parse ({type(exc).__name__})"
    has = lambda *types: any(True for _ in tree.find_all(*types))  # noqa: E731
    if kind == "rate":
        return "" if has(exp.Div, exp.SafeDivide) else "it cites a rate, and its statement divides nothing"
    if kind == "volume":
        return "" if has(exp.Count) else "it cites a volume, and its statement counts nothing"
    if kind == "value":
        return "" if has(exp.Sum, exp.Avg) else "it cites a value, and its statement neither sums nor averages"
    if kind == "duration":
        diffs = (exp.DateDiff, exp.TimestampDiff, exp.DatetimeDiff, exp.Sub, exp.Extract)
        named = any(any(w in c.name.lower() for w in ("day", "hour", "minute", "sec", "duration", "time"))
                    for agg in tree.find_all(exp.Avg, exp.Sum) for c in agg.find_all(exp.Column))
        return "" if (has(*diffs) or named) else "it cites a duration, and its statement subtracts no two moments"
    if kind == "quality":
        return "" if has(exp.Avg, exp.Div) else "it cites a quality, and its statement neither averages nor divides"
    return ""


def _neighbours(area_tables: list[str], facts: dict, entry: dict) -> list[str]:
    """Tables an area's tables join to on a key: one carries a column named as the other's grain column."""
    grains = {name: str((tp or {}).get("grain_column") or "").lower()
              for name, tp in ((entry or {}).get("tables") or {}).items() if isinstance(tp, dict)}
    grains = {k.split(".")[-1].lower(): v for k, v in grains.items() if v}
    out: list[str] = []
    for t in area_tables:
        mine = set((facts.get(t).columns if facts.get(t) else {}).keys())
        for other, grain in grains.items():
            if other in area_tables or other in out or other not in facts:
                continue
            theirs = set(facts[other].columns)
            if (facts[other].rows or 0) < NEIGHBOUR_MIN_ROWS:
                continue                    # a lookup of a handful of rows keyed like a fact is not what an area reads
            if grain in mine or (grains.get(t) and grains[t] in theirs):
                out.append(other)
    return out


def _table_block(t, entry: dict) -> str:
    cols = []
    profiles = (entry or {}).get("columns") or {}
    for col, dtype in list(t.columns.items())[:MAX_COLUMNS]:
        cp = next((v for k, v in profiles.items() if isinstance(v, dict)
                   and str(v.get("table") or k.split(".", 1)[0]).split(".")[-1].lower() == t.name
                   and str(v.get("column") or "").lower() == col), {})
        bits = [dtype]
        if cp.get("null_rate"):
            bits.append(f"{float(cp['null_rate']):.0%} empty")
        if cp.get("is_low_cardinality") and cp.get("top_values"):
            tops = [str(v.get("value") if isinstance(v, dict) else v) for v in (cp.get("top_values") or [])[:5]]
            bits.append("values " + ", ".join(tops))
        elif cp.get("value_range"):
            bits.append(f"range {cp['value_range']}")
        cols.append(f"    {col}: {'; '.join(bits)}")
    head = f"TABLE {t.name} ({t.rows:,} rows)" if t.rows else f"TABLE {t.name}"
    if t.date_column:
        head += f" — main date {t.date_column}"
    return head + "\n" + "\n".join(cols)


def write(connection_id: str, schema_name: Optional[str], mmap, *, db, taken: list) -> tuple[list[dict], dict]:
    """One call per uncovered area with data. Returns ``(proposals, spend)``; each proposal carries the area and pattern
    gates read here, and the run reads the rest."""
    from aughor.llm.provider import get_provider
    from aughor.semantic import coverage_proposals as CP
    from aughor.semantic.metric_coverage import coverage
    from aughor.semantic.metric_map import generic_patterns, match_pattern
    from aughor.semantic.metric_statement import statement_tables
    from aughor.semantic.metric_coverage import tables_of
    from aughor.tools.profile_cache import merged_profile_entry

    matrix = coverage(connection_id, schema_name, figures=True, mmap=mmap)
    facts = {t.name: t for t in tables_of(connection_id, schema_name)}
    entry = merged_profile_entry(connection_id) or {}
    dialect = getattr(db, "dialect", "") or "duckdb"
    taken_names = {CP.metric_name(p.get("name") or "") for p in taken}
    llm = get_provider("coder")
    spend = {"calls": 0, "model": str(getattr(llm, "_model", "") or ""), "at": CP.now(), "areas": []}
    out: list[dict] = []
    for row in matrix["areas"]:
        if not row.get("writable"):
            continue
        area = mmap.area(row["id"])
        if area is None:
            continue
        # this run's code proposals count as written: a recipe or a derived metric is not handed to the model again
        mine = [p for p in taken if p.get("area") == area.id]
        done = {p.get("pattern") for p in mine if p.get("pattern")}
        for p in mine:
            hit = match_pattern(str(p.get("name") or ""), str(p.get("label") or ""), area.patterns)
            if hit is not None:
                done.add(hit.id)
        opened = set(row.get("open_patterns") or []) - done
        no_pattern = not area.proposable_patterns
        patterns = generic_patterns() if no_pattern else [p for p in area.proposable_patterns if p.id in opened][:MAX_PATTERNS]
        if not patterns:
            continue
        own = [t["name"] for t in row["tables"] if t["rows"]][:MAX_TABLES]
        given = own + _neighbours(own, facts, entry)[: max(0, MAX_TABLES - len(own))]
        measured = [m["label"] for m in row["metrics"]] + [str(p.get("label") or "") for p in mine]
        block = "\n\n".join(
            f"PATTERN {p.id} — {p.title} [{p.kind}, {p.direction} is good]\n  definition: {p.definition[:400]}"
            + (f"\n  canonical template: {p.template[:500]}" if p.template else "")
            + "".join(f"\n  trap: {a[:220]}" for a in p.anti_patterns[:3])
            for p in patterns)
        tables = "\n\n".join(_table_block(facts[t], entry) for t in given if t in facts)
        user = (f"DIALECT: {dialect}\nAREA: {area.name} — {area.question}\n"
                + (f"ALREADY MEASURED here (do not write these again): {', '.join(measured)}\n" if measured else "")
                + ("\nNO PATTERN covers this area yet. The kinds a metric can be:\n" if no_pattern else "\nPATTERNS:\n")
                + block + f"\n\nTABLES (the only ones you may read):\n{tables}")
        record = {"area": area.id, "name": area.name, "tables": given, "patterns": len(patterns), "proposals": 0,
                  "skipped": [], "error": ""}
        spend["calls"] += 1
        try:
            got: _Written = llm.complete(system=_SYSTEM, user=user, response_model=_Written, temperature=0.1)
        except Exception as exc:  # noqa: BLE001 — a call that fails is said on the coverage view, the run goes on
            record["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            spend["areas"].append(record)
            continue
        by_id = {p.id: p for p in patterns}
        for w in got.proposals:
            name = CP.metric_name(w.name or w.label)
            if not name or name in taken_names:
                continue
            taken_names.add(name)
            sql = (w.sql or "").strip().rstrip(";")
            try:
                read = [t.split(".")[-1].lower() for t in statement_tables(sql, dialect)]
            except Exception:  # noqa: BLE001 — the runs gate says a statement that does not parse
                read = []
            outside = [t for t in read if t not in given]
            pattern = by_id.get(w.pattern_id) if w.pattern_id else None
            if w.pattern_id and pattern is None:
                pattern_gate = {"ok": False, "why": f"it cites {w.pattern_id}, which is not one of its area's patterns"}
            elif pattern is not None:
                why = _computes(pattern.kind, sql, dialect)
                pattern_gate = {"ok": not why, "why": why or f"it computes {pattern.title}"}
            else:
                pattern_gate = {"ok": True, "why": "it cites no pattern"}
            time_column = (w.time_column or "").strip()
            if time_column and time_column.count(".") >= 1:
                table, column = time_column.rsplit(".", 1)
                time_column = f"{table.split('.')[-1].lower()}.{column}"
            out.append({
                "name": name, "label": w.label or w.name, "area": area.id,
                "source": CP.SOURCE_AREA if (no_pattern or pattern is None) else CP.SOURCE_PATTERN,
                "pattern": pattern.id if pattern else "", "pattern_title": pattern.title if pattern else "",
                "pack_id": pattern.pack_id if pattern else "", "kind": pattern.kind if pattern else "",
                "direction": pattern.direction if pattern else "", "definition": w.definition, "unit": w.unit,
                "sql": sql, "tables": read, "time_column": time_column, "time_kind": "flow",
                "gates": {"area": ({"ok": False, "why": (f"it reads {', '.join(outside)}, which its area was not "
                                                         "given")} if outside else {"ok": True, "why": ""}),
                          "pattern": pattern_gate},
                "written_by": spend["model"] or "a model", "made_at": CP.now()})
            record["proposals"] += 1
        record["skipped"] = [{"pattern": s.pattern_id, "why": s.why[:200]} for s in got.skipped][:20]
        spend["areas"].append(record)
    spend["done_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out, spend
