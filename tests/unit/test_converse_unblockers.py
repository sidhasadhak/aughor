"""The two things Layer 3 needs that its estimate did not book.

The plan describes the converse body as landing on foundations already built. Two of
them were not:

* **A tool call could not be scripted.** The faux backend only ever set
  ``message.content``, so a tool-choosing turn — the whole mechanic of
  pipelines-as-tools — had no way to appear in a test. Worse, this was already a live
  coverage gap: instructor's TOOLS mode is how the gemini binding and the ollama
  reasoning models deliver structured output, and `reliability.response_text` has a
  branch for reading it that nothing could reach.
* **Guard receipts could not be returned.** `run_sql` is meant to hand back
  ``{result, guard_receipts}``, but the seam is push-only: a receipt goes to whoever
  registered a sink and is gone. The data was emitted and never retrievable.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from aughor.kernel.registries import execution_hooks as H
from aughor.llm.faux import FauxToolCall
from aughor.llm.provider import get_provider


class Verdict(BaseModel):
    answer: str


# ── 1. a tool call can be scripted ───────────────────────────────────────────

def test_structured_output_can_arrive_as_a_tool_call(faux_llm):
    """The TOOLS-mode shape, end to end through the real provider stack."""
    faux_llm.set_responses([FauxToolCall({"answer": "via tools"})])
    out = get_provider("coder").complete("s", "u", Verdict)
    assert out.answer == "via tools"


def test_the_tool_call_shape_is_what_the_reader_expects():
    """Pinned against the extraction code rather than assumed. Built directly because
    the assertion IS about the wire shape: content empty, payload on the function
    arguments, the chosen tool nameable — what a real TOOLS binding sends and what
    `reliability.response_text` reaches for."""
    from aughor.llm.faux import _completion
    from aughor.llm.reliability import response_text

    raw = _completion('{"answer": "x"}', system="s", user="u",
                      tool_call=FauxToolCall({"answer": "x"}, name="run_sql"))
    msg = raw.choices[0].message
    assert msg.content is None, "a tool call carries no message content"
    assert msg.tool_calls[0].function.name == "run_sql", "the CHOSEN tool is scriptable"
    assert response_text(raw) == '{"answer": "x"}', "the reader finds the payload"


def test_a_malformed_tool_call_still_classifies(faux_llm):
    """Arguments are validated exactly as content would be — a tool call is not a way
    to smuggle past the reliability layer."""
    from aughor.llm.reliability import StructuredOutputError

    faux_llm.set_responses([FauxToolCall("not json at all")])
    with pytest.raises(StructuredOutputError):
        get_provider("coder").complete("s", "u", Verdict)


def test_content_responses_are_unchanged(faux_llm):
    """The default path must not move: every existing test scripts plain content."""
    faux_llm.set_responses(['{"answer": "via content"}'])
    assert get_provider("coder").complete("s", "u", Verdict).answer == "via content"


# ── 2. guard receipts can be collected ───────────────────────────────────────

def test_receipts_raised_inside_a_block_are_returned():
    with H.collect_guard_receipts() as receipts:
        H.emit_guard_receipt("sql_lint", "rewrote_sql", "added a missing GROUP BY")
    assert len(receipts) == 1
    assert receipts[0]["guard"] == "sql_lint"
    assert receipts[0]["action"] == "rewrote_sql"
    assert "GROUP BY" in receipts[0]["detail"]


def test_before_and_after_ride_along_when_given():
    with H.collect_guard_receipts() as receipts:
        H.emit_guard_receipt("fanout_defan", "rewrote_sql", before="SELECT a", after="SELECT b")
    assert receipts[0]["before"] == "SELECT a"
    assert receipts[0]["after"] == "SELECT b"


def test_collecting_does_not_consume_the_hooks():
    """Opening a collector around code that also streams must not cost the UI its
    frames — the receipt is not a message that gets delivered once."""
    seen = []
    H.register_guard_receipt_hook("test_sink", lambda *a: seen.append(a[0]))
    try:
        with H.collect_guard_receipts() as receipts:
            H.emit_guard_receipt("sql_lint", "rewrote_sql")
        assert len(receipts) == 1
        assert seen == ["sql_lint"], "the registered sink still fired"
    finally:
        H.clear()


def test_nothing_outside_a_block_is_collected():
    """No open collector is the default, and it must stay a free no-op."""
    H.emit_guard_receipt("sql_lint", "rewrote_sql")   # must not raise
    with H.collect_guard_receipts() as receipts:
        pass
    assert receipts == []


def test_a_receipt_after_the_block_does_not_leak_in():
    with H.collect_guard_receipts() as receipts:
        H.emit_guard_receipt("first", "a")
    H.emit_guard_receipt("second", "b")
    assert [r["guard"] for r in receipts] == ["first"]


def test_nested_blocks_collect_independently():
    """A collector answers one caller's question, so an outer block does not absorb an
    inner one's receipts."""
    with H.collect_guard_receipts() as outer:
        H.emit_guard_receipt("outer_before", "a")
        with H.collect_guard_receipts() as inner:
            H.emit_guard_receipt("inner_only", "b")
        H.emit_guard_receipt("outer_after", "c")

    assert [r["guard"] for r in inner] == ["inner_only"]
    assert [r["guard"] for r in outer] == ["outer_before", "outer_after"]


def test_the_detail_is_capped():
    with H.collect_guard_receipts() as receipts:
        H.emit_guard_receipt("g", "a", detail="x" * 5000)
    assert len(receipts[0]["detail"]) == 500
