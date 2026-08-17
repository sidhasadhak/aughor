"""AT-5 — the VALUE layer, and the false positives it is required to keep making.

Half of these tests assert that a witness fires on something that is NOT what the witness
names: `fare_multiplier` (0.2–1.0) gets `percent.fraction`, `Defect rates` gets
`geo.latitude`. That is not a bug being pinned, it is the contract. A value shape narrows
the candidates and the resolver settles them against the other layers — the module's job is
to be honest about what the numbers are consistent with, at a confidence that cannot act
alone.

The measured rates it is calibrated against, all from AT-0 across 105 tables:
3 of 5 bounded-±90 columns are not coordinates; 2 of 12 bounded 0–1 are not proportions.
"""
from __future__ import annotations

import pytest

from aughor.tools.concept import CONFIDENT, LAYER_VALUE, resolve_concept
from aughor.tools.shape import (
    MIN_VALUES,
    as_float,
    decimals,
    read_numeric,
    value_witnesses,
)

N = 120


def concepts(values) -> set:
    return {w.concept for w in value_witnesses(values)}


def witness(values, concept):
    return next((w for w in value_witnesses(values) if w.concept == concept), None)


# ── reading values as written ────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("18.2514534", 18.2514534), ("-66.03", -66.03), ("0", 0.0), (".5", 0.5),
    ("1e3", 1000.0), (3, 3.0), (2.5, 2.5), (True, 1.0),
    (None, None), ("", None), ("NULL", None), ("n/a", None), ("abc", None),
    ("12abc", None), ("2026-08-17", None), ("1,234", None),
])
def test_as_float_reads_only_what_is_a_number(raw, expected):
    assert as_float(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("18.2514534", 7), ("18.25", 2), ("18", 0), ("18.250000", 2), ("18.0", 0),
    ("2.956572139430807", 15), (None, 0), ("abc", 0),
])
def test_decimals_are_counted_as_WRITTEN(raw, expected):
    """`float()` erases the difference between 18.2514534 and 18.25, and that difference is
    the evidence separating a recorded coordinate from a printed float."""
    assert decimals(raw) == expected


def test_a_varchar_column_of_numbers_is_numeric():
    """The whole reason this layer exists: the loader said VARCHAR, the values say
    coordinates. The dtype is never consulted — only the values are."""
    shape = read_numeric([f"{18.25 + i * 0.01371:.8f}" for i in range(N)])
    assert shape.is_numeric
    assert shape.numeric_share == 1.0
    # trailing zeros are not recorded precision: '18.25000000' carries two decimals, and
    # counting the formatter's padding would make every float look like a coordinate
    assert 4 <= shape.median_decimals <= 8
    assert read_numeric(["18.25000000"] * N).median_decimals == 2


def test_a_column_of_words_is_not_numeric():
    assert not read_numeric([f"city{i}" for i in range(N)]).is_numeric
    assert value_witnesses([f"city{i}" for i in range(N)]) == []


def test_a_mostly_numeric_column_still_counts_and_says_so():
    values = [f"{0.001 * i:.4f}" for i in range(N)] + ["n/a", "unknown"]   # 98.4% parse
    assert read_numeric(values).is_numeric
    w = witness(values, "percent.fraction")
    assert w is not None
    assert "% of values parse as numbers" in w.evidence      # 120 of 122 rounds to 99%


def test_a_half_numeric_column_is_not_numeric():
    values = [str(i) if i % 2 else f"x{i}" for i in range(N)]
    assert not read_numeric(values).is_numeric
    assert value_witnesses(values) == []


def test_a_short_sample_shapes_nothing():
    """Nine values inside ±90 is evidence about nine rows, not about a column."""
    assert value_witnesses([f"{18.25 + i * 0.0137:.8f}" for i in range(MIN_VALUES - 1)]) == []


def test_nothing_at_all_never_raises():
    assert value_witnesses([]) == []
    assert value_witnesses(None) == []
    assert value_witnesses([None, "", "NULL"]) == []
    assert read_numeric(None).is_numeric is False


# ── binary ───────────────────────────────────────────────────────────────────

def test_exactly_zero_and_one_is_a_flag():
    w = witness([i % 2 for i in range(N)], "flag.binary")
    assert w is not None
    assert w.layer == LAYER_VALUE
    assert w.confidence == 0.7
    assert "0 or 1" in w.evidence


def test_a_flag_claims_nothing_else():
    """0/1 is inside 0…1 and inside 0…100 too, and reporting all three would be three
    votes from one observation."""
    assert concepts([i % 2 for i in range(N)]) == {"flag.binary"}


def test_one_distinct_value_describes_the_sample_not_the_column():
    assert value_witnesses([0] * N) == []
    assert value_witnesses([1] * N) == []
    assert value_witnesses([7.5] * N) == []


def test_zero_one_and_two_is_not_a_flag():
    assert "flag.binary" not in concepts([i % 3 for i in range(N)])


def test_a_flag_cannot_type_a_column_by_itself():
    v = resolve_concept(value_witnesses([i % 2 for i in range(N)]))
    assert v.concept == "flag.binary"
    assert not v.is_confident
    assert v.confidence < CONFIDENT


