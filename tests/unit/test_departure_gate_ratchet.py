"""HB-2's falsifier — the departure-precision ratchet: a change that lowers a departure
kind's precision cannot ship.

The gate is deterministic, so its precision over a labeled corpus is exact: every case
below IS the baseline, and a case whose verdict flips is a shipped regression — red, not
a number drifting in a report. Grown the vocabulary-ratchet way: a PR may ADD cases
(tightening the gate's contract), never relabel one to get past this file. The corpus
includes the 2026-09-16 live incidents verbatim — the brief that departed flagged NOT
reliable, and the dispatch watch that departed an order count as a count of order lines —
because a falsifier anchored to a real failure cannot be argued away.

The remainder of the wave (laws 1, 2, 4, 5, 6, 7) ADDED cases and relabeled none. One
fixture fact was made explicit rather than left implied: the metrics the tie-out cases call
"governed" now say they are approved. Before law 2 the stubs carried no lifecycle at all,
which the real `MetricDefinition` reads as a draft — and a draft is not governed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from aughor.govern.departure import TRUST_BANNER, Measurement, gate_departure

#: The live 2026-09-16 message's opening, verbatim from #aughor_canvas (13:42) — the
#: departure this gate exists to make impossible.
LIVE_INCIDENT = (
    "⚠️ A trust check flagged the evidence and the figures below are NOT reliable: "
    "metric formula drift: the finding asserts Revenue but the query computes it a "
    "different way (it reads 'order_items'), so this number is not Revenue as your "
    "organisation defines it Do not read the numbers or ranking as fact until they are "
    "recomputed. Observed 2026-09-08 — the most recent complete day…")

#: The live 2026-09-16 dispatch-promise watch, verbatim (automation 9c018203, Slack ts
#: 1789589393.985159). 99,441 is Olist's ORDER count — the delivery promise's objects —
#: stated as dispatch-promise order lines; the promise it is about counted 111,456.
LIVE_DISPATCH = (
    "⚠ Dispatch promise breached: 10,423 of 99,441 order lines (9.35%) missed the declared "
    "dispatch window, measured as of 2018-09-11 on the Olist connection. Declared segment: "
    "late_orders. This finding is filed on promise:order_to_delivery.dispatch — receipt: "
    "GET /links?object_ref=promise:order_to_delivery.dispatch")

DISPATCH = "promise:order_to_delivery.dispatch"


def _olist_dispatch_stamp() -> Measurement:
    """The dispatch promise's stamp as the live API served it on 2026-09-17."""
    return Measurement(
        source="promise dispatch of order_to_delivery",
        values=[112650.0, 111456.0, 10423.0, 101033.0, 1194.0, 1193.0], rates=[0.093517],
        measured_at="2026-09-13T00:05:20+00:00", as_of="2018-09-11 19:48:28",
        definition="promise dispatch (declared)",
        stale_note="a promise is re-measured by the ontology's measure pass, not at a send")


def _fresh(*values):
    """A measurement taken at the moment the case runs, holding exactly these values."""
    def build() -> Measurement:
        return Measurement(source="stub analysis", values=[float(v) for v in values],
                           measured_at=datetime.now(timezone.utc).isoformat())
    return build


def _stale_then(*fresh_values):
    """A measurement three days old whose re-execution at departure reads these values."""
    def build() -> Measurement:
        return Measurement(source="stub analysis", values=[4100.0],
                           measured_at="2020-01-01T00:00:00Z",
                           remeasure=lambda _claims: ([float(v) for v in fresh_values], []))
    return build


_REFUND_READINGS = {
    "subject": "definition of refund rate", "metric_label": "refund rate",
    "metric_name": "refund_rate", "options": ["Governed: refund_rate", "As I read the question"],
    "previews": ["= 2.10%", "= 7.80%"],
    "readings": [{"label": "Governed: refund_rate", "sql": "SUM(refunds)/COUNT(*)"},
                 {"label": "As I read the question", "sql": "SUM(refund_value)/SUM(value)"}]}

