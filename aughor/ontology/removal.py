"""A removed connection — or one removed dataset of it — takes its ontology and its documentation with it.

The user, 2026-10-11: "Removing a connection means also removing its ontology, its metrics and related documents..
make that default". Measured that day on the live install: the connection purge cleared the ontology CACHE and two
of the trees, and nothing else. The people's accepted overrides of five removed connections were still in the
checkout's `data/ontology_overrides/` — which the state-directory sweep never reads — and a removed dataset kept
every tree: its ~250 table and column documents, its recommendations (the datasets a person turned off, its layer),
its column config, its context graph, and its indexed "Schema documentation", searchable still.

Every tree here is laid out ``{root}/{connection}/{dataset}…``, and each root is the STORE'S OWN — read from the
module that writes it, so this follows a store wherever an install keeps it, and never reaches a tree it does not
own: the shipped seed layer (`data/shipped/`) is no store's instance root and is never touched. Idempotent: a tree
already gone is nothing to do.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

from aughor.kernel.errors import tolerate


def _trees() -> list[Path]:
    """Every per-connection ontology tree's root, as its own module resolves it."""
    from aughor.ontology import column_config, doctree, drafts, overrides, recommendations

    return [overrides._ROOT, overrides._DRAFT_ROOT, drafts._ROOT, recommendations._ROOT,
            doctree._root(), column_config._root()]


def _context_graph_root() -> Path:
    from aughor.ontology import context_graph_store
    return context_graph_store._ROOT


def _names(conn_id: str) -> set[str]:
    return {conn_id, re.sub(r"[^A-Za-z0-9._-]", "_", conn_id)}


def _remove(path: Path) -> int:
    if path.is_dir():
        shutil.rmtree(path)
        return 1
    if path.exists():
        path.unlink()
        return 1
    return 0


def _targets(base: Path, dataset: Optional[str]) -> list[Path]:
    """The connection's folder, or one dataset's folder and its single-file forms."""
    if dataset is None:
        return [base]
    return [base / dataset, *(base / f"{dataset}{ext}" for ext in (".yaml", ".yml", ".json"))]


def purge(conn_id: str, dataset: Optional[str] = None) -> dict[str, int]:
    """Remove ``conn_id``'s ontology and documentation — all of it, or one ``dataset``'s. Returns
    ``{"ontology_trees", "context_graph", "schema_docs"}``: folders removed, context graphs removed, indexed
    documentation unregistered. Best-effort per place; a place that will not go is tolerated and counted out."""
    out = {"ontology_trees": 0, "context_graph": 0, "schema_docs": 0}
    if not conn_id:
        return out
    for root in _trees():
        for name in _names(conn_id):
            for target in _targets(Path(root) / name, dataset):
                try:
                    out["ontology_trees"] += _remove(target)
                except OSError as exc:
                    tolerate(exc, f"ontology removal: could not remove {target}", counter="ontology.removal")
    graphs = _context_graph_root()
    if graphs.exists():
        for org in (p for p in graphs.iterdir() if p.is_dir()):
            for name in _names(conn_id):
                for target in _targets(org / name, dataset):
                    try:
                        out["context_graph"] += _remove(target)
                    except OSError as exc:
                        tolerate(exc, f"ontology removal: could not remove {target}", counter="ontology.removal")
    try:
        from aughor.knowledge import indexer
        if dataset is None:
            out["schema_docs"] += int(indexer.purge_connection_doctrees(conn_id) or 0)
        elif indexer.delete_document(indexer.doctree_doc_id(conn_id, dataset)):
            out["schema_docs"] += 1
    except Exception as exc:  # noqa: BLE001 — the trees are gone either way; the index is said
        tolerate(exc, "ontology removal: the schema documentation could not be unregistered",
                 counter="ontology.removal.index")
    return out
