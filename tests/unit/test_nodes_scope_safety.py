"""Scope-safety regression guards for agent.nodes.

Two latent name-resolution bugs were masked by each other on the diagnostic
("which X is weakest") Deep-Analysis path:

1. `classify_question` called `re.search` while `re` was only imported *locally*
   inside other functions → `NameError: name 're' is not defined`. Because this
   fired in the very first node (route_question), it hid bug 2.

2. `execute_planned_queries` appended to `new_pitfalls` in the cross-query
   consistency block (alias/join divergence) BEFORE the list was initialised
   further down → `UnboundLocalError: cannot access local variable 'new_pitfalls'`.

Both compile cleanly and pass imports/most unit tests — only a runtime hit on the
right branch exposes them. These AST/structural guards catch them statically."""
import ast
import inspect

from aughor.agent import nodes as N


def test_re_imported_at_module_scope():
    import re as _re
    assert getattr(N, "re", None) is _re, "agent.nodes must import `re` at module scope"


def _first_lineno(func_node, predicate):
    hits = [n.lineno for n in ast.walk(func_node) if predicate(n)]
    return min(hits) if hits else None


def _func_ast(func):
    """AST of a function relative to its own source (lineno starts at 1)."""
    src = inspect.getsource(func)
    return ast.parse(src).body[0]


def test_new_pitfalls_initialised_before_first_use():
    fn = _func_ast(N.execute_planned_queries)

    def is_assign(n):
        return isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "new_pitfalls" for t in n.targets
        ) or (
            isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and n.target.id == "new_pitfalls"
        )

    def is_use(n):
        # `new_pitfalls.append(...)` — attribute access on the Name
        return (
            isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "new_pitfalls"
        )

    first_assign = _first_lineno(fn, is_assign)
    first_use = _first_lineno(fn, is_use)
    assert first_assign is not None, "new_pitfalls must be initialised in execute_planned_queries"
    assert first_use is not None, "expected new_pitfalls.append(...) usage"
    assert first_assign < first_use, (
        f"new_pitfalls used at line {first_use} before its init at line {first_assign} "
        "(UnboundLocalError on the alias/join-divergence branch)"
    )
