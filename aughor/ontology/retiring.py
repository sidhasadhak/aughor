"""Arc FA, FA-3 — a declaration marked *retiring*: still served, moving to a successor by a date (ROADMAP §3.60).

A withdrawal something depends on is refused (Arc OC-1), which is right, and left a person nothing between keeping an
element for good and breaking what reads it. Now any declaration may carry a mark — the user's
word, 2026-10-26: *retiring* ("withdraw" is removal; "retired" already means archived for dashboards and the graph):

* **The mark** is one field on the declaration, ``retiring: {successor, on, note}``: the element of the SAME kind to
  use instead, which must exist on this ontology, the day it is meant to go, and the person's own words. It is written
  through the normal save path, so it waits in the draft; any change to it is a MEANING change
  (`compatibility.classify`), so publishing it restates the claims computed under it.
* **It still serves.** Retiring is not withdrawal: the element reads exactly as before, and every reader is told —
  the semantic block the agent reads, the entity's panel and its objects' pages say "retiring on <date> — use
  <successor> instead", and after the date "past its retiring date". Withdrawing it stays a separate, person's act.
* **It is the suggested route** when a withdrawal is refused because something depends on it.

The mark lives on the declaration, never on the graph's models: no model field grows, so an element nobody marked
reads exactly as it did. A built element marked retiring gets a declaration that holds the mark alone, which the
overlay applies as nothing.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

#: The declaration field the mark is kept in.
FIELD = "retiring"

KIND_WORDS = {"entity": "entity", "object_set": "segment", "computed_property": "computed property",
              "metric": "metric", "action": "action", "link": "link", "process": "process", "rule": "rule",
              "impact": "impact"}


def _today(today: Optional[date] = None) -> date:
    return today or datetime.now(timezone.utc).date()


def _day(text: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(text or "").strip()[:10]) if len(str(text or "").strip()) == 10 else None
    except ValueError:
        return None


def mark_of(fields: Optional[dict]) -> Optional[dict]:
    """The retiring mark a declaration's fields hold, or None — a malformed one reads as none."""
    raw = (fields or {}).get(FIELD)
    if not isinstance(raw, dict) or not str(raw.get("successor") or "").strip() or _day(raw.get("on")) is None:
        return None
    return {"successor": str(raw["successor"]).strip(), "on": str(raw["on"]).strip()[:10],
            **({"note": str(raw["note"]).strip()} if str(raw.get("note") or "").strip() else {})}


def is_past(mark: dict, today: Optional[date] = None) -> bool:
    day = _day(mark.get("on"))
    return day is not None and _today(today) > day


def said(mark: dict, successor_label: str = "", today: Optional[date] = None) -> str:
    """The sentence every reader is told: "retiring on 2026-12-01 — use Sales order instead", and after the date
    "past its retiring date, 2026-12-01 — use Sales order instead"."""
    use = f"use {successor_label or mark['successor']} instead"
    if is_past(mark, today):
        return f"past its retiring date, {mark['on']} — {use}"
    return f"retiring on {mark['on']} — {use}"


# ── what a mark may name ───────────────────────────────────────────────────────────────────────────────────────────


def _split(target_id: str) -> tuple[str, str]:
    return tuple(target_id.split("::", 1)) if "::" in target_id else ("", target_id)  # type: ignore[return-value]


def _declared_action(graph: Any, action_id: str) -> Any:
    return next((a for a in graph.declared_actions() if a.id == action_id), None)


def label(graph: Any, kind: str, target_id: str) -> Optional[str]:
    """The name a reader knows the element by, or None when this ontology has no such element of that kind."""
    if graph is None:
        return None
    if kind == "entity":
        e = graph.entities.get(target_id)
        return (e.display_name or e.id) if e is not None else None
    if kind in ("object_set", "computed_property"):
        owner, local = _split(target_id)
        e = graph.entities.get(owner)
        if e is None:
            return None
        if kind == "object_set":
            seg = (e.segments or {}).get(local)
            return (seg.display_name or seg.id) if seg is not None else None
        cp = next((c for c in e.computed_properties or [] if c.id == local), None)
        return (cp.label or cp.id) if cp is not None else None
    item = _declared_action(graph, target_id) if kind == "action" else None
    table = {"metric": "metrics", "link": "relationships", "process": "processes", "rule": "rules",
             "impact": "impacts"}.get(kind)
    if table:
        item = (getattr(graph, table, None) or {}).get(target_id)
    if item is None:
        return None
    return str(getattr(item, "display_name", "") or getattr(item, "name", "") or getattr(item, "id", "") or target_id)


