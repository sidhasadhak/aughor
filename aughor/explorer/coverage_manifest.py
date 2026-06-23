"""The L2 coverage manifest — the *data-derived* question space a connection supports.

Today Scout's completeness is a fixed ~5-angle-per-domain checklist (agent.py `DOMAIN_ANGLES`)
capped by a 15/domain budget + novelty decay, so a 5-year warehouse and a one-table CSV hit
the same ~10-30-insight ceiling regardless of how much the data actually holds. That ceiling
is artificial: it measures coverage against a hand-written list, not against the data.

This module enumerates the manifest instead — the set of *material* baseline questions the
data supports — so completeness can be measured as a fraction of it and each run can advance
the frontier rather than redo the checklist. It is the L2 layer (KPI baselines) of the
ground-up knowledge stack (L0 structure → L1 metric defs → **L2 baselines** → L3 anomalies →
L4 explanation); the foundational layers (phases 3-7) already exist.

Sourcing is **profile-led with a profiled-measure fallback** (the design call): the business
profile's north-star KPIs lead, and any profiled *measure* the profile didn't name is added
mechanically — so blind spots in the business profile can't silently shrink the question space.

A manifest cell is one baseline question: a metric, optionally cut by a material dimension or
viewed over a time axis. Pure functions (profiles in, cells out) — no I/O, no LLM — so the
size is a deterministic, testable denominator.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Optional

# A dimension is "material" if it's a real low-cardinality cut — not an id/key/measure, and
# neither degenerate (≤1 value) nor a high-cardinality near-key.
_MAX_DIM_CARDINALITY = 50
# Time axes unlock with enough populated periods.
_MIN_PERIODS_TREND = 4
_MIN_PERIODS_SEASONALITY = 12
_MIN_PERIODS_YOY = 24

_NON_DIM_TYPES = {"id", "foreign_key", "measure", "metric", "key", "primary_key"}


@dataclass(frozen=True)
class ManifestCell:
    """One material baseline question (an L2 cell)."""
    metric: str                 # measure column or KPI name
    table: str                  # the fact table it's computed on ("(business)" for an unmapped KPI)
    axis: str                   # 'headline' | 'dimension' | 'trend' | 'seasonality' | 'yoy'
    cut: Optional[str]          # the dimension column when axis == 'dimension', else None
    source: str                 # 'profile' (named KPI) | 'profiled_measure' (fallback)


def _bare(name: str) -> str:
    """Last segment of a possibly schema-qualified name, lowered."""
    return str(name or "").split(".")[-1].strip().lower()


def _material_dimensions(cols: Iterable[Any], *, max_cardinality: int = _MAX_DIM_CARDINALITY) -> list[str]:
    out: list[str] = []
    for c in cols:
        if getattr(c, "is_fk", False):
            continue
        if (getattr(c, "semantic_type", "") or "").lower() in _NON_DIM_TYPES:
            continue
        if not getattr(c, "is_low_cardinality", False):
            continue
        n = getattr(c, "distinct_count", 0) or 0
        if 2 <= n <= max_cardinality:
            out.append(c.column)
    return sorted(set(out))


def _measures(cols: Iterable[Any]) -> list[Any]:
    """Profiled measures worth a baseline — a numeric measure with a real unit/range, not a key."""
    out = []
    for c in cols:
        if (getattr(c, "semantic_type", "") or "").lower() != "measure" or getattr(c, "is_fk", False):
            continue
        if getattr(c, "value_range", None) or getattr(c, "unit", None) or getattr(c, "value_interpretation", None):
            out.append(c)
    return out


def _time_axes(tprof: Any) -> list[str]:
    if not tprof or not getattr(tprof, "primary_timestamp", None):
        return []
    n = getattr(tprof, "n_periods", None) or 0
    if n < _MIN_PERIODS_TREND:
        return []
    axes = ["trend"]
    if n >= _MIN_PERIODS_SEASONALITY:
        axes.append("seasonality")
    if n >= _MIN_PERIODS_YOY:
        axes.append("yoy")
    return axes


def _ns_get(ns: Any, attr: str) -> str:
    return str(getattr(ns, attr, None) if not isinstance(ns, dict) else ns.get(attr, "") or "")


def _covered_measure_tokens(north_star: Iterable[Any]) -> set[str]:
    """Column-ish tokens named in any north-star metric's ``maps_to`` — a profiled measure whose
    column appears here is already represented by a business KPI (no fallback duplicate)."""
    toks: set[str] = set()
    for ns in north_star or ():
        for t in re.split(r"[^a-zA-Z0-9_]+", _ns_get(ns, "maps_to").lower()):
            if t:
                toks.add(t)
    return toks


def build_manifest(
    table_profiles: dict,
    column_profiles: dict,
    *,
    north_star: Iterable[Any] = (),
    max_dim_cardinality: int = _MAX_DIM_CARDINALITY,
) -> list[ManifestCell]:
    """Enumerate the material L2 cells for a connection.

    ``table_profiles`` = {table: TableProfile}; ``column_profiles`` = {key: ColumnProfile}
    (each ColumnProfile carries ``.table``/``.column``). ``north_star`` = the business profile's
    NorthStarMetric list (objects or dicts with ``name``/``maps_to``).
    """
    cols_by_table: dict[str, list] = defaultdict(list)
    for c in column_profiles.values():
        cols_by_table[getattr(c, "table", "")].append(c)

    all_tables = list(cols_by_table)
    covered = _covered_measure_tokens(north_star)
    cells: list[ManifestCell] = []

    def _emit(metric: str, table: str, source: str) -> None:
        dims = _material_dimensions(cols_by_table.get(table, []), max_cardinality=max_dim_cardinality)
        axes = _time_axes(table_profiles.get(table))
        cells.append(ManifestCell(metric, table, "headline", None, source))
        for d in dims:
            cells.append(ManifestCell(metric, table, "dimension", d, source))
        for a in axes:
            cells.append(ManifestCell(metric, table, a, None, source))

    # ── Primary: profile-led north-star KPIs ──────────────────────────────────
    for ns in north_star or ():
        name = _ns_get(ns, "name")
        if not name:
            continue
        maps = _ns_get(ns, "maps_to").lower()
        hit = [t for t in all_tables if _bare(t) and _bare(t) in maps]
        if hit:
            for t in hit:
                _emit(name, t, "profile")
        else:
            # Named KPI we couldn't map to a fact table — still a real baseline question.
            cells.append(ManifestCell(name, "(business)", "headline", None, "profile"))

    # ── Fallback: profiled measures the profile never named (blind-spot guard) ─
    for table, cols in cols_by_table.items():
        for m in _measures(cols):
            if _bare(m.column) in covered:
                continue                      # already represented by a north-star KPI
            _emit(m.column, table, "profiled_measure")

    return cells


def summarize(cells: list[ManifestCell]) -> dict:
    """A compact, JSON-able size breakdown — the denominator + how it's composed."""
    by_axis: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    metrics: set[tuple] = set()
    for c in cells:
        by_axis[c.axis] += 1
        by_source[c.source] += 1
        metrics.add((c.metric, c.table))
    return {
        "total_cells": len(cells),
        "distinct_metrics": len(metrics),
        "by_axis": dict(by_axis),
        "by_source": dict(by_source),
    }
