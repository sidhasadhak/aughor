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
