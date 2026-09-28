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

2. **What only the platform knows** — whether a card the spec places is in this canvas, and,
   for a spec a MODEL wrote, whether a title states a figure. Those are checked here.

**The numerals law is for text a model wrote.** A person who names a section "Top 1000
accounts" has said so in their own name, and a canvas called "Store 4521" is a canvas's name.
The first cut held every title to the law, whoever wrote it: a cockpit started from a canvas
whose name held a number was refused for "stating a figure" — found by a test that failed one
run in six, because its canvas names were random. ``model_written`` defaults to True, so a
caller that forgets to say gets the strict reading.

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
from typing import Any, Callable, Iterable, Optional

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


def grammar() -> Optional[str]:
    """What the writer of a cockpit is told, as the web writes it from its own catalog — or
    None when the rules cannot run. The server keeps no copy (CT-5)."""
    out, _why = _run({"op": "grammar"})
    text = (out or {}).get("text")
    return text if isinstance(text, str) and text else None


@dataclass(frozen=True)
class Edited:
    """What became of an edit. ``spec`` is the edited spec when ``status`` is ``accepted``,
    and None otherwise: a refused edit leaves nothing behind, and one that could not be
    applied is not one that applied."""
    status: str
    spec: Optional[dict] = None
    sentences: tuple[str, ...] = ()

    @property
    def applied(self) -> bool:
        return self.status == ACCEPTED


def apply_patches(spec: Any, patches: Any) -> Edited:
    """Apply RFC 6902 operations to ``spec``, strictly and all or nothing (CT-5). The result
    is NOT checked here; the caller checks it as it would any spec."""
    try:
        json.dumps([spec, patches])
    except (TypeError, ValueError) as exc:
        return Edited(REFUSED, sentences=(f"The edit is not JSON: {exc}.",))
    out, why = _run({"op": "patch", "spec": spec, "patches": patches})
    if out is None:
        return Edited(NOT_CHECKED, sentences=(
            f"The edit could not be applied: {why}. Nothing is changed unchecked.",))
    issues = out.get("issues")
    if not isinstance(out.get("ok"), bool) or not isinstance(issues, list):
        return Edited(NOT_CHECKED, sentences=(
            "The edit could not be applied: the rules answered without a verdict. "
            "Nothing is changed unchecked.",))
    if not out["ok"] or not isinstance(out.get("spec"), dict):
        said = tuple(str(i.get("message", "")) for i in issues if isinstance(i, dict))
        return Edited(REFUSED, sentences=said or ("The edit was refused and no reason was given.",))
    return Edited(ACCEPTED, spec=out["spec"])


def stated_numerals(text: str) -> list:
    """The figures a piece of reader text states, by the numerals law's own reading
    (``explorer/grounding.py``): a magnitude or a percentage. A year, a rank and a small count
    are not claims about the data, there as here."""
    return [n for n in extract_numerals(text) if n.enforce or n.suffix == "%"]


def stated_figures(text: str) -> list[str]:
    """:func:`stated_numerals`, as the reader saw them written."""
    return [n.text for n in stated_numerals(text)]


def unknown_card(name: str, how: str) -> str:
    """What is said of a card a spec names and the canvas does not hold. ``how`` is "placed"
    or "read" — a ``Card`` places it, or a condition reads its status."""
    if how == "read":
        return f'A condition reads the status of the card "{name}", which this canvas does not hold.'
    return f'The cockpit places the card "{name}", which this canvas does not hold.'


def check_spec(spec: Any, *, known_cards: Iterable[str], model_written: bool = True,
               say_unknown: Optional[Callable[[str, str], str]] = None) -> SpecVerdict:
    """Accept ``spec`` whole or refuse it whole. ``known_cards`` are the ids of the cards this
    canvas holds, plus any the same proposal is about to create. ``model_written`` says whose
    words the titles are: a model's are held to the numerals law, a person's are their own.

    ``say_unknown`` writes the sentence for a card the canvas does not hold. The default is
    for a spec a person hands in. A draft has more to say — what it does create, and how the
    card could be created — and says it itself (``aughor/cockpit/propose.py``)."""
    say_unknown = say_unknown or unknown_card
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
    known = {str(c) for c in known_cards}
    if not out["valid"]:
        # A refusal names every fault it can (CT-5). The rules hand back what they read from
        # the elements that were sound, and what only the platform knows is said of that, in
        # the same refusal — or a writer would learn of a card the canvas does not hold only
        # after repairing everything else.
        said = [str(i.get("message", "")) for i in issues if isinstance(i, dict)]
        seen = out.get("seen") if isinstance(out.get("seen"), dict) else {}
        said += _platform_says(seen, known, model_written, say_unknown)
        return SpecVerdict(REFUSED, tuple(said) or ("The rules refused the spec and gave no reason.",))

    sentences = _platform_says(out, known, model_written, say_unknown)
    if sentences:
        return SpecVerdict(REFUSED, tuple(sentences))
    return SpecVerdict(ACCEPTED, (), tuple(str(c) for c in out.get("cards") or []))


def _platform_says(read: dict, known: set[str], model_written: bool,
                   say_unknown: Callable[[str, str], str]) -> list[str]:
    """What only the platform knows of what the rules read: a card the canvas does not hold,
    and — of text a model wrote — a title that states a figure."""
    # A caller's `say_unknown` may answer "" for a card it has already spoken of.
    said = [say_unknown(str(card), "placed") for card in read.get("cards") or [] if str(card) not in known]
    said += [say_unknown(str(card), "read") for card in read.get("stateCards") or []
             if str(card) not in known]
    sentences: list[str] = [s for s in said if s]
    for t in (read.get("texts") or []) if model_written else []:
        text = str(t.get("text", ""))
        figures = stated_figures(text)
        if figures:
            sentences.append(
                f'The {t.get("prop")} of "{t.get("elementKey")}" reads "{text}", which states a figure '
                f'({", ".join(figures)}). In a cockpit a figure belongs to a card, where it is measured.')
    return sentences


def check_spec_for_canvas(spec: Any, canvas_id: str, *, also_known: Iterable[str] = (),
                          model_written: bool = True,
                          say_unknown: Optional[Callable[[str, str], str]] = None) -> SpecVerdict:
    """:func:`check_spec` against the cards this canvas holds in the card store.
    ``also_known`` names the cards the same proposal will create on approval."""
    from aughor.dashboard.store import list_cards
    held = {c.id for c in list_cards(scope="canvas", scope_ref=canvas_id)}
    return check_spec(spec, known_cards=held | {str(c) for c in also_known},
                      model_written=model_written, say_unknown=say_unknown)
