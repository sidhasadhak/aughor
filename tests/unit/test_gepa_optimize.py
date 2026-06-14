"""GEPA-SQL reflective optimizer — the loop logic, proven deterministically (no LLM).

The loop must: adopt a candidate only when it beats the current best (never regress), keep the
baseline when nothing improves, compute a held-out lift, and feed the worst failures to reflect.
"""
import evals.gepa_optimize as g

RECS = [{"id": f"r{i}", "question": "q", "reference_sql": "y"} for i in range(10)]


def _eval_from(scores: dict):
    """A stub evaluate_fn: every record scores the same for a given prompt."""
    def ev(prompt, recs):
        s = scores.get(prompt, 0.0)
        res = [{"id": r["id"], "question": "q", "generated_sql": "x", "reference_sql": "y",
                "overall": s, "error": None} for r in recs]
        return s, res
    return ev


def test_keeps_best_and_never_regresses():
    ev = _eval_from({"BASE": 0.5, "GOOD": 0.8, "BAD": 0.3})
    out = g.optimize(RECS, baseline_prompt="BASE", evaluate_fn=ev,
                     reflect_fn=lambda p, res, n: ["GOOD", "BAD"][:n],
                     rounds=1, n_candidates=2, train_frac=0.6)
    assert out["best_prompt"] == "GOOD" and out["train_best"] == 0.8 and out["improved"]
    # the worse candidate (0.3) is logged but not accepted
    bad = [e for e in out["log"] if e.get("candidate") == 1][0]
    assert bad["accepted"] is False


def test_no_improvement_keeps_baseline():
    ev = _eval_from({"BASE": 0.7, "WORSE": 0.4})
    out = g.optimize(RECS, baseline_prompt="BASE", evaluate_fn=ev,
                     reflect_fn=lambda p, res, n: ["WORSE"], rounds=2, n_candidates=1)
    assert out["best_prompt"] == "BASE" and out["improved"] is False
    assert out["heldout_best"] == out["heldout_baseline"]  # held-out not even re-run


def test_heldout_split_and_lift():
    ev = _eval_from({"BASE": 0.5, "G": 0.9})
    out = g.optimize(RECS, baseline_prompt="BASE", evaluate_fn=ev,
                     reflect_fn=lambda p, res, n: ["G"], rounds=1, n_candidates=1, train_frac=0.7)
    assert out["n_train"] == 7 and out["n_heldout"] == 3
    assert out["heldout_baseline"] == 0.5 and out["heldout_best"] == 0.9 and out["heldout_lift"] == 0.4
    assert out["log"][0]["source"] == "baseline"


def test_format_failures_picks_the_worst():
    results = [{"question": f"q{i}", "reference_sql": "r", "generated_sql": "g", "overall": v, "error": None}
               for i, v in enumerate([0.2, 1.0, 0.5, 0.9])]
    dig = g.format_failures(results, k=2)
    assert "q0" in dig and "q2" in dig   # the two worst (0.2, 0.5)
    assert "q1" not in dig               # a perfect score is not a failure
