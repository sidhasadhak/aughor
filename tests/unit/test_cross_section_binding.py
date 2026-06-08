"""Regression tests for the cross-sectional / dimensional finding assembler.

These lock the three bugs reported after the cross-sectional path update (#25):

  1. "Card says city but the chart shows country" — findings were bound to narrator
     interpretations by LIST POSITION with a min(i, len-1) clamp, so a reordered or
     truncated narrator list misattributed every card.  _assemble_phase_findings now
     binds each query to the narrator finding for its OWN dimension and grounds the
     title in the query that produced the rows.
  2. "Says X but shows Y in charts" — the web chart prefers a pct/share column as the
     primary axis, so the bar plotted share-of-total while the prose cited dollars.
     _chart_primary_is_metric strips share columns from the rendered finding.
  3. Missing averages — avg_per_record must survive the chart-column cleanup so the
     per-record lens reaches the table.
"""
import types

from aughor.agent import investigate as I


def _q(title, chart="bar_horizontal"):
    return types.SimpleNamespace(title=title, chart_type=chart, sql="SELECT ...")


def _f(title, interp, sig=False):
    return types.SimpleNamespace(
        title=title, interpretation=interp, key_numbers=[],
        chart_type="auto", stat_note=None, is_significant=sig,
    )


class _R:
    def __init__(self, cols, rows, sql):
        self.columns, self.rows, self.sql = cols, rows, sql
        self.row_count, self.error = len(rows), None


def _xsec_results():
    qs = [_q("Net revenue by city"), _q("Net revenue by country"), _q("Net revenue by product")]
    rs = [
        _R(["city", "metric_total", "n", "avg_per_record", "pct_of_total"], [["Rome", 100, 5, 20, 3.0]], "q_city"),
        _R(["country", "metric_total", "n", "avg_per_record", "pct_of_total"], [["Italy", 900, 40, 22, 30.0]], "q_country"),
        _R(["product", "metric_total", "n", "avg_per_record", "pct_of_total"], [["Cake", 50, 2, 25, 1.5]], "q_product"),
    ]
    return list(zip(qs, rs))


def test_reordered_narrator_does_not_swap_dimensions():
    """Narrator returns findings out of order — each card must still describe its own
    query's dimension, never a neighbour's."""
    results = _xsec_results()
    narrator = [_f("By country", "Italy dominates."), _f("By city", "Rome is weakest at $100.")]

    findings = I._assemble_phase_findings(results, narrator, "xsec", metric_label="Net revenue")

    for finding, (_q_, r) in zip(findings, results):
        dim_col = r.columns[0]
        assert dim_col in finding["title"].lower(), (
            f"card titled {finding['title']!r} but charts the {dim_col!r} query"
        )
    # the city card carries the city prose, not the (earlier-listed) country prose
    assert "rome" in findings[0]["interpretation"].lower()
    assert "italy" in findings[1]["interpretation"].lower()


def test_dropped_narrator_finding_falls_back_to_data_only():
    """When the narrator drops a dimension, the unmatched query must fall back to a
    data-only finding — never clamp to another dimension's interpretation."""
    results = _xsec_results()
    narrator = [_f("By country", "Italy dominates."), _f("By city", "Rome is weakest.")]

    findings = I._assemble_phase_findings(results, narrator, "xsec", metric_label="Net revenue")

    product = findings[2]
    assert "product" in product["title"].lower()
    assert product["interpretation"] == "Query executed."  # data-only, not a borrowed narrative


def test_chart_primary_is_metric_strips_share_keeps_average():
    """The rendered finding must plot metric_total (magnitude), not pct_of_total, and
    must retain avg_per_record so the average lens survives."""
    f = {
        "columns": ["city", "metric_total", "n", "avg_per_record", "pct_of_total"],
        "rows": [["Rome", 100, 5, 20, 3.0]],
    }
    I._chart_primary_is_metric(f)
    assert "pct_of_total" not in f["columns"]
    assert f["columns"][1] == "metric_total"          # primary numeric the chart will pick
    assert "avg_per_record" in f["columns"]            # average preserved
    assert f["rows"][0] == ["Rome", 100, 5, 20]        # rows projected in lock-step


def test_label_tokens_collapse_to_dimension():
    assert I._label_tokens("Net revenue by city", I._label_tokens("Net revenue")) == {"city"}
    assert I._label_tokens("By City") == {"city"}


def test_temporal_titles_keep_narrator_label():
    """A time-series query (no dimension token) should keep the narrator's richer title,
    matched positionally — title grounding only fires on a dimension-certain match."""
    qs = [_q("Monthly revenue", chart="line")]
    rs = [_R(["month", "revenue"], [["2026-01", 100]], "q_ts")]
    narrator = [_f("Revenue fell 18% in February", "Down sharply.", sig=True)]

    findings = I._assemble_phase_findings(list(zip(qs, rs)), narrator, "baseline")
    assert findings[0]["title"] == "Revenue fell 18% in February"
    assert findings[0]["is_significant"] is True