#: (check kind, case name, gate kwargs, expected state). `tieout:*` cases run under a
#: stubbed validator (deterministic by metric name); everything else is pure text plus the
#: stubbed stores the fixture below declares. A callable `measurement` is built when the
#: case runs; `after` departs a first message from the same source to the same place.
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

    # ── law 2 — definition ────────────────────────────────────────────────────────
    ("definition", "a draft metric stated with a number holds",
     dict(text="Margin reached 41.2% this week.", conn_id="c1"), "held"),
    ("definition", "a well-known KPI with no approved metric behind it holds",
     dict(text="Conversion rate was 3.4% yesterday.", conn_id="c1"), "held"),
    ("definition", "a monitor's own declaration defines the number it measured",
     dict(text="Conversion rate [critical]: 2.1% vs threshold 3%", conn_id="c1",
          declared_definition="monitor 'Conversion rate' (declared)"), "departed"),
    ("definition", "a message about an undeclared promise holds",
     dict(text="Dispatch promise breached on 12.5% of lines.", conn_id="c1",
          about="promise:ghost.dispatch"), "held"),
    ("definition", "a message about a declared, measured promise departs",
     dict(text="Dispatch promise breached on 9.35% of order lines.", conn_id="c1",
          about=DISPATCH, measurement=_olist_dispatch_stamp), "departed"),

    # ── law 1 — re-measure ────────────────────────────────────────────────────────
    ("remeasure", "the live 2026-09-16 dispatch watch, verbatim — an order count as lines",
     dict(text=LIVE_DISPATCH, conn_id="baef6c3e", about=DISPATCH,
          measurement=_olist_dispatch_stamp), "held"),
    ("remeasure", "the same watch stating the promise's own counts departs",
     dict(text=LIVE_DISPATCH.replace("99,441", "111,456"), conn_id="baef6c3e", about=DISPATCH,
          measurement=_olist_dispatch_stamp), "departed"),
    ("remeasure", "a magnitude with no measurement behind it holds",
     dict(text="Reminder: 1,200 invoices are still pending."), "held"),
    ("remeasure", "a stale measurement re-executed at departure holds a number that moved",
     dict(text="Orders reached 4,100 this week.", measurement=_stale_then(4600)), "held"),
    ("remeasure", "a stale measurement that re-executes to the same number departs",
     dict(text="Orders reached 4,100 this week.", measurement=_stale_then(4100)), "departed"),

    # ── law 4 — freshness ─────────────────────────────────────────────────────────
    ("freshness", "a governed metric whose data breaches its declared SLA holds",
     dict(text="GMV reached 5.2M this week.", conn_id="c1", measurement=_fresh(5_200_000)),
     "held"),
    ("freshness", "a governed metric inside its declared SLA departs",
     dict(text="NMV reached 4.9M this week.", conn_id="c1", measurement=_fresh(4_900_000)),
     "departed"),

    # ── law 5 — claim type ────────────────────────────────────────────────────────
    ("claims", "a forecast never departs",
     dict(text="Order volume is on track to double by December."), "held"),
    ("claims", "a causal claim with no analysis behind it holds",
     dict(text="The price change drove fewer repeat orders this week."), "held"),
    ("claims", "a causal claim on its analysis's causal licence departs",
     dict(text="The price change drove fewer repeat orders this week.",
          investigation_id="inv-causal"), "departed"),
    ("claims", "a refuted analysis withdraws its causal claim",
     dict(text="The price change drove fewer repeat orders this week.",
          investigation_id="inv-refuted"), "held"),
    ("claims", "a negated causal sentence is a description",
     dict(text="Shipping delay was not driven by the carrier."), "departed"),
    ("claims", "an associational claim on its analysis's licence departs",
     dict(text="Late deliveries are correlated with the northern region.",
          investigation_id="inv-assoc"), "departed"),

    # ── law 6 — disagreement ──────────────────────────────────────────────────────
    ("disagreement", "divergent readings ask the owner and send nothing",
     dict(text="Refund rate needs a reading before it can be sent.", conn_id="c1",
          disagreement=_REFUND_READINGS), "held_owner"),
    ("disagreement", "no divergent readings, nothing to ask",
     dict(text="Refund volume is steady.", conn_id="c1"), "departed"),

    # ── law 7 — repeat and the noise band ─────────────────────────────────────────
    ("repeat", "the same message twice to the same place holds",
     dict(text="Nightly load finished without errors.",
          after="Nightly load finished without errors."), "held"),
    ("repeat", "a repeat whose numbers moved within the noise band holds",
     dict(text="Orders reached 4,110 today.", measurement=_fresh(4110),
          after=("Orders reached 4,100 today.", _fresh(4100))), "held"),
    ("repeat", "a repeat whose numbers moved past the noise band departs",
     dict(text="Orders reached 4,600 today.", measurement=_fresh(4600),
          after=("Orders reached 4,100 today.", _fresh(4100))), "departed"),
    ("repeat", "a monitor alert keeps its own anti-flap policy",
     dict(kind="monitor_alert", text="Nightly load finished without errors.",
          after="Nightly load finished without errors."), "departed"),
    ("repeat", "a person chose — sharing twice is not a repeat",
     dict(origin="person", text="Nightly load finished without errors.",
          after="Nightly load finished without errors."), "departed"),
]

