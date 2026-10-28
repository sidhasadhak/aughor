"""Arc MC, MC-3 / MC-4 / MC-6 — metrics proposed for the areas a connection's data covers, every one through the gates
(ROADMAP §3.62).

The proposals the explorer made were "the 6-8 metrics … that matter MOST" — a count in a prompt. These follow the map
(`metric_map`) and the data, cheapest first, and none is shown before the gates have read its figures:

- **recipes bound to roles (MC-3, code).** A package's typed recipe whose roles this connection has bound, its formula
  resolved over the bound columns. Its verdict — runs, a window bounds it, it moves, in its sane range, its roles bound
  to the right columns — is kept here and read by the catalogue's industry row, so the row a person adopts says it.
- **derived from the ontology (MC-4, code).** Each promise a person declared and the data measured gives its ON-TIME
  RATE; each stage after another gives its CONVERSION; each measured rule gives its SHARE of the whole — compiled
  through the object door, so "late" means what the promise says, and counted against the ontology's own measurement
  at the same moment (MC-4's falsifier: a derived count that differs is refused, with both counts).
- **blind spots (MC-6, code).** A profiled measure the explorer's findings keep aggregating — three findings or more —
  with no metric reading it.
- **the knowledge base's patterns written for this schema (MC-5, one model call per area)** — `coverage_writer`.

A proposal that fails a gate is kept, with the gate and why, and is NOT adoptable (MC-3's falsifier). A model never
approves; a proposal becomes a metric only when a person adopts it through the door that exists.

Kept beside the business profile it was made for (`business_profile.store.save_coverage`) — the explorer's proposals'
own store, not a new one.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

STATE_PROPOSED = "proposed"
STATE_GATE_FAILED = "gate_failed"

SOURCE_RECIPE = "recipe"
SOURCE_ONTOLOGY = "ontology"
SOURCE_PATTERN = "pattern"
SOURCE_AREA = "area"            # written for an area the knowledge base has no pattern for
SOURCE_BLIND_SPOT = "blind_spot"

#: Findings that must aggregate one measure, with no metric reading it, before it is proposed (MC-6's N).
BLIND_SPOT_FINDINGS = 3

#: The date fields a proposal is measured by — a cohort needs its outcome, a stock its until.
_DATE_FIELDS = ("time_column", "time_kind", "outcome_column", "until_column", "settles_after_days")

GATE_ORDER = ("runs", "dated", "window", "area", "pattern", "count", "binding", "moves", "sane_range", "twin")
GATE_WORDS = {"runs": "it runs", "dated": "it has a date", "window": "a window bounds it", "area": "it reads its area",
              "pattern": "it computes its pattern", "count": "it counts what the ontology counts",
              "binding": "its roles are bound to the right columns", "moves": "it moves",
              "sane_range": "it sits in its sane range", "twin": "no approved metric measures the same"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def metric_name(text: str) -> str:
    from aughor.semantic.metric_catalogue import normalize_name
    return normalize_name(text)


# ── the gates, over one proposal ────────────────────────────────────────────────────────────────────────────────────

def definition_of(p: dict, connection_id: str, schema_name: Optional[str]):
    """The proposal as the definition it would become — what every gate reads."""
    from aughor.semantic.metrics import ALL_DATASETS, MetricDefinition
    dates = {k: v for k, v in (p.get("dates") or {}).items() if v not in (None, "")}
    dates.setdefault("time_column", p.get("time_column") or None)
    dates.setdefault("time_kind", p.get("time_kind") or ("flow" if p.get("time_column") else None))
    return MetricDefinition(
        name=p["name"], label=p.get("label") or p["name"], sql=p.get("sql") or "", connection=connection_id,
        schema_name=schema_name or ALL_DATASETS, tables=list(p.get("tables") or []),
        lineage=[f"coverage: {p.get('area') or ''} · {p.get('pattern') or p.get('source')}"], status="proposed",
        **dates)


def _first_number(rows: list) -> Optional[float]:
    from aughor.semantic.metric_gates import as_float
    for row in rows or []:
        cells = list(row.values()) if isinstance(row, dict) else list(row)
        for c in cells:
            if (v := as_float(c)) is not None:
                return v
    return None


def _date_type(time_column: str, columns: Optional[dict]) -> str:
    """The profiled type of a proposal's date column, or "" when the profiler did not read it."""
    table, _, col = str(time_column or "").rpartition(".")
    want = (table.split(".")[-1].lower(), col.lower())
    for key, prof in (columns or {}).items():
        if isinstance(prof, dict):
            t = str(prof.get("table") or str(key).split(".", 1)[0]).split(".")[-1].lower()
            if (t, str(prof.get("column") or str(key).split(".", 1)[-1]).lower()) == want:
                return str(prof.get("dtype") or "")
    return ""


