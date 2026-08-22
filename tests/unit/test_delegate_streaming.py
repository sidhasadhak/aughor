"""A delegate's frames must arrive ATTRIBUTED, or not arrive.

Before this, `delegate_task` handed the parent's `emit` straight to the delegate. The
frames did reach the user — and that was the problem. A delegate's SQL, its row counts
and its guard receipts landed in the parent's stream reading exactly like the
supervisor's own work, so the conversation showed a query nobody in it appeared to have
run, against a connection the supervisor may not even be bound to. You could see that
something happened and not who did it.

Two rules, and they pull in opposite directions on purpose:

* **Work frames are forwarded, stamped** with the same `agent_path` the cycle check
  uses — one identity, so what the UI draws and what the runtime refuses cannot disagree.
* **Prose and lifecycle frames are dropped.** The delegate's answer already comes back
  as the tool result; relaying its token stream puts every token on the wire twice. And
  a delegate's `done` would render the turn finished while the supervisor is still
  working.
"""
from __future__ import annotations

from aughor.agent.delegate_tool import _DELEGATE_SUPPRESSED, delegated_emit
from aughor.agent.delegation import DelegationContext


def _capture():
    seen: list[tuple[str, dict]] = []
    return seen, lambda n, p: seen.append((n, p))


def _child(*path: str) -> DelegationContext:
    return DelegationContext(agent_path=tuple(path))


# ── attribution ─────────────────────────────────────────────────────────────────

def test_a_work_frame_is_forwarded_carrying_who_produced_it():
    seen, emit = _capture()
    relay = delegated_emit(emit, ctx=_child("analyst"), agent_id="analyst",
                           agent_name="Analyst")

    relay("sql", {"sql": "SELECT 1"})

    assert len(seen) == 1, "the delegate's work frame never reached the parent stream"
    name, payload = seen[0]
    assert name == "sql"
    assert payload["sql"] == "SELECT 1", "the frame's own content must survive untouched"
    assert payload["delegate"] == {
        "sub_agent_id": "analyst",
        "sub_agent_name": "Analyst",
        "parent_agent_id": "",          # delegated straight from the conversation
        "agent_path": "analyst",
        "depth": 1,
    }


def test_a_nested_delegate_names_its_caller_not_the_root():
    """Depth is unbounded by decision, so `parent_agent_id` has to be the ACTUAL caller."""
    seen, emit = _capture()
    relay = delegated_emit(emit, ctx=_child("analyst", "auditor"), agent_id="auditor",
                           agent_name="Auditor")

    relay("rows", {"rows": [[1]]})

    stamp = seen[0][1]["delegate"]
    assert stamp["parent_agent_id"] == "analyst", "a nested hop misnamed its caller"
    assert stamp["agent_path"] == "analyst/auditor"
    assert stamp["depth"] == 2


def test_the_stamp_matches_the_path_the_cycle_check_authorises_on():
    """One identity, or the tree the UI draws is not the tree the runtime refused."""
    ctx = _child("a", "b", "c")
    seen, emit = _capture()
    delegated_emit(emit, ctx=ctx, agent_id="c", agent_name="C")("sql", {})

    assert seen[0][1]["delegate"]["agent_path"] == "/".join(ctx.agent_path)
    assert seen[0][1]["delegate"]["depth"] == ctx.depth


# ── the copy rule ───────────────────────────────────────────────────────────────

def test_the_stamp_never_mutates_the_pipeline_s_own_payload():
    """The answer pipeline reuses payload dicts across frames. A stamp written in place
    would follow one onto frames this delegate never produced."""
    seen, emit = _capture()
    relay = delegated_emit(emit, ctx=_child("analyst"), agent_id="analyst",
                           agent_name="Analyst")

    reused = {"sql": "SELECT 1"}
    relay("sql", reused)

    assert "delegate" not in reused, (
        "the wrapper wrote its stamp into the caller's dict — the next frame to reuse it "
        "would claim to come from an agent that did not produce it")


