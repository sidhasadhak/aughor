"""Global-ratio plausibility guard — the conditioned-denominator catch (fix 1+2, 2026-07-09).

Deep-Analysis audit finding (inv1, CATASTROPHIC): a "why is the Fragrance refund RATE so high?"
scan generated per-dimension SQL that used the EVENT table (refunds) as the JOIN BASE and
INNER-joined the population (revenue) onto it — so every segment's denominator counted only orders
that HAD a refund. The scan reported a ~73% refund rate (true ≈ 10%) and told the user their premise
was INVERTED. No fan-out/saturation guard caught it (values sit inside [0,100], no row multiplication).
This guard computes the metric's TRUE global level independently — each aggregate over its own full
table — and suppresses the ratio when every segment is implausibly far above it.
See _global_ratio_plausibility_guard in aughor/agent/investigate.py.
"""
import duckdb
import pytest

from aughor.agent.investigate import (
    _parse_ratio_sources,
    _independent_global_ratio,
    _global_ratio_plausibility_guard,
)

INV1_METRIC_SQL = (
    "SUM(analytics.refunds.refund_amount_usd) / "
    "NULLIF(SUM(analytics.order_items.line_revenue_usd), 0) * 100"
)


class _Shim:
    """Minimal conn.execute(tag, sql) -> obj with .rows/.columns/.error over a read-only DuckDB."""

    def __init__(self, path):
        self._c = duckdb.connect(path, read_only=True)

    def execute(self, tag, sql):
        r = type("R", (), {})()
        try:
            cur = self._c.execute(sql)
            r.rows = cur.fetchall()
            r.columns = [d[0] for d in cur.description]
            r.error = None
        except Exception as e:  # noqa: BLE001
            r.rows, r.columns, r.error = [], [], str(e)
        return r


@pytest.fixture
def conn(tmp_path):
    """100 orders @ $100 revenue; first 20 refunded @ $50. True global refund rate = 1000/10000 = 10%."""
    p = str(tmp_path / "bc.duckdb")
    c = duckdb.connect(p)
    c.execute("CREATE SCHEMA analytics")
    c.execute("CREATE TABLE analytics.order_items(order_id INT, line_revenue_usd DOUBLE)")
    c.execute("CREATE TABLE analytics.refunds(order_id INT, refund_amount_usd DOUBLE)")
    c.execute("INSERT INTO analytics.order_items SELECT range, 100.0 FROM range(100)")
    c.execute("INSERT INTO analytics.refunds SELECT range, 50.0 FROM range(20)")
    c.close()
    return _Shim(p)


# ── parser ─────────────────────────────────────────────────────────────────────

def test_parses_qualified_cross_table_ratio():
    s = _parse_ratio_sources(INV1_METRIC_SQL)
    assert s is not None
    assert s["num_table"] == "analytics.refunds" and s["num_col"] == "refund_amount_usd"
    assert s["den_table"] == "analytics.order_items" and s["den_col"] == "line_revenue_usd"
    assert s["scale"] == 100.0


def test_parser_rejects_same_table_ratio():
    # same-table ratio is not a cross-table population rate → no conditioned-denominator risk
    assert _parse_ratio_sources("SUM(orders.a) / SUM(orders.b)") is None


def test_parser_rejects_non_ratio_and_ambiguous():
    assert _parse_ratio_sources("SUM(orders.revenue)") is None
    assert _parse_ratio_sources("SUM(a.x)/SUM(b.y)/SUM(c.z)") is None   # >1 division


# ── independent global ─────────────────────────────────────────────────────────

def test_independent_global_is_population_level(conn):
    g = _independent_global_ratio(conn, _parse_ratio_sources(INV1_METRIC_SQL))
    assert g == pytest.approx(10.0, abs=0.01)


# ── the guard ──────────────────────────────────────────────────────────────────

def _findings(vals):
    return [{
        "columns": ["segment", "metric_total"],
        "rows": [[f"s{i}", str(v)] for i, v in enumerate(vals)],
        "key_numbers": [{"label": "x", "value": f"{vals[0]}%"}],
        "interpretation": "original interpretation",
        "chart_type": "bar_horizontal",
    }]


def test_guard_fires_on_conditioned_denominator(conn):
    """Every segment ~50% while the true global is 10% → systematic inflation → suppress."""
    findings = _findings([50.0, 48.0, 52.0, 49.0])
    cav = _global_ratio_plausibility_guard(findings, conn, INV1_METRIC_SQL, "refund rate")
    assert cav is not None
    assert "10.0%" in cav                       # states the TRUE global
    assert "conditioned denominator" in cav.lower()


def test_guard_silent_on_plausible_spread(conn):
    """A real spread around the 10% global (one high segment, others near it) must NOT fire —
    that is legitimate signal, not a computation artifact."""
    findings = _findings([8.0, 14.0, 11.0, 9.0, 22.0])   # min 8% < 2.5×10% = 25%
    assert _global_ratio_plausibility_guard(findings, conn, INV1_METRIC_SQL, "refund rate") is None


def test_guard_suppresses_numbers_when_it_fires(conn):
    """When it fires, the corrupted key_numbers are cleared and the chart dropped, so the artifact
    numbers cannot reach the synthesis headline."""
    findings = _findings([73.0, 79.0, 85.0])
    from aughor.agent.investigate import _suppress_fanned_ratio
    cav = _global_ratio_plausibility_guard(findings, conn, INV1_METRIC_SQL, "refund rate")
    assert cav is not None
    # mirror the wiring: guard returns caveat; caller suppresses
    _suppress_fanned_ratio(findings, "refund rate", cav)
    assert findings[0]["key_numbers"] == []
    assert findings[0]["chart_type"] == "none"


def test_guard_noop_when_global_unavailable(tmp_path):
    """If the true global can't be computed (missing table), the guard must no-op, never crash."""
    p = str(tmp_path / "empty.duckdb")
    duckdb.connect(p).close()
    shim = _Shim(p)
    findings = _findings([50.0, 60.0])
    assert _global_ratio_plausibility_guard(findings, shim, INV1_METRIC_SQL, "refund rate") is None