def gate(p: dict, *, connection_id: str, schema_name: Optional[str], run_sql: Callable[[str], tuple], dialect: str,
         approved: list, band: Optional[dict] = None, band_label: str = "", columns: Optional[dict] = None) -> dict:
    """Read every gate a proposal can be read by, in order, into ``p["gates"]``; set its state and the first failing
    gate's reason. Gates that do not apply to its source were set by its proposer (area, pattern, count, binding) or
    are left out."""
    from aughor.semantic import metric_gates, metric_time
    from aughor.semantic.metric_twins import twin_of

    gates: dict = dict(p.get("gates") or {})
    m = definition_of(p, connection_id, schema_name)
    sql = (p.get("sql") or "").strip()
    if not sql:
        gates["runs"] = {"ok": False, "why": "it has no statement"}
    else:
        try:
            _cols, rows, error = run_sql(sql)
        except Exception as exc:  # noqa: BLE001 — a statement that raises is one that does not run
            _cols, rows, error = [], [], f"{type(exc).__name__}: {exc}"
        if error:
            gates["runs"] = {"ok": False, "why": f"it does not run: {str(error).strip()[:240]}"}
        elif _first_number(rows) is None:
            gates["runs"] = {"ok": False, "why": "it runs and returns no number"}
        else:
            gates["runs"] = {"ok": True, "why": ""}
            p["value"] = _first_number(rows)
    if gates["runs"]["ok"]:
        if not m.time_column:
            gates["dated"] = {"ok": False, "why": "no date on the tables it reads dates it, so no period has a figure"}
        elif metric_gates.column_kind(dtype := _date_type(m.time_column, columns)) in ("integer", "number"):
            # Live 2026-10-26: the writer dated LuxExperience's cost per click by `marketing_campaigns.fiscal_year` —
            # a year is a number, not a day, so no day, week or month of it exists.
            gates["dated"] = {"ok": False, "why": (f"its date, {m.time_column}, is {dtype} — a number, not a day, so no "
                                                   "day, week or month has a figure")}
        else:
            gates["dated"] = {"ok": True, "why": ""}
            ok, why = metric_time.measurable(m)
            gates["window"] = {"ok": ok, "why": why}
    # A statement that does not run, or that no window can bound, has no figures to read; a wrong binding, a table
    # outside its area or a miscount still has, and they are read so the refusal can say both.
    if all((gates.get(g) or {}).get("ok") is not False for g in ("runs", "dated", "window")):
        figures, months, why = metric_gates.recent_figures(m, run_sql, dialect)
        p["figures"], p["months"] = figures, months
        gates["moves"] = metric_gates.moves(figures, why)
        if figures is None:
            # A definition already approved is never refused for figures that could not be read; a PROPOSAL is not
            # offered until they are — adopting it would make a metric no period can measure.
            gates["moves"]["ok"] = False
        if band:
            gates["sane_range"] = metric_gates.sane(figures, band, band_label or "its recipe")
        if gates["moves"].get("ok") is not False and approved:
            from aughor.briefing.ranges import data_span
            last = data_span(m, run_sql, dialect)[1]
            if last is not None:
                twin = twin_of(m, approved, run_sql=run_sql, dialect=dialect, today=last + timedelta(days=1))
                if twin.get("twin"):
                    t = twin["twin"]
                    gates["twin"] = {"ok": False, "why": (f"it measures exactly what {t['label']} measures — the same "
                                                          f"figure in each of the last {twin['months']} months")}
                else:
                    gates["twin"] = {"ok": True, "why": ""}
    p["gates"] = {g: gates[g] for g in GATE_ORDER if g in gates}
    failed = next(((g, v) for g, v in p["gates"].items() if v.get("ok") is False), None)
    p["state"] = STATE_GATE_FAILED if failed else STATE_PROPOSED
    p["reason"] = f"{GATE_WORDS[failed[0]]} — no: {failed[1]['why']}" if failed else ""
    p["checked_at"] = now()
    return p


