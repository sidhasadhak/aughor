"""JD-3 — bands, not batches, in `semantic_filter`'s cascade. Faux providers, no model call.

The sampled cascade re-runs EVERY row on the champion when a sample disagrees. The banded path
(flag `semops.banded_cascade`, default off) judges each row through JD-1's seam and spends the
champion only on rows inside the uncertainty band. What is pinned:

* OFF, or no cascade asked for: the code that ran before, untouched;
* ON: confident rows are decided by the cheap tier, and only the uncertain ones reach the
  champion — fewer champion questions than rows, which is the claim the receipt will price;
* a row still uncertain after the champion is KEPT and named for a person, never guessed;
* a cheap call that fails leaves its rows unanswered and escalated — not silently kept.
"""
from __future__ import annotations

import pytest

from aughor.agent.state import QueryResult
from aughor.semops import operators as ops
from aughor.semops.operators import semantic_filter


class FakeJudge:
    """Answers a JD-1 bundle: each field `r<gi>` gets `prob(gi)`, or the call raises."""

    def __init__(self, prob=None, *, fail=False):
        self.prob, self.fail, self.calls, self.asked = prob, fail, 0, []

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.calls += 1
        fields = list(response_model.model_fields)
        self.asked.extend(int(f[1:]) for f in fields)
        if self.fail:
            raise RuntimeError("cheap tier unavailable")
        return response_model(**{f: self.prob(int(f[1:])) for f in fields})


def _qr(n):
    return QueryResult(hypothesis_id="t", sql="SELECT 1", columns=["note"],
                       rows=[[f"row {i}"] for i in range(n)], row_count=n)


def _route(monkeypatch, cheap, champ):
    monkeypatch.setattr(ops, "get_provider",
                        lambda role="fast", **kw: champ if role == "coder" else cheap)


@pytest.fixture
def banded(monkeypatch):
    monkeypatch.setenv("AUGHOR_SEMOPS_BANDED_CASCADE", "1")


# 10 rows: 0-3 confidently keep, 4-6 confidently drop, 7-9 uncertain.
def _cheap_p(gi):
    return 0.95 if gi < 4 else 0.05 if gi < 7 else 0.5


def test_off_by_default_the_sampled_cascade_runs_unchanged(monkeypatch):
    cheap, champ = FakeJudge(_cheap_p), FakeJudge(lambda gi: 0.9)
    _route(monkeypatch, cheap, champ)
    monkeypatch.delenv("AUGHOR_SEMOPS_BANDED_CASCADE", raising=False)
    out = semantic_filter(_qr(10), "note", "keepers", validate_sample=4)
    # Asserted by each path's OWN note, not by an exception: the old path swallows provider
    # errors (it never raises into the query path), so "it raised" could not tell the paths
    # apart, and any bug inside the banded code would have passed too.
    assert any(n.startswith("champion cascade:") for n in out.notes)
    assert not any("banded cascade" in n for n in out.notes)


def test_no_cascade_asked_for_means_no_banding_even_with_the_flag_on(monkeypatch, banded):
    """Banding replaces the SAMPLED cascade; where none was requested there is nothing to
    replace, and the operator must behave exactly as before."""
    cheap, champ = FakeJudge(_cheap_p), FakeJudge(lambda gi: 0.9)
    _route(monkeypatch, cheap, champ)
    out = semantic_filter(_qr(10), "note", "keepers", validate_sample=0)
    assert not any("banded cascade" in n for n in out.notes)
    assert champ.calls == 0


def test_only_the_uncertain_rows_reach_the_champion(monkeypatch, banded):
    cheap, champ = FakeJudge(_cheap_p), FakeJudge(lambda gi: 0.9)
    _route(monkeypatch, cheap, champ)
    out = semantic_filter(_qr(10), "note", "keepers", validate_sample=4)
    assert sorted(champ.asked) == [7, 8, 9], "the champion was asked about rows it did not need"
    assert out.result.row_count == 7          # 0-3 by the cheap tier, 7-9 by the champion
    assert [r[0] for r in out.result.rows] == [f"row {i}" for i in (0, 1, 2, 3, 7, 8, 9)]
    assert any("3 uncertain row(s)" in n and "instead of all 10" in n for n in out.notes)


def test_a_row_still_uncertain_after_the_champion_is_kept_for_a_person(monkeypatch, banded):
    cheap, champ = FakeJudge(_cheap_p), FakeJudge(lambda gi: 0.5)
    _route(monkeypatch, cheap, champ)
    out = semantic_filter(_qr(10), "note", "keepers", validate_sample=4)
    kept = {r[0] for r in out.result.rows}
    assert {"row 7", "row 8", "row 9"} <= kept, "an undecided row was dropped — a guess"
    assert any("left for a person" in n and "[7, 8, 9]" in n for n in out.notes)


def test_a_failed_cheap_call_escalates_its_rows_instead_of_keeping_them_blind(monkeypatch,
                                                                            banded):
    cheap, champ = FakeJudge(fail=True), FakeJudge(lambda gi: 0.9 if gi % 2 == 0 else 0.1)
    _route(monkeypatch, cheap, champ)
    out = semantic_filter(_qr(6), "note", "keepers", validate_sample=4)
    assert sorted(champ.asked) == list(range(6))
    assert [r[0] for r in out.result.rows] == ["row 0", "row 2", "row 4"]


def test_the_band_lives_in_code():
    assert ops._band(0.70) == "keep" and ops._band(0.30) == "drop"
    assert ops._band(0.5) == "uncertain" and ops._band(None) == "unanswered"
