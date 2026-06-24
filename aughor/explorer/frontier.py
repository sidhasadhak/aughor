"""Cut-level knowledge frontier for the explorer (Layer 1).

The explorer used to track coverage at coarse "angle" granularity
(``volume``/``value``/``retention``…). Once those ~5 named angles were "covered",
the generator was asked for vague "deeper_analysis / anomalies" with no concrete
target — so it circled back to cuts it had already run.

This module tracks coverage at the level of concrete ``measure × dimension``
cuts, derived from each finding's SQL signature
(:func:`aughor.sql.shape.query_signature`), and computes the FRONTIER — the
highest-value cuts NOT yet explored. The per-domain generator is then handed the
concrete top-K uncovered cuts ("revenue × channel, margin × category, …")
instead of "propose something deeper".

Both sides of the comparison use raw schema column names (a measure column, a
dimension column), so "covered" (parsed out of executed SQL) and the "universe"
(assembled from profiled columns) are directly comparable — no prose-metric vs.
column-name impedance mismatch.
"""
from __future__ import annotations

from dataclasses import dataclass

from aughor.sql.shape import query_signature


def _normcol(name: str) -> str:
    """Separator/case-insensitive column key — matches ``query_signature``'s own
    normalisation so SQL-parsed cuts and profiled-column cuts compare. Kept local
    (not imported from sql.shape's private helper) so the two stay decoupled."""
    return (name or "").replace("_", "").replace("-", "").replace(" ", "").lower()


@dataclass(frozen=True)
class Cut:
    """One analytical cell: a measure column sliced by a dimension column.

    ``dimension == ""`` is the headline (no group-by) cut of the measure.

    Cuts parsed out of executed SQL carry the signature's normalised column names
    (``query_signature`` strips ``_``/``-``/case); cuts built from the profiled
    schema carry readable names. :meth:`key` collapses both to the same normalised
    identity so the two sides compare — coverage matching is always on ``key()``,
    never on the readable fields."""
    measure: str
    dimension: str

    def key(self) -> tuple[str, str]:
        """Normalised identity, matching ``query_signature``'s column normalisation."""
        return (_normcol(self.measure), _normcol(self.dimension))

    def label(self) -> str:
        return f"{self.measure} by {self.dimension}" if self.dimension else f"{self.measure} (headline)"


def _measure_col(m: str) -> str:
    """Normalise a signature measure to its primary column.

    ``query_signature`` emits measures as ``"sum:revenue"`` / ``"count"`` /
    ``"avg:unit_price"``. The frontier compares on the underlying COLUMN so a
    ``SUM(revenue) by region`` finding covers the universe cell ``revenue×region``
    regardless of which aggregate produced it. ``count`` has no column → kept as-is."""
    if ":" in m:
        cols = m.split(":", 1)[1]
        return cols.split(",")[0].strip() if cols else m
    return m


def insight_cuts(sql: str, dialect: str = "duckdb") -> set[Cut]:
    """The set of ``measure × dimension`` cuts a query covers, from its signature.

    A query computing ``{sum:revenue}`` grouped by ``{region, channel}`` covers
    ``revenue×region`` and ``revenue×channel``; ungrouped it covers the
    ``revenue`` headline. Returns an empty set for unparseable SQL (fail-safe:
    such a finding simply doesn't advance the frontier)."""
    sig = query_signature(sql, dialect)
    if sig is None:
        return set()
    _tables, gkeys, measures = sig
    ms = {_measure_col(m) for m in (measures or set())} or {"count"}
    if not gkeys:
        return {Cut(m, "") for m in ms}
    return {Cut(m, g) for m in ms for g in gkeys}


def signature_fields(sql: str, dialect: str = "duckdb") -> dict:
    """Structured cut coordinates for storing on an insight: the tables it reads,
    its group-by dimensions, and its measures (normalised to columns). Populates the
    insight dict's hitherto-empty ``dimensions``/``measures`` and a ``signature``
    block — the substrate the frontier and the synthesis findings-graph read.
    Returns empty lists for unparseable SQL."""
    sig = query_signature(sql, dialect)
    if sig is None:
        return {"tables": [], "dimensions": [], "measures": []}
    tables, gkeys, measures = sig
    return {
        "tables": sorted(tables),
        "dimensions": sorted(gkeys),
        "measures": sorted({_measure_col(m) for m in (measures or set())}),
    }


def covered_cuts(insights, dialect: str = "duckdb") -> set[tuple[str, str]]:
    """The set of normalised cut KEYS covered across all prior findings —
    ready to subtract from a universe of (readable) cuts in :func:`rank_frontier`."""
    out: set[tuple[str, str]] = set()
    for i in insights or ():
        for c in insight_cuts(i.get("sql", "") or "", dialect):
            out.add(c.key())
    return out


def build_universe(measures, dimensions, *, include_headline: bool = True) -> set[Cut]:
    """The space of valuable cuts: every measure × every dimension (+ headline).

    ``measures`` and ``dimensions`` are raw column-name lists drawn from the
    profiled schema by the caller."""
    ms = [m for m in dict.fromkeys(measures) if m]
    ds = [d for d in dict.fromkeys(dimensions) if d]
    universe: set[Cut] = set()
    for m in ms:
        if include_headline:
            universe.add(Cut(m, ""))
        for d in ds:
            universe.add(Cut(m, d))
    return universe


def rank_frontier(universe: set[Cut], covered: set[tuple[str, str]], *, priority_measures=()) -> list[Cut]:
    """Uncovered cuts, ranked by value. Heuristic, deterministic:

    1. priority (profile north-star / recipe) measures first,
    2. then a dimensional cut before a bare headline (cuts reveal more),
    3. stable alphabetical tiebreak so runs are reproducible.

    ``covered`` is a set of normalised keys (from :func:`covered_cuts`); matching
    is on :meth:`Cut.key` so a readable-named universe cut and its SQL-parsed
    counterpart collapse to the same cell."""
    prio = {_normcol(m) for m in priority_measures if m}
    frontier = [c for c in universe if c.key() not in covered]

    def sort_key(c: Cut):
        return (
            0 if _normcol(c.measure) in prio else 1,
            0 if c.dimension else 1,
            c.measure,
            c.dimension,
        )

    return sorted(frontier, key=sort_key)


def render_frontier_block(frontier: list[Cut], k: int = 8) -> str:
    """A prompt block naming the concrete unexplored high-value cuts. Empty string
    when the frontier is exhausted (caller falls back to free-form deepening)."""
    if not frontier:
        return ""
    items = ", ".join(c.label() for c in frontier[:k])
    return (
        "UNEXPLORED HIGH-VALUE CUTS (pick one you have NOT covered — these are "
        f"measure×dimension cells with no finding yet):\n  {items}\n\n"
    )
