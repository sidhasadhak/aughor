"""Charts in a PDF, read back as tables.

Markdown is the pivot of the documents plane, and a chart is the one thing it cannot
carry. A chart's data labels are positioned graphics: `104` and `2018` are two text
objects that mean something together only because they share an x coordinate. Convert
to Markdown — a linear stream — and the coordinate is gone, so what arrives downstream
is a headless row of correct figures attached to nothing.

That loss is what `documents.is_numeric_run` spends its time cleaning up. Measured on
an 83-page retail market deck: 156 lines held out of the index, nearly all of them
chart debris, while 32 of those pages carried a chart whose every value was present in
the file as exact text. The numbers were never missing. The geometry was.

So this module reads the same PDF a second time, keeping the coordinates, and hands
back tables. anydoc remains the reader for prose — this is not a competing document
parser and it never returns a document, only the charts it can prove.

Why not OCR
-----------
OCR answers a different question: it recovers text that exists only as pixels. Here the
text already exists exactly, and rasterising it to guess it back would trade certainty
for a confidence score. In this one deck both `.` and `,` appear as thousands separator
AND as decimal point — `700.000` sqm beside `12,64` Mio. — so a misread mark at 6pt
silently moves a value by three orders of magnitude. The text layer settles which glyph
it is for free. A local OCR backend is still worth having for genuinely scanned pages;
it is a different tier of problem and does not belong here.

What is reconstructed, and what is refused
------------------------------------------
Only a chart that can be proved from its own geometry:

  * a CATEGORY AXIS — four or more labels in one row, evenly pitched;
  * a VALUE AXIS — a column of numeric ticks whose vertical span IS the plot area,
    which is what keeps a headline figure elsewhere on the page from being read as a
    data label;
  * exactly ONE value per category, each sitting within a fraction of the pitch of its
    category's centre.

Anything else is left alone. A stacked bar chart with no printed labels holds values
that are not text anywhere in the file, and a multi-series chart has values this cannot
attribute to a series without inventing the legend — so both return nothing rather than
a plausible guess. That is the same rule the suppression filter follows, applied one
step earlier: a correct number against the wrong label is worse than a missing one.
"""
from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: A category label: a year, a half, a quarter, or a short word. Deliberately narrow —
#: a wide pattern turns any evenly-spaced row of text into an axis, and the cost of a
#: wrong axis is a whole table of misattributed figures.
_CATEGORY = re.compile(r"^(?:FY)?\d{4}$|^[HQ][1-4]$|^[A-Z][a-z]{2}$", re.UNICODE)

#: A value label. Both separator conventions, because this deck uses both.
_VALUE = re.compile(r"^[+\-−]?\d[\d.,]*%?$")

#: Rows are found by grouping on `top`. Two labels on one baseline can differ by a
#: fraction of a point after transformation, and a chart's axis row is typeset flush.
_ROW_TOLERANCE = 2.5

#: How far a value's centre may sit from its category's, as a fraction of the pitch.
#: Measured on the deck the labels land within 0.1pt — they share the bar's centre —
#: so this is slack for typesetting, not a search radius.
_ALIGN_FRACTION = 0.35

#: An axis is only an axis if its spacing is regular. Bar charts are laid out on a
#: constant pitch; a row of prose that happens to be numbers is not.
_MAX_PITCH_VARIATION = 0.12

_MIN_CATEGORIES = 4
_MIN_TICKS = 3

#: Ticks share an x centre. Right-aligned tick labels of different widths ("120" and
#: "20") still centre within a few points of each other.
_TICK_COLUMN_WIDTH = 12.0

#: How far above the plot to look for a name. Wide enough to clear a legend row and
#: reach the title above it; narrow enough not to reach the page's own headline.
_TITLE_WINDOW = 80.0


@dataclass(frozen=True)
class Chart:
    """One reconstructed series, with the page it was proved on."""

    page: int
    title: str
    categories: list[str]
    values: list[str]

    def as_markdown(self) -> str:
        """A table, because a table is the one shape that carries attribution.

        Its header names the column, which is exactly what the chart's geometry was
        doing and what the linear conversion destroyed. It is also why this survives
        the numeric-run filter untouched — a table row is never a run.
        """
        header = self.title or "Value"
        rows = "\n".join(f"| {c} | {v} |" for c, v in zip(self.categories, self.values))
        return (f"#### {self.title or 'Chart'} — page {self.page}\n\n"
                f"| Category | {header} |\n| --- | --- |\n{rows}\n")


def available() -> bool:
    """Is the positioned-text reader installed? Mirrors `convert.available()`."""
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