_METRICS = [
    SimpleNamespace(name="revenue", label="Revenue", sql="SUM(total_amount)",
                    tables=["orders"], dimensions=[],
                    quality_tests=["SELECT COUNT(*)=0 FROM orders WHERE total_amount IS NULL"],
                    wrong_usage_examples=[], status="approved", version=1),
    SimpleNamespace(name="aov", label="AOV", sql="AVG(total_amount)",
                    tables=["orders"], dimensions=[],
                    quality_tests=["SELECT AVG(total_amount) > 0 FROM orders"],
                    wrong_usage_examples=[], status="approved", version=1),
    SimpleNamespace(name="churn", label="Churn", sql="1 - retention",
                    tables=["accounts"], dimensions=[], quality_tests=[],
                    wrong_usage_examples=[], status="approved", version=1),
    # law 2 — a definition still in review
    SimpleNamespace(name="margin", label="Margin", sql="1 - cost / revenue",
                    tables=["orders"], dimensions=[], quality_tests=[],
                    wrong_usage_examples=[], status="draft", version=0),
    # law 4 — two governed metrics with a declared SLA, one stale and one current
    SimpleNamespace(name="gmv", label="GMV", sql="SUM(gross_value)", tables=["orders"],
                    dimensions=[], quality_tests=[], wrong_usage_examples=[],
                    status="approved", version=3, freshness_sla="24h",
                    freshness_check_sql="SELECT MAX(created_at) FROM orders"),
    SimpleNamespace(name="nmv", label="NMV", sql="SUM(net_value)", tables=["orders"],
                    dimensions=[], quality_tests=[], wrong_usage_examples=[],
                    status="approved", version=3, freshness_sla="daily by 6am UTC",
                    freshness_check_sql="SELECT MAX(created_at) FROM orders"),
]

#: The stub validator's table: revenue's tie-out FAILS, aov's passes — fixed facts the
#: corpus labels are written against.
_VALIDATES = {"revenue": False, "aov": True}

#: How old each SLA-bearing metric's latest data is when a case runs.
_DATA_AGE = {"gmv": timedelta(days=3), "nmv": timedelta(hours=2)}

#: The stores laws 2, 5 and 6 read, stubbed to fixed facts.
_DECLARED = {DISPATCH: {"kind": "promise", "label": "promise dispatch of order_to_delivery",
                       "measured": True}}
