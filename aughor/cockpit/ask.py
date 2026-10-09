"""A cockpit from an area a person names, and a change to one they keep, asked for in words
(Arc CT, CT-9; ROADMAP §3.50, §6 item 36(j); the canvas, docs/COCKPIT_CANVAS_2026-10-08.md).

In the Briefing a person says what the cockpit is for — "returns", "pricing and discounts" —
and a model drafts it. Not in a chat: the canvas is for investigation, and a cockpit is not an
answer. The model is given ONE tool, the drafting tool bound to the cockpit, and a budget of a
few steps. It reads what the connection may make a cockpit of, drafts, repairs what is refused,
and stops. What comes back is one staged proposal the person keeps or not.

Since the canvas the same door takes a change to a cockpit that stands — "add the finding about
returns by category", "make the net sales card bigger", "take my note off", "share this with
the sales team" — as an edit against the version on screen, or a publish. A note's words and
an image are never the model's: it may move, resize or take off either, and nothing else.

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
#: The longest change a person may ask for in words.
MAX_WORDS = 400

SYSTEM = (
    "You draft ONE cockpit for a person's Briefing, for the area of the business they name. "
    "Call draft_cockpit with op options first. Then call it with op new: the whole spec, and the "
    "cards it creates. Title the cockpit after the area, in the person's words. Choose only records "
    "that bear on the area. When nothing the connection offers measures it, draft nothing and say "
    "so in one sentence. When a draft is refused, repair every point and draft again. When one is "
    "staged, stop."
)

SYSTEM_EDIT = (
    "You change ONE cockpit a person keeps, exactly as they ask in words, and nothing else. "
    "Call draft_cockpit with op options first: it returns the cockpit as it stands, the cards the "
    "person has, what a new card may be made of, and who the cockpit may be published to. Then call "
    "it ONCE with what the words ask for: op edit, with RFC 6902 operations against the cockpit as it "
    "stands and the cards to create if they ask for a figure the cockpit lacks — or op publish, with "
    "the group or role they name. A note or an image on the cockpit is the person's: move it, give it "
    "a size or take it off when asked; never add one, write one or choose one. An element's size is "
    'one of small, wide, tall, large, full, hero; "bigger" is the next of these. '
    "When what they ask cannot be done with what the cockpit may be made of, draft nothing and say "
    "so in one sentence. When a draft is refused, repair every point and draft again. When one is "
    "staged, stop."
)


def _run(home: Home, system: str, ask: str, *, said: str, schema: Optional[str], provider: Any,
         site: str, nothing: str) -> dict:
    """Run the model once with the drafting tool bound to ``home``. Returns what became of it —
    ``staged`` with the proposal, or not, with the reasons as sentences."""
    from aughor.agent.cockpit_tool import drafting_tool
    from aughor.agent.tool_loop import ToolSpec, run_tool_loop

    if provider is None:
        from aughor.agent.converse_tools import binding_calls_tools
        if not binding_calls_tools():
            return _not("The model this install drafts with cannot call tools, so it cannot draft a "
                        "cockpit. Choose one that can in the model settings.")
        from aughor.llm.provider import get_provider
        provider = get_provider("coder")

    staged: list[dict] = []
    results: list[dict] = []
    tool = drafting_tool(home, said=said, schema=schema,
                         emit=lambda kind, payload: staged.append(payload) if kind == "proposal_staged" else None)

    def run(args: dict) -> dict:
        out = tool.run(args)
        if (args or {}).get("op") in ("new", "edit", "publish"):
            results.append(out if isinstance(out, dict) else {})
        return out

    result = run_tool_loop(
        provider, system, ask,
        [ToolSpec(name=tool.name, description=tool.description, parameters=tool.parameters, run=run)],
        max_steps=MAX_STEPS, conn_id=home.connection_id, site=site)

    rounds = len(results)
    if staged:
        last = next((r for r in reversed(results) if r.get("staged")), {})
        return {"staged": True, "proposal_id": staged[-1]["proposal_id"], "cockpit_id": home.cockpit_id,
                "summary": str(last.get("summary") or ""), "rounds": rounds,
                "stop_reason": result.stop_reason, "sentences": []}

    refused = list((results[-1] if results else {}).get("refused") or [])
    said_ = (result.answer or "").strip()
    from aughor.cockpit.validate import stated_figures
    if said_ and not stated_figures(said_):
        refused = [said_[:400], *refused] if not refused else refused
    if not refused:
        refused = [nothing]
    return {"staged": False, "proposal_id": "", "cockpit_id": "", "summary": "", "rounds": rounds,
            "stop_reason": result.stop_reason, "sentences": refused}


def draft_for_area(connection_id: str, owner: str, area: str, *, schema: Optional[str] = None,
                   provider: Any = None) -> dict:
    """Run the model once for this area. Returns what became of it — ``staged`` with the
    proposal and the cockpit it would be, or not, with the reasons as sentences."""
    area = " ".join((area or "").split())[:MAX_AREA]
    if not area:
        return _not("Name the area this cockpit is for — returns, pricing, marketing.")
    home = Home(connection_id, owner, new_id(area))
    return _run(home, SYSTEM, f"Draft a cockpit for this area: {area}", said=area, schema=schema,
                provider=provider, site="cockpit.draft",
                nothing="The model drafted no cockpit for this area, and gave no reason.")


def edit_in_words(connection_id: str, owner: str, cockpit_id: str, words: str, *, schema: Optional[str] = None,
                  provider: Any = None) -> dict:
    """Run the model once for a change to the cockpit ``cockpit_id`` the person keeps, as they ask
    for it in words. What comes back is a staged edit or publish, or the reasons none was."""
    from aughor.cockpit import versions
    words = " ".join((words or "").split())[:MAX_WORDS]
    if not words:
        return _not("Say what to change — add a finding, move a card, make one bigger, share it with a team.")
    home = Home(connection_id, owner, cockpit_id)
    live = versions.latest(home)
    if live is None or live["retired"] or not live.get("spec"):
        return _not("There is no cockpit here to change.")
    title = versions.title_of(live["spec"]) or cockpit_id
    return _run(home, SYSTEM_EDIT, f'Of their cockpit "{title}", the person asks: {words}', said=words,
                schema=schema, provider=provider, site="cockpit.edit",
                nothing="The model drafted no change for this, and gave no reason.")


def _not(sentence: str) -> dict:
    return {"staged": False, "proposal_id": "", "cockpit_id": "", "summary": "", "rounds": 0,
            "stop_reason": "", "sentences": [sentence]}
