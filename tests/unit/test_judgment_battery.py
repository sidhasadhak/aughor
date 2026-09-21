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

import hashlib  # noqa: E402

from evals.judgment_battery_eval import STATE_ARG, UNCONTROLLED  # noqa: E402


def _rebuild(args):
    """A stand-in prompt builder: deterministic, and it puts the STATE argument in the middle of
    the prompt — where the analyst's `_spec_section(intake)` really sits — so a test that
    swapped the whole assembled string instead of one argument would visibly change more."""
    state = args.get(STATE_ARG[args["builder"]], "")
    return f"IDENTITY for {args.get('connection_id')}\n[STATE:{state}]\nGUARDS budget={args.get('budget')}"


def _sha(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def replayable(i, *, chosen="run_sql", state=None, builder="analyst_system_prompt"):
    """One first-turn row plus the capture that makes it faithfully replayable."""
    args = {"builder": builder, "connection_id": "c1", "budget": 6,
            "question": f"question {i}", STATE_ARG[builder]: state or f"state {i}"}
    fingerprint = _sha(_rebuild(args))
    r = row(id=f"d{i}", context=f"step 1 | last (start) | question {i}", chosen=chosen,
            prompt_fingerprint=fingerprint)
    return r, {**args, "prompt_fingerprint": fingerprint}


def test_step_one_is_matched_as_a_prefix_not_a_substring():
    """`step 1` occurs inside `step 12`. A substring test would count a twelfth-step decision as
    a first-turn one and then replay it as if it had no history — the error in the direction
    that flatters the control."""
    rows = [row(context="step 1 | a"), row(context="step 12 | b"), row(context="step 2 | c")]
    m = replayability(rows)
    assert m.detail["first_turn"] == 1 and m.detail["mid_loop"] == 2


def test_a_first_turn_row_is_not_replayable_by_being_first_alone():
    """`value` used to be the first-turn COUNT — a ceiling mislabelled as a count; the old
    docstring itself said none of those rows was a byte-faithful replay. The live corpus shape:
    14 first-turn rows, no fingerprint, no capture, and the honest count is zero."""
    m = replayability([row(id=f"x{i}") for i in range(3)])
    assert m.detail["first_turn"] == 3
    assert m.value == 0.0, "first-turn is necessary, not sufficient"


def test_each_disqualifier_is_named_not_merely_counted():
    """A zero is only actionable if it says WHICH requirement failed. Each row here fails a
    different one, in the order a reader would want them named."""
    ok_row, ok_cap = replayable(0)
    trunc_row, trunc_cap = replayable(1)
    drift_row, drift_cap = replayable(2)
    rows = [
        row(id="mid", context="step 3 | last run_sql ok | q"),          # mid-loop
        row(id="old", context="step 1 | a", prompt_fingerprint=""),           # pre-JD-4
        row(id="nocap", context="step 1 | a", prompt_fingerprint="abc"),      # window closed
        trunc_row, drift_row, ok_row,
    ]
    caps = {"d0": ok_cap,
            "d1": {**trunc_cap, "intake_truncated": True},
            "d2": {**drift_cap, "prompt_fingerprint": "not-the-rows-fingerprint"}}
    m = replayability(rows, captures=caps)
    why = m.detail["not_replayable_because"]
    assert m.value == 1.0
    assert any("mid-loop" in k for k in why)
    assert any("no prompt fingerprint" in k for k in why)
    assert any("no captured arguments" in k for k in why)
    assert any("truncated" in k for k in why)
    assert any("does not match" in k for k in why)


# ── the control arm, exercised without spending ───────────────────────────────

def test_the_control_refuses_when_no_judge_is_supplied():
    """The default path must stay free, and 'not run' must be distinguishable from 'ran and
    found nothing'. It still reports what it CANNOT hold constant, so a reader sizing the spend
    knows the result would be approximate before paying for it."""
    rows, caps = zip(*(replayable(i) for i in range(3)))
    m = shuffled_control(list(rows), captures=dict(zip((r["id"] for r in rows), caps)))
    assert m.available is False
    assert "no judge was supplied" in m.reason
    assert m.detail["would_cost_calls"] == 6
    assert m.detail["uncontrolled"] == list(UNCONTROLLED)


def test_the_control_refuses_a_corpus_it_cannot_replay_faithfully_and_names_why():
    rows = [row(context="step 4 | a"), row(context="step 5 | b"), row(context="step 6 | c")]
    m = shuffled_control(rows, ask=lambda s, q, o: "run_sql", rebuild=_rebuild)
    assert m.available is False and "mid-loop" in m.reason


def test_a_rebuild_that_drifted_is_refused_BEFORE_a_token_is_spent():
    """The fingerprint exists for exactly this. Live state moves (a roster, a pack index, an org
    context), a rebuild stops matching what the decider was shown, and a replay on it would ask
    a different question than the one logged. It must be refused before the judge is called —
    so the judge here raises if it is reached at all."""
    rows, caps = zip(*(replayable(i) for i in range(3)))
    captures = dict(zip((r["id"] for r in rows), caps))

    def judge_must_not_be_called(system, question, options):
        raise AssertionError("the judge was called on a rebuild that had drifted")

    m = shuffled_control(list(rows), ask=judge_must_not_be_called,
                         rebuild=lambda a: _rebuild(a) + " <live state moved>",
                         captures=captures)
    assert m.available is False
    assert "did not reproduce the recorded prompt fingerprint" in m.reason
    assert len(m.detail["drifted"]) == 3


def test_the_swap_changes_exactly_one_argument_and_nothing_else():
    """The property the whole control rests on. The first version of this arm swapped recorded
    CONTEXT strings — a label, not the state the model read. Swapping whole assembled prompts
    would have been worse: the connection, the budget, the roster and the disclosure block move
    with the state, and five changes get attributed to one. Here every argument but the state is
    held fixed and the judge sees it."""
    rows, caps = zip(*(replayable(i, state=f"S{i}") for i in range(3)))
    captures = dict(zip((r["id"] for r in rows), caps))
    seen = []

    def judge(system, question, options):
        seen.append((system, question))
        return "run_sql"

    shuffled_control(list(rows), ask=judge, rebuild=_rebuild, captures=captures)
    # Row 0 carries row 1's STATE, and nothing else of row 1's.
    system0, question0 = seen[0]
    assert "[STATE:S1]" in system0, "the state was not swapped"
    assert "IDENTITY for c1" in system0 and "budget=6" in system0
    assert question0 == "question 0", "the question moved with the state — two changes, not one"


def test_a_state_blind_judge_reproduces_the_prior_and_fires_the_falsifier():
    """A judge that ignores the state entirely and always answers `run_sql` — exactly what "not
    reading the state" looks like. It agrees with every real choice, lands at the prior, and
    JD-4's falsifier must fire."""
    rows, caps = zip(*(replayable(i) for i in range(4)))
    captures = dict(zip((r["id"] for r in rows), caps))
    s = summarize(list(rows), {"truncated": False}, ask=lambda sy, q, o: "run_sql",
                  rebuild=_rebuild, captures=captures)
    control = s["measures"]["shuffled_control"]
    assert control["available"] is True and control["value"] == pytest.approx(1.0)
    assert control["detail"]["fingerprints_verified"] == 4
    assert control["detail"]["approximate"] is True
    assert s["falsifier"]["judgments_do_not_read_the_state"] is True
    assert s["inconclusive"] is False


def test_a_state_reading_judge_beats_the_prior_and_the_falsifier_holds():
    """The negative control, and the reason the test above proves anything: a judge that DOES
    read the state picks differently once the state is swapped, lands below the prior, and the
    falsifier holds. Without this, a falsifier that always fired would pass the test above."""
    pairs = [replayable(i, chosen=MENU[i % 3], state=MENU[i % 3]) for i in range(6)]
    rows, caps = zip(*pairs)
    captures = dict(zip((r["id"] for r in rows), caps))

    def reads_the_state(system, question, options):
        return system.split("[STATE:")[1].split("]")[0]

    s = summarize(list(rows), {"truncated": False}, ask=reads_the_state, rebuild=_rebuild,
                  captures=captures)
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
