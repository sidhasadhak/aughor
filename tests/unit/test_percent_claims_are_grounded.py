"""A percentage claim must ground against its own rows however the narrator SPELLS it.

Live defect (deep run `2af40e62`, theLook): the dimensional phase ran four queries — by
category, department, traffic source and country. The narrator titled one finding
"Geographic Contribution" and wrote "China (33.1 percent) and the United States (23.9
percent)". Those two numbers are literally cells in the COUNTRY result, so the numeric
pass in `_align_narrator_findings` should have bound them there.

It scored 0.0 instead, because `_CLAIM_NUM_RE` knew "33.1%" but not "33.1 percent" — so
the claim carried no salient numbers at all and the grounding rescue could not fire. The
binding fell through to POSITION, and the card shipped the China/US sentence on top of
the department rows (Women 46.1, Men 53.9), while the real country card shipped with no
prose at all.

The regex is the cause; the binding is what the reader sees. Both are asserted here.
"""
from types import SimpleNamespace

from aughor.agent.investigate import _align_narrator_findings
from aughor.explorer.verify import _salient_number_pairs, grounded_fraction

# The two results whose narration was swapped, with the rows the live run returned.
COUNTRY_ROWS = [
    ["Brasil", "92800.88998138905", "14.9"],
    ["United States", "149247.84013700485", "23.9"],
    ["China", "206674.64032981917", "33.1"],
]
DEPARTMENT_ROWS = [
    ["Women", "287734.0801522359", "46.1"],
    ["Men", "335883.42010211945", "53.9"],
]
GEO_CLAIM = (
    "Revenue growth is geographically concentrated, with China (33.1 percent) and the "
    "United States (23.9 percent) being the primary contributors."
)


def test_spelled_percent_is_a_salient_number():
    """"33.1 percent" is the same claim as "33.1%" and must parse to the same value."""
    assert _salient_number_pairs(GEO_CLAIM) == [("33.1 percent", 33.1), ("23.9 percent", 23.9)]
    assert _salient_number_pairs("China holds 33.1% of revenue") == [("33.1%", 33.1)]


def test_percent_claim_grounds_in_its_own_rows_only():
    """The rescue pass needs a SIGNAL: 1.0 on the rows that hold the numbers, 0.0 elsewhere."""
    assert grounded_fraction(GEO_CLAIM, COUNTRY_ROWS) == 1.0
    assert grounded_fraction(GEO_CLAIM, DEPARTMENT_ROWS) == 0.0


def test_bare_counts_are_not_claims():
    """Widening the regex must not make every integer salient — "the last 90 days" is prose.

    A grounding score built from incidental numbers is worse than none: it would bind a
    finding to whichever query happened to contain a 90 somewhere.
    """
    for prose in ("over the last 90 days", "the top 3 categories", "z = 3.4", "15 months"):
        assert _salient_number_pairs(prose) == [], prose


def test_geographic_finding_binds_to_the_country_query_not_by_position():
    """The defect as the reader met it: the claim must land on the rows it describes.

    Titles share no token ("geographic" vs "country"), so the token pass cannot bind
    these — this is exactly the case the numeric pass exists for. Ordered so that
    positional binding would put the geographic claim on the DEPARTMENT query.
    """
    queries = [
        SimpleNamespace(title="Revenue Contribution by Department", chart_type="auto"),
        SimpleNamespace(title="Revenue Contribution by Country", chart_type="auto"),
    ]
    narrator = [
        SimpleNamespace(title="Geographic Contribution", interpretation=GEO_CLAIM),
        SimpleNamespace(title="Departmental Split", interpretation="Men 53.9 percent of revenue."),
    ]
    aligned, by_token = _align_narrator_findings(
        queries, narrator, result_rows=[DEPARTMENT_ROWS, COUNTRY_ROWS],
    )

    assert aligned[1] is narrator[0], "the geographic claim must bind to the COUNTRY query"
    assert aligned[0] is not narrator[0], "it must not stay on the department query"
    # Evidence-grounded binding is authoritative, so the card is re-titled from its query.
    assert by_token[1], "a numerically grounded match must be marked authoritative"