_LICENCES = {"inv-causal": ("causal", False), "inv-refuted": ("causal", True),
             "inv-assoc": ("associational", False)}


@pytest.fixture()
def _stubbed(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **_: list(_METRICS))
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: object())
    monkeypatch.setattr(
        "aughor.semantic.metrics.validate_metric",
        lambda m, db: SimpleNamespace(passed=_VALIDATES.get(m.name, True),
                                      message="stubbed"))
    monkeypatch.setattr(
        "aughor.semantic.metrics.check_freshness",
        lambda m, db: SimpleNamespace(
            latest_data_at=(datetime.now(timezone.utc) - _DATA_AGE[m.name]).isoformat()))
    monkeypatch.setattr("aughor.govern.departure_basis.declared_thing",
                        lambda securable, conn_id: _DECLARED.get(securable))
    monkeypatch.setattr("aughor.govern.departure_basis.analysis_claim_facts",
                        lambda inv: _LICENCES.get(inv, ("", False)))
    monkeypatch.setattr("aughor.govern.departure_basis.owner_for_disagreement",
                        lambda d, conn_id: "group:finance" if d.get("metric_name") else "")


def _run(kw: dict):
    kw = dict(kw)
    measurement = kw.pop("measurement", None)
    return gate_departure(kind=kw.pop("kind", "slack_post"), org_id="default",
                          conn_id=kw.pop("conn_id", ""), automation_id="ratchet",
                          automation_name="Ratchet", target="#ops",
                          measurement=measurement() if callable(measurement) else measurement,
                          **kw)


@pytest.mark.parametrize("check, name, kw, expected",
                         CORPUS, ids=[c[1] for c in CORPUS])
def test_the_gate_judges_every_corpus_case_as_labeled(_stubbed, check, name, kw, expected):
    kw = dict(kw)
    after = kw.pop("after", None)
    if after is not None:
        first_text, first_measurement = after if isinstance(after, tuple) else (after, None)
        first = _run({**kw, "text": first_text, "measurement": first_measurement})
        assert first.state == "departed", (
            f"[{check}] {name}: the FIRST send must depart for the repeat case to mean "
            f"anything — it was {first.state}: {first.reason_sentence()}")
    v = _run(kw)
    assert v.state == expected, (
        f"[{check}] {name}: the gate said {v.state!r}, the baseline says {expected!r} — "
        f"a flipped corpus verdict is a shipped precision regression (relabeling the "
        f"case instead of fixing the gate defeats the ratchet). Reasons: "
        f"{v.reason_sentence() or '(none)'}")


def test_every_check_kind_has_hold_and_depart_coverage():
    """A vacuous corpus cannot ratchet: each gate check must appear with at least one
    held case and one departed case somewhere in the corpus (clean cases are the
    depart side of `trust`)."""
    by_kind: dict[str, set] = {}
    for check, _name, _kw, expected in CORPUS:
        kind = "trust" if check == "clean" else check
        by_kind.setdefault(kind, set()).add(
            "held" if expected != "departed" else "departed")
    for kind in ("trust", "tieout", "probation", "definition", "remeasure", "freshness",
                 "claims", "disagreement", "repeat"):
        assert by_kind.get(kind) == {"held", "departed"}, (
            f"corpus lost {kind} coverage: {by_kind.get(kind)}")


def test_the_live_incidents_stay_in_the_corpus():
    """The anchor cases cannot be quietly dropped or diluted."""
    assert any("2026-09-16" in name and kw.get("text") == LIVE_INCIDENT
               for _c, name, kw, _e in CORPUS)
    assert "NOT reliable" in LIVE_INCIDENT and "order_items" in LIVE_INCIDENT
    assert any("2026-09-16" in name and kw.get("text") == LIVE_DISPATCH and expected == "held"
               for _c, name, kw, expected in CORPUS)
    assert "99,441" in LIVE_DISPATCH and "10,423" in LIVE_DISPATCH