def _centre(word: dict) -> float:
    return (word["x0"] + word["x1"]) / 2


def _clusters(row: list[dict]) -> list[list[dict]]:
    """Split one row of words wherever a gap dwarfs the typical one.

    Two charts side by side put both their axes on the same baseline — measured on
    this deck, one row held twenty-one words that were two ten-year axes. Splitting on
    the outsized gap between them is what keeps their values from being crossed.
    """
    if len(row) < 2:
        return [row]
    gaps = [row[i + 1]["x0"] - row[i]["x1"] for i in range(len(row) - 1)]
    typical = statistics.median(gaps)
    out, current = [], [row[0]]
    for word, gap in zip(row[1:], gaps):
        if gap > max(typical * 3, 20.0):
            out.append(current)
            current = [word]
        else:
            current.append(word)
    out.append(current)
    return out


def _merge_labels(cluster: list[dict]) -> list[tuple[str, float]]:
    """Words into category labels, and each label's centre.

    "H1 2026" is two words. Left as two it is two categories, the pitch stops being
    regular and the axis is rejected — so the last column of every chart in the deck
    would be lost to a space. Words far closer together than the pitch belong to one
    label; joining them also moves the centre onto the bar, where the value is.
    """
    gaps = [cluster[i + 1]["x0"] - cluster[i]["x1"] for i in range(len(cluster) - 1)]
    if not gaps:
        return [(cluster[0]["text"], _centre(cluster[0]))]
    tight = statistics.median(gaps) / 2
    groups, current = [], [cluster[0]]
    for word, gap in zip(cluster[1:], gaps):
        if gap < tight:
            current.append(word)
        else:
            groups.append(current)
            current = [word]
    groups.append(current)
    return [(" ".join(w["text"] for w in g), (g[0]["x0"] + g[-1]["x1"]) / 2)
            for g in groups]


def _pitch(centres: list[float]) -> float | None:
    """The spacing of an axis, or None if it does not have one."""
    if len(centres) < _MIN_CATEGORIES:
        return None
    steps = [b - a for a, b in zip(centres, centres[1:])]
    if any(s <= 0 for s in steps):
        return None
    mean = statistics.fmean(steps)
    if mean <= 0 or max(abs(s - mean) for s in steps) / mean > _MAX_PITCH_VARIATION:
        return None
    return mean


def _plot_band(numbers: list[dict], axis_top: float,
               left: float, right: float) -> tuple[float, float] | None:
    """The vertical extent of the value axis beside this chart.

    This is the guard that makes the rest safe. Without it the search for data labels
    runs to the top of the page, and on page 5 of the deck the take-up headline's
    `24,000` sits 15pt from the centre of the `2019` column — close enough to be read
    as its value. The tick column says where the plot actually is, and a figure outside
    it is some other part of the page.
    """
    ticks = sorted((w for w in numbers if w["top"] < axis_top - 1), key=_centre)
    # Grouped by PROXIMITY, not into fixed buckets. A column of right-aligned ticks
    # centres within a couple of points, which a fixed grid will still cut in half if
    # it straddles a boundary: on page 5 of the deck that split a seven-tick axis into
    # 120/100 and the rest, so the plot band began below the two tallest bars and the
    # chart was refused for having no values.
    columns: list[list[dict]] = []
    for tick in ticks:
        if columns and _centre(tick) - _centre(columns[-1][-1]) <= _TICK_COLUMN_WIDTH:
            columns[-1].append(tick)
        else:
            columns.append([tick])
    best = None
    for column in columns:
        # The axis belongs to THIS chart: beside its columns, not inside them.
        if len(column) < _MIN_TICKS or not all(_centre(t) < left or _centre(t) > right
                                               for t in column):
            continue
        if abs(statistics.fmean([_centre(t) for t in column]) - left) > (right - left):
            continue
        span = _tick_span(sorted(t["top"] for t in column))
        if span is None:
            continue
        if best is None or span[1] - span[0] > best[1] - best[0]:
            best = span
    return best


def _tick_span(tops: list[float]) -> tuple[float, float] | None:
    """The extent of the longest evenly-spaced RUN in a column of figures.

    Even spacing is what makes a value axis an axis, and checking for it is what stops
    a column of unrelated numbers that merely share an x from winning on sheer height:
    on page 12 of the deck such a column reached from the page headline down to the
    axis, so the band swallowed the page and the headline was offered as a data label.

    But a run, not the whole column — one intruder must not disqualify an axis. On that
    same page the headline's `5` sits in the tick column's x, and demanding the whole
    column be regular refused a chart standing beside eight perfectly pitched ticks.
    """
    best = None
    for start in range(len(tops) - _MIN_TICKS + 1):
        step = tops[start + 1] - tops[start]
        if step <= 0:
            continue
        end = start + 1
        while (end + 1 < len(tops)
               and abs((tops[end + 1] - tops[end]) - step) <= step * _MAX_PITCH_VARIATION):
            end += 1
        if end - start + 1 < _MIN_TICKS:
            continue
        span = (tops[start], tops[end])
        if best is None or span[1] - span[0] > best[1] - best[0]:
            best = span
    return best


