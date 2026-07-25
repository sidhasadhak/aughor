"""Persistence for the connection knowledge graph — Wave C1.

The graph is a **committed, human-editable artifact**, one file per
``(org, connection, schema)`` under ``data/context_graph/`` — following the
``data/ontology_overrides/`` precedent (git-reviewable, not gitignored: the
``data/*.json`` ignore is non-recursive, so a nested file is trackable). Nothing
per-connection was committed before Wave C; this is the net-new artifact the whole
wave reads back. ``version`` is bumped on every rebuild (supersede-not-delete,
mirroring the Ledger ``finding`` artifact); git holds the actual history.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from aughor.db.paths import state_dir
from aughor.ontology.context_graph import ContextGraph

# Per-connection GENERATED state (a deterministic projection of the ontology), so it
# lives under the AUGHOR_STATE_DIR family — isolated in tests by construction (the
# family exists because a hard-coded Path("data") store destroyed real findings
# twice; see aughor/db/paths.py). In production the env is unset ⇒ data/context_graph,
# where the nested json is git-trackable — the committed, reviewable artifact.
_ROOT = state_dir() / "context_graph"


def _slug(part: str) -> str:
    """Filesystem-safe path component (org/connection ids are already short slugs;
    schema names can be empty or dotted)."""
    p = (part or "_default").strip().replace("/", "_").replace("\\", "_")
    return p or "_default"


def graph_path(org_id: str, connection_id: str, schema_name: str = "") -> Path:
    """The committed artifact path for a graph. Kept flat and predictable so it reads
    cleanly in a diff: ``data/context_graph/{org}/{conn}/{schema}.json``."""
    return _ROOT / _slug(org_id) / _slug(connection_id) / f"{_slug(schema_name)}.json"


def load_graph(
    org_id: str, connection_id: str, schema_name: str = ""
) -> Optional[ContextGraph]:
    """Load the committed graph, or ``None`` if it has never been built. Returns
    ``None`` (never raises) on a missing/corrupt file — a caller falls back to a
    rebuild."""
    path = graph_path(org_id, connection_id, schema_name)
    if not path.exists():
        return None
    try:
        return ContextGraph.model_validate_json(path.read_text())
    except Exception:
        return None


def load_graphs_for_connection(org_id: str, connection_id: str) -> list[ContextGraph]:
    """Every per-schema graph committed for a connection (read-back does not always
    know the schema). Returns [] when none is built. Corrupt files are skipped, never
    raised."""
    conn_dir = _ROOT / _slug(org_id) / _slug(connection_id)
    if not conn_dir.exists():
        return []
    out: list[ContextGraph] = []
    for f in sorted(conn_dir.glob("*.json")):
        try:
            out.append(ContextGraph.model_validate_json(f.read_text()))
        except Exception:
            continue
    return out


def save_graph(graph: ContextGraph) -> Path:
    """Write the graph to its committed path, bumping ``version`` past any prior
    build (supersede-not-delete). Returns the path written. Raises on a genuine I/O
    error — the build orchestration tolerates it, so a live rebuild never breaks an
    answer, but a test/proof sees the failure."""
    path = graph_path(graph.org_id, graph.connection_id, graph.schema_name)
    prior = load_graph(graph.org_id, graph.connection_id, graph.schema_name)
    if prior is not None:
        graph.version = int(prior.version) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    # Pretty-printed and key-sorted so a rebuild produces a MINIMAL git diff — only
    # the nodes/edges that actually changed move.
    path.write_text(
        json.dumps(graph.model_dump(), indent=2, sort_keys=True, default=str)
    )
    return path
