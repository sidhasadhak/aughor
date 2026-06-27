"""Engine eval adapter — plan-metadata extraction (Bet 2 live half, 2026-06-27).

extract_plan_meta turns a decompose result into eval metadata; run_pack_evals + check_expectation
score it. Pure (no engine) here; the live make_ask_fn is exercised end-to-end separately.
See aughor/packs/engine_eval.py.
"""
from aughor.packs.engine_eval import extract_plan_meta
from aughor.packs import run_pack_evals, load_pack
from aughor.agent.state import SubQuestion
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _sq(q, purpose="relationship"):
    return SubQuestion(id="Q", purpose=purpose, question=q, expected_output="agg")


def _plan(questions, steered="customer-analytics"):
    return {
        "sub_questions": [_sq(q) for q in questions],
        "verification_checks": [f"specialist:{steered}"] if steered else [],
    }


def test_meta_detects_cohort_grain_and_recipe():
    pack = load_pack(REPO / "packs" / "customer-analytics")
    plan = _plan([
        "What is the volume of new customers by signup month (cohort)?",
        "What is the cohort retention rate at month offsets 0-6?",
        "How does retention vary by acquisition channel?",
    ])
    meta = extract_plan_meta(plan, pack)
    assert meta["grain"] == "cohort"
    assert meta["ran_decomposition"] is True
    assert any("retention" in r.lower() for r in meta["recipe_used"])
    assert meta["steered_by"] == ["customer-analytics"]


def test_meta_period_grain_and_no_decomp():
    pack = load_pack(REPO / "packs" / "customer-analytics")
    meta = extract_plan_meta(_plan(["What is revenue by month?"], steered=None), pack)
    assert meta["grain"] == "period"
    assert meta["ran_decomposition"] is False
    assert meta["steered_by"] == []


def test_eval_scoring_over_extracted_meta_passes():
    pack = load_pack(REPO / "packs" / "customer-analytics")
    questions_meta = {
        "Show retention by monthly cohort for the last year.":
            _plan(["new customers by signup cohort", "cohort retention at offsets 0-6",
                   "retention by channel"]),
        "Is retention dropping?":
            _plan(["cohort retention trend", "acquisition mix shift confounder", "channel churn"]),
    }
    results = run_pack_evals(pack, lambda q: extract_plan_meta(questions_meta[q], pack))
    assert all(r.passed for r in results), [(r.question, r.detail) for r in results]
