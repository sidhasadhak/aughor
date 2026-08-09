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


@dataclass
class LoopResult:
    answer: Optional[str]
    steps: list[LoopStep] = field(default_factory=list)
    #: Why the loop ended: "answered" | "budget" | "no_answer".
    stop_reason: str = "answered"

    @property
    def used_tools(self) -> bool:
        return bool(self.steps)


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
) -> LoopResult:
    """Run one converse turn to an answer, or until the budget runs out.

    The loop is deliberately dumb about content: it dispatches what the model asked
    for, hands back what the tool returned, and asks again. Everything that makes an
    answer trustworthy lives inside the tools.
    """
    by_name = {t.name: t for t in tools}
    wire = [t.as_wire() for t in tools]
    budget = max_steps if max_steps is not None else _budget(provider)
    history: list[dict] = []
    steps: list[LoopStep] = []

    for _ in range(budget):
        turn: ToolTurn = provider.complete_with_tools(
            system, question, wire, history=history or None)

        if turn.malformed:
            # The model DID choose — it just wrote the arguments badly. Telling it so is
            # what lets it retry; silence would read as "the tool returned nothing".
            steps.append(LoopStep(tool="?", arguments={}, ok=False, detail=turn.malformed))
            history.extend(_exchange(None, f"Your tool arguments could not be parsed: "
                                           f"{turn.malformed}. Try again with valid JSON."))
            continue

        if not turn.chose_tool:
            return LoopResult(answer=turn.text, steps=steps, stop_reason="answered")

        call = turn.tool_call
        assert call is not None       # chose_tool is exactly this check
        spec = by_name.get(call.name)
        if spec is None:
            # A hallucinated tool name. Naming the real ones back is cheaper than a
            # wasted step, and the model almost always corrects on the next turn.
            offered = ", ".join(sorted(by_name)) or "(none)"
            steps.append(LoopStep(tool=call.name, arguments=call.arguments, ok=False,
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
        steps.append(LoopStep(tool=call.name, arguments=call.arguments, ok=ok,
                              detail="" if ok else payload))
        history.extend(_exchange(call, payload))

    # Budget spent. The turn is not an error — it is an answer we did not reach, and
    # saying so plainly beats presenting a half-derived guess as a conclusion.
    return LoopResult(answer=None, steps=steps, stop_reason="budget")


def _exchange(call, content: str) -> list[dict]:
    """The assistant/tool message pair that records one step in the conversation.

    The assistant message must echo the tool call the model made: an OpenAI-compatible
    backend rejects a `role="tool"` message that answers nothing, so a loop that sends
    only results fails on the second turn.
    """
    call_id = getattr(call, "id", "") or "call_1"
    name = getattr(call, "name", "") or "unknown"
    arguments = json.dumps(getattr(call, "arguments", {}) or {})
    return [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": call_id, "type": "function",
                         "function": {"name": name, "arguments": arguments}}]},
        {"role": "tool", "tool_call_id": call_id, "content": content},
    ]


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str)
    except (TypeError, ValueError):
        return str(result)
