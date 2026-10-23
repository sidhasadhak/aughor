"""The materialisation cache's one DuckDB handle is used from every worker thread — under a lock.

Live, 2026-10-15 17:37 UTC: the API died with a segmentation fault inside `_duckdb` on a worker
thread (macOS crash report `python3.11-2026-10-15-193753.ips`) while sixteen `/query/run` calls
measured the LuxExperience dashboard at once, each reading and writing this cache; the Briefing desk's
metric moves and the monitors scheduler's eviction share the same handle. A DuckDB connection object
is not safe for concurrent use from two threads. Every public function now holds `_LOCK` around its
use of `_db()`, and this holds it to that: a handle used off the lock is the crash coming back.
"""
from __future__ import annotations

import threading

import pytest

from aughor.control_plane.contracts.execution import QueryResult
from aughor.db import matcache as M


def _res(i: int) -> QueryResult:
    return QueryResult(hypothesis_id=f"h{i}", sql=f"SELECT {i}", columns=["n"], rows=[[i]], row_count=1)


@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "_CACHE_PATH", tmp_path / "mat_cache.duckdb")
    monkeypatch.setattr(M, "_conn", None)
    yield
    if M._conn is not None:
        M._conn.close()
    monkeypatch.setattr(M, "_conn", None)


def test_every_use_of_the_handle_holds_the_lock(monkeypatch):
    real = M._db
    seen: list[str] = []

    def guarded():
        assert M._LOCK.locked(), "the cache's DuckDB handle was taken without the lock"
        seen.append("ok")
        return real()
    monkeypatch.setattr(M, "_db", guarded)
    M.put_cache("c1", "SELECT 1", _res(1))
    assert M.get_cached("c1", "SELECT 1").rows == [[1]]
    assert M.get_cached_entry("c1", "SELECT 1") is not None
    assert M.get_cached("c1", "SELECT 2") is None
    M.evict_expired(ttl=0.0)
    M.invalidate("c1")
    assert M.cache_stats()["entries"] == 0
    assert len(seen) >= 6                                   # each public function went through it
    assert not M._LOCK.locked()                             # and let go


def test_sixteen_threads_read_and_write_at_once_and_each_reads_its_own_rows():
    """The shape of the crash: many workers hammering one handle. Each thread writes its own
    entries and reads them back exact; nothing raises, nothing is lost or crossed."""
    errors: list[BaseException] = []

    def worker(t: int) -> None:
        try:
            for i in range(40):
                sql = f"SELECT {t}, {i}"
                M.put_cache("conn", sql, QueryResult(hypothesis_id="h", sql=sql, columns=["t", "i"],
                                                     rows=[[t, i]], row_count=1))
                got = M.get_cached("conn", sql)
                assert got is not None and got.rows == [[t, i]], (t, i, got and got.rows)
                if i % 10 == 0:
                    M.evict_expired()
                    M.cache_stats()
        except BaseException as exc:  # noqa: BLE001 — collected, reported by the test
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(16)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert not errors, errors[:3]
    assert M.cache_stats()["entries"] == 16 * 40