# ── MC-3: the recipes bound to roles ────────────────────────────────────────────────────────────────────────────────

def binding_fingerprint(bound: dict) -> str:
    return hashlib.sha256(json.dumps(bound or {}, sort_keys=True, default=str).encode()).hexdigest()[:16]


def recipe_proposals(connection_id: str, schema_name: Optional[str], mmap) -> list[dict]:
    """Each recipe of the map whose roles this connection has bound, resolved over the bound columns, with its binding
    read by the binding gate. A recipe whose roles are not bound is the catalogue's `needs_binding` row, said there."""
    from aughor.packs.bindings import load_binding
    from aughor.packs.loader import load_pack
    from aughor.packs.knowledge import packages
    from aughor.semantic.metric_catalogue import resolve_roles
    from aughor.semantic.metric_gates import binding_problems
    from aughor.semantic.metric_statement import as_statement
    from aughor.semantic.metric_time import with_dates
    from aughor.semantic.metric_coverage import dataset_entry

    ds = schema_name or ""
    columns = (dataset_entry(connection_id, schema_name) or {}).get("columns") or {}
    dirs = {p.pack_id: p.directory for p in packages()}
    out: list[dict] = []
    for area in mmap.areas:
        for r in area.recipes:
            bound = ((load_binding(r.pack_id, connection_id, ds) or {}).get("bindings") or {})
            if any(role not in bound for role in r.required_roles):
                continue
            sql, unresolved = resolve_roles(r.formula, r.pack_id, connection_id, ds or None)
            if unresolved:
                continue
            tables = [t for t in dict.fromkeys(str((bound.get(role) or {}).get("table") or "")
                                               for role in r.required_roles) if t]
            statement = as_statement(sql, tables, [], r.name)
            p = {"name": r.name, "label": r.title, "area": area.id, "source": SOURCE_RECIPE, "pattern": "",
                 "pack_id": r.pack_id, "definition": r.definition, "sql": statement, "tables": tables,
                 "sane_range": r.sane_range, "binding_fingerprint": binding_fingerprint(bound), "made_at": now()}
            dated = with_dates(connection_id, definition_of(p, connection_id, schema_name))
            p["time_column"], p["time_kind"] = dated.time_column or "", dated.time_kind or ""
            p["dates"] = {k: getattr(dated, k) for k in _DATE_FIELDS if getattr(dated, k, None) not in (None, "")}
            try:
                pack = load_pack(dirs[r.pack_id])
                problems = binding_problems(r.formula, pack.entities, bound, columns)
            except Exception as exc:  # noqa: BLE001 — a binding unread is said, never passed
                problems, unread = [], f"its binding could not be read ({type(exc).__name__})"
                p["gates"] = {"binding": {"ok": None, "why": unread}}
            else:
                p["gates"] = {"binding": {"ok": not problems, "why": "; ".join(problems)}}
            out.append(p)
    return out


# ── MC-4: what the ontology's declarations derive ───────────────────────────────────────────────────────────────────

def _negate(condition: dict) -> Optional[dict]:
    flip = {">": "<=", ">=": "<", "<": ">=", "<=": ">", "=": "!=", "!=": "="}
    op = condition.get("op")
    if op not in flip:
        return None
    return {**condition, "op": flip[op]}


def _column_of(graph, object_type: str, path: str) -> str:
    """``table.column`` the property ``path`` of ``object_type`` lands on, or ""."""
    from aughor.semantic.object_query import ObjectQueryRefused, property_at
    try:
        entity, prop, _links = property_at(graph, object_type, path)
    except ObjectQueryRefused:
        return ""
    table = (entity.source_tables or [""])[0]
    return f"{str(table).split('.')[-1]}.{prop.name}" if table else ""


def _compile(graph, entity_api: str, measure: dict, dialect: str) -> str:
    from aughor.semantic.object_query import compile_object_query
    return compile_object_query({"object_type": entity_api, "measures": [measure]}, graph, dialect=dialect).sql


