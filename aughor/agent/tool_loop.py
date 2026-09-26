"""The tool-choosing loop — Layer 3's engine, and the first one in this repo.

Every LLM call aughor has ever made was one shot: ask for a shape, get it back. An
agent turn is different in kind — the model may need to look something up before it
can answer, and then look up something else because of what it found. That is a loop,
and no loop existed anywhere in the codebase.

What this is NOT is a router. The model chooses which tool the conversation needs; it
never decides whether a query is safe or correct. Every guard stays inside the tool
body, which is the inversion the whole plan rests on: an LLM picking a pipeline is a
conversation decision, an LLM approving SQL is not.

Three failure modes are values, never exceptions (P2). A model that names a tool that
does not exist, one that emits arguments that will not parse, and a tool body that
raises are all things the model can recover from IF it is told. Raising instead ends
the turn on a technicality and throws away the work already done; the model is told,
and gets to try something else.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from aughor.llm.provider import LLMProvider, ToolTurn

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    """One tool the model may choose.

    ``description`` is the routing policy (P3): there is no intent classifier, so what
    the docstring says is the entire basis on which the model picks. ``run`` receives
    the parsed arguments and returns anything JSON-serialisable.
    """
    name: str
    description: str
    parameters: dict
    run: Callable[[dict], Any]

    def as_wire(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.parameters}}


@dataclass
class LoopStep:
    """One turn, recorded. The route receipt Wave 6 measures is built from these."""
    tool: str
    arguments: dict
    ok: bool
    detail: str = ""
    #: Characters this step's tool result added to the conversation.
    result_chars: int = 0
    #: Characters of history sent to the model on the turn that PRODUCED this step.
    #: The interesting one: history is re-sent whole on every turn, so a result
    #: fetched once is paid for again on each later turn. That re-sending — not any
    #: repeated query — is what 4.3's handles actually remove.
    prompt_chars: int = 0


@dataclass
class LoopResult:
    answer: Optional[str]
    steps: list[LoopStep] = field(default_factory=list)
    #: Why the loop ended: "answered" (the model produced text) | "budget" (it spent
    #: every step) | "silent" (it returned neither a tool call nor text, twice — a
    #: stall, and deliberately NOT the same thing as running out of budget, because
    #: telling a user to narrow their question is wrong advice when the turn stopped
    #: after one step of eight).
    stop_reason: str = "answered"

    @property
    def used_tools(self) -> bool:
        return bool(self.steps)

    @property
    def injected_chars(self) -> int:
        """Total tool-result characters sent to the model across the whole turn.

        Not the sum of result sizes — the sum of what was RE-SENT. A 40 KB result
        fetched on step 1 of a 5-step turn is transmitted 4 more times. This is the
        quantity a handle registry would replace with a preview plus an id, and it is
        the half of 4.3's pre-check that repeat-counting never measured.
        """
        return sum(s.prompt_chars for s in self.steps)

    @property
    def reinjection_ratio(self) -> float:
        """`injected_chars` over the bytes actually fetched. 1.0 means nothing was ever
        re-sent; 3.0 means the average result rode along three times. Handles are worth
        building when this is high, EVEN IF no query is ever repeated."""
        fetched = sum(s.result_chars for s in self.steps)
        return (self.injected_chars / fetched) if fetched else 0.0


def _budget(provider: LLMProvider) -> int:
    """Loop ceiling from the model's own profile, never a module constant."""
    from aughor.llm.profile import profile_for
    return profile_for(provider.role).tool_loop_steps


