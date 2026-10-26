"""Arc MC, MC-2 — every table and every metric placed in the areas it serves, and the coverage matrix (ROADMAP §3.62).

A metric set covers a business when every area the data describes has the metrics a person running that area reads —
not when it holds the "most important" six. This makes that measurable: per area of the map (`metric_map`), the data
placed in it, the metrics that read on it, the patterns the knowledge base would measure, the proposals waiting and the
ones a person declined.

**Placement** reads evidence the platform already holds, and each placement says which:

- a table's NAME — the area whose words name it most strongly (the longest phrase wins: `customer_service` is Service);
- its ontology entity's DOMAIN, where one is declared;
- the METRICS that read it — a table a metric reads is placed in that metric's area, so a table with a metric is never
  left in no area (MC-2's falsifier).

A metric is placed by its lineage (a proposal adopted from an area keeps it), then by the pattern it IS (its name or
label word for word a pattern's title or intent tag), then by its own words, then by the tables it reads, and last in
the generic layer's area — said, never guessed.

**Covered** means an approved metric that MOVES: its figures read over its last six months, the MC-0 gate's verdict, so
an area is never said covered by a metric that reads 1 in every month (the falsifier). An approved metric whose figures
have not been read is said as not checked, and does not cover.

A read. No model; the warehouse only to read approved metrics' figures (`figures=True`), at most hourly per metric.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from aughor.semantic.metric_map import OTHER, Area, MetricMap, best_areas, match_pattern

logger = logging.getLogger(__name__)

#: A table with at least this many rows and a date is a fact the generic layer's area holds when no area names it.
OTHER_MIN_ROWS = 100


@dataclass
class TableFacts:
    name: str
    rows: Optional[int] = None
    date_column: str = ""
    columns: dict[str, str] = field(default_factory=dict)        # column → dtype
    #: The column one row is one of; a table whose grain is its date is a calendar, not a fact.
    grain: str = ""

    @property
    def has_rows(self) -> bool:
        return bool(self.rows)


@dataclass
class Placement:
    area: str
    why: str


def _bare(name: str) -> str:
    return str(name or "").split(".")[-1].strip('`"[]').lower()


def tables_of(connection_id: str, schema_name: Optional[str] = None) -> list[TableFacts]:
    """The connection's tables as the profiler last read them — rows, main date, columns. [] when it was never
    profiled; the caller says so."""
    from aughor.tools.profile_cache import merged_profile_entry

    entry = merged_profile_entry(connection_id) or {}
    out: dict[str, TableFacts] = {}
    want = (schema_name or "").lower()
    for key, tp in (entry.get("tables") or {}).items():
        if not isinstance(tp, dict):
            continue
        name = str(tp.get("table") or key)
        if want and want != "*" and "." in name and name.split(".")[0].lower() != want:
            continue
        bare = _bare(name)
        out[bare] = TableFacts(name=bare, rows=tp.get("row_count"),
                               date_column=str(tp.get("primary_timestamp") or ""),
                               grain=str(tp.get("grain_column") or "").lower())
    for key, cp in (entry.get("columns") or {}).items():
        if not isinstance(cp, dict):
            continue
        table = _bare(str(cp.get("table") or str(key).split(".", 1)[0]))
        if table in out:
            out[table].columns[str(cp.get("column") or str(key).split(".", 1)[-1]).lower()] = str(cp.get("dtype") or "")
    for t in out.values():
        if not t.date_column:
            t.date_column = next((c for c, d in t.columns.items() if "date" in d.lower() or "time" in d.lower()), "")
    return sorted(out.values(), key=lambda t: t.name)


def _domains(connection_id: str, schema_name: Optional[str]) -> dict[str, str]:
    """table → the domain its ontology entity declares, where one does."""
    try:
        from aughor.ontology.store import load_latest_ontology
        graph = load_latest_ontology(connection_id, schema_name or None)
    except Exception as exc:  # noqa: BLE001 — no ontology places nothing by domain
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the ontology could not be read; tables are placed by their names", counter="metric_coverage.onto")
        return {}
    out: dict[str, str] = {}
    for e in (getattr(graph, "entities", None) or {}).values():
        if getattr(e, "domain", None):
            for t in (e.source_tables or []):
                out.setdefault(_bare(t), str(e.domain))
    return out


def place_table(t: TableFacts, areas: list[Area], domain: str = "") -> list[Placement]:
    """The areas a table serves by its name and its entity's domain, each with why."""
    named = [a for a in areas if not a.generic]
    out = [Placement(a.id, f"its name says {w}") for a, w in best_areas(t.name, named)]
    if domain:
        for a, w in best_areas(domain, named):
            if all(p.area != a.id for p in out):
                out.append(Placement(a.id, f"its ontology entity's domain is {domain}"))
    return out


