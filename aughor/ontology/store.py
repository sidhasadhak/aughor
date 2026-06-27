"""
Ontology cache — persists OntologyGraph objects between runs.

Cache key: "{connection_id}:{schema_name}:{schema_fingerprint}"
File:      data/ontology_cache.json
Max:       20 entries (LRU eviction — same pattern as profile_cache.py)

Ontologies are scoped per DB schema so a single connection that exposes
multiple schemas (e.g. analytics + raw) gets independent ontology graphs.

Human overrides (PUT /ontology/entities/{id}) are written directly into the cached
entry so they survive restarts without requiring a re-build.  Override fields are
marked in a separate "overrides" dict within each cache entry so the builder can
tell which fields were user-provided vs auto-extracted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from aughor.ontology.models import OntologyGraph
from aughor.util.json_store import KeyedJsonStore

_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "ontology_cache.json"
_MAX_ENTRIES = 20
_store = KeyedJsonStore(_CACHE_PATH, max_entries=_MAX_ENTRIES)


# ── Internal I/O (kept as thin delegators — override-writes read+mutate+save) ──

def _load() -> dict:
    return _store.load()


def _save(cache: dict) -> None:
    _store.save(cache)


def _key(connection_id: str, schema_name: str, fingerprint: str) -> str:
    """Stable cache key scoped to a specific DB schema within a connection."""
    return f"{connection_id}:{schema_name}:{fingerprint}"


def _schema_prefix(connection_id: str, schema_name: str) -> str:
    return f"{connection_id}:{schema_name}:"


def _conn_prefix(connection_id: str) -> str:
    return f"{connection_id}:"


# ── Public API ────────────────────────────────────────────────────────────────

def load_ontology(
    connection_id: str,
    schema_name: str,
    fingerprint: str,
) -> Optional[OntologyGraph]:
    cache = _load()
    entry = cache.get(_key(connection_id, schema_name, fingerprint))
    if not entry:
        return None
    try:
        return OntologyGraph.model_validate(entry["graph"])
    except Exception:
        return None


def save_ontology(
    connection_id: str,
    schema_name: str,
    fingerprint: str,
    graph: OntologyGraph,
) -> None:
    _store.put(_key(connection_id, schema_name, fingerprint), {"graph": graph.model_dump()})


def invalidate(connection_id: str, schema_name: Optional[str] = None) -> None:
    """Remove cached ontologies for a connection.

    If schema_name is given, only that schema's entries are removed.
    If omitted, all schemas for the connection are evicted (e.g. on DSN change).
    """
    prefix = _schema_prefix(connection_id, schema_name) if schema_name else _conn_prefix(connection_id)
    _store.invalidate_prefix(prefix)


def list_schemas(connection_id: str) -> list[str]:
    """Return the distinct schema names that have a cached ontology for this connection."""
    cache = _load()
    prefix = _conn_prefix(connection_id)
    schemas = set()
    for k in cache:
        if k.startswith(prefix):
            # key format: {conn_id}:{schema_name}:{fingerprint}
            rest = k[len(prefix):]
            parts = rest.split(":", 1)
            if len(parts) == 2:
                schemas.add(parts[0])
    return sorted(schemas)


def patch_entity(
    connection_id: str,
    schema_name: str,
    fingerprint: str,
    entity_id: str,
    overrides: dict,
) -> Optional[OntologyGraph]:
    """
    Apply user overrides to a single entity within a cached graph.
    Returns the updated graph, or None if the cache entry doesn't exist.

    Only the fields explicitly listed in `overrides` are changed — all
    other fields from the auto-extracted graph are preserved.
    """
    cache = _load()
    k = _key(connection_id, schema_name, fingerprint)
    entry = cache.get(k)
    if not entry:
        return None

    try:
        graph = OntologyGraph.model_validate(entry["graph"])
    except Exception:
        return None

    if entity_id not in graph.entities:
        return None

    # Apply overrides field-by-field (whitelist of editable fields)
    _EDITABLE = {
        "description", "active_filter", "default_filters",
        "exclude_when", "lifecycle_states", "terminal_states",
    }
    entity_dict = graph.entities[entity_id].model_dump()
    for field, value in overrides.items():
        if field in _EDITABLE:
            entity_dict[field] = value

    from aughor.ontology.models import OntologyEntity
    graph.entities[entity_id] = OntologyEntity.model_validate(entity_dict)

    cache[k] = {"graph": graph.model_dump()}
    _save(cache)
    return graph


def apply_entity_merge(
    connection_id: str,
    schema_name: str,
    fingerprint: str,
    merge_ids: list[str],
    canonical_id: str,
) -> Optional[OntologyGraph]:
    """Merge ``merge_ids`` into ``canonical_id`` within a cached graph and persist. Returns the merged
    graph, or None if the cache entry is missing or the merge is invalid (unknown entity)."""
    cache = _load()
    k = _key(connection_id, schema_name, fingerprint)
    entry = cache.get(k)
    if not entry:
        return None
    try:
        graph = OntologyGraph.model_validate(entry["graph"])
    except Exception:
        return None

    from aughor.ontology.dedup import merge_entities
    try:
        merged = merge_entities(graph, merge_ids, canonical_id)
    except ValueError:
        return None

    cache[k] = {"graph": merged.model_dump()}
    _save(cache)
    return merged


def load_latest_ontology(
    connection_id: str,
    schema_name: Optional[str] = None,
) -> Optional[OntologyGraph]:
    """Return the most recently cached ontology for a connection+schema combination.

    If schema_name is None, falls back to searching all schemas for the connection
    (useful for legacy callers that don't know the schema name yet).
    """
    cache = _load()
    prefix = _schema_prefix(connection_id, schema_name) if schema_name else _conn_prefix(connection_id)
    matches = {k: v for k, v in cache.items() if k.startswith(prefix)}
    if not matches:
        return None
    last_entry = list(matches.values())[-1]
    try:
        graph = OntologyGraph.model_validate(last_entry["graph"])
    except Exception:
        return None
    # THE shared authority point: chat (investigations._stream_chat), the metrics
    # catalog (semantic.metrics.build_metrics_block) and the eval harness all read
    # the semantic layer through load_latest_ontology. Overlaying human overrides
    # here makes override-wins reach every semantic-layer consumer at once.
    return overlay_human_overrides(graph, connection_id, graph.schema_name)


def patch_action(
    connection_id: str,
    schema_name: str,
    fingerprint: str,
    action_id: str,
    overrides: dict,
) -> Optional[OntologyGraph]:
    """Apply user overrides to a single action within a cached graph."""
    cache = _load()
    k = _key(connection_id, schema_name, fingerprint)
    entry = cache.get(k)
    if not entry:
        return None

    try:
        graph = OntologyGraph.model_validate(entry["graph"])
    except Exception:
        return None

    if action_id not in graph.actions:
        return None

    _EDITABLE = {"description", "sql_template", "business_rules_enforced", "returns"}
    action_dict = graph.actions[action_id].model_dump()
    for field, value in overrides.items():
        if field in _EDITABLE:
            action_dict[field] = value

    from aughor.ontology.models import OntologyAction
    graph.actions[action_id] = OntologyAction.model_validate(action_dict)

    cache[k] = {"graph": graph.model_dump()}
    _save(cache)
    return graph


def get_or_build_ontology(
    connection_id: str,
    schema_name: str,
    table_profiles: dict,
    column_profiles: dict,
    join_map: dict,
    glossary: dict,
) -> Optional[OntologyGraph]:
    """
    Main entry point called at schema-load time.

    Computes a stable fingerprint from table_profiles (table names + row counts
    + grain columns), then either returns the cached graph or builds a fresh one.
    The graph is scoped to the given schema_name so multiple schemas on the same
    connection each get an independent ontology.

    Returns None (not raises) on any failure so schema loading is never blocked.
    """
    from aughor.ontology.builder import extract_structural_ontology

    try:
        # Fingerprint: sorted "{table}:{row_count}:{grain_col}" — invalidates on
        # schema changes (new table, grain column renamed) but not on data changes.
        parts = sorted(
            f"{t}:{tp.row_count}:{tp.grain_column or ''}"
            for t, tp in table_profiles.items()
        )
        import hashlib
        fingerprint = hashlib.md5("|".join(parts).encode()).hexdigest()[:16]

        cached = load_ontology(connection_id, schema_name, fingerprint)
        if cached is not None:
            return _overlay_learned_actions(cached, connection_id, schema_name)

        graph = extract_structural_ontology(
            connection_id=connection_id,
            schema_name=schema_name,
            schema_fingerprint=fingerprint,
            table_profiles=table_profiles,
            column_profiles=column_profiles,
            join_map=join_map,
            glossary=glossary,
        )
        # Stamp measure-grain (additivity: per_unit vs per_line) onto properties FROM THE
        # DATA, so consumers read a persisted grain instead of re-probing each run (#3).
        try:
            from aughor.semantic.measure_grain import probe_measure_grains
            from aughor.db.connection import open_connection_for
            _tc = {ent.source_tables[0]: [p.name for p in ent.properties.values()]
                   for ent in graph.entities.values() if getattr(ent, "source_tables", None)}
            if _tc:
                _db = open_connection_for(connection_id)
                try:
                    _grains, _ = probe_measure_grains(_db, _tc)
                finally:
                    _db.close()
                for ent in graph.entities.values():
                    for p in ent.properties.values():
                        g = _grains.get(p.name.lower())
                        if g:
                            p.measure_grain = g
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "measure-grain stamping is best-effort; the runtime probe still covers it",
                     counter="ontology.grain_stamp_failed")
        # joinable_with — value-verify each relationship's join edge and persist the verdict as a
        # first-class ontology fact (cross-process, reviewable, override-able), not just the
        # in-process catalog cache: stamp the real FKs' overlap and DROP value-disjoint name
        # coincidences so the saved graph never carries a fabricating edge. Build-time + cached.
        try:
            from aughor.sql.join_guard import verify_join_edges
            from aughor.ontology.builder import apply_join_verifications
            from aughor.db.connection import open_connection_for
            edges = [{"t1": r.from_table, "c1": r.from_col, "t2": r.to_table, "c2": r.to_col,
                      "match": r.join_confidence} for r in graph.relationships.values()]
            if edges:
                _vdb = open_connection_for(connection_id)
                try:
                    _verified, _rejected = verify_join_edges(_vdb, edges)
                finally:
                    _vdb.close()
                apply_join_verifications(graph, _verified, _rejected)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "ontology join value-verification is best-effort; catalog probe still covers it",
                     counter="ontology.join_verify_failed")
        # Persist ONLY the structural graph to the fingerprint cache — learned
        # skills must never be baked in (they'd be wiped on rebuild and would
        # pollute the structural fingerprint).  Overlay happens after save.
        save_ontology(connection_id, schema_name, fingerprint, graph)
        return _overlay_learned_actions(graph, connection_id, schema_name)

    except Exception:
        return None


def _overlay_learned_actions(graph, connection_id: str, schema_name: str):
    """Merge learned skills (procedural memory) into the returned graph.

    This is the SINGLE seam where crystallized skills re-enter the live ontology
    for BOTH consumers: the agent's planner (conn.get_ontology() →
    build_actions_prompt_section) and the HTTP ontology views.  Learned actions
    live in their own {conn}:{schema}-keyed store so they survive rebuilds;
    structural actions win on id collision (never silently shadowed).
    """
    if graph is None:
        return graph
    try:
        from aughor.memory.skills import load_learned_actions
        for aid, action in load_learned_actions(connection_id, schema_name).items():
            graph.actions.setdefault(aid, action)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "learned-action overlay is additive procedural memory; the structural graph is usable without it",
                 counter="ontology.store.overlay_learned", conn_id=connection_id or None)
    return graph


def overlay_human_overrides(graph, connection_id: str, schema_name: str):
    """Apply human ontology overrides onto ``graph`` and persist nothing.

    Distinct from ``_overlay_learned_actions`` (the get_or_build seam) on purpose:
    human edits must be applied LAST — after M12b enrichment and M24c validation —
    so a human-asserted ``verified`` flag wins over the validator's verdict. So
    the call site is the end of ``build_intelligence`` (post-validate), not inside
    get_or_build. Idempotent, so a second apply on a read path is harmless.

    Emits a fired/skipped counter and an info log: a human override that silently
    didn't apply must be visible, never a bare ``except: pass``.
    """
    if graph is None:
        return graph
    try:
        from aughor.ontology.overrides import apply_overrides
        _, report = apply_overrides(graph, connection_id, schema_name)
        if report.applied or report.skipped:
            from aughor.stats import stats as _st
            _st.inc("ontology.human_overrides_applied", len(report.applied))
            _st.inc("ontology.human_overrides_skipped", len(report.skipped))
            import logging
            logging.getLogger(__name__).info(
                "human ontology overrides [%s:%s] applied=%s skipped=%s",
                connection_id, schema_name, report.applied, report.skipped)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "human overrides are additive; ontology is usable without them",
                 counter="ontology.human_overrides", conn_id=connection_id or None)
    return graph
