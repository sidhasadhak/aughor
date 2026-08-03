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


def test_numeric_grounding_breaks_same_dimension_tie():
    """Two queries over the SAME dimension (brand tier) but different MEASURES — a z-score
    query and a PoP-change query — tie on {tier}. Each narrator finding must bind to the query
    whose cells actually contain its numbers, not by list position (which swapped them and let
    a z-score card inherit the PoP finding's figures)."""
    q_zscore = _q("Total GMV by brand tier")
    q_pop = _q("Total GMV by brand tier")
    r_zscore = _R(["tier", "obs_gmv", "baseline_mean", "z_score"], [["ultra", 445844, 254385, 5.05]], "q_z")
    r_pop = _R(["tier", "obs", "prior", "delta"], [["ultra", 445844, 541198, -95354]], "q_p")
    results = [(q_zscore, r_zscore), (q_pop, r_pop)]
    # narrator lists the PoP finding FIRST — the old index tie-break would bind it to q_zscore
    f_pop = _f("GMV by brand tier", "Ultra GMV fell -95,354 EUR from 541,198 to 445,844, a -17.6% decline.")
    f_zscore = _f("GMV by brand tier",
                  "Ultra observation GMV of 445,844 sits 5.05 std above its baseline mean of 254,385.")
    narrator = [f_pop, f_zscore]

    findings = I._assemble_phase_findings(results, narrator, "baseline", metric_label="GMV")

    # the z-score card carries the z-score prose (baseline/std), NEVER the PoP decline
    assert "baseline" in findings[0]["interpretation"].lower()
    assert "95,354" not in findings[0]["interpretation"]
    # the PoP card carries the decline prose
    assert "95,354" in findings[1]["interpretation"]
    # and each is now internally grounded → no false trust caveat
    assert findings[0]["trust_caveat"] is None
    assert findings[1]["trust_caveat"] is None


def test_temporal_titles_keep_narrator_label():
    """A time-series query (no dimension token) should keep the narrator's richer title,
    matched positionally — title grounding only fires on a dimension-certain match."""
    qs = [_q("Monthly revenue", chart="line")]
    rs = [_R(["month", "revenue"], [["2026-01", 100]], "q_ts")]
    narrator = [_f("Revenue fell 18% in February", "Down sharply.", sig=True)]

    findings = I._assemble_phase_findings(list(zip(qs, rs)), narrator, "baseline")
    assert findings[0]["title"] == "Revenue fell 18% in February"
    assert findings[0]["is_significant"] is True


# ── The narrator names findings by VALUE; the planner names queries by DIMENSION ──
# Live defect (inv f916ff3a, the revenue-leakage phase). The narrator titled a finding
# "Leakage rate is concentrated in East and Central" while its query was titled by the
# dimension it grouped on. Token overlap was therefore EMPTY, and the candidate list is
# filtered to pairs sharing a token — so the numeric grounding that would have settled it
# was computed and discarded, binding fell through to position, and the report shipped a
# discount-band chart under the "East and Central" heading with the region interpretation
# beside the band rows. Measured on the real artifact: the correct pairing scored
# 0.20/0.17 and the positional one 0.00/0.00.

def _leakage_results():
    """The two queries of the live leakage phase, rows verbatim. Their titles share NO
    token with the narrator's value-named ones."""
    region = _R(["region", "metric_total", "n"],
                [["East", "0.2611152374869911", "39139.80700000001"],
                 ["Central", "0.17341348560825143", "39154.971"],
                 ["South", "0.12170909536054493", "43916.191999999995"],
                 ["West", "0.10642494972718998", "84754.56199999998"]], "q_region")
    band = _R(["discount_band", "total_contra_revenue", "metric_total"],
              [["40%+", "203.55", "0.3142445648658366"],
               ["20%-<40%", "110.20000000000005", "0.15606328079967624"],
               ["0%", "0.0", "0.0"]], "q_band")
    return [(_q("Leakage rate by region"), region), (_q("Leakage rate by discount band"), band)]


def test_value_named_narrator_findings_bind_by_evidence_not_position():
    results = _leakage_results()
    # Narrator titles and interpretations verbatim from the shipped report, in the order
    # they shipped — which is the REVERSE of the query order.
    narrator = [
        _f("Total leakage and primary driver",
           "Measured discount contra-revenue totals $313.75 (0.15% of Tables gross sales). "
           "The dominant source is the 40%+ discount band, which accounts for $203.55, or "
           "64.9% of all measured leakage, and has the highest leakage rate at 0.31% of "
           "its gross sales."),
        _f("Leakage rate is concentrated in East and Central",
           "East has the highest regional leakage rate at 0.26%, followed by Central at "
           "0.17%; both exceed the 0.15% overall Tables rate. South (0.12%) and West "
           "(0.11%) are below the overall rate, although West has the largest regional "
           "gross-sales base."),
    ]

    findings = I._assemble_phase_findings(results, narrator, "leakage",
                                          metric_label="leakage rate")

    region_card, band_card = findings
    assert "East has the highest regional" in region_card["interpretation"], (
        "the region chart must carry the region interpretation, not the discount band's")
    assert "40%+ discount band" in band_card["interpretation"], (
        "the discount-band chart must carry the band interpretation, not the region's")
    # And the heading follows the rows, so a card can never name a slice it does not chart.
    assert "region" in region_card["title"].lower()
    assert "band" in band_card["title"].lower()


def test_positional_binding_still_applies_when_there_is_no_numeric_evidence():
    """The numeric pass must not swallow the existing fallback: interpretations citing no
    number at all still bind in order, as before."""
    results = _leakage_results()
    narrator = [_f("First", "Leakage looks broadly stable."),
                _f("Second", "No material concentration stands out.")]

    findings = I._assemble_phase_findings(results, narrator, "leakage",
                                          metric_label="leakage rate")

    assert findings[0]["interpretation"] == "Leakage looks broadly stable."
    assert findings[1]["interpretation"] == "No material concentration stands out."
