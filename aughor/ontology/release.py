"""Arc OC-2 — the release: what a scope's consumers read is what a person published (ROADMAP §3.56).

Until now a declaration was served the moment its door wrote it, so the explorer's proposals reached the agent before
anyone confirmed them, and moving a promise from two days to three silently changed what every claim computed under
it meant. Behind `ontology.release`:

* **A change waits in the draft.** The declaration store routes a write by what it says (`overrides._route`): a
  verdict written back stays where it was measured, a change waits in the draft layer, a withdrawal waits as a marker.
  The agent, the Briefing, metrics and automations read the published declarations; the ontology's own editing doors
  and screens read the draft laid over them (`overrides.viewing("draft")`).
* **The draft is read as a diff.** Each change carries its class from the compatibility catalogue
  (`ontology.compatibility`) — ERR, MEANING, WARN or SAFE — what changed field by field, and what it touches: the
  automations, the Record's claims and the cockpit cards that name it.
* **Publishing is a person's act.** It is refused while an ERR stands. It moves each change into the published tree
  (each a version in the declaration's history), records the release — every element and the version it pins, and a
  hash of the whole — and restates every claim a MEANING change touches, so a number computed under the old meaning says so.
* **Claims pin their release.** A claim booked while releases are on names the release in force in
  `definition_version` (`<connection>/<schema>@<n>`).

The first release of a scope is recorded at its first change: the declarations in force before anything waited. An
organisation's ontology stays outside releases for now — its declarations are written as before.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: The lifecycle kind a scope's releases are kept under — one artifact per scope, one version per release.
KIND = "ontology_release"


class ReleaseRefused(ValueError):
    """Publishing was refused — the reason is the message."""


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled("ontology.release")


def _key(conn: str, schema: str) -> str:
    return f"ontology-release:{conn}/{schema or 'default'}"


def release_id(conn: str, schema: str, number: int) -> str:
    return f"{conn}/{schema or 'default'}@{number}"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _published(conn: str, schema: str) -> list:
    from aughor.ontology.overrides import load_overrides, viewing
    with viewing("published"):
        return load_overrides(conn, schema)


def _snapshot(conn: str, schema: str) -> dict:
    """Every published declaration of the scope, with the history version it is and a hash of what it says."""
    from aughor.kernel import lifecycle
    from aughor.ontology import history
    from aughor.ontology.overrides import declaration_content
    out = {}
    for ov in _published(conn, schema):
        key = history.element_key(conn, schema, ov.target_kind, ov.target_id)
        kept = [r for r in lifecycle.history(history.KIND, key, limit=50) if r.state != "draft"]
        out[key] = {"kind": ov.target_kind, "target_id": ov.target_id, "hash": _hash(declaration_content(ov)),
                    "version": kept[0].version if kept else None}
    return out


def releases(conn: str, schema: str) -> list[dict]:
    """The scope's releases, newest first."""
    from aughor.kernel import lifecycle
    out = []
    for rev in lifecycle.history(KIND, _key(conn, schema), limit=200):
        body = rev.body or {}
        out.append({"number": rev.version, "id": release_id(conn, schema, rev.version), "at": rev.created_at,
                    "by": rev.by, "note": rev.note, "elements": len(body.get("elements") or {}),
                    "hash": body.get("hash", ""), "changes": body.get("changes", [])})
    return out


def current(conn: str, schema: str) -> Optional[dict]:
    rows = releases(conn, schema)
    return rows[0] if rows else None


def current_id(conn: str, schema: str) -> str:
    row = current(conn, schema)
    return row["id"] if row else ""


def connection_scope(conn: str) -> str:
    """A connection's configured schema — the scope a read of it with no schema named is served from."""
    try:
        from aughor.db.registry import get_meta
        return (get_meta(conn) or {}).get("schema_name") or "default"
    except Exception:  # noqa: BLE001 — an unregistered connection has no configured schema; read as the default
        return "default"


def current_id_for_connection(conn: str) -> str:
    """The release in force on a connection's configured schema — what a claim booked on it pins. "" when none."""
    return current_id(conn, connection_scope(conn))


def _record(conn: str, schema: str, *, by: str, note: str, changes: list[dict]) -> dict:
    from aughor.kernel import lifecycle
    elements = _snapshot(conn, schema)
    body = {"elements": elements, "hash": _hash(elements), "changes": changes}
    rev = lifecycle.record(KIND, _key(conn, schema), body, "published", by=by, note=note, conn_id=conn)
    return {"number": rev.version, "id": release_id(conn, schema, rev.version), "elements": len(elements),
            "hash": body["hash"]}


def ensure_first_release(conn: str, schema: str) -> None:
    """Record release 1 — the declarations in force before the scope's first change waited — once. A no-op when
    releases are off or the scope already has one."""
    if not enabled() or current(conn, schema) is not None:
        return
    _record(conn, schema, by="", note="the declarations in force when releases were turned on", changes=[])


