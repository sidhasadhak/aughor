"""A pack's dashboard templates — a dashboard the industry usually keeps, which a person keeps as their own (Arc FA,
FA-6; ROADMAP §3.60).

A template is ``dashboards/*.yaml`` in a pack (`PackDashboardTemplate`): a title, a short description, cards naming the
pack's metrics by name, and sections laying them out. It is a declaration like the pack's mission templates — it never
becomes a dashboard on its own, and nothing in it is a query.

**The static gate** (:func:`template_problems`, read by `packs/validate.py` and so by the pack kit's check) holds every
template to the anatomy: an id, a title that states no figure, at most as many cards as a draft may create, each card
naming one of the pack's own metrics under a key of its own, every card placed and every placement a card.

**A draft** (:func:`draft`) is made for one connection and one person, with no model call: each card's metric is read
on the connection exactly as a dashboard draft reads it (`dashboards/propose._resolve`); one the connection has not
registered, or has registered and not approved, is skipped and said, a section left with no card is said too, and the
rest goes through ``propose.draft`` — the one proposal path, which runs every card before it is offered and stages the
dashboard as one proposal a person keeps whole or not at all. Kept, the dashboard's source is
``pack:<id>@<version> template`` (`propose.template_source`).

Only the templates of packs bound on the connection are listed, and only an active pack's: a draft pack steers
nothing until a person activates it, and its templates wait with it — said, never left out silently.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from aughor.packs.models import Pack, PackDashboardTemplate

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
#: The widest a template's section is drawn.
MAX_COLUMNS = 4


# ── the static gate ──────────────────────────────────────────────────────────────────────────

def template_problems(pack: Pack) -> list[str]:
    """Every way the pack's dashboard templates do not fit the anatomy — the pack kit refuses a pack with any."""
    from aughor.dashboards.propose import MAX_NEW_CARDS
    from aughor.dashboards.validate import stated_figures
    problems: list[str] = []
    metrics = {m.name for m in pack.metrics}
    seen_ids: set[str] = set()
    for t in pack.dashboards:
        where = f"dashboard template {t.id!r}"
        if not _ID.match(t.id or ""):
            problems.append(f"{where}: an id is 2 to 63 characters of lowercase letters, digits, '-' or '_'")
        if t.id in seen_ids:
            problems.append(f"{where}: two templates share the id")
        seen_ids.add(t.id)
        if not (t.title or "").strip():
            problems.append(f"{where}: no title")
        elif stated_figures(t.title):
            problems.append(f"{where}: the title states a figure — a card's figure is the one it measures")
        if not t.cards:
            problems.append(f"{where}: no cards")
        if len(t.cards) > MAX_NEW_CARDS:
            problems.append(f"{where}: {len(t.cards)} cards; a dashboard draft creates at most {MAX_NEW_CARDS}")
        keys: set[str] = set()
        for c in t.cards:
            if not _KEY.match(c.key or ""):
                problems.append(f"{where}: card key {c.key!r} begins with a letter and holds letters, digits, '-' and '_'")
            if c.key in keys:
                problems.append(f"{where}: two cards share the key {c.key!r}")
            keys.add(c.key)
            if c.metric not in metrics:
                problems.append(f"{where}: card {c.key!r} names metric {c.metric!r}, which is not one of this pack's metrics")
            if c.title and stated_figures(c.title):
                problems.append(f"{where}: card {c.key!r}'s title states a figure")
        if not t.sections:
            problems.append(f"{where}: no sections — the layout places every card in a section")
        placed: set[str] = set()
        for s in t.sections:
            if not (s.title or "").strip():
                problems.append(f"{where}: a section has no title")
            if not s.cards:
                problems.append(f"{where}: section {s.title!r} places no card")
            for k in s.cards:
                if k not in keys:
                    problems.append(f"{where}: section {s.title!r} places {k!r}, which is no card of the template")
                placed.add(k)
        for k in sorted(keys - placed):
            problems.append(f"{where}: card {k!r} is placed in no section")
    return problems


# ── reading a template on a connection ───────────────────────────────────────────────────────

def template_source(pack: Pack) -> str:
    from aughor.dashboards.propose import template_source as _source
    return _source({"pack": pack.id, "version": pack.manifest.version})


def _metric_on(name: str, connection_id: str) -> tuple[Any, str]:
    """The approved metric a card is made from on this connection, or ``(None, why it is skipped)`` — read the way a
    dashboard draft reads it, so the two cannot disagree."""
    from aughor.semantic.metrics import get_metric
    metric = get_metric(name, connection_id=connection_id)
    if metric is None:
        return None, "not registered on this connection"
    if metric.status != "approved":
        return None, f"registered here and {metric.status or 'not approved'}; a card is made from an approved metric"
    return metric, ""


def _titles(pack: Pack) -> dict[str, str]:
    return {m.name: (m.title or m.name) for m in pack.metrics}


def describe(pack: Pack, template: PackDashboardTemplate, connection_id: str) -> dict[str, Any]:
    """A template as the New dashboard list shows it on one connection: each card with whether it can be made here."""
    titles = _titles(pack)
    cards = []
    for c in template.cards:
        metric, why = _metric_on(c.metric, connection_id)
        cards.append({"key": c.key, "metric": c.metric, "title": c.title or titles.get(c.metric, c.metric),
                      "ready": metric is not None, "why": why})
    return {"pack": pack.id, "pack_name": pack.manifest.name or pack.id, "version": int(pack.manifest.version or 0),
            "id": template.id, "title": template.title, "description": template.description,
            "sections": [s.title for s in template.sections], "cards": cards,
            "ready": sum(1 for c in cards if c["ready"]), "source": template_source(pack)}


