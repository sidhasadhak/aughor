"""Lifecycle terminal states, measured against the data (ON-0a, second commit).

The enricher proposes an entity's lifecycle — the column, its states, which of them are
terminal — and the builder derives the active filter and the `get_active_*` action from the
terminal set. The validator proved those segments EXECUTE; nothing checked the claim. On the
bundled samples warehouse the served ontology listed two terminal order states while 500
orders sat in `refunded` (ROADMAP §3.15, the ON-0 receipt), so "active orders" over-counted
by exactly those rows and the prompt rendered the claim as fact.

What a snapshot can and cannot prove. It CAN show an observed state the lists never named
(the enricher did not see the whole domain) and it CAN show rows that LEFT a claimed terminal
state — when a per-state timestamp column exists (`delivered_at`, `cancelled_date` …), a row
now in another state with that timestamp set passed through the state and moved on. Either
is a contradiction and sets `lifecycle_verified=False`. It CANNOT prove a state is final, so
an observed state whose NAME is an end state in the core map (`refunded`, `returned`,
`rejected` …) but is missing from `terminal_states` is reported as UNCONFIRMED — rendered
beside the claim, never as a verdict, for a human to confirm or override (the pack will own
that list: ON-0a part 3). A contradicted lifecycle downgrades the segment derived from it,
so the VERIFIED SEMANTIC LAYER stops offering a filter the data refutes.

    python -m aughor.ontology.lifecycle --graph-json served.json --duckdb wh.duckdb --out measured.json
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from aughor.ontology.cardinality import quote_ident, quote_table
from aughor.ontology.models import OntologyEntity, OntologyGraph

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: End-state NAMES the core e-commerce/operations map expects to be terminal. Reported as
#: unconfirmed when observed and not in `terminal_states`; never a contradiction on their own.
#: Deliberately excludes states a later transition commonly leaves (`captured` → refunded,
#: `shipped` → delivered, `paid` → refunded).
CORE_END_STATE_NAMES = frozenset({
    "delivered", "completed", "complete", "closed", "cancelled", "canceled", "refunded",
    "returned", "rejected", "reject", "failed", "expired", "void", "voided", "fulfilled",
    "done", "finished", "terminated", "resolved", "archived", "lost", "won", "churned",
})

#: Column-name shapes that carry the moment a row reached a state: `<state>_at` first.
_TIMESTAMP_SUFFIXES = ("_at", "_date", "_on", "_ts", "_time")


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _rows(db: Any, sql: str) -> Optional[list]:
    try:
        result = db.execute("__lifecycle_probe__", sql)
    except Exception as exc:  # noqa: BLE001 — a probe that raises is an unmeasurable claim, not a build failure
        logger.debug("lifecycle probe raised: %s", exc)
        return None
    if getattr(result, "error", None) or getattr(result, "rows", None) is None:
        return None
    return list(result.rows)


def observed_states(db: Any, table: str, column: str) -> Optional[dict[str, int]]:
    """The column's non-null value domain with row counts; None when it cannot be read."""
    col = quote_ident(column)
    rows = _rows(db, f"SELECT {col}, COUNT(*) FROM {quote_table(table)} WHERE {col} IS NOT NULL GROUP BY 1")
    if rows is None:
        return None
    out: dict[str, int] = {}
    for r in rows:
        try:
            out[str(r[0])] = int(r[1])
        except (TypeError, ValueError, IndexError):
            continue
    return out


def rows_that_left(db: Any, table: str, column: str, state: str) -> Optional[int]:
    """Rows now in another state whose `<state>_at`-style timestamp is set — they passed
    through `state` and moved on. None when no such timestamp column exists."""
    if not _IDENT.match(state):
        return None
    col = quote_ident(column)
    for suffix in _TIMESTAMP_SUFFIXES:
        ts = quote_ident(f"{state}{suffix}")
        rows = _rows(db, f"SELECT COUNT(*) FROM {quote_table(table)} "
                         f"WHERE {ts} IS NOT NULL AND {col} <> {_sql_literal(state)}")
        if rows:
            try:
                return int(rows[0][0])
            except (TypeError, ValueError, IndexError):
                return None
    return None


@dataclass
class LifecycleMeasurement:
    entity_id: str
    table: str
    column: str
    observed: dict[str, int] = field(default_factory=dict)
    unclassified: dict[str, int] = field(default_factory=dict)   # observed, named in neither list
    vanished: list[str] = field(default_factory=list)            # listed, never observed
    refuted: dict[str, int] = field(default_factory=dict)        # terminal state → rows that left it
    unconfirmed: dict[str, int] = field(default_factory=dict)    # end-state names not listed as terminal
    verdict: Optional[bool] = None
    note: str = ""

    @property
    def contradicted(self) -> bool:
        return self.verdict is False


def _note(m: LifecycleMeasurement) -> str:
    parts: list[str] = []
    if m.unclassified:
        parts.append("contradicted: observed but unlisted "
                     + ", ".join(f"'{s}' ({n} rows)" for s, n in m.unclassified.items()))
    if m.refuted:
        parts.append("contradicted: " + ", ".join(
            f"'{t}' is not terminal — {n} rows left it (its timestamp is set on rows now in another state)"
            for t, n in m.refuted.items()))
    if m.unconfirmed:
        parts.append("unconfirmed: " + ", ".join(f"'{s}' ({n} rows)" for s, n in m.unconfirmed.items())
                     + " reads as an end state and is not in terminal_states — confirm or override")
    if m.vanished:
        parts.append("never observed: " + ", ".join(f"'{s}'" for s in m.vanished))
    return "; ".join(parts)


