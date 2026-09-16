"""The raw streaming path tells the model the WHOLE shape it must write.

It bypasses instructor's schema prompt, and its own instruction named top-level fields
only — `"recommendations" (array)` — so the model wrote strings where objects are required.
Every deep synthesis on the OpenAI-compatible path then failed its terminal validation
("recommendations.0 Input should be a valid dictionary or instance of
AnswerRecommendationModel") and was paid for a second time through the blocking fallback.

Hermetic: schemas and a stub stream only.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest
from pydantic import BaseModel

from aughor.llm.provider import LLMProvider, _json_shape


def _streamed_models():
    """Every response model the codebase hands to `complete_streaming`."""
    from aughor.agent.prompts_investigate import ADASynthesisModel
    from aughor.routers.investigations import _ChatAnswer, _PostAnswer
    return [ADASynthesisModel, _ChatAnswer, _PostAnswer]


def test_the_models_checked_here_are_every_streamed_call_site():
    """The population is read from the source, so a new streamed call cannot slip past."""
    names: set[str] = set()
    for path in (Path(__file__).resolve().parents[2] / "aughor").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "complete_streaming":
                names |= {kw.value.id for kw in node.keywords
                          if kw.arg == "response_model" and isinstance(kw.value, ast.Name)}
    assert names == {m.__name__ for m in _streamed_models()}


def _field_names(node: dict, defs: dict, seen: frozenset = frozenset()) -> set[str]:
    """Every property name at every depth — independent of the renderer under test."""
    out: set[str] = set()
    ref = node.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        return set() if name in seen else _field_names(defs[name], defs, seen | {name})
    for key, sub in (node.get("properties") or {}).items():
        out.add(key)
        out |= _field_names(sub, defs, seen)
    for key in ("items",):
        if isinstance(node.get(key), dict):
            out |= _field_names(node[key], defs, seen)
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in node.get(key) or []:
            out |= _field_names(sub, defs, seen)
    return out


@pytest.mark.parametrize("model", _streamed_models(), ids=lambda m: m.__name__)
def test_every_field_at_every_depth_is_named(model):
    schema = model.model_json_schema()
    instruction = LLMProvider._json_stream_instruction(model)
    missing = {f for f in _field_names(schema, schema.get("$defs") or {})
               if f'"{f}":' not in instruction}
    assert not missing, f"the stream instruction never names: {sorted(missing)}"


def test_the_synthesis_shape_spells_out_its_objects_and_choices():
    from aughor.agent.prompts_investigate import ADASynthesisModel
    text = LLMProvider._json_stream_instruction(ADASynthesisModel)
    assert ('"recommendations": [{"action": string, "expected_impact": string, '
            '"owner": string, "timeline": string}]') in text
    assert '"confidence": "HIGH"|"MEDIUM"|"LOW"' in text
    assert '"from_entity": string|null' in text
    assert text.lstrip().startswith("Return ONLY a JSON object")


def test_a_recursive_model_is_named_not_expanded_forever():
    class Node(BaseModel):
        label: str
        children: list["Node"] = []
        parent: Optional["Node"] = None

    schema = Node.model_json_schema()
    shape = _json_shape(schema, schema.get("$defs") or {})
    assert '"label": string' in shape and "Node" in shape


def test_an_object_shaped_synthesis_needs_no_blocking_redo(monkeypatch):
    """What the instruction buys: the model writes the shape, the terminal validation
    passes, and the blocking fallback is never paid for."""
    from aughor.agent.prompts_investigate import ADASynthesisModel

    body = ('{"headline": "Orders fell 9%", "executive_summary": "Orders fell **9%**.", '
            '"total_change_label": "-9%", "attribution_waterfall": [{"cause": "fewer visits", '
            '"amount_label": "-9%", "pct_of_total": -100.0, "controllable": false, '
            '"structural": false}], "confidence": "MEDIUM", "confidence_justification": "one '
            'day", "recommendations": [{"action": "Check **paid traffic**", "expected_impact": '
            '"recovers visits", "owner": "Growth", "timeline": "this week"}]}')
    chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=body))],
                            usage=None)
    completions = SimpleNamespace(create=lambda **kw: iter([chunk]))
    prov = LLMProvider("ollama", "narrator", model="stub-model", base_url="http://localhost:1/v1")
    prov._client = SimpleNamespace(client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))

    def _no_redo(self, **kw):
        raise AssertionError("the blocking redo ran — the stream did not validate")

    monkeypatch.setattr(LLMProvider, "complete", _no_redo)
    out = prov.complete_streaming(system="s", user="u", response_model=ADASynthesisModel,
                                  text_field="executive_summary", on_text=lambda t: None)
    assert out.recommendations[0].owner == "Growth"
