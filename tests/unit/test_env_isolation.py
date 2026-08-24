"""The suite runs on the environment the conftest declares, and nothing else.

A developer's `.env` is the one thing that can make a local run a DIFFERENT experiment
from CI's, and the divergence is invisible while it lasts: it presents as a test that
fails on a laptop and passes in CI, which reads as flakiness and gets re-run rather than
diagnosed.

That is not hypothetical. `test_route_wide::test_ask_causal_question_pins_investigate_
with_flag_on` was exactly this for weeks — recorded as "`.env`-dependent" with no
mechanism. Measured 2026-08-24 by bisecting the suite: `aughor/api.py` calls
`load_dotenv` at IMPORT, so ANY test that builds a TestClient pulled the developer's
`.env` into the process; `.env`'s `AUGHOR_DEFAULT_POSTGRES_DSN` changed how a connection
id resolves, and the ask then died with "Connection 'c1' not found" before it reached the
faked deep body. Four eval scripts under `evals/` do the same at import, so merely
importing one from a test leaked it too.

These assert the STRUCTURE — that every `load_dotenv` call sits under a check of the
skip flag — rather than the text, because a comment mentioning the flag would satisfy a
substring search while an unguarded call sat right beside it.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Every module that loads `.env` as an import side effect. A new one belongs here with
#: its guard, not in a list of exceptions.
LOADERS = (
    "aughor/api.py",
    "evals/ablation_eval.py",
    "evals/run_golden.py",
    "evals/spider2.py",
    "evals/spider2_diag.py",
    # A LIBRARY module, so this one leaked into the app itself rather than only into
    # tests that imported a script.
    "aughor/semantic/kb_retriever.py",
)

SKIP_FLAG = "AUGHOR_SKIP_DOTENV"


def test_the_suite_declares_a_clean_environment():
    """Set by `tests/conftest.py` before anything imports the app. Without it the rest of
    this file is describing a rule nobody applies."""
    assert os.environ.get(SKIP_FLAG), (
        "the conftest no longer declares a clean environment — every test after the "
        "first TestClient is running on whatever the developer has in `.env`")


def _load_dotenv_calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "load_dotenv"]


def _guarded_by_flag(node: ast.AST) -> bool:
    """Does this `if` test read the skip flag — as a literal, or through the constant
    `aughor/api.py` defines for it?"""
    for c in ast.walk(node):
        if isinstance(c, ast.Constant) and c.value == SKIP_FLAG:
            return True
        if isinstance(c, ast.Name) and c.id == "SKIP_DOTENV_ENV":
            return True
    return False


@pytest.mark.parametrize("rel", LOADERS)
def test_every_dotenv_load_is_behind_the_skip_flag(rel):
    path = REPO / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = _load_dotenv_calls(tree)
    assert calls, (
        f"{rel} no longer loads `.env` at all — drop it from LOADERS rather than "
        f"leaving a guard for something that is not there")

    guarded = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _guarded_by_flag(node.test):
            guarded.extend(_load_dotenv_calls(node))

    unguarded = [c.lineno for c in calls if c not in guarded]
    assert not unguarded, (
        f"{rel} loads `.env` at import on line(s) {unguarded} without checking "
        f"{SKIP_FLAG}. Importing it from a test puts the developer's environment into "
        f"the process, and every test after that one runs a different experiment from CI.")


def test_the_loader_list_has_not_gone_stale():
    """A file that stopped loading `.env` and stayed on the list turns the guard into a
    rule about nothing — the same way a stale exemption does."""
    missing = [rel for rel in LOADERS if not (REPO / rel).exists()]
    assert missing == [], f"{missing} no longer exist — drop them from LOADERS"


def test_nothing_new_loads_dotenv_unguarded():
    """The ratchet. A sixth loader must arrive with its guard, not quietly."""
    offenders = []
    # `aughor/` and `evals/` only. `scripts/` holds standalone probes that are RUN, never
    # imported — loading `.env` is the entire reason they work at all (a bare script
    # without it 401s silently). The test below is what keeps that assumption true.
    for root in ("aughor", "evals"):
        for path in sorted((REPO / root).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if rel in LOADERS:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            if not _load_dotenv_calls(tree):
                continue
            # A load inside a function is fine: it runs when the CLI entry point calls
            # it, not when a test imports the module.
            module_level = [
                c for c in _load_dotenv_calls(tree)
                if not any(isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef))
                           for p in _parents(tree, c))
            ]
            if module_level:
                offenders.append(rel)
    assert offenders == [], (
        f"{offenders} load `.env` at import without being on the guarded list. Either "
        f"move the load into the entry point, or guard it with {SKIP_FLAG} and add the "
        f"file to LOADERS.")


def _parents(tree: ast.AST, target: ast.AST) -> list[ast.AST]:
    """Every ancestor of ``target`` within ``tree`` (ast carries no parent links)."""
    found: list[ast.AST] = []

    def walk(node: ast.AST, stack: list[ast.AST]) -> bool:
        if node is target:
            found.extend(stack)
            return True
        for child in ast.iter_child_nodes(node):
            if walk(child, stack + [node]):
                return True
        return False

    walk(tree, [])
    return found


def _scripts_that_load_dotenv_at_import() -> set:
    """Module names under `scripts/` whose `load_dotenv` runs on import."""
    out = set()
    for path in sorted((REPO / "scripts").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for call in _load_dotenv_calls(tree):
            in_function = any(isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef))
                              for p in _parents(tree, call))
            guarded = any(isinstance(p, ast.If) and _guarded_by_flag(p.test)
                          for p in _parents(tree, call))
            if not in_function and not guarded:
                out.add(f"scripts.{path.stem}")
    return out


def test_no_test_imports_a_script_that_loads_dotenv():
    """`scripts/` is exempt from the loader ratchet because the probes there are RUN,
    never imported — loading `.env` is the entire reason a bare script authenticates at
    all. This is that assumption, asserted, and scoped to the scripts it is about:
    importing a script with no `load_dotenv` is harmless and stays allowed.
    """
    hazardous = _scripts_that_load_dotenv_at_import()
    assert hazardous, "no script loads `.env` at import any more — retire this guard"

    offenders = []
    for path in sorted((REPO / "tests").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                if any(name == h or name.startswith(h + ".") for h in hazardous):
                    offenders.append(f"{path.relative_to(REPO).as_posix()} → {name}")
    assert sorted(set(offenders)) == [], (
        f"{sorted(set(offenders))}: importing these runs their `load_dotenv` inside the "
        f"suite's process, which is the leak this file exists to prevent. Guard that "
        f"script's load and add it to LOADERS, or stop importing it.")


def test_no_test_calls_load_dotenv():
    """A test that loads `.env` mutates `os.environ` for the REST OF THE PROCESS.

    This is the hole the rest of this file did not cover, and something was living in
    it: `test_otlp_export.py` called `load_dotenv` on purpose — sound reasoning, since a
    hermeticity guard that only reads the ambient environment passes when the scrub is
    deleted, so it took the leak path itself. But taking it for real polluted every test
    that ran afterwards, and it was the LAST surviving cause of `test_route_wide` failing
    on a laptop while passing in CI.

    `dotenv_values` reads the same file and returns a dict; apply it with `monkeypatch`
    and the environment is restored when the test ends. The guard keeps its teeth — put
    back the leak and it still fails when the scrub is removed — without the leak.
    """
    offenders = []
    for path in sorted((REPO / "tests").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            func = getattr(node, "func", None)
            name = (getattr(func, "attr", None) or getattr(func, "id", None)
                    if isinstance(node, ast.Call) else None)
            if name != "load_dotenv":
                continue
            # Inside a function it runs only when that code path is chosen — an opt-in
            # e2e fixture may legitimately want the developer's real credentials. At
            # MODULE level it runs on COLLECTION, which is every bare `pytest` invocation
            # including CI's, deselected markers and all.
            if any(isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef))
                   for p in _parents(tree, node)):
                continue
            offenders.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}")
    assert offenders == [], (
        f"{offenders} call `load_dotenv` at module level, so it runs when pytest merely "
        f"COLLECTS the file and mutates os.environ for the rest of the process. Move it "
        f"into a fixture, or use `dotenv_values` + `monkeypatch.setenv`.")
