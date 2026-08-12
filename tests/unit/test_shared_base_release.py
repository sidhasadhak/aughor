"""A superseded workspace database is released, never closed.

`_shared_base` used to call `stale.close()` on the reasoning that "DuckDB keeps the
database alive while a cursor references it, so a request already mid-flight is not
pulled out from under". The first half is true; the conclusion is not. Closing the
parent invalidates its cursors immediately, whoever is using them.

Both crash modes were seen in CI on one day — a SIGSEGV and a SIGABRT — each with one
thread inside `close()` and another inside `execute`. Intermittent because it needs
the close to land mid-query, and fatal because a dead interpreter takes the whole
process with it: on serverless that is every route at once, which is exactly the
shape of an unexplained `FUNCTION_INVOCATION_FAILED`.

These tests run in a SUBPROCESS. A crash is the failure being tested for, and an
in-process reproduction would take the test runner down with it — which is precisely
how this was found rather than reported.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

# Reading a cursor in a loop while the other side does the thing under test. The
# reader keeps a query IN FLIGHT, which is what makes the race reachable at all.
_PROGRAM = textwrap.dedent("""
    import sys, threading, time
    import duckdb
    from aughor.connectors.file.local_upload import _BASE_DBS, _BASE_LOCK, _shared_base, evict_base

    def build():
        c = duckdb.connect(":memory:")
        c.execute("CREATE TABLE t AS SELECT * FROM range(200000) x(i)")
        return c

    base = _shared_base("c1", None, ("sig", 1), build=build)
    # One cursor PER reader: a DuckDB cursor is not itself thread-safe, and sharing
    # one would crash for a reason that has nothing to do with what is under test.
    # Several readers widen the window in which a close can land mid-query — with a
    # single reader the old behaviour survived roughly one run in three.
    cursors = [base.cursor() for _ in range(6)]
    del base

    stop, errs = threading.Event(), []
    def reader(cur):
        while not stop.is_set():
            try:
                cur.execute("SELECT count(*) FROM t").fetchall()
            except Exception as e:
                errs.append(type(e).__name__)
                return

    threads = [threading.Thread(target=reader, args=(c,), daemon=True) for c in cursors]
    for t in threads:
        t.start()
    time.sleep(0.3)

    ACTION = sys.argv[1]
    if ACTION == "supersede":
        _shared_base("c1", None, ("sig", 2), build=build)   # signature changed
    else:
        evict_base("c1")

    time.sleep(0.6)
    stop.set()
    for t in threads:
        t.join(timeout=3)
    print("OK" if not errs else "READER_BROKE:" + errs[0])
""")


def _run(action: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", _PROGRAM, action],
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("action", ["supersede", "evict"])
def test_a_live_cursor_survives_its_database_being_replaced(action):
    """The claim. Negative exit codes are signals: -11 SIGSEGV, -6 SIGABRT."""
    r = _run(action)

    assert r.returncode == 0, (
        f"{action} killed the interpreter (exit {r.returncode}; "
        f"-11=SIGSEGV, -6=SIGABRT). stderr: {r.stderr[-400:]}")
    assert "OK" in r.stdout, f"the reader broke: {r.stdout.strip()} {r.stderr[-300:]}"


def test_superseding_really_does_replace_the_cached_database():
    """Guard against 'fixing' the crash by never evicting: a changed signature must
    still hand out a NEW database, or the workspace would serve stale files forever."""
    prog = textwrap.dedent("""
        import duckdb
        from aughor.connectors.file.local_upload import _shared_base, evict_base, _BASE_DBS
        mk = lambda: duckdb.connect(":memory:")
        a = _shared_base("c1", None, ("sig", 1), build=mk)
        b = _shared_base("c1", None, ("sig", 1), build=mk)   # same signature → cached
        c = _shared_base("c1", None, ("sig", 2), build=mk)   # changed → rebuilt
        assert a is b, "the cache did not hold for an unchanged signature"
        assert c is not a, "a changed signature did not rebuild"
        assert evict_base("c1") is True
        assert evict_base("c1") is False, "evict must report whether one was held"
        assert "c1" not in _BASE_DBS, "evict left the entry in place"
        print("OK")
    """)
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "OK" in r.stdout, f"{r.stdout} {r.stderr[-400:]}"
