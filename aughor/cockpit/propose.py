"""A cockpit a person asked for, as ONE proposal (Arc CT, CT-5; ROADMAP §3.50).

In a Data Canvas's chat a person says "build me a returns cockpit". What is staged is one
proposal: the cards to create and the spec that arranges them. A person approves all of it or
none of it. "Move the watches to their own tab" is the same act, with the spec arriving as
RFC 6902 operations against the cockpit as it stands; approved, it is the next version.

**The model writes no SQL here, and states no figure.** A new card names what it is made
from — an approved metric, an approved trusted query, or a finding of this canvas — and its
query is read from that record. Nothing in a draft can carry a query of its own.

**A card is run before it is offered.** Every new card's query goes through the same guard
battery the Briefing's pin doors use (``aughor/dashboard/doors.py``), at the time the draft is
made. A draft that holds a card which cannot run is refused then, to the model, which can
repair it; a person is never shown one.

**What was approved is what is made.** The proposal keeps each card's query and the version of
the record it came from. On approval each is read again: a metric that has been changed, or
is no longer approved, refuses the whole proposal. So does a cockpit that has moved on since
the draft was made — an edit is written against one version and lands on that one or not at
all.

**All or nothing.** Everything is checked before anything is written. Then the cards are
made, then the spec is kept; if either fails the cards made so far are removed again. That
removal is the one delete in this arc, and it is of cards that were never approved into being.

**A refusal names everything it can.** The writer is a model, and each round it spends
learning of one fault is a model call. So every card is resolved and run before the draft is
refused, and the rules name every kind of fault at once (``web/lib/cockpit/rules.ts``).
"""
from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from aughor.cockpit import cards as _cards
from aughor.cockpit import validate as _validate
from aughor.cockpit import versions as _versions
from aughor.kernel.errors import tolerate

#: The inbox's kind for a cockpit proposal.
KIND = "cockpit_draft"

#: What a new card may be made from.
FROM_METRIC = "metric"
FROM_TRUSTED = "trusted_query"
FROM_FINDING = "finding"
SOURCES = (FROM_METRIC, FROM_TRUSTED, FROM_FINDING)

#: A draft creates at most this many cards: each is run against the warehouse before the
#: draft is offered, in the turn the person is waiting on.
MAX_NEW_CARDS = 12
#: How many of each kind of record a writer is shown to choose from.
MAX_OFFERED = 40

MODE_NEW = "new"
MODE_EDIT = "edit"

_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_CARD_STATUS = re.compile(r"^/cards/([A-Za-z0-9_-]{1,64})/status$")
_DIRECTIONS = ("above", "below")


# ── what a card may be made from ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Source:
    """A record a card is made from, read at this moment."""
    kind: str
    name: str            # the metric's name, the query's id, the finding's id
    version: int
    label: str           # what a reader calls it
    sql: str
    record: Any


def _canvas(canvas_id: str):
    from aughor.canvas.store import get_canvas
    return get_canvas(canvas_id)


def _schema_of(canvas) -> Optional[str]:
    return (canvas.scopes[0].schema_name or None) if canvas.scopes else None


def _resolve(conn_id: str, canvas_id: str, kind: str, name: str) -> tuple[Optional[_Source], str]:
    """The record ``kind``/``name`` names, or ``(None, why it may not be used)``."""
    if kind == FROM_METRIC:
        from aughor.semantic.metrics import get_metric, value_query
        metric = get_metric(name, connection_id=conn_id)
        if metric is None:
            return None, f'There is no metric named "{name}" on this connection.'
        if metric.status != "approved":
            return None, (f'The metric "{name}" is {metric.status or "not approved"}. '
                          "A card is made from an approved metric.")
        return _Source(kind, metric.name, int(metric.version or 0), metric.label or metric.name,
                       value_query(metric), metric), ""
    if kind == FROM_TRUSTED:
        from aughor.semantic.trusted_queries import get_trusted
        tq = get_trusted(name)
        if tq is None or tq.connection_id != conn_id:
            return None, f'There is no trusted query "{name}" on this connection.'
        if tq.status != "approved":
            return None, (f'The trusted query "{name}" is {tq.status or "not approved"}. '
                          "A card is made from an approved one.")
        if tq.owner_automation:
            return None, (f'The trusted query "{name}" belongs to an automation and is not in the '
                          "catalogue. A card is made from a query of the catalogue.")
        return _Source(kind, tq.id, int(tq.version or 0), tq.question or tq.id, tq.sql, tq), ""
    if kind == FROM_FINDING:
        from aughor.explorer.store import canvas_findings
        found = next((f for f in canvas_findings(canvas_id) if str(f.get("id") or "") == name), None)
        if found is None:
            return None, f'This canvas has no finding "{name}".'
        sql = (found.get("sql") or "").strip()
        if not sql:
            return None, f'The finding "{name}" has no query behind it, so no card can be made from it.'
        return _Source(kind, name, 0, (found.get("finding") or "").strip() or name, sql, found), ""
    return None, f'A card is made from one of: {", ".join(SOURCES)}.'


