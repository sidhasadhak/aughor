"""Arc BR-4 · each horizon a different job (ROADMAP §3.48).

§3.27's period Briefing was the standing Briefing's machinery pointed at fewer days. The user's
own reading of the Day — *"what action needs to be taken based on the numbers today"* (§6 item
34(c)) — is a different product from "the newest settled day's totals", which on theLook is 15
days old. A range Briefing is now written by a RECIPE, one per horizon, from the same sections:

* **measured** — every approved metric against its comparisons (BR-2/BR-3);
* **what moved** — each metric broken down by its own declared, low-cardinality dimensions,
  the segments ranked by how much of the move they carry; a segment of fewer than
  ``MIN_CELL_ROWS`` rows is said to be *too few to call*, never headlined;
* **why** — the standing findings (what we know) that name a moving segment;
* **early read** (Day) — the days still settling, measured and labelled early;
* **alerts** — fired in the range, or for the Day since yesterday;
* **the norm** (Week) — the four weeks before, so a move can be called unusual or not;
* **target** (Month) — a metric's declared target, when it has one;
* **data health** — what was not measured, what is provisional, which tables have not settled
  (said, not implied — the block carries all three; the page renders them).

Each recipe tells the narrator which job it is doing; one narrator call per Briefing, under the
Briefer's charter and its budget.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable, Optional

RECIPE_OF_PRESET = {"yesterday": "day", "last_week": "week", "last_month": "month",
                    "last_year": "year", "month_to_date": "month", "year_to_date": "year",
                    "custom": "custom"}

SECTIONS = {
    "day": ("alerts", "what_moved", "early_read", "actions", "data_health"),
    "week": ("what_moved", "norm", "why", "actions", "data_health"),
    "month": ("measured", "target", "why", "data_health"),
    "year": ("measured", "what_moved", "data_health"),
    "custom": ("measured", "what_moved", "why", "data_health"),
}

GUIDANCE = {
    "day": ("This is the DAY briefing, written for acting today. Lead with any alert that fired since "
            "yesterday; then the single biggest move in the newest settled day against the same weekday a "
            "week earlier, with the segment that carried it; then what the days still settling suggest, "
            "saying plainly that they are early. End with the one thing to do first."),
    "week": ("This is the WEEK briefing, written for steering. Lead with what moved against the week "
             "before and whether it is unusual against the weeks before that; name the segment each move "
             "sits in and what the platform already knows about it."),
    "month": ("This is the MONTH briefing, written for review. Lead with each headline metric against the "
              "month before and the same month a year earlier, and against its target where one is declared; "
              "say which figures are still provisional and why."),
    "year": ("This is the YEAR briefing, written for strategy. Lead with the year against the year before, "
             "then the shifts in mix underneath it. Leave day-to-day noise out."),
    "custom": ("This is a CUSTOM RANGE briefing, written for exploring. Lead with what the range shows "
               "against its comparison, then the segments behind the biggest move."),
}

#: Every recipe: a Briefing has no causal licence, and the departure gate holds a causal claim
#: that has none (theLook's first Day send, 2026-09-26: "lifting total revenue" was held).
NO_CAUSES = (" Say what moved, where and alongside what; never write that one figure caused, drove, "
             "lifted or was behind another — nothing here has tested a cause.")
GUIDANCE = {k: v + NO_CAUSES for k, v in GUIDANCE.items()}

WORDS = {"day": "80-150", "week": "120-220", "month": "150-280", "year": "200-350", "custom": "120-250"}

#: A segment behind fewer rows than this is too few to call — listed, never headlined.
MIN_CELL_ROWS = 30
#: How many metric × dimension breakdowns a Briefing may run, and how many dimensions per metric.
MAX_BREAKDOWNS = 6
DIMS_PER_METRIC = 2
#: A dimension with more values than this is a drill, not a breakdown.
MAX_DIM_VALUES = 50
#: How many segment moves the Briefing leads with.
MAX_MOVES = 5


def recipe_for(preset: str) -> str:
    return RECIPE_OF_PRESET.get(preset, "custom")


# ── what moved ─────────────────────────────────────────────────────────────────────────────

def breakdown_dimensions(metric: Any, profile_entry: dict) -> list[str]:
    """The metric's own DECLARED dimensions that are low-cardinality columns of its table — not a
    date, not a key. A dimension the profiler has not seen is left out: it cannot be judged."""
    from aughor.semantic.metric_time import bare_name

    tables = list(getattr(metric, "tables", None) or [])
    if not tables:
        return []
    table = bare_name(tables[0])
    cols = {}
    for key, prof in ((profile_entry or {}).get("columns") or {}).items():
        if isinstance(prof, dict) and bare_name(str(prof.get("table") or str(key).split(".", 1)[0])) == table:
            cols[str(prof.get("column") or str(key).split(".", 1)[-1]).lower()] = prof
    out = []
    for dim in getattr(metric, "dimensions", None) or []:
        prof = cols.get(bare_name(dim))
        if not prof or prof.get("is_fk"):
            continue
        dtype = str(prof.get("dtype") or "").lower()
        if "date" in dtype or "time" in dtype:
            continue
        distinct = prof.get("distinct_count")
        if not (prof.get("is_low_cardinality") or (isinstance(distinct, (int, float)) and distinct <= MAX_DIM_VALUES)):
            continue
        out.append(bare_name(dim))
    return out[:DIMS_PER_METRIC]


def _share_metric(metric: Any) -> bool:
    return getattr(metric, "time_kind", None) == "cohort"


def what_moved(metrics: list, spec: Any, run_sql: Callable[[str], tuple], *, dialect: str,
               profile_entry: dict) -> dict:
    """Every declared, low-cardinality breakdown of every measured metric, for the range and its
    comparison. Returns ``{"moves": [...], "thin": [...], "skipped": [...]}`` — moves ranked by
    how much of their metric's base they moved (a share's by its points)."""
    from aughor.semantic import metric_time as mt

    windows = spec.windows()[:2]
    moves: list[dict] = []
    thin: list[dict] = []
    skipped: list[str] = []
    ran = 0
    for m in metrics:
        if not mt.declared(m):
            continue
        for dim in breakdown_dimensions(m, profile_entry):
            if ran >= MAX_BREAKDOWNS:
                skipped.append(f"{m.label or m.name} by {dim}")
                continue
            ran += 1
            rows, why = mt.run_measure(m, windows, run_sql, dialect=dialect, by=dim)
            if why:
                skipped.append(f"{m.label or m.name} by {dim} ({why})")
                continue
            sql = mt.measure_sql(m, windows, dialect=dialect, by=dim)[0] or ""
            by: dict[str, dict] = {}
            for r in rows:
                g = "(none)" if r["group"] is None else str(r["group"])
                by.setdefault(g, {})[r["window"]] = r
            base = sum(abs((w.get("previous") or {}).get("value") or 0) for w in by.values()) or 1.0
            for g, w in by.items():
                cur, prev = (w.get("current") or {}), (w.get("previous") or {})
                cv, pv = cur.get("value"), prev.get("value")
                if cv is None and pv is None:
                    continue
                # a move is callable only when BOTH sides stand on enough rows: 7 → 31 units
                # read as a surge and led theLook's Day (2026-09-26) on a comparison of 7 rows
                n = min(int(cur.get("n") or 0), int(prev.get("n") or 0))
                cell = {"metric": m.name, "name": m.label or m.name, "dimension": dim, "group": g,
                        "current": cv, "previous": pv, "n": n, "share": _share_metric(m),
                        "unit": m.unit or "", "sql": sql}
                if cell["share"]:
                    cell["change"] = None if cv is None or pv is None else (cv - pv) * 100
                    cell["score"] = abs(cell["change"] or 0) / 100
                else:
                    cell["change"] = (cv or 0) - (pv or 0)
                    cell["score"] = abs(cell["change"]) / base
                (thin if n < MIN_CELL_ROWS else moves).append(cell)
    moves.sort(key=lambda c: c["score"], reverse=True)
    return {"moves": moves[:MAX_MOVES], "thin": sorted(thin, key=lambda c: c["score"], reverse=True)[:MAX_MOVES],
            "skipped": skipped}


def _fmt(v: Optional[float], cell: dict, currency: Optional[str]) -> str:
    from aughor.knowledge import period_brief
    if v is None:
        return "none"
    if cell["share"]:
        return f"{v * 100:.1f}%"
    return period_brief._fmt(v, cell["name"], cell["unit"], currency)


def move_line(cell: dict, block: dict, currency: Optional[str]) -> str:
    """A segment's move as a sentence the triage reads a change from ("from X to Y")."""
    cur, prev = _fmt(cell["current"], cell, currency), _fmt(cell["previous"], cell, currency)
    change = (f"{cell['change']:+.1f} pts" if cell["share"] and cell["change"] is not None
              else f"{'+' if (cell['change'] or 0) >= 0 else '-'}{_fmt(abs(cell['change'] or 0), cell, currency)}")
    return (f"{cell['name']} for {cell['dimension']} {cell['group']} moved from {prev} to {cur} ({change}): "
            f"{block['covers']} against {block['compared_with']}.")


