"""The ontology → llm boundary ratchet (unified plan Layer 0.4).

The ontology package is a knowledge STORE plane: overrides, doc trees, graph
structure — deterministic, hermetic, replayable. The inference plane
(``aughor/llm``) is none of those things, so the dependency direction must be
one-way: **the llm plane may serve ontology content, but ontology modules must not
reach into the llm plane**. A store that quietly calls a model stops being
deterministic exactly where determinism is the contract (the same reasoning that
put the executor↔agent seam behind a kernel registry in PR #271's A4, after the
platform↔agent ratchet rejected the direct import).

Note the relationship to ``test_platform_agent_boundary``: there, ``ontology`` is
an *agent* package and ``llm`` is *platform*, so agent→platform is permitted. This
file is the stricter sub-rule for this one edge.

Same mechanics as the platform↔agent ratchet: stdlib ``ast`` over every ontology
source file (``ast.walk``, so function-local deferred imports are caught — all four
existing edges are exactly that shape), a ``TOLERATED`` allowlist at *submodule*
grain, and **exact equality**: a new edge fails, and a fixed edge left in the
allowlist also fails, so the list can only shrink.
"""
from __future__ import annotations

import ast
from pathlib import Path

AUGHOR = Path(__file__).resolve().parents[2] / "aughor"
ONTOLOGY = AUGHOR / "ontology"

# ── Edges that existed when the ratchet landed (2026-08-08) ───────────────────
# file (relative to repo root) -> the aughor.llm submodules it still imports.
# Adding a row (or a submodule to a row) is a regression, not a fix. Removal notes:
# doctree's provider edge is already an injectable seam (`provider_factory=None`
# defaults to it) — the cheapest to invert; the context_budget edges are a token
# ESTIMATOR (deterministic today, but the import still couples the store plane to
# the inference plane's module graph).
TOLERATED: dict[str, set[str]] = {
    "aughor/ontology/graph_tour.py": {"llm.provider"},
    "aughor/ontology/doctree.py": {"llm.context_budget", "llm.provider"},
}


def _ontology_files():
    for p in sorted(ONTOLOGY.rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p


def _llm_submodules_imported(path: Path) -> set[str]:
    found: set[str] = set()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
        elif isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        for mod in mods:
            parts = mod.split(".")
            if len(parts) >= 2 and parts[0] == "aughor" and parts[1] == "llm":
                found.add(".".join(parts[1:3]))   # "llm" bare, or "llm.<submodule>"
    return found


def _current_violations() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in _ontology_files():
        mods = _llm_submodules_imported(f)
        if mods:
            out[str(f.relative_to(AUGHOR.parent))] = mods
    return out


def test_ontology_does_not_import_llm():
    """Exact-equality ratchet: no NEW ontology→llm edge, and no STALE allowlist row."""
    violations = _current_violations()

    new_edges = {
        f: sorted(mods - TOLERATED.get(f, set()))
        for f, mods in violations.items()
        if mods - TOLERATED.get(f, set())
    }
    stale = {
        f: sorted(TOLERATED[f] - violations.get(f, set()))
        for f in TOLERATED
        if TOLERATED[f] - violations.get(f, set())
    }

    msg = []
    if new_edges:
        msg.append(
            "NEW ontology→llm imports (knowledge stores stay deterministic and "
            "hermetic — inject the dependency or route through a kernel seam, as "
            "PR #271's A4 did for the executor):\n  "
            + "\n  ".join(f"{f} -> {', '.join(m)}" for f, m in sorted(new_edges.items()))
        )
    if stale:
        msg.append(
            "STALE TOLERATED rows (these edges are fixed — delete them so the "
            "ratchet stays tight):\n  "
            + "\n  ".join(f"{f} -> {', '.join(m)}" for f, m in sorted(stale.items()))
        )
    assert not msg, "\n\n".join(msg)


def test_the_ratchet_can_actually_fire(tmp_path):
    """Anti-vacuous-pass guard: the scanner must see both import forms, including the
    function-local deferred shape every existing edge uses."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import aughor.llm.matrix\n"
        "def later():\n"
        "    from aughor.llm.provider import get_provider\n"
    )
    assert _llm_submodules_imported(probe) == {"llm.matrix", "llm.provider"}
