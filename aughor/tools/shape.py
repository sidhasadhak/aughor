"""AT-5 — what a column IS according to its VALUES, and nothing else.

The layer this module adds is the one the roadmap's opening example turns on. The LOADER
said `Latitude` was `VARCHAR`; the values said coordinates to eight decimal places. The
NAME said `Late_delivery_risk` was a risk score; the values said 0 and 1. Both times the
values were right and both times nothing asked them.

**Neither the name nor the declared type is consulted here.** The name is a different
layer, and reading it would make this one an echo rather than a witness — AT-0 measured 27
columns across 9 of 13 datasets where the two disagree, and the whole point of a second
opinion is that it can differ. The dtype is excluded for a sharper reason: the dtype is the
LOADER's opinion, and the loader is the witness that was wrong. The same DataCo export
lands `Latitude` as VARCHAR here and as a float in BigQuery; a rule that consults it makes
the identical column readable on one warehouse and invisible on the other, which is a
property of the import, not of the data.

So a column arrives as a tuple of stringified values and the rules read them as written.
Strings matter: `18.2514534` and `18.25` are different evidence about what somebody
recorded, and `float()` erases the difference.

**Scope.**

    flag.binary        values are exactly {0, 1}
    percent.fraction   inside [0, 1], not binary, and not whole numbers
    geo.latitude       inside ±90, recorded to 4–10 decimals, many distinct
    geo.longitude      inside ±180 and leaving ±90, same precision test
    …and for text, a GRAMMAR table (email, UUID, E.164, ZIP, IP, ISO-8601) and
    SET membership against `aughor.tools.vocab` (currency codes, country codes and
    names, US states, weekday and month names).

**A concept is never made finer than the coarsest layer that can see it.** The value layer
knows `Customer State` holds US state codes and the name layer only knows it is a place —
so both emit `geo.region` and the *kind* goes in the evidence sentence. Splitting them
would give one concept the name's vote and another the value's, and a column with two
agreeing layers would resolve to a hint. That is not hypothetical: it happened to the
best-evidenced flag in the corpus and cost `flag.derived_comparison` its existence.

**`percent.whole` is deliberately absent**, and AT-0 asked for it — its Q6 scope note reads
"build `percent.fraction` vs `percent.whole`". Measured during this build across all 105
tables, `0 ≤ v ≤ 100` fires on **82 columns** and about **two** of them are percentages:
the band is where counts, ratings, quarters, months, weights, prices and small durations
all live (`quantity` 1–14, `csat` 1–5, `month` 1–12, `bathrooms` 1–5.25). Requiring a
fractional part cuts it to 15 and 13 of those are still wrong — one of the survivors is
`Latitude`. There is no range test that separates a whole-scale percentage from a small
count, because there is no difference in the values. The scale ambiguity AT-0 found is
real and remains UNRESOLVED; what this measurement says is that the VALUE layer is not
where it can be resolved.

The grammar table (email, UUID, ISO-4217 …) and the set-membership witnesses (ISO-3166 vs
US states, country names) are a later wave. Checksums — Luhn, IBAN, ISBN-13, EAN — are
never coming: AT-0 found zero columns carrying one across 105 tables, and a module with
real code, real tests and no customers is a cost with no answer attached.

**No witness here can type a column by itself**, and that is measurement rather than
caution. Of the 5 columns in the corpus whose values sit inside ±90 at four decimals, 3 are
not coordinates. Of the 12 bounded 0–1, `fare_multiplier` (0.2–1.0) and
`attribution.weight` (0.4–1.0) are not proportions. The enforcement is AT-4's, not this
module's: `resolve_concept` caps a LONE witness below CONFIDENT whatever it claims, so the
confidences below are only this layer's own certainty and only decide which concept wins
once a second layer agrees. A value shape narrows the candidates; it does not decide.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from aughor.tools.concept import LAYER_VALUE, Witness
from aughor.tools.vocab import (
    COUNTRY_NAMES,
    ISO3166_ALPHA2,
    ISO3166_ALPHA3,
    ISO4217,
    MONTH_NAMES,
    US_STATE_CODES,
    WEEKDAY_NAMES,
    membership,
)

#: Share of non-null sampled values that must parse as numbers before the numeric rules run
#: at all. This is the "numeric-castable text" gate AT-0 measured at 15 of 522 text columns
#: — not a concept in its own right (`numeric_expression` already handles the query-time
#: half), but the switch that lets a VARCHAR latitude be read as a latitude.
NUMERIC_SHARE = 0.95

#: Below this many parsed values a shape is a coincidence. Nine values inside ±90 is not
#: evidence about a column; it is evidence about nine rows.
MIN_VALUES = 30

#: Coordinates: recorded to a precision somebody CHOSE. Below 4 decimals a coordinate is
#: not one; above 10 the digits are a float printed in full, which means the number was
#: computed rather than recorded (`scm.supply_chain_data` stores 2.956572139430807, data_co
#: stores 18.2514534). Shared with `aughor.tools.pairs`, which learned it the same way.
COORD_MIN_DECIMALS = 4
COORD_MAX_DECIMALS = 10
COORD_MIN_DISTINCT = 50

#: A grammar is exact — an address either parses as an email or it does not — so it is held
#: to a higher bar than a curated list, which is allowed real-world debris.
GRAMMAR_SHARE = 0.95

#: A set is allowed outliers, because real columns carry them: `Customer State` holds 44 US
#: state codes and two zip codes (95.7%), and refusing it over those two would be refusing
#: the answer to keep the rule tidy.
SET_SHARE = 0.90

_NUMERIC_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
_NULLISH = {"", "null", "none", "nan", "na", "n/a"}


def as_float(value) -> Optional[float]:
    """A cell as a float, or None when it holds no number.

    Public and shared: `aughor.tools.pairs` reads the same sample, and two parsers over one
    sample is two chances to disagree about what a cell holds.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in _NULLISH:
        return None
    if not _NUMERIC_RE.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def decimals(value) -> int:
    """Digits after the decimal point AS WRITTEN — read from the string, never the float."""
    text = str(value or "").strip()
    if "." not in text or not _NUMERIC_RE.match(text):
        return 0
    frac = text.split(".", 1)[1].split("e")[0].split("E")[0].rstrip("0")
    return len(frac)


