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


def test_huge_table_routes_through_the_hll_probe(monkeypatch):
    # MinHash/HLL for huge tables — an edge touching a table above the threshold must use the
    # cheap HLL estimator, NOT the exact sampled probe.
    used = {"exact": 0, "hll": 0}
    monkeypatch.setattr(jg, "_probe_overlap", lambda *a: (used.__setitem__("exact", used["exact"] + 1), 0.9)[1])
    monkeypatch.setattr(jg, "_probe_overlap_hll", lambda *a: (used.__setitem__("hll", used["hll"] + 1), 0.95)[1])
    joins = [{"t1": "big_facts", "c1": "k_id", "t2": "dim", "c2": "k_id"}]
    v, r = jg.verify_join_edges(object(), joins, table_rows={"big_facts": 5_000_000}, hll_min_rows=1_000_000)
    assert used["hll"] == 2 and used["exact"] == 0   # both directions via HLL
    assert len(v) == 1 and not r
    # below threshold → exact path
    used["hll"] = used["exact"] = 0
    jg.verify_join_edges(object(), joins, table_rows={"big_facts": 1000}, hll_min_rows=1_000_000)
    assert used["exact"] == 2 and used["hll"] == 0


def test_seed_verified_cache_from_phase4_results():
    jg._VERIFIED_JOIN_CACHE.clear()
    joins = [
        {"t1": "orders", "c1": "customer_id", "t2": "customers", "c2": "customer_id"},
        {"t1": "orders", "c1": "promo_id", "t2": "promos", "c2": "promo_id"},
    ]
    verifs = [
        {"from_table": "orders", "from_col": "customer_id", "to_table": "customers",
         "to_col": "customer_id", "verified": True, "orphan_count": 0, "fk_distinct": 100},
        {"from_table": "orders", "from_col": "promo_id", "to_table": "promos",
         "to_col": "promo_id", "verified": False, "orphan_count": 95, "fk_distinct": 100},
    ]
    verified, rejected = jg.seed_verified_cache("connZ", joins, verifs)
    assert [(v.t1, v.t2) for v in verified] == [("orders", "customers")]
    assert [(r.t1, r.t2) for r in rejected] == [("orders", "promos")]   # mostly-orphaned → do not join
    # a later catalog build hits the seeded cache (no conn needed)
    sig = tuple(sorted((j["t1"], j["c1"], j["t2"], j["c2"]) for j in joins))
    assert ("connZ", sig) in jg._VERIFIED_JOIN_CACHE
