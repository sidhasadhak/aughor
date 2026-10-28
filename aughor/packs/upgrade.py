"""Packs as products — the version a pack was installed at, what it offered then, and the upgrade to the version it is
now (Arc FA, FA-6; ROADMAP §3.60).

A binding stored whatever version its caller sent (the web sent none, so every binding read 1) and no record of what
the pack proposed when it was bound, so nothing could say what a newer version brings. A bind now records the MANIFEST's version, who bound it, and a snapshot of what the pack offered at that version
(:func:`offered`): its terms, the bands of its alert priors, its metric recipes and the structure its map claims —
each item with a hash of its content, so a later version's item reads as added, changed or unchanged.

**What a person declined is read where it is already kept** — three stores, none of them a new one:

- a term: the vocabulary's tombstone (`ontology/vocabulary.decline_synonym`);
- an alert: the inbox proposal a person rejected, its source ``pack:<id>``;
- a structure claim: the explorer's draft record — a proposal with the pack's provenance (``pack:<id>@<version>``)
  that a person withdrew, read against the served graph (`ontology/explorer.proposal_tier`).

A metric recipe has no decline: it is read from the pack, and a person registers it on a connection from Metrics.

**The diff** (:func:`diff`) is the snapshot against the pack as it stands — added, changed and removed — with every
item a person declined marked with the version it was declined in. **The upgrade** (:func:`apply`) keeps the
binding's role map, re-binds at the manifest's version, proposes only what is new or changed and never an unchanged
item a person declined, and records the new snapshot. A structure claim is proposed through its own door (Explore
with the pack), which measures it against the data first and never proposes again what a person withdrew: the upgrade
says so instead of going around that door. What the upgrade removes is nothing — a term confirmed or an alert armed
from an earlier version stays as a person left it.

No model is called anywhere here.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Optional

from aughor.packs.models import Pack

#: The kinds of item a pack offers, in the order a diff lists them.
KINDS = ("term", "alert", "metric", "structure")

#: Why a metric recipe is never proposed by an upgrade.
METRIC_NOTE = "a metric recipe is read from the pack as it stands; a person registers it on this connection from Metrics"
#: Why a structure claim is proposed through its own door.
STRUCTURE_NOTE = ("proposed through Explore with this pack, which measures each claim against the data first and never "
                  "proposes again what a person withdrew")
#: What becomes of an item the pack no longer carries.
REMOVED_NOTE = "no longer in the pack; what it proposed earlier stays as a person left it"
#: A binding made before installed versions were recorded.
UNRECORDED = ("this binding was made before installed versions were recorded, so what it offered then is not known: "
              "every item the pack carries is listed as added, and nothing a person declined is offered again")

_SUFFIX = re.compile(r"@v(\d+)$")



def _hash(content: Any) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _item(kind: str, label: str, said: str, content: Any, ref: dict) -> dict:
    return {"kind": kind, "label": label, "said": said, "hash": _hash(content), "ref": ref}


def _structure_of(pack: Pack):
    try:
        from aughor.packs.ontology_map import resolve_ontology
        return resolve_ontology(pack.id) or pack.ontology
    except Exception:  # noqa: BLE001 — a map that cannot be resolved is the pack's own
        return pack.ontology


def alert_content(metric: str, bound: float, unit: str) -> dict:
    """What an alert item is: the metric watched, the bound and its unit — the same three an inbox proposal keeps."""
    return {"metric": metric, "bound": float(bound), "unit": unit or ""}


# ── what a pack offers ───────────────────────────────────────────────────────────────────────

def offered(pack: Pack, *, graph=None) -> dict[str, Any]:
    """What the pack offers on a connection at its manifest's version, as ``{version, items}``: one item per term,
    bounded alert side, metric recipe and structure claim, keyed by what it is and carrying a hash of what it says."""
    from aughor.packs.connect import pack_terms
    items: dict[str, dict] = {}
    for row in pack_terms(pack, graph=graph):
        key = f"term:{row['subject_kind']}:{row['subject_id']}:{row['synonym']}"
        items[key] = _item("term", f'"{row["synonym"]}"', row["what"], [row["subject_kind"], row["subject_id"], row["synonym"]],
                           {"subject_kind": row["subject_kind"], "subject_id": row["subject_id"], "synonym": row["synonym"]})
    titles = {m.name: (m.title or m.name) for m in pack.metrics}
    for m in pack.monitors:
        mid = m.id or m.metric
        if not (m.metric or "").strip() or m.unmeasured or not m.measured_on:
            continue          # an unmeasured prior offers no band, so there is nothing to propose or decline
        for side, bound in (("below", m.low), ("above", m.high)):
            if bound is None:
                continue
            unit = f" {m.unit}" if m.unit else ""
            items[f"alert:{mid}:{side}"] = _item(
                "alert", f"{titles.get(m.metric, m.metric)} {side} its prior range", f"fires {side} {float(bound):g}{unit}",
                alert_content(m.metric, bound, m.unit), {"prior": mid, "side": side, "metric": m.metric})
    for m in pack.metrics:
        band = m.sane_range
        content = {"formula": " ".join((m.formula or "").split()), "binds": m.binds.model_dump(), "unit": m.unit,
                   "definition": m.definition, "grain": " ".join((m.grain or "").split()),
                   "range": [band.min, band.max] if band is not None else None}
        items[f"metric:{m.name}"] = _item("metric", m.title or m.name, " ".join((m.formula or "").split())[:200], content,
                                          {"metric": m.name})
    po = _structure_of(pack)
    for obj in (po.objects if po is not None else []):
        items[f"structure:object:{obj.name}"] = _item(
            "structure", f"object {obj.name}", ", ".join(obj.aliases) or obj.description[:120],
            {"aliases": sorted(obj.aliases), "roles": sorted(obj.roles)}, {"claim": "object", "name": obj.name})
        for part in obj.parts:
            items[f"structure:part:{obj.name}/{part}"] = _item(
                "structure", f"{obj.name} is made of {part}", "", {"object": obj.name, "part": part},
                {"claim": "part", "object": obj.name, "part": part})
    for lk in (po.links if po is not None else []):
        items[f"structure:link:{lk.from_object}>{lk.to_object}"] = _item(
            "structure", f"{lk.from_object} {lk.verb or 'relates to'} {lk.to_object}",
            f"{lk.cardinality}{' on ' + lk.via if lk.via else ''}",
            {"cardinality": lk.cardinality, "via": lk.via, "verb": lk.verb, "reverse_verb": lk.reverse_verb,
             "optional": lk.to_side_optional}, {"claim": "link", "from": lk.from_object, "to": lk.to_object})
    for proc in (po.processes if po is not None else []):
        stages = [{"name": s.name, "hints": list(s.timestamp_hints),
                   "promise": s.promise.model_dump() if s.promise is not None else None} for s in proc.stages]
        items[f"structure:process:{proc.name}"] = _item(
            "structure", f"process {proc.name}", " → ".join(s.name for s in proc.stages),
            {"object": proc.object, "stages": stages}, {"claim": "process", "name": proc.name})
    for lc in (po.lifecycles if po is not None else []):
        items[f"structure:lifecycle:{lc.object}"] = _item(
            "structure", f"lifecycle of {lc.object}", ", ".join(lc.states),
            {"column": lc.column_hint, "states": list(lc.states), "terminal": sorted(lc.terminal_states)},
            {"claim": "lifecycle", "object": lc.object})
    for rule in (po.rules if po is not None else []):
        items[f"structure:rule:{rule.name}"] = _item(
            "structure", f"rule {rule.name}", rule.description[:120],
            {"object": rule.object, "kind": rule.kind, "property": rule.property_hint, "values": list(rule.values)},
            {"claim": "rule", "name": rule.name})
    for action in (po.actions if po is not None else []):
        items[f"structure:action:{action.name}"] = _item(
            "structure", f"action {action.name}", action.description[:120],
            {"object": action.object, "risk": action.risk}, {"claim": "action", "name": action.name})
    return {"version": int(pack.manifest.version or 0), "items": items}


def install_record(pack: Pack, *, by: str, graph=None) -> dict[str, Any]:
    """What a bind records: who bound the pack, and the snapshot of what it offered."""
    from aughor.util.time import now_iso_z
    snap = offered(pack, graph=graph)
    snap["at"] = now_iso_z()
    return {"bound_by": by or "", "offered": snap}


# ── what a person declined, read where it is kept ────────────────────────────────────────────

def _graph(connection_id: str, schema: str):
    try:
        from aughor.ontology.store import load_latest_ontology
        return load_latest_ontology(connection_id, schema or None)
    except Exception:  # noqa: BLE001 — no graph: the structure a person withdrew cannot be read, said
        return None


def declined(pack: Pack, connection_id: str, schema: str = "", *, graph=None,
             snapshot: Optional[dict] = None) -> tuple[dict[str, dict], dict[str, str]]:
    """Every item of this pack a person declined on the connection, as ``{key: {in, where, hash}}`` — ``in`` the
    version it was declined in (None when no record says), ``hash`` the content declined (None when not known) — and
    the stores that could not be read, each with why."""
    snap_items = (snapshot or {}).get("items") or {}
    snap_version = (snapshot or {}).get("version")
    out: dict[str, dict] = {}
    unread: dict[str, str] = {}

    def at_install(key: str) -> Optional[int]:
        prior = snap_items.get(key) or {}
        if prior.get("declined_in") is not None:
            return int(prior["declined_in"])
        return int(snap_version) if key in snap_items and snap_version is not None else None

    try:
        from aughor.ontology import vocabulary as V
        for kind, subject, term in V.declined_synonyms(connection_id):
            key = f"term:{kind}:{subject}:{term}"
            out[key] = {"in": at_install(key), "where": "vocabulary", "hash": _hash([kind, subject, term])}
    except Exception as exc:  # noqa: BLE001 — said, never read as "nothing declined"
        unread["terms"] = f"the vocabulary could not be read: {str(exc)[:160]}"

    try:
        out.update(_rejected_alerts(pack, connection_id, at_install))
    except Exception as exc:  # noqa: BLE001
        unread["alerts"] = f"the inbox could not be read: {str(exc)[:160]}"

    g = graph if graph is not None else _graph(connection_id, schema)
    if g is None:
        unread["structure"] = "no ontology is built for this connection, so what a person withdrew cannot be read"
    else:
        try:
            out.update(_withdrawn_structure(pack, connection_id, g, snap_items))
        except Exception as exc:  # noqa: BLE001
            unread["structure"] = f"the explorer's record could not be read: {str(exc)[:160]}"
    return out, unread


def _alert_proposals(pack: Pack, connection_id: str) -> dict[tuple[str, str], list]:
    """This pack's alert proposals on the connection, by ``(prior id, side)``, newest first."""
    from aughor.actions.inbox import list_proposals
    src = f"pack:{pack.id}"
    out: dict[tuple[str, str], list] = {}
    for p in list_proposals(connection_id=connection_id, limit=1000):       # newest first
        if p.source != src or p.kind != "monitor_bundle":
            continue
        prior = dict((p.detail or {}).get("prior") or {})
        mid, side = str(prior.get("id") or ""), str((p.detail or {}).get("side") or "")
        if mid and side:
            out.setdefault((mid, side), []).append(p)
    return out


