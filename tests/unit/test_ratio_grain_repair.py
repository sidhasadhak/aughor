"""Grain-correct ratio repair (aughor/sql/ratio_grain.py + investigate wiring).

The suppression caveat promised "a grain-correct recompute" for weeks; this is it.
When the guards prove a per-segment cross-table ratio corrupt, the scan is rebuilt
deterministically (each side aggregated over its own table) and accepted ONLY when
its own whole-population level matches the independently computed true global —
a wrong join guess fails the checksum and degrades to suppression.

Hermetic: in-memory DuckDB where the conditioned reading and the true reading
genuinely differ (true global 2.8%; conditioned-denominator reading ~56%).
"""
from __future__ import annotations

import duckdb

from aughor.sql.ratio_grain import plan_grain_correct_scan, validate_totals

METRIC_SQL = "SUM(refunds.refund_chf) / NULLIF(SUM(bookings.total_fare_chf), 0) * 100"


class _Shim:
    def __init__(self, con):
        self._c = con

    def execute(self, tag, sql):
        r = type("R", (), {})()
        try:
            cur = self._c.execute(sql)
            r.rows = cur.fetchall()
            r.columns = [d[0] for d in cur.description]
            r.error = None
        except Exception as e:  # noqa: BLE001
            r.rows, r.columns, r.error = [], [], str(e)
        return r


def _fixture():
    """100 bookings @ 100 CHF (50 web / 50 corporate); 10 refunds @ 28 CHF —
    2 on web, 8 on corporate. True global = 280/10,000 = 2.8%;
    true per channel: corporate 4.48%, web 1.12%. The conditioned reading
    (denominator = only refunded bookings' fares) reads 28%."""
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE bookings(booking_id INT, channel VARCHAR, total_fare_chf DOUBLE)")
    c.execute("INSERT INTO bookings SELECT range, CASE WHEN range < 50 THEN 'web' ELSE 'corporate' END, 100.0 FROM range(100)")
    c.execute("CREATE TABLE refunds(refund_id INT, booking_id INT, refund_chf DOUBLE, reason VARCHAR)")
    c.execute("""INSERT INTO refunds
        SELECT range, CASE WHEN range < 2 THEN range ELSE 50 + range END,
               28.0, CASE WHEN range < 7 THEN 'voluntary' ELSE 'involuntary' END
        FROM range(10)""")
    return c


_SOURCES = {"num_table": "refunds", "num_col": "refund_chf", "num_agg": "SUM",
            "den_table": "bookings", "den_col": "total_fare_chf", "den_agg": "SUM",
            "scale": 100.0}


def _probe_for(c):
    shim = _Shim(c)
    return lambda sql: (lambda r: None if r.error else r.rows)(shim.execute("t", sql))


def test_den_segment_repair_produces_the_true_rates():
    c = _fixture()
    probe = _probe_for(c)
    plan = plan_grain_correct_scan(probe, _SOURCES, "channel")
    assert plan and plan["case"] == "den_segment"
    rows = c.execute(plan["sql"]).fetchall()
    by_seg = {r[0]: (float(r[1]), float(r[2])) for r in rows}
    assert abs(by_seg["corporate"][0] - 4.48) < 0.01     # 8×28 / 5,000
    assert abs(by_seg["web"][0] - 1.12) < 0.01           # 2×28 / 5,000
    assert by_seg["web"][1] == 5000.0                    # n = the segment's OWN denominator
    assert validate_totals(rows, 100.0, 2.8, "den_segment")


def test_num_segment_repair_is_share_of_whole_population():
    """An event-side attribute (refund reason) cannot honestly have a per-reason
    denominator — that IS the conditioned shape. The repair reads it as share of the
    whole population's gross."""
    c = _fixture()
    plan = plan_grain_correct_scan(_probe_for(c), _SOURCES, "reason")
    assert plan and plan["case"] == "num_segment"
    rows = c.execute(plan["sql"]).fetchall()
    by_seg = {r[0]: float(r[1]) for r in rows}
    assert abs(by_seg["voluntary"] - 1.96) < 0.01        # 7×28 / 10,000
    assert abs(by_seg["involuntary"] - 0.84) < 0.01      # 3×28 / 10,000
    assert validate_totals(rows, 100.0, 2.8, "num_segment")


def test_checksum_rejects_a_remultiplied_side():
    """The acceptance gate: totals that don't reproduce the true global are refused —
    the exact failure a wrong join guess produces."""
    good = [["a", 4.48, 5000.0, 224.0], ["b", 1.12, 5000.0, 56.0]]
    assert validate_totals(good, 100.0, 2.8, "den_segment")
    doubled = [["a", 8.96, 5000.0, 448.0], ["b", 2.24, 5000.0, 112.0]]   # num side ×2
    assert not validate_totals(doubled, 100.0, 2.8, "den_segment")
    assert not validate_totals(good[:1], 100.0, 2.8, "den_segment")      # 1 row = no ranking
    assert not validate_totals(good, 100.0, 0.0, "den_segment")          # no global to check