# ── proportions ──────────────────────────────────────────────────────────────

def test_values_inside_zero_and_one_are_a_proportion():
    w = witness([round(i / (N * 2), 4) for i in range(N)], "percent.fraction")
    assert w is not None and w.confidence == 0.5
    assert "0…1" in w.evidence


def test_a_multiplier_also_reads_as_a_proportion_and_that_is_correct():
    """`main.fare_classes.fare_multiplier` runs 0.2–1.0 and is not a percentage;
    `attribution.weight` runs 0.4–1.0 and is not either. The values cannot tell — 2 of the
    12 bounded 0–1 columns AT-0 measured are not proportions, so this witness is scored
    where a second layer has to agree with it."""
    values = [round(0.2 + 0.8 * i / N, 4) for i in range(N)]
    assert witness(values, "percent.fraction") is not None
    # …and it cannot act: AT-4 caps a lone witness, whatever this layer's own certainty is
    assert not resolve_concept(value_witnesses(values)).is_confident


def test_whole_integers_in_range_are_not_a_fraction():
    """A column of 0s and 1s and 2s is not a proportion however tightly it is bounded."""
    assert "percent.fraction" not in concepts([i % 2 for i in range(N)])


def test_a_negative_ratio_is_not_a_proportion():
    """`Order Item Profit Ratio` goes negative — a loss. Outside 0…1, so the shape does not
    claim it."""
    assert "percent.fraction" not in concepts([round(-1 + 2 * i / N, 4) for i in range(N)])


def test_zero_to_one_hundred_claims_NOTHING():
    """The measured reason `percent.whole` does not exist: across 105 tables that band
    fires on 82 columns and about two are percentages. `csat` 1–5, `month` 1–12,
    `quantity` 1–14, `bathrooms` 1–5.25 — the band is where every small number lives, and
    no range test separates them because there is no difference in the values."""
    for not_a_percentage in (
        [1 + (i % 5) for i in range(N)],                     # csat
        [1 + (i % 12) for i in range(N)],                    # month
        [round(1 + (i % 9) * 0.5, 2) for i in range(N)],     # bathrooms
        [round(7 + 22 * i / N, 2) for i in range(N)],        # a plausible discount_pct
    ):
        assert concepts(not_a_percentage) == set(), not_a_percentage[:4]


def test_above_one_hundred_is_no_percentage_either():
    assert concepts([100 + i for i in range(N)]) == set()


# ── coordinates ──────────────────────────────────────────────────────────────

_LATS = [f"{18.25 + i * 0.1371:.8f}" for i in range(N)]          # 18.25…34.5, 8 dp
_LONS = [f"{-66.03 - i * 0.9137:.8f}" for i in range(N)]         # −66…−175, 8 dp


def test_a_precise_varied_column_inside_ninety_is_a_latitude_candidate():
    w = witness(_LATS, "geo.latitude")
    assert w is not None and w.confidence == 0.45
    assert "±90" in w.evidence and "decimal places" in w.evidence


def test_a_column_that_leaves_ninety_is_a_longitude_candidate():
    assert "geo.longitude" in concepts(_LONS)
    assert "geo.latitude" not in concepts(_LONS)


def test_a_latitude_candidate_cannot_act_alone():
    """AT-0: of 5 columns passing this test, only 2 are coordinates. 60% wrong is not a
    verdict."""
    v = resolve_concept(value_witnesses(_LATS))
    assert v.concept == "geo.latitude"
    assert not v.is_confident


def test_sixteen_significant_digits_are_not_a_coordinate():
    """`scm.supply_chain_data.Shipping costs` = 2.956572139430807. Every range test passes;
    the precision is the tell. A coordinate is recorded to a precision somebody chose."""
    values = [f"{2.956572139430807 + i * 0.301701701701:.15f}" for i in range(N)]
    assert "geo.latitude" not in concepts(values)


def test_two_decimal_places_are_not_a_coordinate():
    assert "geo.latitude" not in concepts([f"{18.25 + i * 0.13:.2f}" for i in range(N)])


def test_a_precise_but_repetitive_column_is_not_a_coordinate():
    """A coordinate varies across many places. Ten values repeated is a category."""
    values = [f"{18.25 + (i % 10) * 0.137:.8f}" for i in range(N)]
    assert "geo.latitude" not in concepts(values)


def test_a_defect_rate_reads_as_a_latitude_and_that_is_the_honest_answer():
    """`scm.supply_chain_data.Defect rates` sits inside ±90 at high precision. The values
    genuinely cannot be told from a latitude; the NAME and the missing longitude partner
    are what settle it, one layer up."""
    values = [f"{0.5 + i * 0.0137:.6f}" for i in range(N)]
    assert "geo.latitude" in concepts(values)
    assert not resolve_concept(value_witnesses(values)).is_confident


# ── the layer's standing ─────────────────────────────────────────────────────

