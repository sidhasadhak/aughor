"""JD-4's battery, pinned hermetically.

`evals/` is not collected by pytest (`pyproject.toml` sets `testpaths = ["tests"]`), so the way
an eval becomes a STANDING guard here is a companion in `tests/unit/` that imports its pure
helpers — the shape `test_intake_validity.py` and `test_decision_yield.py` already use. Nothing
below makes a model call or opens a store.

What is pinned, and why each one could otherwise pass for the wrong reason:

* an UNAVAILABLE reading must carry its reason, and an AVAILABLE one must carry a value — the
  collapse this battery exists to prevent is "could not measure" arriving as `0.0`;
* ECE is checked against a HAND-COMPUTED answer in both directions, because a calibration
  number that is merely plausible is indistinguishable from one that is wrong;
* the shuffled control is driven by a STUB judge, so the arm that would cost money is exercised
  for free — otherwise the only way to find a bug in it is to pay for one;
* the `step 1` prefix is tested against `step 12`, which contains it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evals.judgment_battery_eval import (  # noqa: E402
    ECE_REASONS, Measure, choice_prior, ece, replayability, shuffled_control, summarize, top1,
)

MENU = ["baseline", "decompose", "run_sql"]


def row(**kw):
    """One decision_record row, defaulted to the live corpus's shape: an outcome of 'ok', no
    probability, and a first-turn context."""
    base = {"site": "converse.tool", "context": "step 1 | last run_sql ok | ctx",
            "options": list(MENU), "label": 2, "chosen": "run_sql",
            "source": "llm", "confidence": 0.0, "outcome": "ok"}
    base.update(kw)
    return base


# ── The typed reading cannot be silently empty ────────────────────────────────

def test_an_unavailable_measure_must_carry_its_reason():
    with pytest.raises(ValueError, match="must carry its reason"):
        Measure("ece", False)
    assert Measure("ece", False, reason="no probabilities").available is False


def test_an_available_measure_must_carry_a_value():
    """Without this, an available measure could serialise `value: null` and a reader would see
    an empty cell where a number was promised — the same collapse from the other side."""
    with pytest.raises(ValueError, match="must carry its value"):
        Measure("top1", True)


# ── top-1 ─────────────────────────────────────────────────────────────────────

def test_top1_refuses_a_constant_label():
    """The live corpus's exact shape: `outcome` is 'ok' on every row. Accuracy against a
    constant is 1.0 for any corpus whatsoever, so reporting 1.0 here would be a perfect score
    that means nothing."""
    m = top1([row(), row(), row()])
    assert m.available is False
    assert "never takes its other value" in m.reason
    assert m.value is None


def test_top1_computes_once_the_label_varies():
    """The negative control. Without it, `top1` could refuse everything and the test above
    would still pass."""
    m = top1([row(outcome="ok"), row(outcome="ok"), row(outcome="error"), row(outcome="error")])
    assert m.available is True
    assert m.value == pytest.approx(0.5)
    assert m.detail["scored"] == 4


def test_top1_is_unavailable_when_nothing_carries_an_outcome():
    m = top1([row(outcome=""), row(outcome="")])
    assert m.available is False and "nothing to be right or wrong against" in m.reason


# ── ECE ───────────────────────────────────────────────────────────────────────

def test_ece_refuses_a_corpus_with_no_probabilities_and_names_a_cause_per_site():
    """`confidence` defaults to 0.0 and the store documents that as "the decider offers none",
    so a store of zeros is an ABSENCE of probabilities, not a store of confidently-wrong ones.
    Treating the zeros as data would produce a large, meaningless ECE that a reader would act on.
    """
    m = ece([row(site="converse.tool"), row(site="converse.tool")])
    assert m.available is False and m.value is None
    per_site = m.detail["per_site"]
    # Every registered site names its OWN cause, and no two share a string — a single global
    # reason would be wrong for most of them. Asserted against the module's roster rather than
    # a hardcoded count, which would go stale the moment a site is added (`analyst.tool` was,
    # on 2026-09-21).
    assert set(per_site) == set(ECE_REASONS)
    assert len(set(per_site.values())) == len(ECE_REASONS)
    assert all(v.strip() for v in per_site.values())
    # And the causes are semantically different, which is the point the count only gestures at:
    assert "never produced" in per_site["converse.tool"]   # the decider emits none
    assert "traffic gap" in per_site["ask.route"]          # it emits one, nobody asked it
    assert "same seam" in per_site["analyst.tool"]         # same cause as converse, own roster
    assert "flag" in per_site["framing.definition"]        # gated off, empty population


def test_ece_is_zero_for_a_perfectly_calibrated_bin():
    """Hand-computed: two rows at p=0.5, one right and one wrong, land in one bin whose mean
    confidence (0.5) equals its accuracy (0.5). |0.5 - 0.5| = 0."""
    m = ece([row(confidence=0.5, outcome="ok"), row(confidence=0.5, outcome="error")])
    assert m.available is True
    assert m.value == pytest.approx(0.0)
    assert m.detail["occupied_bins"] == 1


def test_ece_matches_a_hand_computed_miscalibration():
    """Two bins, each holding one row:
        p=0.9, outcome ok    -> bin 9: conf 0.9, acc 1.0, gap 0.1, weight 1/2
        p=0.1, outcome error -> bin 1: conf 0.1, acc 0.0, gap 0.1, weight 1/2
    ECE = 0.5*0.1 + 0.5*0.1 = 0.1
    """
    m = ece([row(confidence=0.9, outcome="ok"), row(confidence=0.1, outcome="error")])
    assert m.value == pytest.approx(0.1)
    assert m.detail["occupied_bins"] == 2


def test_ece_refuses_probabilities_with_no_outcome_to_compare_them_to():
    m = ece([row(confidence=0.9, outcome=""), row(confidence=0.4, outcome="")])
    assert m.available is False and "none carries an outcome" in m.reason


# ── the prior ─────────────────────────────────────────────────────────────────

def test_choice_prior_is_the_majority_class_rate():
    """The floor a control must beat, and the one reading that is always free. Three of four
    rows chose run_sql, so a shuffled arm agreeing 75% of the time has reproduced the prior."""
    rows = [row(chosen="run_sql"), row(chosen="run_sql"), row(chosen="run_sql"),
            row(chosen="baseline")]
    m = choice_prior(rows)
    assert m.available is True
    assert m.value == pytest.approx(0.75)
    assert m.detail["majority_choice"] == "run_sql"
    assert m.detail["uniform_baseline"] == pytest.approx(1 / 3)


# ── replayability ─────────────────────────────────────────────────────────────

def test_step_one_is_matched_as_a_prefix_not_a_substring():
    """`step 1` occurs inside `step 12`. A substring test would count a twelfth-step decision as
    a first-turn one and then replay it as if it had no history — the error in the direction
    that flatters the control."""
    rows = [row(context="step 1 | a"), row(context="step 12 | b"), row(context="step 2 | c")]
    m = replayability(rows)
    assert m.value == 1.0
    assert m.detail["first_turn"] == 1 and m.detail["mid_loop"] == 2


def test_replayability_says_even_first_turn_rows_are_not_byte_faithful():
    """The caveat is part of the reading, not decoration: the system prompt was never recorded,
    so 'faithful' here is a ceiling, not a guarantee."""
    assert "system prompt" in replayability([row()]).detail["caveat"]


# ── the control arm, exercised without spending ───────────────────────────────

def test_the_control_refuses_when_no_judge_is_supplied():
    """The default path must stay free, and 'not run' must be distinguishable from 'ran and
    found nothing'."""
    m = shuffled_control([row(), row()])
    assert m.available is False
    assert "no judge was supplied" in m.reason
    assert m.detail["would_cost_calls"] == 4


