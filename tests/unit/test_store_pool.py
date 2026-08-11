"""Platform-store connections are reused, and reuse cannot poison a thread.

`connect_store` opened a new connection per store operation. On Postgres that is a
handshake plus CREATE SCHEMA + SET search_path + commit, and a request makes several —
measured at 10.9s for /catalog/tree in production with the function already warm.

Ownership is per THREAD rather than by checkout, because checkout depends on callers
closing and five stores never do. These tests pin both halves: that reuse happens, and
that the states a REUSED transactional connection can be in — aborted, dead, closed by
a caller — cannot break the thread it belongs to.

Pooling alone left production latency still tracking the number of store operations,
because every store replays its `CREATE TABLE IF NOT EXISTS` block on each one — 9
statements for the metastore, 11 for workspace. `ensure_once` amortises that over the
pooled connection; the tests at the bottom pin that it runs once, that it runs AGAIN
whenever a connection is rebuilt or a thread is new, and that SQLite is untouched.
"""
from __future__ import annotations

import threading

import pytest

from aughor.db import store_pool


class _FakePg:
    """Stands in for psycopg2's connection: transaction status + closed flag."""

    def __init__(self, status: int = 0):
        self.closed = 0
        self._status = status
        self.rollbacks = 0

    def get_transaction_status(self):
        return self._status

    def rollback(self):
        self.rollbacks += 1
        self._status = 0          # IDLE

    def close(self):
        self.closed = 1


class _FakeConn:
    built = 0

    def __init__(self, status: int = 0):
        _FakeConn.built += 1
        self.serial = _FakeConn.built
        self._pg = _FakePg(status)

    def close(self):
        self._pg.close()


@pytest.fixture(autouse=True)
def clean_pool(monkeypatch):
    monkeypatch.setattr(store_pool, "_DISABLED", False)
    store_pool.evict_all()
    _FakeConn.built = 0
    yield
    store_pool.evict_all()


def test_second_acquire_reuses_the_first_connection() -> None:
    a = store_pool.acquire("s", _FakeConn)
    b = store_pool.acquire("s", _FakeConn)
    assert a is b
    assert _FakeConn.built == 1, "a second connection was opened for the same key"


def test_distinct_keys_get_distinct_connections() -> None:
    a = store_pool.acquire("schema_a|0", _FakeConn)
    b = store_pool.acquire("schema_b|0", _FakeConn)
    assert a is not b
    assert store_pool.pooled_count() == 2


def test_dict_rows_shape_is_part_of_the_key() -> None:
    """Both shapes share a schema but not a cursor factory, so they must not be
    handed each other's connection."""
    plain = store_pool.acquire("store_x|0", _FakeConn)
    dicty = store_pool.acquire("store_x|1", _FakeConn)
    assert plain is not dicty


def test_a_callers_close_does_not_end_the_connection() -> None:
    """133 call sites close their store connection. Honouring that literally would
    give every well-behaved store zero reuse."""
    conn = store_pool.acquire("s", _FakeConn)
    conn.close()
    assert conn._pg.closed == 0, "close() physically closed a pooled connection"
    assert store_pool.acquire("s", _FakeConn) is conn
    assert _FakeConn.built == 1


def test_an_aborted_transaction_is_rolled_back_not_handed_on() -> None:
    """The hazard reuse introduces: psycopg2 leaves a connection INERROR after a
    failed statement, and every later statement fails until a rollback. A fresh
    connection hid this; reuse would turn one bad query into a broken store."""
    import psycopg2.extensions as ext

    conn = store_pool.acquire("s", _FakeConn)
    conn._pg._status = ext.TRANSACTION_STATUS_INERROR

    again = store_pool.acquire("s", _FakeConn)

    assert again is conn, "a recoverable connection was thrown away"
    assert conn._pg.rollbacks == 1, "the aborted transaction was handed on as-is"
    assert _FakeConn.built == 1


def test_an_open_transaction_is_also_reset() -> None:
    import psycopg2.extensions as ext

    conn = store_pool.acquire("s", _FakeConn)
    conn._pg._status = ext.TRANSACTION_STATUS_INTRANS
    store_pool.acquire("s", _FakeConn)
    assert conn._pg.rollbacks == 1


def test_a_dead_connection_is_replaced() -> None:
    conn = store_pool.acquire("s", _FakeConn)
    conn._pg.closed = 1
    fresh = store_pool.acquire("s", _FakeConn)
    assert fresh is not conn
    assert _FakeConn.built == 2


