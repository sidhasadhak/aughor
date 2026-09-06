"""SP-6 — one clip for every string Spotlight interpolates or relays.

Everything Spotlight reads is attacker-influenceable data (§3.11's seventh law):
automation names, agent names, trace questions, audit summaries are all free text
someone else authored. The tools quote them — that is their job — but a quoted
string must not be allowed to become a PARAGRAPH inside a summary the model is
told to repeat verbatim, and it must not blow the context budget. Clipping is not
sanitization (the model still reads the text as data; the red-team corpus tests
that posture) — it is the size cap that keeps a hostile or merely enormous name
from drowning the sentence it is quoted in.
"""
from __future__ import annotations

#: Interpolated identifiers (names, actors) — enough for any honest name.
NAME_CLIP = 80
#: Relayed free text (questions, audit summaries) — enough to recognise, not to host.
TEXT_CLIP = 200


def clip(value, limit: int = NAME_CLIP) -> str:
    """One line, at most ``limit`` chars, ellipsis when cut — never None."""
    s = " ".join(str(value or "").split())
    return s if len(s) <= limit else s[: max(1, limit - 1)] + "…"
