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

One tier is different in kind. A stacked bar with NO printed labels holds values that
are not text anywhere in the file, so they cannot be read — but the bars are drawn as
rectangles with exact coordinates and the value axis gives a scale, so they can be
MEASURED. Those tables say so, and their figures are rounded to the resolution a point
of height actually carries. Checked against the deck's own printed headlines across
seven cities, the worst disagreement was 3.8% — and those headlines are themselves
rounded to the nearest thousand, so most of that is their rounding, not the ruler's.

A horizontal bar chart is the same problem transposed and is read the same way. There
the value sits at the end of its bar, sharing a ROW with the label rather than a
column, so nothing lines up in x at all: everything since the previous figure names the
next one. Its rows are evenly pitched too, and a gap in that pitch means a row was not
read — which is refused, because a ranking with a row missing from the middle reads as
complete and is not.

Anything else is left alone. A stacked bar chart with no printed labels holds values
that are not text anywhere in the file, and a multi-series chart has values this cannot
attribute to a series without inventing the legend — so both return nothing rather than
a plausible guess. That is the same rule the suppression filter follows, applied one
step earlier: a correct number against the wrong label is worse than a missing one.
"""
from __future__ import annotations

import logging
import math
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
class Series:
    """One named column of values, aligned to a chart's categories."""

    name: str
    values: list[str]


@dataclass(frozen=True)
class Chart:
    """One reconstructed chart, with the page it was proved on.

    More than one series, because two of the shapes here need it: a donut with an inner
    and an outer ring is two readings of the same eight sectors, and putting them in
    one table is what lets a person — or an agent — compare them at all.
    """

    page: int
    title: str
    categories: list[str]
    series: list[Series]
    #: True when the figures were MEASURED off the drawing rather than read from it —
    #: the chart printed no labels, so its heights were scaled against its own axis.
    #: Said out loud in the table, because the two are not equally certain.
    measured: bool = False

    @property
    def values(self) -> list[str]:
        """The first series, for the single-series shapes that only ever have one."""
        return self.series[0].values if self.series else []

    def as_markdown(self) -> str:
        """A table, because a table is the one shape that carries attribution.

        Its header names the column, which is exactly what the chart's geometry was
        doing and what the linear conversion destroyed. It is also why this survives
        the numeric-run filter untouched — a table row is never a run.
        """
        heads = " | ".join(_cell(s.name or "Value") for s in self.series)
        rule = "|---" * (len(self.series) + 1) + "|"
        rows = "\n".join(
            "| " + " | ".join(_cell(v) for v in [category]
                              + [s.values[i] for s in self.series]) + " |"
            for i, category in enumerate(self.categories))
        note = ("\n\nMeasured from the bar heights against this chart's own axis — "
                "these values are not printed on it." if self.measured else "")
        return (f"#### {self.title or 'Chart'} — page {self.page}{note}\n\n"
                f"| Category | {heads} |\n{rule}\n{rows}\n")


def _cell(text: str) -> str:
    """One table cell, with anything that would break the row escaped.

    A pipe inside a label is not hypothetical: this deck writes its streets as
    "Munich | Kaufingerstraße", which unescaped turns a two-column row into four and
    makes the table unparseable — the one outcome worse than not recovering it, since a
    table is the shape everything downstream trusts.
    """
    return text.replace("|", "\\|").strip()


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


