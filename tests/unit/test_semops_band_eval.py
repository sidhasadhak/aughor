"""The JD-3 harness, held hermetic: stub providers and a stub Jev transport, no network, no model.

`evals/` is not collected by pytest, so — as for the JD-4 battery — the harness becomes a standing
guard through a companion here that imports its pure helpers and drives its arms with stubs. The
arms run the PRODUCTION `semantic_filter`; the stubs only decide what each tier answers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from evals.semops_band_eval import (  # noqa: E402
    ArmResult,
    JevBackend,
    _Retryable,
    accuracy,
    agreement,
    load_rows,
    rescore,
    rows_in,
    planned_calls,
    run_arm,
    run_predicate,
    verdict,
)

ROWS = ["wool coat", "denim jacket", "cotton tee", "maybe a vest", "linen shirt",
        "rain parka", "silk scarf", "maybe a blazer", "chino trousers", "puffer jacket"]
TRUTH = {i for i, r in enumerate(ROWS) if re.search(r"coat|jacket|vest|parka|blazer", r)}
PRED = "the product is outerwear"


class Stub:
    """A tier that answers from the row text. ``unsure`` rows get 0.5 from a cheap tier and a
    decisive answer from the champion — the grey zone the band exists for."""

    def __init__(self, decisive: bool, wrong: set = frozenset()):
        self.decisive, self.wrong, self.calls = decisive, set(wrong), 0

    def _truth(self, i: int) -> bool:
        return (i in TRUTH) != (i in self.wrong)

    def complete(self, *, system, user, response_model):
        self.calls += 1
        fields = getattr(response_model, "model_fields", {})
        if "verdicts" in fields:                         # today's batch prompt: "[gi] text"
            idx = [int(m) for m in re.findall(r"^\[(\d+)\]", user, re.M)]
            item = fields["verdicts"].annotation.__args__[0]
            return response_model(verdicts=[item(index=i, keep=self._truth(i)) for i in idx])
        vals = {}                                        # the seam: one field per row, r<gi>
        for name in fields:
            i = int(name[1:])
            unsure = ROWS[i].startswith("maybe") and not self.decisive
            vals[name] = 0.5 if unsure else (0.95 if self._truth(i) else 0.05)
        return response_model(**vals)


# ── pure helpers ────────────────────────────────────────────────────────────────────────────

def test_planned_calls_are_ranges_where_the_answers_decide():
    plan = planned_calls(200, batch=25, sample=8, jev=True)
    assert plan["sampled"] == {"cheap": (8, 8), "champion": (1, 9)}
    assert plan["banded"] == {"cheap": (8, 8), "champion": (0, 8)}
    assert plan["reference"] == {"champion": (8, 8)}
    assert plan["banded-jev"] == {"jev": (8, 8), "champion": (0, 8)}


def test_agreement_counts_both_kept_and_both_dropped():
    assert agreement({0, 1}, {0, 1}, 4) == 1.0
    assert agreement({0}, {1}, 4) == 0.5
    with pytest.raises(ValueError):
        agreement(set(), set(), 0)


def _arm(name, kept, champion):
    return ArmResult(name, True, kept=set(kept), calls={"champion": champion})


@pytest.mark.parametrize("sampled_calls,banded_calls,expected", [(9, 2, "holds"), (1, 3, "falsified")])
def test_the_verdict_moves_in_both_directions(sampled_calls, banded_calls, expected):
    """A falsifier that can only ever hold is decoration; this one is shown to fire."""
    arms = {"reference": _arm("reference", TRUTH, 1), "sampled": _arm("sampled", TRUTH, sampled_calls),
            "banded": _arm("banded", TRUTH, banded_calls)}
    assert verdict(arms, len(ROWS))["verdict"] == expected


def test_unequal_agreement_settles_nothing():
    arms = {"reference": _arm("reference", TRUTH, 1), "sampled": _arm("sampled", TRUTH, 9),
            "banded": _arm("banded", set(), 0)}
    v = verdict(arms, len(ROWS), tolerance=0.02)
    assert v["verdict"] == "inconclusive" and "not comparable" in v["reason"]


def test_a_missing_arm_is_inconclusive_not_a_pass():
    arms = {"sampled": _arm("sampled", TRUTH, 9), "banded": _arm("banded", TRUTH, 0),
            "reference": ArmResult("reference", False, reason="no key")}
    assert verdict(arms, len(ROWS))["verdict"] == "inconclusive"


def test_rows_load_from_every_shape_the_fetch_can_leave(tmp_path):
    for body in ('["a","b"]', '[{"id":"1","name":"a"},{"id":"2","name":"b"}]', '{"rows":[["1","a"],["2","b"]]}'):
        (tmp_path / "r.json").write_text(body)
        assert load_rows(tmp_path / "r.json") == ["a", "b"]


# ── the arms, through the production operator ──────────────────────────────────────────────

def test_each_tier_is_counted_where_it_is_spent():
    cheap, champ = Stub(decisive=False), Stub(decisive=True)
    banded = run_arm("banded", ROWS, PRED, banded=True, cheap=cheap, champion=champ, sample=4, batch=25)
    assert banded.calls == {"cheap": 1, "champion": 1}           # one bundle each; champion only for the 2 unsure
    assert banded.kept == TRUTH
    sampled = run_arm("sampled", ROWS, PRED, banded=False, cheap=Stub(True, wrong={0, 1, 2}),
                      champion=Stub(True), sample=4, batch=25)
    assert sampled.calls == {"cheap": 1, "champion": 2}          # sample, then escalation of every row
    assert sampled.kept == TRUTH


def test_the_reference_counts_the_champion_as_the_champion():
    ref = run_predicate(ROWS, PRED, cheap=Stub(False), champion=Stub(True), jev=None,
                        sample=4, batch=25, tolerance=0.02)["arms"]["reference"]
    assert ref["calls"] == {"champion": 1}


def test_a_predicate_run_reports_every_arm_and_its_verdict():
    out = run_predicate(ROWS, PRED, cheap=Stub(False), champion=Stub(True), jev=None,
                        sample=4, batch=25, tolerance=0.02)
    assert set(out["arms"]) == {"reference", "sampled", "banded"}
    assert out["arms"]["banded"]["agreement_with_reference"] == 1.0
    assert out["verdict"]["verdict"] in {"holds", "falsified", "inconclusive"}


# ── the Jev arm, with the transport stubbed ─────────────────────────────────────────────────

def _jev_post(answer_for):
    sent = []

    def post(url, body, headers):
        sent.append((url, body, headers))
        return {"model": "jev-test", "usage": {"input_tokens": 100, "output_tokens": 5},
                "answers": {qid: {"type": "noul", "noul": answer_for(qid, q)}
                            for qid, q in body["questions"].items()}}
    return post, sent


def test_the_jev_arm_speaks_the_documented_shape_and_banding_still_decides():
    def answer(qid, q):
        text = q["instructions"].split("Text: ", 1)[1]
        if text.startswith("maybe"):
            return 0.5
        return 0.95 if re.search(r"coat|jacket|vest|parka|blazer", text) else 0.05
    post, sent = _jev_post(answer)
    jev = JevBackend("k", ArmResult("banded-jev", True), post=post)
    champ = Stub(decisive=True)
    arm = run_arm("banded-jev", ROWS, PRED, banded=True, cheap=jev, champion=champ, sample=4, batch=25)
    assert len(sent) == 1, f"the cheap tier should be ONE Jev call, got {len(sent)}"
    url, body, headers = sent[0]
    assert headers["Authorization"] == "Bearer k" and body["model"] == "jev-latest"
    assert all(q["type"] == "noul" for q in body["questions"].values())
    assert arm.calls == {"jev": 1, "champion": 1}                 # the champion only for the unsure rows
    assert arm.tokens == {"jev_input_tokens": 100, "jev_output_tokens": 5}
    assert arm.kept == TRUTH


def test_a_rate_limit_is_retried_and_a_dead_call_is_an_unavailable_answer(monkeypatch):
    from aughor.judgment.seam import Noul
    monkeypatch.setattr("evals.semops_band_eval.time.sleep", lambda s: None)
    tries = []

    def flaky(url, body, headers):
        tries.append(1)
        if len(tries) < 3:
            raise _Retryable("HTTP 429")
        return {"answers": {"r0": {"type": "noul", "noul": 0.9}}}
    got = JevBackend("k", ArmResult("j", True), post=flaky).judge("s", [Noul("r0", "p")])
    assert len(tries) == 3 and got["r0"].available and got["r0"].value is True

    def dead(url, body, headers):
        raise RuntimeError("HTTP 401: bad key")
    got = JevBackend("k", ArmResult("j", True), post=dead).judge("s", [Noul("r0", "p")])
    assert not got["r0"].available and "401" in got["r0"].reason


# ── failed calls, gold labels and rescoring ─────────────────────────────────────────────────

class Refuses(Stub):
    """A tier that returns nothing for any batch carrying a row it will not read — the shape of a
    provider's content filter emptying a response."""

    def complete(self, *, system, user, response_model):
        if "silk scarf" in user:
            raise RuntimeError("structured output empty: the model returned no content")
        return super().complete(system=system, user=user, response_model=response_model)