def listing(connection_id: str, schema: str = "") -> dict[str, Any]:
    """The templates of the active packs bound on this connection, and every bound pack whose templates wait, with why."""
    from aughor.packs.bindings import packs_bound_on
    from aughor.packs.ontology_map import load_pack_by_id
    out: list[dict] = []
    waiting: dict[str, str] = {}
    for pack_id in packs_bound_on(connection_id, schema or ""):
        pack = load_pack_by_id(pack_id)
        if pack is None:
            waiting[pack_id] = "the pack could not be loaded"
            continue
        if not pack.dashboards:
            continue
        if pack.manifest.status != "active":
            waiting[pack_id] = (f"the pack is {pack.manifest.status or 'a draft'}: its templates are offered once a person "
                                "activates it")
            continue
        out.extend(describe(pack, t, connection_id) for t in pack.dashboards)
    return {"connection_id": connection_id, "schema": schema or "", "templates": out, "waiting": waiting}


def find(pack: Pack, template_id: str) -> Optional[PackDashboardTemplate]:
    return next((t for t in pack.dashboards if t.id == template_id), None)


# ── a draft from a template ──────────────────────────────────────────────────────────────────

def spec_for(template: PackDashboardTemplate, keys: set[str]) -> tuple[dict, list[str]]:
    """The dashboard spec the template lays out, placing only the cards in ``keys``, and the sections it left out
    because none of their cards can be made. The skeleton is the composer's own, so the spec's root is the one every
    dashboard has."""
    from aughor.dashboards.compose import default_spec
    spec = default_spec(template.title, [])
    root = spec["root"]
    dropped: list[str] = []
    for i, section in enumerate(template.sections, start=1):
        held = [k for k in section.cards if k in keys]
        if not held:
            dropped.append(section.title)
            continue
        children = []
        for k in held:
            element = f"card-{i}-{k}"
            spec["elements"][element] = {"type": "Card", "props": {"card": k}, "children": []}
            children.append(element)
        sec = f"sec-{i}"
        spec["elements"][sec] = {"type": "Section",
                                 "props": {"title": section.title, "columns": min(MAX_COLUMNS, len(held))},
                                 "children": children}
        spec["elements"][root]["children"].append(sec)
    return spec, dropped


def _summary(pack: Pack, template: PackDashboardTemplate, made: int, skipped: list[dict], dropped: list[str]) -> str:
    said = (f'Drafted "{template.title}" from the {pack.manifest.name or pack.id} pack\'s template '
            f'(v{pack.manifest.version}): {made} card{"s" if made != 1 else ""}.')
    if skipped:
        said += " Left out: " + "; ".join(f'{s["title"]} — {s["why"]}' for s in skipped) + "."
    if dropped:
        said += " No section for " + ", ".join(f'"{d}"' for d in dropped) + ", which held only what was left out."
    return said + " Nothing is kept until you keep it."


def draft(pack: Pack, template: PackDashboardTemplate, *, connection_id: str, owner: str,
          schema: Optional[str] = None) -> dict[str, Any]:
    """Stage the template as ONE dashboard proposal for ``owner`` on ``connection_id``, with no model call — or say why
    none was. A card whose metric the connection lacks is skipped and said; the rest go through ``propose.draft``."""
    from aughor.dashboards import propose
    from aughor.dashboards.home import Home, new_id
    titles = _titles(pack)
    cards: list[dict] = []
    skipped: list[dict] = []
    for c in template.cards:
        metric, why = _metric_on(c.metric, connection_id)
        title = c.title or titles.get(c.metric, c.metric)
        if metric is None:
            skipped.append({"key": c.key, "metric": c.metric, "title": title, "why": why})
            continue
        cards.append({"key": c.key, "metric": c.metric, **({"title": c.title} if c.title else {})})
    dashboard_id = new_id(template.title)
    home = Home(connection_id, owner, dashboard_id)
    base = {"staged": False, "proposal_id": "", **home.as_params(), "dashboard_id": dashboard_id, "summary": "",
            "rounds": 0, "stop_reason": "", "sentences": [], "skipped": skipped, "source": template_source(pack),
            "template": {"pack": pack.id, "version": int(pack.manifest.version or 0), "id": template.id}}
    if not cards:
        base["sentences"] = ["None of the template's metrics can make a card on this connection: "
                             + "; ".join(f'{s["title"]} is {s["why"]}' for s in skipped) + "."]
        return base
    spec, dropped = spec_for(template, {c["key"] for c in cards})
    # The reasoning is read for figures like a model's; the pack and its version ride the proposal's template instead.
    drafted = propose.draft(home, mode=propose.MODE_NEW, spec=spec, cards=cards,
                            reasoning="Started from a pack's dashboard template; no model was asked.",
                            schema=schema, template=base["template"])
    if not drafted.staged:
        base["sentences"] = list(drafted.refusals)
        return base
    return {**base, "staged": True, "proposal_id": drafted.proposal.id,
            "summary": _summary(pack, template, len(cards), skipped, dropped), "dropped_sections": dropped}