def _longest_regular_run(values: list[float]) -> tuple[int, int] | None:
    """The longest evenly-spaced RUN in a sorted sequence, as (start, end) indices.

    Regular spacing is what distinguishes a laid-out axis — of ticks, or of the rows of
    a ranked bar chart — from figures that merely happen to share a coordinate. A run
    rather than the whole sequence, because one intruder must not disqualify an axis.
    """
    best = None
    for start in range(len(values) - _MIN_TICKS + 1):
        step = values[start + 1] - values[start]
        if step <= 0:
            continue
        end = start + 1
        while (end + 1 < len(values)
               and abs((values[end + 1] - values[end]) - step) <= step * _MAX_PITCH_VARIATION):
            end += 1
        if end - start + 1 < _MIN_TICKS:
            continue
        if best is None or (end - start) > (best[1] - best[0]):
            best = (start, end)
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
    run = _longest_regular_run(tops)
    return None if run is None else (tops[run[0]], tops[run[1]])


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

            title = _title_for(words, band, left, right)
            found.append(Chart(page=page_number, title=title,
                               categories=[t for t, _ in labels],
                               series=[Series(title, values)]))
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
                    words = page.extract_words()
                    charts.extend(_charts_on_page(words, number))
                    charts.extend(_ranked_charts_on_page(words, number))
                    charts.extend(_stacked_charts_on_page(words, number))
                    charts.extend(_donut_charts_on_page(words, number))
                    charts.extend(_measured_stacks_on_page(page, words, number))
                except Exception:
                    logger.debug("chart reconstruction skipped page %d", number,
                                 exc_info=True)
    except Exception:
        logger.debug("chart reconstruction could not read the document", exc_info=True)
        return []
    # READ beats MEASURED. Where a chart's values are printed, the reading is exact and
    # the measurement is an approximation of the same thing; offering both would put two
    # answers to one question in the index, one of them needlessly less certain.
    read = {(c.page, tuple(c.categories)) for c in charts if not c.measured}
    return [c for c in charts
            if not c.measured or (c.page, tuple(c.categories)) not in read]


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


# ── Horizontal bars: a ranked list, where the label shares the ROW ────────────

#: A row of a ranked chart carries one pair per chart. Three is room for three charts
#: side by side; a row yielding more is an axis ("0 Mio. 1 Mio. 2 Mio. …"), not data.
_MAX_PAIRS_PER_ROW = 3

#: Labels of a horizontal bar chart are RIGHT-aligned, because the bars all start at
#: the axis and the labels sit against it — a ragged gap before the bars is not a thing
#: any bar chart does. So their right edges form a column a few points wide, and that
#: is a far tighter key than their left edges: it separates two charts side by side AND
#: drops the title and axis rows that share the region but not the alignment.
_LABEL_COLUMN_WIDTH = 25.0

#: Words of one label sit a few points apart. A gap this wide is a different chart's
#: content sharing the row, not a longer name.
_LABEL_WORD_GAP = 30.0


def _rows(words: list[dict]) -> list[list[dict]]:
    """Words grouped into visual lines by PROXIMITY, never into fixed buckets.

    The same trap as the tick columns: two words on one baseline can differ by a
    fraction of a point, and `int(top / tolerance)` cuts them apart whenever that
    fraction straddles a boundary. Here the cost was a row split in half — its label in
    one piece and its figure in the other, so the figure looked orphaned and the whole
    row was dropped. On a footfall page that quietly removed four of twenty-five
    ranked streets.
    """
    out: list[list[dict]] = []
    for word in sorted(words, key=lambda w: w["top"]):
        if out and word["top"] - out[-1][0]["top"] <= _ROW_TOLERANCE:
            out[-1].append(word)
        else:
            out.append([word])
    return out


def _row_pairs(row: list[dict]) -> list[tuple[str, tuple[float, float], dict]] | None:
    """(label, label x0, value) for one row — or None if a figure in it has no name.

    A horizontal bar's value sits at the END of its bar, so unlike a column chart it
    shares a ROW with what it measures and nothing lines up in x at all. Everything
    since the previous figure is this figure's name.

    None, not [], when a figure has no words before it: that is a second series (a
    2025 bar under a 2026 one), and taking the first while dropping the second would
    produce a table that looks complete and is half a chart.
    """
    pairs: list[tuple[str, float, dict]] = []
    pending: list[dict] = []
    for i, word in enumerate(row):
        if not _VALUE.match(word["text"]):
            pending.append(word)
            continue
        if pending:
            # Only the LAST contiguous group of words is this figure's name. Everything
            # since the previous figure is not: on a prime-rent page the left chart's
            # street list runs across the row and would otherwise be read as the label
            # of the right chart's first city, attaching "320 €/sqm" to a street that
            # does not have it.
            group = _last_contiguous(pending)
            pairs.append((" ".join(w["text"] for w in group),
                          (group[0]["x0"], group[-1]["x1"]), word))
            pending = []
        elif not pairs and any(not _VALUE.match(w["text"]) for w in row[i + 1:]):
            continue          # a rank badge sitting in front of its label
        else:
            return None
    # An axis repeats its UNIT under every tick — "0 Mio. 5 Mio. 10 Mio." pairs up
    # perfectly and means nothing. Data does not name every row the same thing.
    if len(pairs) > 1 and len({label for label, _, _ in pairs}) == 1:
        return None
    return pairs


