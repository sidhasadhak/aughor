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
    lifecycle_directive,
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


# The real schema block's shape (`TABLE: name` + indented `col TYPE`) — the lifecycle
# rule names a table.column, so the parse has to survive this format exactly.
_SCHEMA_BLOCK = """
TABLE: flights  (1,981 rows)
  flight_id  VARCHAR
  haul  VARCHAR
  total_seats  BIGINT
  status  VARCHAR
TABLE: tickets  (273,878 rows)
  ticket_id  VARCHAR
  flight_id  VARCHAR
  refund_amount  DOUBLE
  segment_status  VARCHAR
TABLE: sales_customers  (500 rows)
  customer_id  VARCHAR
  state  VARCHAR
"""


def test_lifecycle_columns_are_detected_qualified():
    """The rule filters a specific table at its own grain, so the column must arrive
    qualified. `state` on a customers table is a US state — detected here, but the
    probe declines to pin it because no value reads as cancelled."""
    sig = detect_loss_signals("Where are we losing money?", _SCHEMA_BLOCK)
    assert sig is not None
    assert "tickets.segment_status" in sig["lifecycle"]
    assert "flights.status" in sig["lifecycle"]
    assert "sales_customers.state" in sig["lifecycle"]
    assert lifecycle_directive({"sales_customers.state": ["CA", "NY"]}) == ""


def test_lifecycle_column_scan_ignores_words_that_merely_contain_state():
    from aughor.agent.loss_signals import LIFECYCLE_COL_RE
    for col in ("status", "segment_status", "order_state", "lifecycle_stage"):
        assert LIFECYCLE_COL_RE.search(col), col
    for col in ("real_estate", "estate_id", "statement_date"):
        assert not LIFECYCLE_COL_RE.search(col), col


def test_lifecycle_directive_pins_the_reading_off_probed_values():
    """The whole point: 'paid units' was the planner's call and moved the claim between
    77.7/79.4 and 78.0/80.8. Naming the values removes the choice."""
    d = lifecycle_directive({
        "tickets.segment_status": ["cancelled", "flown", "no_show"],
        "flights.status": ["cancelled", "scheduled"],
    })
    assert "tickets.segment_status: KEEP 'flown'" in d
    assert "EXCLUDE 'cancelled', 'no_show'" in d
    assert "flights.status: KEEP 'scheduled' — EXCLUDE 'cancelled'" in d
    assert "double-counts" in d          # the leakage overlap is stated, not implied


def test_lifecycle_directive_is_silent_when_it_would_pin_nothing():
    """No cancel-like value ⇒ no rule (a `state` column of US states). All values
    cancel-like ⇒ no rule either — an empty numerator is not a reading."""
    assert lifecycle_directive({"c.state": ["CA", "NY", "TX"]}) == ""
    assert lifecycle_directive({"t.status": ["cancelled", "voided"]}) == ""
    assert lifecycle_directive({}) == ""


def test_utilization_claim_is_pinned_to_a_low_cardinality_grouping():
    """The A/B's finding, test-locked. "The most decision-relevant segment" let the
    planner group the claim by route_id (84 routes, 0/4 material); naming the grain
    explicitly took it to 4/4 at the haul level. The evidence query keeps the named
    units, so the group carries the claim and the routes illustrate it."""
    util = [s for s in lens_specs({"capacity": ["total_seats"]}, "net revenue")
            if s["kind"] == "utilization"][0]
    ps = util["plan_system"]
    assert "LOW-CARDINALITY" in ps and "THE CLAIM" in ps
    assert "NEVER group the claim by a high-cardinality identifier" in ps
    assert "THE EVIDENCE" in ps and "LIMIT 10" in ps
    # The grain guard that held across both arms must survive the rewrite.
    assert "COUNT CAPACITY EXACTLY ONCE" in ps


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
    assert not util.get("volume_is_money")          # seats are counted units → z-test applies


