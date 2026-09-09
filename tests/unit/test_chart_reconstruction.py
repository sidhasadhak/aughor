"""Reading a chart back out of a PDF.

Every fixture here is DRAWN, not asserted into existence: the test lays text on a page
at coordinates and then asks the reconstructor to find the chart in it. That is the
only way this can fail honestly — an expectation written beside a hand-built list of
words would pass while the geometry it claims to read was never examined.

Verified against the real thing before these were written. On an 83-page retail market
deck the reconstructor recovers seven charts, and pages 5, 12 and 47 were checked
figure by figure against the rendered pages: Berlin 98/104/70/65/73/79/66/61/65/37,
Duesseldorf 59/59/27/39/27/20/39/41/27/20, Stuttgart 29/35/39/26/12/11/11/12/24/20.
"""
import io
import math
import re

import pytest

pytest.importorskip("pdfplumber")
pytest.importorskip("reportlab")

from aughor.knowledge.charts import as_markdown, reconstruct  # noqa: E402

#: One page, one chart, laid out the way a business deck lays one out.
_TITLE_TOP = 60.0
_BAND = (100.0, 260.0)          # where the value axis runs
_AXIS_TOP = 290.0               # the category labels' baseline
_CATEGORIES = ["2017", "2018", "2019", "2020", "H1 2026"]
_COLUMN_X = [120.0, 200.0, 280.0, 360.0, 440.0]