def _limit(raw: Any, key: str) -> tuple[dict, str]:
    """The limit a draft gives a card, as the card store keeps it, or why it is refused."""
    if raw in (None, {}):
        return {}, ""
    if not isinstance(raw, dict):
        return {}, f'The limit of the card "{key}" is not an object with "warning" or "critical".'
    out: dict[str, Any] = {}
    for name in ("warning", "critical"):
        value = raw.get(name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return {}, f'The {name} limit of the card "{key}" is {value!r}. A limit is a number.'
        out[name] = float(value)
    if not out:
        return {}, f'The limit of the card "{key}" names no "warning" and no "critical".'
    direction = str(raw.get("direction") or "above")
    if direction not in _DIRECTIONS:
        return {}, (f'The limit of the card "{key}" is crossed going "{direction}". '
                    f'It is crossed going: {", ".join(_DIRECTIONS)}.')
    extra = sorted(set(raw) - {"warning", "critical", "direction"})
    if extra:
        return {}, f'The limit of the card "{key}" carries {", ".join(extra)}. It holds "warning", "critical" and "direction".'
    return {**out, "direction": direction}, ""


def _draft_cards(conn_id: str, canvas, asked: Any) -> tuple[list[dict], list[str], set[str]]:
    """The cards a draft creates, each resolved and run; every refusal met on the way; and
    every name the draft gave a card, made or refused."""
    from aughor.dashboard import doors

    if asked in (None, []):
        return [], [], set()
    if not isinstance(asked, list):
        return [], ['"cards" is a list of the cards to create.'], set()
    named_all = {str(c.get("key")) for c in asked if isinstance(c, dict) and _KEY.match(str(c.get("key") or ""))}
    if len(asked) > MAX_NEW_CARDS:
        return [], [f"The draft creates {len(asked)} cards. A draft creates at most {MAX_NEW_CARDS}; "
                    "the rest can follow in an edit."], named_all

    held = {c.id for c in _cards.cards_of(canvas.id)}
    schema = _schema_of(canvas)
    out: list[dict] = []
    refusals: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(asked, start=1):
        if not isinstance(raw, dict):
            refusals.append(f"Card {i} of the draft is not an object.")
            continue
        key = str(raw.get("key") or "")
        if not _KEY.match(key):
            refusals.append(f'Card {i} of the draft is named "{key}". A name begins with a letter and '
                            'holds letters, digits, "-" and "_".')
            continue
        if key in seen:
            refusals.append(f'Two cards of the draft are named "{key}". A name is a card\'s own.')
            continue
        seen.add(key)
        if key in held:
            refusals.append(f'"{key}" is already the id of a card in this canvas. '
                            "Give the new card a name of its own.")
            continue
        named = [s for s in SOURCES if raw.get(s) not in (None, "")]
        if len(named) != 1:
            refusals.append(f'The card "{key}" names {", ".join(named) if named else "nothing"} to be made from. '
                            f'It is made from exactly one of: {", ".join(SOURCES)}.')
            continue
        extra = sorted(set(raw) - {"key", "title", "limit", *SOURCES})
        if extra:
            # Said by name: a draft that carries "sql" is the one thing this arc refuses outright.
            refusals.append(f'The card "{key}" carries {", ".join(extra)}. A card names what it is made '
                            "from; its query is read from that record, never written here.")
            continue
        source, why = _resolve(conn_id, canvas.id, named[0], str(raw.get(named[0])))
        if source is None:
            refusals.append(why)
            continue

        title = str(raw.get("title") or "").strip()
        if title:
            figures = _validate.stated_figures(title)
            if figures:
                refusals.append(f'The title of the card "{key}" reads "{title}", which states a figure '
                                f'({", ".join(figures)}). A card\'s figure is the one it measures.')
                continue
        limit, why = _limit(raw.get("limit"), key)
        if why:
            refusals.append(why)
            continue
        try:
            result = doors.run_guarded(conn_id, source.sql, query_id=f"cockpit-draft:{key}", schema=schema)
        except doors.GuardRefused as refused:
            refusals.append(f'The card "{key}", made from the {source.kind.replace("_", " ")} '
                            f'"{source.name}", could not be run: {refused}')
            continue
        kind = doors.kind_of(result)
        if limit and kind != "kpi":
            refusals.append(f'The card "{key}" draws a chart, and a limit is set on a single figure. '
                            "Leave the limit out.")
            continue
        out.append({
            "id": uuid.uuid4().hex[:8], "key": key,
            "from": source.kind, "name": source.name, "version": source.version,
            "label": source.label[:160],
            "kind": kind, "title": doors.clip_title(title or source.label, source.name),
            "sql": source.sql, "limit": limit,
        })
    return out, refusals, named_all


# ── the spec ─────────────────────────────────────────────────────────────────────────────────

def _with_ids(spec: Any, ids: dict[str, str]) -> Any:
    """``spec`` with each new card's name replaced by the id it will be created with — where a
    ``Card`` places it, and where a condition reads its status."""
    if not ids or not isinstance(spec, dict) or not isinstance(spec.get("elements"), dict):
        return spec
    out = copy.deepcopy(spec)

    def conditions(node: Any) -> Any:
        if isinstance(node, list):
            return [conditions(n) for n in node]
        if not isinstance(node, dict):
            return node
        done = {k: conditions(v) for k, v in node.items()}
        path = done.get("$state")
        m = _CARD_STATUS.match(path) if isinstance(path, str) else None
        if m and m.group(1) in ids:
            done["$state"] = f"/cards/{ids[m.group(1)]}/status"
        return done

    for el in out["elements"].values():
        if not isinstance(el, dict):
            continue
        props = el.get("props")
        if el.get("type") == "Card" and isinstance(props, dict) and props.get("card") in ids:
            props["card"] = ids[props["card"]]
        if "visible" in el:
            el["visible"] = conditions(el["visible"])
    return out


_STATUS_SAID = {
    "within": "within its limit", "over": "over its limit",
    "unmeasured": "unmeasured", "withheld": "withheld",
    "standing": "standing, with none chosen", "final": "final",
    "provisional": "provisional", "to_date": "to date",
}


def _said(cond: Any, titles: dict[str, str]) -> str:
    """A condition in words, for the person approving it."""
    if isinstance(cond, list):
        return " and ".join(_said(c, titles) for c in cond)
    if not isinstance(cond, dict):
        return ""
    for joiner, word in (("$or", " or "), ("$and", " and ")):
        if isinstance(cond.get(joiner), list):
            return "(" + word.join(_said(c, titles) for c in cond[joiner]) + ")"
    path = cond.get("$state")
    value = cond.get("eq", cond.get("neq"))
    if not isinstance(path, str) or not isinstance(value, str):
        return ""
    negated = ("neq" in cond) != (cond.get("not") is True)
    m = _CARD_STATUS.match(path)
    what = f'"{titles.get(m.group(1)) or m.group(1)}"' if m else "the range"
    return f'{what} is {"not " if negated else ""}{_STATUS_SAID.get(value, value)}'


def outline(spec: dict, titles: dict[str, str], new_ids: set[str],
            changes: Optional[dict] = None) -> list[dict]:
    """What the spec arranges, as a person reads it: tabs, their sections, their cards, and
    each condition in words. Written from an ACCEPTED spec, so its shape can be trusted.

    ``changes`` is what an edit does to the cockpit that stands, by element. Each tab, section
    and card then says whether the edit ``added`` it or ``changed`` it, so a person approving
    an edit reads what moves and is not left to find it among what stays."""
    els = spec["elements"]
    added = set((changes or {}).get("added") or [])
    changed = set((changes or {}).get("changed") or [])

    def moved(key: str) -> str:
        return "added" if key in added else "changed" if key in changed else ""

    def section(key: str) -> dict:
        el = els[key]
        return {
            "title": el["props"]["title"],
            "change": moved(key),
            "shown": _said(el.get("visible"), titles) if "visible" in el else "",
            "cards": [{
                "title": titles.get(els[c]["props"]["card"]) or els[c]["props"]["card"],
                "new": els[c]["props"]["card"] in new_ids,
                "change": moved(c),
                "tone": els[c]["props"].get("tone") or "",
                "shown": _said(els[c].get("visible"), titles) if "visible" in els[c] else "",
            } for c in el["children"]],
        }

    root = els[spec["root"]]
    first = els[root["children"][0]]
    if first["type"] == "Tabs":
        return [{"tab": els[t]["props"]["label"], "change": moved(t),
                 "sections": [section(s) for s in els[t]["children"]]}
                for t in first["children"]]
    return [{"tab": "", "change": "", "sections": [section(s) for s in root["children"]]}]


def taken_off(before: Optional[dict], removed: list[str], titles: dict[str, str]) -> list[dict]:
    """What an edit takes off the cockpit, as a person reads it: each card, section and tab by
    its own name, and where it was. The outline says what the cockpit will be, so what is no
    longer in it is said here or nowhere."""
    els = (before or {}).get("elements") or {}
    holder = {c: k for k, el in els.items() if isinstance(el, dict) for c in el.get("children") or []}
    out = []
    for key in removed:
        el = els.get(key) or {}
        props = el.get("props") or {}
        kind = el.get("type")
        if kind == "Card":
            title = titles.get(props.get("card")) or str(props.get("card") or key)
        elif kind == "Tab":
            title = str(props.get("label") or key)
        elif kind == "Section":
            title = str(props.get("title") or key)
        else:
            continue            # the row of tabs itself is not a line a reader sees
        held_by = (els.get(holder.get(key) or "") or {}).get("props") or {}
        out.append({"what": kind.lower(), "title": title,
                    "from": str(held_by.get("title") or held_by.get("label") or "")})
    return out


def _canonical(spec: Any) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)


