"""One answer to what can be said of a source's days, and the only place that words it.

A source's lag was read everywhere as "it settles after N days". That is one of four things:

    unknown   it has not been read for long enough to say
    settles   its days stop changing, N days after they end, and that was measured
    moving    a table was still changing at the oldest age read: N is how far behind it is read, a floor, not a lag
    rewrites  old days keep changing: it rewrites its history at each refresh, and no age will ever settle

Measured 2026-11-04, every row across one refresh: a source redrawn whole at each refresh was being told to readers,
to the model and to other agents as one that "settles after 29 days". Every surface now reads this answer, which is
derived only from a source's own readings (`store.connection_lag`), so a source connected tomorrow gets the same words
from its own behaviour. No connection is named here, and none may be.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

UNKNOWN, SETTLES, MOVING, REWRITES = "unknown", "settles", "moving", "rewrites"


def _days(n: int) -> str:
    return f"{n} day{'s' if n != 1 else ''}"


def _names(tables: tuple[str, ...]) -> str:
    return " and ".join(filter(None, [", ".join(tables[:-1]), tables[-1]])) if tables else "a table"


def _it(tables: tuple[str, ...]) -> str:
    return "it" if len(tables) <= 1 else "them"


@dataclass(frozen=True)
class SettlingAnswer:
    kind: str = UNKNOWN
    days: Optional[int] = None         # how far behind it is read: a measured lag only when it `settles`
    moving: tuple[str, ...] = ()       # every table not seen to stop changing, the ones in `rewrites` among them
    rewrites: tuple[str, ...] = ()     # the tables whose old days keep changing
    horizon: int = 0                   # the oldest age a moving table has been read at; 0 when that is not known

    @property
    def never_settled(self) -> bool:
        """Nothing it holds has been seen to stop changing, so nothing it holds can be called settled."""
        return self.kind in (MOVING, REWRITES)

    def _only_moving(self) -> tuple[str, ...]:
        return tuple(t for t in self.moving if t not in self.rewrites)

    def _still_changing(self, tables: tuple[str, ...]) -> str:
        one = len(tables) <= 1
        age = f"{_days(self.horizon)} after a day ended" if self.horizon else "at the oldest age read"
        return (f"{_names(tables)} {'was' if one else 'were'} still changing {age} and {'has' if one else 'have'} not been "
                "seen to stop")

    def says(self) -> str:
        """What is true of this source, for a reader or a model."""
        if self.kind == REWRITES:
            one, them = len(self.rewrites) <= 1, _it(self.rewrites)
            said = (f"This source rewrites its history at each refresh: {_names(self.rewrites)} {'changes' if one else 'change'} "
                    f"at every age, so no day in {them} settles and an older range can read lower just for being older.")
            others = self._only_moving()
            return said + (f" {self._still_changing(others)}, so figures read from {_it(others)} may still move." if others else "")
        if self.kind == MOVING:
            return f"{self._still_changing(self.moving)}, so figures read from {_it(self.moving)} may still move."
        if self.kind == SETTLES:
            return f"A day's numbers stop changing {_days(self.days or 0)} after it ends, which the platform measured."
        return "The platform has not read this source for long enough to know when its numbers settle."

    def clause(self) -> str:
        """The same, as a clause of a longer sentence; "" when nothing is known to say. It names its tables: "it", in
        someone else's sentence, reads as whatever that sentence was about."""
        if self.kind == REWRITES:
            one = len(self.rewrites) <= 1
            said = (f"{_names(self.rewrites)} {'rewrites its' if one else 'rewrite their'} history at each refresh, so no day in "
                    f"{_it(self.rewrites)} settles")
            others = self._only_moving()
            return said + (f", and {self._still_changing(others)}" if others else "")
        if self.kind == MOVING:
            return self._still_changing(self.moving)
        if self.kind == SETTLES:
            return f"its numbers keep moving for {_days(self.days or 0)} after a day ends, learned from observation"
        return ""

    def for_agents(self) -> str:
        """What an agent answering about this source is told; "" when nothing is known."""
        if self.never_settled:
            return (f"{self.says()} Treat every figure read from {_it(self.moving)} as provisional, say so when you report it, "
                    "and do not read a difference against an earlier period as a move.")
        if self.kind == SETTLES:
            n = self.days or 0
            return (f"This source keeps restating its most recent days: a day's numbers go on changing for {_days(n)} after "
                    f"it ends (learned from observation). Treat totals for the last {_days(n)} as provisional and say so "
                    "when you report them; prefer settled days for any comparison.")
        return ""

    def wait_words(self) -> str:
        """What a date pushed back by ``days`` is waiting for, after "plus"."""
        n = self.days or 0
        if self.never_settled:
            return f"the {_days(n)} this source is read behind (it has not been seen to settle)"
        return f"the connection's learned settling lag of {_days(n)}"

    def about(self, reads: Any) -> "SettlingAnswer":
        """The answer for just what ``reads`` reads (a definition, or ``{"sql": ...}``): a sibling table's behaviour says
        nothing of a figure that does not touch it. A statement whose tables cannot be read gets the whole source's."""
        from aughor.semantic.metric_time import bare_name, tables_touched

        read = tables_touched(reads)
        if not self.never_settled or not read:
            return self
        moving = tuple(t for t in self.moving if bare_name(t) in read)
        rewrites = tuple(t for t in self.rewrites if bare_name(t) in read)
        kind = REWRITES if rewrites else MOVING if moving else UNKNOWN
        return SettlingAnswer(kind, self.days, moving, rewrites, self.horizon)

    def as_block(self) -> dict:
        return {"kind": self.kind, "days": self.days, "tables": list(self.moving), "says": self.says()}


def answer_from(lag: Optional[dict]) -> SettlingAnswer:
    """The answer a `store.connection_lag` reading gives."""
    lag = lag or {}
    days, rewrites = lag.get("days"), tuple(lag.get("rewrites") or ())
    moving = tuple(lag.get("still_moving") or ())
    moving += tuple(t for t in rewrites if t not in moving)
    horizon = int(lag.get("horizon") or 0)
    if rewrites:
        return SettlingAnswer(REWRITES, days, moving, rewrites, horizon)
    if moving:
        return SettlingAnswer(MOVING, days, moving, (), horizon)
    if lag.get("source") == "learned" and days is not None:
        return SettlingAnswer(SETTLES, days, (), (), horizon)
    return SettlingAnswer(UNKNOWN, days, (), (), horizon)


def answer_of_block(block: Optional[dict]) -> SettlingAnswer:
    """The answer a range's block carries; one kept before blocks carried it reads from what it does hold."""
    block = block or {}
    return answer_from({"days": block.get("lag_days"), "source": block.get("lag_source"), "horizon": block.get("horizon"),
                        "still_moving": block.get("still_moving"), "rewrites": block.get("rewrites")})


def settling_answer(connection_id: Optional[str]) -> SettlingAnswer:
    """The answer for a connection. An unreadable store answers "unknown", which claims nothing."""
    if not connection_id:
        return SettlingAnswer()
    try:
        from aughor.settling.store import connection_lag
        return answer_from(connection_lag(connection_id))
    except Exception as exc:  # noqa: BLE001 — not known is said, never guessed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "how this source settles could not be read; it is said to be not yet known", counter="settling.answer")
        return SettlingAnswer()
