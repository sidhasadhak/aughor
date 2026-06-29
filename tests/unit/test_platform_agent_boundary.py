"""The Platform ↔ Agent boundary ratchet.

Aughor is a *Data Intelligence Platform* (the home) with the *Aughor Agent* (the
intelligence) running inside it. For the platform to stay plug-and-play, the
dependency direction must be one-way: the **Agent may import the Platform, but the
Platform must never import the Agent**. (See ``docs/PLATFORM_ARCHITECTURE.md`` /
``docs/AGENTIC_ARCHITECTURE.md``.)

This test statically walks every Platform source file, parses its imports with the
stdlib ``ast``, and fails if any of them import an Agent package. A ``TOLERATED``
allowlist captures the edges that still exist mid-migration so the ratchet lands
green; the assertion is **exact equality**, so every inversion step must *delete*
its rows from the allowlist (a fixed edge left in the allowlist also fails — the
allowlist can never silently rot, and it can only shrink).

The host / wiring seam (``routers/``, ``mcp/``, ``api.py``, ``cli.py``) is exempt:
it legitimately references both sides — it is where the platform *hosts* the agent.
"""
from __future__ import annotations

import ast
from pathlib import Path

AUGHOR = Path(__file__).resolve().parents[2] / "aughor"

# ── Platform surface that gets scanned ────────────────────────────────────────
# NOTE: `samples` is intentionally NOT scanned — it is a demo/fixture *seeder* that
# runs at startup like the host layer, legitimately seeding both platform data and
# agent metrics (e.g. the BeautyCommerce metric catalog). It is setup code, not core
# platform substrate.
PLATFORM_DIRS = {
    "db", "kernel", "connectors", "metastore", "org", "platform", "security",
    "llm", "licensing", "workspace", "orgsettings", "volumes", "canvas",
    "export", "savedquery", "actions",
}
PLATFORM_TOP_MODULES = {"secretvault.py", "stats.py", "telemetry.py"}
# sql/ is split: the inspectors are platform; sql/writer.py is agent (LLM SQL gen).
SQL_AGENT_FILES = {"writer.py"}

# ── Agent packages — forbidden import targets for platform code ───────────────
AGENT_PKGS = {
    "agent", "explorer", "ontology", "semantic", "knowledge", "briefs",
    "playbook", "packs", "profile", "verify", "evidence", "semops",
    "monitors", "memory", "process", "tools", "rules",
}

# ── Edges that still exist mid-migration (each inversion step deletes its rows) ─
# file (relative to repo root) -> the set of agent packages it still imports.
# EMPTY — the boundary is now strict: NO platform module may import an agent module.
# Every coupling has been inverted (contract types · purge hooks · ingestion sinks ·
# schema annotators · execution hooks). Adding an entry here is a regression, not a fix.
TOLERATED: dict[str, set[str]] = {}


def _platform_files():
    for d in sorted(PLATFORM_DIRS):
        for p in (AUGHOR / d).rglob("*.py"):
            if "__pycache__" not in p.parts:
                yield p
    for m in PLATFORM_TOP_MODULES:
        p = AUGHOR / m
        if p.exists():
            yield p
    for p in (AUGHOR / "sql").rglob("*.py"):
        if "__pycache__" not in p.parts and p.name not in SQL_AGENT_FILES:
            yield p


def _agent_pkgs_imported(path: Path) -> set[str]:
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
            if len(parts) >= 2 and parts[0] == "aughor" and parts[1] in AGENT_PKGS:
                found.add(parts[1])
    return found


def _current_violations() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in _platform_files():
        pkgs = _agent_pkgs_imported(f)
        if pkgs:
            out[str(f.relative_to(AUGHOR.parent))] = pkgs
    return out


def test_platform_does_not_import_agent():
    """Exact-equality ratchet: no NEW platform→agent edge, and no STALE allowlist row."""
    violations = _current_violations()

    new_edges = {
        f: sorted(pkgs - TOLERATED.get(f, set()))
        for f, pkgs in violations.items()
        if pkgs - TOLERATED.get(f, set())
    }
    stale = {
        f: sorted(TOLERATED[f] - violations.get(f, set()))
        for f in TOLERATED
        if TOLERATED[f] - violations.get(f, set())
    }

    msg = []
    if new_edges:
        msg.append(
            "NEW Platform→Agent imports (the platform must not import the agent — "
            "invert via a registry/contract, see docs/PLATFORM_ARCHITECTURE.md):\n  "
            + "\n  ".join(f"{f} -> {', '.join(p)}" for f, p in sorted(new_edges.items()))
        )
    if stale:
        msg.append(
            "STALE TOLERATED rows (these edges are fixed — delete them from the "
            "allowlist so the ratchet stays tight):\n  "
            + "\n  ".join(f"{f} -> {', '.join(p)}" for f, p in sorted(stale.items()))
        )
    assert not msg, "\n\n".join(msg)
