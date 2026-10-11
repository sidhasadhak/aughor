"""Arc AP-6 — a changelog in words: what each kept version of a cockpit changed, said as a person reads it (ROADMAP §3.57;
docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.7, "a changelog in words from `changes`").

A version recorded which elements it added, removed or changed, by their keys, and History said "2 added · 1 changed".
A key is the spec's word, never the reader's. Here the two specs are read side by side and each change is said by what
the element is and what it names — "Added the map · distribution center", "Moved the note to Waiting", "Resized the
objects table · order", "Named the set Shipped late" — read from the versions the ledger already keeps, so every version
kept before this says its changes too. No model is asked.
"""
from __future__ import annotations

import json
from typing import Any, Optional

#: The most lines a version says; the rest is counted.
MAX_LINES = 4
#: A piece's room — changing only this is resizing.
_ROOM = frozenset({"size", "w", "h"})
#: The props that are a name a person reads, by the kinds whose they are: a section's or a tab's name, an image's
#: caption, a figure's label. A list's `title` or a timeline's `label` names a property, and changing it is set-up.
_NAMES = {"Cockpit": {"title"}, "Section": {"title"}, "Tab": {"label"}, "Image": {"caption"}, "Drawer": {"title"},
          "ObjectFigure": {"label"}, "ObjectChart": {"label"}, "ObjectSearch": {"label"}}


def _elements(spec: Any) -> dict:
    els = spec.get("elements") if isinstance(spec, dict) else None
    return els if isinstance(els, dict) else {}


def what(el: Any, sets: Optional[dict] = None, titles: Optional[dict] = None) -> str:
    """An element as a person reads it: "the section Waiting", "a note", "the map · distribution center" — a piece
    reading a set by the set's label, never its name in the spec, and a card by its title (``titles``, by card id)."""
    if not isinstance(el, dict):
        return "an element"
    kind, props = str(el.get("type") or ""), el.get("props") if isinstance(el.get("props"), dict) else {}
    label = ((sets or {}).get(props.get("set")) or {}).get("label") if props.get("set") else None
    if label:
        props = {**props, "set": label, "entity": None}
    if kind == "Cockpit":
        return "the cockpit"
    if kind == "Section":
        layout = props.get("layout")
        if layout and not props.get("title"):
            return {"columns": "a row of columns", "rows": "a stack of rows", "tabs": "a set of tabs"}.get(str(layout), "a layout")
        return f"the section {props['title']}" if props.get("title") else "a section"
    if kind == "Tabs":
        return "the tabs"
    if kind == "Tab":
        return f"the tab {props.get('label') or props.get('name') or ''}".strip()
    if kind == "Card":
        card = str(props.get("card") or "")
        return f"the card {(titles or {}).get(card) or card.replace('_', ' ')}".strip()
    if kind == "Note":
        return "a note"
    if kind == "Image":
        return f"the image {props['caption']}" if props.get("caption") else "an image"
    from aughor.cockpit import pieces
    if kind in pieces.PIECES:
        said = pieces.title_of(kind, props)
        return f"the {said[:1].lower()}{said[1:]}"
    return f"the {kind.lower()}" if kind else "an element"


def _parent(els: dict, key: str) -> tuple[str, int]:
    for k, el in els.items():
        kids = el.get("children") if isinstance(el, dict) else None
        if isinstance(kids, list) and key in kids:
            return k, kids.index(key)
    return "", -1


def _changed(b: dict, a: dict, sets: Optional[dict] = None, titles: Optional[dict] = None) -> Optional[str]:
    """How one element that stayed where it was changed — resized, renamed, set up anew or rearranged — or None when
    nothing a reader sees did."""
    bp = b.get("props") if isinstance(b.get("props"), dict) else {}
    ap = a.get("props") if isinstance(a.get("props"), dict) else {}
    differ = {k for k in set(bp) | set(ap) if bp.get(k) != ap.get(k)}
    if differ and differ <= _ROOM:
        return f"Resized {what(a, sets, titles)}"
    if differ and differ <= _NAMES.get(str(a.get("type") or ""), set()):
        return f"Renamed {what(b, sets, titles)} to {next(str(ap[k]) for k in sorted(differ) if ap.get(k))}" \
            if any(ap.get(k) for k in differ) else f"Took the name off {what(b, sets, titles)}"
    if differ:
        return f"Changed what {what(a, sets, titles)} shows" if a.get("type") != "Cockpit" else "Renamed the cockpit"
    if b.get("children") != a.get("children"):
        return f"Rearranged {what(a, sets, titles)}"
    return None


def _wiring(before: Any, after: Any, kind: str, noun: str) -> list[str]:
    b = (before or {}).get(kind) if isinstance(before, dict) else None
    a = (after or {}).get(kind) if isinstance(after, dict) else None
    b, a = (b if isinstance(b, dict) else {}), (a if isinstance(a, dict) else {})

    def label(defs: dict, name: str) -> str:
        d = defs.get(name)
        return str(d.get("label") or name) if isinstance(d, dict) else name
    out = [f"Named the {noun} {label(a, n)}" for n in a if n not in b]
    out += [f"Took off the {noun} {label(b, n)}" for n in b if n not in a]
    out += [f"Changed the {noun} {label(a, n)}" for n in a if n in b and
            json.dumps(a[n], sort_keys=True, default=str) != json.dumps(b[n], sort_keys=True, default=str)]
    return out


def said(before: Any, after: Any, titles: Optional[dict] = None) -> list[str]:
    """What ``after`` changed of ``before``, a line a change, the largest first: what was added, taken off, moved or
    set up, then what was resized, then the sets and values. At most `MAX_LINES`, the rest counted — "and 3 more".
    ``titles`` names the cards the two specs place, by card id."""
    bels, aels = _elements(before), _elements(after)
    if not bels and aels:
        return ["Started the cockpit"]
    bsets = (before.get("sets") if isinstance(before, dict) else None) or {}
    asets = (after.get("sets") if isinstance(after, dict) else None) or {}
    lines: list[str] = []
    # a piece added with what it holds is one change, not one per button inside it
    added = [k for k in aels if k not in bels and _parent(aels, k)[0] in bels]
    lines += [f"Added {what(aels[k], asets, titles)}" for k in added]
    removed = [k for k in bels if k not in aels and _parent(bels, k)[0] in aels]
    lines += [f"Took off {what(bels[k], bsets, titles)}" for k in removed]
    # a move is read from where an element sits, whatever it says of itself — a note moved is the same note
    both = [k for k in aels if k in bels and isinstance(aels[k], dict) and isinstance(bels[k], dict)]
    moved = [k for k in both if _parent(aels, k)[0] and _parent(aels, k)[0] != _parent(bels, k)[0]]
    lines += [f"Moved {what(aels[k], asets, titles)} to {what(aels.get(_parent(aels, k)[0]))}" for k in moved]
    structural = bool(added or removed or moved)
    resized: list[str] = []
    for k in both:
        if k in moved or aels[k] == bels[k]:
            continue
        line = _changed(bels[k], aels[k], asets, titles)
        if line and line.startswith("Resized"):
            resized.append(line)
        elif line and not (line.startswith("Rearranged") and structural):
            # a section that gained or lost what was added, taken off or moved says nothing more of it
            lines.append(line)
    lines += resized
    lines += _wiring(before, after, "sets", "set") + _wiring(before, after, "values", "value")
    if len(lines) > MAX_LINES:
        return lines[:MAX_LINES - 1] + [f"and {len(lines) - (MAX_LINES - 1)} more"]
    return lines
