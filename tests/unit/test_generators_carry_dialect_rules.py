"""Every place that asks a model for SQL through `CHAT_PROMPT` hands it the engine's dialect rules.

The quick path, the deep writer and agent evaluation carried `writer_rules(db)` (#457); the benchmark runner and
the eval harness's generators did not. So on 2026-09-13 two ON-10 falsifier runs measured SQL written blind to the
engine — both lag questions came back as SQLite's JULIANDAY on DuckDB, a function the DuckDB rules forbid by name.
The builders are FOUND by parsing, never listed: a new one is held to this the day it is written. What counts is
CODE that reaches the rules — a name used, a keyword passed — never a comment that mentions them.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_ROOTS = ("aughor", "evals")
_RULE_NAMES = {"writer_rules", "_writer_rules", "dialect_rules"}

#: A builder whose rules ride the schema its caller hands it — and the caller that must carry them.
_RIDES_THE_CALLER = {("aughor/custom_agents/quality.py", "_generate_sql"): "evaluate_agent"}


def _modules():
    for root in _ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            yield path.relative_to(REPO).as_posix(), path.read_text(encoding="utf-8")


def _functions(tree: ast.AST) -> list:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _innermost(functions: list, line: int):
    holding = [f for f in functions if f.lineno <= line <= (f.end_lineno or f.lineno)]
    return max(holding, key=lambda f: f.lineno) if holding else None


def _formats_chat_prompt(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "CHAT_PROMPT")


def _reaches_the_rules(fn: ast.AST) -> bool:
    return any((isinstance(n, ast.Name) and n.id in _RULE_NAMES) or (isinstance(n, ast.keyword)
                                                                     and n.arg == "dialect_rules")
               for n in ast.walk(fn))


def _prompt_builders():
    """(module, the function that formats CHAT_PROMPT) for every such function."""
    for module, text in _modules():
        if "CHAT_PROMPT.format(" not in text:
            continue
        tree = ast.parse(text)
        functions = _functions(tree)
        for node in ast.walk(tree):
            if _formats_chat_prompt(node):
                fn = _innermost(functions, node.lineno)
                assert fn is not None, f"{module}:{node.lineno} formats CHAT_PROMPT outside any function"
                yield module, fn


def _function(module: str, name: str):
    return next(f for f in _functions(ast.parse((REPO / module).read_text(encoding="utf-8"))) if f.name == name)


def test_the_scan_finds_the_builders_it_must_hold():
    """A scan that finds nothing passes everything, so it must find the builders known today."""
    builders = list(_prompt_builders())
    assert len(builders) >= 5
    assert {m for m, _ in builders} >= {"aughor/routers/investigations.py", "aughor/agent/benchmarks.py",
                                        "aughor/custom_agents/quality.py", "evals/run_golden.py"}


def test_every_prompt_builder_carries_the_engine_rules():
    blind = []
    for module, fn in _prompt_builders():
        caller = _RIDES_THE_CALLER.get((module, fn.name))
        if not _reaches_the_rules(_function(module, caller) if caller else fn):
            blind.append(f"{module}:{fn.name}")
    assert not blind, f"these ask a model for SQL without the engine's dialect rules: {blind}"


def test_every_call_of_the_eval_generator_passes_the_rules():
    calls = []
    for module, text in _modules():
        if "generate_sql_chat(" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name == "generate_sql_chat":
                calls.append((f"{module}:{node.lineno}", any(k.arg == "dialect_rules" for k in node.keywords)))
    assert len(calls) >= 5
    assert [where for where, passes in calls if not passes] == []


def test_the_eval_generator_leads_its_prompt_with_the_rules(monkeypatch):
    from aughor.db.dialects import DUCKDB_RULES
    from evals import run_golden

    seen: dict = {}

    class _Provider:
        def complete(self, *, system, user, response_model, temperature):
            seen["user"] = user
            return response_model(sql="SELECT 1")

    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: _Provider())
    sql = run_golden.generate_sql_chat("How many orders?", "c1", "TABLE orders (id)", dialect_rules=DUCKDB_RULES)
    assert sql == "SELECT 1"
    assert seen["user"].startswith(DUCKDB_RULES) and "TABLE orders (id)" in seen["user"]
