"""Artifact lifecycle — save ≠ publish, versions, changelog, revert. Wave V3.

The artifacts a user actually *authors* had no version at all: a saved query, a canvas, a
dashboard card, an eval case. Update was destructive, so an editor's half-finished edit was
what every viewer saw, and "what did this look like last week" had no answer. Meanwhile four
mutually-incompatible draft state machines already existed elsewhere in the tree.

Built **on the ledger**, not beside it. ``artifact_write`` already implements
supersede-not-delete (a new row per version, the prior one stamped ``superseded_by``) and
``artifact_by_id`` already resolves an exact version — its docstring calls that "so a receipt
link is immutable", which is precisely a pin. V3 adds the publication axis and the reading
surface on top; it stores nothing of its own.

**Convergence by projection, not by rewrite.** The scoping doc proposed folding the four
draft state machines onto ``semantic/governance.py``'s four states. Building it showed that
to be the wrong move: governance's ``draft → proposed → approved → deprecated`` is a *review
workflow*, and pushing a saved query or a canvas through "proposed/approved" would invent
review ceremony where none is wanted — while ``playbook``'s auto-promotion (draft→active on
≥2 uses at ≥50%) is a policy that would have to be rewritten to fit. So the convergence is a
**projection**: each existing vocabulary maps onto one publication axis that answers the only
question a reader has — *what does a viewer see?* Nothing is forced to rename its states.

Off by default behind ``lifecycle.publish``: with the flag off nothing is written and every
wired store behaves exactly as before.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional


#: The one axis that answers "what does a viewer see?".
PublicationState = Literal["draft", "published", "archived"]

#: How each pre-existing state vocabulary projects onto that axis. This table IS the
#: convergence — a reader can now compare a metric, a play, a pack and a saved query without
#: learning four state machines, and none of them had to change.
PROJECTIONS: dict[str, dict[str, PublicationState]] = {
    # aughor/semantic/governance.py — a review workflow (metrics, contracts).
    # 'proposed' is still a draft to a VIEWER: proposing is not publishing.
    "governance": {"draft": "draft", "proposed": "draft",
                   "approved": "published", "deprecated": "archived"},
    # aughor/playbook/models.py — auto-promoted on evidence, not by a human act.
    "playbook": {"draft": "draft", "active": "published", "deprecated": "archived"},
    # aughor/packs/models.py — same three words, a different set from governance's.
    "packs": {"draft": "draft", "active": "published", "deprecated": "archived"},
    # This module's own native axis.
    "lifecycle": {"draft": "draft", "published": "published", "archived": "archived"},
}


def publication_state(vocabulary: str, status: Optional[str]) -> PublicationState:
    """Project a store's own status onto the publication axis.

    An unknown status projects to ``draft`` — the conservative direction: a viewer is shown
    nothing rather than something whose state we cannot read. (``routers/metrics.py:347``
    accepts a free-form status string with no gate at all, which is exactly why the default
    must not be ``published``.)
    """
    table = PROJECTIONS.get(vocabulary) or {}
    return table.get((status or "draft").strip().lower(), "draft")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger():
    from aughor.kernel.ledger import Ledger

    return Ledger.default()


@dataclass
class Revision:
    """One stored version of an artifact."""

    natural_key: str
    version: int
    state: PublicationState
    body: dict
    artifact_id: str = ""
    created_at: str = ""
    published_at: str = ""

    @property
    def is_published(self) -> bool:
        return self.state == "published"


def _revision(art: Optional[dict]) -> Optional[Revision]:
    if not art:
        return None
    payload = dict(art.get("payload") or {})
    meta = dict(payload.get("_lifecycle") or {})
    return Revision(
        natural_key=art.get("natural_key", ""),
        version=int(art.get("version") or 0),
        state=meta.get("state") or "draft",
        body=dict(payload.get("_body") or {}),
        artifact_id=art.get("id", ""),
        created_at=meta.get("created_at", ""),
        published_at=meta.get("published_at", ""),
    )


def _write(kind: str, natural_key: str, body: dict, state: PublicationState, *,
           published_at: str = "", conn_id: Optional[str] = None,
           org_id: Optional[str] = None) -> Revision:
    payload = {
        "_body": dict(body),
        "_lifecycle": {"state": state, "created_at": _now(), "published_at": published_at},
    }
    led = _ledger()
    led.artifact_write(kind, natural_key, payload, conn_id=conn_id, org_id=org_id)
    rev = _revision(led.artifact_latest(natural_key))
    assert rev is not None  # just written
    return rev


# ── Authoring ─────────────────────────────────────────────────────────────────

def save_draft(kind: str, natural_key: str, body: dict, *, conn_id: Optional[str] = None,
               org_id: Optional[str] = None) -> Optional[Revision]:
    """Save an edit as a NEW draft version. The published version is untouched — that is
    the whole point of save≠publish."""
    return _write(kind, natural_key, body, "draft", conn_id=conn_id, org_id=org_id)


def publish(kind: str, natural_key: str, *, version: Optional[int] = None,
            conn_id: Optional[str] = None, org_id: Optional[str] = None) -> Optional[Revision]:
    """Publish a version (default: the latest draft) by writing it forward as published.

    Writing forward rather than mutating the row in place keeps supersede-not-delete intact:
    the history still shows the draft that existed, and "when was this published" is a fact
    on a row rather than an overwritten field.
    """
    src = (
        revision(kind, natural_key, version=version) if version is not None
        else _revision(_ledger().artifact_latest(natural_key))
    )
    if src is None:
        return None
    return _write(kind, natural_key, src.body, "published", published_at=_now(),
                  conn_id=conn_id, org_id=org_id)


def revert(kind: str, natural_key: str, to_version: int, *, publish_now: bool = False,
           conn_id: Optional[str] = None, org_id: Optional[str] = None) -> Optional[Revision]:
    """Restore an earlier version's content as a NEW version — never by deleting history.

    A revert that rewound the version counter would erase the evidence that the reverted
    state ever shipped. The restored body is byte-identical to the target version's.
    """
    src = revision(kind, natural_key, version=to_version)
    if src is None:
        return None
    state: PublicationState = "published" if publish_now else "draft"
    return _write(kind, natural_key, src.body, state,
                  published_at=_now() if publish_now else "",
                  conn_id=conn_id, org_id=org_id)


# ── Reading ───────────────────────────────────────────────────────────────────

def resolve(kind: str, natural_key: str, *,
            audience: Literal["viewer", "editor"] = "viewer") -> Optional[Revision]:
    """What this audience should see.

    A **viewer** gets the newest *published* version and never an in-progress draft; an
    **editor** gets the newest version of any state, which is their working copy. This one
    function is save≠publish.
    """
    versions = history(kind, natural_key)
    if audience == "editor":
        return versions[0] if versions else None
    return next((r for r in versions if r.is_published), None)


def history(kind: str, natural_key: str, *, limit: int = 100) -> list[Revision]:
    """Every version, newest first."""
    return [r for r in (_revision(a) for a in
                        _ledger().artifact_versions(natural_key, limit=limit)) if r]


def revision(kind: str, natural_key: str, *, version: int) -> Optional[Revision]:
    """One exact version."""
    return next((r for r in history(kind, natural_key) if r.version == version), None)


# ── The changelog ─────────────────────────────────────────────────────────────

ChangeKind = Literal["add", "delete", "change", "move"]


@dataclass
class Change:
    kind: ChangeKind
    path: str
    before: Any = None
    after: Any = None
    #: For a move: where it went. Kept separate from ``path`` so a renderer can show both.
    to_path: str = ""

    def describe(self) -> str:
        if self.kind == "move":
            return f"moved {self.path} → {self.to_path}"
        if self.kind == "add":
            return f"added {self.path}"
        if self.kind == "delete":
            return f"deleted {self.path}"
        return f"changed {self.path}"


def changelog(before: Any, after: Any) -> list[Change]:
    """A structural diff of two artifact bodies, reporting **moves** as moves.

    Move detection is the part that makes a diff readable. Reordering a dashboard's cards or
    a query's dimensions is the most common edit there is, and a differ without it reports
    that every element from the move point onward was deleted and re-added — pages of noise
    for a change the user would describe in four words. Here, a value that leaves one path
    and appears at another with **no other difference** is one ``move``.
    """
    changes: list[Change] = []
    _walk(before, after, "", changes)
    return _fold_moves(changes)


def _walk(before: Any, after: Any, path: str, out: list[Change]) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(set(before) | set(after)):
            p = f"{path}.{k}" if path else str(k)
            if k not in after:
                out.append(Change("delete", p, before=before[k]))
            elif k not in before:
                out.append(Change("add", p, after=after[k]))
            else:
                _walk(before[k], after[k], p, out)
        return

    if isinstance(before, list) and isinstance(after, list):
        _diff_list(before, after, path, out)
        return

    if before != after:
        out.append(Change("change", path, before=before, after=after))


def _diff_list(before: list, after: list, path: str, out: list[Change]) -> None:
    """Diff two lists by CONTENT, so a reorder reads as moves.

    An index-wise walk cannot see a move: comparing ``[a,b,c]`` with ``[c,a,b]`` position by
    position reports three unrelated changes, which is precisely the noise this exists to
    remove. So elements are matched on content first, and only genuinely unmatched positions
    fall through to a nested comparison.
    """
    bkeys = [_content_key(x) for x in before]
    akeys = [_content_key(x) for x in after]
    if bkeys == akeys:
        return

    matched_after: set[int] = set()
    unmatched_before: list[int] = []

    for i, bk in enumerate(bkeys):
        j = next((jj for jj, ak in enumerate(akeys)
                  if ak == bk and jj not in matched_after), None)
        if j is None:
            unmatched_before.append(i)
            continue
        matched_after.add(j)
        if i != j:
            out.append(Change("move", f"{path}[{i}]", before=before[i], after=after[j],
                              to_path=f"{path}[{j}]"))

    unmatched_after = [j for j in range(len(after)) if j not in matched_after]

    # An unmatched pair at the SAME index is an element edited in place, not a
    # delete-plus-add — recurse so the report names the field that actually changed.
    for i in list(unmatched_before):
        if i in unmatched_after:
            _walk(before[i], after[i], f"{path}[{i}]", out)
            unmatched_before.remove(i)
            unmatched_after.remove(i)

    for i in unmatched_before:
        out.append(Change("delete", f"{path}[{i}]", before=before[i]))
    for j in unmatched_after:
        out.append(Change("add", f"{path}[{j}]", after=after[j]))


def _fold_moves(changes: list[Change]) -> list[Change]:
    """Pair each delete with an add carrying an equal value → one move."""
    deletes = [c for c in changes if c.kind == "delete"]
    adds = [c for c in changes if c.kind == "add"]
    used_add: set[int] = set()
    moves: list[Change] = []
    paired_del: set[int] = set()

    for di, d in enumerate(deletes):
        for ai, a in enumerate(adds):
            if ai in used_add:
                continue
            if _same_value(d.before, a.after) and d.path != a.path:
                moves.append(Change("move", d.path, before=d.before, after=a.after,
                                    to_path=a.path))
                used_add.add(ai)
                paired_del.add(di)
                break

    kept: list[Change] = []
    di = ai = 0
    for c in changes:
        if c.kind == "delete":
            if di not in paired_del:
                kept.append(c)
            di += 1
        elif c.kind == "add":
            if ai not in used_add:
                kept.append(c)
            ai += 1
        else:
            kept.append(c)
    return kept + moves


def _content_key(value: Any) -> str:
    """A stable content key, so a moved dict matches regardless of key order."""
    try:
        import json

        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return repr(value)


def _same_value(a: Any, b: Any) -> bool:
    """Equal *content* — used to pair a dict-key delete with an add (a renamed key)."""
    if a is None or b is None:
        return False
    return _content_key(a) == _content_key(b)


@dataclass
class VersionDiff:
    from_version: int
    to_version: int
    changes: list[Change] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.changes:
            out[c.kind] = out.get(c.kind, 0) + 1
        return out


def diff_versions(kind: str, natural_key: str, a: int, b: int) -> Optional[VersionDiff]:
    """The changelog between two stored versions."""
    ra, rb = revision(kind, natural_key, version=a), revision(kind, natural_key, version=b)
    if ra is None or rb is None:
        return None
    return VersionDiff(a, b, changelog(ra.body, rb.body))