def test_lifecycle_filter_is_scoped_to_the_consumption_lens():
    """Caught by the A/B, and it was silent: every refund sits on a CANCELLED ticket, so
    handing the leakage lens the utilization rule ("keep 'flown'") filters away all 2.38M
    CHF of leakage and reports 0.0% with a straight face. The rule defines which units
    consumed CAPACITY — it says nothing about which units leaked money."""
    specs = {s["kind"]: s for s in lens_specs(
        {"contra_revenue": ["refund_chf"], "capacity": ["total_seats"]}, "net revenue")}
    assert specs["utilization"].get("lifecycle_filter") is True
    assert not specs["leakage"].get("lifecycle_filter")


def test_leakage_opportunity_is_money_and_benchmarks_downward():
    """Its `n` is now the gross the rate is a share of, so gap x volume is CHF. Higher
    leakage is worse, and the volume is an amount — not Bernoulli trials."""
    specs = {s["kind"]: s for s in lens_specs(
        {"contra_revenue": ["refund_chf"], "capacity": ["total_seats"]}, "load factor")}
    leak = specs["leakage"]
    assert "SUM(<gross amount>) AS n" in leak["plan_system"]
    assert "never a row count" in leak["plan_system"]
    assert "LOW-CARDINALITY" in leak["plan_system"]
    opp = leak["opportunity"]
    assert opp["lower_is_better"] is True
    assert opp["volume_is_denominator"] is True and opp["volume_is_money"] is True
    assert opp["volume_label"] == "CHF"             # derived from `refund_chf`
    # No currency token in the column names ⇒ an honest generic, never a guessed symbol.
    generic = [s for s in lens_specs({"contra_revenue": ["discount_value"]}, "load factor")
               if s["kind"] == "leakage"][0]
    assert generic["opportunity"]["volume_label"] == "of gross"


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


def test_flag_defaults_on():
    """Graduated 2026-07-22 (flag-drift audit, Batch 1). This one fixes a WRONG ANSWER, not
    a presentation nicety: the A/B that motivated it caught a revenue ranking calling the
    business "broadly healthy" over 2.4M CHF of refund leakage. Leaving it off by default
    meant every install except one kept giving that answer."""
    from aughor.kernel.flags import FLAG_DEFAULT, FLAG_ENV, flag_enabled
    assert "intake.loss_signals" in FLAG_ENV
    assert FLAG_DEFAULT.get("intake.loss_signals") is True
    assert flag_enabled("intake.loss_signals") is True


def test_starter_question_names_the_loss_lenses():
    from aughor.starters import STARTERS
    q = next(s.question for s in STARTERS if s.id == "where_are_we_losing_money")
    for token in ("refunds", "share of gross", "utilization", "profitable"):
        assert token in q, token


_CATALOG_BLOCK = """
## flights

| Column | Type | Nullable |
|---|---|---|
| flight_id | VARCHAR | YES |
| haul | VARCHAR | YES |
| total_seats | BIGINT | YES |
| status | VARCHAR | YES |

## tickets

| Column | Type | Nullable |
|---|---|---|
| ticket_id | VARCHAR | YES |
| refund_amount | DOUBLE | YES |
| segment_status | VARCHAR | YES |
"""


def test_lifecycle_detection_parses_the_data_catalog_format():
    """The deep path's schema_context is the markdown Data Catalog (## table + | col |
    rows), not the TABLE: block format — and the parser knowing only the latter made the
    lifecycle pin silently detect NOTHING on every live deep run (gates log lifecycle:0)
    while the format-agnostic contra/capacity scans kept firing. Both formats parse now."""
    sig = detect_loss_signals("Where are we losing money?", _CATALOG_BLOCK)
    assert sig is not None
    assert "flights.status" in sig["lifecycle"]
    assert "tickets.segment_status" in sig["lifecycle"]
    # The markdown header row is not a column.
    assert all(not c.endswith(".Column") for c in sig["lifecycle"])