def test_the_rows_a_prompt_carries_are_read_from_both_prompt_shapes():
    assert rows_in("Rows (index: text):\n[3] a\n[17] b") == {3, 17}
    assert rows_in("QUESTIONS:\n- r4 [true/false]: x\n- r12 [true/false]: y") == {4, 12}


def test_a_row_no_model_decided_is_excluded_from_every_arm():
    """The operator keeps a failed batch (fail-open). Scored, those rows would reward whichever arm
    happened to fail on them. Kills: scoring over every row regardless of failures."""
    out = run_predicate(ROWS, PRED, cheap=Stub(False), champion=Refuses(True), jev=None,
                        sample=4, batch=5, tolerance=0.02)
    failed_batch = set(range(5, 10))                            # the batch holding "silk scarf" (row 6)
    assert out["arms"]["reference"]["unjudged_rows"] == sorted(failed_batch)
    # Conservative on purpose: EVERY row of every failed call, in any arm, leaves the population —
    # here also the sampled arm's validation sample (0, 2, 4, 6), whose champion call carried row 6.
    union = set().union(*(set(a["unjudged_rows"]) for a in out["arms"].values()))
    assert set(out["excluded_rows"]) == union >= failed_batch
    assert {0, 2, 4} <= union
    assert out["verdict"]["excluded_rows"] == len(union)


