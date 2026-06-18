"""Human ontology overrides — a fingerprint-independent, version-controlled overlay.

The structural ontology is auto-built and cached per schema *fingerprint*
(``store.get_or_build_ontology``). That cache is the wrong home for human edits:
the fingerprint includes ``row_count`` (store.py), so every data refresh on a
live warehouse mints a new key, rebuilds from scratch, and orphans any edit that
was written into the old entry. Override-wins didn't actually win.

This module is the fix. It mirrors the one pattern that already survives rebuilds
— learned actions, overlaid by ``store._overlay_learned_actions`` — and applies
it to human curations:

  • Stored OUTSIDE the fingerprint cache, keyed by ``{conn}/{schema}`` only, so a
    rebuild can never wipe them.
  • Persisted as a readable **YAML file tree** under
    ``data/ontology_overrides/{conn}/{schema}/{kind}/{id}.yaml`` — the same files
    are the runtime store *and* the version-controllable artifact (git diff / PR
    review), so there is no second representation to drift.
  • Re-applied on EVERY read via ``apply_overrides`` (wired beside
    ``_overlay_learned_actions``), on both the cache-hit and cache-miss branches.

Authority gate. ``ontology.semantic_block.render_semantic_layer`` injects an
object set / computed property into the NL2SQL prompt only when ``verified`` is
True. A human assertion must clear that gate — but not blindly: SQL-bearing
fields are EXPLAIN-bound against the live DB (``bind_overrides``) before they are
marked ``verified=True, verification_note="human-asserted"``. A human override
wins even when the LLM validator rejected the auto-derived value, yet a human
typo that won't bind is surfaced (``bound=False``) and never injected.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional

import yaml
from pydantic import BaseModel, Field

from aughor.ontology.models import (
    ComputedProperty,
    ObjectSet,
    OntologyEntity,
    OntologyGraph,
    OntologyMetric,
)

_ROOT = Path(__file__).parent.parent.parent / "data" / "ontology_overrides"

TargetKind = Literal["entity", "object_set", "computed_property", "metric"]

# Whitelist of fields a human may override, per target kind. Anything outside
# these sets is ignored on write *and* on apply, so an override file can never
# reshape the graph in ways the consumers don't expect.
_EDITABLE: dict[str, set[str]] = {
    "entity": {
        "description", "display_name", "domain", "active_filter",
        "default_filters", "exclude_when", "lifecycle_states", "terminal_states",
    },
    "object_set": {"display_name", "description", "filter_sql", "is_default"},
    "computed_property": {"label", "formula_sql", "unit"},
    "metric": {"display_name", "description", "formula_sql", "grain", "unit"},
}

# Fields whose value is SQL and must EXPLAIN-bind before they earn `verified`.
_SQL_FIELDS = {"active_filter", "filter_sql", "formula_sql"}


class OntologyOverride(BaseModel):
    """One human edit to one ontology target, with provenance and bind status.

    ``target_id`` is the entity/metric id for those kinds, and ``"{entity_id}::{local_id}"``
    for object sets and computed properties (which are nested under an entity).
    """
    target_kind: TargetKind
    target_id: str
    fields: dict[str, Any] = Field(default_factory=dict)
    source: str = "human"
    edited_by: str = ""
    edited_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    note: str = ""
    # Per-SQL-field bind result: {field_name: {"bound": bool, "note": str}}.
    # None for a field means "not yet validated" → treated as unbound (not injected).
    binding: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @property
    def entity_id(self) -> Optional[str]:
        """Owning entity for nested kinds; None for entity/metric targets."""
        if self.target_kind in ("object_set", "computed_property") and "::" in self.target_id:
            return self.target_id.split("::", 1)[0]
        return None

    @property
    def local_id(self) -> str:
        """The object-set / computed-property id within its entity (or the target id)."""
        return self.target_id.split("::", 1)[1] if "::" in self.target_id else self.target_id

    def sql_field_ok(self, field: str) -> bool:
        """True when an SQL field is present and has bound cleanly (so it may earn verified)."""
        b = self.binding.get(field)
        return bool(b and b.get("bound") is True)


# ── filesystem plumbing ─────────────────────────────────────────────────────

def _safe(s: str) -> str:
    """Filesystem-safe slug for a connection id / schema / target id."""
    return re.sub(r"[^A-Za-z0-9_.=-]", "_", s or "default")


def _dir(conn: str, schema: str) -> Path:
    return _ROOT / _safe(conn) / _safe(schema)


def _path(conn: str, schema: str, kind: TargetKind, target_id: str) -> Path:
    return _dir(conn, schema) / kind / f"{_safe(target_id)}.yaml"


# ── public store API ────────────────────────────────────────────────────────

def save_override(conn: str, schema: str, ov: OntologyOverride) -> None:
    """Write (replace) one override's YAML file. Best-effort — never raises."""
    try:
        p = _path(conn, schema, ov.target_kind, ov.target_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(ov.model_dump(), sort_keys=False, allow_unicode=True))
    except Exception:
        pass


