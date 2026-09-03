"""A deck that cannot draw a chart must not also lose its title.

The `svg_to_png` ledger line said "PPTX chart export degrades", which sounded like a
cosmetic loss. Reading the path showed it was not:

* `document._chart_or_table` emits a chart block AND a table block, and blanks the
  TABLE's caption whenever a chart exists — a reasonable call, because the chart is meant
  to carry the title, and in the PDF it does (`pdf.py` embeds the SVG, no raster needed).
* `slides.py` renders a chart slide only `if b.png`. `export.echarts.svg_to_png` returns
  None without a reportlab renderPM backend, and this repo has no rasterizer it can rely
  on — `routers/charts.py` says outright that raster is the caller's edge to convert at.
* So on any install without that backend, the PPTX dropped the chart **and** the table
  arrived with an empty caption. A customer received an untitled table.

The repair belongs in the renderer that drops the chart, not in `document.py`: the block
layer is format-agnostic and correct to blank the caption, because the PDF really does
draw the title.

Deliberately NOT tested for here: a "chart unavailable" slide. The numbers arrive on the
next slide, so a line about our own plumbing would tell a customer nothing they cannot see.
What was lost is the title, so the title is what these tests demand back.
"""
from __future__ import annotations

from aughor.export.document import Block


class _Recorder:
    """Records what the deck would render, so the assertions read as slides.

    The real `_Deck` builds a `Presentation`; asserting on python-pptx shapes would test
    that library's XML rather than our dispatch. `add` is the thing that decides, so `add`
    is what runs — against recording versions of the two slide builders.
    """

    def __init__(self):
        from aughor.export.slides import _Deck
        self.deck = _Deck()
        self.images: list[tuple[bytes, str]] = []
        self.tables: list[tuple[list, list, str]] = []
        self.deck.image_slide = lambda png, caption: self.images.append((png, caption))
        self.deck.table_slide = (
            lambda cols, rows, caption: self.tables.append((cols, rows, caption)))

    def add(self, *blocks: Block):
        for b in blocks:
            self.deck.add(b)
        return self


def _chart(caption: str, *, png: bytes | None) -> Block:
    return Block("chart", svg=b"<svg/>", png=png, caption=caption)


def _table(caption: str = "") -> Block:
    return Block("table", columns=["day", "orders"], rows=[["Mon", 3]], caption=caption)


# ── the defect ───────────────────────────────────────────────────────────────────

def test_a_chart_with_NO_raster_hands_its_title_to_the_table():
    """The whole finding. Without this the customer's slide is a table with no title."""
    r = _Recorder().add(_chart("Orders by day", png=None), _table())
    assert r.images == [], "a chart with no png must not reach a slide"
    assert r.tables == [(["day", "orders"], [["Mon", 3]], "Orders by day")]


def test_a_chart_that_DID_render_leaves_the_table_untitled_as_before():
    """Unchanged behaviour on an install that can rasterise: the chart slide carries the
    title, so repeating it on the table below would be duplication."""
    r = _Recorder().add(_chart("Orders by day", png=b"PNG"), _table())
    assert r.images == [(b"PNG", "Orders by day")]
    assert r.tables == [(["day", "orders"], [["Mon", 3]], "")]


# ── it must not leak ─────────────────────────────────────────────────────────────

def test_the_caption_is_SPENT_and_does_not_reach_a_later_unrelated_table():
    """A held caption that were not cleared would retitle the next table in the deck with
    the name of a chart that has nothing to do with it — a worse failure than the one this
    fixes, because it would be confidently wrong rather than merely blank."""
    r = _Recorder().add(_chart("Orders by day", png=None), _table(), _table())
    assert [c for _, _, c in r.tables] == ["Orders by day", ""]


def test_a_table_with_its_OWN_caption_keeps_it():
    """The table's own title always wins. A chart's leftover name must never displace a
    caption that `document.py` deliberately set."""
    r = _Recorder().add(_chart("Orders by day", png=None), _table("Revenue by region"))
    assert [c for _, _, c in r.tables] == ["Revenue by region"]


def test_a_rendered_chart_CLEARS_a_caption_held_from_an_earlier_dropped_one():
    """Two exhibits, one drawable and one not. Without the clear, the second chart's table
    would inherit the first chart's title."""
    r = _Recorder().add(
        _chart("First exhibit", png=None),
        _chart("Second exhibit", png=b"PNG"),
        _table(),
    )
    assert r.images == [(b"PNG", "Second exhibit")]
    assert [c for _, _, c in r.tables] == [""]


def test_an_untitled_dropped_chart_does_not_blank_a_caption_already_held():
    """`b.caption or self._orphaned_caption` — a second chart with no title of its own
    must not wipe the title still waiting to be spent."""
    r = _Recorder().add(
        _chart("Orders by day", png=None),
        _chart("", png=None),
        _table(),
    )
    assert [c for _, _, c in r.tables] == ["Orders by day"]
