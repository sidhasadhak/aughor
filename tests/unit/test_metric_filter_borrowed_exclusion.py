"""A wider exclusion borrowed from a sibling metric is replaced by the declared filter.

Traced 2026-10-07: theLook's daily runs of 5 and 6 October read "Revenue" (declared
`SUM(sale_price)` over `status <> 'Cancelled'`) through `status NOT IN ('Cancelled', 'Returned')`
— Net merchandise revenue's filter — on a question that said "Use the governed Revenue metric
exactly as defined, including its status filter". The guard counted the condition as the
question's own choice because it named Cancelled, so 26 September read $17,316.12 where the
day before's run had read it under a third definition. The statement below is the 5 October
run's own, as stored.
"""
from __future__ import annotations

from aughor.sql.metric_filter_guard import enforce_metric_filters

RUN_OF_5_OCTOBER = """SELECT
    DATE(created_at) as date,
    SUM(sale_price) as revenue,
    COUNT(DISTINCT order_id) as order_count,
    SUM(sale_price) / COUNT(DISTINCT order_id) as aov
FROM `bigquery-public-data.thelook_ecommerce.order_items`
WHERE created_at >= '2026-09-26' AND created_at < '2026-09-28'
AND status NOT IN ('Cancelled', 'Returned')
GROUP BY 1
ORDER BY 1 ASC"""

ASKED = ("What changed in theLook in the last day? Give me the top three findings with the "
         "numbers. Use the governed Revenue metric exactly as defined, including its status filter.")


def _rule(asked: str) -> list:
    return [{"metric": "revenue", "formula": "SUM(sale_price)", "tables": ["order_items"],
             "filters": ["status <> 'Cancelled'"], "asked": asked}]


def test_the_borrowed_exclusion_is_replaced_by_the_declared_filter():
    out, applied = enforce_metric_filters(RUN_OF_5_OCTOBER, _rule(ASKED), dialect="bigquery")
    assert "'Returned'" not in out
    assert "<> 'Cancelled'" in out
    assert len(applied) == 1
    assert applied[0]["replaced"] == "NOT status IN ('Cancelled', 'Returned')"
    # The rest of the statement is untouched: same window, same grouping.
    assert "created_at >= '2026-09-26'" in out and "GROUP BY" in out


def test_a_question_that_asks_to_exclude_returns_keeps_its_exclusion():
    asked = "What was revenue yesterday, excluding returns?"
    out, applied = enforce_metric_filters(RUN_OF_5_OCTOBER, _rule(asked), dialect="bigquery")
    assert applied == []
    assert out == RUN_OF_5_OCTOBER


def test_the_declared_filter_itself_is_left_alone():
    sql = RUN_OF_5_OCTOBER.replace("status NOT IN ('Cancelled', 'Returned')", "status <> 'Cancelled'")
    out, applied = enforce_metric_filters(sql, _rule(ASKED), dialect="bigquery")
    assert applied == [] and out == sql


def test_measuring_the_cancelled_rows_is_still_the_questions_own_choice():
    sql = RUN_OF_5_OCTOBER.replace("status NOT IN ('Cancelled', 'Returned')", "status = 'Cancelled'")
    out, applied = enforce_metric_filters(sql, _rule("How much revenue was cancelled?"), dialect="bigquery")
    assert applied == [] and out == sql


def test_a_scheduled_runs_context_is_not_read_as_the_persons_words():
    """A quoted previous report that mentions returns must not unlock the exclusion."""
    from aughor.semantic.enforcement import person_words
    from aughor.automations import temporal
    block = (f"{temporal.OBSERVATION_HEADER}\nThis is a scheduled daily run.\n"
             "[Previous scheduled report — for consistency checking]\n"
             "Returns rose 4% on the day.\n"
             f"{temporal.PREVIOUS_REPORT_TAIL}\n\n" if hasattr(temporal, "PREVIOUS_REPORT_TAIL") else "")
    words = person_words(block + ASKED) if block else ASKED
    assert "return" not in words.lower()