def problem(graph: Any, kind: str, target_id: str, raw: Any) -> tuple[int, str]:
    """``(status, why)`` a mark cannot be written, or ``(0, "")``: the element must exist (404), the successor must be
    another element of the same kind on this ontology, and the day a date (400)."""
    word = KIND_WORDS.get(kind, kind)
    if label(graph, kind, target_id) is None:
        return 404, f"no {word} '{target_id}' on this ontology to mark retiring"
    spec = raw if isinstance(raw, dict) else {}
    successor = str(spec.get("successor") or "").strip()
    if not successor:
        return 400, f"name the {word} to use instead — a retiring {word} says what replaces it"
    if successor == target_id:
        return 400, f"{word} '{target_id}' cannot be its own successor"
    if label(graph, kind, successor) is None:
        return 400, (f"no {word} '{successor}' on this ontology to use instead — a successor is a {word} that "
                     "exists, of the same kind")
    if _day(spec.get("on")) is None:
        return 400, f"'{spec.get('on') or ''}' is not a day — say when it retires as YYYY-MM-DD"
    if len(str(spec.get("note") or "")) > 500:
        return 400, "keep the note under 500 characters"
    return 0, ""


def normalized(raw: dict) -> dict:
    return mark_of({FIELD: raw}) or {}


# ── what readers are told ──────────────────────────────────────────────────────────────────────────────────────────


def marks(conn: str, schema: str) -> dict[tuple[str, str], dict]:
    """Every retiring mark on one scope's declarations, in the view this context reads, by ``(kind, target_id)``."""
    from aughor.ontology.overrides import load_overrides
    out: dict[tuple[str, str], dict] = {}
    for ov in load_overrides(conn, schema or "default"):
        mark = mark_of(ov.fields)
        if mark is not None:
            out[(ov.target_kind, ov.target_id)] = mark
    return out


def described(graph: Any, kind: str, target_id: str, mark: dict, today: Optional[date] = None) -> dict:
    """A mark as a panel shows it: the successor and its name, the day, the note, whether the day has passed, and the
    sentence."""
    name = label(graph, kind, mark["successor"]) or mark["successor"]
    return {**mark, "successor_name": name, "past": is_past(mark, today), "said": said(mark, name, today)}


def mark_for(graph: Any, kind: str, target_id: str, *, conn: str = "") -> Optional[dict]:
    """The described mark of one element of ``graph``'s scope — on ``conn``, the connection the request named, else
    the graph's own — or None."""
    if graph is None or getattr(graph, "scope", ""):
        return None
    mark = marks(conn or graph.connection_id, graph.schema_name or "default").get((kind, target_id))
    return described(graph, kind, target_id, mark) if mark is not None else None


def _owners(graph: Any, kind: str, target_id: str) -> set[str]:
    """The entities an element is read on — what scopes it to a question's tables."""
    if kind == "entity":
        return {target_id}
    if kind in ("object_set", "computed_property"):
        return {_split(target_id)[0]}
    if kind == "metric":
        m = (graph.metrics or {}).get(target_id)
        return {m.entity} if m is not None and m.entity else set()
    if kind == "link":
        r = (graph.relationships or {}).get(target_id)
        return {r.from_entity, r.to_entity} if r is not None else set()
    if kind in ("process", "rule"):
        item = (graph.processes if kind == "process" else graph.rules or {}).get(target_id)
        return {item.entity} if item is not None and item.entity else set()
    if kind == "action":
        a = _declared_action(graph, target_id)
        return {x for x in (getattr(a, "object_type", ""), getattr(a, "entity", "")) if x} if a is not None else set()
    return set()


def semantic_lines(graph: Any, wanted: set[str], today: Optional[date] = None) -> list[str]:
    """The semantic block's lines for every retiring element read on an entity whose tables are ``wanted`` (bare,
    lower-case names): what it is, and "retiring on <date> — use <successor> instead"."""
    if graph is None or getattr(graph, "scope", ""):
        return []
    try:
        found = marks(graph.connection_id, graph.schema_name or "default")
    except Exception as exc:  # noqa: BLE001 — the block is still served without the marks, and the gap journaled
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the retiring marks could not be read for the semantic block", counter="ontology.retiring")
        return []
    lines = []
    for (kind, target_id), mark in sorted(found.items()):
        name = label(graph, kind, target_id)
        if name is None:
            continue
        tables = set()
        for owner in _owners(graph, kind, target_id):
            e = graph.entities.get(owner)
            tables |= {str(t).rsplit(".", 1)[-1].strip().strip('"').lower() for t in (e.source_tables if e else [])}
        if not tables & wanted:
            continue
        successor = f'"{label(graph, kind, mark["successor"]) or mark["successor"]}"'
        note = f" ({mark['note']})" if mark.get("note") else ""
        lines.append(f'  "{name}" ({KIND_WORDS.get(kind, kind)}) is {said(mark, successor, today)}{note}')
    return lines


def withdrawal_hint(kind: str) -> str:
    """What a refused withdrawal adds: the way to take an element out of use without breaking what depends on it."""
    word = KIND_WORDS.get(kind, kind)
    return (f" Or mark the {word} retiring — name its successor and a day; it keeps serving while what depends on it "
            "moves, and is withdrawn once nothing does.")
