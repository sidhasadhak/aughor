"""DS-18 (§3.7 second movement) — write up what the step before produced.

The wave's falsifier, from the roadmap: **a `synthesize` answer that states a number
absent from its input.** If that can happen the step is wrong, because this value is bound
into a Slack message or an inbox note where the surrounding prose is the author's and
nothing downstream carries a caveat.

The other three properties are the ones that keep it from being a slop generator pointed at
a channel: an empty input is a stated refusal rather than a paragraph about nothing, the cap
is published rather than implied, and the answer says what it read.
"""
from __future__ import annotations

import pytest

from aughor.automations.models import Automation, Condition, Effect
from aughor.automations.synthesize import MAX_ROWS, dispatch_synthesize


def _auto() -> Automation:
    return Automation(
        id="a1", conn_id="c1", name="nightly",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="synthesize", config={"data": "x"})])


def _step(config: dict, alias: str = "write") -> Effect:
    """A step as the DISPATCHER receives it — constructed with its authored binding, then
    carrying the resolved config, exactly as `_execute_step` hands it over.

    Built this way because a literal empty `data` cannot be CONSTRUCTED (the required-key
    validator refuses it, correctly — an authored step with no input names nothing). The
    empty case is real all the same: `data` is authored as `{"$from": "q.rows"}`, which is
    truthy, and resolves to `[]` on a quiet day. Constructing the empty config directly
    would have tested a shape the engine never produces.
    """
    authored = Effect(kind="synthesize", alias=alias,
                      config={"data": {"$from": "q.rows"}})
    return authored.model_copy(update={"config": config})


class _Provider:
    """Scripted answers, one per call, so a repair attempt can be given a second one."""

    def __init__(self, *answers: str):
        self.answers, self.calls = list(answers), []

    def complete(self, *, system, user, temperature=0.0, **kw):
        self.calls.append(user)
        return self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]


@pytest.fixture
def provider(monkeypatch):
    def _install(*answers: str) -> _Provider:
        p = _Provider(*answers)
        monkeypatch.setattr("aughor.llm.provider.get_provider", lambda *a, **k: p)
        return p
    return _install


ROWS = [{"region": "EMEA", "orders": 1_412}, {"region": "APAC", "orders": 903}]


# ── THE FALSIFIER ────────────────────────────────────────────────────────────────

def test_an_answer_stating_a_number_absent_from_its_input_is_NOT_published(provider):
    """Both attempts invent 2,315 — a plausible sum, and precisely the kind of number a
    model derives when nobody is checking. The step fails and publishes nothing."""
    p = provider("EMEA and APAC together did 2,315 orders.",
                 "Still 2,315 orders across the two regions.")
    out = dispatch_synthesize(_step({"data": ROWS, "context": "how did we do?"}), _auto())

    assert out.status == "failed"
    assert out.data is None or "answer" not in (out.data or {})
    assert "not in the data" in out.message
    assert len(p.calls) == 2, "it must try once to repair before giving up"


def test_a_repaired_answer_IS_published(provider):
    """One repair, and the second attempt grounds itself. The repair prompt has to name
    the offending figures, or it is a retry rather than a repair."""
    p = provider("Together they did 2,315 orders.",
                 "EMEA led with 1,412 orders; APAC did 903.")
    out = dispatch_synthesize(_step({"data": ROWS}), _auto())

    assert out.status == "executed"
    assert out.data["answer"] == "EMEA led with 1,412 orders; APAC did 903."
    assert "2,315" in p.calls[1] and "REJECTED" in p.calls[1]


def test_numbers_quoted_from_the_data_pass_first_time(provider):
    p = provider("EMEA did 1,412 orders and APAC did 903.")
    out = dispatch_synthesize(_step({"data": ROWS}), _auto())
    assert out.status == "executed"
    assert len(p.calls) == 1, "a grounded answer must not pay for a repair"


# ── empty is a stated refusal, not a paragraph about nothing ─────────────────────

@pytest.mark.parametrize("empty", [None, [], {}, ""])
def test_empty_input_is_skipped_with_a_reason_and_never_reaches_the_model(provider, empty):
    p = provider("Nothing much happened this week, which is itself reassuring.")
    out = dispatch_synthesize(_step({"data": empty}), _auto())

    assert out.status == "skipped"
    assert "empty" in out.message
    # §3.11's lesson: "failed" and "healthy empty" must not render alike — and neither
    # should be spent on a model that would happily narrate the absence.
    assert p.calls == []


