"""Arc FA, FA-2 — a choice can leave its piece: the objects a reader ticked, or a set a piece reads, as a question's subject.

A dashboard's table collects ticks and its pieces read named sets; until now neither could leave the dashboard. Behind
``canvas.ask_about_chosen`` a question asked in the Data Canvas may carry one of them as its subject (`AskFocus`):

* **objects** — up to fifty references, ``<type>:<key>`` (the builder doors' form, read by `ontology.object_refs`), of one
  entity or several;
* **a set** — a dashboard's set by name, with the values and the chosen objects the page read it with, and the reader's
  own filters on it. The set's definition is the dashboard's, read here; the browser never sends what a set reads.

Either is read again here through the object listing door (`routers.objects.post_object_listing`) under the asking
person's row policy — keys and titles, at most fifty, and the total. Withheld is said, never implied: a chosen object the
reader may not see is dropped and counted ("2 of the 12 are withheld from you"), one no object holds is counted apart,
and a set past fifty says how many it holds. Nothing here calls a model: the subject is handed to the conversation as a
tool result (`routers.investigations._focus_prose_for`), and the route receipt says it in the same words.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

FLAG = "canvas.ask_about_chosen"
#: The kinds of subject this module reads; every other focus kind is SP-15's one object.
KINDS = ("objects", "set")
#: The most objects a subject names by key and title — a page of a queue, never a warehouse.
MAX_CHOSEN = 50
#: The most of the reader's own filters a set's subject carries — as many as a filter column holds.
MAX_READER_FILTERS = 20
#: What the conversation is handed at most, as the SP-15 focus is.
_MAX_PROSE = 8000


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def is_subject(focus: Any) -> bool:
    """Whether ``focus`` is a subject of objects or a set — not SP-15's one object."""
    return focus is not None and getattr(focus, "kind", "") in KINDS


@dataclass
class Part:
    """The objects of one entity a subject names."""
    entity: str
    noun: str                                      # "orders", as the entity is called
    one: str                                       # "order"
    key: str = ""
    objects: list[dict] = field(default_factory=list)   # [{"key", "title"}], at most MAX_CHOSEN
    asked: int = 0                                 # objects chosen (a set: 0)
    total: Optional[int] = None                    # objects the subject holds, when counted
    withheld: int = 0                              # chosen objects a row policy withholds from the reader
    missing: int = 0                               # chosen keys no object holds
    refused: str = ""

    def count_words(self, n: int) -> str:
        return f"{n:,} {self.one if n == 1 else self.noun}"


