"""A5/CA-4 — the ONE chart vocabulary the model is offered.

Before this module there were three disagreeing vocabularies: the quick path
offered 13/14 types (`prompts.py`), the deep path's pydantic Literals allowed 8
(`prompts_investigate.py`), and the renderer could draw 22 (`web/components/
charts/chartTypeInference.ts`). A5 made this registry the single source; CA-4
changes WHAT it offers: the model no longer picks among two dozen chart shapes —
it names the data's JOB (what the reader must do with the result), and code maps
the job to the form. The specialised shapes stay offered-but-annotated (a sankey
or a gantt is a data-shape fact the model can see), but the everyday shape
choice is no longer the model's to make.

Exhibit-grammar semantics throughout: `combo` and `pareto` are NEVER offered —
dual-axis charts are banned (§6), and nothing auto-upgrades into one. `matrix`
(internal alias of heatmap) and `table` (a view toggle, not a chart) are also
not the model's to pick. Legacy shape tokens (`bar`, `line`, `pie`, …) remain
ACCEPTED at the seams — persisted reports and saved display configs keep
rendering — they are simply no longer in the model's vocabulary.
"""
from __future__ import annotations

#: CA-4 form-by-job: the jobs the model may name, each with what the reader must
#: do — the job picks the chart, code picks the encoding.
CHART_JOBS: dict[str, str] = {
    "magnitude": "compare sizes across categories — renders as one ranked bar",
    "trend": "follow change over time — renders as a line at the grain that shows the event",
    "identity": "tell a few distinct series apart — renders stacked/multi-line; >6 folds to 'Other'",
    "change": "see the signed delta per item (period-over-period, contribution) — renders a diverging delta bar, never grouped before/after bars",
    "share": "see parts of a whole — renders a stacked composition bar",
    "distribution": "see the spread of raw values — renders a histogram",
    "relation": "see how two measures move together — renders a scatter",
}

#: The renderable specialised types (offered-but-annotated) — a strong model can
#: reach for a histogram without a weak one spraying gantts at revenue tables.
EXOTIC_SHAPES: dict[str, str] = {
    "histogram": "1 numeric column of RAW values — its distribution",
    "boxplot": "1 categorical + 1 numeric — spread and outliers per group",
    "counter": "a single number (1 row, 1 numeric) worth showing big",
    "funnel": "ordered stages + 1 numeric that only shrinks stage to stage",
    "waterfall": "ordered signed contributions bridging a start total to an end total",
    "sankey": "source column, target column, flow value — where quantities went",
    "small_multiples": "1 date + 1 category (>10 values) + 1 numeric — one mini-line per series",
    "line_forecast": "1 date + 1 numeric where a projection beyond the data is the point",
    "gantt": "task/name column + start date + end date",
    "choropleth": "region/country/state NAMES + 1 numeric — a shaded map",
    "point_map": "latitude + longitude columns (+ optional numeric) — dots on a map",
    "treemap": "1 additive measure across MANY parts (7–24) — proportional tiles",
    "heatmap": "2 dimensions × 1 measure — a colour grid",
}

#: Everything the model may return, quick and deep alike.
MODEL_CHART_TYPES: tuple[str, ...] = ("auto",) + tuple(CHART_JOBS) + tuple(EXOTIC_SHAPES)

#: Renderer hints the model must not pick. combo/pareto: dual-axis is banned
#: (§6) — nothing offers one and nothing auto-upgrades into one; matrix is
#: heatmap's internal alias. (`table`/`auto` are handled by the surfaces.)
ENGINE_ONLY_HINTS: tuple[str, ...] = ("combo", "matrix", "pareto")

#: Legacy shape tokens still ACCEPTED (never offered): persisted findings and
#: saved viz configs carry them, and the renderer keeps drawing them.
LEGACY_SHAPE_HINTS: tuple[str, ...] = (
    "bar", "bar_horizontal", "bar_vertical", "line", "multi_line", "area",
    "stacked_bar", "scatter", "pie",
)

#: Job → the engine hint its default form renders as (the web mirror lives in
#: chartTypeInference.ts HINT_TO_TYPE; the parity test walks both).
JOB_TO_FORM: dict[str, str] = {
    "magnitude": "bar_horizontal",
    "trend": "line",
    "identity": "stacked_bar",
    "change": "delta_bar",
    "share": "stacked_bar",
    "distribution": "histogram",
    "relation": "scatter",
}


def resolve_chart_type(value: str | None) -> str:
    """A job token becomes its form's engine hint; anything else (legacy shape,
    exotic, auto, none) passes through untouched."""
    v = (value or "auto").strip().lower()
    return JOB_TO_FORM.get(v, v)


def chart_vocab_line() -> str:
    """The prompt fragment offering the vocabulary — jobs first, specialised
    shapes only when the result matches the stated shape. Derived, cannot drift."""
    jobs = " ".join(f"'{j}' ({what})." for j, what in CHART_JOBS.items())
    exotic = " ".join(f"'{t}' ({shape})." for t, shape in EXOTIC_SHAPES.items())
    return (
        f"Also return chart_type — name the data's JOB and the renderer picks the form: {jobs} "
        f"Specialised types, ONLY when the result matches the stated shape: {exotic} "
        f"Or 'auto' to defer to the renderer's shape inference. "
    )
