"""BigQuery's Cancel button did nothing, and said so honestly.

The base `interrupt()` reaches whatever `_driver_handle()` returns and calls its own
`interrupt()`. A BigQuery client is a REST client with no such method, so the connector
returned False — correct, and useless: a long BigQuery scan could not be stopped.

Cancelling on BigQuery means cancelling the JOB, and that needs the `QueryJob` object.
The connector had one on every run (`self._client.query(...)`) and dropped it on the floor.
Retaining it only FOR THE DURATION of the run is the whole design: a job kept afterwards
would make `interrupt()` return True while cancelling something already finished, which is
worse than returning False — a caller that trusts True stops waiting for a query that is
still coming.

No live BigQuery here. These drive the retention and the abort against a fake client; what
they cannot prove is that Google's API accepts the cancel, only that we ask exactly once,
on a job that is actually running.
"""
from __future__ import annotations

import threading

import pytest

from aughor.connectors.warehouse.bigquery import BigQueryConnection


class _Job:
    def __init__(self, on_result=None, cancel_raises=False):
        self.cancelled = 0
        self._on_result = on_result
        self._cancel_raises = cancel_raises

    def cancel(self):
        self.cancelled += 1
        if self._cancel_raises:
            raise RuntimeError("REST call failed")

    def result(self, max_results=None):
        if self._on_result:
            self._on_result()
        return type("Rows", (), {"schema": [], "__iter__": lambda _s: iter(())})()


def _conn(job):
    c = BigQueryConnection.__new__(BigQueryConnection)
    c._connection_id = "bq1"
    c._project, c._dataset = "p", "d"
    c._client = type("C", (), {"query": lambda _s, sql, job_config=None: job})()
    return c


def test_nothing_in_flight_answers_false_rather_than_true():
    """The failure mode the retention window exists to prevent. True means 'I asked the
    engine to stop'; claiming it with no job is how a caller stops waiting for a query that
    is still running."""
    conn = _conn(_Job())

    assert conn.interrupt() is False


def test_a_running_job_is_cancelled():
    seen = {}

    def _during():
        seen["result"] = conn.interrupt()

    job = _Job(on_result=_during)
    conn = _conn(job)
    conn._bind_execute("SELECT @v", {"v": 1})

    assert seen["result"] is True, "interrupt() found no job while one was running"
    assert job.cancelled == 1


def test_the_job_is_released_when_the_run_ends():
    """Including when it ends badly. A job left published after a failure would make the
    next Cancel claim success against a dead run."""
    class _Boom(_Job):
        def result(self, max_results=None):
            raise RuntimeError("query failed")

    conn = _conn(_Boom())
    with pytest.raises(RuntimeError):
        conn._bind_execute("SELECT @v", {"v": 1})

    assert conn._job is None and conn.interrupt() is False


def test_the_unbound_path_is_cancellable_too():
    """`execute` and `_bind_execute` are separate call sites, and a capability added to one
    of a connector's two execution paths is this repo's most-repeated bug."""
    seen = {}
    job = _Job(on_result=lambda: seen.__setitem__("result", conn.interrupt()))
    conn = _conn(job)
    conn.execute("query_workbench", "SELECT 1")

    assert seen["result"] is True and job.cancelled == 1


def test_a_failing_cancel_is_false_not_an_exception():
    """`interrupt()` runs on a SECOND thread while the first is blocked in `result()`.
    An exception there surfaces nowhere useful and the query is no less stuck."""
    seen = {}
    job = _Job(on_result=lambda: seen.__setitem__("result", conn.interrupt()),
               cancel_raises=True)
    conn = _conn(job)
    conn.execute("query_workbench", "SELECT 1")

    assert seen["result"] is False
    assert job.cancelled == 1, "it still asked — the failure was the REST call's"


def test_cancel_reaches_across_threads():
    """The property that makes any of this useful: `execute` blocks its own thread, so the
    only way to stop a runaway query is another thread reaching the engine."""
    started, release = threading.Event(), threading.Event()

    def _wait():
        started.set()
        release.wait(timeout=5)

    job = _Job(on_result=_wait)
    conn = _conn(job)
    runner = threading.Thread(target=conn.execute, args=("query_workbench", "SELECT 1"))
    runner.start()
    try:
        assert started.wait(timeout=5), "the fake never reached result()"
        assert conn.interrupt() is True
    finally:
        release.set()
        runner.join(timeout=5)
    assert job.cancelled == 1


def test_the_connector_no_longer_relies_on_the_base_implementation():
    """A rot-guard: if someone deletes the override, the base returns False against a REST
    client forever and every test above still passes except this one."""
    from aughor.db.connection import DatabaseConnection

    assert BigQueryConnection.interrupt is not DatabaseConnection.interrupt