def test_no_shape_can_type_a_column_by_itself():
    """The enforcement is AT-4's, not this module's: a witness carries its own layer's
    certainty (`flag.binary` is 0.7 — values that are exactly {0,1} really are a strong
    signal), and `resolve_concept` is what refuses to act on one layer. Asserting on the
    raw confidence would test the wrong object."""
    for values in (_LATS, _LONS, [i % 2 for i in range(N)],
                   [round(i / (N * 2), 4) for i in range(N)],
                   ):
        found = value_witnesses(values)
        assert found
        assert all(w.layer == LAYER_VALUE for w in found)
        verdict = resolve_concept(found)
        assert not verdict.is_confident, f"{verdict.concept} acted on one layer"
        assert verdict.confidence < CONFIDENT


def test_the_value_layer_supplies_the_second_witness_a_name_cannot():
    """The point of the whole wave: `Latitude` is VARCHAR and named like a geo code. Its
    values plus its name are two layers, and two layers decide."""
    from aughor.tools.concept import LAYER_NAME, Witness

    name = Witness(layer=LAYER_NAME, concept="geo.latitude", confidence=0.55,
                   evidence="named like a latitude")
    v = resolve_concept([name] + value_witnesses(_LATS))
    assert v.concept == "geo.latitude"
    assert v.is_confident


def test_evidence_always_carries_the_numbers_a_human_can_check():
    for w in value_witnesses(_LATS) + value_witnesses([i % 2 for i in range(N)]):
        assert any(ch.isdigit() for ch in w.evidence), w.evidence


# ── text: grammars and curated lists ─────────────────────────────────────────

def test_an_email_column_is_recognised():
    values = [f"person{i}@example.com" for i in range(N)]
    w = witness(values, "contact.email")
    assert w is not None
    assert "100% of" in w.evidence and "email address" in w.evidence


def test_a_REDACTED_email_column_is_refused():
    """data_co's `Customer Email` holds `[REDACTED]` on every row. The NAME says email and
    the VALUES say otherwise, so the two layers disagree and nothing is claimed — which is
    the entire thesis, arriving on a real column."""
    assert concepts(["[REDACTED]"] * N) == set()


def test_us_state_codes_beat_country_codes_on_the_same_values():
    """`Customer State` is 96% US states and 50% ISO-3166. Both are the VALUE layer talking
    about the same values, so only the better-supported list is reported — a layer says one
    thing about one column."""
    from aughor.tools.vocab import US_STATE_CODES, membership
    values = ["AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "HI", "IA", "ID",
              "IL", "IN", "KS", "KY", "LA", "MA", "MD", "MI", "MN", "MO", "MT", "NC", "ND",
              "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "PR", "RI", "SC", "TN", "TX",
              "UT", "VA", "WA", "WI", "WV", "91732", "95758"]
    assert membership(values, US_STATE_CODES) >= 0.95
    found = [w for w in value_witnesses(values) if w.concept == "geo.region"]
    assert len(found) == 1, [w.evidence for w in found]
    assert "US state codes" in found[0].evidence


def test_spanish_country_names_reach_the_same_concept_as_country_codes():
    """A place is a place whichever notation it arrives in — and that is the granularity
    the NAME layer can also see, so the two can agree."""
    values = ["Brasil", "Níger", "Papúa Nueva Guinea", "EE. UU.", "Myanmar (Birmania)",
              "SudAfrica", "Bélgica", "Corea del Sur"] * 5
    w = witness(values, "geo.region")
    assert w is not None and "country names" in w.evidence
    assert witness(["US", "GB", "DE", "IN", "BR"] * 8, "geo.region") is not None


def test_a_currency_column_is_recognised_even_at_one_distinct_value():
    """`luxexperience.orders.currency` holds a single code. AT-7's `money.amount` says it
    requires a currency witness; this is the only thing that supplies one."""
    w = witness(["EUR"] * N, "code.currency")
    assert w is not None


def test_a_region_column_is_not_a_country_column():
    values = ["Caribbean", "Central Africa", "Central Asia", "East of USA", "Oceania",
              "South Asia", "Western Europe"] * 10
    assert "geo.region" not in concepts(values)


def test_weekday_and_month_names_are_recognised_across_languages():
    assert "time.weekday" in concepts(["Monday", "martes", "Mittwoch", "jeudi",
                                       "Friday", "sábado", "domenica"] * 10)
    assert "time.month" in concepts(["January", "febrero", "Mars", "April",
                                     "maio", "Giugno"] * 10)


def test_a_grammar_is_measured_over_DISTINCT_values():
    """One address repeated 10,000 times would otherwise carry a column."""
    assert concepts(["a@b.com"] * 200 + [f"junk{i}" for i in range(200)]) == set()


def test_free_text_matches_nothing():
    assert concepts([f"the quick brown fox {i}" for i in range(N)]) == set()


def test_a_uuid_column_is_an_identifier_not_a_concept_of_its_own():
    """A second name for `key.identifier` would split the vote with the name layer, which
    already calls `*_uuid` an identifier."""
    values = [f"{i:08x}-0000-4000-8000-000000000000" for i in range(N)]
    assert "key.identifier" in concepts(values)


def test_text_shapes_are_skipped_on_a_short_sample():
    assert value_witnesses([f"p{i}@example.com" for i in range(MIN_VALUES - 1)]) == []
