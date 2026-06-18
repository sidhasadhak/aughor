"""nao-style context file tree — see it, edit it, version it.

The override store (overrides.py) is already a YAML tree, but it only holds the
*deltas*. To curate an ontology a human first needs to SEE what the engine
inferred. This module exports the live ontology to a readable YAML tree and
re-imports on-disk edits as overrides — so the editing surface is plain files
under git, and only the fields a human CHANGED become overrides (override-wins).

Round-trip:
    export_tree(root, graph)              # engine ontology -> readable YAML files
    # ...human edits a file on disk, or git-reviews a PR...
    import_tree(root, base_graph)         # changed editable fields -> OntologyOverride[]
    # caller EXPLAIN-binds + save_override()s them; load_latest_ontology applies them.

Diffing against ``base_graph`` (the pre-override, auto-built graph) is what keeps
re-importing an unedited export a no-op: unchanged fields produce no overrides.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from aughor.ontology.models import OntologyGraph
from aughor.ontology.overrides import OntologyOverride, _EDITABLE, _safe

_EXPORT_ROOT = Path(__file__).parent.parent.parent / "data" / "ontology_export"


def export_root(conn: str, schema: str) -> Path:
    return _EXPORT_ROOT / _safe(conn) / _safe(schema)


# ── export: ontology -> readable YAML tree ──────────────────────────────────

def export_tree(root: Path, graph: OntologyGraph) -> list[str]:
    """Write the ontology to ``root`` as per-entity and per-metric YAML. Returns paths.

    Each file separates an ``editable:`` block (the fields a human may change —
    the same whitelist the override store accepts) from read-only context
    (columns, verified flags) so it's obvious what an edit will affect.
    """
    root = Path(root)
    written: list[str] = []

    for e in graph.entities.values():
        doc = {
            "_kind": "entity",
            "id": e.id,
            "editable": {f: getattr(e, f, None) for f in sorted(_EDITABLE["entity"])},
            "object_sets": {
                oid: {"display_name": os_.display_name, "description": os_.description,
                      "filter_sql": os_.filter_sql, "is_default": os_.is_default,
                      "_verified": os_.verified}
                for oid, os_ in e.object_sets.items()
            },
            "computed_properties": [
                {"id": c.id, "label": c.label, "formula_sql": c.formula_sql,
                 "unit": c.unit, "_verified": c.verified}
                for c in e.computed_properties
            ],
            "_readonly_columns": {
                p.name: {"type": p.data_type, "semantic_type": p.semantic_type,
                         "unit": p.unit, "grain": p.measure_grain}
                for p in e.properties.values()
            },
        }
        written.append(_write(root / "entities" / f"{_safe(e.id)}.yaml", doc))

    for m in graph.metrics.values():
        doc = {
            "_kind": "metric", "id": m.id, "entity": m.entity,
            "editable": {f: getattr(m, f, None) for f in sorted(_EDITABLE["metric"])},
            "_verified": m.verified,
        }
        written.append(_write(root / "metrics" / f"{_safe(m.id)}.yaml", doc))

    return written


def _write(path: Path, doc: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return str(path)


# ── import: edited tree -> overrides (changed fields only) ──────────────────

def import_tree(root: Path, base_graph: OntologyGraph) -> list[OntologyOverride]:
    """Diff the edited tree against ``base_graph`` and return one override per change.

    Only whitelisted editable fields are considered; ``_readonly_*`` and
    ``_verified`` markers are ignored. A metric file with an id absent from the
    base graph is treated as a newly-authored metric.
    """
    root = Path(root)
    out: list[OntologyOverride] = []

    ent_dir = root / "entities"
    if ent_dir.exists():
        for f in sorted(ent_dir.glob("*.yaml")):
            doc = _read(f)
            if not doc:
                continue
            eid = doc.get("id")
            base = base_graph.entities.get(eid)
            if base is None:
                continue  # can't author a brand-new entity from disk in v1
            out.extend(_entity_overrides(eid, doc, base))

    met_dir = root / "metrics"
    if met_dir.exists():
        for f in sorted(met_dir.glob("*.yaml")):
            doc = _read(f)
            if not doc:
                continue
            out.extend(_metric_overrides(doc, base_graph))

    return out


def _read(path: Path) -> Optional[dict]:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return None


def _entity_overrides(eid: str, doc: dict, base) -> list[OntologyOverride]:
    out: list[OntologyOverride] = []
    # entity scalar/list fields
    changed = {k: v for k, v in (doc.get("editable") or {}).items()
               if k in _EDITABLE["entity"] and v != getattr(base, k, None)}
    if changed:
        out.append(OntologyOverride(target_kind="entity", target_id=eid, fields=changed))

    # object sets
    base_os = base.object_sets
    for oid, od in (doc.get("object_sets") or {}).items():
        bo = base_os.get(oid)
        f = {k: od[k] for k in _EDITABLE["object_set"]
             if k in od and (bo is None or od.get(k) != getattr(bo, k, None))}
        if f:
            out.append(OntologyOverride(target_kind="object_set", target_id=f"{eid}::{oid}", fields=f))

    # computed properties
    base_cps = {c.id: c for c in base.computed_properties}
    for cp in (doc.get("computed_properties") or []):
        cid = cp.get("id")
        if not cid:
            continue
        bc = base_cps.get(cid)
        f = {k: cp[k] for k in _EDITABLE["computed_property"]
             if k in cp and (bc is None or cp.get(k) != getattr(bc, k, None))}
        if f:
            out.append(OntologyOverride(target_kind="computed_property",
                                        target_id=f"{eid}::{cid}", fields=f))
    return out


def _metric_overrides(doc: dict, base_graph: OntologyGraph) -> list[OntologyOverride]:
    mid = doc.get("id")
    if not mid:
        return []
    ed = {k: v for k, v in (doc.get("editable") or {}).items() if k in _EDITABLE["metric"]}
    base = base_graph.metrics.get(mid)
    if base is None:
        # newly authored metric — needs its entity to bind/render
        fields = dict(ed)
        fields.setdefault("entity", doc.get("entity"))
        if not fields.get("formula_sql"):
            return []
        return [OntologyOverride(target_kind="metric", target_id=mid, fields=fields)]
    changed = {k: v for k, v in ed.items() if v != getattr(base, k, None)}
    return [OntologyOverride(target_kind="metric", target_id=mid, fields=changed)] if changed else []