def ontology_proposals(connection_id: str, schema_name: Optional[str], graph, db, mmap) -> list[dict]:
    """Each measured promise's on-time rate, each measured stage's conversion from the one before, each measured rule's
    share — compiled through the object door, and counted against the ontology's own filters at the same moment."""
    from aughor.ontology.derived import promise_filters, promise_noun, rule_filters
    from aughor.ontology.processes import NotMeasurable, ObjectCounter, cell_int, reached_filters
    from aughor.semantic.metric_map import OTHER, best_areas

    if graph is None:
        return []
    from aughor.semantic.metric_coverage import tables_of

    dialect = getattr(db, "dialect", "") or "duckdb"
    counter = ObjectCounter(db, graph)
    named = [a for a in mmap.areas if not a.generic]
    dates = {t.name: t.date_column for t in tables_of(connection_id, schema_name)}
    out: list[dict] = []

    def area_of(*texts: str) -> str:
        for text in texts:
            hits = best_areas(text, named)
            if hits:
                return hits[0][0].id
        return OTHER

    def counts(entity_api: str, filters: list[list]) -> Optional[list[int]]:
        """One count per filter list, read through one counter — the ontology's own way to the data."""
        try:
            got = counter.one(entity_api, [{"name": f"n{i}", "agg": "count", "where": w} for i, w in enumerate(filters)])
        except NotMeasurable as exc:
            logger.info("derived proposal counts not read: %s", exc)
            return None
        return [cell_int(got.get(f"n{i}")) or 0 for i in range(len(filters))]

    def count_gate(mine: Optional[list[int]], theirs: Optional[list[int]], words: str) -> dict:
        """The count gate: what the proposal counts against what the ontology counts, read at the same moment."""
        if mine is None or theirs is None:
            return {"ok": None, "why": "the counts could not be read"}
        if mine != theirs:
            return {"ok": False, "why": (f"it counts {mine[0]:,} of {mine[1]:,} where the ontology counts "
                                         f"{theirs[0]:,} of {theirs[1]:,}")}
        return {"ok": True, "why": f"{mine[0]:,} {words} {mine[1]:,}, as the ontology counts"}

    for process in (graph.processes or {}).values():
        entity = graph.entities.get(process.entity)
        if entity is None:
            continue
        title = process.display_name or process.id.replace("_", " ")
        for i, stage in enumerate(process.stages):
            promise = stage.promise
            spec = promise_filters(process, i)
            if promise is not None and promise.verified is True and spec is not None and len(spec["breach"]) == 1:
                kept = _negate(spec["breach"][0])
                grain = graph.entities.get(spec["grain"])
                if kept is None or grain is None:
                    continue
                noun = promise_noun(stage)
                reached, keep = list(spec["reached"]), list(spec["reached"]) + [kept]
                name = metric_name(f"{noun}_on_time_rate")
                try:
                    sql = _compile(graph, grain.api_name, {"name": name, "agg": "count", "where": keep,
                                                           "divide_by": {"agg": "count", "where": reached}}, dialect)
                except Exception as exc:  # noqa: BLE001 — a derivation the door refuses is said, not proposed
                    logger.info("on-time rate for %s not compiled: %s", noun, exc)
                    continue
                # The ontology counts the reached and the breached (`_measure_promise`); the kept are the rest.
                mine = counts(grain.api_name, [keep, reached])
                breached = counts(grain.api_name, [list(spec["breach"]), reached])
                theirs = None if breached is None else [breached[1] - breached[0], breached[1]]
                count = count_gate(mine, theirs, "kept of")
                out.append({
                    "name": name, "label": f"{title}: {noun.replace('_', ' ')} on time", "source": SOURCE_ONTOLOGY,
                    "area": area_of(f"{noun} {title}", stage.name), "pattern": "", "pack_id": "",
                    "definition": (f"the share of the {spec['grain']} objects that reached {stage.name} with the {noun} "
                                   f"promise in force and kept it — {spec['words']} is late"),
                    "sql": sql, "tables": [], "time_column": _column_of(graph, grain.api_name, spec["moment"]),
                    "time_kind": "flow", "derived_from": f"the {noun} promise of process {process.id}",
                    "gates": {"count": count}, "made_at": now()})
            previous = process.stages[i - 1] if i else None
            if (previous is not None and stage.timestamp and previous.timestamp and stage.verified is True
                    and previous.verified is True):
                both = [{"path": previous.timestamp, "op": "not_null"}, {"path": stage.timestamp, "op": "not_null"}]
                entered = [{"path": previous.timestamp, "op": "not_null"}]
                name = metric_name(f"{process.id}_{previous.name}_to_{stage.name}")
                try:
                    sql = _compile(graph, entity.api_name, {"name": name, "agg": "count", "where": both,
                                                            "divide_by": {"agg": "count", "where": entered}}, dialect)
                except Exception as exc:  # noqa: BLE001
                    logger.info("stage conversion %s not compiled: %s", name, exc)
                    continue
                theirs_both = [{"path": previous.timestamp, "op": "not_null"}, {"path": stage.timestamp, "op": "not_null"}]
                out.append({
                    "name": name, "label": f"{title}: {previous.name} to {stage.name}", "source": SOURCE_ONTOLOGY,
                    "area": area_of(title, stage.name), "pattern": "", "pack_id": "",
                    "definition": (f"the share of the {entity.id} objects that reached {previous.name} and went on to "
                                   f"{stage.name}"),
                    "sql": sql, "tables": [], "time_column": _column_of(graph, entity.api_name, previous.timestamp),
                    "time_kind": "flow", "derived_from": f"stages {previous.name} and {stage.name} of process {process.id}",
                    "gates": {"count": count_gate(counts(entity.api_name, [both, entered]),
                                                  counts(entity.api_name, [theirs_both, reached_filters(previous)]),
                                                  "went on of")},
                    "made_at": now()})
    for rule in (graph.rules or {}).values():
        if rule.verified is not True:
            continue
        entity = graph.entities.get(rule.entity)
        if entity is None:
            continue
        admits = list(rule_filters(rule))
        name = metric_name(f"{rule.id}_share")
        try:
            sql = _compile(graph, entity.api_name, {"name": name, "agg": "count", "where": admits,
                                                    "divide_by": {"agg": "count"}}, dialect)
        except Exception as exc:  # noqa: BLE001
            logger.info("segment share %s not compiled: %s", name, exc)
            continue
        table = (entity.source_tables or [""])[0].split(".")[-1]
        date = dates.get(table, "")
        out.append({
            "name": name, "label": f"{(rule.description or rule.id.replace('_', ' '))[:60]} — share", "source": SOURCE_ONTOLOGY,
            "area": area_of(rule.id, entity.id), "pattern": "", "pack_id": "",
            "definition": f"the share of the {entity.id} objects rule {rule.id} admits",
            "sql": sql, "tables": [], "time_column": f"{table}.{date}" if (table and date) else "", "time_kind": "flow",
            "derived_from": f"rule {rule.id}",
            "gates": {"count": count_gate(counts(entity.api_name, [admits, []]),
                                          counts(entity.api_name, [list(rule_filters(rule)), []]), "admitted of")},
            "made_at": now()})
    return out


