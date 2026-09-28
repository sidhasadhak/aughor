"""A cockpit drafted for a person, as ONE proposal (Arc CT, CT-5; the home moved in CT-7).

In the Briefing a person names an area — "returns", "pricing" — and a model drafts a cockpit
of their own for it (``aughor/cockpit/ask.py``). What is staged is one proposal: the cards to
create and the spec that arranges them. The person keeps all of it or none of it. An edit is
the same act, with the spec arriving as RFC 6902 operations against the cockpit as it stands;
kept, it is the next version.

**The model writes no SQL here, and states no figure.** A new card names what it is made
from — an approved metric, an approved trusted query, or a finding the Briefing shows — and
its query is read from that record. Nothing in a draft can carry a query of its own.

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
from aughor.cockpit.home import NOBODY_IN_PARTICULAR, Home, approver
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

#: What a writer is told of drafting, beside the grammar of the spec. Each sentence is here
#: because a receipt by a model (the study's §12 and §14) found a draft that went wrong for
#: want of it.
HOW_TO_DRAFT = (
    'To draft: call again with op "new" and the whole spec, or op "edit" and operations against the '
    'cockpit above. A "new" cockpit replaces the one that stands, whole; to add to it or change it, '
    'draft an "edit". '
    'A card is CREATED by listing it in "cards", under a name of your own and with the one record it is '
    'made from, for example {"key": "return-rate", "metric": "return_rate"}. It is PLACED by that same '
    'name, {"type": "Card", "props": {"card": "return-rate"}}, and a condition reads it by that name too, '
    '"/cards/return-rate/status". A name the spec places and "cards" does not list is refused, unless it '
    'is the id of a card the person already has ("cards_you_have" above). '
    'A record a card they have already shows ("made_from" above) is placed by that card\'s id, not '
    "created again; a card may be placed in more than one section. "
    'A finding is one the Briefing shows, listed above under "findings". '
    f"A draft creates at most {MAX_NEW_CARDS} cards, because each is run before the draft is offered; "
    "choose the ones that matter most, and say that more can follow in an edit. "
    'A limit goes on a card, as "limit", only when the user named it; a limit you choose is refused. '
    'Leave "visible" out of an element that is always shown. '
    "A card shows what its record measures and no more: a metric is one figure for the whole connection, "
    "and a trusted query or a finding shows its own rows. When the user asks for what no record "
    "measures, such as a breakdown no record gives, say so in your answer rather than drafting "
    "something else in its place."
)

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


def findings(conn_id: str, schema: Optional[str]) -> list[dict]:
    """The findings the Briefing shows for this connection — the ones a person pins from, read
    the way the Briefing's own pin door reads them. Only those with a query behind them can
    become a card; the rest are said to have none."""
    from aughor.routers import exploration
    by_domain = exploration.domain_findings_for(conn_id, schema or None)
    return [i for items in (by_domain or {}).values() for i in (items or []) if isinstance(i, dict)]


def _resolve(conn_id: str, schema: Optional[str], kind: str, name: str) -> tuple[Optional[_Source], str]:
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
        found = next((f for f in findings(conn_id, schema) if str(f.get("id") or "") == name), None)
        if found is None:
            # Said as what it is: the Briefing does not show it. A finding it leaves out — one set
            # aside as not holding — may exist elsewhere, and is not said not to.
            return None, (f'The Briefing shows no finding "{name}". A card is made from a finding it '
                          'shows, as op options lists them under "findings".')
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


def _named_by_the_user(value: float, said: str) -> bool:
    """Whether the person's own words name this limit — 12, 12% and 0.12 alike, as
    :func:`_is_a_limit` reads them."""
    from aughor.explorer.grounding import extract_numerals
    return any(_is_a_limit(n, [value]) for n in extract_numerals(said))


def _made_from(card: Any) -> Optional[tuple[str, str]]:
    """The record a card was made from, as its provenance keeps it."""
    prov = card.provenance
    if prov.metric:
        return FROM_METRIC, prov.metric
    if (prov.receipt_ref or "").startswith("trusted_query:"):
        return FROM_TRUSTED, prov.receipt_ref.split(":")[1]
    if prov.insight_id:
        return FROM_FINDING, prov.insight_id
    return None


def _limit_key(thresholds: Any) -> tuple:
    t = thresholds if isinstance(thresholds, dict) else {}
    if t.get("warning") is None and t.get("critical") is None:
        return ()
    return t.get("warning"), t.get("critical"), t.get("direction") or "above"


def _query_key(sql: str) -> str:
    return " ".join((sql or "").split()).rstrip(";")


def _draft_cards(home: Home, schema: Optional[str], asked: Any,
                 said: Optional[str] = None) -> tuple[list[dict], list[str], set[str]]:
    """The cards a draft creates, each resolved and run; every refusal met on the way; and
    every name the draft gave a card, made or refused.

    ``said`` is what the person said on this turn. When it is given, a limit it does not name
    is refused: the third run of the receipt found a writer setting 12% on two cards nobody had
    asked a limit of, and a person approving reads a limit on the card as one they set."""
    from aughor.dashboard import doors

    if asked in (None, []):
        return [], [], set()
    if not isinstance(asked, list):
        return [], ['"cards" is a list of the cards to create.'], set()
    named_all = {str(c.get("key")) for c in asked if isinstance(c, dict) and _KEY.match(str(c.get("key") or ""))}
    if len(asked) > MAX_NEW_CARDS:
        return [], [f"The draft creates {len(asked)} cards. A draft creates at most {MAX_NEW_CARDS}; "
                    "the rest can follow in an edit."], named_all

    conn_id = home.connection_id
    held_cards = _cards.cards_of(home)
    held = {c.id for c in held_cards}
    out: list[dict] = []
    refusals: list[str] = []
    seen: set[str] = set()
    drafted_from: dict[tuple[str, str], tuple[str, set]] = {}
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
            refusals.append(f'"{key}" is already the id of a card the person has. '
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
        source, why = _resolve(conn_id, schema, named[0], str(raw.get(named[0])))
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
        if limit and said is not None:
            unnamed = [f"{limit[n]:g}" for n in ("warning", "critical")
                       if n in limit and not _named_by_the_user(limit[n], said)]
            if unnamed:
                refusals.append(f'The card "{key}" sets a limit of {" and ".join(unnamed)}, which the user '
                                'did not name. A limit goes on a card only when the user names it: leave '
                                '"limit" out, or ask the user for one.')
                continue

        # One record, one card. The third run of the receipt found a second lead-time card
        # drafted beside the first, and a second Revenue: the writer made a card where it
        # could have placed one. A second card of a record is made only to set a limit the
        # first does not have.
        what = f'the {source.kind.replace("_", " ")} "{source.name}"'
        mine = _limit_key(limit)
        same = " with the same limit" if mine else ""
        twins = [h for h in held_cards if _made_from(h) == (source.kind, source.name)
                 or _query_key(h.sql) == _query_key(source.sql)]
        if twins and (not mine or any(_limit_key(h.thresholds) == mine for h in twins)):
            twin = next((h for h in twins if _limit_key(h.thresholds) == mine), twins[0])
            refusals.append(f'The card "{key}" would show {what}, which the card "{twin.id}" '
                            f'("{twin.title}") the person has already shows{same}. Place "{twin.id}" '
                            "by its id instead; a card may be placed in more than one section.")
            continue
        earlier = drafted_from.get((source.kind, source.name))
        if earlier is not None and (not mine or mine in earlier[1]):
            refusals.append(f'The cards "{earlier[0]}" and "{key}" of the draft are both made from '
                            f"{what}{same}. One card shows it; place that card in each section it "
                            "belongs in.")
            continue
        drafted_from.setdefault((source.kind, source.name), (key, set()))[1].add(mine)
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


def _replaced(before: dict, placed_after: set[str], removed: list[str], titles: dict[str, str]) -> list[dict]:
    """What a NEW cockpit takes off the one that stands. A new spec may reuse an element's name
    for another card, so a card is taken off when it is placed nowhere in the new one, whatever
    its element is called; a tab or a section, when its element is gone. Each card once.

    The third run of the receipt found two new cockpits that would have taken off 9 and 12
    cards, and the card a person approves on listed none of them: this was computed for an
    edit only."""
    els = before.get("elements") or {}
    keys, told = [], set()
    for key, el in els.items():
        if not isinstance(el, dict):
            continue
        card = (el.get("props") or {}).get("card") if el.get("type") == "Card" else None
        if card is not None and card not in placed_after and card not in told:
            told.add(card)
            keys.append(key)
        elif el.get("type") in ("Tab", "Section") and key in removed:
            keys.append(key)
    return taken_off(before, keys, titles)


def _canonical(spec: Any) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)


# ── what a writer may choose from ────────────────────────────────────────────────────────────

def options(home: Home, schema: Optional[str] = None) -> dict:
    """What a cockpit for this person may be made of, and how one is written. No model call,
    no query, nothing written."""
    from aughor.semantic.metrics import list_metrics
    from aughor.semantic.trusted_queries import list_trusted

    text = _validate.grammar()
    if text is None:
        return {"available": False,
                "summary": "The cockpit's rules could not run on this server, so no cockpit can be drafted. "
                           "Say so; do not draft one."}

    metrics = [m for m in list_metrics(connection_id=home.connection_id) if m.status == "approved"]
    trusted = [t for t in list_trusted(home.connection_id)
               if t.status == "approved" and not t.owner_automation]
    shown = [f for f in findings(home.connection_id, schema) if (f.get("sql") or "").strip()]
    current = _versions.latest(home)
    live = current if current and not current["retired"] and current.get("spec") else None
    return {
        "available": True,
        "cockpit": ({"version": live["version"], "spec": live["spec"]} if live else None),
        "cards_you_have": [{"id": c.id, "title": c.title, "kind": c.kind,
                            "has_limit": bool(_limit_key(c.thresholds)),
                            **({"made_from": dict([_made_from(c)])} if _made_from(c) else {})}
                           for c in _cards.cards_of(home)],
        "metrics": [{"metric": m.name, "label": m.label, "unit": m.unit or ""}
                    for m in metrics[:MAX_OFFERED]],
        "trusted_queries": [{"trusted_query": t.id, "answers": (t.question or "")[:160]}
                            for t in trusted[:MAX_OFFERED]],
        "findings": [{"finding": str(f.get("id") or ""), "says": (f.get("finding") or "")[:160]}
                     for f in shown[:MAX_OFFERED]],
        "not_shown": {"metrics": max(0, len(metrics) - MAX_OFFERED),
                      "trusted_queries": max(0, len(trusted) - MAX_OFFERED),
                      "findings": max(0, len(shown) - MAX_OFFERED)},
        # What a draft may not exceed, beside the spec's own limits (which the grammar gives).
        # The receipt by a model found this cap stated nowhere a writer reads: two of ten
        # first drafts made 19 and 17 cards against it.
        "limits": {"new_cards": MAX_NEW_CARDS},
        "how_to_write_one": text,
        "summary": HOW_TO_DRAFT,
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


def _retire_pending(home: Home, by: str) -> tuple[str, ...]:
    """One pending draft per cockpit. A newer draft replaces the older ones: two drafts written
    against one version cannot both land, and an approver offered both is offered a stale one."""
    from aughor.actions.inbox import list_proposals, supersede_proposal
    gone = []
    for old in list_proposals(connection_id=home.connection_id, status="pending"):
        if old.kind != KIND or old.id == by or Home.of((old.params or {}).get("home")) != home:
            continue
        if supersede_proposal(old.id, actor="cockpit:redraft", note=f"superseded by {by}"):
            gone.append(old.id)
    return tuple(gone)


def draft(home: Home, *, mode: str, spec: Any = None, patches: Any = None, cards: Any = None,
          reasoning: str = "", said: Optional[str] = None, schema: Optional[str] = None) -> Drafted:
    """Stage ONE proposal for this person's cockpit, or refuse with every reason found.

    ``said`` is what the person asked for, when the caller knows it: a limit is then set only
    where they named it (:func:`_draft_cards`). ``schema`` is the one the Briefing is read on;
    a card is run on it, as a pin from the Briefing is."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.org.context import current_org_id

    if mode not in (MODE_NEW, MODE_EDIT):
        return Drafted(refusals=(f'A cockpit is drafted "{MODE_NEW}" or as an "{MODE_EDIT}".',))

    current = _versions.latest(home)
    live = current if current and not current["retired"] and current.get("spec") else None
    refusals: list[str] = []

    # The reasoning is a model's text, and it is read twice: by the person approving, on the
    # card, and by whoever later reads the cockpit's history, where it is the version's note.
    # It states no figure — but a limit the draft sets is a setting a person asked for and
    # approves on the same card, not a measurement, and the reasoning may name it. Only one
    # they asked for: a limit the writer chose is a figure it read, and the third run of the
    # receipt found one licensed that way ("each capped at 12% because every category sits
    # near 11-12%").
    reasoning = (reasoning or "").strip()[:400]
    limits = [v for v in _limits_asked(cards) if said is None or _named_by_the_user(v, said)]
    figures = _validate.as_written(n for n in _validate.stated_numerals(reasoning) if not _is_a_limit(n, limits))
    if figures:
        refusals.append(f'The reasoning states a figure ({", ".join(figures)}). Say why the cockpit is '
                        "arranged this way; a figure is a card's to show, where it is measured. "
                        "A limit this draft sets on a card may be named.")

    if mode == MODE_EDIT:
        if live is None:
            return Drafted(refusals=('There is no cockpit here to edit. Draft one with op "new".',))
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
    made, card_refusals, named = _draft_cards(home, schema, cards, said)
    refusals.extend(card_refusals)

    ids = {c["key"]: c["id"] for c in made}
    final = _with_ids(spec, ids) if spec is not None else None
    verdict = None
    if final is not None:
        # A card that was refused is still a name the spec places. It is counted as known
        # here, or the rules would call it a card the cockpit may not place — a second
        # sentence for a fault already told in its own.
        refused_names = named - set(ids)
        verdict = _validate.check_spec_for_home(
            final, home, also_known=[*ids.values(), *refused_names],
            say_unknown=_undeclared(home, schema, named))
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

    titles = {c.id: c.title for c in _cards.cards_of(home)} | {c["id"]: c["title"] for c in made}
    title = str(final["elements"][final["root"]]["props"]["title"])
    params = {
        "home": home.as_params(),
        "schema": schema or "",
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
        "title": title,
        "mode": mode,
        "replaces_version": live["version"] if live else None,
        "outline": arranged,
        # A card placed twice — once as an alert, once in its section — is one card.
        "counts": {"tabs": sum(1 for t in arranged if t["tab"]),
                   "sections": sum(len(t["sections"]) for t in arranged),
                   "cards": len(verdict.cards), "new": len(made)},
        "changes": moves,
        "taken_off": (taken_off(live["spec"], moves["removed"], titles) if mode == MODE_EDIT
                      else _replaced(live["spec"], set(verdict.cards), moves["removed"], titles)) if live else [],
    }
    p = stage_proposal(StagedProposal(
        kind=KIND, org_id=current_org_id() or "", connection_id=home.connection_id,
        schema_name=schema or "", action_id=f"cockpit:{title}",
        params=params, detail=detail, reasoning=reasoning,
        proposer="cockpit", source="agent"))
    return Drafted(proposal=p, replaced=_retire_pending(home, p.id))