def test_gold_makes_the_verdict_about_accuracy_and_needs_no_reference():
    gold = {i: (i in TRUTH) for i in range(len(ROWS))}
    # With a WRONG reference present, the gold must still be what decides…
    arms = {"sampled": _arm("sampled", TRUTH, 9), "banded": _arm("banded", TRUTH, 1),
            "reference": _arm("reference", set(), 1)}
    v = verdict(arms, len(ROWS), gold=gold)
    assert v["yardstick"] == "gold" and v["banded_score"] == 1.0
    # …and with none at all, the gold is enough.
    del arms["reference"]
    v = verdict(arms, len(ROWS), gold=gold)
    assert v["yardstick"] == "gold" and v["verdict"] == "holds"
    assert accuracy(set(), gold) == 1 - len(TRUTH) / len(ROWS)


def test_a_saved_run_rescores_the_same_with_no_model_call():
    run = run_predicate(ROWS, PRED, cheap=Stub(False), champion=Stub(True), jev=None,
                        sample=4, batch=25, tolerance=0.02)
    gold = {PRED: {i: (i in TRUTH) for i in range(len(ROWS))}}
    again = rescore({"predicates": [run]}, gold, tolerance=0.02)[0]
    assert again["yardstick"] == "gold"
    assert again["arms"]["banded"]["accuracy_vs_gold"] == 1.0
    assert again["arms"]["banded"]["kept_rows"] == run["arms"]["banded"]["kept_rows"]
