"""Build-time joinability — value-verify name-inferred join edges so a value-disjoint
coincidence is demoted to DO-NOT-JOIN before generation (prevention, not recovery).
Hermetic: the overlap probe is stubbed to drive the verdict deterministically."""
from __future__ import annotations

import aughor.sql.join_guard as jg
from aughor.sql.join_guard import VerifiedJoin, render_verified_joins


def test_verify_rejects_value_disjoint_keeps_real_fk(monkeypatch):
    # directed containment per (ta,ca → tb,cb): a real FK is contained; a name coincidence isn't
    overlaps = {
        ("orders", "customer_id", "customers", "customer_id"): 0.98,
        ("customers", "customer_id", "orders", "customer_id"): 0.40,
        ("orders", "customer_id", "campaigns", "campaign_id"): 0.0,
        ("campaigns", "campaign_id", "orders", "customer_id"): 0.0,
    }
    monkeypatch.setattr(jg, "_probe_overlap",
                        lambda conn, ta, ca, tb, cb: overlaps.get((ta, ca, tb, cb)))
    joins = [
        {"t1": "orders", "c1": "customer_id", "t2": "customers", "c2": "customer_id", "match": "exact"},
        {"t1": "orders", "c1": "customer_id", "t2": "campaigns", "c2": "campaign_id", "match": "exact"},
    ]
    verified, rejected = jg.verify_join_edges(object(), joins)
    assert [(v.t1, v.t2) for v in verified] == [("orders", "customers")]
    assert [(r.t1, r.t2) for r in rejected] == [("orders", "campaigns")]
    assert verified[0].overlap == 0.98 and rejected[0].overlap == 0.0


def test_verify_is_fail_open_when_unprobeable(monkeypatch):
    # a probe that can't run (None) must KEEP the edge — never reject on inability to check
    monkeypatch.setattr(jg, "_probe_overlap", lambda *a: None)
    verified, rejected = jg.verify_join_edges(object(), [{"t1": "a", "c1": "x_id", "t2": "b", "c2": "x_id"}])
    assert len(verified) == 1 and not rejected
    assert verified[0].overlap == -1.0


def test_render_lists_use_and_do_not_join():
    out = render_verified_joins(
        [VerifiedJoin("orders", "customer_id", "customers", "customer_id", 0.98)],
        [VerifiedJoin("orders", "customer_id", "campaigns", "campaign_id", 0.0)],
    )
    assert "orders.customer_id = customers.customer_id" in out
    assert "DO NOT JOIN" in out and "orders.customer_id ≠ campaigns.campaign_id" in out
    assert "0% value overlap" in out


def test_verified_join_edges_caches(monkeypatch):
    calls = {"n": 0}

    def _probe(conn, ta, ca, tb, cb):
        calls["n"] += 1
        return 0.9

    monkeypatch.setattr(jg, "_probe_overlap", _probe)
    jg._VERIFIED_JOIN_CACHE.clear()
    joins = [{"t1": "a", "c1": "k_id", "t2": "b", "c2": "k_id"}]
    jg.verified_join_edges(object(), joins, cache_key="conn1")
    n1 = calls["n"]
    assert n1 > 0
    jg.verified_join_edges(object(), joins, cache_key="conn1")   # cache hit → no new probes
    assert calls["n"] == n1