def _limits_asked(cards: Any) -> list[float]:
    """Every limit the draft asks to set, as written — on a card that is made or on one that
    is refused: the reasoning is judged by what the draft says, not by what became of it."""
    out: list[float] = []
    for card in cards if isinstance(cards, list) else []:
        limit = card.get("limit") if isinstance(card, dict) else None
        for name in ("warning", "critical"):
            value = limit.get(name) if isinstance(limit, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out.append(float(value))
    return out


def _is_a_limit(numeral: Any, limits: list[float]) -> bool:
    """Whether a figure in the reasoning is one of the draft's own limits. "12%" names a limit
    of 12 and a limit of 0.12 alike: which of the two a metric's unit calls for is the
    writer's to get right on the card, and either way the figure is the limit and no
    measurement."""
    readings = (numeral.value, numeral.value / 100.0, numeral.value * 100.0)
    return any(abs(r - limit) <= 1e-9 * max(1.0, abs(limit)) for r in readings for limit in limits)


def _undeclared(home: Home, schema: Optional[str], named: set[str]):
    """The sentence for a name a DRAFT places, or reads, that is no card the person has and none
    the draft creates. The default sentence says the cockpit may not place it, which is true and
    does not say the repair; three drafts of the receipt by a model were refused for this, and
    the writer had to work out for itself that the name belonged in "cards"."""
    offered: dict[str, tuple[str, str]] = {}
    told: set[str] = set()

    def records() -> dict[str, tuple[str, str]]:
        if not offered:
            from aughor.semantic.metrics import list_metrics
            from aughor.semantic.trusted_queries import list_trusted
            for f in findings(home.connection_id, schema):
                if (f.get("sql") or "").strip():
                    offered[str(f.get("id") or "").lower()] = (FROM_FINDING, str(f.get("id") or ""))
            for t in list_trusted(home.connection_id):
                offered[t.id.lower()] = (FROM_TRUSTED, t.id)
            for m in list_metrics(connection_id=home.connection_id):
                if m.status == "approved":
                    offered[m.name.lower()] = (FROM_METRIC, m.name)
            offered[""] = ("", "")                 # read once, even when nothing is offered
        return offered

    def say(name: str, how: str) -> str:
        if name in told:
            return ""               # placed and read: one missing card, told once, with its repair
        told.add(name)
        does = "places the card" if how == "placed" else "reads the status of the card"
        said = (f'The cockpit {does} "{name}". The person has no card with that id, and the draft '
                "creates none of that name.")
        kind, record = records().get(name.lower().replace("-", "_"), records().get(name.lower(), ("", "")))
        if kind and _KEY.match(name):
            said += (f' "{record}" is {_A[kind]}: to make a card from it, add '
                     f'{{"key": "{name}", "{kind}": "{record}"}} to "cards".')
        else:
            said += (f' To create it, add it to "cards" with "key": "{name}" and the one record it is '
                     f'made from ({", ".join(SOURCES)}).')
        if named:
            said += f' The draft creates: {", ".join(sorted(named))}.'
        return said

    return say


_A = {FROM_METRIC: "an approved metric", FROM_TRUSTED: "a trusted query", FROM_FINDING: "a finding the Briefing shows"}


def _as_written(sentence: str, ids: dict[str, str]) -> str:
    """A refusal in the writer's own names: the id a new card was given means nothing to the
    model that named it."""
    for key, card_id in ids.items():
        sentence = sentence.replace(card_id, key)      # quoted on its own, or inside a path
    return sentence


# ── approval ─────────────────────────────────────────────────────────────────────────────────

def _as_drafted(conn_id: str, schema: Optional[str], card: dict) -> tuple[Optional[_Source], str]:
    """The record a card was drafted from, if it is as it was — else ``(None, why not)``."""
    source, why = _resolve(conn_id, schema, str(card.get("from")), str(card.get("name")))
    if source is None:
        return None, why
    what = f'the {source.kind.replace("_", " ")} "{source.name}"'
    if source.version != int(card.get("version") or 0):
        return None, (f'The card "{card.get("title")}" was drafted from version {card.get("version")} '
                      f"of {what}, which is now at version {source.version}.")
    if source.sql.strip() != str(card.get("sql") or "").strip():
        return None, f'The card "{card.get("title")}" was drafted from {what}, whose query has changed since.'
    return source, ""


def _card_of(home: Home, card: dict, source: _Source):
    from aughor.dashboard import doors
    from aughor.dashboard.models import CardProvenance, DashboardCard

    thresholds = dict(card.get("limit") or {})
    if source.kind == FROM_FINDING:
        return doors.card_from_finding(
            home.connection_id, source.record, kind=str(card["kind"]), title=str(card["title"]),
            scope=_cards.OWN, scope_ref=home.owner, card_id=str(card["id"]),
        ).model_copy(update={"thresholds": thresholds})
    # Where the card's query came from, kept on the card. A metric is stamped by `place`.
    proof = f"trusted_query:{source.name}:v{source.version}" if source.kind == FROM_TRUSTED else ""
    return DashboardCard(
        id=str(card["id"]), connection_id=home.connection_id, scope=_cards.OWN, scope_ref=home.owner,
        source="authored", kind=str(card["kind"]), title=str(card["title"]), sql=source.sql,
        thresholds=thresholds, provenance=CardProvenance(receipt_ref=proof))


def accept(params: dict, *, connection_id: str, approved_by: str, proposal_id: str,
           note: str = "") -> tuple[bool, Any]:
    """Make what an approved proposal holds: every card, then the spec — or nothing.
    Returns ``(True, outcome)`` or ``(False, the sentence why not)``."""
    from aughor.dashboard.store import delete_card, get_card

    home = Home.of((params or {}).get("home"))
    if home is None:
        return False, "This proposal names no cockpit to keep. Nothing was made."
    if home.connection_id != connection_id:
        return False, "The cockpit this was drafted for is on another connection. Nothing was made."
    if not (approved_by or "").strip():
        return False, "A cockpit is kept with the name of the person who approved it. None was given."
    # A person's cockpit is theirs: only they keep it. Where identity is off there is one
    # operator, and whoever approves is them.
    if home.owner != NOBODY_IN_PARTICULAR and approved_by.strip() != approver(home.owner):
        return False, "This cockpit was drafted for someone else, and only they can keep it. Nothing was made."
    schema = str(params.get("schema") or "") or None

    current = _versions.latest(home)
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
        source, why = _as_drafted(connection_id, schema, card)
        if source is None:
            return False, why + " Nothing was made. Ask for the cockpit again."
        if not card.get("id") or get_card(str(card["id"])) is not None:
            return False, f'A card with the id "{card.get("id")}" already exists. Nothing was made.'
        sources.append(source)
    ids = [str(c["id"]) for c in drafts]
    verdict = _validate.check_spec_for_home(spec, home, also_known=ids)
    if not verdict.accepted:
        return False, " ".join(verdict.sentences) + " Nothing was made."

    made: list[str] = []

    def undo() -> None:
        for card_id in made:
            try:
                delete_card(card_id)
            except Exception as exc:
                tolerate(exc, f"a card of a cockpit proposal that failed ({card_id}) could not be removed again",
                         counter="cockpit.propose.undo", conn_id=home.connection_id)

    try:
        for card, source in zip(drafts, sources):
            placed = _cards.place(
                home, _card_of(home, card, source),
                metric=source.record if source.kind == FROM_METRIC else None)
            made.append(placed.id)
        kept = _versions.keep(
            home, spec, approved_by=approved_by, source=f"proposal {proposal_id}",
            note=note, also_known=ids, written_by_model=True)
    except Exception as exc:
        undo()
        tolerate(exc, "a cockpit proposal failed part-way; what it had made was removed again",
                 counter="cockpit.propose.accept", conn_id=home.connection_id)
        return False, f"The cockpit could not be made: {exc}. Nothing was kept."
    if not kept.kept:
        undo()
        said = " ".join(kept.sentences) or "The cockpit already reads this way."
        return False, f"{said} Nothing was kept."

    title = str(spec["elements"][spec["root"]]["props"]["title"])
    return True, {**home.as_params(), "title": title,
                  "version": kept.version, "artifact_id": kept.artifact_id, "cards_created": made}
