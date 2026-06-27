"""Raw-COUNT rate over a join — cardinality guard (2026-06-26).

The Swiss-Air refund rate was COUNT(refund_id)/NULLIF(COUNT(ticket_id),0) over a LEFT
JOIN — correct only if every ticket has ≤1 refund. count_ratio_distinct_risk flags the
pattern so the analyst validates the cardinality and switches to COUNT(DISTINCT ...).
See aughor/sql/fanout.py.
"""
from aughor.sql.fanout import count_ratio_distinct_risk

SWISS_AIR_SQL = """
SELECT
    EXTRACT(MONTH FROM f.flight_date) AS departure_month,
    COUNT(t.ticket_id) AS total_tickets,
    COUNT(r.refund_id) AS refunded_tickets,
    COUNT(r.refund_id) / NULLIF(COUNT(t.ticket_id), 0) AS refund_rate
FROM swiss_air.tickets t
JOIN swiss_air.flights f ON t.flight_id = f.flight_id
LEFT JOIN swiss_air.refunds r ON t.ticket_id = r.ticket_id
GROUP BY EXTRACT(MONTH FROM f.flight_date)
"""


def test_flags_swiss_air_refund_rate():
    reason = count_ratio_distinct_risk(SWISS_AIR_SQL)
    assert reason is not None
    assert "DISTINCT" in reason
    assert "cardinality" in reason.lower()


def test_distinct_form_is_not_flagged():
    safe = """
    SELECT COUNT(DISTINCT CASE WHEN r.refund_id IS NOT NULL THEN t.ticket_id END)
           / NULLIF(COUNT(DISTINCT t.ticket_id), 0) AS refund_rate
    FROM tickets t LEFT JOIN refunds r ON t.ticket_id = r.ticket_id
    """
    assert count_ratio_distinct_risk(safe) is None


def test_single_table_count_ratio_not_flagged():
    # No join → no fan-out risk.
    sql = "SELECT COUNT(a) / NULLIF(COUNT(b), 0) AS r FROM t"
    assert count_ratio_distinct_risk(sql) is None


def test_count_star_ratio_not_flagged():
    sql = "SELECT COUNT(*) / NULLIF(COUNT(*), 0) FROM a JOIN b ON a.id = b.aid"
    assert count_ratio_distinct_risk(sql) is None


def test_same_column_ratio_not_flagged():
    sql = "SELECT COUNT(a.x) / NULLIF(COUNT(a.x), 0) FROM a JOIN b ON a.id = b.aid"
    assert count_ratio_distinct_risk(sql) is None


def test_sum_over_count_not_flagged():
    # Not a count/count rate.
    sql = "SELECT SUM(a.v) / NULLIF(COUNT(b.id), 0) FROM a JOIN b ON a.id = b.aid"
    assert count_ratio_distinct_risk(sql) is None


def test_garbage_sql_returns_none():
    assert count_ratio_distinct_risk("not sql at all ((") is None