# ── MC-6: what the explorer keeps computing ─────────────────────────────────────────────────────────────────────────

_AVERAGED = ("day", "days", "hour", "hours", "sec", "second", "seconds", "minute", "minutes", "duration", "time",
             "score", "rating", "csat", "nps", "rate", "pct", "percent", "ratio", "share", "age")


def blind_spot_proposals(connection_id: str, schema_name: Optional[str], mmap, metrics: list) -> list[dict]:
    """Each profiled measure that ``BLIND_SPOT_FINDINGS`` or more of the explorer's findings aggregate, that no metric
    reads — its sum, or its average when its name says it is a duration, a score or a share."""
    import sqlglot
    from sqlglot import exp

    from aughor.explorer.store import get_findings
    from aughor.semantic.metric_coverage import place_table, tables_of
    from aughor.semantic.metric_map import OTHER
    from aughor.semantic.metric_statement import statement_tables
    from aughor.semantic.metric_coverage import dataset_entry
    from aughor.trust.lineage_edges import dialect_for_connection

    dialect = dialect_for_connection(connection_id) or "duckdb"
    entry = dataset_entry(connection_id, schema_name) or {}
    measures: dict[tuple[str, str], dict] = {}
    for key, cp in (entry.get("columns") or {}).items():
        if isinstance(cp, dict) and str(cp.get("semantic_type") or "").lower() == "measure" and not cp.get("is_fk"):
            table = str(cp.get("table") or str(key).split(".", 1)[0]).split(".")[-1].lower()
            measures[(table, str(cp.get("column") or "").lower())] = cp
    read_by_metrics = " ".join(str(getattr(m, "sql", "") or "").lower() for m in metrics)
    seen: dict[tuple[str, str], set] = {}
    for f in get_findings(connection_id):
        sql = str(f.get("sql") or "")
        if not sql.strip():
            continue
        try:
            tree = sqlglot.parse_one(sql, read=dialect)
            tables = {t.split(".")[-1].lower() for t in statement_tables(sql, dialect)}
        except Exception as exc:  # noqa: BLE001 — a finding whose SQL does not parse computes nothing countable
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a finding's SQL did not parse; it counts towards no blind spot", counter="coverage.blind_spot")
            continue
        for agg in tree.find_all(exp.Sum, exp.Avg):
            for col in agg.find_all(exp.Column):
                hits = [(t, col.name.lower()) for t in tables if (t, col.name.lower()) in measures]
                for key in hits[:1]:
                    seen.setdefault(key, set()).add(str(f.get("id") or sql[:80]))
    by_table = {t.name: t for t in tables_of(connection_id, schema_name)}
    areas = [a for a in mmap.readable]
    out: list[dict] = []
    for (table, column), ids in sorted(seen.items()):
        if len(ids) < BLIND_SPOT_FINDINGS or re.search(rf"\b{re.escape(column)}\b", read_by_metrics):
            continue
        words = re.split(r"[^a-z0-9]+", column)
        agg = "AVG" if any(w in _AVERAGED for w in words) else "SUM"
        facts = by_table.get(table)
        placed = place_table(facts, areas) if facts else []
        name = metric_name(f"{'average' if agg == 'AVG' else 'total'}_{column}")
        out.append({
            "name": name, "label": f"{'Average' if agg == 'AVG' else 'Total'} {column.replace('_', ' ')}",
            "source": SOURCE_BLIND_SPOT, "area": placed[0].area if placed else OTHER, "pattern": "", "pack_id": "",
            "definition": (f"the {('average' if agg == 'AVG' else 'sum')} of {table}.{column} — {len(ids)} of the "
                           "explorer's findings compute it, and no metric reads it"),
            "sql": f"SELECT {agg}({column}) AS {name} FROM {table}", "tables": [table],
            "time_column": f"{table}.{facts.date_column}" if facts and facts.date_column else "", "time_kind": "flow",
            "findings": len(ids), "made_at": now()})
    return out


