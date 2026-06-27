"""Pre-flight pruning of impossible sub-questions (2026-06-26).

The Swiss-Air run planned a seasonality sub-question, ran a query, and only THEN
discovered the data was single-month June — wasted a planning slot and a round-trip.
_data_span_months reads the date span from the DATA PORTRAIT; _prune_impossible_subqs
drops temporal/seasonality steps when the span is under two months (never landscape or
synthesis). See aughor/agent/explore.py.
"""
from aughor.agent.explore import _data_span_months, _prune_impossible_subqs
from aughor.agent.state import SubQuestion


def _sq(id, purpose, question, expected="agg"):
    return SubQuestion(id=id, purpose=purpose, question=question, expected_output=expected)


def test_span_single_month_from_portrait():
    portrait = "[PROFILE] swiss_air.flights rows=273878 date 2024-06-01 → 2024-06-30"
    span = _data_span_months(portrait)
    assert span is not None and span < 2.0


def test_span_multi_year_from_portrait():
    portrait = "[PROFILE] ecommerce.orders date 2022-01-15 → 2024-01-15"
    assert _data_span_months(portrait) > 20


def test_span_none_when_no_dates():
    assert _data_span_months("no dates here") is None


def test_prunes_seasonality_on_single_month_data():
    chain = [
        _sq("Q1", "landscape", "What is the overall refund volume?"),
        _sq("Q2", "relationship", "What is the refund rate by route and cabin?"),
        _sq("Q3", "threshold", "What is the refund rate by month and quarter (seasonality)?"),
        _sq("Q4", "synthesis", "What is the most direct answer overall?"),
    ]
    kept, dropped = _prune_impossible_subqs(chain, span_months=1.0)
    kept_ids = [s.id for s in kept]
    assert kept_ids == ["Q1", "Q2", "Q4"]
    assert [s.id for s in dropped] == ["Q3"]


def test_never_prunes_when_span_is_adequate():
    chain = [_sq("Q1", "threshold", "refund rate by month and quarter")]
    kept, dropped = _prune_impossible_subqs(chain, span_months=14.0)
    assert dropped == [] and len(kept) == 1


def test_never_prunes_when_span_unknown():
    chain = [_sq("Q1", "threshold", "refund rate by quarter")]
    kept, dropped = _prune_impossible_subqs(chain, span_months=None)
    assert dropped == []


def test_landscape_and_synthesis_are_never_pruned():
    # Even if a landscape/synthesis step mentions a temporal word, keep it.
    chain = [
        _sq("Q1", "landscape", "overall volume and monthly cadence"),
        _sq("Q2", "synthesis", "answer including any seasonal angle"),
    ]
    kept, dropped = _prune_impossible_subqs(chain, span_months=0.5)
    assert dropped == [] and len(kept) == 2