def test_a_connection_that_will_not_roll_back_is_replaced() -> None:
    import psycopg2.extensions as ext

    conn = store_pool.acquire("s", _FakeConn)
    conn._pg._status = ext.TRANSACTION_STATUS_INERROR

    def _refuse():
        raise RuntimeError("connection is gone")
    conn._pg.rollback = _refuse

    fresh = store_pool.acquire("s", _FakeConn)
    assert fresh is not conn, "an unsalvageable connection was handed out again"


def test_threads_never_share_a_connection() -> None:
    """The safety property exclusive checkout exists to provide — psycopg2
    connections are not thread-safe — held here by ownership instead."""
    seen: dict[int, int] = {}
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        c = store_pool.acquire("s", _FakeConn)
        seen[threading.get_ident()] = c.serial
        store_pool.evict_all()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(seen) == 4
    assert len(set(seen.values())) == 4, (
        f"two threads were handed the same connection: {seen}")


def test_disabled_opts_out_entirely() -> None:
    store_pool._DISABLED = True
    try:
        a = store_pool.acquire("s", _FakeConn)
        b = store_pool.acquire("s", _FakeConn)
        assert a is not b
        assert store_pool.pooled_count() == 0
    finally:
        store_pool._DISABLED = False


def test_sqlite_is_not_pooled(tmp_path, monkeypatch) -> None:
    """A local file open is microseconds; pooling it would add lifetime bugs for no
    gain, so `connect_store` must not route SQLite through the pool."""
    from aughor.db import backend

    monkeypatch.setattr(backend, "is_postgres", lambda: False)
    before = store_pool.pooled_count()
    c1 = backend.connect_store(tmp_path / "a.db")
    c2 = backend.connect_store(tmp_path / "a.db")
    assert c1 is not c2
    assert store_pool.pooled_count() == before
    c1.close()
    c2.close()


def test_connect_store_reuses_on_the_postgres_path(monkeypatch) -> None:
    """The wiring, not just the pool. Locally `is_postgres()` is False, so nothing
    else in the suite reaches this branch — without this test the pooled path ships
    on unit evidence that never touched it.
    """
    from aughor.db import backend

    built = []

    class _StubPg(_FakeConn):
        def __init__(self, url, *, schema, dict_rows=False):
            super().__init__()
            built.append((url, schema, dict_rows))

    monkeypatch.setattr(backend, "is_postgres", lambda: True)
    monkeypatch.setattr(backend, "PgConnection", _StubPg)
    monkeypatch.setenv(backend.DB_URL_ENV, "postgresql://u:p@host/db")
    monkeypatch.setattr(backend, "_schema_name", lambda path, default: "store_test")
    monkeypatch.setattr(backend, "default_for_path", lambda p: p)

    a = backend.connect_store("/tmp/whatever.db")
    b = backend.connect_store("/tmp/whatever.db")

    assert a is b, "connect_store opened a second connection for the same store"
    assert len(built) == 1
    assert built[0][1] == "store_test"

    # row_factory is a different cursor shape and must not share the connection
    c = backend.connect_store("/tmp/whatever.db", row_factory=True)
    assert c is not a
    assert len(built) == 2 and built[1][2] is True


# ── ensure_once: the schema DDL stops being replayed per operation ─────────────

def _ddl(counter: list):
    """A stand-in for a store's `_ensure_schema`, counting its own runs."""
    def _ensure_schema(conn):
        counter.append(conn)
    return _ensure_schema


def test_schema_ddl_runs_once_per_connection() -> None:
    ran: list = []
    conn = _FakeConn()
    assert store_pool.ensure_once(conn, _ddl(ran)) is True
    for _ in range(5):
        store_pool.ensure_once(conn, _ddl(ran))
    assert len(ran) == 1, f"schema DDL replayed {len(ran)}x on one connection"


def test_two_stores_sharing_a_connection_each_get_their_ddl() -> None:
    """The memo is per store, not per connection — one store's CREATE TABLE says
    nothing about another's."""
    a_ran, b_ran = [], []

    def store_a(conn):
        a_ran.append(conn)

    def store_b(conn):
        b_ran.append(conn)

    conn = _FakeConn()
    store_pool.ensure_once(conn, store_a)
    store_pool.ensure_once(conn, store_b)
    store_pool.ensure_once(conn, store_a)
    assert len(a_ran) == 1 and len(b_ran) == 1


