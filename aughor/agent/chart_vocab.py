"""A5 — the ONE chart-type vocabulary the model is offered.

Before this module there were three disagreeing vocabularies: the quick path
offered 13/14 types (`prompts.py`), the deep path's pydantic Literals allowed 8
(`prompts_investigate.py`), and the renderer could draw 22 (`web/components/
charts/chartTypeInference.ts`) — so the deep path could never ask for a heatmap
the renderer has always been able to draw. This registry is the single source:
prompt fragments derive from it, the deep Literals are drift-tested against it,
and a frontend-parity test asserts every offered type is renderable.

Exhibit-grammar semantics throughout: `combo` is NEVER offered — the renderer's
deterministic scoreDualAxis gate stays the only door to a dual axis. `matrix`
(internal alias of heatmap) and `table` (a view toggle, not a chart) are also
not the model's to pick.
"""
from __future__ import annotations

#: The classic 13 the quick path already offered under the exhibit grammar.
_CORE_TYPES: tuple[str, ...] = (
    "auto", "bar", "bar_horizontal", "bar_vertical", "line", "multi_line",
    "area", "stacked_bar", "scatter", "pie", "pareto", "treemap", "heatmap",
)

#: The renderable types the model was never offered (A5 opens them), each with the
#: data shape that makes it sane — offered-but-annotated, so a strong model can
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
}

#: Everything the model may return, quick and deep alike (exhibit grammar).
MODEL_CHART_TYPES: tuple[str, ...] = _CORE_TYPES + tuple(EXOTIC_SHAPES)

#: Engine-only hints the RENDERER also accepts but the model must not pick:
#: combo arrives only via the deterministic dual-axis gate; matrix is heatmap's
#: internal alias. (`table`/`auto` are handled by the surfaces themselves.)
ENGINE_ONLY_HINTS: tuple[str, ...] = ("combo", "matrix")


def chart_vocab_line() -> str:
    """The prompt fragment offering the full vocabulary — the successor of the
    hand-maintained `_CHART_VOCAB_GRAMMAR` string, derived so it cannot drift."""
    core = ", ".join(f"'{t}'" for t in _CORE_TYPES)
    exotic = " ".join(f"'{t}' ({shape})." for t, shape in EXOTIC_SHAPES.items())
    return (
        f"Also return chart_type — one of: {core}. "
        f"Additional specialised types, ONLY when the result matches the stated shape: {exotic} "
    )
