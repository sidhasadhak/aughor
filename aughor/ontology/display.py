"""ON-3b — the display property, measured (ROADMAP §3.15, amended 2026-09-11).

An object type declares the property that names its instances (`DisplayProperty`): proposed from the
profile when the builder leaves it empty, or set by a person through the overrides tree. Proposed or
declared, the claim that it NAMES objects is measured here the ON-0a way — ``COUNT(*)``,
``COUNT(col)``, ``COUNT(DISTINCT col)`` over the backing — and every reader (the object page, a list of
linked objects, the agent's summaries) asks `display_of` what titles an object instead of guessing from
column names on each read.

A property names objects when at least `NAMES_MIN_NON_NULL` of them carry a value and at least
`NAMES_MIN_DISTINCT` of those values differ. Two customers may share a name, so uniqueness is not the
bar; a category is not a name (a handful of values repeated across thousands of products), and neither
is a column most objects leave empty. A refuted PROPOSAL gives way to the key; a person's declaration
stands, with its measurement shown beside it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from aughor.ontology.cardinality import quote_ident
from aughor.ontology.models import Backing, OntologyEntity, OntologyGraph

logger = logging.getLogger(__name__)

#: The share of objects that must carry a value for a property to name them.
NAMES_MIN_NON_NULL = 0.9
#: The share of those values that must differ — below it the property is a category, not a name.
NAMES_MIN_DISTINCT = 0.5


def key_of(entity: OntologyEntity) -> str:
    """The column unique per instance: the backing's key, else the entity's identity key."""
    backing = entity.backing
    return (backing.primary_key if backing is not None else "") or entity.identity_key


def verdict(rows: Optional[int], non_null: Optional[int], distinct: Optional[int]) -> tuple[Optional[bool], str]:
    """Whether counted values name objects, and the evidence in words. None when there was nothing to count."""
    if rows is None or non_null is None or distinct is None:
        return None, "not measurable"
    if rows == 0:
        return None, "the backing has no rows to measure"
    detail = f"{non_null:,} of {rows:,} objects carry a value, {distinct:,} distinct"
    if non_null / rows < NAMES_MIN_NON_NULL:
        return False, f"{detail} — too many objects have none for it to name them"
    if distinct / non_null < NAMES_MIN_DISTINCT:
        return False, f"{detail} — too few distinct values: a category, not a name"
    return True, detail


@dataclass
class DisplayMeasurement:
    entity_id: str
    name: str
    source: str
    rows: Optional[int] = None
    non_null: Optional[int] = None
    distinct: Optional[int] = None
    verified: Optional[bool] = None
    note: str = ""


def measure_display(db: Any, entity: OntologyEntity, name: str, source: str = "proposed") -> DisplayMeasurement:
    """Count one property over the entity's backing. A probe that fails leaves it unmeasured, never refuted."""
    m = DisplayMeasurement(entity_id=entity.id, name=name, source=source)
    from_clause = entity.backing.from_clause() if entity.backing is not None else ""
    if not from_clause or not name:
        m.note = "no backing or no display property to measure"
        return m
    col = quote_ident(name)
    sql = f"SELECT COUNT(*), COUNT({col}), COUNT(DISTINCT {col}) FROM {from_clause}"
    try:
        result = db.execute("__display_probe__", sql)
    except Exception as exc:  # noqa: BLE001 — an unprobeable property is unmeasured, not a failure
        m.note = f"probe raised: {exc}"[:200]
        return m
    if getattr(result, "error", None) or not getattr(result, "rows", None):
        m.note = f"probe failed: {getattr(result, 'error', '') or 'no rows'}"[:200]
        return m
    try:
        row = result.rows[0]
        m.rows, m.non_null, m.distinct = int(row[0]), int(row[1]), int(row[2])
    except (TypeError, ValueError, IndexError):
        m.note = "probe returned an unreadable row"
        return m
    m.verified, m.note = verdict(m.rows, m.non_null, m.distinct)
    return m


