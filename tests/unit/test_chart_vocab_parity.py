"""A5 — one chart vocabulary, drift-tested at every seam.

Three vocabularies used to disagree (quick prompt 13/14, deep Literals 8,
renderer 22), so the deep path could never ask for a heatmap the renderer has
always drawn. The registry (`aughor.agent.chart_vocab`) is the single source;
these tests are the CI gate that keeps the seams honest — same spirit as the
api.gen.ts drift check.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from aughor.agent.chart_vocab import (
    CHART_JOBS,
    ENGINE_ONLY_HINTS,
    EXOTIC_SHAPES,
    JOB_TO_FORM,
    MODEL_CHART_TYPES,
    chart_vocab_line,
    resolve_chart_type,
)

_WEB_INFERENCE = (Path(__file__).resolve().parents[2]
                  / "web" / "components" / "charts" / "chartTypeInference.ts")


def _renderer_hints() -> set[str]:
    """The underscore hints the renderer dispatches on — parsed from HINT_TO_TYPE's
    KEYS in the frontend source, so this test reads the artifact that ships."""
    src = _WEB_INFERENCE.read_text()
    m = re.search(r"export const HINT_TO_TYPE[^=]*=\s*\{(.*?)\n\};", src, re.S)
    assert m, "HINT_TO_TYPE not found — the renderer moved; update this parser"
    return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", m.group(1)))


def test_every_offered_type_is_renderable():
    """The backend must never offer a chart the frontend cannot draw."""
    hints = _renderer_hints()
    offered = set(MODEL_CHART_TYPES) - {"auto"}   # 'auto' is a deferral, not a chart
    missing = offered - hints
    assert not missing, f"offered to the model but unknown to the renderer: {sorted(missing)}"


def test_engine_only_types_are_not_offered():
    """combo arrives only via the deterministic dual-axis gate; matrix is internal.
    A registry that starts offering them has lost the exhibit grammar."""
    assert not set(ENGINE_ONLY_HINTS) & set(MODEL_CHART_TYPES)
    vocab = chart_vocab_line()
    for t in ENGINE_ONLY_HINTS:
        assert f"'{t}'" not in vocab


def test_deep_literals_match_the_registry():
    """Quick and deep offer the SAME vocabulary — the deep pydantic Literals (whose
    JSON-schema enum is what the model actually sees) must equal the registry plus
    'none' (deep-only: a finding may decline a chart)."""
    from aughor.agent.prompts_investigate import PhaseFindingModel, PhaseQueryPlan
    for model in (PhaseQueryPlan, PhaseFindingModel):
        lit = get_args(model.model_fields["chart_type"].annotation)
        assert set(lit) == set(MODEL_CHART_TYPES) | {"none"}, model.__name__


def test_quick_grammar_prompt_offers_the_registry():
    """The grammar prompt derives from the registry — every type appears, and each
    newly-opened type carries its data-shape annotation (offer-but-annotate)."""
    from aughor.agent.prompts import chat_sql_system
    prompt = chat_sql_system(True)
    for t in MODEL_CHART_TYPES:
        assert f"'{t}'" in prompt, t
    for t, shape in EXOTIC_SHAPES.items():
        assert shape in prompt, f"{t} lost its shape annotation"


def test_every_job_resolves_to_a_renderable_form():
    """CA-4 form-by-job: each job the model may name resolves to an engine hint
    the renderer draws, and the web's JOB_TO_ENGINE_HINT mirror agrees with the
    Python JOB_TO_FORM — the two halves of the mapping cannot drift."""
    hints = _renderer_hints()
    for job in CHART_JOBS:
        form = resolve_chart_type(job)
        assert form != job, f"job {job} has no form mapping"
        assert form in hints, f"job {job} resolves to unrenderable {form}"
    src = _WEB_INFERENCE.read_text()
    m = re.search(r"export const JOB_TO_ENGINE_HINT[^=]*=\s*\{(.*?)\};", src, re.S)
    assert m, "JOB_TO_ENGINE_HINT not found in chartTypeInference.ts"
    web_map = dict(re.findall(r"([a-z_]+)\s*:\s*\"([a-z_]+)\"", m.group(1)))
    assert web_map == JOB_TO_FORM, f"job→form drift: web {web_map} vs python {JOB_TO_FORM}"


def test_dual_axis_stays_banned():
    """§6: no dual-axis charts. Neither combo nor pareto may re-enter the model's
    vocabulary, and no job may resolve to one."""
    for banned in ("combo", "pareto"):
        assert banned not in MODEL_CHART_TYPES
        assert banned not in JOB_TO_FORM.values()


def test_legacy_prompt_is_untouched():
    """CHAT_SQL_SYSTEM (benchmark + custom-agent paths) keeps the frozen 14-type
    legacy vocabulary — A5 changes the exhibit-grammar variant only."""
    from aughor.agent.prompts import CHAT_SQL_SYSTEM
    assert "'treemap', 'heatmap', 'combo'" in CHAT_SQL_SYSTEM
    assert "histogram" not in CHAT_SQL_SYSTEM
