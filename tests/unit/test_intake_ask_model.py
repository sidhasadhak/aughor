"""The model is not asked for values the code throws away.

Measured 2026-09-18 while answering "Agent mode is burning tokens": one intake call was
~9,737 tokens — a 12,382-char prompt, up to 20,000 chars of schema, and a 28-field
structured output. Three of those 28 fields are marked "(set by code …)" in their own
descriptions and are overwritten immediately after the call returns:

  descriptive_only   `intake.descriptive_only = _is_descriptive_question(question)` — unconditional
  no_prior_period    decided by `_clamp_intake_to_coverage` from the real date coverage
  named_dimensions   resolved from the question against the schema

So the model reasoned about, and emitted, values that were discarded on the next line.

`IntakeAsk` is `IntakeOutput` minus those fields, DERIVED from the marker rather than
listed beside it — add a fourth code-set field and it leaves the ask on its own. Every
excluded field has a default, so `widen_intake` reproduces exactly the object the
overwrite assumes: this removes wasted work, not behaviour.

HONEST SCALE, recorded so nobody mistakes this for the answer to the token question: the
intake call is 5.2% of a run's prompt tokens (measured over 1,644 recorded llm_calls). The
real drivers are `tool_loop:run_tool_loop` at 42.7% and `sql.writer:fix` at 17.8% — the
latter 435 calls against 67 `write`s, i.e. 6.5 repairs per query generated.
"""
import inspect

from aughor.agent import investigate as I
from aughor.agent.prompts_investigate import (
    _CODE_SET_INTAKE_FIELDS,
    INTAKE_PROMPT,
    IntakeAsk,
    IntakeOutput,
    widen_intake,
)


class TestTheSubsetIsDerived:
    def test_it_excludes_exactly_the_code_set_fields(self):
        assert _CODE_SET_INTAKE_FIELDS == {"descriptive_only", "no_prior_period",
                                           "named_dimensions"}
        assert set(IntakeOutput.model_fields) - set(IntakeAsk.model_fields) == _CODE_SET_INTAKE_FIELDS

    def test_the_marker_is_what_selects_them(self):
        """Derived, not listed: the description IS the declaration, so a fourth code-set
        field leaves the ask without anyone editing a list."""
        for name in _CODE_SET_INTAKE_FIELDS:
            assert "set by code" in (IntakeOutput.model_fields[name].description or "")
        for name in IntakeAsk.model_fields:
            assert "set by code" not in (IntakeOutput.model_fields[name].description or ""), name

    def test_every_excluded_field_has_a_default(self):
        """Without one, widening would raise instead of reproducing the old object."""
        for name in _CODE_SET_INTAKE_FIELDS:
            f = IntakeOutput.model_fields[name]
            assert f.default is not None or f.default_factory is not None, name

    def test_the_code_really_does_overwrite_them(self):
        """If a field stopped being code-set, dropping it from the ask would lose it."""
        src = inspect.getsource(I)
        for name in ("descriptive_only", "no_prior_period", "named_dimensions"):
            assert f"intake.{name} = " in src, f"{name} is no longer assigned by code"


class TestWideningIsLossless:
    #: The minimum a healthy intake carries.
    SPEC = dict(
        metric_label="net revenue", metric_sql="SUM(sale_price)",
        observation_start="2026-03-20", observation_end="2026-09-18",
        observation_label="Last 6 months", comparison_start="2025-09-19",
        comparison_end="2026-03-19", comparison_label="Prior 6 months",
        date_column="main.order_items.created_at", metric_table="main.order_items",
        dimensions=["main.products.category"], intake_notes="",
    )

    def test_it_reproduces_what_the_old_path_produced(self):
        """The whole safety argument: same object, minus work nobody used."""
        asked = IntakeAsk(**self.SPEC)
        widened = widen_intake(asked)
        before = IntakeOutput(**self.SPEC)          # what the old call returned
        assert widened.model_dump() == before.model_dump()

    def test_the_excluded_fields_land_on_their_defaults(self):
        w = widen_intake(IntakeAsk(**self.SPEC))
        assert w.descriptive_only is False
        assert w.no_prior_period is False
        assert w.named_dimensions == []

    def test_a_niche_field_still_round_trips(self):
        """Only the code-set three were removed; the shape-specific fields are untouched."""
        asked = IntakeAsk(**self.SPEC, cross_sectional=True, metric_is_ratio=True,
                          comparison_segment_sql="(late)", relationship_left_sql="delay")
        w = widen_intake(asked)
        assert w.cross_sectional and w.metric_is_ratio
        assert w.comparison_segment_sql == "(late)" and w.relationship_left_sql == "delay"


class TestNoCallSiteStillAsksForTheWholeThing:
    def test_every_intake_round_trip_asks_the_subset(self):
        src = inspect.getsource(I)
        assert "response_model=IntakeOutput" not in src, (
            "an intake call still asks for the code-set fields")
        assert src.count("response_model=IntakeAsk") == 4, (
            "all four intake round-trips (first, validation retry, unsafe-SQL retry, "
            "money retry) must ask the subset")

    def test_each_one_widens(self):
        src = inspect.getsource(I)
        assert src.count("widen_intake(") >= 4


class TestTheDeduplicatedInstructionSurvived:
    def test_the_prompt_no_longer_repeats_the_field(self):
        """`METRIC KIND` restated `metric_is_ratio`'s own description almost verbatim —
        470 characters buying nothing, and two copies that can drift apart."""
        assert "METRIC KIND:" not in INTAKE_PROMPT

    def test_the_instruction_is_still_given(self):
        """Removing a duplicate must not remove the rule. The description is now the one
        place it lives, examples included."""
        d = IntakeOutput.model_fields["metric_is_ratio"].description or ""
        assert "RATIO" in d and "must NOT be summed" in d
        for example in ("cancellation rate", "average order value", "margin %"):
            assert example in d, f"the {example!r} example was lost with the duplicate"
