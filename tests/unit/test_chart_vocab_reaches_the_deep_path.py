"""The investigation path must actually be OFFERED the chart vocabulary.

Reported 2026-09-18: "I barely see any different charts used in the Investigations — it's
always either line or bar. What happened to all the efforts we put in? Is the LLM not able
to make a judgement call?"

Measured over the 1,026 stored complete investigations (1,477 findings):

    bar_horizontal  779  52.7%      line     107   7.2%
    (none)          326  22.1%      pie       25   1.7%
    auto            237  16.0%      heatmap    3   0.2%

Six distinct types out of twenty-two, and the CA-4 job vocabulary — magnitude, trend,
identity, change, share, distribution, relation — named **zero** times in three months.

It was not a judgement failure. The model was never told what the words mean:

- `chart_vocab_line()` — 1,755 characters explaining every job and every specialised shape
  — is spliced into `prompts.py` only. That is the QUICK path. The deep path never saw it.
- Both deep-path models declared `chart_type` as a BARE `Literal[...]`: 22 opaque tokens,
  no descriptions, nothing saying what `magnitude` or `identity` mean.
- Meanwhile the deep-path prompts told it to return "line", "bar", "pareto" and
  "bar_horizontal" — three of which that same Literal forbids, and `pareto` which
  `chart_vocab` never offers at all, because dual-axis is banned (§6).

So the instruction and the schema contradicted each other. The model emitted what the
prompt asked for, structured output rejected it, and the field fell back to its `auto`
default — which is exactly the September shape in the data: legacy tokens collapse to 27%
while auto/none climbs to 73%.

These pin the wiring, not the model's taste.
"""
import inspect
import re

import pytest

from aughor.agent import chart_vocab as CV
from aughor.agent import prompts_investigate as PI


CHART_MODELS = (PI.PhaseQueryPlan, PI.PhaseFindingModel) if hasattr(PI, "PhaseFindingModel") else ()


def _models_with_chart_type():
    import pydantic
    out = []
    for name, obj in vars(PI).items():
        if isinstance(obj, type) and issubclass(obj, pydantic.BaseModel):
            if "chart_type" in getattr(obj, "model_fields", {}):
                out.append((name, obj))
    return out


class TestTheModelIsToldWhatTheWordsMean:
    def test_every_chart_type_field_carries_the_vocabulary(self):
        models = _models_with_chart_type()
        assert models, "no model declares chart_type — re-pin this test"
        for name, model in models:
            desc = model.model_fields["chart_type"].description or ""
            assert desc, f"{name}.chart_type is a bare Literal — 22 tokens with no meaning"
            for job in CV.CHART_JOBS:
                assert job in desc, f"{name}.chart_type never explains the job {job!r}"

    def test_the_description_comes_from_the_one_registry(self):
        """A5's rule. A second hand-written copy is how the three vocabularies that this
        module replaced drifted apart in the first place."""
        assert PI._CHART_VOCAB == CV.chart_vocab_field_description()

    def test_the_two_vocabulary_renderings_agree(self):
        """The prompt sentence and the field description are different shapes of the same
        two dicts; a job in one must be a job in the other."""
        line, field = CV.chart_vocab_line(), CV.chart_vocab_field_description()
        for job in CV.CHART_JOBS:
            assert job in line and job in field, job


class TestThePromptsDoNotContradictTheSchema:
    #: Every value the models will actually accept.
    ALLOWED = set(PI.PhaseQueryPlan.model_fields["chart_type"].annotation.__args__)

    @pytest.mark.parametrize("token", ["bar_horizontal", "bar", "line", "pie", "pareto"])
    def test_the_legacy_shape_tokens_are_not_instructed(self, token):
        """A prompt that names a token the schema rejects cannot be obeyed. `pareto` is the
        sharpest case: it is banned outright (dual-axis, §6) and was still being asked for."""
        src = inspect.getsource(PI)
        # Only the INSTRUCTION matters; the prose above quotes these tokens deliberately.
        for m in re.finditer(r'chart_type[^\n]*', src):
            text = m.group(0)
            if text.lstrip().startswith("#") or "Literal[" in text:
                continue
            assert f'"{token}"' not in text, f"a prompt still instructs {token!r}: {text[:90]}"

    def test_every_instructed_token_is_one_the_schema_accepts(self):
        src = inspect.getsource(PI)
        for m in re.finditer(r'chart_type[^\n]*', src):
            text = m.group(0)
            if text.lstrip().startswith("#") or "Literal[" in text:
                continue
            for tok in re.findall(r'"([a-z_]+)"', text):
                assert tok in self.ALLOWED, f"prompt instructs {tok!r}, which the schema rejects"

    def test_pareto_is_offered_nowhere(self):
        assert "pareto" not in CV.CHART_JOBS
        assert "pareto" not in CV.EXOTIC_SHAPES
        assert "pareto" not in self.ALLOWED
