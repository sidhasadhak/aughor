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
    """
    by_name = {t.name: t for t in tools}
    wire = [t.as_wire() for t in tools]
    budget = max_steps if max_steps is not None else _budget(provider)
    history: list[dict] = []
    steps: list[LoopStep] = []
    # One nudge per turn. A model that goes silent twice is not stalling on a
    # formatting slip, and re-asking would spend the whole budget on silence.
    nudged = False

    def _record(step: LoopStep) -> None:
        """Append and announce, together. Three branches record a step and all three
        must reach the caller — a progress seam that only reports the SUCCESSFUL
        branch would show a turn recovering from nothing."""
        steps.append(step)
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

        try:
            result = spec.run(call.arguments)
            ok, payload = True, _as_text(result)
        except Exception as exc:
            # A tool that raises is a RESULT — "that query failed, here is why" is
            # something the model can act on. Letting it propagate would end the turn
            # and discard every step already paid for.
            logger.warning("tool_loop: %s raised (%s)", call.name, str(exc)[:200])
            ok, payload = False, f"{type(exc).__name__}: {exc}"
        _record(LoopStep(tool=call.name, arguments=call.arguments, ok=ok,
                         detail="" if ok else payload,
                         result_chars=len(payload),
                         prompt_chars=_history_chars(history)))
        history.extend(_exchange(call, payload))

    # Budget spent. The turn is not an error — it is an answer we did not reach, and
    # saying so plainly beats presenting a half-derived guess as a conclusion.
    return LoopResult(answer=None, steps=steps, stop_reason="budget")


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


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str)
    except (TypeError, ValueError):
        return str(result)
