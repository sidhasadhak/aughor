"""Platform-store connections are reused, and reuse cannot poison a thread.

`connect_store` opened a new connection per store operation. On Postgres that is a
handshake plus CREATE SCHEMA + SET search_path + commit, and a request makes several —
measured at 10.9s for /catalog/tree in production with the function already warm.

Ownership is per THREAD rather than by checkout, because checkout depends on callers
closing and five stores never do. These tests pin both halves: that reuse happens, and
that the states a REUSED transactional connection can be in — aborted, dead, closed by
a caller — cannot break the thread it belongs to.
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