# ── the run ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def run(connection_id: str, schema_name: Optional[str] = None, *, write: bool = False, why: str = "") -> dict:
    """One coverage run: the code proposers, and — with ``write`` — one model call per uncovered area; every proposal
    through the gates; kept beside the profile. Returns the payload."""
    from aughor.business_profile import store as profile_store
    from aughor.semantic.metric_coverage import defined_metrics
    from aughor.semantic.metric_map import map_for

    mmap = map_for(connection_id, schema_name)
    metrics = defined_metrics(connection_id, schema_name)
    defined = {metric_name(m.name) for m in metrics} | {metric_name(m.label or "") for m in metrics}
    approved = [m for m in metrics if m.status == "approved"]
    said: list[str] = []
    proposals: list[dict] = []
    spend: Optional[dict] = None
    previous = profile_store.load_coverage(connection_id, schema_name)

    from aughor.db.connection import open_connection_for, open_connection_for_with_schema
    db = (open_connection_for_with_schema(connection_id, schema_name) if schema_name
          else open_connection_for(connection_id))
    try:
        proposals += recipe_proposals(connection_id, schema_name, mmap)
        from aughor.agent.framing import served_graph
        proposals += ontology_proposals(connection_id, schema_name, served_graph(connection_id, schema_name), db, mmap)
        proposals += blind_spot_proposals(connection_id, schema_name, mmap, metrics)
        if write:
            from aughor.semantic import coverage_writer
            written, spend = coverage_writer.write(connection_id, schema_name, mmap, db=db, taken=proposals)
            spend["why"] = why                          # the calls keep the reason they were made
            proposals += written
        elif previous.get("spend"):
            # a run without the writer keeps what the last written run wrote, re-checked below
            from aughor.semantic.metric_map import OTHER
            proposals += [p for p in previous.get("proposals") or []
                          if p.get("source") in (SOURCE_PATTERN, SOURCE_AREA) and p.get("area") != OTHER]
            spend = previous.get("spend")
        kept: list[dict] = []
        names: set[str] = set()
        for p in proposals:
            key = metric_name(p["name"])
            if key in defined or key in names:
                continue                               # a definition of that name exists, or an earlier proposal has it
            names.add(key)
            kept.append(p)

        def run_sql(sql: str) -> tuple:
            bounded = getattr(db, "execute_bounded", None)
            res = bounded("__coverage_gate__", sql, 50) if callable(bounded) else db.execute("__coverage_gate__", sql,
                                                                                           internal=True)
            return list(res.columns or []), list(res.rows or []), res.error

        dialect = getattr(db, "dialect", "") or "duckdb"
        from aughor.semantic.metric_coverage import dataset_entry
        columns = (dataset_entry(connection_id, schema_name) or {}).get("columns") or {}
        for p in kept:
            try:
                gate(p, connection_id=connection_id, schema_name=schema_name, run_sql=run_sql, dialect=dialect,
                     approved=approved, band=p.get("sane_range"), band_label=f"the {p.get('label')} recipe",
                     columns=columns)
            except Exception as exc:  # noqa: BLE001 — a proposal whose gates could not be read is said, not offered
                from aughor.kernel.errors import tolerate
                tolerate(exc, "a coverage proposal's gates could not be read", counter="coverage.gate")
                p["state"], p["reason"] = STATE_GATE_FAILED, f"its gates could not be read ({type(exc).__name__})"
    finally:
        try:
            db.close()
        except Exception as exc:  # noqa: BLE001 — a connection that will not close is said; the run stands
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the coverage run's connection did not close", counter="coverage.close")
    one_measure_once(kept)
    payload = {"run_at": now(), "why": why, "proposals": kept, "spend": spend, "said": said + mmap.problems}
    if not profile_store.save_coverage(connection_id, schema_name, payload):
        payload["said"].append("this dataset has no business profile yet, so the proposals were not kept — profile it")
    return payload