def _page(draw) -> bytes:
    """A 600x400 PDF whose origin has been flipped, so tests read in `top` terms."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(600, 400))
    pdf.setFont("Helvetica", 8)

    def at(x: float, top: float, text: str, centred: bool = True) -> None:
        y = 400 - top
        (pdf.drawCentredString if centred else pdf.drawRightString)(x, y, text)

    draw(at)
    pdf.save()
    return buffer.getvalue()


def _chart(at, values, *, title="Openings per year", ticks=True, categories=None):
    at(120, _TITLE_TOP, title)
    if ticks:
        # The value axis. Evenly spaced, and to the LEFT of every column.
        for i, top in enumerate(range(int(_BAND[0]), int(_BAND[1]) + 1, 40)):
            at(90, float(top), str(80 - i * 20), centred=False)
    for x, category in zip(_COLUMN_X, categories or _CATEGORIES):
        at(x, _AXIS_TOP, category)
    for x, value in zip(_COLUMN_X, values):
        if value is not None:
            at(x, 200.0, str(value))


def test_a_labelled_column_chart_comes_back_as_a_table():
    """The whole point. `104` and `2018` are two text objects that mean something
    together only because they share an x coordinate — which Markdown cannot carry."""
    charts = reconstruct(_page(lambda at: _chart(at, [98, 104, 70, 65, 37])))

    assert len(charts) == 1
    chart = charts[0]
    assert chart.categories == _CATEGORIES
    assert chart.values == ["98", "104", "70", "65", "37"]
    assert chart.page == 1
    assert chart.title == "Openings per year"


def test_a_two_word_category_is_one_column():
    """"H1 2026" is two words. Read as two categories the pitch stops being regular
    and the axis is rejected, so the last column of every chart in the deck would be
    lost to a space."""
    chart = reconstruct(_page(lambda at: _chart(at, [98, 104, 70, 65, 37])))[0]

    assert chart.categories[-1] == "H1 2026"
    assert chart.values[-1] == "37"


def test_a_chart_with_no_printed_values_is_refused():
    """A stacked bar chart carries values that are not text ANYWHERE in the file. There
    is nothing to read, and inventing something from the bar geometry is a different
    tier of problem — so this returns nothing rather than a plausible guess."""
    assert reconstruct(_page(lambda at: _chart(at, [None] * 5))) == []


def test_a_headline_elsewhere_on_the_page_is_not_read_as_a_value():
    """The guard the whole thing rests on, and a bug this actually had.

    Without a plot band the search for data labels runs to the top of the page. On page
    5 of the real deck the take-up headline's `24,000` sits 15pt from the centre of the
    2019 column — close enough to be adopted as its value.
    """
    def draw(at):
        _chart(at, [98, 104, None, 65, 37])
        at(_COLUMN_X[2], 20.0, "24,000")      # a headline, dead above the 2019 column

    # The column has no value of its own, and the headline must not supply one.
    assert reconstruct(_page(draw)) == []


def test_a_column_with_two_candidates_is_refused():
    """Two figures over one category is either a multi-series chart this cannot
    attribute without inventing the legend, or an alignment coincidence. Both get the
    same answer, for the same reason: a correct number against the wrong label is worse
    than a missing one."""
    def draw(at):
        _chart(at, [98, 104, 70, 65, 37])
        at(_COLUMN_X[1], 160.0, "51")          # a second series, unnamed

    assert reconstruct(_page(draw)) == []


def test_a_value_axis_survives_a_stray_figure_in_its_column():
    """One intruder must not disqualify an axis.

    On page 12 of the deck the headline's `5` sits in the tick column's x. Demanding
    that the WHOLE column be evenly spaced refused a chart standing beside eight
    perfectly pitched ticks, so the longest regular RUN is what counts.
    """
    def draw(at):
        _chart(at, [98, 104, 70, 65, 37])
        at(90, 20.0, "5", centred=False)       # shares the axis's x, far above it

    assert reconstruct(_page(draw))[0].values == ["98", "104", "70", "65", "37"]


def test_a_column_of_strays_cannot_stretch_the_plot_band():
    """The other half of the value-axis guard, and the page-12 bug exactly.

    A figure that merely shares the axis's x extends the column. Take the column's full
    extent and the band reaches the top of the page, so anything up there becomes a
    candidate value — on the real page that was the headline. Only the longest EVENLY
    SPACED run is the axis; a stray sits outside it.

    Here the fourth column has no value of its own. If the band stretched to the stray,
    the decoy above the plot would supply one and the chart would come back carrying a
    figure that is not its data.
    """
    def draw(at):
        _chart(at, [98, 104, 70, None, 37])
        at(90, 20.0, "5", centred=False)        # shares the axis x, far above it
        at(_COLUMN_X[3], 50.0, "777")           # only reachable if the band stretches

    charts = reconstruct(_page(draw))
    assert charts == [], "a figure from outside the plot was adopted as a data label"


def test_two_charts_side_by_side_do_not_cross():
    """Both axes land on one baseline — measured on the deck, a single row held
    twenty-one words that were two ten-year axes."""
    def draw(at):
        _chart(at, [1, 2, 3, 4, 5])
        for i, top in enumerate(range(int(_BAND[0]), int(_BAND[1]) + 1, 40)):
            at(1090, float(top), str(80 - i * 20), centred=False)
        at(1120, _TITLE_TOP, "Second chart")
        for i, x in enumerate([1120.0, 1200.0, 1280.0, 1360.0, 1440.0]):
            at(x, _AXIS_TOP, _CATEGORIES[i])
            at(x, 200.0, str(90 + i))

    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(1600, 400))
    pdf.setFont("Helvetica", 8)

    def at(x, top, text, centred=True):
        (pdf.drawCentredString if centred else pdf.drawRightString)(x, 400 - top, text)

    draw(at)
    pdf.save()

    charts = reconstruct(buffer.getvalue())
    assert len(charts) == 2
    assert sorted(c.values for c in charts) == [
        ["1", "2", "3", "4", "5"], ["90", "91", "92", "93", "94"]]


def test_a_recovered_chart_survives_the_suppression_filter():
    """The two halves of this problem, joined.

    A reconstructed chart is emitted as a TABLE, and a table row is never a numeric run
    — its header names the column. Emitted any other way, the very figures just
    recovered would be held straight back out of the index as unattributed.
    """
    from aughor.knowledge.documents import numeric_run_lines

    markdown = as_markdown(reconstruct(_page(lambda at: _chart(at, [98, 104, 70, 65, 37]))))

    assert "| 2018 | 104 |" in markdown
    assert numeric_run_lines(markdown) == []


def test_a_document_with_no_charts_is_left_alone_and_never_raises():
    """This runs beside a conversion that has ALREADY succeeded. A chart that cannot be
    read is not an import failure."""
    assert reconstruct(_page(lambda at: at(100, 100, "Just some prose."))) == []
    assert reconstruct(b"not a pdf at all") == []
    assert reconstruct(b"") == []
    assert as_markdown([]) == ""


# ── Horizontal bars: the value shares a ROW with its label ────────────────────

_RANKED_TOP = 120.0
_RANKED_PITCH = 20.0


def _ranked(at, entries, *, x_label=200.0, x_value=300.0, title="Pedestrians per year"):
    """A ranked bar chart: labels right-aligned to the axis, values at the bar ends."""
    at(x_label, _RANKED_TOP - 30, title)
    for i, (label, value) in enumerate(entries):
        top = _RANKED_TOP + i * _RANKED_PITCH
        at(x_label, top, label, centred=False)          # right-aligned, as on an axis
        at(x_value + i * 7, top, str(value))


_STREETS = [("Munich | Kaufingerstrasse", "12,64"), ("Frankfurt | Zeil", "10,58"),
            ("Hanover | Georgstrasse", "10,05"), ("Cologne | Schildergasse", "9,68"),
            ("Stuttgart | Koenigstrasse", "9,21")]


def test_a_ranked_list_is_read_from_its_rows():
    """The transpose of a column chart. A horizontal bar's value sits at the END of its
    bar, so it shares a row with its label and nothing lines up in x at all."""
    chart = reconstruct(_page(lambda at: _ranked(at, _STREETS)))[0]

    assert chart.categories[0] == "Munich | Kaufingerstrasse"
    assert chart.values == ["12,64", "10,58", "10,05", "9,68", "9,21"]
    assert chart.title == "Pedestrians per year"


def test_a_pipe_inside_a_label_cannot_break_the_table():
    """"Munich | Kaufingerstrasse" unescaped turns a two-column row into four. A table
    that does not parse is worse than one not recovered — a table is the shape
    everything downstream trusts."""
    markdown = as_markdown(reconstruct(_page(lambda at: _ranked(at, _STREETS))))

    for row in [ln for ln in markdown.splitlines()
                if ln.startswith("|") and not ln.startswith("|---")]:
        assert len(re.findall(r"(?<!\\)\|", row)) == 3, row


def test_a_second_series_refuses_rather_than_returning_half_a_chart():
    """A 2025 bar under a 2026 one leaves a figure with no words before it. Taking the
    first and dropping the second yields a table that looks complete and is half."""
    def draw(at):
        _ranked(at, _STREETS)
        at(305, _RANKED_TOP + 8, "11,90")        # a second bar, inside the chart

    assert reconstruct(_page(draw)) == []


def test_an_axis_that_repeats_its_unit_is_not_data():
    """"0 Mio. 5 Mio. 10 Mio." pairs up perfectly and means nothing."""
    def draw(at):
        _ranked(at, _STREETS)
        for i, v in enumerate(["0", "5", "10", "15"]):
            at(240 + i * 60, _RANKED_TOP - 12, v)
            at(255 + i * 60, _RANKED_TOP - 12, "Mio.")

    assert reconstruct(_page(draw))[0].values == ["12,64", "10,58", "10,05", "9,68", "9,21"]


def test_a_label_is_the_last_contiguous_run_of_words():
    """The prime-rent bug. Another chart's list of streets runs across the same row; read
    as one label it attaches "320 EUR/sqm" to a street that does not have it."""
    def draw(at):
        _ranked(at, [("Munich", "320"), ("Frankfurt", "295"), ("Duesseldorf", "285"),
                     ("Hamburg", "235"), ("Cologne", "230")], x_label=600, x_value=700)
        for i in range(5):                        # a different chart, same rows
            at(120, _RANKED_TOP + i * _RANKED_PITCH, "Tauentzienstrasse", centred=False)

    chart = reconstruct(_page(draw))[0]
    assert chart.categories == ["Munich", "Frankfurt", "Duesseldorf", "Hamburg", "Cologne"]


def test_a_gap_in_the_rows_refuses_the_ranking():
    """A ranking with a row missing out of the middle reads as complete and is not."""
    def draw(at):
        at(200, _RANKED_TOP - 30, "Pedestrians per year")
        for i, (label, value) in enumerate(_STREETS):
            top = _RANKED_TOP + i * _RANKED_PITCH + (60 if i >= 3 else 0)   # a hole
            at(200, top, label, centred=False)
            at(300 + i * 7, top, str(value))

    assert reconstruct(_page(draw)) == []


# ── A 100% stacked column, and a donut ────────────────────────────────────────

_SIZES = ["<=100 sqm", "101-200 sqm", "201-500 sqm", "501-1,000 sqm", ">1,000 sqm"]


def _stacked(at, values, *, x=300.0, zero=400.0, per_percent=2.0):
    """A 100% stacked bar: a value axis, one labelled column, a legend, a category."""
    for tick in range(0, 101, 20):
        at(90, zero - tick * per_percent, f"{tick}%", centred=False)
    for i, name in enumerate(_SIZES):
        at(140 + i * 90, 170.0, name)                    # the legend, entry per swatch
    cumulative = 0.0
    for value in values:
        at(x, zero - (cumulative + value / 2) * per_percent, f"{value}%")
        cumulative += value
    at(x, zero + 12, "H1 2026")                          # the category under the bar


def test_a_stacked_column_is_attributed_by_its_own_geometry():
    """Refused by the column reader, which allows one value per category — here one
    column carries five. The attribution is provable: the segments sum to 100 and each
    label sits at the midpoint of its own cumulative band, so legend order bottom to top
    predicts every position. A wrong order would miss by tens of points."""
    chart = reconstruct(_page(lambda at: _stacked(at, [24, 27, 22, 5, 22])))[0]

    assert chart.categories == _SIZES
    assert chart.values == ["24%", "27%", "22%", "5%", "22%"]
    assert chart.series[0].name == "H1 2026"


def test_a_stack_that_does_not_account_for_everything_is_refused():
    """The first of the two proofs. Segments that do not sum to 100 are not a 100%
    stacked bar, and whatever they are cannot be read this way."""
    assert reconstruct(_page(lambda at: _stacked(at, [24, 27, 22, 5, 8]))) == []


def test_a_stack_whose_labels_sit_wrong_is_refused():
    """The second proof, and the one that pins the ORDER. The values still sum to 100;
    only their positions disagree with the bands they claim."""
    def draw(at):
        _stacked(at, [24, 27, 22, 5, 22])
        at(300, 300.0, "22%")            # a sixth label, off its band

    assert reconstruct(_page(draw)) == []


def _donut(at, outer, inner, names, *, cx=200.0, cy=300.0):
    for i, (out_v, in_v) in enumerate(zip(outer, inner)):
        angle = math.radians(22.5 + i * 45)
        for radius, value in ((100.0, out_v), (55.0, in_v)):
            at(cx + radius * math.sin(angle), cy - radius * math.cos(angle), f"{value}%")
    at(cx, cy - 150, "outer circle = 2022-H1 2026 inner circle = 2017-2021")
    for i, name in enumerate(names):
        at(360, 250.0 + i * 20, name, centred=False)


_SECTORS = ["Fashion", "Beverage", "Leisure", "Food", "Furnishings", "Leather",
            "Jewellery", "Others"]


def test_a_two_ring_donut_comes_back_as_two_columns():
    """A ring has no axis and nothing lines up, so the geometry is polar: the same
    sector's two readings share an angle and differ in radius, and the farther is the
    outer ring. One table, because the comparison is the point."""
    chart = reconstruct(_page(lambda at: _donut(
        at, [27, 19, 9, 9, 8, 6, 6, 16], [23, 26, 7, 9, 9, 7, 3, 16], _SECTORS)))[0]

    assert chart.categories == _SECTORS
    assert [s.name for s in chart.series] == ["2022-H1 2026", "2017-2021"]
    assert chart.series[0].values[:2] == ["27%", "19%"]
    assert chart.series[1].values[:2] == ["23%", "26%"]


def test_a_ring_that_does_not_sum_to_a_whole_is_refused():
    """The check that makes the radius rule safe. Split the rings the wrong way and the
    totals stop being 100, which is exactly what a mis-paired chart looks like."""
    assert reconstruct(_page(lambda at: _donut(
        at, [27, 19, 9, 9, 8, 6, 6, 16], [23, 26, 7, 9, 9, 7, 3, 40], _SECTORS))) == []


# ── Bars with no labels: measured, not read ───────────────────────────────────

_M_ZERO = 350.0          # where the axis zero sits, in `top` coordinates
_M_FULL = 150.0          # points from zero to the top tick
_M_MAX = 100_000         # what the top tick says
_PER_POINT = _M_MAX / _M_FULL          # 666.7 units per point
_M_STEP = 1000           # what values round to at that resolution
_QUARTERS = [("Q1", (0.1, 0.1, 0.1)), ("Q2", (0.3, 0.8, 0.8)), ("Q3", (0.3, 0.6, 0.7))]

#: A tick label's glyph box sits a shade above its baseline; the reader calibrates on
#: label CENTRES, so the fixture draws baselines two points below the gridline it means.
_BASELINE_NUDGE = 2.0


def _measured_page(stacks, *, feet=None, swatches=True, gap=None) -> bytes:
    """A stacked bar chart with a value axis, a legend, and no data labels at all."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(600, 400))
    pdf.setFont("Helvetica", 8)

    def text(x, top, s):
        pdf.setFillColorRGB(0, 0, 0)
        pdf.drawCentredString(x, 400 - top, s)

    text(200, _M_ZERO - _M_FULL - 40, "Retail take-up in city locations")
    for i in range(4):                                   # the value axis
        value = _M_MAX * i // 3
        top = _M_ZERO - _M_FULL * i / 3
        text(90, top + _BASELINE_NUDGE, f"{value:,}".replace(",", "."))
    for i, (name, colour) in enumerate(_QUARTERS):       # the legend
        if swatches:
            pdf.setFillColorRGB(*colour)
            pdf.rect(120 + i * 60, 400 - _M_ZERO + _M_FULL + 22, 14, 5, stroke=0, fill=1)
        text(147 + i * 60, _M_ZERO - _M_FULL - 20, name)

    for column, (label, heights) in enumerate(stacks):
        x = 140.0 + column * 70
        text(x, _M_ZERO + 12, label)                     # the category
        foot = (feet or {}).get(label, _M_ZERO)
        for i, ((_, colour), height) in enumerate(zip(_QUARTERS, heights)):
            if height <= 0:
                continue
            if i and label == (gap or {}).get("label"):
                foot -= gap["points"]          # a hole between two segments
            pdf.setFillColorRGB(*colour)
            pdf.rect(x - 8, 400 - foot, 16, height, stroke=0, fill=1)
            foot -= height
    pdf.save()
    return buffer.getvalue()