# ── what a writer may choose from ────────────────────────────────────────────────────────────

def _in_canvas(tables: list[str], canvas) -> bool:
    """Whether a record that reads ``tables`` belongs to this canvas. A canvas of the whole
    schema holds everything; a record that names no table is not held back for it."""
    chosen = {t.split(".")[-1].lower() for t in (canvas.table_filter or [])}
    if not chosen or not tables:
        return True
    return any(t.split(".")[-1].lower() in chosen for t in tables)


def options(connection_id: str, canvas_id: str) -> dict:
    """What a cockpit for this canvas may be made of, and how one is written. No model call,
    no query, nothing written."""
    from aughor.explorer.store import canvas_findings
    from aughor.semantic.metrics import list_metrics
    from aughor.semantic.trusted_queries import list_trusted

    canvas = _canvas(canvas_id)
    if canvas is None or (canvas.primary_connection_id or "") != connection_id:
        return {"available": False,
                "summary": "This conversation is not in a Data Canvas of this connection, so there is no cockpit to draft."}
    text = _validate.grammar()
    if text is None:
        return {"available": False,
                "summary": "The cockpit's rules could not run on this server, so no cockpit can be drafted. "
                           "Say so; do not draft one."}

    metrics = [m for m in list_metrics(connection_id=connection_id)
               if m.status == "approved" and _in_canvas(list(m.tables or []), canvas)]
    trusted = [t for t in list_trusted(connection_id) if _in_canvas(list(t.tables or []), canvas)]
    findings = [f for f in canvas_findings(canvas_id) if (f.get("sql") or "").strip()]
    current = _versions.latest(canvas_id)
    live = current if current and not current["retired"] and current.get("spec") else None
    return {
        "available": True,
        "canvas": {"name": canvas.name},
        "cockpit": ({"version": live["version"], "spec": live["spec"]} if live else None),
        "cards_in_canvas": [{"id": c.id, "title": c.title, "kind": c.kind,
                             "has_limit": bool((c.thresholds or {}).get("warning") is not None
                                               or (c.thresholds or {}).get("critical") is not None)}
                            for c in _cards.cards_of(canvas_id)],
        "metrics": [{"metric": m.name, "label": m.label, "unit": m.unit or ""}
                    for m in metrics[:MAX_OFFERED]],
        "trusted_queries": [{"trusted_query": t.id, "answers": (t.question or "")[:160]}
                            for t in trusted[:MAX_OFFERED]],
        "findings": [{"finding": str(f.get("id") or ""), "says": (f.get("finding") or "")[:160]}
                     for f in findings[:MAX_OFFERED]],
        "not_shown": {"metrics": max(0, len(metrics) - MAX_OFFERED),
                      "trusted_queries": max(0, len(trusted) - MAX_OFFERED),
                      "findings": max(0, len(findings) - MAX_OFFERED)},
        "how_to_write_one": text,
        "summary": ("To draft: call again with op \"new\" (the whole spec) or op \"edit\" (operations against "
                    "the cockpit above). Create a card by naming what it is made from; place it in the spec by "
                    "the name you gave it. Place a card the canvas already holds by its id."),
    }


