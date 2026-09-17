"""HB-4 — the injection gate: a source kind reaches a PROMPT only with measured lift.

The law (§3.18, R4's lesson made structural): the only ablation of injected context
(R4, 2026-06-21) was a regression, and ON-0 lifted nothing until the framing did — so
each new source kind enters the prompt under its own harness arm and stays only with
measured lift, per kind. A source that does not lift is STORED AND SHOWN (the object
page, the arrivals door, the receipt), never injected.

``INJECTABLE_SOURCE_KINDS`` is therefore a closed constant, DEFAULT EMPTY, flipped only
by a change that cites a dated harness receipt (``evals/ablation_eval.py``'s ``notes``
arm writes one). While it is empty the block renders ``""`` and every prompt is
byte-identical to the day before this module existed — the flag-grid's Guard-1 shape,
by construction.
"""
from __future__ import annotations

from aughor.kernel.errors import tolerate

#: Source kinds allowed into prompts. EMPTY until a harness arm measures lift for a
#: kind on the ON-10 sets; the flip cites the dated results file in its diff. This is
#: the falsifier's resting state, not a stub.
INJECTABLE_SOURCE_KINDS: tuple[str, ...] = ()

#: The ranked block's budget when a kind ever graduates — deliberately small; context
#: is spent where it measured.
NOTES_BLOCK_BUDGET_CHARS = 1200


def ranked_notes_block(connection_id: str, question: str = "") -> str:
    """The ranked, stamped conversation-notes block for a prompt — ``""`` unless the
    conversation kind has GRADUATED (measured lift). Rendering is deterministic
    (aughor/hub/ranker.py); a failure degrades to empty, never an error."""
    if "conversation" not in INJECTABLE_SOURCE_KINDS:
        return ""
    try:
        from aughor.hub.adapters import conversation_note_pieces
        from aughor.hub.ranker import rank
        pieces = conversation_note_pieces(connection_id)
        if not pieces:
            return ""
        ranked = rank(pieces, budget_chars=NOTES_BLOCK_BUDGET_CHARS)
        if not ranked.kept:
            return ""
        return ("CONTEXT FROM PEOPLE (ranked; every line carries its provenance — weigh "
                "it by the stamp, and prefer measured numbers over said ones):\n"
                + ranked.rendered())
    except Exception as exc:
        tolerate(exc, "ranked notes block unavailable — the prompt goes on without it",
                 counter="hub.injection.notes_block")
        return ""
