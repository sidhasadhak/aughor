"""Regression: _aiter_sync must terminate CLEANLY at stream-end.

The bridge wraps a sync iterator (LangGraph .stream()) into an async generator via
`run_in_executor(None, next, it)`. The iterator's terminal StopIteration gets marshaled
through a Future, and asyncio converts it to a TypeError ("StopIteration ... cannot be
raised into a Future") that an `except StopIteration` never catches — so the TypeError
used to leak out at stream-end and route a cleanly-completed ADA investigation through
the except/salvage path. These pin: full drain, clean stop, and that a REAL error still
propagates (we only swallow the terminal sentinel, not genuine failures).
"""
import asyncio

import pytest

from aughor.routers.investigations import _aiter_sync


def _drain(sync_iter):
    async def _collect():
        return [x async for x in _aiter_sync(sync_iter)]
    return asyncio.run(_collect())


def test_yields_all_items_and_stops_cleanly():
    # The bug: this raised TypeError at exhaustion instead of stopping.
    assert _drain(iter([1, 2, 3])) == [1, 2, 3]


def test_empty_iterator_terminates():
    assert _drain(iter([])) == []


def test_generator_source_drains_fully():
    def gen():
        yield "a"
        yield "b"
    assert _drain(gen()) == ["a", "b"]


def test_real_exception_still_propagates():
    # We must swallow ONLY the terminal sentinel, never a genuine error.
    def boom():
        yield 1
        raise ValueError("kaboom")
    with pytest.raises(ValueError, match="kaboom"):
        _drain(boom())
