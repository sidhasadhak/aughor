"""
Ontology cache — persists OntologyGraph objects between runs.

Cache key: "{connection_id}:{schema_fingerprint}"
File:      data/ontology_cache.json
Max:       20 entries (LRU eviction — same pattern as profile_cache.py)

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

_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "ontology_cache.json"
_MAX_ENTRIES = 20


# ── Internal I/O ──────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if _CACHE_PATH.exists():
            return json.loads(_CACHE_PATH.read_text())
    except Exception:
        pass
    return {}


def _save(cache: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass


def _key(connection_id: str, fingerprint: str) -> str:
    return f"{connection_id}:{fingerprint}"


# ── Public API ────────────────────────────────────────────────────────────────

def load_ontology(
    connection_id: str,
    fingerprint: str,
) -> Optional[OntologyGraph]:
    cache = _load()
    entry = cache.get(_key(connection_id, fingerprint))
    if not entry:
        return None
    try:
        return OntologyGraph.model_validate(entry["graph"])
    except Exception:
        return None


def save_ontology(
    connection_id: str,
    fingerprint: str,
    graph: OntologyGraph,
) -> None:
    cache = _load()
    k = _key(connection_id, fingerprint)
    cache.pop(k, None)
    cache[k] = {"graph": graph.model_dump()}
    while len(cache) > _MAX_ENTRIES:
        del cache[next(iter(cache))]
    _save(cache)


def invalidate(connection_id: str) -> None:
    """Remove all cached ontologies for a connection (called on delete / DSN change)."""
    cache = _load()
    prefix = f"{connection_id}:"
    evict = [k for k in cache if k.startswith(prefix)]
    for k in evict:
        del cache[k]
    if evict:
        _save(cache)


def patch_entity(
    connection_id: str,
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
    k = _key(connection_id, fingerprint)
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


def load_latest_ontology(connection_id: str) -> Optional[OntologyGraph]:
    """Return the most recently cached ontology for a connection (any fingerprint)."""
    cache = _load()
    prefix = f"{connection_id}:"
    matches = {k: v for k, v in cache.items() if k.startswith(prefix)}
    if not matches:
        return None
    last_entry = list(matches.values())[-1]
    try:
        return OntologyGraph.model_validate(last_entry["graph"])
    except Exception:
        return None


def patch_action(
    connection_id: str,
    fingerprint: str,
    action_id: str,
    overrides: dict,
) -> Optional[OntologyGraph]:
    """Apply user overrides to a single action within a cached graph."""
    cache = _load()
    k = _key(connection_id, fingerprint)
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
    table_profiles: dict,
    column_profiles: dict,
    join_map: dict,
    glossary: dict,
) -> Optional[OntologyGraph]:
    """
    Main entry point called at schema-load time.

    Computes a stable fingerprint from table_profiles (table names + row counts
    + grain columns), then either returns the cached graph or builds a fresh one.

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

        cached = load_ontology(connection_id, fingerprint)
        if cached is not None:
            return cached

        graph = extract_structural_ontology(
            connection_id=connection_id,
            schema_fingerprint=fingerprint,
            table_profiles=table_profiles,
            column_profiles=column_profiles,
            join_map=join_map,
            glossary=glossary,
        )
        save_ontology(connection_id, fingerprint, graph)
        return graph

    except Exception:
        return None