_STACKS = [("2023", (30.0, 30.0, 60.0)), ("2024", (15.0, 45.0, 30.0)),
           ("2025", (60.0, 15.0, 15.0)), ("2026", (30.0, 45.0, 0.0))]


def _close(got: str, want: float) -> bool:
    return abs(float(got.replace(",", "")) - want) <= _M_STEP


def test_a_bar_with_no_labels_is_measured_against_its_own_axis():
    """The tier every other reader refuses. Nothing on this chart says what its
    segments are worth — but they are drawn as rectangles with exact coordinates, and
    the axis gives a scale, so the heights can be measured."""
    chart = reconstruct(_measured_page(_STACKS))[0]

    assert chart.measured is True
    assert chart.categories == ["2023", "2024", "2025", "2026"]
    assert [s.name for s in chart.series] == ["Q1", "Q2", "Q3"]
    assert _close(chart.series[0].values[0], 30.0 * _PER_POINT)
    assert _close(chart.series[2].values[0], 60.0 * _PER_POINT)
    assert _close(chart.series[0].values[2], 60.0 * _PER_POINT)


def test_a_measured_table_says_that_it_was_measured():
    """A reading and a measurement are not equally certain, and the table has to carry
    the difference — otherwise the least reliable numbers in the corpus look exactly
    like the most reliable ones."""
    markdown = as_markdown(reconstruct(_measured_page(_STACKS)))

    assert "Measured from the bar heights" in markdown
    assert "not printed on it" in markdown