@dataclass
class DisplayReport:
    measurements: list[DisplayMeasurement] = field(default_factory=list)
    overrides_measured: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"entities": len(self.measurements),
                "names": [m.entity_id for m in self.measurements if m.verified is True],
                "refuted": [{"entity": m.entity_id, "property": m.name, "note": m.note}
                            for m in self.measurements if m.verified is False],
                "unmeasurable": [m.entity_id for m in self.measurements if m.verified is None],
                "overrides_measured": list(self.overrides_measured)}


def apply_display_measurements(graph: OntologyGraph, db: Any) -> DisplayReport:
    """Measure every type's display property in ``graph`` and stamp the counts and the verdict on it.

    The measure door measures the RAW cached graph, whose display properties are the proposals; a person's
    declaration lives on its override and is measured by `measure_override_display_properties`."""
    report = DisplayReport()
    for entity in graph.entities.values():
        shown = entity.display_property
        if shown is None or not shown.name:
            continue
        m = measure_display(db, entity, shown.name, shown.source)
        shown.rows, shown.non_null, shown.distinct, shown.verified = m.rows, m.non_null, m.distinct, m.verified
        shown.note = m.note
        report.measurements.append(m)
    if any(m.verified is False for m in report.measurements):
        logger.info("[ontology:%s] display property refuted on %s", graph.connection_id,
                    [m.entity_id for m in report.measurements if m.verified is False])
    return report


def measure_override_display_properties(connection_id: str, schema_name: Optional[str], db: Any,
                                        graph: OntologyGraph,
                                        report: Optional[DisplayReport] = None) -> DisplayReport:
    """Measure every display property a person declared in the overrides tree and record the counts and the
    verdict on the override's binding, so the overlay carries them at read time without a database in hand.
    Measured over the backing the same override sets, when it sets one. Best-effort; an unreadable tree
    measures nothing."""
    report = report if report is not None else DisplayReport()
    try:
        from aughor.ontology.overrides import load_overrides, save_override
        overrides = load_overrides(connection_id, schema_name or "default")
    except Exception:  # noqa: BLE001
        return report
    for ov in overrides:
        name = ov.fields.get("display_property") if ov.target_kind == "entity" else None
        entity = graph.entities.get(ov.target_id)
        if not isinstance(name, str) or not name.strip() or entity is None:
            continue
        spec = ov.fields.get("backing")
        if isinstance(spec, dict):
            entity = entity.model_copy(update={"backing": Backing(**{k: v for k, v in spec.items()
                                                                    if k in Backing.model_fields})})
        m = measure_display(db, entity, name.strip(), "human")
        entry = dict(ov.binding.get("display_property") or {"bound": True, "note": ""})
        entry.update({"property": name.strip(), "rows": m.rows, "non_null": m.non_null, "distinct": m.distinct,
                      "verified": m.verified, "measured_note": m.note})
        ov.binding["display_property"] = entry
        try:
            save_override(connection_id, schema_name or "default", ov)
            report.overrides_measured.append(ov.target_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("display property measurement not saved for %s: %s", ov.target_id, exc)
        report.measurements.append(m)
    return report


def display_of(entity: OntologyEntity) -> dict:
    """What titles one object of this type, and on what warrant.

    ``{property, source, is_key, verified, rows, non_null, distinct, note}`` — the declared display
    property, unless it is a PROPOSAL the data refuted: then the key, with the refuted name kept under
    ``refuted``. ``source`` is ``proposed``, ``human`` or ``key``."""
    key = key_of(entity)
    shown = entity.display_property
    if shown is None or not shown.name or (shown.source == "proposed" and shown.verified is False):
        out = {"property": key, "source": "key", "is_key": True, "verified": None,
               "rows": None, "non_null": None, "distinct": None, "note": "the key names each object"}
        if shown is not None and shown.name and shown.verified is False:
            out.update({"refuted": shown.name,
                        "note": f"the proposed {shown.name} does not name objects ({shown.note}), so the key does"})
        return out
    return {"property": shown.name, "source": shown.source,
            "is_key": bool(key) and shown.name.lower() == key.lower(),
            "verified": shown.verified, "rows": shown.rows, "non_null": shown.non_null, "distinct": shown.distinct,
            "note": shown.note or ("not yet measured" if shown.verified is None else "")}
