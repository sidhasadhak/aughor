"""
M24c — Ontology semantic self-validation.

The enricher (M12b) emits metric formulas, computed-property expressions, and
object-set filters that are *never executed*. This module runs each of them
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
import re
from typing import Any

from aughor.ontology.models import OntologyGraph

# Bump when the validation logic below changes — cached graphs with a lower
# version are re-validated automatically (same pattern as ENRICHMENT_VERSION).
VALIDATION_VERSION = 1

_OVERFLOW = 1e15

# AGG(...) * AGG(...) — product of two aggregates, the $3T metric anti-pattern.
_PRODUCT_OF_AGGS = re.compile(
    r"\b(?:SUM|COUNT|AVG|MIN|MAX)\s*\([^)]*\)\s*\*\s*(?:SUM|COUNT|AVG|MIN|MAX)\s*\(",
    re.IGNORECASE,
)


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


# ── Public API ────────────────────────────────────────────────────────────────

def validate_semantics(graph: OntologyGraph, db: Any) -> OntologyGraph:
    """Execute every metric / computed-property / object-set against `db` and set
    each one's `verified` flag in place. Returns the same graph, marked validated.

    Best-effort: any unexpected error leaves that item unverified rather than
    raising, so a flaky probe never breaks ontology construction.
    """
    # ── Metrics ───────────────────────────────────────────────────────────────
    for m in graph.metrics.values():
        try:
            table = (m.tables[0] if m.tables else "") or _entity_table(graph, m.entity)
            if not table:
                m.verified, m.verification_note = False, "no source table to probe"
                continue
            if _PRODUCT_OF_AGGS.search(m.formula_sql or ""):
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
        table = entity.source_tables[0] if entity.source_tables else ""
        for cp in entity.computed_properties:
            try:
                if not table:
                    cp.verified, cp.verification_note = False, "entity has no source table"
                    continue
                ok, err, val = _probe(db, f"SELECT ({cp.formula_sql}) AS v FROM {table} LIMIT 1")
                if not ok:
                    cp.verified, cp.verification_note = False, f"did not execute: {err}"
                    continue
                sane, note = _check_value(val)
                cp.verified, cp.verification_note = sane, ("" if sane else note)
            except Exception as e:  # pragma: no cover
                cp.verified, cp.verification_note = False, str(e)[:120]

        # ── Object sets (per entity) ──────────────────────────────────────────
        for os_ in entity.object_sets.values():
            try:
                if not (os_.filter_sql or "").strip():
                    os_.verified, os_.verification_note = True, ""   # all-rows view
                    continue
                if not table:
                    os_.verified, os_.verification_note = False, "entity has no source table"
                    continue
                ok, err, _ = _probe(db, f"SELECT COUNT(*) FROM {table} WHERE {os_.filter_sql}")
                os_.verified, os_.verification_note = ok, ("" if ok else f"filter failed: {err}")
            except Exception as e:  # pragma: no cover
                os_.verified, os_.verification_note = False, str(e)[:120]

    graph.validated = True
    graph.validation_version = VALIDATION_VERSION
    return graph


def _entity_table(graph: OntologyGraph, entity_id: str) -> str:
    ent = graph.entities.get(entity_id)
    return ent.source_tables[0] if ent and ent.source_tables else ""
