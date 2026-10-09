"""Arc OC-1 — every declaration keeps its history (ROADMAP §3.56).

A declaration lived in one YAML file: a save replaced it and a withdrawal deleted it (`overrides._write`, `_unlink`).
So once someone moved a promise from two days to three, "what did *late* mean on 1 October" had no answer, and
AGENTS.md's *supersede, do not delete* was not true of the ontology. Behind `ontology.history` every save and every
withdrawal is also a version on the platform's one versioning substrate (`aughor/kernel/lifecycle.py`, on the
ledger's supersede-not-delete artifacts), under the element's stable id:

* **The stable id** is the declaration's scope, kind and target id — `ontology:<connection>/<schema>/<kind>/<id>`. A
  name lives in the fields (`display_name`, a link's `name`), so a rename is a new version of the same element, never
  a delete and an add. A built element's id comes from its table, so a table renamed in the warehouse is still a new
  element — said here, not solved.
* **A version is what the declaration says** — its fields, its source and its note. A measure door writes its verdict
  back into the file it read; that changes the binding, not the declaration, and is not a version (the measurement is
  journaled as `ontology.measure`).
* **History starts when it is first kept.** The first time a declaration already on the tree changes, its content as
  it stood is recorded first, in force from its own `edited_at`. Before that moment the history says it does not
  know — never that nothing was declared.

The YAML tree stays what every reader serves from; this is its record. OC-2's release reads these versions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: The lifecycle kind every declaration version is kept under.
KIND = "ontology_declaration"

#: How a version recorded from the tree, rather than by a door, says so.
BASELINE_NOTE = "on the tree before its history was kept — in force since its last edit"


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled("ontology.history")


def element_key(conn: str, schema: str, kind: str, target_id: str) -> str:
    """The element's stable id: its scope, its kind and its target id."""
    return f"ontology:{conn}/{schema or 'default'}/{kind}/{target_id}"


def _body(ov: Any) -> dict:
    return {"target_kind": ov.target_kind, "target_id": ov.target_id, "fields": dict(ov.fields or {}),
            "source": ov.source or "human", "note": ov.note or ""}


def _actor(ov: Any = None) -> str:
    from aughor.org.context import current_actor
    return current_actor() or (getattr(ov, "edited_by", "") or "")


def _latest(key: str):
    from aughor.kernel import lifecycle
    versions = lifecycle.history(KIND, key, limit=1)
    return versions[0] if versions else None


def _baseline(conn: str, key: str, prior: Any) -> None:
    from aughor.kernel import lifecycle
    lifecycle.record(KIND, key, _body(prior), "published", by=prior.edited_by or "",
                     published_at=prior.edited_at or "", note=BASELINE_NOTE, conn_id=conn)


def on_save(conn: str, schema: str, prior: Any, ov: Any) -> None:
    """Record a save that landed. ``prior`` is the declaration as it stood before the write, or None. Off: nothing."""
    if not enabled():
        return
    from aughor.kernel import lifecycle
    key = element_key(conn, schema, ov.target_kind, ov.target_id)
    latest = _latest(key)
    if latest is None and prior is not None:
        _baseline(conn, key, prior)
        latest = _latest(key)
    body = _body(ov)
    if latest is not None and latest.state == "published" and latest.body == body:
        return                      # a verdict written back, or a save that changed nothing the declaration says
    lifecycle.record(KIND, key, body, "published", by=_actor(ov), conn_id=conn)


def on_withdraw(conn: str, schema: str, prior: Any) -> None:
    """Record a withdrawal that landed, with what the declaration said when it went. Off, or nothing was there: nothing."""
    if not enabled() or prior is None:
        return
    from aughor.kernel import lifecycle
    key = element_key(conn, schema, prior.target_kind, prior.target_id)
    if _latest(key) is None:
        _baseline(conn, key, prior)
    lifecycle.record(KIND, key, _body(prior), "archived", by=_actor(), conn_id=conn)


def _effective(rev) -> str:
    """When a version took effect: a save when it was published, a withdrawal when it was made."""
    return (rev.published_at or rev.created_at) if rev.state == "published" else rev.created_at


def _version_out(rev, before) -> dict:
    from aughor.kernel import lifecycle
    changes = [c.describe() for c in lifecycle.changelog(before.body.get("fields", {}), rev.body.get("fields", {}))] \
        if before is not None else []
    return {"version": rev.version, "state": "withdrawn" if rev.state == "archived" else "declared",
            "in_force_from": _effective(rev), "recorded_at": rev.created_at, "by": rev.by, "note": rev.note,
            "fields": rev.body.get("fields", {}), "source": rev.body.get("source", ""), "changes": changes}


def versions(conn: str, schema: str, kind: str, target_id: str) -> list[dict]:
    """Every version of one declaration, newest first, each with what changed from the one before. A declaration on
    the tree that has not changed since history was first kept reads as one unrecorded version, in force since its
    last edit — so the history of something that never changed is not empty."""
    from aughor.kernel import lifecycle
    revs = lifecycle.history(KIND, element_key(conn, schema, kind, target_id), limit=500)
    if not revs:
        from aughor.ontology.overrides import find_override
        current = find_override(conn, schema, kind, target_id)  # type: ignore[arg-type]
        if current is None:
            return []
        return [{"version": None, "state": "declared", "in_force_from": current.edited_at or "", "recorded_at": "",
                 "by": current.edited_by or "", "note": BASELINE_NOTE, "fields": dict(current.fields or {}),
                 "source": current.source or "human", "changes": []}]
    oldest_first = list(reversed(revs))
    out = [_version_out(rev, oldest_first[i - 1] if i else None) for i, rev in enumerate(oldest_first)]
    return list(reversed(out))


def _moment(when: str) -> datetime:
    """An ISO moment; a bare date means the end of that day (UTC) — what was in force on it. Raises ValueError on
    anything else."""
    text = str(when).strip()
    if len(text) == 10:
        text += "T23:59:59.999999+00:00"
    at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)


def _moment_or_none(when: str) -> Optional[datetime]:
    try:
        return _moment(when)
    except (TypeError, ValueError):
        return None


def as_of(conn: str, schema: str, kind: str, target_id: str, when: str) -> dict:
    """What one declaration said at a moment — the falsifier's question, "what did *late* mean on 1 October".
    ``known`` is False when the moment precedes everything kept and the earliest version was found on the tree:
    that is said as not known, never answered as "not declared". Raises ValueError when ``when`` is not a date."""
    at = _moment(when)
    rows = list(reversed(versions(conn, schema, kind, target_id)))
    in_force = None
    for row in rows:
        start = _moment_or_none(row["in_force_from"])
        if start is not None and start <= at:
            in_force = row
    if in_force is not None:
        declared = in_force["state"] == "declared"
        return {"known": True, "state": in_force["state"], "version": in_force["version"],
                "fields": in_force["fields"] if declared else {},
                "withdrawn_fields": {} if declared else in_force["fields"],
                "in_force_from": in_force["in_force_from"]}
    if not rows:
        return {"known": False, "state": "", "version": None, "fields": {},
                "why": "nothing is declared under this id and no history is kept for it"}
    if rows[0]["note"] == BASELINE_NOTE:
        return {"known": False, "state": "", "version": None, "fields": {},
                "why": f"what is kept starts on {rows[0]['in_force_from']} — what it said before is not known"}
    return {"known": True, "state": "not declared", "version": None, "fields": {},
            "in_force_from": "", "why": f"first declared on {rows[0]['in_force_from']}"}