def _graph(conn: str, schema: str):
    from aughor.ontology.overrides import viewing
    from aughor.ontology.store import load_latest_ontology
    with viewing("published"):
        return load_latest_ontology(conn, schema)


def element_names(kind: str, target_id: str, fields: Optional[dict]) -> set[str]:
    """The names an element is read by — what a claim, a card or an automation names when it reads it: a process's
    derived segments, lags and breach rates; a rule's segment; a segment's, a metric's or an entity's id."""
    names = {target_id}
    if kind in ("object_set", "computed_property") and "::" in target_id:
        names.add(target_id.split("::", 1)[1])
    if kind == "link" and fields and fields.get("name"):
        names.add(str(fields["name"]))
    if kind == "process" and fields:
        try:
            from aughor.ontology.derived import process_derivations
            from aughor.ontology.processes import process_from_fields
            d = process_derivations(process_from_fields(target_id, fields))
            names |= {x.name for x in (*d.segments, *d.properties, *d.metrics)}
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"the names process '{target_id}' derives could not be read; its claims are matched by id",
                     counter="ontology.release")
    return names


def _touches(conn: str, names: set[str], automations: list[dict], metrics: list[dict] = ()) -> dict:
    """What names one of ``names``: the Record's current claims on the connection, cockpit cards, and the automations
    and keyed metrics (Arc OC-3) the dependents index found."""
    claims, cards = [], []
    try:
        from aughor.record.claims import list_claims
        for c in list_claims(conn_id=conn, limit=5000):
            refs = {c.statement.metric, c.statement.object_set} | (
                {c.about.key} if c.about.kind in ("type", "segment", "object") else set())
            if names & {r for r in refs if r}:
                claims.append({"id": c.id, "key": c.key, "text": c.statement.text[:200],
                               "definition_version": c.definition_version})
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the claims a change touches could not be read", counter="ontology.release")
    try:
        from aughor.dashboard.store import list_cards
        for card in list_cards(connection_id=conn):
            if card.provenance.metric and card.provenance.metric in names:
                cards.append({"id": card.id, "title": card.title})
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the cards a change touches could not be read", counter="ontology.release")
    out = {"claims": claims, "cards": cards,
           "automations": [{"id": a["id"], "name": a["name"], "how": a["how"]} for a in automations],
           "metrics": [{"id": m["id"], "name": m["name"], "how": m["how"]} for m in metrics]}
    from aughor.kernel.flags import flag_enabled
    if flag_enabled("ontology.cockpit_pieces"):
        # Arc OC-4 — a cockpit's pieces name the process, the entity, the segment and the action they read.
        try:
            from aughor.cockpit.pieces import cockpits_reading
            out["cockpits"] = cockpits_reading(conn, names)
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the cockpits a change touches could not be read", counter="ontology.release")
            out["cockpits"] = []
    return out


def _watched_promises(conn: str, process_id: str) -> set[str]:
    from aughor.automations.store import list_automations
    out = set()
    for a in list_automations(conn_id=conn):
        for c in a.conditions:
            if c.kind == "promise_breached" and str(c.config.get("process") or "") == process_id:
                out.add(str(c.config.get("promise") or "") or "*")
    return out


def changes(conn: str, schema: str) -> list[dict]:
    """Every change waiting in the scope's draft, as a person reads it before publishing: the element, whether it is
    added, changed or withdrawn, its class and reasons, what changed field by field, and what it touches."""
    from aughor.kernel import lifecycle
    from aughor.ontology import history
    from aughor.ontology.compatibility import classify
    from aughor.ontology.dependents import dependents_of
    from aughor.ontology.overrides import draft_entries, find_override, viewing
    graph = _graph(conn, schema)
    out = []
    for kind, target_id, drafted, withdrawn in draft_entries(conn, schema):
        with viewing("published"):
            published = find_override(conn, schema, kind, target_id)  # type: ignore[arg-type]
        before = published.fields if published is not None else None
        after = drafted.fields if drafted is not None else None
        if before is not None and after is not None and before == after and \
                (published.source, published.note) == (drafted.source, drafted.note):
            continue                                            # a verdict copied up, nothing said differently
        deps = dependents_of(graph, conn, kind, target_id) if published is not None else []
        watched = _watched_promises(conn, target_id) if kind == "process" else set()
        if "*" in watched:                                      # a trigger on the whole process watches every promise
            watched |= {(s.get("promise") or {}).get("name") or s.get("name")
                        for s in (before or {}).get("stages") or [] if s.get("promise")}
        cls, reasons = classify(kind, before, after, dependents=deps, binding=drafted.binding if drafted else None,
                                watched_promises=watched)
        if drafted is not None and "model" in (str((after or {}).get("origin") or ""), drafted.source):
            cls = "ERR"                                         # §6 item 50(f): the release holds what a person confirmed
            reasons = [{"class": "ERR", "why": "a model proposed it and no person has confirmed it — confirm it, or "
                                               "discard it from the draft"}] + reasons
        names = element_names(kind, target_id, before or after) | element_names(kind, target_id, after or before)
        out.append({
            "element": history.element_key(conn, schema, kind, target_id), "kind": kind, "target_id": target_id,
            "change": "withdrawn" if drafted is None else ("added" if published is None else "changed"),
            "class": cls, "reasons": reasons,
            "fields": [c.describe() for c in lifecycle.changelog(before or {}, after or {})],
            "touches": _touches(conn, names, [d for d in deps if d["consumer"] == "automation"],
                                [d for d in deps if d["consumer"] == "metric"])
            if cls in ("ERR", "MEANING") else {"claims": [], "cards": [], "automations": [], "metrics": []},
            "by": (drafted or withdrawn).edited_by if (drafted or withdrawn) is not None else "",
        })
    order = {"ERR": 0, "MEANING": 1, "WARN": 2, "SAFE": 3}
    return sorted(out, key=lambda r: (order[r["class"]], r["kind"], r["target_id"]))


