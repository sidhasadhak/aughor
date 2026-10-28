"""Every name the golden-set harness imports from Aughor exists (PENDING item 19).

`evals/run_golden.py` builds each question's context the way the chat path does, inside `try: … except: pass`, so a
name that moved does not fail the run — it removes that step from it. `_parse_schema_tables` left `aughor.tools.schema`
on 2026-06-30, and from then on no table was linked: no Data Catalog, no fan-out guard, and an empty data profile, so
the two with/without runs of `grounding.data_profiles` (2026-09-24, 2026-10-04) compared one prompt with itself. This
reads every `from aughor… import …` in the harness, wherever it sits, and resolves it.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "evals" / "run_golden.py"


def _imports() -> list[tuple[str, str]]:
    tree = ast.parse(HARNESS.read_text())
    return [(node.module, alias.name) for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("aughor")
            for alias in node.names]


def test_the_harness_imports_from_aughor_at_all():
    assert len(_imports()) > 20


def _resolves(module: str, name: str) -> bool:
    if hasattr(importlib.import_module(module), name):
        return True
    try:   # `from aughor.tools import catalog_profiles` names a submodule
        importlib.import_module(f"{module}.{name}")
        return True
    except ModuleNotFoundError:
        return False


def test_every_name_the_harness_imports_from_aughor_exists():
    assert [f"{module}.{name}" for module, name in _imports() if not _resolves(module, name)] == []