def test_a_missing_segment_is_absence_not_zero():
    """The deck's last bar is a HALF year: it has no Q3 rectangle at all. Writing a zero
    would invent a quarter's worth of nothing where the chart simply stops."""
    chart = reconstruct(_measured_page(_STACKS))[0]

    assert chart.series[2].values[3] == "—"


def test_a_stack_that_does_not_stand_on_the_axis_is_refused():
    """Measuring a height means nothing without knowing where it starts. A bar floating
    off its baseline is not a bar this can read."""
    floating = reconstruct(_measured_page(_STACKS, feet={"2024": _M_ZERO - 40}))

    assert floating == []


def test_a_colour_with_no_legend_swatch_is_refused():
    """The swatch is the ONLY thing tying a drawn segment to a series — the segments
    carry no text whatsoever. A colour nobody named cannot be attributed by position."""
    assert reconstruct(_measured_page(_STACKS, swatches=False)) == []


def test_segments_with_a_hole_between_them_are_not_a_stack():
    """Contiguity is what makes four rectangles in a column a STACK rather than four
    rectangles in a column. Without it any set of shapes that happens to line up gets
    measured, and their heights mean nothing together."""
    holed = reconstruct(_measured_page(_STACKS, gap={"label": "2024", "points": 12.0}))

    assert holed == []