def _ranked_charts_on_page(words: list[dict], page_number: int) -> list[Chart]:
    found: list[tuple[str, tuple[float, float], dict, float]] = []
    # Figures nothing in their row names. Kept, not discarded: a chart standing over one
    # is a chart with a series this cannot read, and the row it sits in is not the only
    # thing it invalidates.
    orphans: list[dict] = []
    for row in _rows(words):
        ordered = sorted(row, key=lambda w: w["x0"])
        pairs = _row_pairs(ordered)
        if pairs is None:
            orphans.extend(w for w in ordered if _VALUE.match(w["text"]))
            continue
        if not 1 <= len(pairs) <= _MAX_PAIRS_PER_ROW:
            continue
        top = min(w["top"] for w in row)
        found.extend((label, x0, value, top) for label, x0, value in pairs)

    charts: list[Chart] = []
    for cluster in _by_gap(sorted(found, key=lambda p: p[1][1]), lambda p: p[1][1],
                           _LABEL_COLUMN_WIDTH):
        entries = sorted(cluster, key=lambda p: p[3])
        if len(entries) < _MIN_CATEGORIES:
            continue
        # A ranked chart's rows are evenly pitched. A gap means a row was not read, and
        # a ranking with a row missing out of the middle is worse than no ranking: it
        # reads as complete and it is not. Refused rather than quietly shortened.
        steps = [b[3] - a[3] for a, b in zip(entries, entries[1:])]
        if steps and max(steps) > statistics.median(steps) * 1.6:
            continue
        left = min(e[1][0] for e in entries)
        right = max(e[2]["x1"] for e in entries)
        band = (entries[0][3], entries[-1][3])
        # A nameless figure standing inside this chart is a second series it cannot
        # attribute. Half a chart that reads as a whole one is the thing to avoid.
        if any(left <= _centre(w) <= right and band[0] - _ROW_TOLERANCE <= w["top"]
               <= band[1] + _ROW_TOLERANCE for w in orphans):
            continue
        title = _nearest_line_above(words, band[0], left, right)
        charts.append(Chart(page=page_number, title=title,
                            categories=[e[0] for e in entries],
                            series=[Series(title, [e[2]["text"] for e in entries])]))
    return charts


def _nearest_line_above(words: list[dict], top: float,
                        left: float, right: float) -> str:
    """The line of prose immediately above a ranked chart, over the chart itself.

    Different from the rule a column chart uses. There the nearest line above is the
    LEGEND and the title sits higher, so the leftmost line wins; here the labels ARE
    the left edge, so anything further left belongs to something else on the page —
    measured on a footfall page, a map panel's "WEST" was closer to the left than the
    chart's own title.
    """
    above = [w for w in words if w["top"] < top - 1
             and left - 20 <= _centre(w) <= right + 20]
    lines: dict[int, list[dict]] = {}
    for word in above:
        lines.setdefault(int(word["top"] / _ROW_TOLERANCE), []).append(word)
    named = [ln for ln in lines.values()
             if sum(1 for w in ln if _VALUE.match(w["text"])) * 2 < len(ln)]
    if not named:
        return ""
    line = max(named, key=lambda ln: min(w["top"] for w in ln))
    return " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"])).strip()


def _last_contiguous(words: list[dict]) -> list[dict]:
    """The final run of words with no wide gap in it.

    Measured edge to edge — `x0` to `x0` includes the word's own width, so on
    "Munich | Kaufingerstraße" a 29-point word made its own 31-point step and split
    the city off its street.
    """
    start = 0
    for i in range(1, len(words)):
        if words[i]["x0"] - words[i - 1]["x1"] > _LABEL_WORD_GAP:
            start = i
    return words[start:]


