"""A narrator finding sits over the rows that hold its numbers — and nowhere else.

Live (LuxExperience 34ca1559, 2026-10-14): the decomposition phase ran three queries — orders
vs AOV (one row), line revenue by segment (17 rows), revenue by brand (30 rows). The narrator
wrote two findings from the FIRST result's rows ("Order volume explains the whole increase";
"Value per order was a small drag, driven by lower price per unit") and one from the second,
and nothing about the brands. The binding fell through to position: the AOV prose shipped
over the segment rows and the segment prose over the brand rows.

The derivation-credited grounding could not tell (it scored 1.0 for every finding against the
85-cell segment grid — on a wide result some pair of cells derives almost any figure); the
RAW cells can (0.83 against the rows that hold them, 0.17 against the rest). The finding's
home is the query whose rows hold its numbers; a second reading of the same rows folds onto
that card; a query nobody wrote about keeps its own title and no borrowed prose.
"""
from types import SimpleNamespace

from aughor.agent.investigate import (
    _align_narrator_findings,
    _align_narrator_findings_with_orphans,
    _assemble_phase_findings,
    _finding_homes,
)
from aughor.explorer.verify import _salient_number_pairs, raw_grounded_fraction

ORDERS_VS_AOV_COLS = ["aug_rev", "sep_rev", "rev_delta", "rev_pct", "aug_orders", "sep_orders", "aug_aov",
                      "sep_aov", "aug_units_per_order", "sep_units_per_order", "aug_price_per_unit",
                      "sep_price_per_unit"]
ORDERS_VS_AOV_ROWS = [["627935", "721755", "93820", "14.9", "1063", "1242", "590.72", "581.12", "2.097",
                       "2.108", "281.71", "275.69"]]
SEGMENT_COLS = ["dimension", "segment", "aug_rev", "sep_rev", "delta", "pct_change", "pct_of_total_delta"]
SEGMENT_ROWS = [["brand_tier", "contemporary", "160041", "202240", "42199", "26.4", "45.0"],
                ["brand_tier", "luxury", "265934", "296879", "30945", "11.6", "33.0"],
                ["category", "womenswear", "250824", "294357", "43532", "17.4", "46.4"],
                ["category", "shoes", "75876", "93781", "17905", "23.6", "19.1"]]
BRAND_COLS = ["brand", "aug_rev", "sep_rev", "delta", "pct_of_total_delta"]
BRAND_ROWS = [["Etro", "7357", "15834", "8477", "9.0"], ["Dolce & Gabbana", "6553", "14242", "7689", "8.2"],
              ["Valentino", "5208", "12853", "7645", "8.1"]]

VOLUME = ("Revenue rose from €627,935 in August to €721,755 in September, a delta of +€93,820 (+14.9%). "
          "Orders rose from 1,063 to 1,242 (+179, +16.8%).")
AOV = ("AOV fell from €590.72 to €581.12 (-1.6%). Units per order were flat (2.097 to 2.108), so the "
       "decline comes from price per unit, which fell from €281.71 to €275.69 (-2.1%).")
SEGMENTS = ("By category, womenswear added +€43,532 (46.4% of the delta, +17.4%) and shoes +€17,905 "
            "(19.1%, +23.6%). By brand tier, contemporary added +€42,199 (45.0%, +26.4%).")


def _kn(label, value):
    return SimpleNamespace(label=label, value=value, delta=None, context=None)


def _narrator():
    return [
        SimpleNamespace(title="Order volume explains the whole increase", interpretation=VOLUME,
                        key_numbers=[_kn("Volume effect", "+€105,739")], chart_type="auto", stat_note=None,
                        is_significant=False, claim=None),
        SimpleNamespace(title="Value per order was a small drag, driven by lower price per unit",
                        interpretation=AOV, key_numbers=[_kn("Price per unit", "€281.71 to €275.69")],
                        chart_type="auto", stat_note=None, is_significant=False, claim=None),
        SimpleNamespace(title="Womenswear and the contemporary tier led the gain", interpretation=SEGMENTS,
                        key_numbers=[_kn("Womenswear delta", "+€43,532")], chart_type="auto", stat_note=None,
                        is_significant=False, claim=None),
    ]