def _restate(conn: str, rows: list[dict], before_id: str, after_id: str, by: str) -> list[str]:
    """Restate every current claim a MEANING change touches: the same statement, marked as computed under the release
    before — and the inquiries and decisions that stood on it are told, the Record's own restatement path."""
    from aughor.record.claims import book, latest, restated_consequences
    restated = []
    for row in rows:
        if row["class"] != "MEANING":
            continue
        said = "; ".join(r["why"] for r in row["reasons"] if r["class"] == "MEANING")
        for c in row["touches"]["claims"]:
            prior = latest(c["key"])
            if prior is None or prior.extra.get("definition_changed", {}).get("to_release") == after_id:
                continue
            new = prior.model_copy(deep=True)
            new.confidence = None
            new.definition_version = prior.definition_version or before_id
            new.extra = {**prior.extra, "definition_changed": {
                "element": row["element"], "from_release": new.definition_version, "to_release": after_id,
                "what": said, "published_by": by}}
            try:
                new_id = book(new, key=prior.key, conn_id=conn)
                restated_consequences(prior.id, new_id, how=f"computed under {new.definition_version}, before {said}")
                restated.append(new_id)
            except Exception as exc:  # noqa: BLE001
                from aughor.kernel.errors import tolerate
                tolerate(exc, f"claim {prior.id} could not be restated for release {after_id}; it still reads as it "
                              "was booked", counter="ontology.release")
    return restated


def publish(conn: str, schema: str, *, by: str) -> dict:
    """Publish the scope's draft as its next release. Refused (ReleaseRefused) while releases are off, when the draft is
    empty, or while an ERR stands — with every reason."""
    from aughor.ontology.overrides import (
        clear_draft_entry, draft_entries, organisation_scope, publish_override, publish_withdrawal,
    )
    if not enabled():
        raise ReleaseRefused("releases are off on this install — a declaration is published when it is saved")
    if organisation_scope(conn):
        raise ReleaseRefused("an organisation's ontology is not released yet — its declarations apply when saved")
    rows = changes(conn, schema)
    errs = [r for r in rows if r["class"] == "ERR"]
    if errs:
        raise ReleaseRefused("not published — " + "; ".join(
            f"{r['kind']} '{r['target_id']}': " + "; ".join(x["why"] for x in r["reasons"] if x["class"] == "ERR")
            for r in errs))
    entries = draft_entries(conn, schema)
    if not entries:
        raise ReleaseRefused("the draft holds no change to publish")
    ensure_first_release(conn, schema)
    before_id = current_id(conn, schema)
    for kind, target_id, drafted, _ in entries:
        if drafted is not None:
            publish_override(conn, schema, drafted)
        else:
            publish_withdrawal(conn, schema, kind, target_id)  # type: ignore[arg-type]
        clear_draft_entry(conn, schema, kind, target_id)  # type: ignore[arg-type]
    summary = [{"element": r["element"], "change": r["change"], "class": r["class"]} for r in rows]
    made = _record(conn, schema, by=by, note=f"{len(rows)} change{'s' if len(rows) != 1 else ''} published",
                   changes=summary)
    restated = _restate(conn, rows, before_id, made["id"], by)
    return {**made, "published": summary, "restated_claims": restated, "previous": before_id}


def discard(conn: str, schema: str, *, kind: str = "", target_id: str = "") -> int:
    """Drop changes from the scope's draft — every one, or the one ``kind``/``target_id`` names; the published
    declarations are untouched. Returns how many were dropped."""
    from aughor.ontology.overrides import clear_draft_entry, draft_entries
    dropped = 0
    for k, t, _, _ in draft_entries(conn, schema):
        if (kind and k != kind) or (target_id and t != target_id):
            continue
        clear_draft_entry(conn, schema, k, t)  # type: ignore[arg-type]
        dropped += 1
    return dropped
