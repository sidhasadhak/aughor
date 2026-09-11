"""Object backings, measured (ON-1: the noun decouples from the table).

An object type is read FROM a backing — its table today, a keyed SELECT when a human sets
one. Either way the claim that its key is unique per instance is MEASURED here, the way
ON-0a measures every other claim: ``COUNT(*)``, ``COUNT(key)``, ``COUNT(DISTINCT key)``
over the backing's rows. A table backing that fails the check also corrects the entity's
``grain_verified`` — the builder's grain flag was a profile-derived inference, and on one
warehouse it read "verified" over 114 repeated keys. A human-set query backing lives in the
overrides tree; its uniqueness verdict is written onto the override's binding so the
overlay can carry it at read time without a database in hand.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from aughor.ontology.cardinality import quote_ident
from aughor.ontology.models import Backing, OntologyEntity, OntologyGraph

logger = logging.getLogger(__name__)


@dataclass
class BackingMeasurement:
    entity_id: str
    kind: str
    rows: Optional[int] = None
    non_null: Optional[int] = None
    distinct: Optional[int] = None
    unique: Optional[bool] = None
    note: str = ""


def measure_key(db: Any, from_clause: str, primary_key: str) -> tuple[Optional[tuple[int, int, int]], str]:
    """(rows, non-null keys, distinct keys) over a FROM fragment, or (None, why)."""
    if not from_clause or not primary_key:
        return None, "no backing or no primary key to measure"
    col = quote_ident(primary_key)
    sql = f"SELECT COUNT(*), COUNT({col}), COUNT(DISTINCT {col}) FROM {from_clause}"
    try:
        result = db.execute("__backing_probe__", sql)
    except Exception as exc:  # noqa: BLE001 — an unprobeable backing is unmeasured, not a failure
        return None, f"probe raised: {exc}"[:200]
    if getattr(result, "error", None) or not getattr(result, "rows", None):
        return None, f"probe failed: {getattr(result, 'error', '') or 'no rows'}"[:200]
    try:
        row = result.rows[0]
        return (int(row[0]), int(row[1]), int(row[2])), ""
    except (TypeError, ValueError, IndexError):
        return None, "probe returned an unreadable row"


def measure_backing(db: Any, backing: Backing, entity_id: str = "") -> BackingMeasurement:
    m = BackingMeasurement(entity_id=entity_id, kind=backing.kind)
    counts, why = measure_key(db, backing.from_clause(), backing.primary_key)
    if counts is None:
        m.note = why
        return m
    m.rows, m.non_null, m.distinct = counts
    m.unique = m.non_null > 0 and m.distinct == m.non_null
    m.note = (f"{backing.primary_key}: {m.distinct} distinct over {m.non_null} non-null rows"
              + ("" if m.unique else " — NOT unique per row"))
    return m


@dataclass
class BackingReport:
    measurements: list[BackingMeasurement] = field(default_factory=list)
    grain_corrected: list[str] = field(default_factory=list)
    overrides_measured: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"entities": len(self.measurements),
                "unique": [m.entity_id for m in self.measurements if m.unique is True],
                "not_unique": [{"entity": m.entity_id, "note": m.note} for m in self.measurements if m.unique is False],
                "unmeasurable": [m.entity_id for m in self.measurements if m.unique is None],
                "grain_corrected": list(self.grain_corrected),
                "overrides_measured": list(self.overrides_measured)}


def apply_backing_measurements(graph: OntologyGraph, db: Any) -> BackingReport:
    """Measure every entity's backing key; stamp `backing.verified`; correct a table
    backing's `grain_verified` when the data contradicts it (the data wins, the flag's
    old value survives in the note)."""
    report = BackingReport()
    for entity in graph.entities.values():
        if entity.backing is None:
            continue
        m = measure_backing(db, entity.backing, entity.id)
        report.measurements.append(m)
        if m.unique is None:
            entity.backing.verified = None
            entity.backing.verification_note = m.note
            continue
        entity.backing.verified = m.unique
        entity.backing.verification_note = m.note
        if entity.backing.kind == "table" and entity.grain_verified != m.unique:
            entity.backing.verification_note = f"grain_verified was {entity.grain_verified}; measured {m.unique} — {m.note}"
            entity.grain_verified = m.unique
            report.grain_corrected.append(entity.id)
    if report.grain_corrected:
        logger.info("[ontology:%s] grain corrected by measurement on %s", graph.connection_id, report.grain_corrected)
    return report


def measure_override_backings(connection_id: str, schema_name: Optional[str], db: Any,
                              report: Optional[BackingReport] = None) -> BackingReport:
    """Measure the key of every human-set query backing in the overrides tree and record
    the verdict on the override's binding (`unique`, `unique_note`), so the overlay carries
    `verified` at read time. Best-effort; an unreadable tree measures nothing."""
    report = report if report is not None else BackingReport()
    try:
        from aughor.ontology.overrides import load_overrides, save_override
        overrides = load_overrides(connection_id, schema_name or "default")
    except Exception:  # noqa: BLE001
        return report
    for ov in overrides:
        if ov.target_kind != "entity" or not isinstance(ov.fields.get("backing"), dict):
            continue
        spec = ov.fields["backing"]
        backing = Backing(**{k: v for k, v in spec.items() if k in Backing.model_fields})
        if backing.kind != "query":
            continue
        m = measure_backing(db, backing, ov.target_id)
        entry = dict(ov.binding.get("backing") or {"bound": True, "note": ""})
        entry.update({"unique": m.unique, "unique_note": m.note,
                      "sql": (backing.sql or "").strip(), "primary_key": backing.primary_key})
        ov.binding["backing"] = entry
        try:
            save_override(connection_id, schema_name or "default", ov)
            report.overrides_measured.append(ov.target_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("override backing measurement not saved for %s: %s", ov.target_id, exc)
        report.measurements.append(m)
    return report


def entity_from_clause(entity: OntologyEntity) -> str:
    """The FROM fragment an object is queried through — the seam ON-2's compiler reads."""
    if entity.backing is not None and entity.backing.from_clause():
        return entity.backing.from_clause()
    return entity.source_tables[0] if entity.source_tables else ""
