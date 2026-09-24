"""
M24c — Ontology semantic self-validation.

The enricher (M12b) emits metric formulas, computed-property expressions, and
segment filters that are *never executed*. This module runs each of them
against the live database and marks the survivors `verified=True`. Only verified
semantics are injected into the NL2SQL prompt with authority (see
ontology.semantic_block + semantic.metrics overlay), so an LLM-hallucinated
formula can no longer silently corrupt an answer.

Validation is conservative on purpose (the semantic_validator false-positive
scar): a formula is demoted ONLY when it
  1. raises a SQL error (wrong column, bad function, multi-table single-probe),
  2. returns a non-finite or overflow-magnitude value (> 1e15), or
  3. matches the product-of-aggregates anti-pattern — AGG(...) * AGG(...) — the
     exact class of the $3T `SUM(final_price_usd) * SUM(quantity)` bug.
Everything else (including a clean NULL on empty data) stays verified.

Runs once per (connection, fingerprint): build_intelligence() gates on
graph.validation_version and persists the result, so it is off the query hot path.
"""
from __future__ import annotations

import math
from typing import Any

from aughor.ontology.models import OntologyGraph
from aughor.sql.analyze import analyze

# Bump when the validation logic below changes — cached graphs with a lower
# version are re-validated automatically (same pattern as ENRICHMENT_VERSION).
VALIDATION_VERSION = 1

_OVERFLOW = 1e15


def _to_float(cell: Any) -> float | None:
    """Best-effort parse of a (stringified) result cell to float; None if not numeric."""
    if cell is None:
        return None
    s = str(cell).strip()
    if s == "" or s.upper() == "NULL":
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _probe(db: Any, sql: str) -> tuple[bool, str, Any]:
    """Run a guarded probe query. Returns (ok, error_msg, first_cell)."""
    try:
        res = db.execute("__ontology_validate__", sql)
    except Exception as e:  # pragma: no cover — defensive
        return False, str(e)[:200], None
    if getattr(res, "error", None):
        return False, str(res.error)[:200], None
    rows = getattr(res, "rows", None) or []
    first = rows[0][0] if rows and rows[0] else None
    return True, "", first


def _check_value(value: Any) -> tuple[bool, str]:
    """Magnitude sanity on a numeric probe result. Non-numeric / NULL pass."""
    v = _to_float(value)
    if v is None:
        return True, ""
    if not math.isfinite(v):
        return False, "formula returned a non-finite value"
    if abs(v) > _OVERFLOW:
        return False, f"formula returned an overflow-magnitude value ({v:.3g})"
    return True, ""


#: How many rows a computed property is verified on (PENDING item 27 — it was one).
_FORMULA_ROWS = 1000


def _verify_formula_rows(db: Any, formula: str, table: str) -> tuple[bool, str]:
    """A computed property's formula run over the first `_FORMULA_ROWS` rows of its table, every value checked — it
    was run on ONE row, so a formula that fails past it, or is empty on every row, verified. Values are read rather
    than aggregated: MIN/MAX over a boolean formula does not run everywhere."""
    rows = f"SELECT ({formula}) AS v FROM (SELECT * FROM {table} LIMIT {_FORMULA_ROWS}) AS _s"
    try:
        # counted in SQL — exact over every row checked; a result's returned rows are capped
        counted = db.execute("__ontology_validate__", f"SELECT COUNT(*) AS n, COUNT(v) AS held FROM ({rows}) AS _v")
        res = None if getattr(counted, "error", None) else db.execute("__ontology_validate__", rows)
    except Exception as e:  # noqa: BLE001 — defensive, like `_probe`
        return False, f"did not execute: {str(e)[:200]}"
    error = getattr(counted, "error", None) or getattr(res, "error", None)
    if error:
        return False, f"did not execute: {str(error)[:200]}"
    n, held = (int(float(v or 0)) for v in ((counted.rows or [[0, 0]])[0] + [0, 0])[:2])
    for row in getattr(res, "rows", None) or []:
        value = row[0] if row else None
        if value is None or (isinstance(value, str) and value.strip().upper() == "NULL"):
            continue
        sane, note = _check_value(value)
        if not sane:
            return False, note
    if n and not held:
        return False, f"empty on every one of the {n:,} rows checked"
    return True, ""


