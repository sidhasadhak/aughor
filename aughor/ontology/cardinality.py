"""Relationship cardinality, measured against the data (ON-0a, first commit).

The builder infers a relationship's cardinality from profiled distinct counts and falls to
"N:N" when a side's column profile is missing — so on the LuxExperience demo warehouse
several N:1 and 1:1 joins reached the SQL prompt labelled N:N *and verified*: the join-value
pass had proved the KEYS overlap, and nothing had ever measured the CARDINALITY (ROADMAP
§3.15, the ON-0 receipt). An N:N label under the block's CARDINALITY sentence tells the model
nothing about which side to pre-aggregate; on the one hard-set question the block could have
won, it said nothing.

A side is "1" when its key is unique over its non-null rows, else "N"; the label reads
left→right exactly like the prompt's own sentence ('a.x → b.y [N:1]' = many a-rows per
b-row). Measured from ``COUNT(*)``, ``COUNT(col)`` and ``COUNT(DISTINCT col)`` — exact,
dialect-neutral, one scan per side. A measured label REPLACES a contradicted authored one
and the authored value survives in ``cardinality_note``; an unmeasurable side (empty table,
missing table, failed probe) leaves the label untouched and says so — never demote what we
could not check.

    python -m aughor.ontology.cardinality --graph-json served.json --duckdb wh.duckdb --out measured.json
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

from aughor.ontology.models import OntologyGraph, OntologyRelationship

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    """Quote an identifier only when it needs it (`Product type` does; `order_id` does not)."""
    return name if _IDENT.match(name) else '"' + name.replace('"', '""') + '"'


def quote_table(table: str) -> str:
    return ".".join(quote_ident(part) for part in table.split("."))


@dataclass
class SideCount:
    """One side of a join edge, counted: rows, non-null key rows, distinct key values."""
    table: str
    column: str
    rows: int
    non_null: int
    distinct: int

    @property
    def unique(self) -> bool:
        return self.non_null > 0 and self.distinct == self.non_null

    @property
    def side(self) -> str:
        return "1" if self.unique else "N"


def measure_side(db: Any, table: str, column: str) -> Optional[SideCount]:
    """Count one side; None when the probe fails (missing table/column, dialect refusal)."""
    col = quote_ident(column)
    sql = f"SELECT COUNT(*), COUNT({col}), COUNT(DISTINCT {col}) FROM {quote_table(table)}"
    try:
        result = db.execute("__cardinality_probe__", sql)
    except Exception as exc:  # noqa: BLE001 — a probe that raises is an unmeasurable side, not a build failure
        logger.debug("cardinality probe raised on %s.%s: %s", table, column, exc)
        return None
    if getattr(result, "error", None) or not getattr(result, "rows", None):
        return None
    row = result.rows[0]
    try:
        rows, non_null, distinct = int(row[0]), int(row[1]), int(row[2])
    except (TypeError, ValueError, IndexError):
        return None
    return SideCount(table, column, rows, non_null, distinct)


def label_for(from_side: SideCount, to_side: SideCount) -> str:
    """'from:to' — many from-rows per to-row is N:1, read left→right like the prompt."""
    return f"{from_side.side}:{to_side.side}"


@dataclass
class Measurement:
    relationship_id: str
    authored: str
    measured: Optional[str]
    note: str
    from_count: Optional[SideCount] = None
    to_count: Optional[SideCount] = None

    @property
    def contradicted(self) -> bool:
        return self.measured is not None and self.measured != self.authored


def measure_relationship(db: Any, rel: OntologyRelationship) -> Measurement:
    fc = measure_side(db, rel.from_table, rel.from_col)
    tc = measure_side(db, rel.to_table, rel.to_col)
    missing = [f"{rel.from_table}.{rel.from_col}" for _ in [0] if fc is None or fc.non_null == 0]
    missing += [f"{rel.to_table}.{rel.to_col}" for _ in [0] if tc is None or tc.non_null == 0]
    if missing:
        return Measurement(rel.id, rel.cardinality, None,
                           f"not measurable: no non-null rows or no probe result on {', '.join(missing)}",
                           fc, tc)
    measured = label_for(fc, tc)
    detail = (f"{rel.from_table}.{rel.from_col} {fc.distinct} distinct over {fc.non_null} non-null rows"
              f" ({fc.side}); {rel.to_table}.{rel.to_col} {tc.distinct} distinct over {tc.non_null}"
              f" non-null rows ({tc.side})")
    note = (f"measured {measured}: {detail}" if measured == rel.cardinality
            else f"authored {rel.cardinality}, measured {measured}: {detail}")
    return Measurement(rel.id, rel.cardinality, measured, note, fc, tc)


@dataclass
class CardinalityReport:
    measurements: list[Measurement] = field(default_factory=list)

    @property
    def contradicted(self) -> list[Measurement]:
        return [m for m in self.measurements if m.contradicted]

    @property
    def confirmed(self) -> list[Measurement]:
        return [m for m in self.measurements if m.measured is not None and not m.contradicted]

    @property
    def unmeasurable(self) -> list[Measurement]:
        return [m for m in self.measurements if m.measured is None]

    def summary(self) -> dict:
        return {"relationships": len(self.measurements), "confirmed": len(self.confirmed),
                "contradicted": [{"id": m.relationship_id, "authored": m.authored, "measured": m.measured}
                                 for m in self.contradicted],
                "unmeasurable": [m.relationship_id for m in self.unmeasurable]}


def apply_cardinality_measurements(graph: OntologyGraph, db: Any) -> CardinalityReport:
    """Measure every relationship in ``graph`` against ``db`` and stamp the result.

    ``measured_cardinality`` and ``cardinality_note`` are set on every measurable edge; a
    contradicted ``cardinality`` is REPLACED by the measurement (the authored label is kept
    in the note), so the relationship block renders what the data says. Unmeasurable edges
    keep their label and carry a note saying why. Mutates and returns via the report.
    """
    report = CardinalityReport()
    for rel in graph.relationships.values():
        m = measure_relationship(db, rel)
        rel.cardinality_note = m.note
        if m.measured is not None:
            rel.measured_cardinality = m.measured  # type: ignore[assignment]
            if m.measured != rel.cardinality:
                rel.cardinality = m.measured  # type: ignore[assignment]
        report.measurements.append(m)
    if report.contradicted:
        logger.info("[ontology:%s] cardinality measured: %d relationship(s) relabelled — %s",
                    graph.connection_id, len(report.contradicted),
                    "; ".join(f"{m.relationship_id} {m.authored}→{m.measured}" for m in report.contradicted))
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Measure a served ontology graph's relationship cardinalities against a DuckDB file")
    ap.add_argument("--graph-json", required=True, help="the JSON of GET /ontology?connection_id=…&schema_name=…")
    ap.add_argument("--duckdb", required=True, help="DuckDB file the graph's tables live in (opened read-only)")
    ap.add_argument("--out", default=None, help="write the measured graph here (default: report only)")
    args = ap.parse_args(argv)
    from aughor.db.connection import open_connection
    graph = OntologyGraph.model_validate(json.loads(Path(args.graph_json).read_text()))
    db = open_connection("duckdb", str(Path(args.duckdb)), schema_name=graph.schema_name,
                         connection_id=graph.connection_id)
    try:
        report = apply_cardinality_measurements(graph, db)
    finally:
        db.close()
    print(f"{graph.connection_id}/{graph.schema_name}: {len(report.measurements)} relationship(s) — "
          f"{len(report.confirmed)} confirmed, {len(report.contradicted)} relabelled, "
          f"{len(report.unmeasurable)} unmeasurable")
    for m in report.measurements:
        mark = "✗→" if m.contradicted else ("· " if m.measured else "? ")
        print(f"  {mark} {m.relationship_id:44} {m.authored:>4} → {m.measured or '?':4}  {m.note[:110]}")
    if args.out:
        Path(args.out).write_text(json.dumps(graph.model_dump(mode="json"), indent=2, default=str))
        print(f"measured graph → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
