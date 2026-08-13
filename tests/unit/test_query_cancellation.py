"""SE-3 F — a query time limit that ends the query, and a cancel that reaches the engine.

Before this wave `QueryBudget.max_time_ms` was compared against the elapsed time *after*
the query returned, so it named a runaway query instead of stopping one — the docstring
in ``security/sandbox.py`` said as much ("we cannot *cancel* an already-running query
without connection-level support"). These tests pin the two things that had to become
true for that to change:

1. ``DatabaseConnection.interrupt()`` really aborts a statement blocking another thread.
2. ``_run_watched`` turns a deadline OR a client disconnect into that interrupt, and
   waits for the worker to unwind before reporting — so no thread outlives the request
   still holding a connection.

The slow statement is a real DuckDB scan rather than a ``sleep``: the interrupt has to
land inside the *engine's* execution loop, and a Python sleep would prove only that
Python can be interrupted.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from aughor.db.connection import DuckDBConnection
from aughor.routers.query import QueryAborted, _run_watched

# Big enough that it cannot finish while we watch it, and cheap to start.
_SLOW_SQL = "SELECT count(*) FROM range(20000000000) t(i) WHERE i % 7 = 0"


@pytest.fixture()
def db(tmp_path):
    """A real on-disk DuckDB connection (the class opens read-only, which rejects
    ``:memory:``)."""
    import duckdb
    path = tmp_path / "cancel.duckdb"
    duckdb.connect(str(path)).close()
    conn = DuckDBConnection(path)
    yield conn
    try:
        conn.close()
    except Exception:
        pass


class _Request:
    """The two lines of Starlette's Request that ``_run_watched`` touches."""

    def __init__(self, disconnect_after: float | None = None):
        self._t0 = time.monotonic()
        self._after = disconnect_after

    async def is_disconnected(self) -> bool:
        return self._after is not None and (time.monotonic() - self._t0) > self._after


def test_interrupt_aborts_a_statement_running_on_another_thread(db):
    """The primitive everything else rests on.

    Note the SHAPE: ``execute()`` catches the engine's ``InterruptException`` and
    returns it as ``QueryResult.error`` rather than raising — the same contract it
    uses for a syntax error. So "it stopped" is proved by the elapsed time and the
    error text, not by an exception escaping. ``_run_watched`` is written for that:
    it reports the abort from what IT knows (it asked for the interrupt), never from
    whether the future raised.
    """
    seen: dict[str, object] = {}

    def worker():
        started = time.monotonic()
        result = db.execute("__test__", _SLOW_SQL)
        seen["elapsed"] = time.monotonic() - started
        seen["error"] = result.error
        seen["rows"] = result.rows

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.5)
    assert db.interrupt() is True          # the connector could ask the engine
    t.join(timeout=30)

    assert not t.is_alive(), "interrupt did not end the statement"
    # Minutes of work, ended within a moment of the interrupt.
    assert seen["elapsed"] < 5.0, f"statement ran on for {seen['elapsed']:.1f}s"
    assert "interrupt" in str(seen["error"]).lower(), seen["error"]
    assert seen["rows"] == []


def test_interrupt_leaves_the_connection_reusable(db):
    """It goes back to the POOL afterwards, so an aborted run must not poison it."""
    def worker():
        try:
            db.execute("__test__", _SLOW_SQL)
        except Exception:
            pass

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.5)
    db.interrupt()
    t.join(timeout=30)

    result = db.execute("__test__", "SELECT 42 AS answer")
    assert result.error is None
    assert result.rows[0][0] in (42, "42")


def _work_for(db):
    """The shape the route uses: the OWNING thread closes, never the interrupter."""
    def _work():
        try:
            return db.execute("__test__", _SLOW_SQL)
        finally:
            db.close()
    return _work


