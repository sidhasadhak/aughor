"""Rung 0 — telling the model a pack exists, before it has any reason to look.

The disclosure ladder had two rungs: `list_packs` (cheap descriptions) and `read_pack` (one
body). Both are TOOLS, so both require the model to already suspect a pack might help. It
never did.

**Measured on the live ledger, 2026-08-24:** 2,672 recorded tool calls across 72 converse
turns, every one of them named. `run_sql` 55, `propose_context_note` 1, `list_tables`,
`answer_question` — so platform tools are recorded when they fire. `list_packs`: **0**.
`read_pack`: **0**. Not rare. Never. A ladder whose first rung is only reachable by someone
who already knows it is there is not a ladder.

So rung 0 is unconditional: when a pack ACTIVE on this connection matches the question by
description, the prompt says so, as state — the same shape as VA-2's delegation roster
("these agents exist, here is what each is for"), and omitted entirely when nothing matches.

**It names the pack; it does not paste it.** The roadmap's own risk note for this
deliverable is prompt bloat — "a skill that adds 800 tokens and changes nothing is a
regression" — and the `duckdb-engine` prose is ~1,500 tokens. Injecting a body on every turn
to save a tool call would spend the budget the two-rung ladder exists to protect. A pointer
costs tens of tokens and leaves the fetch where it already works.
"""
from __future__ import annotations

from typing import Optional

#: Token overlap a pack's description needs before it is worth naming. One shared word is
#: noise ("data", "the"); two is a topic. Deliberately not tuned finer than the evidence
#: supports — there is no adoption data to tune against yet, because adoption was zero.
MIN_SCORE = 2.0

#: At most this many, best first. The cap is the cost control: a roster that grows with the
#: pack library turns a fixed prompt into a variable one.
MAX_NAMED = 2


def matching_packs(question: str, connection_id: str, packs: Optional[list] = None) -> list:
    """Active packs that apply to this connection AND match the question, best first."""
    from aughor.packs import scope as pack_scope
    from aughor.packs.intake import active_packs
    from aughor.packs.routing import score_pack, score_text

    pool = packs if packs is not None else active_packs()
    pool = pack_scope.filter_applicable(pool, connection_id)

    scored = []
    for pack in pool:
        # `score_pack` reads the STRUCTURED routing fields (intent_tags, domains, canonical
        # questions); `score_text` reads the description. Both, because neither is enough
        # alone: a pack with no questions.yaml has only its description, and a description
        # is a thin signal — measured, "why is my revenue column stored as a string?" scores
        # 0.0 against the one-line summary of a pack entirely about casting surprises. The
        # tags are the words a user TYPES; the description is the words we chose.
        text = " ".join(filter(None, (pack.manifest.name, " ".join(pack.manifest.domains),
                                      _description(pack))))
        score = max(score_pack(question, pack), score_text(question, text))
        if score >= MIN_SCORE:
            scored.append((score, pack))
    scored.sort(key=lambda s: (-s[0], s[1].id))
    return [pack for _score, pack in scored[:MAX_NAMED]]


def _description(pack) -> str:
    """The pack's own one-line description — the same rung-1 line `list_packs` advertises."""
    from aughor.agent.platform_tools import pack_description

    return pack_description(pack)


def disclosure_block(question: str, connection_id: str,
                     packs: Optional[list] = None) -> str:
    """The prompt block naming the matching packs, or '' when none match.

    Empty is the common case and the right one: a prompt that names a pack for every
    question teaches the model to ignore the line.
    """
    hits = matching_packs(question, connection_id, packs)
    if not hits:
        return ""
    lines = ["DOMAIN PACKS THAT MATCH THIS QUESTION — installed here, and not yet read:"]
    for pack in hits:
        summary = _description(pack)
        lines.append(f"- `{pack.id}` ({pack.manifest.name}): {summary}")
    lines.append("Call `read_pack` with one of those ids before answering if its subject "
                 "bears on the question. A pack is prose about a domain, not a claim about "
                 "this data — ground its advice in real columns before relying on it.")
    return "\n".join(lines)
