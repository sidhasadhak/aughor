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


def test_directive_demands_the_lenses_and_forbids_the_verdict():
    d = loss_signal_directive("Where are we losing money?", _SCHEMA)
    assert "refund" in d and "total_seats" in d
    assert "LEAKAGE" in d and "UTILIZATION" in d
    assert "never" in d and "no losses" in d          # the honesty clause
    assert "revenue ranking" in d                      # names the failure mode


def test_directive_is_empty_when_inapplicable():
    assert loss_signal_directive("revenue by region", _SCHEMA) == ""


def test_flag_defaults_off():
    from aughor.kernel.flags import FLAG_ENV, flag_enabled
    assert "intake.loss_signals" in FLAG_ENV
    assert flag_enabled("intake.loss_signals") is False


def test_starter_question_names_the_loss_lenses():
    from aughor.starters import STARTERS
    q = next(s.question for s in STARTERS if s.id == "where_are_we_losing_money")
    for token in ("refunds", "share of gross", "utilization", "profitable"):
        assert token in q, token