def test_deadline_stops_the_query(db):
    async def go():
        return await _run_watched(db, _work_for(db), request=_Request(), limit_ms=1200)

    t0 = time.monotonic()
    with pytest.raises(QueryAborted) as caught:
        asyncio.run(go())
    elapsed = time.monotonic() - t0

    assert caught.value.reason == "timeout"
    assert caught.value.limit_ms == 1200
    # Ended near the limit, not at the query's natural end (which is minutes away).
    # The upper bound allows one watchdog interval plus unwind.
    assert 1.2 <= elapsed < 4.0, f"stopped at {elapsed:.2f}s"


def test_client_disconnect_stops_the_query(db):
    """No job id, no second endpoint — the socket closing IS the cancel signal."""
    async def go():
        return await _run_watched(
            db, _work_for(db), request=_Request(disconnect_after=0.8), limit_ms=0)

    t0 = time.monotonic()
    with pytest.raises(QueryAborted) as caught:
        asyncio.run(go())
    elapsed = time.monotonic() - t0

    assert caught.value.reason == "cancelled"
    assert 0.8 <= elapsed < 4.0, f"stopped at {elapsed:.2f}s"


def test_fast_query_is_untouched_by_an_armed_deadline(db):
    """The watchdog must cost a normal query nothing — this is the common case."""
    def _work():
        try:
            return db.execute("__test__", "SELECT 42 AS answer")
        finally:
            db.close()

    async def go():
        return await _run_watched(db, _work, request=_Request(), limit_ms=5000)

    t0 = time.monotonic()
    result = asyncio.run(go())
    elapsed = time.monotonic() - t0

    assert result.error is None
    assert result.rows[0][0] in (42, "42")
    # One watchdog interval is 250 ms; a sub-second query must not be made to wait
    # for a poll tick before its result is returned.
    assert elapsed < 0.25, f"fast query took {elapsed:.3f}s — the watchdog is blocking it"


def test_every_duckdb_backed_connector_can_be_interrupted():
    """The defect this test exists for: `interrupt()` first landed on
    ``DuckDBConnection`` only, so the demo Workspace — a ``LocalUploadConnection`` —
    was silently uncancellable while every test passed. Cancel read as broken in the
    product and correct in CI.

    A DuckDB-backed connector is not one class, so assert on the PROPERTY that makes
    one cancellable: it keeps its driver handle where the base implementation looks.
    A new connector that stores it elsewhere fails here rather than in someone's
    browser.
    """
    from aughor.connectors.file.local_upload import LocalUploadConnection

    for cls in (DuckDBConnection, LocalUploadConnection):
        assert cls.interrupt is DuckDBConnection.interrupt, (
            f"{cls.__name__} overrides interrupt() — check it still actually aborts")

    conn = LocalUploadConnection.__new__(LocalUploadConnection)
    import duckdb
    conn._conn = duckdb.connect(":memory:")
    try:
        assert conn.interrupt() is True, (
            "LocalUploadConnection cannot be interrupted — the base implementation "
            "did not find its driver handle at `_conn`")
    finally:
        conn._conn.close()


def test_interrupt_is_false_when_there_is_no_engine_handle():
    """The honest negative: a connector with nothing to ask reports so, which is what
    makes `_run_watched` wait instead of claiming a stop that never happened."""
    class _Handleless(DuckDBConnection):
        def __init__(self):  # no _conn at all
            pass

    assert _Handleless().interrupt() is False


def test_connector_without_interrupt_support_waits_rather_than_lying(db, monkeypatch):
    """A connector that cannot abort must not report a stop that did not happen —
    returning early would strand a thread still holding the connection."""
    monkeypatch.setattr(type(db), "interrupt", lambda self: False)

    def _work():
        try:
            return db.execute("__test__", "SELECT 7 AS answer")
        finally:
            db.close()

    async def go():
        return await _run_watched(
            db, _work, request=_Request(disconnect_after=0.0), limit_ms=1)

    result = asyncio.run(go())          # completes rather than raising QueryAborted
    assert result.rows[0][0] in (7, "7")