def run_tool_loop(
    provider: LLMProvider,
    system: str,
    question: str,
    tools: list[ToolSpec],
    *,
    max_steps: Optional[int] = None,
    on_step: Optional[Callable[[LoopStep], None]] = None,
    conn_id: str = "",
    trace_id: str = "",
    inv_id: str = "",
    site: str = "converse.tool",
    replay_args: Optional[dict] = None,
) -> LoopResult:
    """Run one converse turn to an answer, or until the budget runs out.

    The loop is deliberately dumb about content: it dispatches what the model asked
    for, hands back what the tool returned, and asks again. Everything that makes an
    answer trustworthy lives inside the tools.

    ``on_step`` is called with each :class:`LoopStep` the instant it is recorded — the
    turn's only progress seam. A streaming caller needs it for two things a returned
    ``LoopResult`` cannot give: frames while the turn is still running, and a
    CANCELLATION checkpoint (raise from the callback and the loop unwinds), which is
    what stops a departed client from paying for the remaining provider round-trips.
    Default ``None`` so every existing caller — the ten-turn receipt included — runs
    the identical code path it ran before.

    ``conn_id`` / ``trace_id`` / ``inv_id`` are provenance for the decision records this
    loop writes, and nothing else reads them. They default to empty so a caller that does
    not have a run around it is unchanged; a caller that does should pass them, because a
    tool pick recorded without its connection cannot be attributed to the roster and
    schema the model was actually choosing against.

    ``site`` names WHICH decider this is, and it matters because this loop has two callers
    with different rosters: `converse_tools.converse` (38 tools) and `analyst.run_analyst`
    (11). The site was a hardcoded ``"converse.tool"`` literal here until 2026-09-21, so
    every analyst pick was filed under the conversational label — measured on the live
    corpus that was **46 of 58 rows, 79%**, and the two are discriminable only by an
    accident of roster size (the 38-entry menu carries ``delegate_task``; the 11-entry one
    does not). A corpus whose site column answers "which decider" wrongly cannot be
    segmented by decider at all, which is what every judgment measurement over it needs.
    The default stays ``"converse.tool"`` so a caller that has not been updated keeps the
    label its rows already carry rather than silently starting a third population.
    """
    by_name = {t.name: t for t in tools}
    wire = [t.as_wire() for t in tools]
    # JD-4 — a fingerprint of what the decider was shown. `system` is built once by the
    # caller and never mutated across steps, so one fingerprint covers the whole turn. It is
    # metadata (irreversible) and rides every decision row; see `_prompt_sha256`.
    prompt_fingerprint = _prompt_sha256(system)
    # The decision-record menu: SORTED, so the option order (and therefore each label
    # index) is stable across turns regardless of roster assembly order. Only real
    # menus are recorded — one tool is not a choice.
    menu = sorted(by_name)
    budget = max_steps if max_steps is not None else _budget(provider)
    history: list[dict] = []
    steps: list[LoopStep] = []
    # One nudge per turn. A model that goes silent twice is not stalling on a
    # formatting slip, and re-asking would spend the whole budget on silence.
    nudged = False

    def _record(step: LoopStep, *, result: Any = None, elapsed_ms: Optional[float] = None) -> None:
        """Append, announce and RECORD, together. Four branches record a step and all
        four must reach the caller — a progress seam that only reports the SUCCESSFUL
        branch would show a turn recovering from nothing — and all four land in the
        session log as one `step` event (TJ-2), so the trajectory a run leaves behind
        has every step the loop took, not only the ones that ran a tool."""
        steps.append(step)
        _emit_step(len(steps), step, result=result, elapsed_ms=elapsed_ms,
                   site=site, conn_id=conn_id, trace_id=trace_id)
        if on_step is not None:
            on_step(step)

    for _ in range(budget):
        turn: ToolTurn = provider.complete_with_tools(
            system, question, wire, history=history or None)

        if turn.malformed:
            # The model DID choose — it just wrote the arguments badly. Telling it so is
            # what lets it retry; silence would read as "the tool returned nothing".
            _record(LoopStep(tool="?", arguments={}, ok=False, detail=turn.malformed))
            history.extend(_exchange(None, f"Your tool arguments could not be parsed: "
                                           f"{turn.malformed}. Try again with valid JSON."))
            continue

        if not turn.chose_tool:
            if (turn.text or "").strip():
                return LoopResult(answer=turn.text, steps=steps, stop_reason="answered")
            # The model chose no tool AND wrote nothing. Returning that as an answer
            # hands the caller an empty string it can only report as a failure — and
            # observed live, it does: a question whose tables were sitting in the
            # `list_tables` result it had just been given came back "I ran out of
            # steps" after ONE step of a budget of eight.
            #
            # Silence is not a decision, so it does not end the turn. Say so and let
            # the model spend another step — it still cannot exceed the budget, and
            # the nudge names the two ways out so a second silence is a real choice
            # rather than a stall. Recorded as a step so the turn's cost stays honest.
            if nudged:
                return LoopResult(answer=None, steps=steps, stop_reason="silent")
            nudged = True
            _record(LoopStep(tool="(none)", arguments={}, ok=False,
                             detail="model returned neither a tool call nor text"))
            history.extend(_exchange(
                None,
                "You returned neither a tool call nor an answer. Either call one of the "
                "available tools, or answer the question directly in plain text using "
                "what the previous tool results already gave you."))
            continue

        call = turn.tool_call
        assert call is not None       # chose_tool is exactly this check
        spec = by_name.get(call.name)
        if spec is None:
            # A hallucinated tool name. Naming the real ones back is cheaper than a
            # wasted step, and the model almost always corrects on the next turn.
            offered = ", ".join(sorted(by_name)) or "(none)"
            _record(LoopStep(tool=call.name, arguments=call.arguments, ok=False,
                             detail="no such tool"))
            history.extend(_exchange(call, f"No tool named {call.name!r}. Available: {offered}."))
            continue

        _t0 = time.monotonic()
        try:
            result = spec.run(call.arguments)
            ok, payload = True, _as_text(result)
        except Exception as exc:
            # A tool that raises is a RESULT — "that query failed, here is why" is
            # something the model can act on. Letting it propagate would end the turn
            # and discard every step already paid for.
            logger.warning("tool_loop: %s raised (%s)", call.name, str(exc)[:200])
            ok, payload = False, f"{type(exc).__name__}: {exc}"
            result = None
        _record(LoopStep(tool=call.name, arguments=call.arguments, ok=ok,
                         detail="" if ok else payload,
                         result_chars=len(payload),
                         prompt_chars=_history_chars(history)),
                result=result, elapsed_ms=(time.monotonic() - _t0) * 1000.0)
        # One decision record per executed choice: the menu the model picked from, what
        # it picked, and whether the pick ran clean. The context is a routing glimpse
        # (step position, the previous pick and how it went, the question) — never tool
        # results, which belong to the session log. Hallucinated names are skipped: a
        # pick that was not on the menu is a model failure, not a selection example.
        if len(menu) >= 2:
            prev = steps[-2] if len(steps) >= 2 else None
            from aughor.learning.decisions import record_decision
            decision_id = record_decision(
                site,
                f"step {len(steps)} | last {prev.tool + (' ok' if prev.ok else ' error') if prev else '(start)'}"
                f" | {question}",
                menu, chosen=call.name, source="llm",
                # TJ-3 (2026-09-26): "the tool did not raise" is liveness, not quality — unlabeled.
                outcome="unlabeled" if ok else "error",
                conn_id=conn_id, trace_id=trace_id, inv_id=inv_id,
                prompt_fingerprint=prompt_fingerprint)
            # `history` has not had THIS step appended yet (that is the next line), so an
            # empty history here means the model decided with nothing but system + question
            # + tools in front of it: the only rows a shuffled control can rebuild faithfully.
            if not history and replay_args:
                _capture_replay(decision_id, site, question, wire, provider, prompt_fingerprint,
                                replay_args, trace_id=trace_id)
        history.extend(_exchange(call, payload))

    # Budget spent. The turn is not an error — it is an answer we did not reach, and
    # saying so plainly beats presenting a half-derived guess as a conclusion.
    return LoopResult(answer=None, steps=steps, stop_reason="budget")


