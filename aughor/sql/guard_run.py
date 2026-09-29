"""GM-4 (ROADMAP §3.49) — a guard that cannot run says so.

A value-domain or grain guard that could not read a statement — it did not parse the way the guard read it, or
the warehouse refused the guard's own probe — returned what a clean statement returns: no findings. The repair
loop, the receipt and the reader all took that for "checked, nothing wrong". Measured on theLook (BigQuery)
2026-09-29: on a backticked, project-qualified query — the spelling the model and the cards write there — the
join and filter guards ran NO statement and reported clean, and GM-3's receipt said the statement had passed
them.

A guard's run over one statement is a :class:`GuardRun`: what it found, and each part it could not check, with
the reason. ``unchecked`` is the house word for it (the fact check, the answer re-check and a metric's save use
it). The receipt says ``guarded:<guard>`` only when every part was checked; otherwise ``unchecked:<guard>``, and
the reasons ride the result as caveats.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: How much of a warehouse's error a reason carries — enough to name the cause, short enough for a caveat.
_WHY_CHARS = 160


def why(error: object) -> str:
    """An error, trimmed to one line a caveat can carry."""
    text = " ".join(str(error or "").split())
    return text if len(text) <= _WHY_CHARS else text[: _WHY_CHARS - 1] + "…"


@dataclass
class GuardRun:
    """One guard's run over one statement."""
    guard: str                                          # the guard's door name: "join-domain", "filter-domain", "grain"
    findings: list = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)  # one plain reason per part the guard could not check

    @property
    def door(self) -> str:
        """The receipt's word for this run — ``guarded`` only when nothing was left unchecked."""
        return f"{'unchecked' if self.unchecked else 'guarded'}:{self.guard}"

    def cleared(self, before: "GuardRun") -> bool:
        """Whether this run — over a repaired statement — confirms the repair: no findings, and nothing left
        unchecked that ``before`` had checked. A part that no run could check does not refuse the repair; a repair
        that made a checked part uncheckable, or that the guard could not read at all, is not one it confirmed."""
        return not self.findings and self._subjects() <= before._subjects()

    def _subjects(self) -> set[str]:
        """What each unchecked reason is about — the words before its first colon, so an engine's error text,
        which can differ between two runs of the same probe, never tells two runs apart."""
        return {reason.split(":", 1)[0] for reason in self.unchecked}

    def caveats(self) -> list[str]:
        """What the reader is told about each part that was not checked."""
        from aughor.db.doors import GUARDS
        name = GUARDS.get(self.guard, self.guard)
        return [f"{name} guard: not checked — {reason}" for reason in self.unchecked]
