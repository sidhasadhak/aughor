"""A metric's range reads as the range its text states — measured over every range the industry packages ship.

`business_profile/validate.py::stated_range` turns a metric's unit/range text into the bound the live checks hold
its value to: `audit_value_sql` blanks a KPI whose scalar falls outside it, and `is_degenerate_result` drops a
finding whose rate column overshoots it. It tested for "percent" before "ratio", and for the bare word "ratio"
anywhere, so the ranges `packs/<industry>/industry.json` ships were misread (measured on main `21a4484f`,
2026-09-17 — 11 of the 50 held to a bound their text does not state):

- "ratio 0..1 (0..100%)" read as a 0..100 percent — airline load factor, on-time performance and cancellation
  rate, food-delivery take rate, saas trial conversion — so an impossible 1.4 passed;
- "ratio, typically 0.8..1.4" (NRR), "LTV:CAC ratio typically 3..5", "ratio ≥ 1" (orders per active user),
  "ratio 0..~4" (courier utilization) and "positive durations" (manufacturing downtime, whose "du-ratio-ns" matched)
  read as a 0..1 ratio, so a normal value failed;
- "hours per aircraft per day, 0..24" read as open, so an impossible 26 hours passed.

The population is every `sane_range` and `unit_or_range` string in the shipped files, read from disk; the reading
each one states is written below, and the two must cover each other exactly — a range added or reworded fails here
until someone states how it reads. The files are never edited to fit the reader: IP-1's parity fixture pins them.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aughor.business_profile.validate import stated_range, audit_value_sql, profile_metric_ranges
from aughor.explorer.verify import is_degenerate_result

#: The shipped packages — the repository's own, not the suite's temp copy of `packs/`.
PACKS = Path(__file__).resolve().parents[2] / "packs"


def _industry_metrics(pack: str) -> list[dict]:
    return json.loads((PACKS / pack / "industry.json").read_text(encoding="utf-8"))["metrics"]


def _shipped_ranges() -> list[tuple[str, str, str, str]]:
    """(package, metric, field, text) for every range string an industry package ships."""
    return [(path.parent.name, metric["name"], field, metric[field])
            for path in sorted(PACKS.glob("*/industry.json"))
            for metric in _industry_metrics(path.parent.name)
            for field in ("sane_range", "unit_or_range")
            if isinstance(metric.get(field), str)]


SHIPPED = _shipped_ranges()

RATIO = ("ratio01", 0.0, 1.0)
OPEN = ("open", None, None)

#: The reading each shipped range states, as (kind, lo, hi) — the phrase that decides it beside each.
INTENDED = {
    # airline
    ("airline", "Load Factor", "sane_range"): RATIO,                                # "ratio 0..1 (0..100%)"
    ("airline", "Revenue Passenger Kilometers/Miles vs Available Seat Kilometers/Miles (RPK/ASK)",
     "sane_range"): OPEN,                                                           # "large positive counts"
    ("airline", "On-Time Performance (OTP)", "sane_range"): RATIO,                  # "ratio 0..1 (0..100%)"
    ("airline", "Cancellation Rate", "sane_range"): RATIO,                          # "ratio 0..1 (0..100%)"
    ("airline", "Yield (Passenger Revenue per RPK/RPM)", "sane_range"): ("typical", 0.05, 0.2),  # "e.g. ~0.05–0.20"
    ("airline", "RASM / CASM (Unit Revenue / Unit Cost per ASM)", "sane_range"): ("typical", 10.0, 20.0),  # "typically ~10–20"
    ("airline", "Ancillary Revenue per Passenger", "sane_range"): ("typical", 5.0, 60.0),  # "typically ~5–60"
    ("airline", "Aircraft / Fleet Utilization (Block Hours per Aircraft per Day)",
     "sane_range"): ("band", 0.0, 24.0),                                            # "0..24 (physically capped at 24)"
    # food-delivery
    ("food-delivery", "Average Delivery Time", "sane_range"): ("typical", 20.0, 60.0),  # "typically 20–60 min"
    ("food-delivery", "Orders per Active User", "sane_range"): ("band", 1.0, None),     # "ratio ≥ 1"
    ("food-delivery", "Average Order Value (AOV)", "sane_range"): OPEN,             # "low tens to ~100"
    ("food-delivery", "Cancellation Rate", "sane_range"): RATIO,                    # "ratio 0..1"
    ("food-delivery", "Courier Utilization (Deliveries per Online Hour)",
     "sane_range"): ("typical", 0.0, 4.0),                                          # "0..~4 deliveries/hour typical"
    ("food-delivery", "Repeat / Retention Rate (Cohort)", "sane_range"): RATIO,     # "ratio 0..1"
    ("food-delivery", "Take Rate", "sane_range"): RATIO,                            # "ratio 0..1, typically … (10–30%)"
    ("food-delivery", "Courier Acceptance Rate", "sane_range"): RATIO,              # "ratio 0..1"
    # logistics
    ("logistics", "On-Time Delivery Rate (OTD)", "sane_range"): RATIO,              # "ratio 0..1 (never > 1)"
    ("logistics", "OTIF (On-Time In-Full)", "sane_range"): RATIO,                   # "ratio 0..1"
    ("logistics", "Average Transit Time", "sane_range"): OPEN,                      # "hours or days, strictly positive"
    ("logistics", "Cost per Shipment / Cost per Mile (km)", "sane_range"): OPEN,    # "currency per shipment"
    ("logistics", "Vehicle / Asset Capacity Utilization (Load Factor)", "sane_range"): RATIO,  # "ratio 0..1 (occasionally slightly >1"
    ("logistics", "First-Attempt Delivery Success Rate", "sane_range"): RATIO,      # "ratio 0..1"
    ("logistics", "Dwell Time", "sane_range"): OPEN,                                # "minutes to hours, non-negative"
    ("logistics", "Damage / Exception / Loss Rate", "sane_range"): RATIO,           # "ratio 0..1, typically very small (…)"
    ("logistics", "Deliveries per Route / Driver", "sane_range"): ("typical", 80.0, 200.0),  # "often 80–200"
    # manufacturing
    ("manufacturing", "Overall Equipment Effectiveness (OEE)", "sane_range"): RATIO,  # "ratio 0..1 (world-class ~0.85"
    ("manufacturing", "First Pass Yield (FPY) / Quality Rate", "sane_range"): RATIO,  # "ratio 0..1"
    ("manufacturing", "Scrap / Defect Rate (PPM)", "sane_range"): RATIO,            # "ratio 0..1; PPM 0..1,000,000" — stated first
    ("manufacturing", "Cycle Time vs Takt Time", "sane_range"): OPEN,               # "time per unit, strictly positive"
    ("manufacturing", "Throughput (Units per Period)", "sane_range"): OPEN,         # "units per period, non-negative"
    ("manufacturing", "Unplanned Downtime & MTBF / MTTR", "sane_range"): OPEN,      # "minutes/hours <= scheduled time"
    ("manufacturing", "Capacity Utilization", "sane_range"): RATIO,                 # "ratio 0..1 (commonly 0.6–0.9"
    ("manufacturing", "On-Time-In-Full (OTIF) / Schedule Adherence", "sane_range"): RATIO,  # "ratio 0..1"
    # retail
    ("retail", "Average Order Value (AOV)", "sane_range"): OPEN,                    # "USD, strictly positive"
    ("retail", "Cart-to-Order Conversion Rate", "sane_range"): RATIO,               # "ratio 0..1 (never > 1)"
    ("retail", "Gross Margin %", "sane_range"): ("pct100", 0.0, 100.0),             # "percent 0..100"
    ("retail", "Inventory Turnover", "sane_range"): OPEN,                           # "ratio 0..∞"
    ("retail", "Return / Refund Rate", "sane_range"): RATIO,                        # "ratio 0..1"
    ("retail", "Repeat Purchase Rate", "sane_range"): RATIO,                        # "ratio 0..1."
    ("retail", "Customer Acquisition Cost (CAC)", "sane_range"): OPEN,              # "USD, positive"
    ("retail", "ROAS (Return on Ad Spend) by Channel", "sane_range"): OPEN,         # "ratio 0..∞"
    # saas
    ("saas", "Monthly / Annual Recurring Revenue (MRR / ARR)", "sane_range"): OPEN,  # "currency, strictly positive"
    ("saas", "Net Revenue Retention (NRR / NDR)", "sane_range"): ("typical", 0.8, 1.4),  # "ratio, typically 0.8..1.4"
    ("saas", "Gross Revenue Churn Rate", "sane_range"): RATIO,                      # "ratio 0..1"
    ("saas", "Logo / Customer Churn Rate", "sane_range"): RATIO,                    # "ratio 0..1 (never > 1"
    ("saas", "Customer Acquisition Cost (CAC)", "sane_range"): OPEN,                # "currency, positive"
    ("saas", "Customer Lifetime Value (LTV) and LTV:CAC", "sane_range"): ("typical", 3.0, 5.0),  # "LTV:CAC ratio typically 3..5"
    ("saas", "Average Revenue Per Account / User (ARPA / ARPU)", "sane_range"): OPEN,  # "currency per account/user"
    ("saas", "CAC Payback Period", "sane_range"): OPEN,                             # "months, positive; healthy … <12"
    ("saas", "Activation / Trial-to-Paid Conversion Rate", "sane_range"): RATIO,    # "ratio 0..1 (never > 1)"
}


def test_every_shipped_range_has_a_stated_reading():
    shipped = {(pack, metric, field) for pack, metric, field, _ in SHIPPED}
    assert shipped, f"no range strings found under {PACKS}"
    assert sorted(shipped - set(INTENDED)) == [], "a shipped range has no stated reading"
    assert sorted(set(INTENDED) - shipped) == [], "a stated reading names a range no package ships"


@pytest.mark.parametrize("pack, metric, field, text", SHIPPED, ids=[f"{p}:{m}" for p, m, _, _ in SHIPPED])
def test_a_shipped_range_reads_as_it_states(pack, metric, field, text):
    assert stated_range(text) == INTENDED[(pack, metric, field)]


# ── The value_sql audit holds a KPI's scalar to the range read ───────────────────────────────────────────────


class _Scalar:
    """A connection that binds anything and returns one scalar, so the live range check alone decides."""
    dialect = "duckdb"

    def __init__(self, value: float):
        self._value = value

    def dry_run(self, _sql):
        return (True, "")

    def execute(self, _label, _sql):
        return SimpleNamespace(rows=[[str(self._value)]], error=None, columns=["v"])


def _sane_range(pack: str, metric: str) -> str:
    return next(m["sane_range"] for m in _industry_metrics(pack) if m["name"] == metric)


#: (package, metric, the value its SQL returned, whether the audit keeps it).
AUDITED = [
    # impossible — blanked
    ("airline", "Load Factor", 1.4, False),
    ("airline", "On-Time Performance (OTP)", 1.4, False),
    ("airline", "Cancellation Rate", 1.4, False),
    ("food-delivery", "Take Rate", 1.3, False),
    ("saas", "Activation / Trial-to-Paid Conversion Rate", 1.2, False),
    ("airline", "Aircraft / Fleet Utilization (Block Hours per Aircraft per Day)", 26.0, False),  # "> 24 is impossible"
    ("food-delivery", "Orders per Active User", 0.4, False),   # "A value < 1 means the denominator is wrong"
    # healthy — kept
    ("airline", "Load Factor", 0.82, True),
    ("food-delivery", "Take Rate", 0.18, True),
    ("saas", "Activation / Trial-to-Paid Conversion Rate", 0.2, True),
    ("saas", "Net Revenue Retention (NRR / NDR)", 1.1, True),
    ("saas", "Customer Lifetime Value (LTV) and LTV:CAC", 4.0, True),
    ("food-delivery", "Orders per Active User", 3.0, True),
    ("food-delivery", "Courier Utilization (Deliveries per Online Hour)", 2.5, True),
    ("airline", "Aircraft / Fleet Utilization (Block Hours per Aircraft per Day)", 11.5, True),
    # a typical band is not a bound: 75 minutes is outside "typically 20–60" and inside "Sub-5 or >180 … signals a
    # unit error", which is where the text puts impossible
    ("food-delivery", "Average Delivery Time", 75.0, True),
]


@pytest.mark.parametrize("pack, metric, value, kept", AUDITED, ids=[f"{p}:{m}={v}" for p, m, v, _ in AUDITED])
def test_the_value_sql_audit_holds_a_kpi_to_its_shipped_range(pack, metric, value, kept):
    ok, reason = audit_value_sql("SELECT 1 AS v", {}, _Scalar(value), _sane_range(pack, metric))
    assert ok is kept, reason


# ── A finding matched to a shipped metric is held to the range read ─────────────────────────────────────────


def _profile_ranges(pack: str) -> list[tuple]:
    """The ranges an explorer run reads from a profile whose north-star metrics carry the package's ranges."""
    return profile_metric_ranges(SimpleNamespace(north_star_metrics=[
        SimpleNamespace(name=m["name"], unit_or_range=m["sane_range"]) for m in _industry_metrics(pack)]))