def place_metric(m: Any, mmap: MetricMap, table_areas: dict[str, list[Placement]]) -> Placement:
    """The one area a metric reads on, and why."""
    from aughor.semantic.metric_time import tables_read

    for line in (getattr(m, "lineage", None) or []):
        text = str(line)
        if text.startswith("coverage:"):
            area = text.split(":", 1)[1].strip().split(" ")[0]
            if mmap.area(area):
                return Placement(area, "it was adopted from this area's proposals")
    name, label = str(getattr(m, "name", "") or ""), str(getattr(m, "label", "") or "")
    pattern = match_pattern(name, label, mmap.patterns())
    if pattern is not None:
        return Placement(pattern.area, f"it is the knowledge base's {pattern.title}")
    named = [a for a in mmap.areas if not a.generic]
    hits = best_areas(f"{name} {label}", named)
    if hits:
        a, w = hits[0]
        return Placement(a.id, f"its name says {w}")
    for t in tables_read(m):
        placed = table_areas.get(_bare(t)) or []
        if placed:
            return Placement(placed[0].area, f"it reads {_bare(t)}, which {placed[0].why}")
    return Placement(OTHER, "nothing in its name or its tables names an area")


# ── the matrix ──────────────────────────────────────────────────────────────────────────────────────────────────────

def defined_metrics(connection_id: str, schema_name: Optional[str]) -> list:
    from aughor.semantic.metrics import ALL_DATASETS, list_metrics
    scope = None if schema_name in (None, "", ALL_DATASETS) else schema_name
    return [m for m in list_metrics(connection_id=connection_id, schema_name=scope)
            if m.connection == connection_id and m.status != "deprecated"]


def _moves(metrics: list, connection_id: str, *, figures: bool) -> dict[str, dict]:
    """name → the moves verdict of each approved metric: cached, or read now when ``figures``."""
    from aughor.semantic import metric_gates

    out: dict[str, dict] = {}
    todo = []
    for m in metrics:
        if m.status != "approved":
            continue
        hit = metric_gates.cached(m, connection_id)
        if hit is not None:
            out[m.name] = hit["moves"]
        elif figures:
            todo.append(m)
        else:
            out[m.name] = {"ok": None, "why": "its figures have not been read yet"}
    if todo:
        try:
            from aughor.knowledge import period_brief
            with period_brief.connection_runner(connection_id) as (run_sql, dialect):
                for m in todo:
                    out[m.name] = metric_gates.check(m, connection_id, run_sql=run_sql, dialect=dialect)["moves"]
        except Exception as exc:  # noqa: BLE001 — not read is said, and an unread metric covers nothing
            from aughor.kernel.errors import tolerate
            tolerate(exc, "approved metrics' figures could not be read for the coverage view",
                     counter="metric_coverage.figures")
            for m in todo:
                out.setdefault(m.name, {"ok": None, "why": f"the connection could not be opened ({type(exc).__name__})"})
    return out


