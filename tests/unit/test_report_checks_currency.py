"""A currency the narrator names must be one the run's evidence carries.

Live (1f925796, 2026-10-14): a theLook answer stated every figure in CHF — "385,389 CHF", "36,698
CHF" — over data that holds no currency at all. The only CHF in the whole run was the example in
the narrator's style rule ("168K CHF per flight"); the example lost its unit, and this check is
the guard."""
from __future__ import annotations

from types import SimpleNamespace

from aughor.agent.report_checks import check_currency, run_report_checks

EVIDENCE_NO_CURRENCY = ("=== Baseline ===\nSQL: SELECT month, SUM(sale_price) AS revenue FROM order_items\n"
                        "month | revenue\n2026-07 | 336383\n2026-08 | 385389")
EVIDENCE_EUR_COLUMN = ("=== Baseline ===\nSQL: SELECT ship_country, SUM(gmv_eur) AS revenue FROM orders\n"
                       "ship_country | revenue\nCanada | 370226.47")


def test_a_currency_code_no_result_carries_is_a_violation():
    out = check_currency("August revenue was 385,389 CHF, up from 336,383 CHF.", EVIDENCE_NO_CURRENCY)
    assert len(out) == 1 and "CHF" in out[0] and "#36" in out[0]
    assert out[0].disclosure == "the figures were stated in CHF, a currency no result of this run carries"


def test_a_code_the_evidence_carries_as_a_column_is_allowed():
    assert check_currency("Canada led at 370,226 EUR.", EVIDENCE_EUR_COLUMN) == []


def test_a_code_the_question_names_is_allowed():
    assert check_currency("Revenue was 385,389 USD.", EVIDENCE_NO_CURRENCY, "What was revenue in USD?") == []


def test_symbols_and_prose_without_a_code_say_nothing():
    assert check_currency("Revenue was $385,389, up from €336,383.", EVIDENCE_NO_CURRENCY) == []
    assert check_currency("", EVIDENCE_NO_CURRENCY) == [] and check_currency("No figures here.", "") == []


def test_the_runner_checks_the_recommendations_too():
    synth = SimpleNamespace(headline="August rose 14.6%", executive_summary="Revenue was 385,389, up from 336,383.",
                            closing_summary="", attribution_waterfall=[], data_gaps=[],
                            recommendations=[SimpleNamespace(action="Reconcile the two totals, 385,389 CHF and 336,383 CHF.",
                                                             expected_impact="")])
    out = run_report_checks(synth, "Why did revenue change in August?", EVIDENCE_NO_CURRENCY, phases=[], claim_type="")
    assert any("CHF" in v for v in out)
