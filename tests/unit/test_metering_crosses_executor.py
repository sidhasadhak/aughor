"""Metering must survive the `run_in_executor` boundary — or every number is a lie.

Found the hard way. A metered exploration reported `llm_calls=0` with 44 episodes on
disk: the stdlib default executor does not copy contextvars, so every LLM and SQL call
dispatched into a thread saw `metering._current is None` and silently no-oped. The run
looked clean. It measured almost nothing.

`aughor.api._install_context_executor` fixes that by installing a
`ContextThreadPoolExecutor` as the loop's default — but it is one line in a lifespan
whose ORDER matters (it must precede any startup step that dispatches into a thread),
and nothing protected it. Move it, drop it, or add an earlier threaded step, and cost
metering silently reports zero across the whole platform while every test stays green.

That is the failure this file exists to make loud.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.kernel import metering


def _record_in_thread():
    metering.record_llm(10, 5, 1.0)
    metering.record_query(1, 1.0, "SELECT 1")


async def _measure() -> metering.RunMetrics:
    m = metering.RunMetrics()
    token = metering._current.set(m)
    try:
        await asyncio.get_running_loop().run_in_executor(None, _record_in_thread)
    finally:
        metering._current.reset(token)
    return m


def test_the_stdlib_executor_really_does_drop_metering():
    """The vacuous-pass guard. If this ever passes without the fix, the whole file is
    measuring nothing — exactly the trap it documents."""
    async def go():
        from concurrent.futures import ThreadPoolExecutor
        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(thread_name_prefix="stdlib"))   # no context copying
        return await _measure()

    m = asyncio.run(go())
    assert m.llm_calls == 0 and m.query_count == 0, (
        "the stdlib executor now propagates contextvars — this guard's premise changed; "
        "re-read it before trusting the test below")


def test_the_installed_executor_carries_metering_into_threads():
    async def go():
        from aughor.kernel.concurrency import ContextThreadPoolExecutor
        asyncio.get_running_loop().set_default_executor(
            ContextThreadPoolExecutor(thread_name_prefix="test-exec"))
        return await _measure()

    m = asyncio.run(go())
    assert m.llm_calls == 1, "LLM cost dispatched into a thread was not attributed"
    assert m.query_count == 1 and m.distinct_queries == 1


def test_the_api_lifespan_installs_it_before_any_threaded_step():
    """Ordering, asserted on the shipping source rather than on a comment.

    `_install_context_executor()` must come before the first `await _…` startup step,
    because anything dispatching into a thread before it runs is unmetered forever.
    """
    import inspect

    from aughor import api

    src = inspect.getsource(api.lifespan) if hasattr(api, "lifespan") else None
    if src is None:                                   # renamed — find it by content
        src = next((inspect.getsource(v) for v in vars(api).values()
                    if callable(v) and "_install_context_executor" in
                    (inspect.getsource(v) if inspect.isfunction(v) else "")), None)
    assert src and "_install_context_executor()" in src, (
        "the lifespan no longer installs the context executor — per-run metering is "
        "silently zero for every threaded call on the platform")

    install_at = src.index("_install_context_executor()")
    threaded = [src.index(m) for m in ("_kernel_journal_boot", "_setup_samples")
                if m in src]
    assert threaded and install_at < min(threaded), (
        "a startup step that can dispatch into a thread now runs BEFORE the context "
        "executor is installed; its cost will not be attributed to any run")


@pytest.mark.parametrize("field", ["llm_calls", "query_count"])
def test_a_liveness_invariant_exists_for_readers(field):
    """The habit that caught the false zero: never read a ratio off a run without first
    asserting the instrument was attached. Pinned here so the reasoning survives."""
    m = metering.RunMetrics()
    assert getattr(m, field) == 0, "a fresh run starts at zero — so zero proves nothing"
