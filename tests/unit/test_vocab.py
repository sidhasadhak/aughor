"""AT-5 — the bundled lists, and the one column that proves why they are lists.

`^[A-Z]{2}$` matched `Customer State` (`UT`, `MD`, `GA`) as ISO-3166 country codes. Every
two-letter code has the same shape, so a pattern cannot separate Utah from Moldova. A list
can, and the separation is measurable: of that column's 46 distinct values, 44 are US state
codes and about half are also country codes. One list accepts it at 96%, the other refuses
it at 50%, and the SHARE is the discriminator.
"""
from __future__ import annotations

import re

import pytest

from aughor.tools.vocab import (
    ALL_SETS,
    COUNTRY_NAMES,
    ISO3166_ALPHA2,
    ISO3166_ALPHA3,
    ISO4217,
    MONTH_NAMES,
    US_STATE_CODES,
    WEEKDAY_NAMES,
    membership,
    normalize,
)

#: `Customer State`, exactly as data_co holds it — 44 state codes and two stray zip codes.
CUSTOMER_STATE = [
    "91732", "95758", "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "HI",
    "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "MI", "MN", "MO", "MT", "NC",
    "ND", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "PR", "RI", "SC", "TN", "TX",
    "UT", "VA", "WA", "WI", "WV",
]

#: A sample of what `Order Country` holds — Spanish, accented, abbreviated, parenthesised.
ORDER_COUNTRY = [
    "Brasil", "Níger", "Papúa Nueva Guinea", "EE. UU.", "Myanmar (Birmania)", "SudAfrica",
    "República Democrática del Congo", "Bosnia y Herzegovina", "Corea del Sur", "Bélgica",
    "Sáhara Occidental", "Trinidad y Tobago", "Costa de Marfil", "Emiratos Árabes Unidos",
]


# ── normalisation ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("EE. UU.", "eeuu"),
    ("Papúa Nueva Guinea", "papuanuevaguinea"),
    ("Myanmar (Birmania)", "myanmarbirmania"),
    ("Níger", "niger"),
    ("SudAfrica", "sudafrica"),
    ("Sudáfrica", "sudafrica"),                 # the accented spelling folds to the same key
    ("  UT  ", "ut"),
    ("Bosnia y Herzegovina", "bosniayherzegovina"),
    ("", ""), (None, ""),
])
def test_normalize_folds_everything_that_is_not_a_letter_or_digit(raw, expected):
    assert normalize(raw) == expected


def test_accented_and_unaccented_spellings_are_one_key():
    """The corpus writes `SudAfrica`; a dictionary writes `Sudáfrica`. A vocabulary that
    distinguished them would refuse the data over a missing accent."""
    assert normalize("Sudáfrica") == normalize("SudAfrica")
    assert normalize("Perú") == normalize("Peru")


# ── the discriminator ────────────────────────────────────────────────────────

def test_customer_state_is_us_states_and_is_NOT_country_codes():
    """The measured false positive, refused. Both numbers matter: the state list has to
    accept a column carrying two zip codes, and the country list has to refuse one where
    half the values genuinely ARE country codes."""
    us = membership(CUSTOMER_STATE, US_STATE_CODES)
    iso = membership(CUSTOMER_STATE, ISO3166_ALPHA2 | ISO3166_ALPHA3)
    assert us >= 0.95, us
    assert iso <= 0.60, iso
    assert us > iso


def test_the_spanish_country_names_are_covered():
    """data_co's `Order Country` holds 164 Spanish spellings. A vocabulary that covered
    most of them would score below the threshold and refuse the column outright."""
    assert membership(ORDER_COUNTRY, COUNTRY_NAMES) == 1.0


def test_a_region_column_is_not_a_country_column():
    """`Order Region` holds `Caribbean`, `Central Asia`, `West of USA` — a real dimension
    that is not a country list, and must not be typed as one."""
    regions = ["Caribbean", "Central Africa", "Central America", "Central Asia",
               "East of USA", "Eastern Asia", "Northern Europe", "Oceania", "South Asia",
               "Southeast Asia", "US Center", "West Africa", "Western Europe"]
    assert membership(regions, COUNTRY_NAMES) < 0.5


def test_a_market_column_is_nobody():
    assert membership(["Africa", "Europe", "LATAM", "Pacific Asia", "USCA"], COUNTRY_NAMES) == 0.0


# ── membership is over DISTINCT values ───────────────────────────────────────

def test_membership_counts_distinct_not_rows():
    """One value repeated ten thousand times would otherwise carry a column."""
    assert membership(["USD"] * 10_000 + ["not-a-code"], ISO4217) == 0.5


def test_membership_of_nothing_is_zero_not_one():
    """An absent answer, never a perfect one."""
    assert membership([], ISO4217) == 0.0
    assert membership(None, ISO4217) == 0.0
    assert membership(["", "  ", None], ISO4217) == 0.0


# ── the lists themselves ─────────────────────────────────────────────────────

def test_the_lists_are_the_size_they_should_be():
    assert len(ISO3166_ALPHA2) == 249
    assert len(ISO3166_ALPHA3) == 249
    assert 150 <= len(ISO4217) <= 200
    assert len(US_STATE_CODES) == 57            # 50 + DC + 6 territories
    assert len(COUNTRY_NAMES) >= 250            # English + Spanish, folded
    assert len(WEEKDAY_NAMES) >= 40
    assert len(MONTH_NAMES) >= 60


@pytest.mark.parametrize("code", ["US", "GB", "DE", "IN", "BR", "ZA"])
def test_common_country_codes_are_present(code):
    assert normalize(code) in ISO3166_ALPHA2


@pytest.mark.parametrize("code", ["USD", "EUR", "GBP", "JPY", "INR", "CHF", "BRL"])
def test_common_currencies_are_present(code):
    assert normalize(code) in ISO4217


@pytest.mark.parametrize("name", ["Monday", "lunes", "Sonntag", "Domingo", "Mercredi"])
def test_weekdays_in_several_languages(name):
    assert normalize(name) in WEEKDAY_NAMES


@pytest.mark.parametrize("name", ["January", "enero", "Février", "März", "Dicembre"])
def test_months_in_several_languages(name):
    assert normalize(name) in MONTH_NAMES


def test_every_published_set_is_non_empty_and_normalised():
    for vocabulary in ALL_SETS:
        assert vocabulary
        for key in vocabulary:
            assert key == normalize(key), f"unnormalised key {key!r}"


def test_no_empty_key_ever_enters_a_set():
    """An empty key would make every blank cell a member of every list."""
    for vocabulary in ALL_SETS:
        assert "" not in vocabulary


def test_this_module_publishes_no_concept_NAMES():
    """It shipped naming `code.country`, `geo.us_state` and `geo.country_name` — three
    concepts nothing emits and the operations vocabulary has no rows for — in the one file
    the coverage ratchet does not read. The concept↔list mapping belongs beside the code
    that emits the witness, so a drifted copy cannot exist here to drift."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "aughor" / "tools" / "vocab.py").read_text()
    body = source.split('"""', 2)[-1]           # skip the module docstring
    offenders = re.findall(r'"([a-z_]+\.[a-z_]+)"', body)
    assert not offenders, f"vocab.py names concepts: {offenders}"