def _queries():
    return [SimpleNamespace(title="Revenue change decomposed into order count and AOV", chart_type="auto"),
            SimpleNamespace(title="Line revenue change by category and brand tier (units vs price)",
                            chart_type="auto"),
            SimpleNamespace(title="Revenue change by brand", chart_type="auto")]


ROWS = [ORDERS_VS_AOV_ROWS, SEGMENT_ROWS, BRAND_ROWS]


def test_euros_are_salient_numbers():
    """The cause under the cause: on a EUR connection the grounding passes saw only percentages."""
    assert [v for _, v in _salient_number_pairs("AOV fell from €590.72 to €581.12")] == [590.72, 581.12]
    assert [v for _, v in _salient_number_pairs("£1,200 and $3.50")] == [1200.0, 3.5]


def test_raw_cells_discriminate_where_derivations_do_not():
    assert raw_grounded_fraction(AOV, ORDERS_VS_AOV_ROWS) > 0.7
    assert raw_grounded_fraction(AOV, SEGMENT_ROWS) < 0.3
    assert raw_grounded_fraction(SEGMENTS, SEGMENT_ROWS) == 1.0
    assert raw_grounded_fraction(SEGMENTS, BRAND_ROWS) < 0.2


def test_each_finding_has_the_home_whose_rows_hold_its_numbers():
    assert _finding_homes(_narrator(), ROWS) == [0, 0, 1]
    # No numbers, no home — such a finding binds the old ways.
    assert _finding_homes([SimpleNamespace(interpretation="Growth was broad.")], ROWS) == [None]


def test_a_finding_never_binds_away_from_its_home_by_position_or_token():
    # The title token trap: the segment query names "price" and "units", so does the AOV finding.
    aligned, by_token, orphans = _align_narrator_findings_with_orphans(_queries(), _narrator(), result_rows=ROWS)
    narrator = _narrator()
    assert aligned[0].title == narrator[0].title            # the lead reading of the orders-vs-AOV rows
    assert aligned[1].title == narrator[2].title            # the segment prose over the segment rows
    assert aligned[2] is None                               # nobody wrote about the brands
    assert by_token[1] is True                              # evidence-grounded, so the query names the card
    assert [f.title for f in orphans[0]] == [narrator[1].title]   # the AOV reading belongs to query 0 too


def test_the_two_tuple_form_still_binds_the_same():
    aligned, by_token = _align_narrator_findings(_queries(), _narrator(), result_rows=ROWS)
    assert [a.title if a else None for a in aligned] == [
        "Order volume explains the whole increase", "Womenswear and the contemporary tier led the gain", None]


def test_the_second_reading_folds_onto_its_own_card_and_the_brand_card_borrows_nothing():
    results = [
        (q, SimpleNamespace(sql=f"SELECT {i}", columns=c, rows=r, row_count=len(r), error=None, caveats=[]))
        for i, (q, c, r) in enumerate(zip(_queries(), [ORDERS_VS_AOV_COLS, SEGMENT_COLS, BRAND_COLS], ROWS))
    ]
    out = _assemble_phase_findings(results, _narrator(), "decomp", metric_label="revenue")
    assert [f["finding_id"] for f in out] == ["decomp_0", "decomp_1", "decomp_2"]
    assert out[0]["interpretation"].startswith("Revenue rose") and "price per unit" in out[0]["interpretation"]
    assert [k["label"] for k in out[0]["key_numbers"]] == ["Volume effect", "Price per unit"]
    assert out[1]["title"] == "Line revenue change by category and brand tier (units vs price)"
    assert out[1]["interpretation"].startswith("By category")
    assert out[2]["title"] == "Revenue change by brand" and out[2]["interpretation"] == ""
    assert out[2]["key_numbers"] == []