#: The temperature `LLMProvider.complete_with_tools` defaults to, and therefore what this loop
#: REQUESTS (it passes none). Recorded as requested, not as served: a run-scoped pin in the
#: provider can silently beat the argument, which is one of the things a replay cannot hold
#: constant and the battery says so rather than assuming it.
_REQUESTED_TEMPERATURE = 0.1


def _prompt_sha256(system: str) -> str:
    """sha256 of the assembled system prompt, or '' when there is none.

    Irreversible, so it is METADATA under §6 item 4 and is written on every row. A replay that
    rebuilds a prompt from captured arguments compares against this before it spends a token;
    a mismatch means the rebuild drifted (live state moved, a builder changed) and the replay
    would be asking a different question than the one logged.
    """
    if not system:
        return ""
    import hashlib
    return hashlib.sha256(system.encode("utf-8", "replace")).hexdigest()


def _capture_replay(decision_id: str, site: str, question: str, wire: list[dict],
                    provider: LLMProvider, prompt_fingerprint: str, replay_args: dict,
                    *, trace_id: str = "") -> None:
    """Emit the arguments that rebuild this decision's prompt — only while a window is open.

    Observation, never control: every failure is counted and swallowed, and nothing here can
    change what the turn does. `session_log.capture_replay` returns ``{}`` unless an operator's
    capture window is open, so by default this writes NOTHING and spends nothing.

    A capture that cannot be written is COUNTED rather than dropped silently — A5's concern
    about this exact seam. `session_log.emit` discards an event with no trace (explicit or
    ambient), and the analyst passes an empty `trace_id`, so this is a real loss path rather
    than a hypothetical one, and an operator should be able to see its size.
    """
    try:
        from aughor.obs import session_log
        captured = session_log.capture_replay({
            **replay_args,
            "question": question,
            # The roster in SENT order, full schemas. `options` on the decision row keeps only
            # sorted names, and a tool whose description interpolates live state changes the
            # input while its name stays identical.
            "wire": json.dumps(wire, ensure_ascii=False, sort_keys=False),
        })
        if not captured:
            return  # no window open — the expected, default case, and not a loss
        from aughor import telemetry as _tel
        if not (trace_id or _tel.current_trace_id()):
            from aughor.kernel.errors import tolerate
            tolerate(RuntimeError("no trace to attach a replay capture to"),
                     "a replay capture with no trace cannot be emitted; the decision still stands",
                     counter="learning.replay_capture.no_trace")
            return
        session_log.emit(
            session_log.DECISION_REPLAY, name=site, trace_id=trace_id,
            provider=str(getattr(provider, "backend", "") or ""),
            model=str(getattr(provider, "model", "") or ""),
            payload={
                **captured,
                "decision_id": decision_id,
                "site": site,
                "prompt_fingerprint": prompt_fingerprint,
                "role": str(getattr(provider, "role", "") or ""),
                "requested_temperature": _REQUESTED_TEMPERATURE,
            })
    except Exception as exc:  # noqa: BLE001 — observation must never fail the observed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a replay capture that failed leaves the decision recorded",
                 counter="learning.replay_capture")