def measure_entity(db: Any, entity: OntologyEntity) -> Optional[LifecycleMeasurement]:
    """None when the entity claims no lifecycle; otherwise a measurement (verdict None when
    the column could not be read)."""
    if not entity.lifecycle_column or not entity.source_tables:
        return None
    table, column = entity.source_tables[0], entity.lifecycle_column
    m = LifecycleMeasurement(entity.id, table, column)
    obs = observed_states(db, table, column)
    if obs is None:
        m.note = f"not measurable: {table}.{column} could not be read"
        return m
    m.observed = obs
    listed = set(entity.lifecycle_states) | set(entity.terminal_states)
    m.unclassified = {s: n for s, n in obs.items() if s not in listed}
    m.vanished = [s for s in entity.lifecycle_states if s not in obs]
    for t in entity.terminal_states:
        left = rows_that_left(db, table, column, t)
        if left:
            m.refuted[t] = left
    m.unconfirmed = {s: n for s, n in obs.items()
                     if s.lower() in CORE_END_STATE_NAMES and s not in entity.terminal_states}
    m.verdict = not (m.unclassified or m.refuted)
    m.note = _note(m)
    return m


@dataclass
class LifecycleReport:
    measurements: list[LifecycleMeasurement] = field(default_factory=list)

    @property
    def contradicted(self) -> list[LifecycleMeasurement]:
        return [m for m in self.measurements if m.verdict is False]

    @property
    def unconfirmed(self) -> list[LifecycleMeasurement]:
        return [m for m in self.measurements if m.unconfirmed and m.verdict is not None]

    @property
    def unmeasurable(self) -> list[LifecycleMeasurement]:
        return [m for m in self.measurements if m.verdict is None]

    def summary(self) -> dict:
        return {
            "entities": len(self.measurements),
            "clean": len([m for m in self.measurements if m.verdict and not m.unconfirmed]),
            "contradicted": [{"entity": m.entity_id, "note": m.note} for m in self.contradicted],
            "unconfirmed": [{"entity": m.entity_id, "states": m.unconfirmed} for m in self.unconfirmed],
            "unmeasurable": [m.entity_id for m in self.unmeasurable],
        }


def apply_lifecycle_measurements(graph: OntologyGraph, db: Any) -> LifecycleReport:
    """Measure every entity that claims a lifecycle and stamp the verdict and its note.

    A contradicted lifecycle also downgrades the segment derived from it (the default
    `source == "lifecycle"` segment, the active filter), so the semantic-layer block stops
    offering a filter the data refutes. An unconfirmed end state changes no verdict — it is
    rendered beside the claim for a human to settle.
    """
    report = LifecycleReport()
    for entity in graph.entities.values():
        m = measure_entity(db, entity)
        if m is None:
            continue
        entity.lifecycle_verified = m.verdict
        entity.lifecycle_note = m.note
        if m.verdict is False:
            for seg in entity.segments.values():
                if seg.source == "lifecycle" and seg.is_default and seg.filter_sql:
                    seg.verified = False
                    seg.verification_note = f"derived from a contradicted lifecycle — {m.note}"[:300]
        report.measurements.append(m)
    if report.contradicted:
        logger.info("[ontology:%s] lifecycle measured: %d entity(ies) contradicted — %s",
                    graph.connection_id, len(report.contradicted),
                    "; ".join(f"{m.entity_id}: {m.note}" for m in report.contradicted))
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Measure a served ontology graph's lifecycles against a DuckDB file")
    ap.add_argument("--graph-json", required=True, help="the JSON of GET /ontology?connection_id=…&schema_name=…")
    ap.add_argument("--duckdb", required=True, help="DuckDB file the graph's tables live in (opened read-only)")
    ap.add_argument("--out", default=None, help="write the measured graph here (default: report only)")
    args = ap.parse_args(argv)
    from aughor.db.connection import open_connection
    graph = OntologyGraph.model_validate(json.loads(Path(args.graph_json).read_text()))
    db = open_connection("duckdb", str(Path(args.duckdb)), schema_name=graph.schema_name,
                         connection_id=graph.connection_id)
    try:
        report = apply_lifecycle_measurements(graph, db)
    finally:
        db.close()
    s = report.summary()
    print(f"{graph.connection_id}/{graph.schema_name}: {s['entities']} lifecycle(s) — {s['clean']} clean, "
          f"{len(s['contradicted'])} contradicted, {len(s['unconfirmed'])} unconfirmed, {len(s['unmeasurable'])} unmeasurable")
    for m in report.measurements:
        mark = "✗ " if m.verdict is False else ("? " if m.verdict is None else ("~ " if m.unconfirmed else "· "))
        print(f"  {mark}{m.entity_id:18} {m.column:14} observed={m.observed}  {m.note[:120]}")
    if args.out:
        Path(args.out).write_text(json.dumps(graph.model_dump(mode="json"), indent=2, default=str))
        print(f"measured graph → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