@pytest.mark.parametrize("falsy", [0, 0.0, False])
def test_zero_is_a_finding_not_an_absence(provider, falsy):
    """A governed metric that reads 0, or a flag that reads False, is an ANSWER. Treating
    it as absence is how a real result becomes a shrug — and `not data` would do exactly
    that, which is why this asserts on the SCALAR a `metric_value.value` binding delivers
    rather than on a dict that merely contains one.

    🔑 The first version of this test did pass a dict (`{"count": 0}`), and a mutation run
    caught it: a truthiness check survived, because a non-empty dict is truthy whatever is
    inside it. The test named the right property and could not fail on it.
    """
    provider("The count is 0.")
    out = dispatch_synthesize(_step({"data": falsy}), _auto())
    assert out.status == "executed"


# ── the cap is published, not implied ────────────────────────────────────────────

def test_a_long_result_is_capped_and_SAYS_so(provider):
    p = provider("Most rows are small.")
    rows = [{"n": i} for i in range(MAX_ROWS + 50)]
    out = dispatch_synthesize(_step({"data": rows}), _auto())

    assert out.status == "executed"
    # `mcp_call`'s precedent: a step reading `answer` must be able to tell a whole one
    # from half of one, so this is a value to guard on rather than a fact in the prose.
    assert out.data["truncated"] is True
    assert str(MAX_ROWS) in out.message
    assert f'"n": {MAX_ROWS - 1}' in p.calls[0]
    assert f'"n": {MAX_ROWS}' not in p.calls[0]


def test_a_short_result_is_not_marked_truncated(provider):
    provider("Two regions.")
    out = dispatch_synthesize(_step({"data": ROWS}), _auto())
    assert out.data["truncated"] is False


# ── the answer says what it read, and does what it was told ─────────────────────

def test_the_answer_carries_the_reference_it_synthesised(provider):
    from aughor.automations.engine import SYNTHESIS_SOURCE_KEY

    provider("EMEA did 1,412 orders.")
    out = dispatch_synthesize(
        _step({"data": ROWS, SYNTHESIS_SOURCE_KEY: "rollup.rows"}), _auto())
    # So a Slack message's receipt reaches back to the query a person approved.
    assert out.data["source"] == "rollup.rows"


def test_the_authored_context_reaches_the_model_and_a_missing_one_has_a_stated_default(provider):
    from aughor.automations.synthesize import DEFAULT_CONTEXT

    p = provider("EMEA did 1,412 orders.")
    dispatch_synthesize(_step({"data": ROWS, "context": "call out anything unusual"}), _auto())
    assert "call out anything unusual" in p.calls[0]

    p2 = provider("EMEA did 1,412 orders.")
    dispatch_synthesize(_step({"data": ROWS}), _auto())
    assert DEFAULT_CONTEXT in p2.calls[0]


def test_a_model_outage_is_a_step_failure_not_a_crash(monkeypatch):
    class _Boom:
        def complete(self, **kw):
            raise RuntimeError("model unreachable")

    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda *a, **k: _Boom())
    out = dispatch_synthesize(_step({"data": ROWS}), _auto())
    assert out.status == "failed"
    assert "model unreachable" in out.message


def test_an_empty_model_answer_is_a_failure_rather_than_an_empty_publish(provider):
    provider("   ")
    out = dispatch_synthesize(_step({"data": ROWS}), _auto())
    assert out.status == "failed"


# ── the step is wired into the plane the same way every sibling is ──────────────

def test_the_kind_is_registered_everywhere_a_step_has_to_be():
    from aughor.automations.dataflow import BINDABLE_FIELDS, PUBLISHED_KEYS
    from aughor.automations.engine import _DISPATCHERS
    from aughor.automations.palette import entries

    assert PUBLISHED_KEYS["synthesize"] == ("answer", "truncated", "source")
    assert BINDABLE_FIELDS["synthesize"] == ("data", "context")
    assert _DISPATCHERS["synthesize"] is dispatch_synthesize
    row = next(e for e in entries("any") if e["kind"] == "synthesize")
    # Always ready: both its required keys are values a person types, which is
    # `palette.py`'s own rule for a kind that needs nothing to exist here.
    assert row["availability"] == "ready"


def test_a_step_with_no_data_is_refused_at_construction():
    with pytest.raises(ValueError, match="data"):
        Effect(kind="synthesize", config={"context": "summarise"})