def _by_gap(items: list, key, gutter: float) -> list[list]:
    """Split a sorted sequence wherever consecutive keys jump by more than `gutter`."""
    out: list[list] = []
    for item in items:
        if out and key(item) - key(out[-1][-1]) <= gutter:
            out[-1].append(item)
        else:
            out.append([item])
    return out


# ── A 100% stacked column, and a donut ────────────────────────────────────────

_PERCENT = re.compile(r"^(\d{1,3})%$")

#: A ring, or a stack, must account for everything. Rounding to whole percents lets a
#: set of eight land a few points either side of 100.
_WHOLE = (95.0, 105.0)

#: How far a stacked label may sit from the position its own cumulative band predicts.
#: Measured on a retail deck the worst was 0.3pt, so this is slack, not a search.
_STACK_TOLERANCE = 4.0

#: Words of one legend entry ("101-200 sqm") sit closer together than two entries do.
_LEGEND_ENTRY_GAP = 8.0

#: How far apart two of a ring's labels may sit and still belong to the same ring. A
#: two-ring chart spreads its labels over the whole band, so this is wide — and it can
#: afford to be: on the deck the nearest thing that is NOT the ring, the slide's own
#: headline, sits 226 points away.
_DONUT_REACH = 110.0


def _percent(word: dict) -> float | None:
    m = _PERCENT.match(word["text"])
    return float(m.group(1)) if m else None


def _columns(words: list[dict], width: float) -> list[list[dict]]:
    """Words grouped into vertical columns by the proximity of their centres."""
    out: list[list[dict]] = []
    for word in sorted(words, key=_centre):
        if out and _centre(word) - _centre(out[-1][-1]) <= width:
            out[-1].append(word)
        else:
            out.append([word])
    return out


def _axis_scale(column: list[dict]) -> tuple[float, float] | None:
    """(top of 0%, points per percent) from a column of percentage ticks.

    The ticks must be evenly spaced in BOTH value and position — that is what makes
    them a scale rather than a set of figures that share an x.
    """
    ticks = sorted(((_percent(w), w["top"]) for w in column if _percent(w) is not None),
                   key=lambda t: t[0])
    if len(ticks) < _MIN_TICKS:
        return None
    # A value axis reads DOWNWARD — 100% at the top, 0% at the bottom — so its steps are
    # negative in `top` and positive in value. `_longest_regular_run` wants an ascending
    # sequence and rejected every axis in the deck until this was checked directly.
    if not (_evenly_spaced([v for v, _ in ticks])
            and _evenly_spaced([t for _, t in ticks])):
        return None
    span = ticks[-1][0] - ticks[0][0]
    if span <= 0:
        return None
    per_percent = (ticks[0][1] - ticks[-1][1]) / span
    return ticks[0][1] + ticks[0][0] * per_percent, per_percent


def _evenly_spaced(values: list[float]) -> bool:
    """Constant step, in either direction."""
    steps = [b - a for a, b in zip(values, values[1:])]
    if not steps or steps[0] == 0:
        return False
    return all(abs(s - steps[0]) <= abs(steps[0]) * _MAX_PITCH_VARIATION for s in steps)


def _legend_row(words: list[dict], above: float, left: float,
                right: float, count: int) -> tuple[list[str], float] | None:
    """The nearest row above a chart that reads as exactly `count` legend entries."""
    # Not clipped to the column's own width: a legend spans the whole chart while the
    # labelled bar may be one column of ten, and narrowing to the bar cut a five-entry
    # legend down to the three that happened to sit above it. The exact-count match is
    # what keeps this honest, not the window.
    candidates = [w for w in words if w["top"] < above - 1
                  and left - 40 <= _centre(w) <= right + 40 and _percent(w) is None]
    for row in sorted(_rows(candidates), key=lambda r: -r[0]["top"]):
        ordered = sorted(row, key=lambda w: w["x0"])
        entries, current = [], [ordered[0]]
        for word in ordered[1:]:
            if word["x0"] - current[-1]["x1"] > _LEGEND_ENTRY_GAP:
                entries.append(current)
                current = [word]
            else:
                current.append(word)
        entries.append(current)
        if len(entries) == count:
            return ([" ".join(w["text"] for w in e) for e in entries],
                    min(w["top"] for w in ordered))
    return None


