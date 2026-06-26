"""No-signal honesty guard wiring (2026-06-26).

When multiple sub-questions find the metric uniform across their segments, synthesis
must be told to stop attributing the (noise) spread to drivers. _uniform_dimensions
counts those flagged dimensions from query_history (the stats are attached by
_attach_stats during execution). See aughor/agent/explore.py.
"""
from aughor.agent.explore import _uniform_dimensions
from aughor.agent.state import QueryResult, StatResult  # pydantic serialization model


def _qr(hid, stats):
    return QueryResult(hypothesis_id=hid, sql="SELECT 1", columns=["a"], rows=[[1]],
                       row_count=1, stats=stats)


def test_counts_uniform_dimensions():
    hist = [
        _qr("Q1", [StatResult(type="uniformity", interpretation="UNIFORM / NO SIGNAL: delay", is_significant=False)]),
        _qr("Q2", [StatResult(type="uniformity", interpretation="UNIFORM / NO SIGNAL: route", is_significant=False)]),
        _qr("Q3", [StatResult(type="trend", interpretation="upward", is_significant=True)]),
    ]
    dims = _uniform_dimensions(hist)
    assert len(dims) == 2
    assert all("NO SIGNAL" in d for d in dims)


def test_significant_uniformity_result_is_not_counted():
    # A rate-by-segment result where a segment DID differ is signal, not no-signal.
    hist = [
        _qr("Q1", [StatResult(type="uniformity", interpretation="2 of 5 segments differ", is_significant=True)]),
    ]
    assert _uniform_dimensions(hist) == []


def test_empty_history_is_safe():
    assert _uniform_dimensions([]) == []
    assert _uniform_dimensions(None) == []


def test_attach_stats_actually_attaches_uniformity_stat():
    # Regression: _attach_stats called analyze_query_result with the wrong arity, so the
    # whole stats feature was dead in explore. This proves it's live end-to-end now AND
    # that the dataclass→pydantic StatResult bridge validates.
    from aughor.agent.explore import _attach_stats
    qr = QueryResult(
        hypothesis_id="Q1",
        sql="SELECT segment, total_tickets, refund_rate FROM t GROUP BY segment",
        columns=["segment", "total_tickets", "refund_rate"],
        rows=[
            ["on_time", 270000, 0.0252],
            ["delay_30", 5000, 0.0260],
            ["delay_60", 870, 0.0276],
            ["longhaul_biz", 6726, 0.0253],
        ],
        row_count=4,
    )
    out = _attach_stats(qr)
    assert any(s.type == "uniformity" for s in out.stats), "uniformity stat must attach"
    uni = next(s for s in out.stats if s.type == "uniformity")
    assert uni.is_significant is False
    assert "NO SIGNAL" in uni.interpretation
