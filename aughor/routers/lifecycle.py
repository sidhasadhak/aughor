"""Artifact-lifecycle routes — history, publish, revert, freeze. Wave V6.

The serving half of Waves V3/V4: everything a version-history panel, a diff view and a
lock-and-as-of badge needs, behind the same flags as the machinery underneath. Every route
404s when its flag is off, so the default surface is byte-identical.

One shape is deliberate throughout: **a refused or unhonourable pin is an error with a
reason, never a silent fall-back to live data.** ``FreezeRefused`` becomes a 409 (the request
was understood and is being declined, with the reason) and ``FrozenDataGoneError`` a 410
(the thing you pinned is gone) — so a UI can render the sentence rather than inventing one.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


class RevisionOut(BaseModel):
    version: int
    state: str
    created_at: str = ""
    published_at: str = ""
    artifact_id: str = ""


class HistoryOut(BaseModel):
    natural_key: str
    revisions: list[RevisionOut] = []
    published_version: Optional[int] = None
    editor_version: Optional[int] = None


class ChangeOut(BaseModel):
    kind: str
    path: str
    to_path: str = ""
    describe: str


class DiffOut(BaseModel):
    from_version: int
    to_version: int
    changes: list[ChangeOut] = []
    summary: dict[str, int] = {}


class FreezeOut(BaseModel):
    frozen: bool
    version: Optional[int] = None
    mode: Optional[str] = None
    as_of: str = ""
    data_version: str = ""
    status: str = "ok"
    reason: str = ""
    describe: str = ""


class FreezeIn(BaseModel):
    connection_id: str
    version: int
    tables: list[str] = []


def _rev_out(r) -> RevisionOut:
    return RevisionOut(version=r.version, state=r.state, created_at=r.created_at,
                       published_at=r.published_at, artifact_id=r.artifact_id)


@router.get("/{kind}/history", response_model=HistoryOut)
def get_history(kind: str, natural_key: str = Query(...)):
    """Every stored version of an artifact, newest first, plus what each audience resolves to.

    ``published_version`` vs ``editor_version`` is save≠publish made visible: when they
    differ, an editor has unpublished work and a viewer is still on the older content.
    """
    from aughor.kernel.lifecycle import history, resolve

    revs = history(kind, natural_key)
    viewer = resolve(kind, natural_key, audience="viewer")
    editor = resolve(kind, natural_key, audience="editor")
    return HistoryOut(
        natural_key=natural_key,
        revisions=[_rev_out(r) for r in revs],
        published_version=viewer.version if viewer else None,
        editor_version=editor.version if editor else None,
    )


@router.get("/{kind}/diff", response_model=DiffOut)
def get_diff(kind: str, natural_key: str = Query(...),
             from_version: int = Query(...), to_version: int = Query(...)):
    """The changelog between two versions — moves reported as moves."""
    from aughor.kernel.lifecycle import diff_versions

    d = diff_versions(kind, natural_key, from_version, to_version)
    if d is None:
        raise HTTPException(status_code=404, detail="one or both versions do not exist")
    return DiffOut(
        from_version=d.from_version, to_version=d.to_version, summary=d.summary,
        changes=[ChangeOut(kind=c.kind, path=c.path, to_path=c.to_path,
                           describe=c.describe()) for c in d.changes],
    )


@router.post("/{kind}/publish", response_model=RevisionOut)
def post_publish(kind: str, natural_key: str = Query(...),
                 version: Optional[int] = Query(default=None)):
    """Publish a version (default: the latest draft), making it what viewers resolve."""
    from aughor.kernel.lifecycle import publish

    rev = publish(kind, natural_key, version=version)
    if rev is None:
        raise HTTPException(status_code=404, detail="nothing to publish for this artifact")
    return _rev_out(rev)


@router.post("/{kind}/revert", response_model=RevisionOut)
def post_revert(kind: str, natural_key: str = Query(...), to_version: int = Query(...),
                publish_now: bool = Query(default=False)):
    """Restore an earlier version's content as a NEW version (history is never rewound)."""
    from aughor.kernel.lifecycle import revert

    rev = revert(kind, natural_key, to_version, publish_now=publish_now)
    if rev is None:
        raise HTTPException(status_code=404, detail=f"version {to_version} does not exist")
    return _rev_out(rev)


@router.get("/{kind}/freeze", response_model=FreezeOut)
def get_freeze(kind: str, natural_key: str = Query(...)):
    """The pin on an artifact and whether it can still be honoured.

    A drifted detect-only pin is reported as ``drifted`` with its reason rather than as
    ``ok`` — the badge has to be able to say "this lags".
    """
    from aughor.kernel.freeze import frozen, verify

    pin = frozen(kind, natural_key)
    if pin is None:
        return FreezeOut(frozen=False)
    status, reason = verify(kind, natural_key)
    return FreezeOut(frozen=True, version=pin.version, mode=pin.mode, as_of=pin.as_of,
                     data_version=pin.data_version, status=status, reason=reason,
                     describe=pin.describe())


@router.post("/{kind}/freeze", response_model=FreezeOut)
def post_freeze(kind: str, body: FreezeIn, natural_key: str = Query(...)):
    """Pin an artifact to a version and the data behind it.

    **409 when the freeze is refused.** Accepting a pin that cannot be honoured would put a
    lock icon on a guarantee that does not exist, so the refusal and its reason travel to the
    caller instead.
    """
    from aughor.kernel.freeze import FreezeRefused, freeze

    try:
        pin = freeze(kind, natural_key, version=body.version,
                     connection_id=body.connection_id, tables=body.tables)
    except FreezeRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if pin is None:
        raise HTTPException(status_code=409, detail="nothing about this artifact can be pinned")
    return FreezeOut(frozen=True, version=pin.version, mode=pin.mode, as_of=pin.as_of,
                     data_version=pin.data_version, status="ok",
                     reason="pinned", describe=pin.describe())


@router.delete("/{kind}/freeze", response_model=FreezeOut)
def delete_freeze(kind: str, natural_key: str = Query(...)):
    """Unfreeze — return the artifact to following live data."""
    from aughor.kernel.freeze import unfreeze

    unfreeze(kind, natural_key)
    return FreezeOut(frozen=False, reason="unfrozen")


@router.get("/{kind}/frozen-content")
def get_frozen_content(kind: str, natural_key: str = Query(...)):
    """The pinned content itself.

    **410 when the pin can no longer be honoured**, carrying the as-of stamp and the reason.
    This route deliberately has no live fall-back: a frozen label over live numbers is worse
    than an error, because the reader cannot tell the difference.
    """
    from aughor.kernel.freeze import FrozenDataGoneError, read_frozen

    try:
        rev, status, reason = read_frozen(kind, natural_key)
    except FrozenDataGoneError as exc:
        raise HTTPException(
            status_code=410,
            detail={"message": str(exc), "as_of": exc.as_of, "reason": exc.reason},
        ) from exc
    return {"version": rev.version, "state": rev.state, "body": rev.body,
            "status": status, "reason": reason}