def _stacked_charts_on_page(words: list[dict], page_number: int) -> list[Chart]:
    """A 100% stacked column whose segments are labelled.

    Refused by the column-chart reader, which allows one value per category: here one
    column carries five. The attribution is not a guess though, it is PROVABLE. The
    segments sum to 100, the value axis gives a scale, and each label sits at the
    midpoint of its own cumulative band — so assuming the stack runs in legend order
    bottom to top predicts every label's position. Measured on a retail deck the worst
    error was 0.3pt; a wrong order would miss by tens of points.
    """
    percents = [w for w in words if _percent(w) is not None]
    columns = _columns(percents, _TICK_COLUMN_WIDTH / 2)
    scales = [s for c in columns if (s := _axis_scale(c)) is not None]
    if not scales:
        return []

    found: list[Chart] = []
    for column in columns:
        stack = sorted(column, key=lambda w: -w["top"])          # bottom of the bar up
        values = [_percent(w) for w in stack]
        if len(stack) < _MIN_TICKS or not _WHOLE[0] <= sum(values) <= _WHOLE[1]:
            continue
        for zero, per_percent in scales:
            cumulative, proved = 0.0, True
            for word, value in zip(stack, values):
                middle = cumulative + value / 2
                proved &= abs((zero - middle * per_percent) - word["top"]) <= _STACK_TOLERANCE
                cumulative += value
            if not proved:
                continue
            left = min(w["x0"] for w in column)
            right = max(w["x1"] for w in column)
            legend = _legend_row(words, min(w["top"] for w in column) - 20,
                                 0.0, max(w["x1"] for w in words), len(stack))
            if legend is None:
                continue
            names, legend_top = legend
            # The column's own category, read from the axis BELOW it — the legend above
            # names the segments, not the bar.
            series = _category_below(words, zero, (left + right) / 2)
            found.append(Chart(
                page=page_number,
                # Above the LEGEND, not above the bar: the legend names the segments
                # and the title names the chart.
                title=_title_for(words, (legend_top, zero), left - 300, right),
                categories=names,
                series=[Series(series, [w["text"] for w in stack])]))
            break
    return found


def _donut_charts_on_page(words: list[dict], page_number: int) -> list[Chart]:
    """A donut, including the two-ring kind, read from where its labels sit.

    A ring has no axis and nothing lines up, so the geometry is polar: each label sits
    at the angular middle of its segment, and a two-ring chart puts the same sector's
    two readings at the same angle and different radii. Pair by angle, and the farther
    of each pair is the outer ring.

    Three things have to agree before any of it is emitted, and on the deck all three
    did: each ring sums to 100, the angular order matches the legend, and the outer
    ring reproduces the slide's own headline — "Fashion: 27%, Food & Beverage: 19%,
    Leisure: 9%" against a reading of 27, 19, 9.
    """
    # Every percentage, clustered by position — no filtering by column first. Three of
    # this ring's labels happened to share an x with each other, and excluding shared
    # columns to keep the value axis out took them with it. Position alone is enough:
    # the axis and the stacked bar sit 270 points away and fall into their own blobs.
    percents = [w for w in words if _percent(w) is not None]
    for loose in _blobs(percents, _DONUT_REACH):
        if len(loose) >= 8 and not len(loose) % 2:
            chart = _donut_from(words, loose, page_number)
            if chart is not None:
                return [chart]
    return []


def _blobs(words: list[dict], reach: float) -> list[list[dict]]:
    """Words grouped into 2-D clusters — anything within `reach` of the group joins it.

    A ring's labels sit around its centre and nothing else on the page does. Taking
    every scattered percentage instead swept in the slide's own headline, whose
    "27%, 19%, 9%" paired off against the ring and left both totals wrong.
    """
    remaining = list(words)
    out: list[list[dict]] = []
    while remaining:
        group = [remaining.pop()]
        moved = True
        while moved:
            moved = False
            for word in list(remaining):
                if any(math.dist((_centre(word), word["top"]), (_centre(g), g["top"]))
                       <= reach for g in group):
                    group.append(word)
                    remaining.remove(word)
                    moved = True
        out.append(group)
    return sorted(out, key=len, reverse=True)


