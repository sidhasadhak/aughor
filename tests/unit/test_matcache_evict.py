"""Regression: mat_cache is TTL-on-read, so unread entries never expire on their
own — evict_expired() must actually purge stale rows (and report how many) so the
DuckDB file can't grow unbounded on a long-running server (AUDIT_2026-06-27.md #5).
Hermetic: runs against an in-memory cache DB."""
from __future__ import annotations

import time

import duckdb
import pytest

from aughor.db import matcache


@pytest.fixture
def mem_cache(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute(matcache._DDL)
    monkeypatch.setattr(matcache, "_conn", conn)
    return conn


def _insert(conn, key, conn_id, stored_at):
    conn.execute(
        "INSERT INTO mat_cache VALUES (?, ?, ?, ?, ?, ?)",
        [key, conn_id, "[]", "[]", 0, stored_at],
    )


def test_evict_expired_removes_stale_and_counts(mem_cache):
    now = time.time()
    _insert(mem_cache, "fresh", "c1", now)                # within TTL
    _insert(mem_cache, "stale1", "c1", now - 7_200)       # 2h old
    _insert(mem_cache, "stale2", "c2", now - 10_000)

    evicted = matcache.evict_expired(ttl=3_600)

    assert evicted == 2
    remaining = [r[0] for r in mem_cache.execute("SELECT cache_key FROM mat_cache").fetchall()]
    assert remaining == ["fresh"]


def test_evict_expired_noop_when_all_fresh(mem_cache):
    _insert(mem_cache, "fresh", "c1", time.time())
    assert matcache.evict_expired(ttl=3_600) == 0


def test_invalidate_drops_a_connections_rows(mem_cache):
    now = time.time()
    _insert(mem_cache, "a", "c1", now)
    _insert(mem_cache, "b", "c2", now)
    matcache.invalidate("c1")
    remaining = [r[0] for r in mem_cache.execute("SELECT conn_id FROM mat_cache").fetchall()]
    assert remaining == ["c2"]