def test_a_rebuilt_connection_runs_the_ddl_again() -> None:
    """The memo lives on the connection, so a connection the pool discards and
    rebuilds — a dead socket, an eviction — must not inherit the claim that its
    tables exist. It is a different session against a database that may be new."""
    ran: list = []
    ensure = _ddl(ran)

    first = store_pool.acquire("s", _FakeConn)
    store_pool.ensure_once(first, ensure)
    first._pg.closed = 1                       # server hung up

    second = store_pool.acquire("s", _FakeConn)
    store_pool.ensure_once(second, ensure)

    assert second is not first
    assert len(ran) == 2, "a rebuilt connection skipped its schema DDL"


def test_a_failed_ddl_is_not_remembered_as_done() -> None:
    """Memoizing a CREATE that raised would leave every later operation on this
    connection querying tables that were never created."""
    calls: list = []

    def flaky(conn):
        calls.append(conn)
        if len(calls) == 1:
            raise RuntimeError("CREATE TABLE lost the connection")

    conn = _FakeConn()
    with pytest.raises(RuntimeError):
        store_pool.ensure_once(conn, flaky)
    store_pool.ensure_once(conn, flaky)        # must retry, not assume success
    assert len(calls) == 2


def test_each_thread_ensures_its_own_connection() -> None:
    """Connections are owned per thread, so the memo is too — a second thread's
    connection has never run the DDL, whatever the first thread did."""
    ran: list = []
    ensure = _ddl(ran)
    store_pool.ensure_once(store_pool.acquire("s", _FakeConn), ensure)

    def worker():
        store_pool.ensure_once(store_pool.acquire("s", _FakeConn), ensure)
        store_pool.evict_all()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert len(ran) == 2


def test_sqlite_still_runs_the_ddl_every_time() -> None:
    """SQLite is not pooled, so each operation opens a fresh connection that really
    does need its tables — and a raw sqlite3.Connection has no __dict__ to memoize
    on anyway. Both reasons point the same way: unchanged behaviour."""
    import sqlite3

    ran: list = []
    ensure = _ddl(ran)
    for _ in range(3):
        conn = sqlite3.connect(":memory:")
        assert store_pool.ensure_once(conn, ensure) is True
        conn.close()
    assert len(ran) == 3


def test_the_ddl_outcome_is_counted_for_production_verification() -> None:
    """Deltas, not absolutes — `stats` is a process-wide singleton.

    These two counters are how the next production check reads this change directly,
    instead of inferring it from endpoint arithmetic the way the cost it fixes had to
    be found.
    """
    from aughor.stats import stats

    def count(k: str) -> int:
        return stats.snapshot()["counters"].get(f"store.schema_ddl.{k}", 0)

    ran0, skipped0 = count("ran"), count("skipped")
    conn = _FakeConn()
    ensure = _ddl([])
    for _ in range(3):
        store_pool.ensure_once(conn, ensure)

    assert count("ran") - ran0 == 1
    assert count("skipped") - skipped0 == 2


def test_a_real_store_stops_replaying_its_ddl_across_operations(monkeypatch) -> None:
    """The shipped claim, through the real wiring rather than the helper alone:
    three metastore operations on the Postgres path, one CREATE TABLE block.

    Locally `is_postgres()` is False, so nothing else in the suite reaches this
    branch — without this test the change ships on evidence that never touched it.
    """
    import sqlite3

    from aughor.db import backend
    from aughor.metastore import store as ms

    backing = sqlite3.connect(":memory:")
    backing.row_factory = sqlite3.Row

    class _StubPg:
        """Postgres-shaped: a plain object (so it can carry the memo) over real SQL."""

        def __init__(self, url, *, schema, dict_rows=False):
            self._pg = _FakePg()

        def execute(self, sql, params=()):
            return backing.execute(sql, params)

        def executemany(self, sql, seq):
            return backing.executemany(sql, seq)

        def commit(self):
            return backing.commit()

        def close(self):
            pass

    monkeypatch.setattr(backend, "is_postgres", lambda: True)
    monkeypatch.setattr(backend, "PgConnection", _StubPg)
    monkeypatch.setenv(backend.DB_URL_ENV, "postgresql://u:p@h/d")
    monkeypatch.setattr(backend, "_schema_name", lambda path, default: "store_metastore_test")
    monkeypatch.setattr(backend, "default_for_path", lambda p: p)

    ran: list = []
    real_ensure = ms._ensure_schema

    def counting(conn):
        ran.append(conn)
        real_ensure(conn)

    monkeypatch.setattr(ms, "_ensure_schema", counting)

    ms.upsert_catalog("c1", name="one")
    ms.upsert_catalog("c2", name="two")
    assert len(ms.list_catalogs()) == 2, "the stubbed store did not actually work"

    assert len(ran) == 1, (
        f"schema DDL ran {len(ran)}x across 3 store operations — it is still per-operation")
