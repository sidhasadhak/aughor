"""A new cockpit from an area a person names (Arc CT, CT-9; ROADMAP §3.50, §6 item 36(j)).

In the Briefing a person says what the cockpit is for — "returns", "pricing and discounts" —
and a model drafts it. Not in a chat: the canvas is for investigation, and a cockpit is not an
answer. The model is given ONE tool, the drafting tool bound to the new cockpit, and a budget
of a few steps. It reads what the connection may make a cockpit of, drafts, repairs what is
refused, and stops. What comes back is one staged proposal the person keeps or not.

**Nothing the model writes reaches the person as fact.** When a draft is staged, what the
person reads is the platform's summary of it. When none is, they read the platform's reasons —
the last refusal's own sentences — and the model's words only if they state no figure.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.cockpit.home import Home, new_id

#: Steps the model may take: options, a draft, and repairs.
MAX_STEPS = 6
#: The longest area a person may name. It is read as the ask, and a limit is set only where
#: it names one.
MAX_AREA = 200

SYSTEM = (
    "You draft ONE cockpit for a person's Briefing, for the area of the business they name. "
    "Call draft_cockpit with op options first. Then call it with op new: the whole spec, and the "
    "cards it creates. Title the cockpit after the area, in the person's words. Choose only records "
    "that bear on the area. When nothing the connection offers measures it, draft nothing and say "
    "so in one sentence. When a draft is refused, repair every point and draft again. When one is "
    "staged, stop."
)


def draft_for_area(connection_id: str, owner: str, area: str, *, schema: Optional[str] = None,
                   provider: Any = None) -> dict:
    """Run the model once for this area. Returns what became of it — ``staged`` with the
    proposal and the cockpit it would be, or not, with the reasons as sentences."""
    from aughor.agent.cockpit_tool import drafting_tool
    from aughor.agent.tool_loop import ToolSpec, run_tool_loop

    area = " ".join((area or "").split())[:MAX_AREA]
    if not area:
        return _not("Name the area this cockpit is for — returns, pricing, marketing.")
    if provider is None:
        from aughor.agent.converse_tools import binding_calls_tools
        if not binding_calls_tools():
            return _not("The model this install drafts with cannot call tools, so it cannot draft a "
                        "cockpit. Choose one that can in the model settings.")
        from aughor.llm.provider import get_provider
        provider = get_provider("coder")

    home = Home(connection_id, owner, new_id(area))
    staged: list[dict] = []
    results: list[dict] = []
    tool = drafting_tool(home, said=area, schema=schema,
                         emit=lambda kind, payload: staged.append(payload) if kind == "proposal_staged" else None)

    def run(args: dict) -> dict:
        out = tool.run(args)
        if (args or {}).get("op") in ("new", "edit"):
            results.append(out if isinstance(out, dict) else {})
        return out

    result = run_tool_loop(
        provider, SYSTEM, f"Draft a cockpit for this area: {area}",
        [ToolSpec(name=tool.name, description=tool.description, parameters=tool.parameters, run=run)],
        max_steps=MAX_STEPS, conn_id=connection_id, site="cockpit.draft")

    rounds = len(results)
    if staged:
        last = next((r for r in reversed(results) if r.get("staged")), {})
        return {"staged": True, "proposal_id": staged[-1]["proposal_id"], "cockpit_id": home.cockpit_id,
                "summary": str(last.get("summary") or ""), "rounds": rounds,
                "stop_reason": result.stop_reason, "sentences": []}

    refused = list((results[-1] if results else {}).get("refused") or [])
    said = (result.answer or "").strip()
    from aughor.cockpit.validate import stated_figures
    if said and not stated_figures(said):
        refused = [said[:400], *refused] if not refused else refused
    if not refused:
        refused = ["The model drafted no cockpit for this area, and gave no reason."]
    return {"staged": False, "proposal_id": "", "cockpit_id": "", "summary": "", "rounds": rounds,
            "stop_reason": result.stop_reason, "sentences": refused}


def _not(sentence: str) -> dict:
    return {"staged": False, "proposal_id": "", "cockpit_id": "", "summary": "", "rounds": 0,
            "stop_reason": "", "sentences": [sentence]}
