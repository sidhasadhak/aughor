"""HB-2's falsifier — the departure-precision ratchet: a change that lowers a departure
kind's precision cannot ship.

The gate is deterministic, so its precision over a labeled corpus is exact: every case
below IS the baseline, and a case whose verdict flips is a shipped regression — red, not
a number drifting in a report. Grown the vocabulary-ratchet way: a PR may ADD cases
(tightening the gate's contract), never relabel one to get past this file. The corpus
includes the 2026-09-16 live incident verbatim — the brief that departed flagged NOT
reliable — because a falsifier anchored to a real failure cannot be argued away.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.govern.departure import TRUST_BANNER, gate_departure

#: The live 2026-09-16 message's opening, verbatim from #aughor_canvas (13:42) — the
#: departure this gate exists to make impossible.
LIVE_INCIDENT = (
    "⚠️ A trust check flagged the evidence and the figures below are NOT reliable: "
    "metric formula drift: the finding asserts Revenue but the query computes it a "
    "different way (it reads 'order_items'), so this number is not Revenue as your "
    "organisation defines it Do not read the numbers or ranking as fact until they are "
    "recomputed. Observed 2026-09-08 — the most recent complete day…")

#: (check kind, case name, gate kwargs, expected state). `tieout:*` cases run under a
#: stubbed validator (deterministic by metric name); everything else is pure text.
CORPUS: list[tuple[str, str, dict, str]] = [
    ("trust", "the live 2026-09-16 incident, verbatim",
     dict(text=LIVE_INCIDENT), "held"),
    ("trust", "a reframed brief with any caveat",
     dict(text=f"⚠ {TRUST_BANNER} and the figures below are NOT reliable: "
               f"fan-out corrupts the ratio. Do not read the numbers. Meta fell 22%."),
     "held"),
    ("trust", "banner mid-text still holds (position is not load-bearing)",
     dict(text=f"Weekly summary. {TRUST_BANNER} and the figures below are NOT reliable: x."),
     "held"),
    ("clean", "an ordinary all-quiet message departs",
     dict(text="All metrics nominal today; nothing unusual to report."), "departed"),
    ("clean", "a message that merely mentions trust checks departs",
     dict(text="Our trust checks all passed this week; numbers are steady."), "departed"),
    ("tieout", "a failing tie-out on an asserted governed metric holds",
     dict(text="Revenue reached 4,100 this week.", conn_id="c1"), "held"),
    ("tieout", "a passing tie-out departs",
     dict(text="AOV held at 96 this week.", conn_id="c1"), "departed"),
    ("tieout", "an asserted metric with no quality tests departs",
     dict(text="Churn was 3.1% this week.", conn_id="c1"), "departed"),
    ("probation", "a declared new automation's clean send goes to its declarer",
     dict(text="All quiet.", probation=True, declared_by="user:ana"), "held_probation"),
    ("probation", "probation with no declarer is inert (identity off)",
     dict(text="All quiet.", probation=True, declared_by=""), "departed"),
    ("probation", "an accuracy hold outranks probation",
     dict(text=f"⚠ {TRUST_BANNER}: bad. Do not read.", probation=True,
          declared_by="user:ana"), "held"),
]

_METRICS = [
    SimpleNamespace(name="revenue", label="Revenue", sql="SUM(total_amount)",
                    tables=["orders"], dimensions=[],
                    quality_tests=["SELECT COUNT(*)=0 FROM orders WHERE total_amount IS NULL"],
                    wrong_usage_examples=[]),
    SimpleNamespace(name="aov", label="AOV", sql="AVG(total_amount)",
                    tables=["orders"], dimensions=[],
                    quality_tests=["SELECT AVG(total_amount) > 0 FROM orders"],
                    wrong_usage_examples=[]),
    SimpleNamespace(name="churn", label="Churn", sql="1 - retention",
                    tables=["accounts"], dimensions=[], quality_tests=[],
                    wrong_usage_examples=[]),
]

#: The stub validator's table: revenue's tie-out FAILS, aov's passes — fixed facts the
#: corpus labels are written against.
_VALIDATES = {"revenue": False, "aov": True}


@pytest.fixture()
def _stubbed(monkeypatch):
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **_: list(_METRICS))
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: object())
    monkeypatch.setattr(
        "aughor.semantic.metrics.validate_metric",
        lambda m, db: SimpleNamespace(passed=_VALIDATES.get(m.name, True),
                                      message="stubbed"))


@pytest.mark.parametrize("check, name, kw, expected",
                         CORPUS, ids=[c[1] for c in CORPUS])
def test_the_gate_judges_every_corpus_case_as_labeled(_stubbed, check, name, kw, expected):
    v = gate_departure(kind="slack_post", org_id="default",
                       conn_id=kw.pop("conn_id", ""),
                       automation_id="ratchet", automation_name="Ratchet", target="#ops",
                       **kw)
    assert v.state == expected, (
        f"[{check}] {name}: the gate said {v.state!r}, the baseline says {expected!r} — "
        f"a flipped corpus verdict is a shipped precision regression (relabeling the "
        f"case instead of fixing the gate defeats the ratchet)")


def test_every_check_kind_has_hold_and_depart_coverage():
    """A vacuous corpus cannot ratchet: each gate check must appear with at least one
    held case and one departed case somewhere in the corpus (clean cases are the
    depart side of `trust`)."""
    by_kind: dict[str, set] = {}
    for check, _name, _kw, expected in CORPUS:
        kind = "trust" if check == "clean" else check
        by_kind.setdefault(kind, set()).add(
            "held" if expected != "departed" else "departed")
    for kind in ("trust", "tieout", "probation"):
        assert by_kind.get(kind) == {"held", "departed"}, (
            f"corpus lost {kind} coverage: {by_kind.get(kind)}")


def test_the_live_incident_stays_in_the_corpus():
    """The anchor case cannot be quietly dropped or diluted."""
    assert any("2026-09-16" in name and kw.get("text") == LIVE_INCIDENT
               for _c, name, kw, _e in CORPUS)
    assert "NOT reliable" in LIVE_INCIDENT and "order_items" in LIVE_INCIDENT