# ── staging ──────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Drafted:
    """What became of a draft. ``proposal`` is the staged record, or None with the reasons."""
    proposal: Any = None
    refusals: tuple[str, ...] = ()
    not_checked: bool = False
    replaced: tuple[str, ...] = ()

    @property
    def staged(self) -> bool:
        return self.proposal is not None


def _retire_pending(conn_id: str, canvas_id: str, by: str) -> tuple[str, ...]:
    """One pending draft per canvas. A newer draft replaces the older ones: two drafts written
    against one version cannot both land, and an approver offered both is offered a stale one."""
    from aughor.actions.inbox import list_proposals, supersede_proposal
    gone = []
    for old in list_proposals(connection_id=conn_id, status="pending"):
        if old.kind != KIND or old.id == by or (old.params or {}).get("canvas_id") != canvas_id:
            continue
        if supersede_proposal(old.id, actor="cockpit:redraft", note=f"superseded by {by}"):
            gone.append(old.id)
    return tuple(gone)


def draft(connection_id: str, canvas_id: str, *, mode: str, spec: Any = None, patches: Any = None,
          cards: Any = None, reasoning: str = "") -> Drafted:
    """Stage ONE proposal for this canvas's cockpit, or refuse with every reason found."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.org.context import current_org_id

    canvas = _canvas(canvas_id)
    if canvas is None or (canvas.primary_connection_id or "") != connection_id:
        return Drafted(refusals=("This conversation is not in a Data Canvas of this connection.",))
    if mode not in (MODE_NEW, MODE_EDIT):
        return Drafted(refusals=(f'A cockpit is drafted "{MODE_NEW}" or as an "{MODE_EDIT}".',))

    current = _versions.latest(canvas_id)
    live = current if current and not current["retired"] and current.get("spec") else None
    refusals: list[str] = []

    # The reasoning is a model's text, and it is read twice: by the person approving, on the
    # card, and by whoever later reads the cockpit's history, where it is the version's note.
    reasoning = (reasoning or "").strip()[:400]
    figures = _validate.stated_figures(reasoning)
    if figures:
        refusals.append(f'The reasoning states a figure ({", ".join(figures)}). Say why the cockpit is '
                        "arranged this way; a figure is a card's to show, where it is measured.")

    if mode == MODE_EDIT:
        if live is None:
            return Drafted(refusals=('This canvas has no cockpit to edit. Draft one with op "new".',))
        if spec is not None:
            refusals.append('An edit carries "patches", not a "spec".')
        edited = _validate.apply_patches(live["spec"], patches)
        if edited.status == _validate.NOT_CHECKED:
            return Drafted(refusals=edited.sentences, not_checked=True)
        if not edited.applied:
            refusals.extend(edited.sentences)
        spec = edited.spec
    else:
        if patches is not None:
            refusals.append('A new cockpit carries its whole "spec", not "patches".')
        if not isinstance(spec, dict):
            refusals.append('A new cockpit carries its whole "spec".')
            spec = None

    # Every card is resolved and run even when the spec is already refused, and the spec is
    # checked even when a card was: the writer is told of everything in one round.
    made, card_refusals, named = _draft_cards(connection_id, canvas, cards)
    refusals.extend(card_refusals)

    ids = {c["key"]: c["id"] for c in made}
    final = _with_ids(spec, ids) if spec is not None else None
    verdict = None
    if final is not None:
        # A card that was refused is still a name the spec places. It is counted as known
        # here, or the rules would call it a card the canvas does not hold — a second
        # sentence for a fault already told in its own.
        refused_names = named - set(ids)
        verdict = _validate.check_spec_for_canvas(
            final, canvas_id, also_known=[*ids.values(), *refused_names])
        if verdict.status == _validate.NOT_CHECKED:
            return Drafted(refusals=verdict.sentences, not_checked=True)
        if not verdict.accepted:
            refusals.extend(_as_written(s, ids) for s in verdict.sentences)
        else:
            placed = set(verdict.cards)
            for c in made:
                if c["id"] not in placed:
                    refusals.append(f'The card "{c["key"]}" is created and placed nowhere. '
                                    "Place it in a section, or leave it out.")
    if refusals:
        return Drafted(refusals=tuple(refusals))
    if final is None or verdict is None:          # nothing was offered to check
        return Drafted(refusals=("The draft holds no cockpit.",))
    if live and not made and _canonical(final) == _canonical(live["spec"]):
        return Drafted(refusals=("The cockpit already reads this way. Nothing was drafted.",))

    titles = {c.id: c.title for c in _cards.cards_of(canvas_id)} | {c["id"]: c["title"] for c in made}
    title = str(final["elements"][final["root"]]["props"]["title"])
    params = {
        "canvas_id": canvas_id,
        "mode": mode,
        "base_version": current["version"] if current else None,
        "cards": made,
        "spec": final,
        "patches": patches if mode == MODE_EDIT else [],
    }
    moves = _versions.changes(live["spec"] if live else None, final)
    # A new cockpit is all of it new; saying "added" of every line would say nothing.
    arranged = outline(final, titles, set(ids.values()), moves if mode == MODE_EDIT else None)
    detail = {
        "canvas_name": canvas.name,
        "title": title,
        "mode": mode,
        "replaces_version": live["version"] if live else None,
        "outline": arranged,
        # A card placed twice — once as an alert, once in its section — is one card.
        "counts": {"tabs": sum(1 for t in arranged if t["tab"]),
                   "sections": sum(len(t["sections"]) for t in arranged),
                   "cards": len(verdict.cards), "new": len(made)},
        "changes": moves,
        "taken_off": taken_off(live["spec"], moves["removed"], titles) if mode == MODE_EDIT and live else [],
    }
    p = stage_proposal(StagedProposal(
        kind=KIND, org_id=current_org_id() or "", connection_id=connection_id,
        schema_name=_schema_of(canvas) or "", action_id=f"cockpit:{canvas.name}",
        params=params, detail=detail, reasoning=reasoning,
        proposer="cockpit", source="agent"))
    return Drafted(proposal=p, replaced=_retire_pending(connection_id, canvas_id, p.id))


def _as_written(sentence: str, ids: dict[str, str]) -> str:
    """A refusal in the writer's own names: the id a new card was given means nothing to the
    model that named it."""
    for key, card_id in ids.items():
        sentence = sentence.replace(card_id, key)      # quoted on its own, or inside a path
    return sentence


# ── approval ─────────────────────────────────────────────────────────────────────────────────

def _as_drafted(conn_id: str, canvas_id: str, card: dict) -> tuple[Optional[_Source], str]:
    """The record a card was drafted from, if it is as it was — else ``(None, why not)``."""
    source, why = _resolve(conn_id, canvas_id, str(card.get("from")), str(card.get("name")))
    if source is None:
        return None, why
    what = f'the {source.kind.replace("_", " ")} "{source.name}"'
    if source.version != int(card.get("version") or 0):
        return None, (f'The card "{card.get("title")}" was drafted from version {card.get("version")} '
                      f"of {what}, which is now at version {source.version}.")
    if source.sql.strip() != str(card.get("sql") or "").strip():
        return None, f'The card "{card.get("title")}" was drafted from {what}, whose query has changed since.'
    return source, ""


def _card_of(conn_id: str, canvas_id: str, card: dict, source: _Source):
    from aughor.dashboard import doors
    from aughor.dashboard.models import CardProvenance, DashboardCard

    thresholds = dict(card.get("limit") or {})
    if source.kind == FROM_FINDING:
        return doors.card_from_finding(
            conn_id, source.record, kind=str(card["kind"]), title=str(card["title"]),
            scope=_cards.SCOPE, scope_ref=canvas_id, card_id=str(card["id"]),
        ).model_copy(update={"thresholds": thresholds})
    # Where the card's query came from, kept on the card. A metric is stamped by `place`.
    proof = f"trusted_query:{source.name}:v{source.version}" if source.kind == FROM_TRUSTED else ""
    return DashboardCard(
        id=str(card["id"]), connection_id=conn_id, scope=_cards.SCOPE, scope_ref=canvas_id,
        source="authored", kind=str(card["kind"]), title=str(card["title"]), sql=source.sql,
        thresholds=thresholds, provenance=CardProvenance(receipt_ref=proof))


def accept(params: dict, *, connection_id: str, approved_by: str, proposal_id: str,
           note: str = "") -> tuple[bool, Any]:
    """Make what an approved proposal holds: every card, then the spec — or nothing.
    Returns ``(True, outcome)`` or ``(False, the sentence why not)``."""
    from aughor.dashboard.store import delete_card, get_card

    canvas_id = str(params.get("canvas_id") or "")
    canvas = _canvas(canvas_id)
    if canvas is None:
        return False, "The canvas this cockpit was drafted for no longer exists."
    if (canvas.primary_connection_id or "") != connection_id:
        return False, "The canvas this cockpit was drafted for is no longer on this connection."
    if not (approved_by or "").strip():
        return False, "A cockpit is kept with the name of the person who approved it. None was given."

    current = _versions.latest(canvas_id)
    now = current["version"] if current else None
    drafted_on = params.get("base_version")
    if now != drafted_on:
        return False, (f"The cockpit has changed since this was drafted: it was "
                       f"{'version ' + str(drafted_on) if drafted_on else 'not yet made'}, and it is now "
                       f"version {now}. Ask for it again.")

    spec = params.get("spec")
    drafts = [c for c in (params.get("cards") or []) if isinstance(c, dict)]

    # Everything is checked before anything is written.
    sources: list[_Source] = []
    for card in drafts:
        source, why = _as_drafted(connection_id, canvas_id, card)
        if source is None:
            return False, why + " Nothing was made. Ask for the cockpit again."
        if not card.get("id") or get_card(str(card["id"])) is not None:
            return False, f'A card with the id "{card.get("id")}" already exists. Nothing was made.'
        sources.append(source)
    ids = [str(c["id"]) for c in drafts]
    verdict = _validate.check_spec_for_canvas(spec, canvas_id, also_known=ids)
    if not verdict.accepted:
        return False, " ".join(verdict.sentences) + " Nothing was made."

    made: list[str] = []

    def undo() -> None:
        for card_id in made:
            try:
                delete_card(card_id)
            except Exception as exc:
                tolerate(exc, "a card of a cockpit proposal that failed could not be removed again",
                         counter="cockpit.propose.undo", card_id=card_id)

    try:
        for card, source in zip(drafts, sources):
            placed = _cards.place(
                canvas_id, _card_of(connection_id, canvas_id, card, source),
                metric=source.record if source.kind == FROM_METRIC else None)
            made.append(placed.id)
        kept = _versions.keep(
            canvas_id, spec, approved_by=approved_by, source=f"proposal {proposal_id}",
            note=note, also_known=ids, written_by_model=True)
    except Exception as exc:
        undo()
        tolerate(exc, "a cockpit proposal failed part-way; what it had made was removed again",
                 counter="cockpit.propose.accept", canvas_id=canvas_id)
        return False, f"The cockpit could not be made: {exc}. Nothing was kept."
    if not kept.kept:
        undo()
        said = " ".join(kept.sentences) or "The cockpit already reads this way."
        return False, f"{said} Nothing was kept."

    title = str(spec["elements"][spec["root"]]["props"]["title"])
    return True, {"canvas_id": canvas_id, "canvas_name": canvas.name, "title": title,
                  "version": kept.version, "artifact_id": kept.artifact_id, "cards_created": made}