@dataclass
class Subject:
    """What a question is about, read for the asker: one part per entity, the set it came from, what was withheld."""
    kind: str
    label: str = ""                                # the set's label: read, or ticked from
    parts: list[Part] = field(default_factory=list)
    said: list[str] = field(default_factory=list)  # the object door's caveats — a row policy, a masked property
    read: dict = field(default_factory=dict)       # a set as the door read it: entity, segment, filters
    narrowed: bool = False                         # the reader's own filters narrowed the set
    refused: str = ""

    @property
    def withheld(self) -> int:
        return sum(p.withheld for p in self.parts)

    @property
    def shown(self) -> int:
        return sum(len(p.objects) for p in self.parts)

    def words(self) -> str:
        """The subject in one line, as the reader is told it: "About 10 of the 12 orders chosen · from Late dispatch ·
        2 of the 12 are withheld from you"."""
        if self.refused:
            return f"The subject could not be read: {self.refused}"
        refused = [f"{p.entity}: {p.refused}" for p in self.parts if p.refused]
        if self.kind == "set":
            p = self.parts[0]
            out = f"About {self.label or 'the set'}"
            if p.total is not None:
                out += f" · {p.count_words(p.total)}"
                if p.total > len(p.objects):
                    out += f" · the first {len(p.objects):,} named"
            return out + (" · narrowed by your filters" if self.narrowed else "")
        asked = sum(p.asked for p in self.parts)
        listed = " and ".join(p.count_words(p.asked) for p in self.parts)
        out = (f"About {self.shown:,} of the {listed} chosen" if self.shown < asked
               else f"About the {listed} chosen")
        if self.label:
            out += f" · from {self.label}"
        if self.withheld:
            out += f" · {self.withheld:,} of the {asked:,} {'is' if self.withheld == 1 else 'are'} withheld from you"
        missing = sum(p.missing for p in self.parts)
        if missing:
            out += f" · {missing:,} {'is' if missing == 1 else 'are'} not found"
        if refused:
            out += " · " + "; ".join(refused)
        return out

    def receipt(self, carried: bool) -> dict:
        """The route receipt's key: what the turn is about, and whether the body answering it read it."""
        return {"kind": self.kind, "said": self.words(), "shown": self.shown, "withheld": self.withheld,
                "carried": bool(carried)}

    def prose(self) -> str:
        """The subject for the conversation, as a tool result its claims are bound to (the SP-15 law)."""
        body: dict[str, Any] = {"subject": self.words()}
        if self.refused:
            body["refused"] = self.refused
        if self.kind == "set":
            body["set"] = self.label
            body["read_as"] = self.read
            body["narrowed_by_reader_filters"] = self.narrowed
        body["entities"] = [{"entity": p.entity, "key": p.key,
                             **({"chosen": p.asked} if self.kind == "objects" else {"holds": p.total}),
                             "listed": len(p.objects),
                             **({"withheld_from_the_reader": p.withheld} if p.withheld else {}),
                             **({"not_found": p.missing} if p.missing else {}),
                             **({"refused": p.refused} if p.refused else {}),
                             "objects": p.objects} for p in self.parts]
        if self.said:
            body["caveats"] = list(self.said)
        where = (f"the set \"{self.label}\" a piece of their dashboard reads" if self.kind == "set"
                 else "objects they chose on a dashboard" + (f" (from \"{self.label}\")" if self.label else ""))
        return ("## On screen\n"
                f"The reader asks about {where}, read again through the object door as they may see them. Answer "
                "about these objects; quote their keys, and never name one that is not listed. What is withheld from "
                "the reader is counted here and is theirs to be told, never guessed at:\n```json\n"
                + json.dumps(body, ensure_ascii=False, default=str)[:_MAX_PROSE] + "\n```")


# ── reading a subject ────────────────────────────────────────────────────────────────────────────────────────────────

def resolve(focus: Any, connection_id: str, schema_name: Optional[str] = None, *, person: str = "") -> Optional[Subject]:
    """The subject ``focus`` names, read for the asker — or None when the flag is off or the focus is not a subject.
    Never raises: a subject that cannot be read says why in ``refused``, and the turn proceeds."""
    if not is_subject(focus) or not on():
        return None
    try:
        if focus.kind == "objects":
            return _objects(list(focus.objects or []), connection_id, schema_name, label=str(focus.label or ""))
        return _set(focus, connection_id, schema_name, person=person)
    except Exception as exc:  # noqa: BLE001 — the subject is context, never a dependency of the turn
        from aughor.kernel.errors import tolerate
        tolerate(exc, "ask: the chosen objects could not be read; the turn proceeds and says so",
                 counter="ask.subject_unread")
        return Subject(kind=focus.kind, refused=f"{type(exc).__name__}: {exc}"[:300])


def _graph(connection_id: str, schema_name: Optional[str]):
    from aughor.routers.ontology import served_ontology_graph
    return served_ontology_graph(connection_id, schema_name)


def _naming(entity: Any) -> tuple[str, str]:
    from aughor.dashboards.from_object import plural
    one = (entity.display_name or entity.id or "object").strip().lower()
    return plural(one), one


def _list(connection_id: str, schema_name: Optional[str], listing: dict) -> dict:
    """One page through the object listing door, as the asker reads it — the door's own statements apply the row
    policy themselves (`security_sql.object_door`)."""
    from fastapi import HTTPException

    from aughor.ontology.security_sql import object_door
    from aughor.routers.objects import post_object_listing
    from aughor.semantic.object_query import ObjectListing
    with object_door():
        try:
            out = post_object_listing(ObjectListing.model_validate(listing), connection_id=connection_id,
                                      schema_name=schema_name, execute=True)
        except HTTPException as exc:
            return {"path": "refused", "refused": str(exc.detail)}
    return out if isinstance(out, dict) else {"path": "refused", "refused": "the listing door answered nothing"}