def _rejected_alerts(pack: Pack, connection_id: str, at_install: Callable[[str], Optional[int]]) -> dict[str, dict]:
    """The alert sides whose LATEST proposal a person rejected — an earlier rejection followed by an accepted offer is
    not a decline that stands — with the version it was offered at and the band they rejected."""
    out: dict[str, dict] = {}
    for (mid, side), rows in _alert_proposals(pack, connection_id).items():
        latest = rows[0]
        if latest.status != "rejected":
            continue
        key = f"alert:{mid}:{side}"
        detail = latest.detail or {}
        prior = dict(detail.get("prior") or {})
        hit = _SUFFIX.search(latest.call_id or "")
        version = int(hit.group(1)) if hit else detail.get("pack_version") or at_install(key)
        bound = detail.get("bound")
        content = alert_content(str(prior.get("metric") or ""), float(bound), str(prior.get("unit") or "")) \
            if bound is not None else None
        out[key] = {"in": int(version) if version is not None else None, "where": "inbox",
                    "hash": _hash(content) if content is not None else None}
    return out


def _withdrawn_structure(pack: Pack, connection_id: str, graph, snap_items: dict) -> dict[str, dict]:
    """The structure claims a person withdrew: each draft proposal written with this pack's provenance whose tier is
    now withdrawn (or, for a part, released), matched to the claim by the reason the pack's drafter gave it."""
    from aughor.ontology.drafts import load_draft
    from aughor.ontology.explorer import proposal_tier
    from aughor.packs.drafter import link_reason, part_reason
    po = _structure_of(pack)
    if po is None:
        return {}
    by_reason: dict[str, str] = {}
    for obj in po.objects:
        for part in obj.parts:
            by_reason[part_reason(pack.id, obj.name, part)] = f"structure:part:{obj.name}/{part}"
    for lk in po.links:
        by_reason[link_reason(pack.id, lk)] = f"structure:link:{lk.from_object}>{lk.to_object}"
    processes = {proc.name for proc in po.processes}
    prefix = f"pack:{pack.id}@"
    out: dict[str, dict] = {}
    for proposal in load_draft(connection_id, graph.schema_name).proposals.values():
        if not (proposal.provenance or "").startswith(prefix):
            continue
        if proposal_tier(graph, proposal) not in ("withdrawn", "released"):
            continue
        said = proposal.said or {}
        key = ""
        if proposal.kind == "process" and str(said.get("id") or "") in processes:
            key = f"structure:process:{said.get('id')}"
        elif proposal.kind in ("part", "link", "link_name"):
            key = by_reason.get(str(said.get("reason") or ""), "")
        if not key:
            continue
        tail = proposal.provenance[len(prefix):]
        version = int(tail) if tail.isdigit() else None
        out[key] = {"in": version, "where": "ontology draft", "hash": (snap_items.get(key) or {}).get("hash")}
    return out