def test_the_control_refuses_a_corpus_it_cannot_replay_faithfully():
    """Mid-loop rows saw a tool-result history persisted nowhere. Re-asking them would change
    more than the state and then attribute the difference to the shuffle."""
    rows = [row(context="step 4 | a"), row(context="step 5 | b"), row(context="step 6 | c")]
    m = shuffled_control(rows, ask=lambda ctx, opts: "run_sql")
    assert m.available is False and "mid-loop" in m.reason


def test_a_state_blind_judge_reproduces_the_prior_and_fires_the_falsifier():
    """A stub judge that ignores the context entirely and always answers `run_sql` — which is
    exactly what "not reading the state" looks like. It agrees with every real choice, the
    control lands at 1.0 against a 1.0 prior, and JD-4's falsifier must fire.

    Driving the arm with a stub is the point: the scoring is exercised for free, so a bug in it
    does not have to be paid for to be found.
    """
    rows = [row(context=f"step 1 | ctx {i}") for i in range(4)]
    m = shuffled_control(rows, ask=lambda ctx, opts: "run_sql")
    assert m.available is True and m.value == pytest.approx(1.0)
    assert m.detail["pairing"] == "rotate-by-one (deterministic)"

    s = summarize(rows, {"truncated": False}, ask=lambda ctx, opts: "run_sql")
    assert s["falsifier"]["judgments_do_not_read_the_state"] is True
    assert s["inconclusive"] is False


