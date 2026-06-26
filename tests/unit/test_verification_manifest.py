"""Run Verification Manifest — liveness assertions (Bet 0, increment 0-I, 2026-06-26).

Defeats class-E silent failures: a guard that's off but assumed on. The manifest records
which guards actually fired; the `stats_attached` canary catches the exact dead-_attach_stats
bug (numeric results but no stats → a guard silently failed). See aughor/agent/explore.py.
"""
from aughor.agent.explore import _build_verification_manifest
from aughor.agent.state import QueryResult, StatResult


def _qr(hid="Q1", rows=None, stats=None, error=None):
    return QueryResult(hypothesis_id=hid, sql="SELECT 1", columns=["a"],
                       rows=rows if rows is not None else [[1]], row_count=1,
                       error=error, stats=stats or [])


def _uni_stat():
    return StatResult(type="uniformity", interpretation="UNIFORM / NO SIGNAL", is_significant=False)


def test_healthy_run_full_coverage():
    state = {
        "verification_checks": ["temporal_prune:1", "join_value_domain", "cardinality_guard"],
        "query_history": [_qr(stats=[_uni_stat()])],
    }
    m = _build_verification_manifest(state)
    by = {c.name: c for c in m.checks}
    assert by["temporal_prune"].status == "ran"
    assert "pruned 1" in (by["temporal_prune"].detail or "")
    assert by["join_value_domain"].status == "ran"
    assert by["cardinality_guard"].status == "ran"
    assert by["stats_attached"].status == "ran"
    assert by["segment_significance"].status == "ran"
    assert m.coverage == 1.0


def test_dead_attach_stats_is_caught():
    # Numeric results exist but NO stats attached → the silent-failure canary fires.
    state = {
        "verification_checks": ["temporal_prune:0", "join_value_domain", "cardinality_guard"],
        "query_history": [_qr(rows=[[1], [2]], stats=[])],
    }
    m = _build_verification_manifest(state)
    by = {c.name: c for c in m.checks}
    assert by["stats_attached"].status == "not_run"
    assert "silently failed" in (by["stats_attached"].detail or "")
    assert m.coverage < 1.0


def test_no_numeric_results_marks_stats_na():
    state = {
        "verification_checks": ["temporal_prune:0", "join_value_domain", "cardinality_guard"],
        "query_history": [_qr(rows=[], error="boom")],
    }
    m = _build_verification_manifest(state)
    by = {c.name: c for c in m.checks}
    assert by["stats_attached"].status == "n/a"
    # n/a checks are excluded from coverage; the three recorded guards all ran.
    assert m.coverage == 1.0


def test_unrecorded_guard_shows_not_run():
    # A guard that never appended its name shows not_run (not silently assumed passed).
    state = {"verification_checks": ["temporal_prune:0"], "query_history": [_qr(stats=[_uni_stat()])]}
    m = _build_verification_manifest(state)
    by = {c.name: c for c in m.checks}
    assert by["join_value_domain"].status == "not_run"
    assert by["cardinality_guard"].status == "not_run"
    assert m.coverage < 1.0


def test_empty_state_is_safe():
    m = _build_verification_manifest({})
    assert any(c.name == "stats_attached" for c in m.checks)