# ── the diff and the upgrade ────────────────────────────────────────────────────────────────

def _offers_again(item: dict, stone: Optional[dict]) -> bool:
    """Whether an added or changed item is offered: always, unless a person declined it and its content has not
    changed since (or no record says what was declined, when it is never offered again)."""
    if stone is None:
        return True
    return stone.get("hash") is not None and stone["hash"] != item["hash"]


def _row(key: str, item: dict, *, was: Optional[dict], stone: Optional[dict], change: str) -> dict:
    kind = item["kind"]
    if change == "removed":
        offer, why = False, REMOVED_NOTE
    elif change == "unchanged":
        offer, why = False, "declined, and unchanged since — not offered again"
    elif kind == "metric":
        offer, why = False, METRIC_NOTE
    elif kind == "structure":
        offer, why = False, STRUCTURE_NOTE
    else:
        offer = _offers_again(item, stone)
        why = "" if offer else ("declined, and unchanged since — not offered again" if stone and stone.get("hash")
                                else "declined — not offered again")
        if offer and stone is not None:
            why = "declined before, and changed since — offered again"
    return {"key": key, "kind": kind, "label": item["label"], "said": item.get("said", ""),
            "was": (was or {}).get("said", "") if change == "changed" else "",
            "ref": item.get("ref") or {}, "declined": stone is not None,
            "declined_in": (stone or {}).get("in"), "will_offer": offer, "why": why}


