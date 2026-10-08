"""Watch over time — the third job (exploration principles §2 and §4, 2026-10-08).

"Time detects, dimensions explain." When a period has arrived AND settled, at each approved metric's
date grain, the dataset's metrics are re-read for it — SQL only, the same measurement the Briefing and
the cockpit read (`briefing.ranges.measured_block`), so a figure watched here is the figure a person
sees there. The reading is kept on the dataset's program (`explorer/program.py`), which the Time
maturity reading and the next check read; a figure that REALLY moved — a settled figure, at least
``MOVED`` from the period before — is a named event that reopens the dataset's questions.

A grain is read once per settled period: the reading names the last day it covers, and the next
reading is due only when the newest settled period ends later.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from aughor.explorer import program as P

#: A settled figure that moved at least this much from the period before reopens the questions.
MOVED = 0.10
#: The Briefing's preset that reads each grain's newest settled period.
PRESET_FOR = {"day": "yesterday", "week": "last_week", "month": "last_month", "year": "last_year"}


def grain_of(m: Any) -> str:
    g = str(getattr(m, "time_grain", "") or "").lower()
    return g if g in PRESET_FOR or g == "quarter" else "day"


def _quarter_spec(conn_id: str, resolve: Callable, today: date):
    """The newest settled quarter, as a custom range — the Briefing has no quarter preset."""
    month, _ = resolve(conn_id, "last_month", today=today)
    if month is None:
        return None
    last = month.last_day                     # the newest settled month's last day
    m, year = (last.month if last.month % 3 == 0 else (last.month // 3) * 3), last.year
    if m == 0:                                # before March: the quarter that closed in December
        m, year = 12, year - 1
    end = date(year + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(days=1)
    start = date(year, m - 2, 1)
    spec, _ = resolve(conn_id, "custom", start=start, end=end, today=today)
    return spec


def due(conn_id: str, schema: Optional[str], prog: dict, *, today: Optional[date] = None,
        metrics: Optional[list] = None, resolve: Optional[Callable] = None) -> list[tuple[str, Any]]:
    """``[(grain, range)]`` whose newest settled period this dataset has not read yet."""
    from aughor.briefing import ranges as R
    from aughor.semantic import metric_time as mt
    today = today or datetime.now(timezone.utc).date()
    resolve = resolve or R.resolve_for
    if metrics is None:
        metrics = R.governed_metrics(conn_id, schema)
    grains = sorted({grain_of(m) for m in metrics if mt.declared(m)})
    out = []
    for g in grains:
        spec = (_quarter_spec(conn_id, resolve, today) if g == "quarter"
                else resolve(conn_id, PRESET_FOR[g], today=today)[0])
        if spec is None:
            continue
        seen = (prog.get("watch") or {}).get(g) or {}
        if str(seen.get("through") or "") < spec.last_day.isoformat():
            out.append((g, spec))
    return out


def moved_figures(measured: list[dict], grain_metrics: set[str]) -> list[dict]:
    """The settled figures of this grain that moved at least ``MOVED`` from the period before."""
    out = []
    for f in measured or []:
        if f.get("metric") not in grain_metrics or f.get("anchored"):
            continue                      # a dataset whose data ended has nothing new to move
        rel = f.get("rel")
        if rel is None or f.get("status") not in ("final", None):
            continue
        if abs(float(rel)) >= MOVED:
            out.append({"name": f.get("name"), "metric": f.get("metric"), "rel": round(float(rel), 4)})
    return out


def _fallback_dimensions(m: Any, profile_entry: dict) -> list[str]:
    """A metric with no declared dimension is broken down by the low-cardinality columns the profiler knows
    on its own table — not a key, not a date — so a move is still explained, by what is known of its table."""
    from aughor.semantic.metric_statement import split_grain
    from aughor.semantic.metric_time import bare_name
    grain = split_grain(getattr(m, "time_column", "") or "")[0] or ((getattr(m, "tables", None) or [""])[0])
    table = bare_name(str(grain or ""))
    out = []
    for prof in ((profile_entry or {}).get("columns") or {}).values():
        if not isinstance(prof, dict) or bare_name(str(prof.get("table") or "")) != table:
            continue
        dtype = str(prof.get("dtype") or "").lower()
        if prof.get("is_fk") or not prof.get("is_low_cardinality") or "date" in dtype or "time" in dtype:
            continue
        out.append(str(prof.get("column") or ""))
    return sorted(c for c in out if c)[:3]


def explain_moves(conn_id: str, moved: list[Any], spec: Any, *, runner: Optional[Callable] = None,
                  profile_entry: Optional[dict] = None) -> list[dict]:
    """§4 — time detects, dimensions explain: each moved figure broken down by its dimensions — declared,
    else the profiler's on its table — for the period and the one before, the segments ranked by how much
    of the move they carry (`briefing.recipes.what_moved`, the Briefing's own breakdown). SQL only.
    ``[{"metric", "name", "dimension", "group", "change", "current", "previous", "share"}]``, at most two a
    metric; a segment of too few rows to call is never one of them."""
    from aughor.briefing.recipes import breakdown_dimensions, what_moved
    from aughor.knowledge import period_brief
    if not moved:
        return []
    if profile_entry is None:
        from aughor.tools.profile_cache import merged_profile_entry
        profile_entry = merged_profile_entry(conn_id) or {}
    metrics = []
    for m in moved:
        if not breakdown_dimensions(m, profile_entry):
            dims = _fallback_dimensions(m, profile_entry)
            if dims and hasattr(m, "model_copy"):
                m = m.model_copy(update={"dimensions": dims})
        metrics.append(m)
    with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
        got = what_moved(metrics, spec, run_sql, dialect=dialect, profile_entry=profile_entry)
    out: list[dict] = []
    per: dict[str, int] = {}
    for c in got.get("moves") or []:
        if per.get(c["metric"], 0) >= 2:
            continue
        per[c["metric"]] = per.get(c["metric"], 0) + 1
        out.append({k: c.get(k) for k in ("metric", "name", "dimension", "group", "change", "current",
                                           "previous", "share")})
    return out


def explanation_line(e: dict) -> str:
    """One segment's part of a move, said plainly: "most of it country = US (-4,200)"."""
    change = e.get("change")
    amount = (f"{change:+.1f} pts" if e.get("share") and change is not None
              else f"{change:+,.0f}" if isinstance(change, (int, float)) else "")
    return f"{e.get('dimension')} = {e.get('group')}" + (f" ({amount})" if amount else "")


def read_due(conn_id: str, schema: Optional[str], *, reopen_questions: bool, today: Optional[date] = None,
             measure: Optional[Callable] = None, explain: Optional[Callable] = None) -> list[dict]:
    """Read every due grain of one dataset; record each reading; reopen on a real move. Returns the
    readings made. SQL only — never a model."""
    from aughor.briefing import ranges as R
    key = P.key_for(conn_id, schema)
    prog = P.load(key)
    metrics = R.governed_metrics(conn_id, schema)
    if not metrics:
        return []
    measure = measure or (lambda spec: R.measured_block(conn_id, spec, schema=schema))
    readings = []
    for grain, spec in due(conn_id, schema, prog, today=today, metrics=metrics):
        block = measure(spec)
        names = {m.name for m in metrics if grain_of(m) == grain}
        labels = {(m.label or m.name) for m in metrics if grain_of(m) == grain}
        measured = [f for f in (block.get("measured") or []) if f.get("metric") in names]
        unmeasured = [u for u in (block.get("unmeasured") or [])
                      if u.get("metric") in names or u.get("name") in labels]
        moved = moved_figures(measured, names)
        explained: list[dict] = []
        if moved:
            try:
                explained = (explain or (lambda ms, sp: explain_moves(conn_id, ms, sp)))(
                    [m for m in metrics if m.name in {x["metric"] for x in moved}], spec)
            except Exception as exc:  # noqa: BLE001 — the move stands, said without its segments
                from aughor.kernel.errors import tolerate
                tolerate(exc, "a moved figure could not be broken down", counter="explorer.explain_move",
                         conn_id=conn_id)
        reading = {"through": spec.last_day.isoformat(), "from": spec.start.isoformat(),
                   "measured": len(measured), "unmeasured": [u.get("name") for u in unmeasured][:12],
                   "moved": moved, "explained": explained}
        P.record_watch(key, grain, reading)
        if moved and reopen_questions:
            top = max(moved, key=lambda m: abs(m["rel"]))
            why = next((e for e in explained if e.get("metric") == top.get("metric")), None)
            P.reopen(key, f"{top['name']} moved {top['rel']:+.0%} in the {grain} to {reading['through']}"
                          + (f" — most of it {explanation_line(why)}" if why else ""))
        readings.append({"grain": grain, **reading})
    return readings
