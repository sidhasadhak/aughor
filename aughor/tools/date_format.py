"""Arc NV-1 — the notation a text column writes its dates in, inferred from every distinct value, or withheld.

A VARCHAR column holding ``'20260131'`` or ``'31/01/2026'`` is the text-to-SQL trap the trust checks catch at the
comparison and nobody caught at the parse: a model that compares it as text, or casts it with the wrong format,
returns rows for a question about the wrong month and says nothing. NVIDIA's Auto-Ontology infers a notation per
text date column (`docs/NVIDIA_AUTO_ONTOLOGY_STUDY_2026-11-04.md` §5.3) and its method transfers whole:

* at most :data:`MAX_DISTINCT` distinct values are read, so the probe stays bounded on a column of daily dates
  spanning years; the verdict says how many it rests on, and the profiler adds how many the column holds;
* the candidates are tried in **specificity order** (:data:`CANDIDATES`): a winner must parse EVERY value, with
  the year in [1900, 2099], so a notation is a fact about the whole column, never about its first rows;
* **DD/MM against MM/DD is refused**: when both parse every value — every day ≤ 12 — the column is reported
  ``ambiguous`` with the two notations named. Saying so beats the coin flip a model would take as a fact, and under
  this repo's rule a withheld fact is said, never implied: the property carries the note, and the ENTITY MODEL
  block prints it.

Pure: values in, a verdict out. No store, no model, no connection — the profiler owns the read
(`aughor/tools/profiler.py`), the builder copies the verdict onto the property (`EntityProperty.format`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

#: Distinct values read per column — the profiler's own bound for a column's value sample. The probe reads
#: ``DISTINCT … LIMIT MAX_DISTINCT`` and every value read must parse; a column holding more (daily dates over
#: six years are ~2,200) is judged on what was read, and the note says so. Found live on Superstore, 2026-11-04:
#: `Order Date` holds 1,237 distinct values, and a 200-value cap read as eligibility had kept the probe silent on the
#: very column whose cast had just failed in the API log ("invalid date field format: 11/8/2016").
MAX_DISTINCT = 2000

#: Years outside this range mean the pattern matched digits that are not a date (`%Y` parses `'0001'`).
YEAR_MIN, YEAR_MAX = 1900, 2099

#: (strptime pattern, the notation a reader sees). Most specific first: a timestamp before its date, a
#: four-digit year before a two-digit one, ISO before the slashed national forms. The two national pairs that
#: share a shape (day-first / month-first) sit next to each other so the ambiguity check below can name both.
CANDIDATES: tuple[tuple[str, str], ...] = (
    ("%Y-%m-%dT%H:%M:%S.%f", "YYYY-MM-DDTHH:MM:SS.ffffff"),
    ("%Y-%m-%dT%H:%M:%S", "YYYY-MM-DDTHH:MM:SS"),
    ("%Y-%m-%d %H:%M:%S.%f", "YYYY-MM-DD HH:MM:SS.ffffff"),
    ("%Y-%m-%d %H:%M:%S", "YYYY-MM-DD HH:MM:SS"),
    ("%Y-%m-%d %H:%M", "YYYY-MM-DD HH:MM"),
    ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%Y/%m/%d", "YYYY/MM/DD"),
    ("%Y.%m.%d", "YYYY.MM.DD"),
    ("%Y%m%d%H%M%S", "YYYYMMDDHHMMSS"),
    ("%Y%m%d", "YYYYMMDD"),
    ("%d/%m/%Y %H:%M:%S", "DD/MM/YYYY HH:MM:SS"),
    ("%m/%d/%Y %H:%M:%S", "MM/DD/YYYY HH:MM:SS"),
    ("%d/%m/%Y %H:%M", "DD/MM/YYYY HH:MM"),
    ("%m/%d/%Y %H:%M", "MM/DD/YYYY HH:MM"),
    ("%d/%m/%Y", "DD/MM/YYYY"),
    ("%m/%d/%Y", "MM/DD/YYYY"),
    ("%d-%m-%Y", "DD-MM-YYYY"),
    ("%m-%d-%Y", "MM-DD-YYYY"),
    ("%d.%m.%Y", "DD.MM.YYYY"),
    ("%d/%m/%y", "DD/MM/YY"),
    ("%m/%d/%y", "MM/DD/YY"),
    ("%d %b %Y", "DD Mon YYYY"),
    ("%b %d, %Y", "Mon DD, YYYY"),
    ("%d %B %Y", "DD Month YYYY"),
    ("%B %d, %Y", "Month DD, YYYY"),
    ("%Y-%m", "YYYY-MM"),
    ("%b %Y", "Mon YYYY"),
)

#: The day-first / month-first pairs: when both members parse every value, the column is ambiguous.
_AMBIGUOUS_PAIRS: tuple[tuple[str, str], ...] = (
    ("%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"),
    ("%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"),
    ("%d/%m/%Y", "%m/%d/%Y"),
    ("%d-%m-%Y", "%m-%d-%Y"),
    ("%d/%m/%y", "%m/%d/%y"),
)

_NOTATION = dict(CANDIDATES)

#: A cheap gate before any strptime: a date-like string holds digits and at most the separators the candidates
#: use (and month names). It keeps a free-text column from costing 27 × 200 parse attempts for nothing.
_LOOKS_DATELIKE = re.compile(r"^[0-9A-Za-z ,./:\-T]{4,32}$")
_HAS_DIGITS = re.compile(r"\d{2}")


@dataclass(frozen=True)
class DateFormat:
    """What the probe found for one text column."""

    notation: str = ""         # "YYYYMMDD" — "" when nothing parsed every value, or when ambiguous
    strptime: str = ""         # the Python pattern behind the notation, for a caller that parses
    ambiguous: bool = False    # DD/MM and MM/DD both parse every value
    note: str = ""             # the sentence a reader (and the ENTITY MODEL block) gets
    n_values: int = 0          # distinct non-null values the verdict rests on

    @property
    def found(self) -> bool:
        """A notation was found, or an ambiguity was — either is a fact worth stating on the property."""
        return bool(self.notation) or self.ambiguous


def _parses_all(values: list[str], pattern: str) -> bool:
    for v in values:
        try:
            dt = datetime.strptime(v, pattern)
        except (ValueError, TypeError):
            return False
        if not (YEAR_MIN <= dt.year <= YEAR_MAX):
            return False
    return True


def infer_date_format(values: Iterable[object]) -> Optional[DateFormat]:
    """The notation every value in ``values`` is written in, an ambiguity verdict, or None when the column is not
    a text date column at all (no value, more than :data:`MAX_DISTINCT`, or nothing parses every value).

    None means "not a date column": the property stays as it was. An ambiguity returns a :class:`DateFormat` with
    an empty notation and ``ambiguous=True`` — a fact to state, not a guess to take. Values past
    :data:`MAX_DISTINCT` are not read: the verdict rests on the first ``MAX_DISTINCT`` and ``n_values`` says so."""
    seen: list[str] = []
    for raw in values:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s or s.upper() in ("NULL", "NONE", "NAN", "NAT"):
            continue
        seen.append(s)
        if len(seen) >= MAX_DISTINCT:
            break
    if not seen:
        return None
    if not all(_LOOKS_DATELIKE.match(v) and _HAS_DIGITS.search(v) for v in seen):
        return None

    winners = [pat for pat, _ in CANDIDATES if _parses_all(seen, pat)]
    if not winners:
        return None

    for day_first, month_first in _AMBIGUOUS_PAIRS:
        if day_first in winners and month_first in winners:
            return DateFormat(
                notation="", strptime="", ambiguous=True, n_values=len(seen),
                note=(f"ambiguous: every one of {len(seen)} distinct values parses as both "
                      f"{_NOTATION[day_first]} and {_NOTATION[month_first]} (no day above 12) — the notation is "
                      "not stated; a person can declare it"),
            )

    pat = winners[0]
    return DateFormat(
        notation=_NOTATION[pat], strptime=pat, ambiguous=False, n_values=len(seen),
        note=f"text dates written {_NOTATION[pat]}; every one of {len(seen)} distinct values parses",
    )


def looks_like_date_column(name: str, dtype: str, sample: Iterable[object] = ()) -> bool:
    """Whether a text column is worth the probe: its name says date or time, or every sampled value looks like one.
    ``dtype`` must be a text type — a typed DATE or TIMESTAMP column needs no notation."""
    from aughor.tools.profiler import is_date_named, is_text_type  # the profiler owns the patterns
    if not is_text_type(dtype):
        return False
    if is_date_named(name):
        return True
    vals = [str(v).strip() for v in sample if v is not None and str(v).strip()]
    if len(vals) < 2:
        return False
    return all(_LOOKS_DATELIKE.match(v) and _HAS_DIGITS.search(v) for v in vals) and any(
        _parses_all(vals[:5], pat) for pat, _ in CANDIDATES)