def _history_chars(history: list[dict]) -> int:
    """Characters of prior conversation re-sent on this turn. Measured BEFORE the new
    exchange is appended, so it is what the model was actually shown when it decided."""
    return sum(len(str(m.get("content") or "")) for m in history)


def _exchange(call, content: str) -> list[dict]:
    """The messages that record one step in the conversation.

    With a tool call, that is the assistant message echoing it plus the `role="tool"`
    result answering it: an OpenAI-compatible backend rejects a tool message that
    answers nothing, so a loop that sends only results fails on the second turn.

    WITHOUT one — the model wrote arguments that would not parse, or said nothing at
    all — the feedback goes back as a plain USER message. The obvious alternative,
    inventing an assistant tool call for the result to answer, writes a function call
    into the transcript that the model never made. That is harmless on most backends
    and fatal on Gemini, which requires every function call it is shown to carry the
    reasoning signature it issued (see `ToolCall.extra_content`) and refuses the whole
    request when one cannot.
    """
    if call is None:
        return [{"role": "user", "content": content}]

    call_id = getattr(call, "id", "") or "call_1"
    name = getattr(call, "name", "") or "unknown"
    arguments = json.dumps(getattr(call, "arguments", {}) or {})
    echoed: dict = {"id": call_id, "type": "function",
                    "function": {"name": name, "arguments": arguments}}
    # Handed back verbatim and never read: this is the vendor's own bookkeeping, and
    # the next request is refused without it.
    extra = getattr(call, "extra_content", None)
    if extra:
        echoed["extra_content"] = extra
    return [
        {"role": "assistant", "content": None, "tool_calls": [echoed]},
        {"role": "tool", "tool_call_id": call_id, "content": content},
    ]


#: What a `step` event keeps of a tool's result by field. Work artifacts (§3.47's lawful
#: lane): the statement, its count, its error, which guards fired — stored always. The
#: rest of a result (rows, prose, the model's arguments) is payload: an excerpt only, and only
#: while a capture window is open.
_STEP_RESULT_EXCERPT = 400
_STEP_ARGS_CAP = 2000


def _emit_step(index: int, step: LoopStep, *, result: Any, elapsed_ms: Optional[float],
               site: str, conn_id: str, trace_id: str) -> None:
    """TJ-2 — one `step` event per loop step, from the one seam every loop passes.

    The session log drops an event with no trace, so a loop run outside a bound run
    (a bare unit test, a script) writes nothing and costs nothing. Best-effort like every
    observation: a step that could not be recorded still happened."""
    try:
        from aughor.obs import prompt_window, session_log

        r = result if isinstance(result, dict) else {}
        guards = []
        for receipt in (r.get("guard_receipts") or []):
            if isinstance(receipt, dict):
                guards.append(str(receipt.get("guard") or receipt.get("pattern") or "")[:80])
        row_count = r.get("row_count")
        if row_count is None and isinstance(r.get("rows"), list):
            row_count = len(r["rows"])
        payload: dict[str, Any] = {
            "index": index, "site": site, "tool": step.tool, "ok": step.ok,
            "sql": str(r.get("sql") or "")[:4000],
            "error": (str(r.get("error") or "") if step.ok else str(step.detail or ""))[:1000],
            "guards": guards, "result_chars": step.result_chars,
            "captured": False,
        }
        # The payload fields, by the lawful lane: only under an open capture window. The
        # window is not consumed here — its budget counts MODEL calls, and a step is not one.
        if prompt_window.active():
            payload["captured"] = True
            payload["arguments"] = _as_text(step.arguments)[:_STEP_ARGS_CAP]
            payload["result_excerpt"] = (_as_text(result) if result is not None
                                        else str(step.detail or ""))[:_STEP_RESULT_EXCERPT]
        session_log.emit(session_log.STEP, name=step.tool, trace_id=trace_id or "",
                         ok=step.ok, duration_ms=elapsed_ms, conn_id=conn_id or None,
                         row_count=(int(row_count) if isinstance(row_count, (int, float)) else None),
                         payload=payload)
    except Exception as exc:  # noqa: BLE001 — observation must never fail the observed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a step that could not be recorded still happened; the turn goes on",
                 counter="tool_loop.step_event")


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str)
    except (TypeError, ValueError):
        return str(result)