#: (package, finding, sql, rows, whether the finding is dropped as degenerate).
FINDINGS = [
    ("airline", "load factor by route", "AS load_factor", [("JFK-LAX", "1.4"), ("SFO-SEA", "0.83")], True),
    ("food-delivery", "take rate by city", "AS take_rate", [("NYC", "1.31"), ("SF", "0.22")], True),
    ("saas", "net revenue retention by segment", "AS nrr", [("SMB", "1.08"), ("Enterprise", "1.21")], False),
    ("saas", "LTV to CAC by cohort", "AS ltv_cac", [("2024", "1.3"), ("2025", "1.4")], False),
    ("food-delivery", "orders per active user by city", "AS orders_per_active_user",
     [("NYC", "1.2"), ("SF", "1.4")], False),
    ("food-delivery", "courier utilization, deliveries per online hour", "AS deliveries_per_hour",
     [("NYC", "1.3"), ("SF", "1.2")], False),
    # A band bounds the metric's own scalar, not every column a finding returns beside it: 31 is the aircraft count.
    ("airline", "fleet utilization, block hours per aircraft per day by type", "AS block_hours_per_day, n_aircraft",
     [("A320", "11.2", "31"), ("B737", "10.4", "28")], False),
]


@pytest.mark.parametrize("pack, finding, sql, rows, dropped", FINDINGS, ids=[f[1] for f in FINDINGS])
def test_a_finding_is_held_to_its_matched_metrics_shipped_range(pack, finding, sql, rows, dropped):
    assert is_degenerate_result(rows, finding, sql, _profile_ranges(pack)) is dropped