# ── why ────────────────────────────────────────────────────────────────────────────────────

def why_links(moves: list[dict], domain_data: dict, *, per_move: int = 2) -> list[dict]:
    """Standing findings — what we know — that name a moving segment. A segment name shorter
    than four characters is not matched: "M" and "F" name everything."""
    rows = [(dom, i) for dom, payload in (domain_data or {}).items()
            for i in (payload if isinstance(payload, list) else (payload or {}).get("rows", []) or [])
            if isinstance(i, dict) and i.get("finding")]
    out = []
    for cell in moves:
        g = str(cell["group"])
        if len(g) < 4:
            continue
        hits = [{"segment": g, "dimension": cell["dimension"], "domain": dom, "id": i.get("id"),
                 "finding": i["finding"]}
                for dom, i in rows if g.lower() in str(i["finding"]).lower()]
        out += hits[:per_move]
    return out


# ── the Day: since yesterday, and what is still settling ────────────────────────────────────

def recent_alerts(conn_id: str, spec: Any) -> list[dict]:
    """Alerts that fired since yesterday — the Day acts on what fired, whatever day it is about."""
    from types import SimpleNamespace

    from aughor.knowledge import period_brief

    since = SimpleNamespace(start=spec.as_of - timedelta(days=1), end=spec.as_of + timedelta(days=1))
    return period_brief.alert_findings(conn_id, since)


