"""Arc FA, FA-1 — find an object by the name it goes by, across entities (ROADMAP §3.60).

An object could be found only from inside its entity: a search box's ``contains`` condition reads one entity's title,
so finding "Jane Doe" meant knowing she is a customer first. Here one read looks across the served entities. Each
entity whose objects are titled by a text property is listed — its key and its title, nothing else — with the words
typed as a ``contains`` condition on the title, through the object door's own compiler (its row policies, its masks,
the accepted edits) and on one opened connection.

It is bounded, and the bound is said: at most ``MAX_ENTITIES`` entities, a few objects each, within ``BUDGET_MS``. The
answer says how many entities it searched of how many there are, and each one it did not search is listed with why —
named by its key, a name that is not text, a name masked for the reader, refused, past the cap or past the time. An
entity with more matches than it shows is named. No model call.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from aughor.ontology.models import OntologyEntity, OntologyGraph
from aughor.semantic.object_query import (
    MAX_CONTAINS_CHARS,
    NUMERIC_TYPES,
    ObjectFilter,
    ObjectListing,
    ObjectQueryRefused,
    compile_object_listing,
    find_property,
    is_temporal,
)

#: The most entities one search reads, the objects it shows from each by default and at most, and the time it may take
#: — a search runs as a person types.
MAX_ENTITIES = 12
PER_ENTITY = 5
MAX_PER_ENTITY = 20
BUDGET_MS = 4000
MIN_CHARS = 2


def _why_not(entity: OntologyEntity) -> str:
    """Why an entity cannot be searched by name, or "" when it can."""
    from aughor.ontology.display import display_of
    from aughor.ontology.platform_objects import is_platform
    from aughor.ontology.security import masked
    if is_platform(entity):
        return "its objects are held by the platform, not read from the connection"
    shown = display_of(entity)
    if shown["is_key"]:
        key = shown["property"]
        return (f"named by its key ({key}) — there is no name to match" if key
                else "it declares no key and no name — there is nothing to match")
    title = shown["property"]
    why = masked(entity, title)
    if why:
        return f"its name is masked for you — {why}"
    prop = find_property(entity, title)
    if prop is not None and (is_temporal(prop) or any(t in (prop.data_type or "").upper() for t in NUMERIC_TYPES)):
        return f"its name, {title}, holds no text"
    return ""


def _order(entity: OntologyEntity) -> tuple:
    """Entities a person named first, then those whose name the data proved names objects, then the larger ones."""
    from aughor.ontology.display import display_of
    shown = display_of(entity)
    rows = entity.backing.rows if entity.backing is not None and entity.backing.rows is not None else -1
    return (shown["source"] != "human", shown["verified"] is not True, -rows, entity.api_name)


def find_objects(graph: OntologyGraph, run: Callable[[str], Any], q: str, *, dialect: str = "duckdb",
                 overlay: Optional[list] = None, per_entity: int = PER_ENTITY, max_entities: Optional[int] = None,
                 budget_ms: Optional[int] = None) -> dict:
    """The objects whose name holds the words ``q``, across the served entities. ``run(sql)`` reads one statement on the
    connection the caller opened (through the guard battery) and returns its result.

    ``{q, hits: [{type, type_id, key, title, entity_label}], searched, of, said, skipped: [{entity, why}], more,
    withheld, masked}`` — ``withheld`` the entities a row policy narrowed for this reader, ``masked`` the names emptied
    for them. Raises `ObjectQueryRefused` when the words are too short or too long to look for."""
    words = " ".join(str(q or "").split())
    if len(words) < MIN_CHARS:
        raise ObjectQueryRefused(f"type at least {MIN_CHARS} characters to find an object by its name")
    if len(words) > MAX_CONTAINS_CHARS:
        raise ObjectQueryRefused(f"an object is found by at most {MAX_CONTAINS_CHARS} characters of its name")
    per_entity = max(1, min(int(per_entity), MAX_PER_ENTITY))
    max_entities = MAX_ENTITIES if max_entities is None else max_entities
    budget_ms = BUDGET_MS if budget_ms is None else budget_ms
    from aughor.ontology.display import display_of

    skipped: list[dict] = []
    masked: list[str] = []
    candidates: list[OntologyEntity] = []
    for entity in sorted(graph.entities.values(), key=_order):
        why = _why_not(entity)
        if why:
            skipped.append({"entity": entity.api_name, "why": why})
            if why.startswith("its name is masked"):
                masked.append(f"{entity.id}.{display_of(entity)['property']}")
            continue
        candidates.append(entity)
    for entity in candidates[max_entities:]:
        skipped.append({"entity": entity.api_name, "why": f"past the cap — one search reads {max_entities} "
                                                          f"entit{'y' if max_entities == 1 else 'ies'}"})

    hits: list[dict] = []
    more: list[str] = []
    withheld: list[str] = []
    searched = 0
    start = time.monotonic()
    for entity in candidates[:max_entities]:
        if (time.monotonic() - start) * 1000 > budget_ms:
            skipped.append({"entity": entity.api_name,
                            "why": f"past the time — the search stops after {budget_ms / 1000:g} seconds"})
            continue
        title = display_of(entity)["property"]
        listing = ObjectListing(entity=entity.id, columns=[title], order_by=title, limit=per_entity + 1,
                                filters=[ObjectFilter(path=title, op="contains", value=words)])
        try:
            compiled = compile_object_listing(listing, graph, dialect=dialect, overlay=overlay)
        except ObjectQueryRefused as exc:
            skipped.append({"entity": entity.api_name, "why": f"refused — {exc.reason}"})
            continue
        result = run(compiled.sql)
        error = str(getattr(result, "error", "") or "")
        if error:
            skipped.append({"entity": entity.api_name, "why": f"could not be read — {error}"[:300]})
            continue
        searched += 1
        withheld += [e for e in compiled.withheld if e not in withheld]
        names = [str(c) for c in (getattr(result, "columns", None) or [])]
        at = names.index(compiled.columns[0]["name"]) if compiled.columns and compiled.columns[0]["name"] in names else 1
        rows = list(getattr(result, "rows", None) or [])
        for row in rows[:per_entity]:
            hits.append({"type": entity.api_name, "type_id": entity.id, "key": str(row[0]),
                         "title": "" if row[at] in (None, "NULL") else str(row[at]),
                         "entity_label": entity.display_name or entity.id})
        if len(rows) > per_entity:
            more.append(entity.api_name)

    of = len(graph.entities)
    return {"q": words, "hits": hits, "searched": searched, "of": of,
            "said": f"searched {searched} of {of} entit{'y' if of == 1 else 'ies'}",
            "skipped": skipped, "more": more, "withheld": withheld, "masked": masked}