def test_two_hops_do_not_share_one_stamp_object():
    seen, emit = _capture()
    delegated_emit(emit, ctx=_child("a"), agent_id="a", agent_name="A")("sql", {})
    delegated_emit(emit, ctx=_child("b"), agent_id="b", agent_name="B")("sql", {})

    assert seen[0][1]["delegate"]["sub_agent_id"] == "a"
    assert seen[1][1]["delegate"]["sub_agent_id"] == "b"
    assert seen[0][1]["delegate"] is not seen[1][1]["delegate"]


# ── suppression ─────────────────────────────────────────────────────────────────

def test_the_delegate_s_prose_is_not_streamed_twice():
    """It is already coming back as the tool result. Relaying it doubles every token."""
    seen, emit = _capture()
    relay = delegated_emit(emit, ctx=_child("analyst"), agent_id="analyst",
                           agent_name="Analyst")

    for frame in ("narrative_delta", "insight_delta", "report_delta", "headline"):
        relay(frame, {"text": "..."})

    assert seen == [], f"the delegate's prose reached the wire: {[n for n, _ in seen]}"


def test_a_delegate_cannot_end_or_redden_the_parent_turn():
    """Only the outer turn knows when it is over; a failure comes back as a RESULT."""
    seen, emit = _capture()
    relay = delegated_emit(emit, ctx=_child("analyst"), agent_id="analyst",
                           agent_name="Analyst")

    relay("done", {"inv_id": "x"})
    relay("error", {"message": "boom"})
    relay("mode", {"mode": "final_text"})

    assert seen == [], (
        "a delegate ended or mislabelled the supervisor's turn — "
        f"{[n for n, _ in seen]} must never leave the hop")


def test_guard_receipts_survive_suppression():
    """The evidence guards are the product. Dropping a delegate's receipt would let its
    answer reach the narrator with no proof attached."""
    seen, emit = _capture()
    delegated_emit(emit, ctx=_child("analyst"), agent_id="analyst",
                   agent_name="Analyst")("guard_receipt", {"guard": "grounding"})

    assert [n for n, _ in seen] == ["guard_receipt"]
    assert seen[0][1]["delegate"]["sub_agent_id"] == "analyst"


def test_suppression_is_not_silently_empty():
    """A rot guard: if the set is ever emptied, everything forwards and this file's other
    assertions would still pass one by one."""
    assert {"done", "error", "narrative_delta"} <= _DELEGATE_SUPPRESSED


# ── the no-emit caller ──────────────────────────────────────────────────────────

def test_a_non_streaming_caller_stays_non_streaming():
    """`delegate_task` is also called with emit=None; the wrapper must not invent one."""
    assert delegated_emit(None, ctx=_child("a"), agent_id="a", agent_name="A") is None


# ── the hop actually uses it ────────────────────────────────────────────────────

def test_the_hop_streams_under_the_delegate_s_identity_not_the_caller_s():
    """The seam test: wiring the wrapper and never calling it would pass every test
    above. This one drives `_run_one` and reads what the pipeline was handed."""
    from aughor.agent.delegate_tool import _run_one

    seen, emit = _capture()
    handed: dict = {}

    def _answer(conn, args, *, emit=None, session_id=""):
        handed["emit"] = emit
        emit("sql", {"sql": "SELECT 1"})       # the delegate does some work
        emit("narrative_delta", {"text": "…"})  # ... and some prose
        return {"answer": "42", "usage": {}}

    row = _run_one({"id": "analyst", "name": "Analyst", "connection_id": "c1"},
                   "count things", DelegationContext(),
                   answer=_answer, emit=emit)

    assert handed["emit"] is not emit, (
        "the delegate was handed the PARENT's emit — its frames stream unattributed")
    assert [n for n, _ in seen] == ["sql"], (
        f"expected the work frame only, got {[n for n, _ in seen]}")
    assert seen[0][1]["delegate"]["sub_agent_name"] == "Analyst"
    assert row["response"] == "42"