def _donut_from(words: list[dict], loose: list[dict], page_number: int) -> Chart | None:
    x = statistics.fmean([_centre(w) for w in loose])
    y = statistics.fmean([(w["top"] + w["bottom"]) / 2 for w in loose])
    polar = []
    for word in loose:
        dx, dy = _centre(word) - x, (word["top"] + word["bottom"]) / 2 - y
        polar.append((math.hypot(dx, dy),
                      (math.degrees(math.atan2(dx, -dy)) + 360) % 360, word))

    pairs, used = [], set()
    for i, one in enumerate(polar):
        if i in used:
            continue
        rest = [(j, p) for j, p in enumerate(polar) if j != i and j not in used]
        if not rest:
            return None
        j, other = min(rest, key=lambda jp: abs(jp[1][1] - one[1]))
        used |= {i, j}
        inner, outer = sorted([one, other], key=lambda p: p[0])
        pairs.append((min(one[1], other[1]), inner[2], outer[2]))
    pairs.sort()

    rings = {"outer": [p[2] for p in pairs], "inner": [p[1] for p in pairs]}
    if not all(_WHOLE[0] <= sum(_percent(w) for w in ring) <= _WHOLE[1]
               for ring in rings.values()):
        return None

    names = _legend_column(words, len(pairs))
    if names is None:
        return None
    labels = _ring_labels(words)
    return Chart(page=page_number, title=_donut_title(words, loose),
                 categories=names,
                 series=[Series(labels[key], [w["text"] for w in ring])
                         for key, ring in rings.items()])


def _category_below(words: list[dict], axis_top: float, centre: float) -> str:
    """The category label under a column — "H1 2026" beneath the bar it names."""
    below = [w for w in words if w["top"] > axis_top - _ROW_TOLERANCE
             and abs(_centre(w) - centre) < 18]
    if not below:
        return ""
    line = min(below, key=lambda w: w["top"])["top"]
    return " ".join(w["text"] for w in
                    sorted((w for w in below if abs(w["top"] - line) <= _ROW_TOLERANCE),
                           key=lambda w: w["x0"]))


def _legend_column(words: list[dict], count: int) -> list[str] | None:
    """A legend written down the side: `count` rows sharing a left edge, evenly pitched."""
    # Grouped by PROXIMITY of the shared edge, not into fixed buckets — the third time
    # in this module that a fixed grid split something that lines up, here two legend
    # entries whose right edges landed a fraction either side of a boundary. And on
    # BOTH edges, because a legend down the side of a chart may be aligned either way.
    ordered_rows = [sorted(r, key=lambda w: w["x0"])
                    for r in _rows([w for w in words if _percent(w) is None])]
    groups: list[list[list[dict]]] = []
    for edge in (lambda r: r[0]["x0"], lambda r: r[-1]["x1"]):
        for cluster in _by_gap(sorted(ordered_rows, key=edge), edge, 4.0):
            groups.append(cluster)
    for rows in groups:
        if len(rows) != count:
            continue
        tops = sorted(r[0]["top"] for r in rows)
        if _longest_regular_run(tops) != (0, len(tops) - 1):
            continue
        return [" ".join(w["text"] for w in r)
                for r in sorted(rows, key=lambda r: r[0]["top"])]
    return None


