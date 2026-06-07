"""Unit tests for the connection pool (aughor/db/pool.py).

Correctness-critical: a pooled connection must never be shared by two callers at
once, a double-close must not double-return it, stale/unhealthy connections must
be discarded, and opt-outs must bypass pooling entirely.
"""
import time

import aughor.db.pool as poolmod
from aughor.db.pool import ConnectionPool


class FakeConn:
    poolable = True

    def __init__(self):
        self.closed = 0
        self.healthy = True

    def close(self):
        self.closed += 1

    def is_healthy(self):
        return self.healthy


def _pool():
    return ConnectionPool()


def test_reuse_same_object():
    p = _pool()
    a = p.acquire("k", FakeConn)
    a.close()  # swapped → returns to pool
    b = p.acquire("k", FakeConn)
    assert a is b, "an idle connection should be reused"
    assert a.closed == 0, "reused connection must not have been physically closed"


def test_exclusive_checkout_distinct_objects():
    p = _pool()
    a = p.acquire("k", FakeConn)
    b = p.acquire("k", FakeConn)  # not released → must be a different physical conn
    assert a is not b, "concurrent checkouts must not share one connection"


def test_double_close_is_idempotent():
    p = _pool()
    a = p.acquire("k", FakeConn)
    a.close()
    a.close()  # second close must be a no-op, not a second return
    # only one idle entry should exist
    assert p.stats()["keys"].get("k") == 1
    b = p.acquire("k", FakeConn)
    c = p.acquire("k", FakeConn)
    assert b is a and c is not a, "double-close must not let the same object be handed out twice"


def test_ttl_eviction(monkeypatch):
    p = _pool()
    monkeypatch.setattr(poolmod, "_TTL", 0.05)
    a = p.acquire("k", FakeConn)
    a.close()
    time.sleep(0.08)
    b = p.acquire("k", FakeConn)
    assert b is not a, "expired idle connection must not be reused"
    assert a.closed == 1, "expired connection must be physically closed"


def test_max_idle_cap(monkeypatch):
    p = _pool()
    monkeypatch.setattr(poolmod, "_MAX_IDLE", 2)
    conns = [p.acquire("k", FakeConn) for _ in range(3)]
    for c in conns:
        c.close()
    assert p.stats()["keys"].get("k") == 2, "idle bucket must be capped"
    assert sum(c.closed for c in conns) == 1, "the overflow connection must be physically closed"


def test_unhealthy_idle_discarded():
    p = _pool()
    a = p.acquire("k", FakeConn)
    a.healthy = False
    a.close()
    b = p.acquire("k", FakeConn)
    assert b is not a, "an unhealthy idle connection must be discarded"
    assert a.closed == 1


def test_poolable_false_bypasses():
    class NoPool(FakeConn):
        poolable = False

    p = _pool()
    a = p.acquire("k", NoPool)
    a.close()  # real close — not pooled
    assert a.closed == 1
    assert p.stats()["idle_total"] == 0


def test_evict_conn_clears_all_schemas():
    p = _pool()
    a = p.acquire("c1|public", FakeConn)
    b = p.acquire("c1|analytics", FakeConn)
    a.close(); b.close()
    assert p.clear_conn("c1") == 2
    assert a.closed == 1 and b.closed == 1
    assert p.stats()["idle_total"] == 0


def test_disabled_flag_bypasses(monkeypatch):
    p = _pool()
    monkeypatch.setattr(poolmod, "_DISABLED", True)
    a = p.acquire("k", FakeConn)
    a.close()
    assert a.closed == 1, "disabled pool must close immediately"
    assert p.stats()["idle_total"] == 0