def delete_override(conn: str, schema: str, kind: TargetKind, target_id: str) -> bool:
    """Remove one override file. Returns True if a file was deleted."""
    try:
        p = _path(conn, schema, kind, target_id)
        if p.exists():
            p.unlink()
            return True
    except Exception:
        pass
    return False


def load_overrides(conn: str, schema: str) -> list[OntologyOverride]:
    """Read every override under {conn}/{schema}, sorted for deterministic apply."""
    out: list[OntologyOverride] = []
    base = _dir(conn, schema)
    if not base.exists():
        return out
    for f in sorted(base.rglob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text()) or {}
            out.append(OntologyOverride.model_validate(data))
        except Exception:
            # A single corrupt/edited-by-hand file must not blind the others.
            continue
    return out


# ── overlay: apply overrides onto a graph ───────────────────────────────────

class OverlayReport(BaseModel):
    """What ``apply_overrides`` actually did — so callers can log/assert it FIRED.

    A silently-swallowed override looks identical to one that helped; this report
    exists so wiring can emit a fired/skipped counter instead of trusting a `pass`.
    """
    applied: list[str] = Field(default_factory=list)   # "kind:target_id (fields)"
    skipped: list[str] = Field(default_factory=list)   # "kind:target_id — reason"

    @property
    def count(self) -> int:
        return len(self.applied)


def _apply_entity(ent: OntologyEntity, ov: OntologyOverride) -> list[str]:
    touched: list[str] = []
    for field, value in ov.fields.items():
        if field not in _EDITABLE["entity"]:
            continue
        setattr(ent, field, value)
        touched.append(field)
        # active_filter is the fast-path WHERE used directly by the investigation
        # pipeline (no verified gate). Mirror it into the default object set so the
        # *prompt* path (render_semantic_layer) gets it too — but only verified
        # when the SQL bound.
        if field == "active_filter" and value:
            default_id = "active"
            os_ = ent.object_sets.get(default_id) or ObjectSet(
                id=default_id, display_name=f"Active {ent.display_name or ent.id}",
                is_default=True, source="manual",
            )
            os_.filter_sql = value
            os_.verified = ov.sql_field_ok("active_filter")
            os_.verification_note = "human-asserted" if os_.verified else (
                ov.binding.get("active_filter", {}).get("note", "") or "unbound"
            )
            ent.object_sets[default_id] = os_
    return touched


def _apply_object_set(ent: OntologyEntity, ov: OntologyOverride) -> list[str]:
    local = ov.local_id
    os_ = ent.object_sets.get(local) or ObjectSet(id=local, display_name=local, source="manual")
    touched: list[str] = []
    for field, value in ov.fields.items():
        if field not in _EDITABLE["object_set"]:
            continue
        setattr(os_, field, value)
        touched.append(field)
    # Earn verified only when its filter SQL bound (empty filter = all rows = trivially fine).
    if (os_.filter_sql or "").strip():
        os_.verified = ov.sql_field_ok("filter_sql")
        os_.verification_note = "human-asserted" if os_.verified else (
            ov.binding.get("filter_sql", {}).get("note", "") or "unbound"
        )
    else:
        os_.verified = True
        os_.verification_note = "human-asserted (all rows)"
    ent.object_sets[local] = os_
    return touched


def _apply_computed_property(ent: OntologyEntity, ov: OntologyOverride) -> list[str]:
    local = ov.local_id
    existing = next((c for c in ent.computed_properties if c.id == local), None)
    cp = existing or ComputedProperty(id=local, label=local, formula_sql="")
    touched: list[str] = []
    for field, value in ov.fields.items():
        if field not in _EDITABLE["computed_property"]:
            continue
        setattr(cp, field, value)
        touched.append(field)
    cp.verified = ov.sql_field_ok("formula_sql")
    cp.verification_note = "human-asserted" if cp.verified else (
        ov.binding.get("formula_sql", {}).get("note", "") or "unbound"
    )
    if existing is None:
        ent.computed_properties.append(cp)
    return touched


