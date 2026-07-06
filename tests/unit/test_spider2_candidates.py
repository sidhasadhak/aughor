"""Levers 4+5 — strategy-diverse candidates: signature grouping + deterministic selection.

Offline (stub generate/execute): the selection contract is what's pinned — plurality of
execution signatures wins, grain conformance breaks ties, then brevity, then stable order.
"""
from __future__ import annotations

from evals.spider2_candidates import (
    Candidate,
    result_signature,
    run_candidates,
    select_candidate,
)


def _c(strategy, sql, sig, ok=True, grain_ok=True):
    return Candidate(strategy=strategy, sql=sql, ok=ok, signature=sig, grain_ok=grain_ok)


def test_signature_is_order_insensitive_and_value_sensitive():
    a = result_signature(["x"], [(1, "a"), (2, "b")])
    b = result_signature(["x"], [(2, "b"), (1, "a")])
    c = result_signature(["x"], [(1, "a"), (2, "DIFFERENT")])
    assert a == b != c
    assert result_signature(["x"], None) == "ERROR"


def test_plurality_wins():
    cands = [_c("direct", "S1", "sigA"), _c("decompose", "S2", "sigA"),
             _c("plan_first", "S3", "sigB")]
    assert select_candidate(cands).signature == "sigA"


def test_grain_breaks_signature_tie():
    cands = [_c("direct", "SELECT long_version_padding", "sigA", grain_ok=False),
             _c("decompose", "SELECT other", "sigB", grain_ok=True)]
    assert select_candidate(cands).signature == "sigB"


def test_brevity_then_stability():
    cands = [_c("plan_first", "SELECT 1 /* longer */", "sigA"),
             _c("direct", "SELECT 1", "sigB")]
    assert select_candidate(cands).sql == "SELECT 1"
    # exact tie in every criterion → stable by strategy name
    cands = [_c("plan_first", "SELECT 1", "sigA"), _c("direct", "SELECT 1", "sigB")]
    assert select_candidate(cands).strategy == "direct"


def test_failed_candidates_excluded_and_all_failed_none():
    cands = [_c("direct", "S", "ERROR", ok=False), _c("decompose", "S2", "sigA")]
    assert select_candidate(cands).signature == "sigA"
    assert select_candidate([_c("direct", "S", "ERROR", ok=False)]) is None


def test_run_candidates_orchestration_offline():
    # strategy-dependent stub: two strategies produce the same (correct) result,
    # one produces a divergent grain-violating result, one fails to generate.
    def gen(q, schema, doc):
        if "decompose" in doc.lower() or doc == "":
            return "SELECT grp, SUM(v) FROM t GROUP BY grp"
        if "grain" in doc.lower() and "one row per what" in doc.lower():
            return "SELECT grp, SUM(v) FROM t GROUP BY grp  -- planned"
        raise RuntimeError("provider hiccup")

    def execute(sql):
        if "GROUP BY grp" in sql:
            return True, [("a", 3), ("b", 4)], ""
        return False, None, "boom"

    out = run_candidates(
        "total v for each grp", "SCHEMA", "",
        generate_fn=gen, execute_fn=execute, columns_fn=lambda s: ["grp", "sum"],
        strategies=["direct", "decompose", "plan_first", "adversarial"],
    )
    assert out.chosen is not None
    assert out.chosen.ok and out.n_signatures == 1
    # the two identical-signature candidates form the winning group
    live = [c for c in out.candidates if c.ok]
    assert len(live) >= 2
    assert out.agreed
