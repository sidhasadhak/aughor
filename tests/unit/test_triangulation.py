"""Triangulation — independent-path agreement (Bet 0, increment 0-III, 2026-06-27).

A raw-COUNT rate over a join is trustworthy only if its COUNT(DISTINCT) twin agrees.
count_distinct_variant builds the twin; rate_columns_diverge compares the rate column;
the verification manifest surfaces the outcome and divergence tanks data_trust.
See aughor/sql/fanout.py, aughor/agent/explore.py.
"""
from aughor.sql.fanout import count_distinct_variant, rate_columns_diverge
from aughor.agent.explore import _build_verification_manifest
from aughor.agent.state import QueryResult, StatResult

SWISS = ("SELECT COUNT(r.refund_id) / NULLIF(COUNT(t.ticket_id), 0) AS refund_rate "
         "FROM tickets t LEFT JOIN refunds r ON t.ticket_id = r.ticket_id")


def test_variant_wraps_both_counts_in_distinct():
    out = count_distinct_variant(SWISS)
    assert out is not None
    low = out.lower()
    assert "count(distinct r.refund_id)" in low.replace(" ", "").replace("count(distinct", "count(distinct ") or "distinct" in low
    assert low.count("distinct") >= 2


def test_variant_none_when_no_count_ratio():
    assert count_distinct_variant("SELECT SUM(x) FROM t") is None


def test_already_distinct_is_not_rewritten():
    sql = ("SELECT COUNT(DISTINCT a) / NULLIF(COUNT(DISTINCT b), 0) AS rate "
           "FROM t JOIN u ON t.id = u.tid")
    assert count_distinct_variant(sql) is None


def test_diverge_detects_disagreement():
    cols = ["seg", "refund_rate"]
    a = [["x", 0.05], ["y", 0.06]]
    b = [["x", 0.025], ["y", 0.061]]   # x diverges by 0.025 > tol
    assert rate_columns_diverge(cols, a, cols, b) is True


def test_agree_within_tolerance():
    cols = ["seg", "refund_rate"]
    a = [["x", 0.0500], ["y", 0.0600]]
    b = [["x", 0.0505], ["y", 0.0598]]
    assert rate_columns_diverge(cols, a, cols, b) is False


def test_diverge_none_when_no_rate_column_or_shape_mismatch():
    assert rate_columns_diverge(["a", "b"], [[1, 2]], ["a", "b"], [[1, 2]]) is None
    assert rate_columns_diverge(["rate"], [[0.1]], ["rate"], [[0.1], [0.2]]) is None


def _qr(stats=None):
    return QueryResult(hypothesis_id="Q1", sql="x", columns=["a"], rows=[[1]], row_count=1,
                       stats=stats or [])


def test_manifest_surfaces_divergence_and_tanks_trust():
    state = {
        "verification_checks": ["temporal_prune:0", "join_value_domain", "cardinality_guard",
                                "triangulation:diverge"],
        "query_history": [_qr()],
    }
    m = _build_verification_manifest(state)
    tri = next(c for c in m.checks if c.name == "triangulation")
    assert tri.status == "ran" and "DISAGREE" in (tri.detail or "")
    assert m.data_trust <= 0.6
    assert any("FAILED triangulation" in s for s in m.signals)


def test_manifest_records_agreement():
    state = {
        "verification_checks": ["temporal_prune:0", "join_value_domain", "cardinality_guard",
                                "triangulation:agree"],
        "query_history": [_qr(stats=[StatResult(type="uniformity", interpretation="x", is_significant=False)])],
    }
    m = _build_verification_manifest(state)
    tri = next(c for c in m.checks if c.name == "triangulation")
    assert tri.status == "ran" and "agrees" in (tri.detail or "")
