"""The cockpit's validator (Arc CT, CT-2) — a spec is accepted whole or refused whole, with
sentences (AV-0's law, ROADMAP §3.11).

Two halves, and the split is by who can know:

1. **What the spec says on its own** — its shape, the props of each component, what a
   condition may read, and the refusals (``watch``, ``on``, an expression in a prop, a state
   the spec seeds beyond the open tab). These are checked by the web's OWN rules,
   ``web/lib/cockpit/rules.ts``, bundled by ``npm run build:cockpit-validate`` into
   ``validate.bundle.mjs`` beside this module and run as a node subprocess — the arrangement
   ``export/echarts.py`` uses for charts, for the same reason: the server checks a spec with
   the function the browser draws it with, so the two cannot come to disagree.

2. **What only the platform knows** — whether a card the spec places is in this canvas, and
   whether a title states a figure. Those are checked here.

**This gate fails CLOSED.** The chart renderer falls back to a table when node is missing; a
validator that fell back to "accepted" would be no validator. When the rules cannot run, the
verdict is ``not_checked`` with the reason, and ``accepted`` is False.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from aughor.explorer.grounding import extract_numerals
from aughor.kernel.errors import tolerate

_BUNDLE = Path(__file__).with_name("validate.bundle.mjs")
_TIMEOUT_S = 20

ACCEPTED = "accepted"
REFUSED = "refused"
NOT_CHECKED = "not_checked"


@dataclass(frozen=True)
class SpecVerdict:
    """What the validator decided. ``accepted`` is True for ``ACCEPTED`` and for nothing else:
    a spec that could not be checked is not a spec that passed."""
    status: str
    sentences: tuple[str, ...] = ()
    #: The card ids the spec places, in its own order. Empty unless accepted.
    cards: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.status == ACCEPTED

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "accepted": self.accepted,
                "sentences": list(self.sentences), "cards": list(self.cards)}


def _node_bin() -> Optional[str]:
    return os.environ.get("AUGHOR_NODE_BIN") or shutil.which("node")


def _run(payload: dict[str, Any]) -> tuple[Optional[dict], str]:
    """Run the bundle once. Returns ``(output, "")``, or ``(None, why it could not run)``."""
    node = _node_bin()
    if not node:
        return None, "node was not found on this machine"
    if not _BUNDLE.exists():
        return None, f"{_BUNDLE.name} is missing; build it with `npm run build:cockpit-validate`"
    try:
        proc = subprocess.run(
            [node, str(_BUNDLE)], input=json.dumps(payload).encode("utf-8"),
            capture_output=True, timeout=_TIMEOUT_S,
        )
        if proc.returncode != 0:
            said = proc.stderr.decode("utf-8", "replace").strip()[:300]
            return None, f"the rules exited with {proc.returncode}" + (f": {said}" if said else "")
        out = json.loads(proc.stdout.decode("utf-8"))
        if not isinstance(out, dict):
            return None, "the rules answered with something that is not an object"
        return out, ""
    except Exception as exc:
        tolerate(exc, "the cockpit's rules could not run; the spec is NOT accepted",
                 counter="cockpit.validator_unavailable")
        return None, f"{type(exc).__name__}: {exc}"[:300]


def _not_checked(why: str) -> SpecVerdict:
    return SpecVerdict(NOT_CHECKED, (
        f"The cockpit's rules could not run: {why}. Nothing is accepted unchecked.",))


def vocabulary() -> Optional[dict]:
    """The catalog's vocabulary as the web declares it — components, tones, statuses, limits —
    or None when the rules cannot run. The server reads it; it does not keep a second copy."""
    out, _why = _run({"op": "vocabulary"})
    return out


def _stated_figures(text: str) -> list[str]:
    """The figures a piece of reader text states, by the numerals law's own reading
    (``explorer/grounding.py``): a magnitude or a percentage. A year, a rank and a small count
    are not claims about the data, there as here."""
    return [n.text for n in extract_numerals(text) if n.enforce or n.suffix == "%"]


def check_spec(spec: Any, *, known_cards: Iterable[str]) -> SpecVerdict:
    """Accept ``spec`` whole or refuse it whole. ``known_cards`` are the ids of the cards this
    canvas holds, plus any the same proposal is about to create."""
    try:
        json.dumps(spec)
    except (TypeError, ValueError) as exc:
        return SpecVerdict(REFUSED, (f"The spec is not JSON: {exc}.",))

    out, why = _run({"op": "check", "spec": spec})
    if out is None:
        return _not_checked(why)
    issues = out.get("issues")
    if not isinstance(out.get("valid"), bool) or not isinstance(issues, list):
        return _not_checked("the rules answered without a verdict")
    if not out["valid"]:
        said = tuple(str(i.get("message", "")) for i in issues if isinstance(i, dict))
        return SpecVerdict(REFUSED, said or ("The rules refused the spec and gave no reason.",))

    known = {str(c) for c in known_cards}
    placed = [str(c) for c in out.get("cards") or []]
    sentences: list[str] = []
    for card in placed:
        if card not in known:
            sentences.append(f'The cockpit places the card "{card}", which this canvas does not hold.')
    for card in out.get("stateCards") or []:
        if str(card) not in known:
            sentences.append(
                f'A condition reads the status of the card "{card}", which this canvas does not hold.')
    for t in out.get("texts") or []:
        text = str(t.get("text", ""))
        figures = _stated_figures(text)
        if figures:
            sentences.append(
                f'The {t.get("prop")} of "{t.get("elementKey")}" reads "{text}", which states a figure '
                f'({", ".join(figures)}). In a cockpit a figure belongs to a card, where it is measured.')
    if sentences:
        return SpecVerdict(REFUSED, tuple(sentences))
    return SpecVerdict(ACCEPTED, (), tuple(placed))


def check_spec_for_canvas(spec: Any, canvas_id: str, *,
                          also_known: Iterable[str] = ()) -> SpecVerdict:
    """:func:`check_spec` against the cards this canvas holds in the card store.
    ``also_known`` names the cards the same proposal will create on approval."""
    from aughor.dashboard.store import list_cards
    held = {c.id for c in list_cards(scope="canvas", scope_ref=canvas_id)}
    return check_spec(spec, known_cards=held | {str(c) for c in also_known})
