"""Temporal Tier 3 — query cost governor. See aughor/sql/cost.py."""
from aughor.sql.cost import approximate_aggregates, sample_aggregates, govern


def _l(s):
    return (s or "").lower()


# ── approximate_aggregates ────────────────────────────────────────────────────

def test_count_distinct_to_approx():
    out = approximate_aggregates("SELECT COUNT(DISTINCT order_id) AS n FROM t", "duckdb")
    assert "approx_count_distinct(order_id)" in _l(out)


def test_no_distinct_unchanged():
    sql = "SELECT SUM(amount) AS s FROM t"
    assert approximate_aggregates(sql, "duckdb") == sql


def test_approx_noop_on_unsupported_dialect():
    sql = "SELECT COUNT(DISTINCT x) FROM t"
    assert approximate_aggregates(sql, "postgres") == sql


def test_approx_noop_on_garbage():
    assert approximate_aggregates(";;;not sql;;;", "duckdb") == ";;;not sql;;;"


# ── sample_aggregates ─────────────────────────────────────────────────────────

def test_sample_scales_count_and_sum():
    out = sample_aggregates("SELECT COUNT(*) AS c, SUM(x) AS s FROM t", "duckdb", 10.0)
    assert out and "tablesample" in _l(out)
    assert "count(*) * 10" in _l(out) and "sum(x) * 10" in _l(out)


def test_sample_leaves_avg_unscaled():
    out = sample_aggregates("SELECT AVG(x) AS a FROM t", "duckdb", 25.0)
    assert out and "avg(x)" in _l(out) and "* 4" not in _l(out)  # AVG unbiased → not scaled


def test_sample_refuses_joins():
    assert sample_aggregates("SELECT COUNT(*) FROM a JOIN b ON a.id = b.id", "duckdb") is None


def test_sample_refuses_distinct():
    assert sample_aggregates("SELECT COUNT(DISTINCT id) FROM t", "duckdb") is None
    assert sample_aggregates("SELECT approx_count_distinct(id) FROM t", "duckdb") is None


def test_sample_refuses_bad_pct_and_dialect():
    assert sample_aggregates("SELECT COUNT(*) FROM t", "duckdb", 0) is None
    assert sample_aggregates("SELECT COUNT(*) FROM t", "duckdb", 150) is None
    assert sample_aggregates("SELECT COUNT(*) FROM t", "postgres") is None


# ── govern (the decision) ─────────────────────────────────────────────────────

def test_govern_approx_on_by_default():
    g = govern("SELECT COUNT(DISTINCT id) FROM t", dialect="duckdb")
    assert g.approximated and not g.sampled and "approx_count_distinct" in _l(g.sql)
    assert g.is_approximate


def test_govern_no_sampling_below_threshold():
    g = govern("SELECT COUNT(*) FROM t", dialect="duckdb", row_count=1000,
               allow_sampling=True, sample_threshold=5_000_000)
    assert not g.sampled


def test_govern_samples_large_additive_query():
    g = govern("SELECT COUNT(*) AS c, SUM(x) AS s FROM big", dialect="duckdb",
               row_count=10_000_000, allow_sampling=True, sample_threshold=5_000_000)
    assert g.sampled and "tablesample" in _l(g.sql) and "sample" in g.note.lower()


def test_govern_distinct_query_not_sampled_even_when_large():
    # distinct → approx on the FULL table, never sampled (correctness over cost)
    g = govern("SELECT COUNT(DISTINCT id) AS n, SUM(x) AS s FROM big", dialect="duckdb",
               row_count=10_000_000, allow_sampling=True, sample_threshold=5_000_000)
    assert g.approximated and not g.sampled
    assert "tablesample" not in _l(g.sql)


def test_govern_sampling_opt_in():
    # sampling off by default even for a huge additive query
    g = govern("SELECT SUM(x) FROM big", dialect="duckdb", row_count=10_000_000)
    assert not g.sampled