def is_nullish(value) -> bool:
    return value is None or str(value).strip().lower() in _NULLISH


@dataclass(frozen=True)
class NumericShape:
    """What a column's values look like as numbers. Every field is a fact about the sample,
    not a judgement about the column — the judgements are the witnesses below."""
    n_present: int = 0          # cells holding anything at all
    n_numeric: int = 0          # cells that parsed
    distinct: int = 0
    lo: float = 0.0
    hi: float = 0.0
    median_decimals: int = 0
    all_integral: bool = True
    values: tuple = ()

    @property
    def numeric_share(self) -> float:
        return self.n_numeric / self.n_present if self.n_present else 0.0

    @property
    def is_numeric(self) -> bool:
        return self.n_numeric >= MIN_VALUES and self.numeric_share >= NUMERIC_SHARE

    @property
    def is_binary(self) -> bool:
        return self.distinct == 2 and set(self.values) == {0.0, 1.0}


def read_numeric(values: Iterable) -> NumericShape:
    """Parse a column's sampled values once. Never raises."""
    raw = tuple(values or ())
    present = [v for v in raw if not is_nullish(v)]
    parsed = [(v, as_float(v)) for v in present]
    nums = [f for _, f in parsed if f is not None]
    if not nums:
        return NumericShape(n_present=len(present))
    decs = sorted(decimals(v) for v, f in parsed if f is not None)
    return NumericShape(
        n_present=len(present),
        n_numeric=len(nums),
        distinct=len(set(nums)),
        lo=min(nums),
        hi=max(nums),
        median_decimals=decs[len(decs) // 2] if decs else 0,
        all_integral=all(f == int(f) for f in nums),
        values=tuple(nums),
    )


def _witness(concept: str, confidence: float, evidence: str) -> Witness:
    return Witness(layer=LAYER_VALUE, concept=concept, confidence=confidence, evidence=evidence)


def _range_text(shape: NumericShape) -> str:
    return f"{shape.lo:g}…{shape.hi:g} over {shape.distinct} distinct values"


# ── the grammar table ────────────────────────────────────────────────────────
# One row per shape text can take. AT-0 measured only `email` firing anywhere in the corpus
# — UUID, E.164, ZIP, IPv4 and ISO-8601-in-text are all zero across 105 tables — and the
# rows are here anyway because a compiled regex is nearly free and the alternative is
# noticing the gap the day a column needs it. Checksums are the opposite trade and stay
# refused: Luhn, IBAN mod-97, ISBN-13 and EAN are real code with real tests and, measured,
# zero customers.
#
# `key.identifier` for UUIDs rather than a concept of its own: the name layer already calls
# `*_uuid` an identifier, and a second name for the same idea splits the vote.
_GRAMMARS: tuple = (
    ("contact.email", 0.7, "an email address",
     re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")),
    ("key.identifier", 0.75, "a UUID",
     re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")),
    ("contact.phone", 0.7, "an E.164 phone number", re.compile(r"^\+[1-9]\d{7,14}$")),
    ("net.ip_address", 0.75, "an IPv4 address",
     re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")),
    ("net.ip_address", 0.75, "an IPv6 address",
     re.compile(r"^(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$")),
    ("geo.postal_code", 0.55, "a US ZIP code", re.compile(r"^\d{5}(?:-\d{4})?$")),
    # ⚠ The one place this layer is not fully independent of the loader: a DATE-typed
    # column stringifies to `2026-08-17`, so its values match because of its type, and the
    # name layer's timestamp rule reads that same type. Two witnesses, one source. It is
    # left in because it cannot produce a WRONG answer — a column the loader typed as a
    # date is a date — but do not read a confident `time.instant` on a DATE column as two
    # independent opinions. On a VARCHAR date column (data_co's `order date (DateOrders)`)
    # the independence is real, and that is the case worth having.
    ("time.instant", 0.7, "an ISO-8601 timestamp",
     re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")),
)

#: Curated lists, and the concept each supports. Country codes, country names and US state
#: codes all answer `geo.region` — a named place is a grouping key whichever notation it
#: arrives in, and that is the granularity the NAME layer can also see.
_SETS: tuple = (
    ("code.currency", 0.7, "ISO-4217 currency codes", ISO4217),
    ("geo.region", 0.65, "ISO-3166 country codes", ISO3166_ALPHA2 | ISO3166_ALPHA3),
    ("geo.region", 0.65, "US state codes", US_STATE_CODES),
    ("geo.region", 0.65, "country names", COUNTRY_NAMES),
    ("time.weekday", 0.7, "weekday names", WEEKDAY_NAMES),
    ("time.month", 0.7, "month names", MONTH_NAMES),
)


def _text_witnesses(values: tuple) -> list[Witness]:
    """Grammars and set membership, over the DISTINCT values.

    Distinct rather than rows throughout: a column where one address repeats 10,000 times
    would otherwise pass on the strength of a single match, and a skewed dimension would
    beat a varied one for no reason connected to what the column is.
    """
    distinct = {str(v).strip() for v in values if not is_nullish(v)}
    if not distinct:
        return []

    out: list[Witness] = []
    for concept, confidence, label, pattern in _GRAMMARS:
        share = sum(1 for v in distinct if pattern.match(v)) / len(distinct)
        if share >= GRAMMAR_SHARE:
            out.append(_witness(
                concept, confidence,
                f"{share:.0%} of {len(distinct)} distinct values are {label}"))

    # Competing lists are settled HERE, not by the resolver: `Customer State` is 95.7% US
    # state codes and 50.0% ISO-3166 country codes, and both claims are the value layer
    # speaking about the same values. Only the best-supported one is reported, so a layer
    # says one thing about one column.
    best: dict[str, tuple] = {}
    for concept, confidence, label, vocabulary in _SETS:
        share = membership(distinct, vocabulary)
        if share >= SET_SHARE and share > best.get(concept, (0.0,))[0]:
            best[concept] = (share, confidence, label)
    for concept, (share, confidence, label) in best.items():
        out.append(_witness(
            concept, confidence,
            f"{share:.0%} of {len(distinct)} distinct values are {label}"))
    return out


def value_witnesses(values: Iterable) -> list[Witness]:
    """The VALUE layer's opinion about one column, from its sampled values alone.

    Returns every shape the values are consistent with, not a single best guess. A column
    inside [0, 1] is consistent with a proportion; a column inside ±90 at eight decimals is
    consistent with a latitude; a column can be consistent with both and the resolver is
    where that gets settled against the other layers. Choosing here would be the same
    mistake the module exists to prevent, one level earlier.
    """
    raw = tuple(values or ())
    shape = read_numeric(raw)
    if not shape.is_numeric:
        # Not numbers — so the question is what SHAPE the text takes, and which curated
        # list it belongs to. A column is one or the other: a set of country codes is not
        # also a bounded numeric, and running both would be inventing a second opinion out
        # of the same observation.
        return _text_witnesses(raw) if len(raw) >= MIN_VALUES else []

    cast_note = ""
    if shape.numeric_share < 1.0:
        cast_note = f"; {shape.numeric_share:.0%} of values parse as numbers"

    out: list[Witness] = []

    # ── exactly {0, 1} ────────────────────────────────────────────────────────
    # The strongest shape in this module and still not enough alone: a status column, a
    # deleted marker and a genuine indicator are indistinguishable by values.
    if shape.is_binary:
        return [_witness(
            "flag.binary", 0.7,
            f"every value is 0 or 1 over {shape.n_numeric} sampled rows{cast_note}")]

    # A single distinct value describes the sample, not the column.
    if shape.distinct < 2:
        return []

    # ── proportions ───────────────────────────────────────────────────────────
    # Bounded 0–1 AND fractional is a real signal: 10 columns across the corpus, 9 of them
    # genuine proportions (discounts, duty rates, open rates, fraud scores). The tenth,
    # `attribution.weight` at 0.4…1.0 over 3 values, is why this is 0.5 and not higher.
    # The `all_integral` test is doing work — without it every 0/1/2 column joins in.
    if shape.lo >= 0.0 and shape.hi <= 1.0 and not shape.all_integral:
        out.append(_witness(
            "percent.fraction", 0.5,
            f"every value inside 0…1 ({_range_text(shape)}){cast_note}"))

    # ── coordinates ───────────────────────────────────────────────────────────
    # Bounded, precise, and varied. AT-0 measured this test alone at a 60% false-positive
    # rate, which is why it scores below the proportion rules despite being far more
    # specific: `Shipping costs` and `Defect rates` both sit inside ±90.
    precise = COORD_MIN_DECIMALS <= shape.median_decimals <= COORD_MAX_DECIMALS
    varied = shape.distinct >= COORD_MIN_DISTINCT
    if precise and varied:
        detail = (f"{_range_text(shape)} at {shape.median_decimals} decimal places"
                  f"{cast_note}")
        if -90.0 <= shape.lo and shape.hi <= 90.0:
            out.append(_witness("geo.latitude", 0.45, f"inside ±90: {detail}"))
        # A longitude has to leave ±90 somewhere, or nothing in the values separates it
        # from a latitude.
        if -180.0 <= shape.lo and shape.hi <= 180.0 and (shape.lo < -90.0 or shape.hi > 90.0):
            out.append(_witness("geo.longitude", 0.45, f"inside ±180 and beyond ±90: {detail}"))

    return out