def _title_for(words: list[dict], band: tuple[float, float],
               left: float, right: float) -> str:
    """The nearest line of prose above the plot that sits over this chart.

    A table needs a header and the chart already has one; taking it beats naming the
    column "Value" and losing what the figures measure.
    """
    above = [w for w in words if band[0] - _TITLE_WINDOW <= w["top"] < band[0]
             and left - 60 <= _centre(w) <= right + 60]
    lines: dict[int, list[dict]] = {}
    for word in above:
        lines.setdefault(int(word["top"] / _ROW_TOLERANCE), []).append(word)
    # A line that is mostly figures is part of the chart, not a name for it.
    named = [sorted(line, key=lambda w: w["x0"]) for line in lines.values()
             if sum(1 for w in line if _VALUE.match(w["text"])) * 2 < len(line)]
    if not named:
        return ""
    # The leftmost line wins. A chart's title is set flush with its left edge while a
    # legend sits over the plot — measured on this deck, taking the NEAREST line above
    # instead picked the legend every time and named the column after the series
    # markers rather than after what the chart measures.
    line = min(named, key=lambda ln: ln[0]["x0"])
    return " ".join(w["text"] for w in line).strip()


def _charts_on_page(words: list[dict], page_number: int) -> list[Chart]:
    rows: dict[int, list[dict]] = {}
    for word in words:
        rows.setdefault(int(word["top"] / _ROW_TOLERANCE), []).append(word)
    numbers = [w for w in words if _VALUE.match(w["text"])]

    found: list[Chart] = []
    for row in rows.values():
        for cluster in _clusters(sorted(row, key=lambda w: w["x0"])):
            if len(cluster) < _MIN_CATEGORIES:
                continue
            if not all(_CATEGORY.match(w["text"]) for w in cluster):
                continue
            labels = _merge_labels(cluster)
            centres = [c for _, c in labels]
            pitch = _pitch(centres)
            if pitch is None:
                continue

            axis_top = min(w["top"] for w in cluster)
            left, right = centres[0], centres[-1]
            band = _plot_band(numbers, axis_top, left, right)
            if band is None:
                continue

            tolerance = pitch * _ALIGN_FRACTION
            values: list[str] = []
            for _, centre in labels:
                hits = [w for w in numbers
                        if band[0] - _ROW_TOLERANCE <= w["top"] < axis_top - 1
                        and abs(_centre(w) - centre) <= tolerance]
                # One value, or nothing. Two candidates means either a multi-series
                # chart this cannot attribute or an alignment coincidence, and both
                # are answered the same way.
                if len(hits) != 1:
                    values = []
                    break
                values.append(hits[0]["text"])
            if not values:
                continue

            found.append(Chart(page=page_number,
                               title=_title_for(words, band, left, right),
                               categories=[t for t, _ in labels],
                               values=values))
    return found


def reconstruct(data: bytes) -> list[Chart]:
    """Every chart in a PDF that can be proved from its own geometry.

    Never raises on a document: a chart that cannot be read is not an import failure,
    and this runs beside a conversion that has already succeeded. Returns [] when the
    reader is absent, the bytes are not a PDF, or nothing could be proved.
    """
    if not available():
        return []
    import io

    import pdfplumber

    charts: list[Chart] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                try:
                    charts.extend(_charts_on_page(page.extract_words(), number))
                except Exception:
                    logger.debug("chart reconstruction skipped page %d", number,
                                 exc_info=True)
    except Exception:
        logger.debug("chart reconstruction could not read the document", exc_info=True)
        return []
    return charts


def as_markdown(charts: list[Chart]) -> str:
    """The recovered charts as one appendable section.

    Appended rather than interleaved: the Markdown arrives from anydoc with no page
    boundaries in it, so there is nowhere truthful to splice a page-5 table. Each
    table names its page instead, which is also what a person needs in order to go
    and check it against the original.
    """
    if not charts:
        return ""
    body = "\n".join(chart.as_markdown() for chart in charts)
    return ("\n\n## Chart data recovered from this document\n\n"
            "Read from the positions of each chart's own labels. Charts whose values "
            "are not printed on them are not included.\n\n" + body)