def one_measure_once(proposals: list[dict]) -> None:
    """Two proposals that read the same figure (at one scale) in every month both have one are one measure: the first
    stays, each later one is refused naming it. Across tables too — two different measures agreeing to nine places
    month after month is not a coincidence a business has (`metric_twins`); live 2026-10-26, three LuxExperience
    consent proposals read 0.6196 alike."""
    from aughor.semantic.metric_twins import agree

    kept: list[dict] = []
    for p in proposals:
        if p.get("state") != STATE_PROPOSED or not p.get("figures"):
            continue
        twin = next((q for q in kept if agree(p["figures"], q["figures"])), None)
        if twin is None:
            kept.append(p)
            continue
        months = sum(1 for a, b in zip(p["figures"], twin["figures"]) if a is not None and b is not None)
        p["gates"]["twin"] = {"ok": False, "why": (f"it reads exactly what {twin.get('label')}, proposed here too, reads "
                                                   f"in each of the last {months} months — one measure, proposed twice")}
        p["state"], p["reason"] = STATE_GATE_FAILED, f"{GATE_WORDS['twin']} — no: {p['gates']['twin']['why']}"


def stored(connection_id: str, schema_name: Optional[str] = None) -> list[dict]:
    """The last run's proposals, each with whether a person declined it."""
    from aughor.business_profile import store as profile_store
    from aughor.semantic.metrics import dismissed_proposals, is_dismissed

    rows = list(profile_store.load_coverage(connection_id, schema_name).get("proposals") or [])
    try:
        removed = dismissed_proposals(connection_id)
    except Exception:  # noqa: BLE001 — unread declines decline nothing
        removed = []
    for p in rows:
        p["declined"] = bool(is_dismissed(removed, connection_id, schema_name or "*", p.get("name") or ""))
    return rows


def proposals_by_area(connection_id: str, schema_name: Optional[str] = None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in stored(connection_id, schema_name):
        out.setdefault(str(p.get("area") or ""), []).append(p)
    return out


def recipe_verdict(connection_id: str, schema_name: Optional[str], name: str, bound: dict) -> Optional[dict]:
    """The last run's verdict on a recipe — only while the binding it was read under still stands."""
    for p in stored(connection_id, schema_name):
        if p.get("source") == SOURCE_RECIPE and p.get("name") == name:
            return p if p.get("binding_fingerprint") == binding_fingerprint(bound) else None
    return None


def run_in_background(connection_id: str, schema_name: Optional[str], *, write: bool, why: str) -> bool:
    """Start a run on a thread — the hook a profiling build calls. True once it is started."""
    import threading

    def _go() -> None:
        try:
            run(connection_id, schema_name, write=write, why=why)
        except Exception as exc:  # noqa: BLE001 — a background run that fails is logged; the profile stands
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a coverage run after profiling failed", counter="coverage.background")

    threading.Thread(target=_go, name=f"coverage-{connection_id}", daemon=True).start()
    return True