def _apply_metric(graph: OntologyGraph, ov: OntologyOverride) -> list[str]:
    m = graph.metrics.get(ov.target_id)
    if m is None:
        # Allow authoring a brand-new metric only if we know its entity (via fields).
        ent_id = ov.fields.get("entity")
        if not ent_id:
            return []
        m = OntologyMetric(
            id=ov.target_id, display_name=ov.target_id, entity=ent_id, formula_sql="",
        )
        graph.metrics[ov.target_id] = m
    touched: list[str] = []
    for field, value in ov.fields.items():
        if field not in _EDITABLE["metric"]:
            continue
        setattr(m, field, value)
        touched.append(field)
    if "formula_sql" in touched:
        m.verified = ov.sql_field_ok("formula_sql")
        m.verification_note = "human-asserted" if m.verified else (
            ov.binding.get("formula_sql", {}).get("note", "") or "unbound"
        )
    return touched


def apply_overrides(graph: Optional[OntologyGraph], conn: str, schema: str) -> tuple[Optional[OntologyGraph], OverlayReport]:
    """Overlay all human overrides for {conn}/{schema} onto ``graph`` in place.

    Pure w.r.t. the DB: it trusts the bind status persisted on each override
    (see ``bind_overrides`` for where SQL is validated). Returns the graph and an
    ``OverlayReport`` so the caller can prove the overlay fired.
    """
    report = OverlayReport()
    if graph is None:
        return graph, report
    for ov in load_overrides(conn, schema):
        try:
            if ov.target_kind == "entity":
                ent = graph.entities.get(ov.target_id)
                touched = _apply_entity(ent, ov) if ent else []
            elif ov.target_kind in ("object_set", "computed_property"):
                ent = graph.entities.get(ov.entity_id or "")
                if not ent:
                    report.skipped.append(f"{ov.target_kind}:{ov.target_id} — entity not in graph")
                    continue
                touched = (_apply_object_set if ov.target_kind == "object_set"
                           else _apply_computed_property)(ent, ov)
            elif ov.target_kind == "metric":
                touched = _apply_metric(graph, ov)
            else:
                touched = []

            if touched:
                report.applied.append(f"{ov.target_kind}:{ov.target_id} ({','.join(touched)})")
            else:
                report.skipped.append(f"{ov.target_kind}:{ov.target_id} — target/fields not applicable")
        except Exception as exc:  # one bad override must not break the overlay
            report.skipped.append(f"{ov.target_kind}:{ov.target_id} — {type(exc).__name__}: {exc}")
    return graph, report


# ── binding: EXPLAIN-validate SQL-bearing overrides against the live DB ──────

def bind_overrides(
    ov: OntologyOverride,
    graph: Optional[OntologyGraph],
    explain: Callable[[str], Optional[str]],
) -> OntologyOverride:
    """Validate each SQL field on ``ov`` by EXPLAIN-ing a probe query.

    ``explain(sql)`` runs a non-executing EXPLAIN/dry-run and returns an error
    string on failure or None on success (the universal binder, per the phase-8
    grounding architecture). The result is written back onto ``ov.binding`` so a
    later ``apply_overrides`` can gate ``verified`` without a DB handle.

    The probe wraps the fragment in the smallest query that exercises it against
    the target entity's table, so a fragment that references a dropped/renamed
    column fails to bind instead of silently poisoning the prompt.
    """
    table = _probe_table(ov, graph)
    for field, value in ov.fields.items():
        if field not in _SQL_FIELDS or not str(value or "").strip():
            continue
        probe = _probe_sql(field, str(value), table)
        err = None
        try:
            err = explain(probe)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
        ov.binding[field] = {"bound": err is None, "note": "" if err is None else err}
    return ov


def _probe_table(ov: OntologyOverride, graph: Optional[OntologyGraph]) -> str:
    """Best-effort source table for the override's entity (for the bind probe)."""
    if graph is None:
        return ""
    eid = ov.entity_id or (ov.target_id if ov.target_kind == "entity" else None)
    if not eid and ov.target_kind == "metric":
        m = graph.metrics.get(ov.target_id)
        # For a brand-new metric (not yet in the graph) fall back to the entity
        # named in the override's fields, so its formula can still EXPLAIN-bind.
        eid = (m.entity if m else None) or ov.fields.get("entity")
    ent = graph.entities.get(eid) if eid else None
    return (ent.source_tables[0] if ent and ent.source_tables else "")


def _probe_sql(field: str, value: str, table: str) -> str:
    """Smallest query that makes the DB validate the fragment without returning rows."""
    frm = f" FROM {table}" if table else ""
    if field in ("active_filter", "filter_sql"):
        return f"SELECT 1{frm} WHERE {value} LIMIT 0"
    # formula_sql is a SELECT-clause expression.
    return f"SELECT {value} AS _probe{frm} LIMIT 0"
