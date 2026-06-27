"""Binding column-verify (#2) + eval runner/checker (Bet 2 runner) — 2026-06-27.

verify_binding_columns confirms bound columns exist; run_pack_evals scores golden questions
via an injected engine call (ask_fn). See aughor/packs/resolver.py, evalrunner.py.
"""
from aughor.packs import verify_binding_columns, run_pack_evals, check_expectation
from aughor.packs.models import Pack, PackManifest, PackEval

TABLE_COLS = {"dim_customers": ["customer_id", "signup_ts"], "fct_orders": ["order_id", "order_ts", "customer_id"]}


# ── #2 binding verify ─────────────────────────────────────────────────────────

def test_verify_ok_when_columns_exist():
    binding = {
        "customer": {"table": "dim_customers", "column": "customer_id"},
        "event": {"table": "fct_orders", "column": "order_ts"},
        "active_definition": {"value": "purchased_in_window"},   # value-role, skipped
    }
    ok, missing = verify_binding_columns(binding, TABLE_COLS)
    assert ok and missing == []


def test_verify_flags_missing_table_and_column():
    binding = {
        "customer": {"table": "ghost", "column": "id"},
        "event": {"table": "fct_orders", "column": "nope_ts"},
    }
    ok, missing = verify_binding_columns(binding, TABLE_COLS)
    assert not ok
    assert any("ghost" in m for m in missing)
    assert any("nope_ts" in m for m in missing)


# ── Bet 2 eval runner ─────────────────────────────────────────────────────────

def _pack():
    return Pack(manifest=PackManifest(id="ca", name="CA"), evals=[
        PackEval(question="Show retention by cohort.", expect={"uses_recipe": "cohort-retention", "grain": "cohort"}),
        PackEval(question="Is retention dropping?", expect={"runs_decomposition": True}),
    ])


def test_check_expectation_pass_and_fail():
    ok, _ = check_expectation({"recipe_used": "cohort-retention", "grain": "cohort"},
                              {"uses_recipe": "cohort-retention", "grain": "cohort"})
    assert ok
    bad, detail = check_expectation({"recipe_used": "generic", "grain": "period"},
                                    {"uses_recipe": "cohort-retention"})
    assert not bad and "expected recipe" in detail


def test_must_not_violation():
    ok, detail = check_expectation({"text": "this counts survivorship in denominator"},
                                   {"must_not": ["survivorship in denominator"]})
    assert not ok and "must_not" in detail


def test_run_pack_evals_scores_each():
    metas = {
        "Show retention by cohort.": {"recipe_used": "cohort-retention", "grain": "cohort"},
        "Is retention dropping?": {"ran_decomposition": True},
    }
    results = run_pack_evals(_pack(), lambda q: metas.get(q, {}))
    assert all(r.passed for r in results)


def test_run_pack_evals_failure_and_error_safe():
    def ask(q):
        if "dropping" in q:
            raise RuntimeError("engine boom")
        return {"recipe_used": "generic"}   # wrong recipe → fail
    results = run_pack_evals(_pack(), ask)
    assert not any(r.passed for r in results)
    assert any("errored" in (r.detail or "") for r in results)