def diff(pack: Pack, install: dict, *, connection_id: str, schema: str = "", graph=None) -> dict[str, Any]:
    """The installed snapshot against the pack as it stands: what was added, changed and removed, each item a person
    declined marked with the version it was declined in, and the unchanged items they declined, which stay declined."""
    g = graph if graph is not None else _graph(connection_id, schema)
    snapshot = install.get("offered") or {}
    recorded = bool(snapshot.get("items") is not None and "version" in snapshot)
    installed = int(snapshot.get("version")) if recorded else int(install.get("version") or 0)
    then = snapshot.get("items") or {} if recorded else {}
    now = offered(pack, graph=g)["items"]
    stones, unread = declined(pack, connection_id, schema, graph=g, snapshot=snapshot if recorded else None)

    added, changed, removed, kept = [], [], [], []
    for key, item in now.items():
        was = then.get(key)
        if was is None:
            added.append(_row(key, item, was=None, stone=stones.get(key), change="added"))
        elif was.get("hash") != item["hash"]:
            changed.append(_row(key, item, was=was, stone=stones.get(key), change="changed"))
        elif key in stones:
            kept.append(_row(key, item, was=was, stone=stones[key], change="unchanged"))
    for key, was in then.items():
        if key not in now:
            removed.append(_row(key, was, was=was, stone=stones.get(key), change="removed"))
    order = {k: i for i, k in enumerate(KINDS)}
    for rows in (added, changed, removed, kept):
        rows.sort(key=lambda r: (order.get(r["kind"], 9), r["label"].lower(), r["key"]))
    available = int(pack.manifest.version or 0)

    def counts(rows: list[dict]) -> dict[str, int]:
        return {k: sum(1 for r in rows if r["kind"] == k) for k in KINDS}

    out = {
        "pack": pack.id, "connection_id": connection_id, "schema": schema or "",
        "installed": installed, "available": available, "recorded": recorded,
        "bound_by": install.get("bound_by") or "", "bound_at": install.get("updated_at") or "",
        "upgrade_available": available > installed or bool(added or changed or removed),
        "added": added, "changed": changed, "removed": removed, "kept_declined": kept,
        "counts": {"added": counts(added), "changed": counts(changed), "removed": counts(removed),
                   "kept_declined": counts(kept)},
        "will_offer": sum(1 for r in [*added, *changed] if r["will_offer"]),
        "not_read": unread,
    }
    if not recorded:
        out["note"] = UNRECORDED
    elif available == installed and (added or changed or removed):
        out["note"] = f"the pack changed without a new version: it still reads v{available}"
    return out


