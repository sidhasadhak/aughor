"""The 4.3 pre-check's real instrument — distinct queries vs queries issued.

The artifact-based measurement said 0 repeats across 55 queries, which looked like a
clean answer and was not one: `data/exploration_*.json` is the run's FINAL STATE, so it
records what survived into findings, not what was issued. Counting there measures a
different and much smaller thing than "how much of a run is spent re-asking".

This counts at the execution chokepoint, where every query really passes. 4.3 gets built
only if THIS number is high — never on the artifact number.
"""
from __future__ import annotations

from aughor.kernel import metering


def _run():
    m = metering.RunMetrics()
    token = metering._current.set(m)
    return m, token


def test_repeats_are_counted_as_one_distinct_query():
    m, token = _run()
    try:
        metering.record_query(1, 1.0, "SELECT count(*) FROM orders")
        metering.record_query(1, 1.0, "SELECT count(*) FROM orders")
        metering.record_query(1, 1.0, "SELECT 1")
    finally:
        metering._current.reset(token)

    assert m.query_count == 3
    assert m.distinct_queries == 2, "the repeat was not recognised"


def test_normalisation_sees_through_whitespace_and_case():
    """A model re-asking the same question rarely re-types it byte-identically."""
    m, token = _run()
    try:
        metering.record_query(1, 1.0, "SELECT  count(*)\n  FROM orders")
        metering.record_query(1, 1.0, "select count(*) from orders")
    finally:
        metering._current.reset(token)

    assert m.query_count == 2 and m.distinct_queries == 1


def test_a_query_without_sql_still_meters_cost():
    """`sql` is optional. A caller that does not pass it must not lose its cost row —
    the instrument is additive, not a new requirement."""
    m, token = _run()
    try:
        metering.record_query(5, 2.0)
    finally:
        metering._current.reset(token)

    assert m.query_count == 1 and m.rows_returned == 5
    assert m.distinct_queries == 0


def test_the_trust_receipt_cost_blob_is_unchanged():
    """`to_dict` is stamped on the Trust Receipt. An instrument is not a billed quantity,
    and `_sql_seen` is a set no JSON encoder accepts — neither may leak into it."""
    import json

    m, token = _run()
    try:
        metering.record_query(1, 1.0, "SELECT 1")
    finally:
        metering._current.reset(token)

    d = m.to_dict()
    assert "distinct_queries" not in d and "_sql_seen" not in d
    json.dumps(d)          # would raise on a set
    assert d["query_count"] == 1