def _ring_labels(words: list[dict]) -> dict[str, str]:
    """What the chart calls its rings, taken from the chart. It usually says."""
    text = " ".join(w["text"] for w in sorted(words, key=lambda w: (w["top"], w["x0"])))
    out = {"outer": "Outer ring", "inner": "Inner ring"}
    for key in out:
        # Bounded on purpose: the joined page text runs straight on into the chart's
        # own figures, and an unbounded capture swallowed the entire slide.
        found = re.search(rf"{key}\s+circle\s*=\s*((?:\S+ ){{0,3}}\S+)",
                          text, re.IGNORECASE)
        if found:
            # The joined page text runs straight on into the other ring's caption and
            # then into the chart's own figures; an unbounded capture swallowed the
            # slide. Trimmed at whichever comes first.
            label = re.split(r"\s+(?:outer|inner)\s+circle|\s+\d{1,3}%",
                             found.group(1), flags=re.IGNORECASE)[0].strip()
            if label:
                out[key] = label
    return out


def _donut_title(words: list[dict], loose: list[dict]) -> str:
    left = min(w["x0"] for w in loose)
    right = max(w["x1"] for w in loose)
    return _title_for(words, (min(w["top"] for w in loose), 0.0), left, right)


# ── Bars with no labels at all: measured, not read ────────────────────────────

#: A tick like "60.000" or "1,200" — thousands separators, either convention. Not a
#: decimal: an axis counts in whole units, and the evenly-spaced check settles the rest.
_AXIS_NUMBER = re.compile(r"^\d{1,3}(?:[.,]\d{3})*$")

#: A drawn segment thinner than this is a rounding artefact of the renderer, not data.
_MIN_SEGMENT_POINTS = 0.6

#: How far a stack's foot may sit from the axis zero, and each segment from the next.
_SEAM_TOLERANCE = 1.5


def _axis_number(text: str) -> float | None:
    if not _AXIS_NUMBER.match(text):
        return None
    return float(text.replace(".", "").replace(",", ""))


def _value_axes(words: list[dict]) -> list[tuple[float, float, float, float]]:
    """Every numeric value axis on the page: (zero centre, units per point, top, x).

    All of them, not the best one. A page carries two charts side by side and their
    axes are the same height, so choosing globally picks whichever sorts first — on the
    deck that measured take-up in square metres against the lettings chart's 0-120
    scale, off by a factor of five hundred. Each axis is paired with the chart standing
    beside it instead.

    Fitted on the label CENTRES, not their tops: a tick label is centred on its
    gridline, and using the top biases every reading by half a line of type.
    """
    found = []
    for column in _columns([w for w in words if _axis_number(w["text"]) is not None],
                           _TICK_COLUMN_WIDTH / 2):
        ticks = sorted(((_axis_number(w["text"]), (w["top"] + w["bottom"]) / 2)
                        for w in column), key=lambda t: t[0])
        if len(ticks) < _MIN_TICKS or len({v for v, _ in ticks}) != len(ticks):
            continue
        if not (_evenly_spaced([v for v, _ in ticks])
                and _evenly_spaced([c for _, c in ticks])):
            continue
        span = ticks[-1][0] - ticks[0][0]
        points = ticks[0][1] - ticks[-1][1]
        if span <= 0 or points <= 0:
            continue
        zero = ticks[0][1] + ticks[0][0] * (points / span)
        found.append((zero, span / points, ticks[-1][1],
                      statistics.fmean([_centre(w) for w in column])))
    return found


def _fill(shape: dict) -> str:
    return str(shape.get("non_stroking_color"))


def _swatch_names(rects: list[dict], words: list[dict]) -> tuple[dict[str, str], set]:
    """Fill colour → series name, taken from the legend.

    A legend entry is a small filled patch with its name immediately to the right. That
    patch is the ONLY thing tying a drawn segment to a series — the segments themselves
    carry no text at all — so a colour with no swatch is a series that cannot be named,
    and its chart is refused rather than labelled by position.
    """
    names: dict[str, str] = {}
    swatches: set = set()
    for rect in rects:
        if rect["height"] > 12 or rect["width"] > 40:
            continue
        middle = (rect["top"] + rect["bottom"]) / 2
        to_right = [w for w in words if w["x0"] >= rect["x1"] - 1
                    and w["x0"] - rect["x1"] < 12
                    and w["top"] <= middle <= w["bottom"] + _ROW_TOLERANCE]
        if len(to_right) == 1:
            names.setdefault(_fill(rect), to_right[0]["text"])
            # Returned so the caller can exclude them. A swatch is a small filled patch
            # in exactly the colour of the series it names, and one of them sat close
            # enough to a column to be read as a fifth segment of that bar.
            swatches.add((round(rect["x0"], 2), round(rect["top"], 2)))
    return names, swatches


