"""Deterministic parent-fanout de-fan (build_parent_fanout_rewrite).

Fan-out (SUM of a parent measure across a one-to-many join) is the #1 model-
invariant correctness failure — it over-counts (TPC-H: 5x; ecommerce: 2.4x). The
LLM-rewrite path is only ~20% reliable (it returns plausible CTEs that STILL
double-count), so the de-fan must be deterministic: DISTINCT(parent-key, measure)
sums each parent once. High-precision — it bails (None) on any shape it can't
prove correct, and the caller dry-runs the result before adopting it.
"""
from aughor.sql.fanout import detect_fanout, build_parent_fanout_rewrite, build_chasm_fanout_rewrite, defan

# orders (parent, root "order") one-to-many lineitem (child) — the classic case.
TC = {"orders": ["o_orderkey", "o_orderstatus", "o_totalprice"],
      "lineitem": ["l_orderkey", "l_shipmode", "l_quantity"]}


def _rewrite(sql):
    ff = detect_fanout(sql, TC)
    return build_parent_fanout_rewrite(sql, ff) if ff else None


def test_scalar_sum_is_deduped():
    rw = _rewrite("SELECT SUM(o.o_totalprice) FROM orders o JOIN lineitem l ON o.o_orderkey = l.l_orderkey")
    assert rw is not None
    low = rw.lower()
    assert "distinct" in low
    assert "o_orderkey" in low          # deduped by the parent join key
    assert "_dedup" in low


def test_explicit_alias_preserved():
    rw = _rewrite("SELECT SUM(o.o_totalprice) AS total_revenue FROM orders o JOIN lineitem l ON o.o_orderkey = l.l_orderkey")
    assert rw is not None and "total_revenue" in rw


def test_where_filter_is_preserved():
    rw = _rewrite("SELECT SUM(o.o_totalprice) FROM orders o JOIN lineitem l ON o.o_orderkey = l.l_orderkey WHERE l.l_shipmode = 'TRUCK'")
    assert rw is not None and "truck" in rw.lower()


def test_parent_dim_group_rewrites():
    rw = _rewrite("SELECT o.o_orderstatus, SUM(o.o_totalprice) FROM orders o JOIN lineitem l ON o.o_orderkey = l.l_orderkey GROUP BY o.o_orderstatus")
    assert rw is not None
    assert "group by" in rw.lower() and "o_orderstatus" in rw.lower()


def test_child_dim_group_bails():
    # Grouping by a CHILD column makes the parent measure ambiguous → must NOT rewrite.
    assert _rewrite("SELECT l.l_shipmode, SUM(o.o_totalprice) FROM orders o JOIN lineitem l ON o.o_orderkey = l.l_orderkey GROUP BY l.l_shipmode") is None


def test_count_star_bails():
    assert _rewrite("SELECT COUNT(*) FROM orders o JOIN lineitem l ON o.o_orderkey = l.l_orderkey") is None


def test_non_parent_fanout_finding_bails():
    # A finding that isn't parent_fanout (or None) yields no rewrite.
    assert build_parent_fanout_rewrite("SELECT 1", None) is None  # type: ignore[arg-type]


# ── Chasm (≥2 satellites of one hub) ──────────────────────────────────────────
# part (hub, root "part") with two many-side satellites: lineitem + partsupp.
CHASM_TC = {"part": ["p_partkey", "p_mfgr"],
            "lineitem": ["l_orderkey", "l_partkey", "l_quantity"],
            "partsupp": ["ps_partkey", "ps_suppkey", "ps_availqty"]}
_CHASM_SQL = ("SELECT SUM(l.l_quantity) AS lqty, SUM(ps.ps_availqty) AS psqty "
              "FROM part p JOIN lineitem l ON p.p_partkey = l.l_partkey "
              "JOIN partsupp ps ON p.p_partkey = ps.ps_partkey")


def _chasm(sql):
    ff = detect_fanout(sql, CHASM_TC)
    return build_chasm_fanout_rewrite(sql, ff) if ff else None


def test_chasm_preaggregates_each_satellite():
    rw = _chasm(_CHASM_SQL)
    assert rw is not None
    low = rw.lower()
    assert low.count("group by") == 2          # one pre-agg per satellite
    assert "with" in low and "_s_l" in low and "_s_ps" in low


def test_chasm_count_supported():
    rw = _chasm("SELECT COUNT(l.l_orderkey), COUNT(ps.ps_suppkey) FROM part p JOIN lineitem l ON p.p_partkey = l.l_partkey JOIN partsupp ps ON p.p_partkey = ps.ps_partkey")
    assert rw is not None and rw.lower().count("group by") == 2


def test_chasm_bails_on_satellite_where():
    assert _chasm(_CHASM_SQL + " WHERE l.l_quantity > 10") is None


def test_chasm_bails_on_avg():
    assert _chasm("SELECT AVG(l.l_quantity), SUM(ps.ps_availqty) FROM part p JOIN lineitem l ON p.p_partkey = l.l_partkey JOIN partsupp ps ON p.p_partkey = ps.ps_partkey") is None


def test_chasm_bails_on_count_star():
    assert _chasm("SELECT COUNT(*), SUM(ps.ps_availqty) FROM part p JOIN lineitem l ON p.p_partkey = l.l_partkey JOIN partsupp ps ON p.p_partkey = ps.ps_partkey") is None


def test_chasm_bails_on_outer_join():
    assert _chasm("SELECT SUM(l.l_quantity), SUM(ps.ps_availqty) FROM part p LEFT JOIN lineitem l ON p.p_partkey = l.l_partkey JOIN partsupp ps ON p.p_partkey = ps.ps_partkey") is None


def test_defan_dispatches_by_kind():
    parent = "SELECT SUM(o.o_totalprice) FROM orders o JOIN lineitem l ON o.o_orderkey = l.l_orderkey"
    assert defan(parent, detect_fanout(parent, TC)) is not None          # parent_fanout
    assert defan(_CHASM_SQL, detect_fanout(_CHASM_SQL, CHASM_TC)) is not None  # chasm
    assert defan("SELECT 1", None) is None