def _tolerated(fn: Callable[[], dict], what: str, connection_id: str) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — the upgrade stands; what could not be proposed is said
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"an upgraded pack's {what} could not be proposed", counter=f"packs.upgrade.{what}",
                 conn_id=connection_id)
        return {"note": f"{what} could not be proposed: {str(exc)[:160]}"}


def _supersede_stale(pack: Pack, connection_id: str, alerts: dict[tuple[str, str], str], target: int) -> list[str]:
    """A side offered again under a new band leaves the earlier offer pending beside it: that one is superseded, with
    history intact, so a person is never offered the old band and the new one side by side."""
    from aughor.actions.inbox import supersede_proposal
    gone: list[str] = []
    for (mid, side), rows in _alert_proposals(pack, connection_id).items():
        suffix = alerts.get((mid, side))
        if not suffix or not any((p.call_id or "").endswith(suffix) for p in rows):
            continue          # nothing offered under the new band (its metric is not registered, say): the old stands
        for p in rows:
            if p.status == "pending" and not (p.call_id or "").endswith(suffix) \
                    and supersede_proposal(p.id, actor=f"pack:{pack.id}:upgrade", note=f"superseded by v{target} of the pack"):
                gone.append(p.id)
    return gone


def apply(pack: Pack, install: dict, binding: dict, *, by: str, connection_id: str, schema: str = "", graph=None,
          run_sql=None, today=None) -> dict[str, Any]:
    """Upgrade the binding to the manifest's version: propose what is new or changed (never an unchanged item a person
    declined), keep the role map, and record the new snapshot. Returns what was proposed and the new binding."""
    from aughor.packs.bindings import save_binding
    from aughor.packs.connect import alert_proposals_for, propose_terms
    g = graph if graph is not None else _graph(connection_id, schema)
    d = diff(pack, install, connection_id=connection_id, schema=schema, graph=g)
    target = d["available"]
    offer = [r for r in [*d["added"], *d["changed"]] if r["will_offer"]]
    terms = {(r["ref"]["subject_kind"], r["ref"]["subject_id"], r["ref"]["synonym"]) for r in offer if r["kind"] == "term"}
    alerts = {(r["ref"]["prior"], r["ref"]["side"]): (f"@v{target}" if (r in d["changed"] or r["declined"]) else "")
              for r in offer if r["kind"] == "alert"}
    out: dict[str, Any] = {"pack": pack.id, "connection_id": connection_id, "schema": schema or "",
                           "from": d["installed"], "to": target}
    out["terms"] = _tolerated(lambda: propose_terms(pack, connection_id, schema_name=schema, graph=g, only=terms),
                              "terms", connection_id) if terms else {"proposed": 0, "note": "no new term to propose"}
    if alerts:
        out["alerts"] = _tolerated(lambda: alert_proposals_for(pack, connection_id, run_sql=run_sql, today=today,
                                                               only=alerts), "alerts", connection_id)
        out["alerts"]["superseded"] = _supersede_stale(pack, connection_id, alerts, target)
    else:
        out["alerts"] = {"staged": [], "note": "no new or changed alert to propose"}
    out["metrics"] = {"added": d["counts"]["added"]["metric"], "changed": d["counts"]["changed"]["metric"], "note": METRIC_NOTE}
    out["structure"] = {"added": d["counts"]["added"]["structure"], "changed": d["counts"]["changed"]["structure"],
                        "note": STRUCTURE_NOTE}
    held = [r for r in [*d["added"], *d["changed"], *d["kept_declined"]] if r["declined"] and not r["will_offer"]]
    out["kept_declined"] = sum(1 for r in held if r["kind"] in ("term", "alert"))
    record = install_record(pack, by=by, graph=g)
    # A decline that still stands is carried into the new snapshot, so the next version's diff still says which
    # version it was declined in; one offered again here is not carried.
    for r in held:
        if r["key"] in record["offered"]["items"] and r["declined_in"] is not None:
            record["offered"]["items"][r["key"]]["declined_in"] = r["declined_in"]
    record["offered"]["upgraded_from"] = d["installed"]
    out["binding"] = save_binding(pack.id, connection_id, dict(binding.get("bindings") or {}), version=target,
                                  verified=bool(binding.get("verified")), schema=schema or "", installed=record)
    out["binding"]["bound_by"] = record["bound_by"]
    return out