def _measured_stacks_on_page(page, words: list[dict], page_number: int) -> list[Chart]:
    """Stacked bars whose values were never printed, measured against their own axis.

    Every other reader here REFUSES this chart, and rightly: nothing on it says what
    the segments are worth. But the bars are drawn as rectangles with exact
    coordinates, and the value axis gives a scale, so the heights can be measured — a
    different kind of answer, and it is labelled as one. These tables say MEASURED, and
    the figures are rounded to the resolution a point of height actually carries
    (about 250 sqm on this deck) rather than to the spurious precision of the division.

    What has to hold before a single number is emitted:

      * the segments of a bar are CONTIGUOUS — each one's foot is the next one's head,
        which is what makes it a stack rather than four rectangles in a column;
      * the bottom segment stands ON the axis zero, so the bar is measured from the
        baseline the axis defines and not from wherever it happens to start;
      * every fill has a legend swatch, because a colour nobody named is a series this
        cannot attribute;
      * each stack sits under a category label.
    """
    axes = _value_axes(words)
    names, swatches = _swatch_names(page.rects, words)
    if not axes or not names:
        return []

    found: list[Chart] = []
    for row in _rows(words):
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
            baseline = min(w["top"] for w in cluster)

            # The axis that belongs to THIS chart: below the labels' baseline, to their
            # left, and the nearest such. The legend row sits above every axis and is
            # dropped here — it is four evenly spaced labels and nothing else.
            candidates = [a for a in axes if a[0] < baseline and a[3] < centres[0]]
            if not candidates:
                continue
            zero, per_point, axis_top, _ = max(candidates, key=lambda a: a[3])

            bars = [r for r in page.rects
                    if r["height"] >= _MIN_SEGMENT_POINTS and r["width"] < pitch
                    and axis_top - 20 <= r["top"]
                    and r["bottom"] <= zero + _SEAM_TOLERANCE
                    and (round(r["x0"], 2), round(r["top"], 2)) not in swatches
                    and _fill(r) in names]
            # Every segment of one bar shares that bar's centre exactly, so the window
            # is tight. A wide one reached into the neighbouring column and returned a
            # stack with five segments and a quarter appearing twice.
            columns = [sorted((r for r in bars
                               if abs((r["x0"] + r["x1"]) / 2 - centre)
                               <= max(3.0, pitch * 0.12)),
                              key=lambda r: r["bottom"], reverse=True)
                       for centre in centres]
            if not all(columns) or not all(_is_stack(s, zero) for s in columns):
                continue

            # A column may legitimately be short: the deck's last bar is a HALF year, so
            # it has no Q3 or Q4 rectangle at all. That is absence, not zero, and it is
            # written as absence — claiming a zero would invent a quarter's worth of
            # nothing where the chart simply stops.
            order = list(dict.fromkeys(_fill(r) for stack in columns for r in stack))
            if any(len({_fill(r) for r in stack}) != len(stack) for stack in columns):
                continue
            step = 10 ** round(math.log10(per_point)) if per_point > 0 else 1
            series = [
                Series(names[fill],
                       [next((f"{round(r['height'] * per_point / step) * step:,.0f}"
                              for r in stack if _fill(r) == fill), "—")
                        for stack in columns])
                for fill in order]
            found.append(Chart(page=page_number,
                               title=_title_for(words, (axis_top, zero),
                                                centres[0] - 60, centres[-1]),
                               categories=[t for t, _ in labels],
                               series=series, measured=True))
    return found


def _is_stack(stack: list[dict], zero: float) -> bool:
    """Contiguous segments standing on the axis zero. See `_measured_stacks_on_page`."""
    if abs(stack[0]["bottom"] - zero) > _SEAM_TOLERANCE:
        return False
    return all(abs(lower["top"] - upper["bottom"]) <= _SEAM_TOLERANCE
               for lower, upper in zip(stack, stack[1:]))