# ── Public API ────────────────────────────────────────────────────────────────

def validate_semantics(graph: OntologyGraph, db: Any) -> OntologyGraph:
    """Execute every metric / computed-property / segment against `db` and set
    each one's `verified` flag in place. Returns the same graph, marked validated.

    Best-effort: any unexpected error leaves that item unverified rather than
    raising, so a flaky probe never breaks ontology construction.
    """
    _dialect = getattr(db, "dialect", "duckdb")
    # ── Metrics ───────────────────────────────────────────────────────────────
    for m in graph.metrics.values():
        try:
            table = (m.tables[0] if m.tables else "") or _entity_table(graph, m.entity)
            if not table:
                m.verified, m.verification_note = False, "no source table to probe"
                continue
            # Product-of-aggregates is now detected on the AST (shared analyze()
            # facade) rather than a regex — so a nested argument like
            # SUM(COALESCE(price,0)) * SUM(qty), which the old `AGG(...)*AGG(`
            # pattern silently missed, is caught.
            if analyze(m.formula_sql, dialect=_dialect).product_of_aggregates:
                m.verified, m.verification_note = False, (
                    "product-of-aggregates anti-pattern — AGG(...) * AGG(...) double-counts; "
                    "use SUM(a * b) per row instead"
                )
                continue
            ok, err, val = _probe(db, f"SELECT ({m.formula_sql}) AS v FROM {table}")
            if not ok:
                m.verified, m.verification_note = False, f"did not execute: {err}"
                continue
            sane, note = _check_value(val)
            m.verified, m.verification_note = sane, ("" if sane else note)
        except Exception as e:  # pragma: no cover
            m.verified, m.verification_note = False, str(e)[:120]

    # ── Computed properties (per entity) ──────────────────────────────────────
    for entity in graph.entities.values():
        table = _entity_table(graph, entity.id) if entity.source_tables else ""
        for cp in entity.computed_properties:
            try:
                if not table:
                    cp.verified, cp.verification_note = False, "entity has no source table"
                    continue
                cp.verified, cp.verification_note = _verify_formula_rows(db, cp.formula_sql, table)
            except Exception as e:  # pragma: no cover
                cp.verified, cp.verification_note = False, str(e)[:120]

        # ── Segments (per entity) ─────────────────────────────────────────────
        for seg in entity.segments.values():
            try:
                if not (seg.filter_sql or "").strip():
                    seg.verified, seg.verification_note = True, ""   # all-rows view
                    continue
                if not table:
                    seg.verified, seg.verification_note = False, "entity has no source table"
                    continue
                ok, err, _ = _probe(db, f"SELECT COUNT(*) FROM {table} WHERE {seg.filter_sql}")
                seg.verified, seg.verification_note = ok, ("" if ok else f"filter failed: {err}")
            except Exception as e:  # pragma: no cover
                seg.verified, seg.verification_note = False, str(e)[:120]

    graph.validated = True
    graph.validation_version = VALIDATION_VERSION
    return graph


def probe_query(db: Any, sql: str) -> tuple[bool, str, Any]:
    """Public face of `_probe` for other modules (2026-09-22): run a guarded probe, ``(ok, error, first cell)``."""
    return _probe(db, sql)


def check_value(value: Any) -> tuple[bool, str]:
    """Public face of `_check_value`: magnitude sanity on a numeric probe result."""
    return _check_value(value)


def entity_table(graph: OntologyGraph, entity_id: str) -> str:
    """Public face of `_entity_table`: the FROM clause a type's own rows are read from."""
    return _entity_table(graph, entity_id)


def _entity_table(graph: OntologyGraph, entity_id: str) -> str:
    """The FROM fragment the entity's SQL is probed against: its table (byte-identical to
    before ON-1) or, for a query-backed object, the keyed SELECT as a subquery."""
    ent = graph.entities.get(entity_id)
    if ent is None:
        return ""
    if ent.backing is not None and ent.backing.kind == "query" and ent.backing.sql:
        return ent.backing.from_clause()
    return ent.source_tables[0] if ent.source_tables else ""