def _rows(page: dict, title: str) -> list[dict]:
    names = list(page.get("names") or [])
    at = names.index(title) if title and title in names else -1
    return [{"key": str(r[0]), **({"title": str(r[at])} if at > 0 and r[at] not in (None, "", "NULL") else {})}
            for r in page.get("rows") or [] if r]


def _objects(refs: list[Any], connection_id: str, schema_name: Optional[str], *, label: str = "") -> Subject:
    from aughor.ontology.object_refs import split_ref, type_word
    from aughor.semantic.object_instances import key_of, title_column
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    out = Subject(kind="objects", label=label)
    graph = _graph(connection_id, schema_name)
    if graph is None:
        out.refused = "no ontology is built for this connection, so it has no objects to name"
        return out
    groups: dict[str, tuple[str, list[str]]] = {}
    for ref in refs[:MAX_CHOSEN]:
        typ, key = split_ref(ref)
        if not typ or not key:
            continue
        word = type_word(typ)
        keys = groups.setdefault(word, (typ, []))[1]
        if key not in keys:
            keys.append(key)
    for typ, keys in groups.values():
        try:
            entity = find_object_type(graph, typ)
            key = key_of(entity)
        except ObjectQueryRefused as exc:
            out.parts.append(Part(entity=typ, noun=typ, one=typ, asked=len(keys), refused=exc.reason))
            continue
        noun, one = _naming(entity)
        part = Part(entity=entity.id, noun=noun, one=one, key=key, asked=len(keys))
        title = title_column(entity) or ""
        listing = {"entity": entity.id, "filters": [{"path": key, "op": "in", "values": keys}],
                   "columns": [title or key], "limit": max(1, len(keys))}
        page = _list(connection_id, schema_name, listing)
        if page.get("path") == "refused" or page.get("error"):
            part.refused = str(page.get("refused") or page.get("error"))
            out.parts.append(part)
            continue
        part.objects = _rows(page, title)
        part.total = len(keys)
        # what the door said of the read — a row policy, a masked name — but not of the keys asked for: a key the reader
        # may not see reads to the value checks as one no row holds, and naming it would list what the policy withheld
        out.said += [c for c in page.get("caveats") or [] if c not in out.said and not any(k in c for k in keys)]
        gone = [k for k in keys if k not in {o["key"] for o in part.objects}]
        if gone:
            part.withheld = _existing(connection_id, schema_name, entity, key, gone)
            part.missing = len(gone) - part.withheld
        out.parts.append(part)
    return out


def _existing(connection_id: str, schema_name: Optional[str], entity: Any, key: str, keys: list[str]) -> int:
    """How many of ``keys`` name an object at all — the platform's own check, so a chosen object the reader may not see
    is said to be withheld rather than missing (`security.unfiltered`, as the object page says it). Only the count leaves
    here; with row policies off, a key the reader cannot list is not there."""
    from aughor.ontology import security
    if not security.enabled():
        return 0
    with security.unfiltered():
        page = _list(connection_id, schema_name, {"entity": entity.id, "filters": [{"path": key, "op": "in",
                                                                                    "values": keys}],
                                                  "columns": [], "limit": max(1, len(keys))})
    total = page.get("total")
    return int(total) if isinstance(total, int) else len(page.get("rows") or [])


def _set(focus: Any, connection_id: str, schema_name: Optional[str], *, person: str) -> Subject:
    from aughor.dashboards import validate
    from aughor.semantic.object_query import ObjectFilter
    if not focus.dashboard and focus.entity and focus.segment:
        return _segment(focus, connection_id, schema_name)
    out = Subject(kind="set")
    spec, why = _dashboard_spec(connection_id, str(focus.dashboard or ""), str(focus.owner or ""), person)
    if spec is None:
        out.refused = why
        return out
    sets = spec.get("sets") if isinstance(spec.get("sets"), dict) else {}
    name = str(focus.set or "")
    out.label = str((sets.get(name) or {}).get("label") or name)
    read = validate.read_set(spec, name, dict(focus.values or {}), {str(k): str(v) for k, v in (focus.chosen or {}).items()})
    if read is None:
        out.refused = "the dashboard's rules could not run, so the set was not read"
        return out
    if "refused" in read or "waiting" in read:
        waiting = str(read.get("waiting") or "").replace("_", " ").replace("-", " ")
        out.refused = str(read.get("refused") or f"the set waits on the {waiting}, and the page sent none")
        return out
    try:
        mine = [ObjectFilter.model_validate(f).model_dump(exclude_defaults=True)
                for f in list(focus.filters or [])[:MAX_READER_FILTERS]]
    except ValueError as exc:
        out.refused = f"your filters on the set could not be read: {exc}"[:300]
        return out
    out.narrowed = bool(mine)
    return _listed(out, connection_id, schema_name, str(read.get("entity") or ""), str(read.get("segment") or ""),
                   list(read.get("filters") or []), mine)


