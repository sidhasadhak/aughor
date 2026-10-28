"""How complete an object read is (Arc ED, ED-6; ROADMAP §3.58).

An answer owes its reader whether it holds everything it was asked for, and what it left out. Aughor's object
doors carried one boolean, and on the query door it could not be true: every connection hands back at most
``db.connection.MAX_ROWS`` (500) rows, and the door said ``truncated`` only past 1,000 (measured 2026-10-24) — a cut
read reached its reader as complete. Here every object door says one typed thing, the same way:

* ``complete`` — every object or row the read asked for is here;
* ``truncated`` — the connection stopped at its cap: ``shown`` rows, and there are more;
* ``withheld`` — a row policy narrowed the objects this reader is shown, or a sensitive property was emptied
  (``withheld`` names the entities, ``masked`` the properties);
* ``refused`` — nothing was read: the door refused it, a cap among the reasons, said in ``said``.

``shown`` is how many came back, ``of`` how many there are when the door counted them (a listing's ``total``), and
``took_ms`` how long the read took. Withheld is said, never implied: an empty or a cut answer that does not say so
teaches its reader the data ends there.
"""
from __future__ import annotations

import time
from typing import Iterable, Optional

STATES = ("complete", "truncated", "withheld", "refused")


class Clock:
    """The time a read takes, from the door's first step to its answer."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def ms(self) -> int:
        return int(round((time.monotonic() - self._start) * 1000))


def cut(result) -> bool:
    """Whether a connection stopped a read at its cap: it counted more rows than it handed back. Every connector
    counts one past what it returns, or all of them, so this holds on each engine (`db/connection.py`)."""
    rows = len(getattr(result, "rows", None) or [])
    return int(getattr(result, "row_count", 0) or 0) > rows


def of_read(*, shown: int, took_ms: int, of: Optional[int] = None, truncated: bool = False,
            withheld: Iterable[str] = (), masked: Iterable[str] = (), refused: str = "",
            said: Iterable[str] = ()) -> dict:
    """One read's completeness. Precedence when more than one holds: refused, then truncated, then withheld — the
    lists say every one. ``said`` carries the door's own sentences for what it withheld (the row policies' words)."""
    entities = sorted(dict.fromkeys(str(e) for e in withheld if e))
    props = sorted(dict.fromkeys(str(p) for p in masked if p))
    words = [s for s in dict.fromkeys(str(s) for s in said if s)]
    if refused:
        state, lead = "refused", refused
    elif truncated:
        state, lead = "truncated", (f"the first {shown:,} rows — the connection hands back no more in one read, and "
                                    "there are more; narrow or group the query to read them all")
    elif entities or props:
        state, lead = "withheld", ""
    else:
        state, lead = "complete", ""
    if props and not words:
        words.append(f"{', '.join(props)} {'is' if len(props) == 1 else 'are'} withheld from you")
    return {"state": state, "shown": int(shown), "of": of, "withheld": entities, "masked": props,
            "said": "; ".join([lead, *words] if lead else words), "took_ms": int(took_ms)}


def refused(reason: str, clock: Clock) -> dict:
    return of_read(shown=0, took_ms=clock.ms(), refused=reason or "the read was refused")


def policy_words(graph, entity_ids: Iterable[str]) -> list[str]:
    """What each row policy that narrowed a read tells its reader (`ontology/security.rows_said`)."""
    from aughor.ontology.security import rows_said
    out = []
    for eid in entity_ids:
        entity = (graph.entities or {}).get(eid) if graph is not None else None
        said = rows_said(entity) if entity is not None else None
        if said:
            out.append(said)
    return out


def narrowed(entity) -> list[str]:
    """``[entity.id]`` when a row policy narrows this reader's objects of it, else ``[]``."""
    from aughor.ontology.security import rows_said
    return [entity.id] if entity is not None and rows_said(entity) else []


#: The contract's description of the field (`ontology/builder_doors.ontology_contract`), for a program to read.
SCHEMA = {
    "type": "object",
    "description": "How complete an object read is — on every object door's answer.",
    "required": ["state", "shown", "of", "withheld", "masked", "said", "took_ms"],
    "properties": {
        "state": {"enum": list(STATES), "description": "complete · truncated (the connection's cap, there are more) "
                                                       "· withheld (a row policy or a masked property) · refused"},
        "shown": {"type": "integer", "description": "the objects or rows this answer holds"},
        "of": {"anyOf": [{"type": "integer"}, {"type": "null"}],
               "description": "how many there are, when the door counted them; null when it did not"},
        "withheld": {"type": "array", "items": {"type": "string"},
                     "description": "the entities whose objects a row policy narrowed for this reader"},
        "masked": {"type": "array", "items": {"type": "string"},
                   "description": "the properties emptied for this reader"},
        "said": {"type": "string", "description": "the read's completeness in words; empty when complete"},
        "took_ms": {"type": "integer", "description": "how long the read took, in milliseconds"},
    },
}