def test_a_state_reading_judge_beats_the_prior_and_the_falsifier_holds():
    """The negative control, and the reason the test above proves anything: a judge that DOES
    read the state picks differently under a shuffled one, lands below the prior, and the
    falsifier holds. Without this, a falsifier that always fired would pass the test above."""
    rows = [row(context=f"step 1 | ctx {i}", chosen=MENU[i % 3], label=i % 3) for i in range(6)]

    def reads_the_state(ctx, opts):
        return MENU[int(str(ctx).split("ctx ")[1]) % 3]

    s = summarize(rows, {"truncated": False}, ask=reads_the_state)
    control = s["measures"]["shuffled_control"]
    assert control["available"] is True
    assert control["value"] < s["measures"]["choice_prior"]["value"]
    assert s["falsifier"]["judgments_do_not_read_the_state"] is False


# ── the whole report ──────────────────────────────────────────────────────────

def test_an_unrun_control_is_inconclusive_not_a_pass():
    """The siblings keep `inconclusive` separate from the falsifier for this reason: a battery
    that took no reading settles nothing, and reporting it as a clean run makes the instrument
    decoration."""
    s = summarize([row(), row()], {"truncated": False}, ask=None)
    assert s["inconclusive"] is True
    assert s["falsifier"]["judgments_do_not_read_the_state"] is False
    assert "not evaluable" in s["falsifier"]["note"]


def test_the_live_corpus_shape_reports_three_unavailables_and_one_number():
    """The live store on 2026-09-20, in miniature: outcome constant, no probabilities, and a
    skewed choice distribution. Exactly one reading should survive — the prior."""
    rows = ([row(chosen="run_sql")] * 3) + [row(chosen="baseline")]
    s = summarize(rows, {"truncated": False}, ask=None)
    m = s["measures"]
    assert m["top1"]["available"] is False
    assert m["ece"]["available"] is False
    assert m["shuffled_control"]["available"] is False
    assert m["choice_prior"]["available"] is True
    assert m["replayable_rows"]["available"] is True
    assert s["inconclusive"] is True


def test_truncation_rides_the_report():
    """`list_decisions` caps at 500 per site. At 58 rows that is invisible, which is why it is
    carried explicitly — a battery that silently measured 500 of 5,000 would report a confident
    number about a sample nobody chose."""
    s = summarize([row()], {"truncated": True, "note": "read 500 of 5000"}, ask=None)
    assert s["truncation"]["truncated"] is True and "500 of 5000" in s["truncation"]["note"]