def coverage(connection_id: str, schema_name: Optional[str] = None, *, figures: bool = False,
             mmap: Optional[MetricMap] = None) -> dict:
    """The coverage matrix: per readable area, in the map's order — its data, its metrics, its patterns, its proposals —
    with every placement's reason, and what could not be read said."""
    from aughor.semantic.metric_map import map_for

    mmap = mmap or map_for(connection_id, schema_name)
    tables = tables_of(connection_id, schema_name)
    domains = _domains(connection_id, schema_name)
    said: list[str] = list(mmap.problems)
    if not tables:
        said.append("the profiler has not read this connection's tables yet — profile it to place them")
    areas = mmap.readable
    by_table: dict[str, list[Placement]] = {t.name: place_table(t, areas, domains.get(t.name, "")) for t in tables}

    from aughor.semantic.metric_time import tables_read

    metrics = defined_metrics(connection_id, schema_name)
    moved = _moves(metrics, connection_id, figures=figures)
    placed_metrics: dict[str, list[tuple[Any, Placement]]] = {}
    for m in metrics:
        p = place_metric(m, mmap, by_table)
        placed_metrics.setdefault(p.area, []).append((m, p))
        for t in tables_read(m):
            bare = _bare(t)
            if bare in by_table and all(x.area != p.area for x in by_table[bare]):
                by_table[bare].append(Placement(p.area, f"{m.label or m.name} reads it"))

    facts = {t.name: t for t in tables}
    for t in tables:
        if (not by_table[t.name] and t.has_rows and (t.rows or 0) >= OTHER_MIN_ROWS and t.date_column
                and t.grain != t.date_column.lower()):
            by_table[t.name].append(Placement(OTHER, "a dated table no area's words name"))

    proposals: dict[str, list[dict]] = {}
    try:
        from aughor.semantic.coverage_proposals import proposals_by_area
        proposals = proposals_by_area(connection_id, schema_name)
    except Exception as exc:  # noqa: BLE001 — proposals unread are said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "coverage proposals could not be read", counter="metric_coverage.proposals")
        said.append(f"the proposals could not be read ({type(exc).__name__})")

    rows: list[dict] = []
    for order, area in enumerate(areas):
        area_tables = [{"name": n, "rows": facts[n].rows, "dated": bool(facts[n].date_column),
                        "why": next(p.why for p in ps if p.area == area.id)}
                       for n, ps in by_table.items() if any(p.area == area.id for p in ps)]
        area_metrics = []
        for m, p in placed_metrics.get(area.id, []):
            v = moved.get(m.name)
            area_metrics.append({"name": m.name, "label": m.label or m.name, "status": m.status, "why": p.why,
                                 "moves": v})
        working = [x for x in area_metrics if x["status"] == "approved" and (x["moves"] or {}).get("ok") is True]
        unchecked = [x for x in area_metrics if x["status"] == "approved" and (x["moves"] or {}).get("ok") is None]
        has_data = any(t["rows"] for t in area_tables)
        mine = proposals.get(area.id, [])
        notes = []
        if not area.proposable_patterns and not area.recipes and not area.generic:
            notes.append("the knowledge base carries no pattern for this area yet — a package can add one")
        broken = [x for x in area_metrics if (x["moves"] or {}).get("ok") is False]
        for x in broken:
            notes.append(f"{x['label']} does not cover it: {x['moves']['why']}")
        state = ("covered" if working else "unchecked" if unchecked and has_data
                 else "uncovered" if has_data else "no_data")
        # The patterns of this area no metric and no proposal here computes yet — what a person running the area reads
        # that this data is not yet measured by. An area thin on metrics is as open as one with none.
        taken = [(m.name, m.label or "") for m, _p in placed_metrics.get(area.id, [])]
        taken += [(str(x.get("name") or ""), str(x.get("label") or "")) for x in mine]
        done = {x.get("pattern") for x in mine if x.get("pattern")}
        for n, lab in taken:
            hit = match_pattern(n, lab, area.patterns)
            if hit is not None:
                done.add(hit.id)
        open_patterns = [p.id for p in area.proposable_patterns if p.id not in done]
        writable = has_data and (bool(open_patterns) if area.proposable_patterns else state != "covered")
        if area.generic and not area_tables and not area_metrics:
            continue                                    # the generic layer's area, empty: nothing to say
        rows.append({
            **area.as_dict(), "order": order, "state": state, "has_data": has_data,
            "rows": sum(t["rows"] or 0 for t in area_tables),
            "tables": sorted(area_tables, key=lambda t: -(t["rows"] or 0)),
            "metrics": area_metrics,
            "proposals": len(mine),
            "adoptable": sum(1 for x in mine if x.get("state") == "proposed" and not x.get("declined")),
            "failed": sum(1 for x in mine if x.get("state") == "gate_failed" and not x.get("declined")),
            "declined": sum(1 for x in mine if x.get("declined")),
            "open_patterns": open_patterns, "writable": writable,
            "said": notes,
        })
    unplaced = sorted(n for n, ps in by_table.items() if not ps)
    return {
        "connection_id": connection_id, "schema": schema_name, "industry_pack": mmap.industry_pack,
        "areas": rows, "unplaced_tables": unplaced, "said": said,
        "counts": {
            "areas": len(rows), "with_data": sum(1 for r in rows if r["has_data"]),
            "covered": sum(1 for r in rows if r["state"] == "covered"),
            "uncovered": sum(1 for r in rows if r["state"] == "uncovered"),
            "unchecked": sum(1 for r in rows if r["state"] == "unchecked"),
            "patterns": sum(len(r["patterns"]) for r in rows),
            "open_patterns": sum(len(r["open_patterns"]) for r in rows if r["has_data"]),
            "writable": sum(1 for r in rows if r["writable"]),
        },
    }
