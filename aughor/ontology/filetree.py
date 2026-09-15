"""nao-style context file tree — see it, edit it, version it.

The override store (overrides.py) is already a YAML tree, but it only holds the
*deltas*. To curate an ontology a human first needs to SEE what the engine
inferred. This module exports the live ontology to a readable YAML tree and
re-imports on-disk edits as overrides — so the editing surface is plain files
under git, and only the fields a human CHANGED become overrides (override-wins).

Round-trip:
    export_tree(root, graph, declarations)  # engine ontology -> readable YAML files
    # ...human edits a file on disk, or git-reviews a PR...
    import_tree(root, base_graph)           # changed editable fields -> OntologyOverride[]
    read_declarations(root)                 # declared types, links, processes, rules -> their doors' specs
    # caller EXPLAIN-binds + save_override()s the edits, and declares each declaration through its own door
    # (counted, refused with the reason); load_latest_ontology applies them.

Diffing against ``base_graph`` (the pre-override, auto-built graph) is what keeps
re-importing an unedited export a no-op: unchanged fields produce no overrides.
A DECLARATION is not a diff — the built graph never held it — so it is written
whole, as the spec its door takes, under ``declared/``, and imported by declaring
it again: an unchanged one is left as it is.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from aughor.db.sqlite_util import resolve_db_path
from aughor.ontology.models import OntologyGraph
from aughor.ontology.overrides import OntologyOverride, _EDITABLE, _safe

#: `data/ontology_export`, or `AUGHOR_ONTOLOGY_EXPORT_DIR` — the overrides tree's sibling, isolated with it.
_EXPORT_ROOT = resolve_db_path("AUGHOR_ONTOLOGY_EXPORT_DIR",
                               Path(__file__).parent.parent.parent / "data" / "ontology_export")


def export_root(conn: str, schema: str) -> Path:
    return _EXPORT_ROOT / _safe(conn) / _safe(schema)


# ── export: ontology -> readable YAML tree ──────────────────────────────────

#: The part of a backing a human edits — never its measured verdict. ON-8 — `connection_id` is where its rows live, so
#: a tree never moves a type's rows to the graph's own connection.
_BACKING_EDITABLE = ("kind", "table", "sql", "primary_key", "connection_id")

#: The kinds a person DECLARES whole — ON-7's types and links, ON-9's processes and rules — in the order they can be
#: declared again: a link names its two types, and a process or a rule names its type.
DECLARED_KINDS = ("entity", "link", "process", "rule")
#: An entity's declaration: the fields its door reads. Anything else on its override is an edit made after it.
_ENTITY_DECLARATION = ("display_name", "backing", "description", "domain", "entity_type", "origin", "provenance")


def _editable_value(obj, field: str):
    """The on-disk form of an editable field. ON-1's `backing` is a model, so it is written
    as its editable spec (kind/table/sql/primary_key/connection_id) and compared the same way on
    import — an unedited file must round-trip as a no-op, and the measured verdict is not an edit."""
    value = getattr(obj, field, None)
    if field == "backing" and value is not None:
        return {k: getattr(value, k) for k in _BACKING_EDITABLE}
    if field == "display_property" and value is not None:
        return value.name          # ON-3b: the property's NAME is the edit; its measurement is not
    if field == "bindings":
        from aughor.ontology.bindings import binding_spec
        return {b.name: binding_spec(b) for b in value or []}   # ON-1b: each binding's spec is the edit; its count is not
    return value


def declaration_spec(ov: OntologyOverride) -> dict:
    """The spec a declaration's door takes, from the override that door wrote — declaring it again stores the same
    fields, because every door's ``*_fields`` is idempotent. An entity's later edits (a binding, a display property,
    a part mark) are not its declaration; `declaration_edits` names them."""
    fields = ov.fields
    if ov.target_kind == "entity":
        spec = {k: fields[k] for k in _ENTITY_DECLARATION if k in fields}
        spec["backing"] = {k: v for k, v in dict(spec.get("backing") or {}).items() if k != "kind"}  # the door derives it
    else:
        spec = {k: v for k, v in fields.items() if k != "declared"}
    return {"id": ov.target_id, **spec}


def declaration_edits(ov: OntologyOverride) -> list[str]:
    """The fields on a declared entity's override that its declaration does not hold — edits made after it, which a
    declaration from a file does not carry: each is made again through its own door."""
    if ov.target_kind != "entity":
        return []
    return sorted(k for k in ov.fields if k not in (*_ENTITY_DECLARATION, "declared"))


def export_tree(root: Path, graph: OntologyGraph,
                declarations: Optional[list[OntologyOverride]] = None) -> list[str]:
    """Write the ontology to ``root`` as per-entity and per-metric YAML. Returns paths.

    Each file separates an ``editable:`` block (the fields a human may change —
    the same whitelist the override store accepts) from read-only context
    (columns, verified flags) so it's obvious what an edit will affect.

    ``declarations`` are the scope's overrides: each one a person DECLARED whole is written under ``declared/`` as the
    spec its door takes — and a declared type there only, one file per thing. ``declared/`` mirrors the declarations
    exactly, so a declaration withdrawn since the last export leaves no file behind to be declared again.
    """
    root = Path(root)
    written: list[str] = []
    declared = [ov for ov in declarations or [] if ov.target_kind in DECLARED_KINDS and ov.fields.get("declared")]
    declared_types = {ov.target_id for ov in declared if ov.target_kind == "entity"}

    for e in graph.entities.values():
        if e.id in declared_types:
            continue
        doc = {
            "_kind": "entity",
            "id": e.id,
            "editable": {f: _editable_value(e, f) for f in sorted(_EDITABLE["entity"])},
            "segments": {
                sid: {"display_name": seg.display_name, "description": seg.description,
                      "filter_sql": seg.filter_sql, "is_default": seg.is_default,
                      "_verified": seg.verified}
                for sid, seg in e.segments.items()
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

    for stale in sorted((root / "declared").glob("*/*.yaml")):
        stale.unlink()
    for ov in declared:
        doc = {"_kind": f"declared_{ov.target_kind}", "id": ov.target_id, "spec": declaration_spec(ov)}
        edits = declaration_edits(ov)
        if edits:
            doc["_edits_not_carried"] = edits
        written.append(_write(root / "declared" / f"{ov.target_kind}s" / f"{_safe(ov.target_id)}.yaml", doc))

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
    base graph is treated as a newly-authored metric. A declared type is not in
    the base graph and is not diffed here: `read_declarations` reads it.
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
                continue  # a type the built graph never held is a declaration: `read_declarations`
            out.extend(_entity_overrides(eid, doc, base))

    met_dir = root / "metrics"
    if met_dir.exists():
        for f in sorted(met_dir.glob("*.yaml")):
            doc = _read(f)
            if not doc:
                continue
            out.extend(_metric_overrides(doc, base_graph))

    return out


def read_declarations(root: Path) -> tuple[list[tuple[str, str, dict, list[str]]], list[str]]:
    """``(declarations, unreadable)``: each declaration file under ``declared/`` as ``(kind, id, spec, edits not
    carried)``, in the order they can be declared again — types, then links, processes and rules — and the relative
    path of every file there that is not one, so a broken file is reported rather than silently read as nothing."""
    root = Path(root)
    declarations: list[tuple[str, str, dict, list[str]]] = []
    unreadable: list[str] = []
    for kind in DECLARED_KINDS:
        for f in sorted((root / "declared" / f"{kind}s").glob("*.yaml")):
            doc = _read(f)
            spec = (doc or {}).get("spec")
            if not isinstance(spec, dict) or doc.get("_kind") != f"declared_{kind}" or not doc.get("id"):
                unreadable.append(str(f.relative_to(root)))
                continue
            edits = doc.get("_edits_not_carried")
            declarations.append((kind, str(doc["id"]), spec, [str(e) for e in edits] if isinstance(edits, list) else []))
    return declarations, unreadable


def _read(path: Path) -> Optional[dict]:
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def _entity_overrides(eid: str, doc: dict, base) -> list[OntologyOverride]:
    out: list[OntologyOverride] = []
    # entity scalar/list fields
    changed = {k: v for k, v in (doc.get("editable") or {}).items()
               if k in _EDITABLE["entity"] and v != _editable_value(base, k)}
    if changed:
        out.append(OntologyOverride(target_kind="entity", target_id=eid, fields=changed))

    # segments — `object_sets` is still read so a tree exported before the rename (or an
    # edit branched off one) still imports instead of silently producing no overrides.
    base_segs = base.segments
    for sid, sd in (doc.get("segments") or doc.get("object_sets") or {}).items():
        bs = base_segs.get(sid)
        f = {k: sd[k] for k in _EDITABLE["object_set"]
             if k in sd and (bs is None or sd.get(k) != getattr(bs, k, None))}
        if f:
            # target_kind "object_set" is the frozen store value (see overrides.TargetKind)
            out.append(OntologyOverride(target_kind="object_set", target_id=f"{eid}::{sid}", fields=f))

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
