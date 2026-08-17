"""AT-6 — the concepts that only exist as PAIRS, each decided by a computed test.

A single column can be read wrong with total confidence. A pair cannot lie as easily,
because the rule has to hold on real rows: `Late_delivery_risk` looks like a risk score
until you notice it equals `real > scheduled` on 97.5% of 180,519 rows, at which point it
is not a score at all, it is a comparison someone stored.

Everything here is a second witness for both members, which is the point. The AT-0
pre-check found `Latitude` typed VARCHAR and named like a key; it reaches `geo.latitude`
here on range + partner, without its name being read once.

**The name is never consulted in this module.** A pair rule that leans on a shared stem is
not a pair rule, it is the name layer wearing a hat — and AT-0 measured what that costs:
zero of the corpus's binary-flag/duration pairs share a stem, *including the case this
wave exists for* (`Late_delivery_risk` vs `Days for shipping (real)` — "delivery" is not
"shipping"). The spec's lexical test would have missed its own motivating example. So
every rule below is arithmetic on sampled rows.

The rules, in the order AT-0 measured them worth building:

    arithmetic identity   a × b ≈ c        7 pairs in 6 datasets — the strongest signal
    start / end           a ≤ b per row    4 datasets
    duplicate column      a == b always    the tautology guard, below
    derived flag          f == (a > b)     the computed form of the MAGNITUDE GUARD
    coordinate partner    ±90 beside ±180  1 real pair; kept CHEAP and structural

Three things cut, each with a receipt:

* the bundled city-centroid table — AT-0 found one real coordinate pair in 105 tables,
  which does not earn a geographic fixture;
* gross/net — AT-0's one hit was a false positive on inspection (`net_sales_eur_m` and
  `gross_profit_eur_m` are different measures, not two views of one);
* **actual/planned by distribution shape** — cut during THIS wave, on a measurement. The
  spec's signature (difference centred near zero, right tail) does not discriminate:
  measured on data_co, the true pair `Days for shipping (real)` / `Days for shipment
  (scheduled)` sits at a median absolute difference of 0.25× its own magnitude, while
  `Sales per customer` / `Order Item Product Price` — two unrelated measures — sits at
  0.226 and `Sales` / `Order Item Total` at 0.070. There is no threshold that admits the
  true pair and refuses those. A first implementation shipped 18 findings on the one table
  the rule existed for, all but one nonsense. The concept survives: the derived-flag rule
  below names exactly the same two columns from an EQUALITY on 98.3% of rows, which is
  evidence a shape test cannot match.

And one thing AT-0 forced in: **constant factors are rejected.** The identity sweep
returned `transactionID × unitPrice ≈ franchiseID` holding on 100% of rows because
`unitPrice` was the constant 3, which makes `a × b ≈ c` a restatement of `c ∝ a`. A factor
that never varies is not evidence of an identity; it is a unit conversion at best.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from aughor.tools.concept import LAYER_PAIR, Witness

# ── Bounds. Every one of these caps is REPORTED when it truncates (see `truncated`),
# because a silent cap reads as "we looked at everything" when we did not. The first
# version of this module capped numeric columns at 20 and data_co has 27 — so the cap
# dropped `Sales`, `Order Item Total` and `Product Price`, which is where the identity
# actually lives. The sweep found nothing and said nothing was there. The cap is now high
# enough for a real wide table because the search early-aborts instead of scoring every
# triple to completion.
MAX_NUMERIC_COLS = 40
MAX_FLAG_COLS = 8            # flags × ordered numeric pairs
MAX_TIME_COLS = 8

#: A rule must hold on at least this share of the rows where every side has a value.
#: 0.95 rather than 1.0 because real exports carry corrections: the motivating case sits
#: at 0.9755 and is unambiguously the rule someone wrote.
SUPPORT = 0.95

#: Below this many usable rows a share is noise, not support. A 20-row sample agreeing
#: 100% of the time is one coincidence away from a finding.
MIN_ROWS = 30

#: Identity tolerance. RELATIVE alone is what let a constant factor through, so the test
#: is relative OR a small absolute — and the constant-factor rejection below is the part
#: that actually does the work.
REL_TOL = 0.005
ABS_TOL = 0.01

#: A factor must take at least this many distinct values in the sample. This is the
#: `unitPrice = 3` guard, stated as a number.
MIN_FACTOR_DISTINCT = 3

#: Coordinate candidates: a coordinate is recorded to a precision a rating or a cost is
#: not, and it varies across many places.
COORD_MIN_DECIMALS = 4
#: …and to a precision a human CHOSE. This ceiling is the fix for the one false positive
#: AT-0 named in advance: `scm.supply_chain_data` stores `Shipping costs`
#: 2.956572139430807 beside `Price` 69.80800554211577, which passes every range test —
#: 69.8 does leave ±90 further down the column, and both sit in bounds. But sixteen
#: significant digits is a float printed in full, which means the number was COMPUTED;
#: data_co's coordinates read 18.2514534 and -66.03705597, a precision somebody recorded.
#: Sub-micrometre geography does not exist, so past ten decimals the digits are an artifact
#: of the type, not evidence about the concept.
COORD_MAX_DECIMALS = 10
COORD_MIN_DISTINCT = 50


@dataclass(frozen=True)
class ColumnSample:
    """One column's values from a ROW-ALIGNED sample: index i is the same row in every
    ColumnSample of the same scan. That alignment is the whole capability — `f == (a > b)`
    is unanswerable from three independent samples."""
    column: str
    dtype: str = ""
    values: tuple = ()


@dataclass(frozen=True)
class PairFinding:
    """A rule that held, with the number it held on.

    `expression` is the SQL for the quantity the pair implies where there is one — the
    subtraction intake had to invent by itself in six consecutive runs. `note` is the
    sentence a human reads; it always carries the support and the row count, so a rule
    that held on 31 rows cannot be mistaken for one that held on 180,000.

    `roles` is positional against `columns`: what this rule says each member IS, with ""
    where it says nothing. A rule decides its own roles at scan time rather than reading
    them from a table, because the answer is sometimes computed — which factor of a product
    is a per-unit rate depends on which one holds whole numbers, not on which rule fired.
    """
    kind: str
    columns: tuple[str, ...]
    support: float
    n_rows: int
    expression: str = ""
    note: str = ""
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class PairScan:
    """Findings plus what was NOT looked at. `truncated` exists so a bounded sweep never
    reads as an exhaustive one."""
    findings: list[PairFinding] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)


# ── Parsing the sample ────────────────────────────────────────────────────────

_NUMERIC_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
_NULLISH = {"", "null", "none", "nan", "na", "n/a"}


def _as_float(value) -> Optional[float]:
    """A cell as a float, or None. A VARCHAR holding '18.2514534' is a number here — that
    is the entire reason `Latitude` was invisible to every numeric path before AT-6."""
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


def _decimals(value) -> int:
    """Digits after the decimal point AS WRITTEN. Read from the string, not the float:
    18.2514534 and 18.25 are different evidence, and float() erases the difference."""
    text = str(value or "").strip()
    if "." not in text or not _NUMERIC_RE.match(text):
        return 0
    frac = text.split(".", 1)[1].split("e")[0].split("E")[0].rstrip("0")
    return len(frac)


_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%d/%m/%Y %H:%M")


def _try_parse(text: str, parse) -> Optional[datetime]:
    """One parse attempt. A cell that is not a timestamp is the ordinary case here, not a
    failure worth a trail — so this returns the answer rather than swallowing an exception
    with a bare `pass`."""
    try:
        return parse(text)
    except (ValueError, TypeError):
        return None


def _as_time(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text or text.lower() in _NULLISH:
        return None
    got = _try_parse(text, datetime.fromisoformat)
    for fmt in _TS_FORMATS:
        if got is not None:
            break
        got = _try_parse(text, lambda t, f=fmt: datetime.strptime(t, f))
    return got


@dataclass
class _Col:
    """A parsed column: the raw sample plus the two readings the rules need."""
    name: str
    dtype: str
    raw: tuple
    nums: list                  # float | None, row-aligned
    times: list                 # datetime | None, row-aligned
    n_numeric: int = 0
    n_time: int = 0
    distinct_nums: int = 0
    median_decimals: int = 0
    lo: Optional[float] = None
    hi: Optional[float] = None

    @property
    def is_numeric(self) -> bool:
        # A column is numeric here when its VALUES are, whatever the loader called it.
        return self.n_numeric >= MIN_ROWS and self.n_numeric >= 0.9 * max(1, self._n_present)

    @property
    def is_time(self) -> bool:
        return self.n_time >= MIN_ROWS and self.n_time >= 0.9 * max(1, self._n_present)

    @property
    def is_binary(self) -> bool:
        """Exactly {0, 1}. One distinct value carries no information and is not a flag."""
        if self.distinct_nums != 2 or not self.is_numeric:
            return False
        vals = {v for v in self.nums if v is not None}
        return vals == {0.0, 1.0}

    @property
    def _n_present(self) -> int:
        return sum(1 for v in self.raw if v is not None and str(v).strip().lower() not in _NULLISH)


def _parse(samples: Iterable[ColumnSample]) -> list[_Col]:
    cols: list[_Col] = []
    for s in samples or ():
        nums = [_as_float(v) for v in s.values]
        present = [v for v in nums if v is not None]
        # Timestamps are only parsed when the column is not already a number: '20150131'
        # is a plausible date and an unambiguous integer, and treating it as both makes
        # every rule below answer twice.
        times = [] if len(present) >= MIN_ROWS else [_as_time(v) for v in s.values]
        decs = sorted(_decimals(v) for v in s.values if _as_float(v) is not None)
        col = _Col(
            name=s.column, dtype=s.dtype or "", raw=tuple(s.values),
            nums=nums, times=times,
            n_numeric=len(present),
            n_time=sum(1 for t in times if t is not None),
            distinct_nums=len(set(present)),
            median_decimals=decs[len(decs) // 2] if decs else 0,
            lo=min(present) if present else None,
            hi=max(present) if present else None,
        )
        cols.append(col)
    return cols


def _support(hits: int, tested: int) -> float:
    return round(hits / tested, 4) if tested else 0.0


# ── Rule 1 · arithmetic identity (AT-0: the most prevalent pair signal) ───────

def _identity_findings(cols: list[_Col], truncated: list[str]) -> list[PairFinding]:
    numeric = [c for c in cols if c.is_numeric and c.distinct_nums >= MIN_FACTOR_DISTINCT]
    if len(numeric) > MAX_NUMERIC_COLS:
        truncated.append(
            f"arithmetic identity: {len(numeric)} numeric columns exceed the "
            f"{MAX_NUMERIC_COLS}-column cap — the last {len(numeric) - MAX_NUMERIC_COLS} were not tested")
        numeric = numeric[:MAX_NUMERIC_COLS]

    out: list[PairFinding] = []
    for i, a in enumerate(numeric):
        for b in numeric[i + 1:]:
            for c in numeric:
                if c.name in (a.name, b.name):
                    continue
                usable = sum(
                    1 for av, bv, cv in zip(a.nums, b.nums, c.nums)
                    if av is not None and bv is not None and cv is not None
                )
                if usable < MIN_ROWS:
                    continue
                # A wrong triple is wrong on nearly every row, so counting misses and
                # abandoning at the first row that cannot be recovered turns an O(n³)
                # sweep into something that finishes: the budget is spent only on triples
                # that keep agreeing.
                budget = int(usable * (1.0 - SUPPORT))
                misses = tested = hits = 0
                for av, bv, cv in zip(a.nums, b.nums, c.nums):
                    if av is None or bv is None or cv is None:
                        continue
                    tested += 1
                    if abs(av * bv - cv) <= max(ABS_TOL, REL_TOL * abs(cv)):
                        hits += 1
                    else:
                        misses += 1
                        if misses > budget:
                            break
                if misses > budget:
                    continue
                share = _support(hits, tested)
                if share >= SUPPORT:
                    # Which factor is the RATE is computed, not named: a count holds whole
                    # numbers, a per-unit price does not. This is the fact AT-7 turns into
                    # "never SUM this column".
                    a_whole = all(v == int(v) for v in a.nums if v is not None)
                    b_whole = all(v == int(v) for v in b.nums if v is not None)
                    if a_whole and not b_whole:
                        roles = ("count.quantity", "rate.per_unit", "measure.additive_total")
                    elif b_whole and not a_whole:
                        roles = ("rate.per_unit", "count.quantity", "measure.additive_total")
                    else:
                        roles = ("", "", "measure.additive_total")
                    out.append(PairFinding(
                        kind="arithmetic_identity",
                        columns=(a.name, b.name, c.name),
                        support=share, n_rows=tested,
                        expression=f'"{a.name}" * "{b.name}"',
                        note=(f'"{a.name}" × "{b.name}" equals "{c.name}" on {share:.1%} of '
                              f'{tested} sampled rows — "{c.name}" is the product, and neither '
                              f"factor is constant"),
                        roles=roles,
                    ))
    return out


# ── Rule 2 · start / end ──────────────────────────────────────────────────────

def _start_end_findings(cols: list[_Col], truncated: list[str]) -> list[PairFinding]:
    times = [c for c in cols if c.is_time]
    if len(times) > MAX_TIME_COLS:
        truncated.append(
            f"start/end: {len(times)} timestamp columns exceed the {MAX_TIME_COLS}-column cap")
        times = times[:MAX_TIME_COLS]

    out: list[PairFinding] = []
    for i, a in enumerate(times):
        for b in times[i + 1:]:
            fwd = rev = strict_fwd = strict_rev = tested = 0
            for av, bv in zip(a.times, b.times):
                if av is None or bv is None:
                    continue
                tested += 1
                if av <= bv:
                    fwd += 1
                if bv <= av:
                    rev += 1
                if av < bv:
                    strict_fwd += 1
                if bv < av:
                    strict_rev += 1
            if tested < MIN_ROWS:
                continue
            # An ordering that holds only because the two columns are equal is not a span.
            for start, end, ordered, strict in ((a, b, fwd, strict_fwd), (b, a, rev, strict_rev)):
                if _support(ordered, tested) >= SUPPORT and _support(strict, tested) >= 0.5:
                    out.append(PairFinding(
                        kind="start_end",
                        columns=(start.name, end.name),
                        support=_support(ordered, tested), n_rows=tested,
                        expression=f'"{end.name}" - "{start.name}"',
                        note=(f'"{start.name}" is at or before "{end.name}" on '
                              f'{_support(ordered, tested):.1%} of {tested} sampled rows — the '
                              f"span between them is a duration this table does not store"),
                        roles=("time.start", "time.end"),
                    ))
                    break
    return out


# ── Rule 3 · the same column twice, under two names ───────────────────────────

def _duplicate_findings(cols: list[_Col]) -> list[PairFinding]:
    """Two columns that hold the same value on every row.

    This replaced the actual/planned shape test (see the module docstring) and it earns the
    slot on the same table that killed its predecessor: data_co carries `Benefit per order`
    and `Order Profit Per Order` with a median absolute difference of exactly 0 across all
    180,519 rows and 21,998 identical distinct values. They are one column stored twice.

    Why it belongs in a truthfulness program: the relationship primitive refuses two sides
    that name the SAME column, but nothing refuses two sides that name two names for one
    column. Correlate those and the answer is r = 1.0, delivered as a discovery — the
    tautology Track 1 spent a day removing, arriving through a door Track 1 did not close.
    """
    numeric = [c for c in cols if c.is_numeric][:MAX_NUMERIC_COLS]
    out: list[PairFinding] = []
    for i, a in enumerate(numeric):
        if a.distinct_nums < 2:                     # a constant equals every other constant
            continue
        for b in numeric[i + 1:]:
            if b.distinct_nums < 2:
                continue
            same = tested = 0
            for av, bv in zip(a.nums, b.nums):
                if av is None or bv is None:
                    continue
                tested += 1
                if av == bv:
                    same += 1
            if tested < MIN_ROWS or same != tested:
                continue                            # a duplicate is exact, not mostly
            out.append(PairFinding(
                kind="duplicate_column",
                columns=(a.name, b.name),
                support=1.0, n_rows=tested,
                note=(f'"{a.name}" and "{b.name}" hold the same value on all {tested} sampled '
                      f"rows over {a.distinct_nums} distinct values — they are one column "
                      f"under two names, and comparing them measures nothing"),
                roles=("", ""),
            ))
    return out


# ── Rule 4 · the derived flag (AT-0 finding 2 — the computed MAGNITUDE GUARD) ─

def _derived_flag_findings(cols: list[_Col], truncated: list[str]) -> list[PairFinding]:
    """`f == (a > b)` — the 0/1 column that is a comparison someone stored.

    No single-column threshold explains `Late_delivery_risk`; nothing about it reaches 90%
    on its own. The pair does: it equals `real > scheduled` on 97.55% of 180,519 rows. That
    turns the intake MAGNITUDE GUARD from a paragraph of prompt into a fact with a number —
    the flag answers "how often", and the subtraction beside it answers "how much".
    """
    flags = [c for c in cols if c.is_binary]
    if len(flags) > MAX_FLAG_COLS:
        truncated.append(f"derived flag: {len(flags)} binary columns exceed the {MAX_FLAG_COLS}-column cap")
        flags = flags[:MAX_FLAG_COLS]
    numeric = [c for c in cols if c.is_numeric and c.distinct_nums >= 2 and not c.is_binary]
    numeric = numeric[:MAX_NUMERIC_COLS]

    out: list[PairFinding] = []
    for f in flags:
        best: Optional[PairFinding] = None
        for a in numeric:
            for b in numeric:
                if a.name == b.name:
                    continue
                for op, test in ((">", lambda x, y: x > y), (">=", lambda x, y: x >= y)):
                    hits = tested = 0
                    for fv, av, bv in zip(f.nums, a.nums, b.nums):
                        if fv is None or av is None or bv is None:
                            continue
                        tested += 1
                        if (fv == 1.0) == test(av, bv):
                            hits += 1
                    if tested < MIN_ROWS:
                        continue
                    share = _support(hits, tested)
                    if share >= SUPPORT and (best is None or share > best.support):
                        best = PairFinding(
                            kind="derived_flag",
                            columns=(f.name, a.name, b.name),
                            support=share, n_rows=tested,
                            expression=f'"{a.name}" - "{b.name}"',
                            note=(f'"{f.name}" holds 0/1 and equals ("{a.name}" {op} "{b.name}") '
                                  f"on {share:.1%} of {tested} sampled rows — it is a comparison "
                                  f'someone stored, not a measured quantity. The magnitude behind '
                                  f'it is "{a.name}" - "{b.name}"'),
                            roles=("flag.derived_comparison", "measure.actual", "measure.planned"),
                        )
        if best is not None:
            out.append(best)
    return out


# ── Rule 5 · coordinate partner (cheap and structural — AT-0 cut the centroids) ─

def _is_lat_candidate(c: _Col) -> bool:
    return bool(
        c.is_numeric and c.lo is not None and c.hi is not None
        and -90.0 <= c.lo and c.hi <= 90.0
        and COORD_MIN_DECIMALS <= c.median_decimals <= COORD_MAX_DECIMALS
        and c.distinct_nums >= COORD_MIN_DISTINCT
    )


def _is_lon_candidate(c: _Col) -> bool:
    # The |value| > 90 requirement is what makes this a partner test rather than a second
    # guess: a column that never leaves ±90 cannot be told from a latitude by range alone,
    # and AT-0 measured a 60% false-positive rate for exactly that test run on its own.
    return bool(
        c.is_numeric and c.lo is not None and c.hi is not None
        and -180.0 <= c.lo and c.hi <= 180.0
        and (c.lo < -90.0 or c.hi > 90.0)
        and COORD_MIN_DECIMALS <= c.median_decimals <= COORD_MAX_DECIMALS
        and c.distinct_nums >= COORD_MIN_DISTINCT
    )


def _coordinate_findings(cols: list[_Col]) -> list[PairFinding]:
    lats = [c for c in cols if _is_lat_candidate(c)]
    lons = [c for c in cols if _is_lon_candidate(c)]
    lats = [c for c in lats if not _is_lon_candidate(c)]
    if not lats or not lons:
        return []
    lat, lon = lats[0], lons[0]
    n = sum(1 for a, b in zip(lat.nums, lon.nums) if a is not None and b is not None)
    if n < MIN_ROWS:
        return []
    return [PairFinding(
        kind="coordinate_partner",
        columns=(lat.name, lon.name),
        support=1.0, n_rows=n,
        note=(f'"{lat.name}" stays inside ±90 and "{lon.name}" leaves it (to {lon.lo:g}…{lon.hi:g}), '
              f"both to {min(lat.median_decimals, lon.median_decimals)} decimal places over "
              f"{lat.distinct_nums} and {lon.distinct_nums} distinct values — a latitude needs a "
              f"longitude, and this table has one"),
        roles=("geo.latitude", "geo.longitude"),
    )]


# ── The scan, and the witnesses it implies ────────────────────────────────────

def scan_pairs(samples: Iterable[ColumnSample]) -> PairScan:
    """Every pair rule that holds on a row-aligned sample. Never raises, never queries."""
    cols = _parse(samples)
    if len(cols) < 2:
        return PairScan()
    truncated: list[str] = []
    findings = (
        _identity_findings(cols, truncated)
        + _start_end_findings(cols, truncated)
        + _duplicate_findings(cols)
        + _derived_flag_findings(cols, truncated)
        + _coordinate_findings(cols)
    )
    return PairScan(findings=findings, truncated=truncated)


#: How much each rule is worth as ONE witness. None reaches CONFIDENT alone by accident:
#: under AT-4 a lone witness is capped below it regardless, and these numbers only decide
#: what wins when two layers do agree.
_STRENGTH: dict[str, float] = {
    "derived_flag": 0.8,            # an equality on 180k rows is the strongest thing here
    "coordinate_partner": 0.7,
    "arithmetic_identity": 0.65,
    "start_end": 0.6,
}


def pair_witnesses(scan: PairScan) -> dict[str, list[Witness]]:
    """{column: [Witness]} — the pair layer's opinion, ready for `resolve_concept`.

    A rule speaks about every member it has a role for, which is what makes pair coherence
    a second witness for BOTH sides rather than a fact about one of them.
    """
    out: dict[str, list[Witness]] = {}
    for f in (scan.findings if scan else []):
        for column, concept in zip(f.columns, f.roles):
            if not concept:
                continue
            out.setdefault(column, []).append(Witness(
                layer=LAYER_PAIR,
                concept=concept,
                confidence=_STRENGTH.get(f.kind, 0.5),
                evidence=f.note,
            ))
    return out


def derived_expressions(scan: PairScan) -> list[PairFinding]:
    """The findings that name a quantity the table does not store — the subtraction behind
    a flag, the span between two timestamps, the variance between plan and outcome.

    This is what intake needs. Six consecutive runs of one question had to invent
    `"Days for shipping (real)" - "Days for shipment (scheduled)"` from a prompt paragraph;
    it is a measured fact about the table, and a fact belongs in the schema, not in a rule
    the model is asked to remember.
    """
    ranked = sorted(
        (f for f in (scan.findings if scan else []) if f.expression),
        key=lambda f: (_STRENGTH.get(f.kind, 0.0), f.support), reverse=True,
    )
    return ranked
