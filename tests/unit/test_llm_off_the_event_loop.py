"""No synchronous LLM call may run on the event loop.

`LLMProvider.complete` and its siblings are synchronous all the way down to a blocking
TLS read (`_ssl__SSLSocket_read_impl -> PySSL_select -> poll(2)`). Called from an
`async def` — an SSE generator, say — that read parks the event loop thread for the whole
provider round-trip, and the process stops answering *every* request, `/health` included,
while staying alive and holding its listening socket. It then recovers on its own.

That failure mode is the reason this guard exists rather than a comment. It presented
three times in one session as a frontend bug (`Failed to fetch`, `ERR_CONNECTION_REFUSED`)
and cost a wrong IPv6 diagnosis plus two blocked verifications, because every cheap
liveness check a person reaches for — is the process up, is the port open — says yes.

The three sites that caused it (`_stream_chat`'s follow-up suggestions, at the
`ada_synthesize`, `synthesize_exploration` and `synthesize` branches) sat a few lines from
neighbours that hop to a thread correctly, including one `await asyncio.to_thread(lambda:
get_provider("narrator").complete(...))` forty lines above. Nothing about the call site
looked wrong; the omission is invisible by inspection, which is what makes it a rot guard
and not a code-review item.

Fixing those three did not end it. A run still stalled for seconds at the very end, and
trapping the stack mid-stall found a second shape in the same generator: a synchronous
`_write_answer_receipt` whose graph write goes out over TLS (`b"".join` over an httpx
chunk iterator, 2121 of 2123 samples in `poll(2)`). An LLM-only guard passed clean over
it. So the rule this file enforces is the general one — blocking I/O off the loop — and
`complete()` is only its most familiar instance.

The rule: a call named in `_BLOCKING` is allowed inside an `async def` only underneath
`asyncio.to_thread` / `run_in_executor`, or inside a nested plain `def` (a worker
function or thread target, which is the other pattern this codebase uses).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

#: Provider entry points that block. Each one ends in a synchronous SDK call.
_LLM_METHODS = {"complete", "complete_streaming", "complete_with_tools"}

#: Helpers that reach the network by a route other than the provider, found the same
#: way and in the same generator. `_write_answer_receipt` writes the ledger AND calls
#: `note_finding`, whose graph write goes out over TLS; `_try_salvage` runs a synthesis.
#: An LLM-only guard passed clean over both, which is why this list exists: the rule is
#: "blocking I/O off the loop", and `complete()` is only its most obvious instance. Add
#: to this set whenever a sync helper that touches the network gains an async caller.
_BLOCKING_HELPERS = {"_write_answer_receipt", "_try_salvage"}

_BLOCKING = _LLM_METHODS | _BLOCKING_HELPERS

#: Anything that moves the call off the loop thread.
_OFFLOADERS = {"to_thread", "run_in_executor"}

_PACKAGE = pathlib.Path(__file__).resolve().parents[2] / "aughor"


def _callee(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _blocking_llm_calls_on_async_paths() -> list[str]:
    """Every blocking call in `_BLOCKING` reachable on an event-loop thread."""
    found: list[str] = []

    def visit(node: ast.AST, on_loop: bool, offloaded: bool, path: pathlib.Path) -> None:
        for child in ast.iter_child_nodes(node):
            child_on_loop, child_offloaded = on_loop, offloaded
            if isinstance(child, ast.AsyncFunctionDef):
                # A new coroutine: on the loop again, and whatever offload wrapped the
                # enclosing scope does not cover its body.
                child_on_loop, child_offloaded = True, False
            elif isinstance(child, ast.FunctionDef):
                # A plain `def` nested in a coroutine is the worker/thread-target
                # pattern (`_hl_worker`, `_llm_work`) — its body is not on the loop.
                child_on_loop, child_offloaded = False, False
            if isinstance(child, ast.Call):
                name = _callee(child)
                if name in _OFFLOADERS:
                    child_offloaded = True
                elif name in _BLOCKING and child_on_loop and not offloaded:
                    found.append(
                        f"{path.relative_to(_PACKAGE.parent)}:{child.lineno} "
                        f"{ast.unparse(child.func)}(...)"
                    )
            visit(child, child_on_loop, child_offloaded, path)

    for source in sorted(_PACKAGE.rglob("*.py")):
        try:
            tree = ast.parse(source.read_text())
        except SyntaxError:  # pragma: no cover — a file that cannot parse is CI's problem
            continue
        visit(tree, on_loop=False, offloaded=False, path=source)
    return found


def test_no_blocking_llm_call_runs_on_the_event_loop():
    offenders = _blocking_llm_calls_on_async_paths()
    assert offenders == [], (
        "A synchronous LLM call is reachable on the event-loop thread. It will freeze "
        "every route (including /health) for the length of the provider round-trip, "
        "while the process stays alive and listening — the symptom reads as a dead API.\n"
        "Wrap it: `await asyncio.to_thread(lambda: get_provider(...).complete(...))`, or "
        "move it into a plain `def` worker run via `run_in_executor`.\n\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_can_actually_see_a_violation():
    """A scanner that cannot fail is a scanner that proves nothing.

    The real test above passes both when the codebase is clean and when the scan is
    broken, so the scan is exercised here against a snippet shaped exactly like the
    defect it exists to catch — and against the two spellings that are legitimate.
    """
    offending = ast.parse(
        "import asyncio\n"
        "async def stream():\n"
        "    yield 1\n"
        "    fq = get_provider('narrator').complete(system='s', user='u')\n"
    )
    legitimate = ast.parse(
        "import asyncio\n"
        "async def stream():\n"
        "    yield 1\n"
        "    fq = await asyncio.to_thread(lambda: get_provider('n').complete(system='s'))\n"
        "\n"
        "async def worker_style():\n"
        "    def _llm_work():\n"
        "        return get_provider('coder').complete(system='s')\n"
        "    return await loop.run_in_executor(None, _llm_work)\n"
    )

    def scan(tree: ast.AST) -> int:
        hits = 0

        def visit(node: ast.AST, on_loop: bool, offloaded: bool) -> None:
            nonlocal hits
            for child in ast.iter_child_nodes(node):
                child_on_loop, child_offloaded = on_loop, offloaded
                if isinstance(child, ast.AsyncFunctionDef):
                    child_on_loop, child_offloaded = True, False
                elif isinstance(child, ast.FunctionDef):
                    child_on_loop, child_offloaded = False, False
                if isinstance(child, ast.Call):
                    name = _callee(child)
                    if name in _OFFLOADERS:
                        child_offloaded = True
                    elif name in _BLOCKING and child_on_loop and not offloaded:
                        hits += 1
                visit(child, child_on_loop, child_offloaded)

        visit(tree, False, False)
        return hits

    # The second shape: not an LLM call at all, and the reason _BLOCKING_HELPERS exists.
    helper_shape = ast.parse(
        "import asyncio\n"
        "async def stream():\n"
        "    yield 1\n"
        "    rcpt = _write_answer_receipt(kind='ada_report', question='q')\n"
    )

    assert scan(offending) == 1, "the guard would not have caught the original defect"
    assert scan(legitimate) == 0, "the guard flags the correct patterns as violations"
    assert scan(helper_shape) == 1, (
        "the guard would not have caught the residual end-of-run stall, which was a "
        "blocking helper rather than a provider call"
    )


@pytest.mark.parametrize("method", sorted(_LLM_METHODS))
def test_the_named_provider_methods_still_exist(method):
    """The guard matches on method NAME, so a rename would silently blind it.

    This repo has been bitten by exactly that: #251's rename took a contract scanner from
    266 paths to 0 without failing anything.
    """
    from aughor.llm.provider import LLMProvider

    assert hasattr(LLMProvider, method) or any(
        method in n for n in dir(LLMProvider)
    ), f"LLMProvider.{method} is gone — update _LLM_METHODS or this guard is blind"
