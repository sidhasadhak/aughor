"""The explorer's coverage (2026-10-30) — the user: "firing 200, 300 or 500 queries in order to understand connection in
its absolute entirety". A run shares hundreds of questions across a dataset's domains; a period label is never summed as
a measure ("Summing fiscal_year gives 133,524" was kept as a finding on LuxExperience)."""
from __future__ import annotations

def test_a_run_shares_hundreds_of_questions_across_its_domains_and_each_gets_at_least_fifteen():
    from aughor.explorer.budget import COVERAGE_QUERIES, MIN_DOMAIN_QUESTIONS, domain_cap
    assert COVERAGE_QUERIES >= 200
    assert domain_cap(1) == COVERAGE_QUERIES                      # one domain (LuxExperience's): the whole run
    assert domain_cap(3) == COVERAGE_QUERIES // 3
    assert domain_cap(1000) == MIN_DOMAIN_QUESTIONS


def test_a_period_label_is_not_a_measure_to_sum():
    from types import SimpleNamespace

    from aughor.explorer.coverage_manifest import _measures
    col = lambda name: SimpleNamespace(column=name, semantic_type="measure", is_fk=False, value_range=(0, 1))  # noqa: E731
    kept = [c.column for c in _measures([col("fiscal_year"), col("signup_fy"), col("order_month"),
                                         col("days_to_ship"), col("gmv_eur"), col("quantity")])]
    assert kept == ["days_to_ship", "gmv_eur", "quantity"]
