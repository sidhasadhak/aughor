"""Loss-signal directive (flag `intake.loss_signals`) — deterministic tests.

The A/B finding: "where are we losing money" was reduced to a net-revenue ranking —
a lens that can only ever conclude "no losses" — over 2.4M CHF of refund leakage and
a 1.2M CHF utilization gap. The directive names the loss signals the schema carries
and forbids the profitability verdict profit-less data cannot support.
"""
from __future__ import annotations

from aughor.agent.loss_signals import (
    LOSS_INTENT_RE,
    detect_loss_signals,
    lens_specs,
    loss_signal_directive,
)

_SCHEMA = """
bookings(booking_id, channel, cabin, total_fare_chf, total_taxes_chf, n_passengers)
refunds(refund_id, booking_id, refund_chf, reason, refund_date)
flights(flight_id, route_id, haul, aircraft_type, total_seats, delay_minutes)
tickets(ticket_id, flight_id, fare_chf, cabin)
"""


def test_loss_intent_matches_the_starter_and_siblings():
    for q in ("Where are we losing money?",
              "why is margin erosion accelerating",
              "find revenue leakage by channel",
              "which units are underperforming"):
        assert LOSS_INTENT_RE.search(q), q
    for q in ("total revenue by region", "top customers by GMV"):
        assert not LOSS_INTENT_RE.search(q), q


def test_detect_names_the_signals_this_schema_carries():
    sig = detect_loss_signals("Where are we losing money?", _SCHEMA)
    assert sig is not None
    assert any("refund" in c for c in sig["contra_revenue"])
    assert any("total_seats" in c for c in sig["capacity"])


def test_detect_is_silent_without_intent_or_signals():
    assert detect_loss_signals("revenue by region", _SCHEMA) is None
    assert detect_loss_signals("Where are we losing money?",
                               "orders(order_id, region, revenue)") is None


def test_optimization_phrasings_reach_the_same_lenses():
    """The flip question. "Where are we losing money?" and "where can we optimise?" ask
    the same thing of the same columns — a revenue ranking answers neither."""
    for q in (
        "Where can we optimise?",
        "What's our biggest opportunity to improve margins?",
        "Where should we focus to do better?",
        "Which routes are underutilised?",
        "Is there headroom in our capacity?",
        "What's being left on the table?",
    ):
        assert detect_loss_signals(q, _SCHEMA) is not None, q


def test_ordinary_temporal_questions_are_not_hijacked():
    """Deliberately tight: bare "improve"/"efficiency" read as ordinary questions the
    loss lenses would distort."""
    for q in (
        "Did our load factor improve last quarter?",
        "How has efficiency changed since January?",
        "Which route has the highest revenue?",
    ):
        assert detect_loss_signals(q, _SCHEMA) is None, q


def test_utilization_spec_declares_a_sound_opportunity_and_leakage_does_not():
    """The utilization grid's `n` IS its rate's denominator, so gap x volume is
    unit-correct. The leakage grid's `n` is COUNT(*) while the denominator is gross —
    it must stay silent rather than ship a number with no unit."""
    specs = {s["kind"]: s for s in lens_specs(
        {"contra_revenue": ["refund_amount"], "capacity": ["total_seats"]}, "net revenue")}
    util = specs["utilization"]["opportunity"]
    assert util["volume_is_denominator"] is True
    assert util["lower_is_better"] is False
    assert util["volume_label"] == "seats"          # derived from `total_seats`
    assert "opportunity" not in specs["leakage"]


def test_directive_demands_the_lenses_and_forbids_the_verdict():
    d = loss_signal_directive("Where are we losing money?", _SCHEMA)
    assert "refund" in d and "total_seats" in d
    assert "LEAKAGE" in d and "UTILIZATION" in d
    assert "never" in d and "no losses" in d          # the honesty clause
    assert "revenue ranking" in d                      # names the failure mode


def test_directive_is_empty_when_inapplicable():
    assert loss_signal_directive("revenue by region", _SCHEMA) == ""


def test_lens_specs_cover_what_the_primary_metric_leaves_uncovered():
    from aughor.agent.loss_signals import lens_specs
    sig = {"contra_revenue": ["refund_chf", "refunds"], "capacity": ["total_seats"]}
    # Primary = revenue ranking → BOTH loss lenses are owed.
    both = lens_specs(sig, "net revenue SUM(bookings.total_fare_chf)")
    assert [s["kind"] for s in both] == ["leakage", "utilization"]
    # Primary = load factor → only the leakage story is untold.
    leak_only = lens_specs(sig, "Load factor (seat utilization rate)")
    assert [s["kind"] for s in leak_only] == ["leakage"]
    # Primary = refund rate → only utilization is owed.
    util_only = lens_specs(sig, "refund rate SUM(refund_chf)/SUM(total_fare_chf)")
    assert [s["kind"] for s in util_only] == ["utilization"]
    # No signals → nothing owed.
    assert lens_specs(None, "anything") == []


def test_lens_specs_carry_the_grain_guards_and_honesty():
    from aughor.agent.loss_signals import lens_specs
    sig = {"contra_revenue": ["refund_chf"], "capacity": ["total_seats"]}
    leak, util = lens_specs(sig, "net revenue")
    # Ratio-of-sums + own-grain aggregation — the fan-out prevention, in the prompt.
    assert "ratio of sums" in leak["plan_system"]
    assert "EXACTLY ONCE" in util["plan_system"] or "exactly once" in util["plan_system"].lower()
    # The detected columns reach the planner.
    assert "refund_chf" in leak["plan_ask"] and "total_seats" in util["plan_ask"]
    # Honesty clause on both interpreters.
    for s in (leak, util):
        assert "no losses" in s["interpret_system"]


def test_flag_defaults_off():
    from aughor.kernel.flags import FLAG_ENV, flag_enabled
    assert "intake.loss_signals" in FLAG_ENV
    assert flag_enabled("intake.loss_signals") is False


def test_starter_question_names_the_loss_lenses():
    from aughor.starters import STARTERS
    q = next(s.question for s in STARTERS if s.id == "where_are_we_losing_money")
    for token in ("refunds", "share of gross", "utilization", "profitable"):
        assert token in q, token