def _segment(focus: Any, connection_id: str, schema_name: Optional[str]) -> Subject:
    """A set the ontology names — a segment, or a rule read as one — that a piece reads directly, under the conditions
    the piece reads it with (the reader's filters among them). No dashboard is consulted: the segment's own definition
    is the server's, and the conditions are read through the same door, so nothing the page sends can widen it."""
    from aughor.semantic.object_query import ObjectFilter
    out = Subject(kind="set", label=str(focus.label or focus.segment))
    try:
        filters = [ObjectFilter.model_validate(f).model_dump(exclude_defaults=True)
                   for f in list(focus.filters or [])[:MAX_READER_FILTERS]]
    except ValueError as exc:
        out.refused = f"the piece's filters on the set could not be read: {exc}"[:300]
        return out
    out.narrowed = bool(filters) and bool(focus.narrowed)
    return _listed(out, connection_id, schema_name, str(focus.entity), str(focus.segment), filters, [])


def _listed(out: Subject, connection_id: str, schema_name: Optional[str], entity_name: str, segment: str,
            filters: list[dict], mine: list[dict]) -> Subject:
    """The set read for the asker through the object listing door: at most `MAX_CHOSEN` named, with the total."""
    from aughor.semantic.object_instances import key_of, title_column
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    graph = _graph(connection_id, schema_name)
    if graph is None:
        out.refused = "no ontology is built for this connection, so it has no objects to name"
        return out
    try:
        entity = find_object_type(graph, entity_name)
        key = key_of(entity)
    except ObjectQueryRefused as exc:
        out.refused = exc.reason
        return out
    noun, one = _naming(entity)
    out.read = {"entity": entity.id, "segment": segment, "filters": filters}
    title = title_column(entity) or ""
    page = _list(connection_id, schema_name, {"entity": entity.id, "segment": segment, "filters": filters + mine,
                                              "columns": [title or key], "limit": MAX_CHOSEN})
    part = Part(entity=entity.id, noun=noun, one=one, key=key)
    if page.get("path") == "refused" or page.get("error"):
        out.refused = str(page.get("refused") or page.get("error"))
        return out
    part.objects = _rows(page, title)
    total = page.get("total")
    part.total = int(total) if isinstance(total, int) else None
    out.said = [c for c in page.get("caveats") or []]
    out.parts.append(part)
    return out


def _dashboard_spec(connection_id: str, dashboard: str, owner: str, person: str) -> tuple[Optional[dict], str]:
    """The spec of the dashboard a set is read from, as the asker reads it: their own newest version, or — for one
    another person published to them — the version its readers read. ``(None, why)`` when it is not theirs to read."""
    from aughor.dashboards import sharing, versions
    from aughor.dashboards.home import Home, valid_id
    if not valid_id(dashboard):
        return None, "the subject names no dashboard"
    if owner and owner != person:
        try:
            got = sharing.read_shared(connection_id, owner, dashboard, reader=person)
        except sharing.Refused as exc:
            return None, str(exc)
        kept = next((v for k, v in got.items() if k != "home"), None)     # the version its readers read
    else:
        kept = versions.latest(Home(connection_id, person, dashboard))
    spec = (kept or {}).get("spec")
    if not isinstance(spec, dict) or (kept or {}).get("retired"):
        return None, "this dashboard is not one you can read, or it was retired"
    return spec, ""