def early_read(metrics: list, spec: Any, run_sql: Callable[[str], tuple], *, dialect: str) -> dict:
    """The days after the newest settled one, up to yesterday, measured and labelled EARLY — the
    Day's view of what is happening now, never called final."""
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metric_time import Window

    start, end = spec.end, spec.as_of
    if end <= start:
        return {"start": None, "end": None, "figures": []}
    w = Window("early", start, end, as_of=spec.as_of)
    figures = []
    for m in metrics:
        if not mt.declared(m) or m.time_kind == "cohort":   # a cohort this young says nothing yet
            continue
        rows, why = mt.run_measure(m, [w], run_sql, dialect=dialect)
        if why or not rows or rows[0]["value"] is None:
            continue
        figures.append({"metric": m.name, "name": m.label or m.name, "unit": m.unit or "",
                        "value": rows[0]["value"], "n": rows[0]["n"],
                        "sql": mt.measure_sql(m, [w], dialect=dialect)[0] or ""})
    return {"start": start.isoformat(), "end": (end - timedelta(days=1)).isoformat(), "figures": figures}


# ── the Week's norm, the Month's target ─────────────────────────────────────────────────────

def weekly_norm(metric: Any, spec: Any, run_sql: Callable[[str], tuple], *, dialect: str) -> Optional[float]:
    """The mean of the four weeks before the comparison week — the norm a week's move is judged
    against (one statement, four windows)."""
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metric_time import Window

    age = spec.as_of - spec.end
    weeks = [Window(f"w{i}", spec.previous_start - timedelta(days=7 * i),
                    spec.previous_end - timedelta(days=7 * i),
                    as_of=spec.previous_end - timedelta(days=7 * i) + age) for i in range(1, 5)]
    rows, why = mt.run_measure(metric, weeks, run_sql, dialect=dialect)
    vals = [r["value"] for r in rows if r["value"] is not None]
    return (sum(vals) / len(vals)) if (not why and len(vals) == 4) else None


