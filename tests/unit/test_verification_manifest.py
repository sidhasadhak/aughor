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


# ── 0-II: earned confidence + data-trust ──────────────────────────────────────

def _sq(i):
    from aughor.agent.state import SubQuestion
    return SubQuestion(id=f"Q{i}", purpose="relationship", question=f"q{i}", expected_output="agg")


def _ans(i):
    from aughor.agent.state import SubQuestionAnswer
    return SubQuestionAnswer(subq_id=f"Q{i}", question="q", purpose="relationship", sql="",
                             columns=[], rows=[], row_count=0, answer="a", insight="i")


def _pitfall(issue):
    from aughor.agent.state import Pitfall
    return Pitfall(original_sql="", error=issue, fixed_sql="", fix_explanation=issue,
                   data_quality_issue=issue)


def test_healthy_run_high_confidence():
    state = {
        "verification_checks": ["temporal_prune:0", "join_value_domain", "cardinality_guard"],
        "query_history": [_qr(stats=[_uni_stat()])],
        "sub_questions": [_sq(1), _sq(2)],
        "subq_answers": [_ans(1), _ans(2)],
    }
    m = _build_verification_manifest(state)
    assert m.data_trust == 1.0
    assert m.confidence_band == "high"
    assert m.earned_confidence >= 0.9


def test_swiss_air_shape_low_trust():
    # Uniform across 6 dims + single-period (temporal pruned) + a raw-COUNT cardinality caveat.
    hist = [_qr(hid=f"Q{i}", stats=[_uni_stat()]) for i in range(6)]
    state = {
        "verification_checks": ["temporal_prune:1", "join_value_domain", "cardinality_guard"],
        "query_history": hist,
        "sub_questions": [_sq(i) for i in range(1, 8)],
        "subq_answers": [_ans(i) for i in range(1, 8)],
        "pitfalls": [_pitfall("rate divides two raw COUNT()s across a join — ...")],
    }
    m = _build_verification_manifest(state)
    assert m.data_trust <= 0.3                  # 1 - 0.4 (uniform≥3) - 0.2 (single period) - 0.2 (count ratio)
    assert m.confidence_band == "low"
    assert any("suspiciously flat" in s for s in m.signals)
    assert any("single period" in s for s in m.signals)


def test_genuine_partial_run_penalised():
    state = {
        "verification_checks": ["temporal_prune:0", "join_value_domain", "cardinality_guard"],
        "query_history": [_qr(stats=[])],   # numeric? rows default [[1]] but stats empty
        "sub_questions": [_sq(i) for i in range(1, 7)],
        "subq_answers": [_ans(1)],          # only 1 of 6 ran, nothing converged
    }
    m = _build_verification_manifest(state)
    assert any("1/6 planned" in s for s in m.signals)
    assert m.earned_confidence < 0.7


def test_adversarial_refutation_halves_confidence():
    # Healthy run, but an independent skeptic refuted the headline → earned confidence halved.
    base_state = {
        "verification_checks": ["temporal_prune:0", "join_value_domain", "cardinality_guard"],
        "query_history": [_qr(stats=[_uni_stat()])],
        "sub_questions": [_sq(1), _sq(2)], "subq_answers": [_ans(1), _ans(2)],
    }
    healthy = _build_verification_manifest(base_state)
    refuted = _build_verification_manifest(base_state, extra_checks=["adversarial_refute:refuted"])
    assert refuted.earned_confidence <= round(healthy.earned_confidence * 0.5 + 1e-9, 3)
    chk = next(c for c in refuted.checks if c.name == "adversarial_refute")
    assert chk.status == "ran" and "REFUTED" in (chk.detail or "")
    assert any("refuted the headline" in s for s in refuted.signals)


def test_adversarial_survived_recorded():
    state = {
        "verification_checks": ["temporal_prune:0", "join_value_domain", "cardinality_guard"],
        "query_history": [_qr(stats=[_uni_stat()])],
        "sub_questions": [_sq(1)], "subq_answers": [_ans(1)],
    }
    m = _build_verification_manifest(state, extra_checks=["adversarial_refute:survived"])
    chk = next(c for c in m.checks if c.name == "adversarial_refute")
    assert chk.status == "ran" and "survived" in (chk.detail or "")


def test_adversarial_na_when_not_run():
    m = _build_verification_manifest({"verification_checks": [], "query_history": [_qr()]})
    chk = next(c for c in m.checks if c.name == "adversarial_refute")
    assert chk.status == "n/a"


def test_converged_early_not_penalised_for_completeness():
    # ≥3 uniform dims + unanswered planned steps = deliberate convergence, not incompleteness.
    hist = [_qr(hid=f"Q{i}", stats=[_uni_stat()]) for i in range(3)]
    state = {
        "verification_checks": ["temporal_prune:0", "join_value_domain", "cardinality_guard"],
        "query_history": hist,
        "sub_questions": [_sq(i) for i in range(1, 7)],
        "subq_answers": [_ans(1), _ans(2), _ans(3)],   # stopped at 3 of 6 on purpose
    }
    m = _build_verification_manifest(state)
    assert not any("planned sub-questions" in s for s in m.signals)  # no completeness penalty
