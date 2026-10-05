"""Persistence for the connection knowledge graph — Wave C1; generated state since the 2027
study's close-out (C3).

The graph is a **projection of the ledger, rebuilt on demand** (the study §F: "a way of reading
claims, not a place they live"), one file per ``(org, connection, schema)`` under the state
directory's ``context_graph/``. Until the close-out it was a committed, git-reviewed artifact
under ``data/context_graph/`` — the precedent `data/ontology_overrides/` set; that stopped the day
its facts came from the Record, which is the authority and keeps its own history. The file is a
cache of the projection: :func:`graphs_for_connection` rebuilds it when it is missing, ``version``
still rises on every rebuild (so a reader can tell two builds apart), and nothing of it is tracked.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from aughor.db.paths import state_dir
from aughor.ontology.context_graph import ContextGraph

# Per-connection GENERATED state (a deterministic projection of the ontology and the Record), so
# it lives under the AUGHOR_STATE_DIR family — isolated in tests by construction (the family
# exists because a hard-coded Path("data") store destroyed real findings twice; see
# aughor/db/paths.py). In production the env is unset ⇒ data/context_graph, gitignored since the
# close-out; a migrated home carries it like any other generated state.
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


def graphs_for_connection(org_id: str, connection_id: str, *, schema_name: Optional[str] = None,
                          build: bool = True) -> list[ContextGraph]:
    """The connection's graphs, REBUILT ON DEMAND: what is on disk when something is, else — when
    ``build`` — one projection built now from the ontology and the Record and kept for the next
    reader. A connection with no built ontology yet has no graph, and the empty list says so.
    Readers that answer questions (read-back, the MCP knowledge tools, lineage, the answer trace)
    go through here, so a missing or deleted file is never a missing fact."""
    built = load_graphs_for_connection(org_id, connection_id)
    if built or not build:
        return built
    try:
        from aughor.ontology.context_graph_build import build_context_graph
        cg = build_context_graph(connection_id, schema_name, org_id=org_id, persist=True)
    except Exception as exc:  # noqa: BLE001 — a rebuild that fails is an empty graph, said by the caller
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the context graph could not be rebuilt on demand", counter="context_graph.rebuild",
                 conn_id=connection_id)
        return []
    return [cg] if cg is not None else []


def save_graph(graph: ContextGraph) -> Path:
    """Write the graph to its committed path, bumping ``version`` past any prior
    build (supersede-not-delete). Returns the path written. Raises on a genuine I/O
    error — the build orchestration tolerates it, so a live rebuild never breaks an
    answer, but a test/proof sees the failure."""
    path = graph_path(graph.org_id, graph.connection_id, graph.schema_name)
    prior = load_graph(graph.org_id, graph.connection_id, graph.schema_name)
    if prior is not None:
        graph.version = int(prior.version) + 1
    # CB-1 — the history rides across the rebuild: what each node said before, when it was
    # first seen, and the nodes that went. Before this a rebuild overwrote all of it.
    from aughor.ontology.context_graph import carry_history
    carry_history(graph, prior, now=graph.generated_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Pretty-printed and key-sorted so a rebuild produces a MINIMAL git diff — only
    # the nodes/edges that actually changed move.
    path.write_text(
        json.dumps(graph.model_dump(), indent=2, sort_keys=True, default=str)
    )
    return path
