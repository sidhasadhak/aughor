"""How mature a dataset is — three readings a person can see (exploration principles §3, 2026-10-08).

=============  ===========================================================================
Structure      the platform knows its shape: profiled, then its empty values, joins,
               lifecycles, distributions and cross-table patterns read
Questions      its question space is explored: the question list's cells asked, or the
               last two runs found almost nothing new
Time           it is being watched: its approved metrics have dates, and each date grain's
               newest settled period has been read
=============  ===========================================================================

Each is a share (0–1) or None with the reason it does not apply — a staging dataset's Questions
reading says "not explored — raw" rather than 0%, and a dataset with no approved metric has no Time
reading at all. Computed from what is stored only — the exploration state, the dataset's program,
the profile cache, the metric store — so reading it never queries a warehouse and never builds.

``MATURE`` is the Questions share at which a dataset moves from exploring to watching: from then on
time is its only new factor, and only a named event reopens its questions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

#: The Questions share at which a dataset is watched rather than explored.
MATURE = 0.8
#: Two questions runs in a row that each found at most this many new findings: the space is saturated.
SATURATED_NEW = 1
#: The structure job's steps, in the order a run takes them.
STRUCTURE_STEPS = ("profiled", "null_meaning", "join_verification", "lifecycle_mapping",
                   "distribution", "cross_table")
#: How long a grain's reading stays current: a period and a little.
_GRAIN_DAYS = {"day": 2, "week": 8, "month": 32, "quarter": 93, "year": 367}


def _bar(share: Optional[float], note: str) -> dict:
    return {"share": None if share is None else round(max(0.0, min(1.0, share)), 3), "note": note}


def structure_bar(state: dict) -> dict:
    """How much of the structure job this dataset's state shows done."""
    phase = str(state.get("phase") or "pending")
    if state.get("structure_learned"):
        return _bar(1.0, "structure learned")
    if phase in ("domain_intel", "synthesis", "complete"):
        return _bar(1.0, "structure learned")
    if phase in STRUCTURE_STEPS:
        done = STRUCTURE_STEPS.index(phase)
        return _bar(done / len(STRUCTURE_STEPS), f"learning — {phase.replace('_', ' ')}")
    # failed or pending: read what was recorded
    done = sum(1 for k in ("null_meanings", "join_verifications", "lifecycle_maps", "distributions")
               if state.get(k)) + (1 if state.get("tables_total") else 0)
    if not done:
        return _bar(0.0, "not explored yet")
    return _bar(done / len(STRUCTURE_STEPS), "partly learned — the last run stopped")


def saturated(program: dict) -> bool:
    """The last two completed questions runs each found almost nothing new."""
    runs = [r for r in (program.get("runs") or [])
            if r.get("job") in ("questions", "full") and r.get("outcome") == "complete"]
    return len(runs) >= 2 and all(int(r.get("new_findings") or 0) <= SATURATED_NEW for r in runs[-2:])


def _covered_cells(state: dict) -> list:
    return [c for c in ((state.get("manifest_covered") or {}).get("cells") or [])
            if isinstance(c, (list, tuple)) and len(c) >= 2 and str(c[1]) != "(kpi)"]


def questions_bar(state: dict, program: dict, *, layer: str, explored_layers: frozenset,
                  table: str = "") -> dict:
    """How much of the question space is explored. ``explored_layers`` are the layers whose
    questions the platform asks; any other layer's reading is "not explored", said as such."""
    from aughor.ontology.dataset_layers import LABEL
    if layer and layer not in explored_layers:
        return _bar(None, f"not explored — {LABEL.get(layer, layer).lower()}")
    total_by_table = ((state.get("manifest_status") or {}).get("by_table") or {})
    covered = _covered_cells(state)
    if table:
        bare = table.split(".")[-1].lower()
        total = int(total_by_table.get(bare) or 0)
        n = sum(1 for c in covered if str(c[1]).split(".")[-1].lower() == bare)
        if not total:
            return _bar(None, "no question on its own") if total_by_table else _bar(None, "not measured yet")
        return _bar(n / total, f"{min(n, total)} of {total} questions asked")
    if saturated(program):
        return _bar(1.0, "the last two runs found almost nothing new")
    total = int((state.get("manifest_status") or {}).get("cells") or 0)
    if total:
        n = min(len(covered), total)
        note = f"{n} of {total} questions asked"
        if not layer:
            note += " — the rest wait for its layer to be set"
        return _bar(n / total, note)
    if state.get("domain_coverage"):
        return _bar(None, "explored before the question list was kept — the next run measures it")
    return _bar(0.0, "its questions wait for its layer to be set" if not layer else "not explored yet")


def _grain(m: Any) -> str:
    g = str(getattr(m, "time_grain", "") or "").lower()
    return g if g in _GRAIN_DAYS else "day"


def _current(reading: Optional[dict], grain: str, now: datetime) -> bool:
    if not reading or not reading.get("read_at"):
        return False
    try:
        at = datetime.fromisoformat(str(reading["read_at"]))
    except ValueError:
        return False
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return (now - at).days < _GRAIN_DAYS[grain]


def time_bar(metrics: list, program: dict, *, table: str = "", now: Optional[datetime] = None) -> dict:
    """Whether the dataset is watched: half for its approved metrics having dates, half for each
    of their date grains having its newest settled period read."""
    from aughor.semantic import metric_time as mt
    now = now or datetime.now(timezone.utc)
    if table:
        bare = table.split(".")[-1].lower()
        metrics = [m for m in metrics if bare in {mt.bare_name(t) for t in mt.tables_read(m)}]
    if not metrics:
        return _bar(None, "no approved metric reads it" if table else "no approved metrics to watch")
    dated = [m for m in metrics if mt.declared(m)]
    grains = sorted({_grain(m) for m in dated})
    watch = program.get("watch") or {}
    read = [g for g in grains if _current(watch.get(g), g, now)]
    share = 0.5 * len(dated) / len(metrics) + (0.5 * len(read) / len(grains) if grains else 0.0)
    if not dated:
        note = f"none of its {len(metrics)} approved metrics has dates"
    elif len(read) < len(grains):
        missing = [g for g in grains if g not in read]
        note = f"{len(dated)} of {len(metrics)} metrics dated · newest {', '.join(missing)} not read yet"
    else:
        note = f"{len(dated)} of {len(metrics)} metrics dated · newest {', '.join(grains)} read"
    return _bar(share, note)


def overall(bars: dict) -> Optional[int]:
    """The number beside the bars: the mean of the readings that apply, as a percentage."""
    shares = [b["share"] for b in bars.values() if b.get("share") is not None]
    return round(100 * sum(shares) / len(shares)) if shares else None


def maturity(state: dict, program: dict, metrics: list, *, layer: str, explored_layers: frozenset,
             table: str = "", profiled: bool = True) -> dict:
    """The three readings, the number beside them, and the stage they put the dataset (or table) in."""
    bars = {"structure": structure_bar(state) if not table else _table_structure(state, profiled),
            "questions": questions_bar(state, program, layer=layer, explored_layers=explored_layers, table=table),
            "time": time_bar(metrics, program, table=table)}
    pct = overall(bars)
    q = bars["questions"]["share"]
    return {**bars, "percent": pct,
            "stage": ("watching" if (q is not None and q >= MATURE) else "exploring" if q is not None else "learning")}


def _table_structure(state: dict, profiled: bool) -> dict:
    """A table's structure: profiled, and how far its dataset's structure job got."""
    return structure_bar(state) if profiled else _bar(0.0, "not profiled yet")
