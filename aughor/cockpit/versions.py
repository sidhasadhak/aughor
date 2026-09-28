"""A cockpit's spec, kept as versions (Arc CT, CT-3; ROADMAP §3.50).

**No new store.** The Ledger already keeps versioned artifacts — ``artifact_write`` writes the
next version for a natural key and stamps ``superseded_by`` on the one before, with lineage
and a tenant — and BR-6 keeps every Briefing that way. A cockpit's spec is the same shape, so
it is an artifact of kind ``cockpit``, one natural key per canvas.

**Keeping is an act of approval, and it can be refused.** That is the difference from a
Briefing's history, which is written in passing and must never break the page it records.
Here a person approved something, so every outcome is SAID: ``kept``, ``unchanged``,
``refused`` (the validator's sentences), ``not_checked`` (the validator could not run — and
then nothing is kept), or ``failed`` (the write itself went wrong).

**Provenance is required.** A spec is kept with the name of the person who approved it and
where it came from. Without both it is refused.

**Supersede, never delete.** An edit is the next version. Going back is the next version too:
``restore`` keeps an earlier spec again, checked against the canvas as it is today. Retiring a
cockpit is a version that says so, and its history stays readable.

**A version is a change of the spec**, not an act of approving: approving the same spec twice
writes nothing, by the same reasoning that keeps a Briefing from versioning on every visit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from aughor.cockpit import validate as _validate
from aughor.kernel.errors import tolerate

#: The artifact kind. A cockpit's history is ``artifact_versions(natural_key(canvas_id))``.
KIND = "cockpit"

KEPT = "kept"
UNCHANGED = "unchanged"
REFUSED = "refused"
NOT_CHECKED = "not_checked"
FAILED = "failed"


@dataclass(frozen=True)
class Kept:
    """What happened when a spec was offered for keeping. ``kept`` is True only when a new
    version was written."""
    status: str
    version: Optional[int] = None
    artifact_id: str = ""
    sentences: tuple[str, ...] = ()

    @property
    def kept(self) -> bool:
        return self.status == KEPT

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "kept": self.kept, "version": self.version,
                "artifact_id": self.artifact_id, "sentences": list(self.sentences)}


def natural_key(canvas_id: str) -> str:
    return f"cockpit:{canvas_id}"


def _canonical(spec: Any) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)


def changes(before: Optional[dict], after: Optional[dict]) -> dict[str, list[str]]:
    """Which elements a version added, removed or changed, by their keys. What a history
    shows beside a version, so a reader need not compare two specs by eye."""
    b = (before or {}).get("elements") or {}
    a = (after or {}).get("elements") or {}
    return {
        "added": sorted(k for k in a if k not in b),
        "removed": sorted(k for k in b if k not in a),
        "changed": sorted(k for k in a if k in b and a[k] != b[k]),
    }


def _mine(row: Optional[dict]) -> Optional[dict]:
    """The row, if it is this tenant's cockpit. The Ledger reads a natural key across
    tenants; a canvas id is not a secret, so the tenant is checked here."""
    from aughor.org.context import current_org_id
    if not row or row.get("kind") != KIND:
        return None
    if (row.get("org_id") or "default") != current_org_id():
        return None
    return row if isinstance(row.get("payload"), dict) else None


def _entry(row: dict, *, with_spec: bool) -> dict[str, Any]:
    p = row["payload"]
    out = {
        "version": row.get("version"),
        "artifact_id": row.get("id") or "",
        "kept_at": row.get("created_at") or "",
        "current": row.get("superseded_by") is None,
        "retired": bool(p.get("retired")),
        "approved_by": p.get("approved_by") or "",
        "source": p.get("source") or "",
        "note": p.get("note") or "",
        "vocabulary_version": p.get("vocabulary_version") or 0,
        "cards": list(p.get("cards") or []),
        "changes": p.get("changes") or {"added": [], "removed": [], "changed": []},
    }
    if with_spec:
        out["spec"] = p.get("spec")
    return out


def _latest_row(canvas_id: str) -> Optional[dict]:
    from aughor.kernel.ledger import Ledger
    return _mine(Ledger.default().artifact_latest(natural_key(canvas_id)))


def latest(canvas_id: str) -> Optional[dict]:
    """The newest version, with its spec — or None when this canvas never had a cockpit.
    A retired cockpit is returned, with ``retired`` True and no spec: that it was retired,
    when and by whom is something a reader is owed."""
    row = _latest_row(canvas_id)
    return _entry(row, with_spec=True) if row else None


def history(canvas_id: str, *, limit: int = 50) -> list[dict]:
    """Every version, newest first, without the specs."""
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().artifact_versions(natural_key(canvas_id), limit=limit)
    return [_entry(r, with_spec=False) for r in rows if _mine(r)]


def version(canvas_id: str, number: int) -> Optional[dict]:
    """One version, with its spec."""
    from aughor.kernel.ledger import Ledger
    for row in Ledger.default().artifact_versions(natural_key(canvas_id), limit=1000):
        if row.get("version") == number and _mine(row):
            return _entry(row, with_spec=True)
    return None


def _provenance_missing(approved_by: str, source: str) -> Optional[Kept]:
    if not (approved_by or "").strip():
        return Kept(REFUSED, sentences=(
            "A cockpit is kept with the name of the person who approved it. None was given.",))
    if not (source or "").strip():
        return Kept(REFUSED, sentences=(
            "A cockpit is kept with where it came from — a proposal, or a person's own hand. "
            "Nothing was given.",))
    return None


def _write(canvas_id: str, payload: dict, prior: Optional[dict], why: str) -> Kept:
    from aughor.canvas.store import get_canvas
    from aughor.kernel.ledger import Ledger
    try:
        canvas = get_canvas(canvas_id)
        art_id = Ledger.default().artifact_write(
            KIND, natural_key(canvas_id), payload,
            conn_id=(canvas.primary_connection_id if canvas else None), canvas_id=canvas_id,
            lineage=[("supersedes", prior["id"], why)] if prior else None)
    except Exception as exc:
        tolerate(exc, "a cockpit's version could not be written; the caller is told it FAILED",
                 counter="cockpit.version.write", canvas_id=canvas_id)
        return Kept(FAILED, sentences=(
            f"The cockpit could not be kept: {type(exc).__name__}: {exc}. Nothing was changed.",))
    return Kept(KEPT, version=int((prior or {}).get("version") or 0) + 1, artifact_id=art_id)


def keep(canvas_id: str, spec: Any, *, approved_by: str, source: str, note: str = "",
         also_known: Iterable[str] = ()) -> Kept:
    """Keep ``spec`` as this canvas's cockpit: the next version, or nothing at all.

    ``approved_by`` is the person who approved it; ``source`` is where it came from.
    ``also_known`` names cards the same approval has just created.
    """
    from aughor.canvas.store import get_canvas

    missing = _provenance_missing(approved_by, source)
    if missing:
        return missing
    if get_canvas(canvas_id) is None:
        return Kept(REFUSED, sentences=(
            f'The canvas "{canvas_id}" does not exist, so no cockpit can be kept for it.',))

    verdict = _validate.check_spec_for_canvas(spec, canvas_id, also_known=also_known)
    if verdict.status == _validate.NOT_CHECKED:
        return Kept(NOT_CHECKED, sentences=verdict.sentences)
    if not verdict.accepted:
        return Kept(REFUSED, sentences=verdict.sentences)

    prior = _latest_row(canvas_id)
    before = (prior or {}).get("payload") or {}
    if prior and not before.get("retired") and _canonical(before.get("spec")) == _canonical(spec):
        return Kept(UNCHANGED, version=prior.get("version"), artifact_id=prior.get("id") or "")

    vocab = _validate.vocabulary() or {}
    payload = {
        "spec": spec, "retired": False,
        "approved_by": approved_by.strip(), "source": source.strip(), "note": note.strip(),
        "vocabulary_version": int(vocab.get("version") or 0),
        "cards": list(verdict.cards),
        "changes": changes(before.get("spec"), spec),
    }
    return _write(canvas_id, payload, prior, "the spec changed")


def restore(canvas_id: str, number: int, *, approved_by: str) -> Kept:
    """Go back to an earlier version by keeping its spec AGAIN, as the newest. It is checked
    against the canvas as it is today: a card removed since then makes the restore a refusal,
    which is the honest answer."""
    earlier = version(canvas_id, number)
    if earlier is None:
        return Kept(REFUSED, sentences=(f"This cockpit has no version {number}.",))
    if earlier["retired"] or earlier.get("spec") is None:
        return Kept(REFUSED, sentences=(
            f"Version {number} is the one that retired the cockpit; it holds no spec to go back to.",))
    return keep(canvas_id, earlier["spec"], approved_by=approved_by,
                source=f"restored from version {number}")


def retire(canvas_id: str, *, approved_by: str, note: str = "") -> Kept:
    """Retire this canvas's cockpit. Written as a version that says so: the history stays, and
    a later ``keep`` or ``restore`` brings a cockpit back as the version after it."""
    missing = _provenance_missing(approved_by, "retired")
    if missing:
        return missing
    prior = _latest_row(canvas_id)
    if prior is None:
        return Kept(REFUSED, sentences=("This canvas has no cockpit to retire.",))
    before = prior["payload"]
    if before.get("retired"):
        return Kept(UNCHANGED, version=prior.get("version"), artifact_id=prior.get("id") or "")
    payload = {
        "spec": None, "retired": True,
        "approved_by": approved_by.strip(), "source": "retired", "note": note.strip(),
        "vocabulary_version": before.get("vocabulary_version") or 0,
        "cards": [],
        "changes": changes(before.get("spec"), None),
    }
    return _write(canvas_id, payload, prior, "the cockpit was retired")