def test_plan_fails_open_on_everything_it_cannot_prove():
    c = _fixture()
    probe = _probe_for(c)
    assert plan_grain_correct_scan(probe, _SOURCES, "origin") is None          # column nowhere
    assert plan_grain_correct_scan(probe, _SOURCES, "seg; DROP TABLE x") is None
    avg = dict(_SOURCES, num_agg="AVG")
    assert plan_grain_correct_scan(probe, avg, "channel") is None              # AVG ≠ ratio of sums
    same = dict(_SOURCES, den_table="refunds")
    assert plan_grain_correct_scan(probe, same, "channel") is None             # same-table
    # ambiguous owner: a column present on BOTH tables
    c.execute("ALTER TABLE refunds ADD COLUMN channel VARCHAR")
    assert plan_grain_correct_scan(_probe_for(c), _SOURCES, "channel") is None


def test_orchestration_repairs_the_finding_in_place():
    """The investigate-side wrapper: corrupt finding in, validated finding out —
    rows replaced, SQL replaced with the correct query, caveat transparent and free
    of the 'fan-out' token (that phrase trips the synthesis damper for data that is
    now exact), unreachable sibling left for suppression."""
    from aughor.agent.investigate import _repair_conditioned_ratio
    c = _fixture()
    conn = _Shim(c)
    corrupt = {"columns": ["channel", "metric_total", "n"],
               "rows": [["corporate", "56.0"], ["web", "28.0"]],
               "key_numbers": [{"label": "x", "value": "56%"}],
               "interpretation": "corporate leaks at 56%", "sql": "SELECT wrong",
               "chart_type": "bar_horizontal", "error": None}
    unreachable = {"columns": ["origin", "metric_total", "n"], "rows": [["GVA", "58.2"]],
                   "key_numbers": [], "interpretation": "x", "sql": "SELECT wrong2",
                   "chart_type": "bar_horizontal", "error": None}
    repaired, gstr, g = _repair_conditioned_ratio(
        [corrupt, unreachable], conn, METRIC_SQL, "refund leakage rate")
    assert repaired == [corrupt]
    assert corrupt["_grain_repaired"] is True
    assert not unreachable.get("_grain_repaired")
    by_seg = {r[0]: float(r[1]) for r in corrupt["rows"]}
    assert abs(by_seg["corporate"] - 4.48) < 0.01 and abs(by_seg["web"] - 1.12) < 0.01
    assert "WITH den AS" in corrupt["sql"]
    # Clean-output policy (2026-07-18): a repaired finding carries NO reader-facing process-
    # speak — the corrected chart IS the finding. The whole-population level the ranking is
    # validated against rides the trust_caveat (receipt-only), not the interpretation prose.
    assert corrupt["interpretation"] == ""
    assert "2.8%" in corrupt["trust_caveat"]
    assert "fan-out" not in corrupt["trust_caveat"]
    assert "2.8%" in (gstr or "") and abs(g - 2.8) < 0.01


def test_suppressed_rows_are_redacted_from_synthesis_evidence():
    """The synthesis model cited a suppressed single-period '58.04%' straight out of the
    evidence log even under the hard don't-cite instruction — because the finding's raw
    rows were dumped verbatim. A suppressed finding's rows are redacted from the evidence;
    its SQL + caveat stay so synthesis knows what was attempted."""
    from aughor.agent.investigate import _one_phase_evidence, _is_suppressed_finding
    phase = {"phase_name": "Temporal", "findings": [
        {"title": "Single period", "sql": "SELECT ...", "error": None,
         "columns": ["period", "refund leakage rate (%)", "records"],
         "rows": [["2024-06", "58.04", "6907"]], "row_count": 1,
         "chart_type": "none", "key_numbers": [],
         "interpretation": "refund leakage rate could not be computed reliably; artifact.",
         "_suppressed": True}]}
    ev = _one_phase_evidence(phase)
    assert "58.04" not in ev                    # the artifact value is gone from the evidence
    assert "SELECT ..." in ev                   # the SQL stays (what was attempted)
    assert "values suppressed" in ev            # replaced by the honest note
    # a normal finding is untouched
    ok = {"phase_name": "X", "findings": [
        {"title": "t", "sql": "SELECT 1", "error": None, "columns": ["a"],
         "rows": [["3.4"]], "row_count": 1, "chart_type": "bar_horizontal",
         "key_numbers": [], "interpretation": "fine"}]}
    assert "3.4" in _one_phase_evidence(ok)
    assert not _is_suppressed_finding(ok["findings"][0])