# ── the recipe, applied ─────────────────────────────────────────────────────────────────────

def apply(conn_id: str, spec: Any, got: dict, *, run_sql: Callable[[str], tuple], dialect: str,
          domain_data: dict, currency: Optional[str], block: dict) -> dict:
    """The recipe's own sections, added to a range's measurement (``got`` — ``measured`` and
    ``unmeasured`` from ``ranges.measure_range``). Returns what to add: ``moves``, ``thin``,
    ``why``, ``early``, ``alerts`` and the extra candidate findings the narrator reads."""
    from aughor.semantic.metrics import list_metrics
    from aughor.tools.profile_cache import latest_profile_entry

    recipe = recipe_for(spec.preset)
    sections = SECTIONS[recipe]
    metrics = [m for m in list_metrics(connection_id=conn_id)
               if m.status == "approved" and m.connection == conn_id]
    measured = {m["metric"]: m for m in got.get("measured") or []}
    metrics = [m for m in metrics if m.name in measured]
    out: dict = {"recipe": recipe, "sections": list(sections), "moves": [], "thin": [], "why": [],
                 "early": None, "candidates": {}}
    if "what_moved" in sections or "why" in sections:
        moved = what_moved(metrics, spec, run_sql, dialect=dialect,
                           profile_entry=latest_profile_entry(conn_id))
        for c in moved["moves"] + moved["thin"]:   # the page shows the text the narrator read
            c["current_text"] = _fmt(c["current"], c, currency)
            c["previous_text"] = _fmt(c["previous"], c, currency)
            c["change_text"] = (f"{c['change']:+.1f} pts" if c["share"] and c["change"] is not None
                                else f"{'+' if (c['change'] or 0) >= 0 else '-'}{_fmt(abs(c['change'] or 0), c, currency)}")
        out["moves"], out["thin"] = moved["moves"], moved["thin"]
        out["candidates"]["What moved"] = [
            {"id": f"range-segment::{block['key']}::{c['metric']}::{c['dimension']}::{c['group']}"[:180],
             "domain": "What moved", "angle": "Segment", "finding": move_line(c, block, currency),
             "sql": "", "confidence": 0.8, "novelty": 3, "period_move": True} for c in out["moves"]]
    if "why" in sections and out["moves"]:
        out["why"] = why_links(out["moves"], domain_data)
        out["candidates"]["What we know"] = [
            {"id": w["id"] or f"why::{w['segment']}", "domain": "What we know", "angle": "Standing",
             "finding": w["finding"], "sql": "", "confidence": 0.7, "novelty": 1} for w in out["why"]]
    if "early_read" in sections:
        out["early"] = early_read(metrics, spec, run_sql, dialect=dialect)
        for f in out["early"]["figures"]:
            f["value_text"] = _fmt(f["value"], {"share": False, "name": f["name"], "unit": f["unit"]}, currency)
    if "alerts" in sections and recipe == "day":
        alerts = recent_alerts(conn_id, spec)
        if alerts:
            out["candidates"]["Alerts"] = alerts
    if "norm" in sections:
        for m in metrics:
            norm = weekly_norm(m, spec, run_sql, dialect=dialect)
            row = measured[m.name]
            row["norm"] = norm
            row["rel_norm"] = (None if norm in (None, 0) or row["current"] is None
                               else (row["current"] - norm) / abs(norm))
    if "target" in sections:
        for m in metrics:
            row = measured[m.name]
            row["target"] = m.target_value
            row["vs_target"] = (None if m.target_value in (None, 0) or row["current"] is None
                                else (row["current"] - m.target_value) / abs(m.target_value))
    return out
