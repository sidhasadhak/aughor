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


def test_chasm_splits_a_single_satellite_where_into_its_cte():
    # FAN-b breadth: a predicate on one aggregated satellite is now pushed into that
    # satellite's pre-agg CTE (was a bail). The lineitem filter lands in _s_l, not the outer.
    rw = _chasm(_CHASM_SQL + " WHERE l.l_quantity > 10")
    assert rw is not None
    low = rw.lower()
    assert low.count("group by") == 2
    # the predicate rides inside the lineitem CTE (alias-stripped); with no hub predicate the
    # outer query has no WHERE, so any WHERE present is the pushed-down CTE filter.
    assert "where l_quantity > 10" in low
    assert "inner join _s_l" in low and "inner join _s_ps" in low   # outer is a pure CTE star-join


def test_chasm_splits_hub_and_satellite_predicates():
    # AND of a hub predicate + a satellite predicate: hub stays outer, satellite pushes in.
    rw = _chasm(_CHASM_SQL + " WHERE p.p_mfgr = 'M1' AND l.l_quantity > 10")
    assert rw is not None
    low = rw.lower()
    assert "p_mfgr = 'm1'" in low and "l_quantity > 10" in low


def test_chasm_still_bails_on_unsplittable_where():
    # cross-table predicate (one conjunct touches two tables) → cannot attribute → bail
    assert _chasm(_CHASM_SQL + " WHERE l.l_quantity > ps.ps_availqty") is None
    # an OR spanning two satellites is a single conjunct touching both → bail
    assert _chasm(_CHASM_SQL + " WHERE l.l_quantity > 10 OR ps.ps_availqty > 5") is None
    # an unqualified column can't be attributed to a table → bail
    assert _chasm(_CHASM_SQL + " WHERE l_quantity > 10") is None


def test_chasm_satellite_where_is_numerically_correct():
    # The real proof: pushing the filter into the CTE must equal the TRUE filtered un-fanned
    # value, not the inflated cross-product. Runs on DuckDB.
    import duckdb
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE orders(order_id INT)"); con.execute("INSERT INTO orders VALUES (1),(2)")
    con.execute("CREATE TABLE clicks(order_id INT, source VARCHAR, n_clicks INT)")
    con.execute("INSERT INTO clicks VALUES (1,'google',10),(1,'google',20),(1,'bing',5),(2,'google',7)")
    con.execute("CREATE TABLE impressions(order_id INT, n_imp INT)")
    con.execute("INSERT INTO impressions VALUES (1,100),(1,200),(2,300),(2,400),(2,500)")
    tc = {"orders": ["order_id"], "clicks": ["order_id", "source", "n_clicks"],
          "impressions": ["order_id", "n_imp"]}
    sql = ("SELECT SUM(c.n_clicks) AS clicks, SUM(i.n_imp) AS imps "
           "FROM orders o JOIN clicks c ON o.order_id=c.order_id "
           "JOIN impressions i ON o.order_id=i.order_id WHERE c.source = 'google'")
    assert con.execute(sql).fetchone() == (81, 1800)         # the fanned (wrong) value
    rw = build_chasm_fanout_rewrite(sql, detect_fanout(sql, tc))
    assert rw is not None
    assert con.execute(rw).fetchone() == (37, 1500)          # exact filtered un-fanned truth


def test_chasm_rewrites_avg_as_ratio_of_sums():
    # AVG over a chasm is now decomposed into per-satellite SUM(x)+COUNT(x), divided in
    # the outer query (was a bail). High-precision: it must produce a NULLIF-guarded ratio.
    rw = _chasm("SELECT AVG(l.l_quantity), SUM(ps.ps_availqty) FROM part p JOIN lineitem l ON p.p_partkey = l.l_partkey JOIN partsupp ps ON p.p_partkey = ps.ps_partkey")
    assert rw is not None
    low = rw.lower()
    assert "nullif" in low and low.count("group by") == 2
    assert "count(l_quantity)" in low and "sum(l_quantity)" in low   # the decomposition


def test_chasm_avg_decomposition_is_numerically_correct():
    # The real proof: a fanned AVG is biased when a GROUP's hubs have different fan-out
    # multiplicities; the rewrite must equal the TRUE un-fanned mean. Runs on DuckDB.
    import duckdb
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE campaigns(campaign_id INT, name VARCHAR)")
    con.execute("INSERT INTO campaigns VALUES (1,'A'),(2,'A'),(3,'B')")
    con.execute("CREATE TABLE clicks(click_id INT, campaign_id INT, x DOUBLE)")
    con.execute("INSERT INTO clicks VALUES (1,1,10),(2,1,20),(3,2,30),(4,3,40)")
    con.execute("CREATE TABLE impressions(impression_id INT, campaign_id INT, y DOUBLE)")
    con.execute("INSERT INTO impressions VALUES (1,1,100),(2,1,200),(3,1,300),(4,2,400),(5,3,500)")
    tc = {"campaigns": ["campaign_id", "name"],
          "clicks": ["click_id", "campaign_id", "x"],
          "impressions": ["impression_id", "campaign_id", "y"]}
    sql = ("SELECT ca.name, AVG(c.x) AS avg_x, SUM(i.y) AS sum_y FROM campaigns ca "
           "JOIN clicks c ON c.campaign_id=ca.campaign_id "
           "JOIN impressions i ON i.campaign_id=ca.campaign_id GROUP BY ca.name ORDER BY ca.name")
    rw = build_chasm_fanout_rewrite(sql, detect_fanout(sql, tc))
    assert rw is not None
    fanned = con.execute(sql).fetchall()
    rewritten = con.execute(rw).fetchall()
    true = [("A", 20.0, 1000.0), ("B", 40.0, 500.0)]   # AVG(x) per name from clicks alone; SUM(y) from impressions alone
    assert rewritten == true          # the rewrite recovers the un-fanned values
    assert fanned != true             # and the original fanned query was genuinely wrong


def test_chasm_bails_on_count_star():
    assert _chasm("SELECT COUNT(*), SUM(ps.ps_availqty) FROM part p JOIN lineitem l ON p.p_partkey = l.l_partkey JOIN partsupp ps ON p.p_partkey = ps.ps_partkey") is None


def test_chasm_bails_on_outer_join():
    assert _chasm("SELECT SUM(l.l_quantity), SUM(ps.ps_availqty) FROM part p LEFT JOIN lineitem l ON p.p_partkey = l.l_partkey JOIN partsupp ps ON p.p_partkey = ps.ps_partkey") is None


def test_defan_dispatches_by_kind():
    parent = "SELECT SUM(o.o_totalprice) FROM orders o JOIN lineitem l ON o.o_orderkey = l.l_orderkey"
    assert defan(parent, detect_fanout(parent, TC)) is not None          # parent_fanout
    assert defan(_CHASM_SQL, detect_fanout(_CHASM_SQL, CHASM_TC)) is not None  # chasm
    assert defan("SELECT 1", None) is None
