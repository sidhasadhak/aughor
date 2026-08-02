"""Freeze — live by default, snapshot by choice, gone data errors loudly. Wave V4.

The rule (docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md, L337): *live-by-default + explicit
freeze with a lock icon and an
as-of timestamp; frozen artifacts whose backing data is gone error loudly.* All three
ingredients already existed in this tree and none was composed:

* ``kernel/ledger.artifact_by_id`` pins an exact artifact version ("so a receipt link is
  immutable");
* ``playbook.get_version`` pins past content;
* ``db/snapshot.data_version`` + ``execute_as_of`` pin and replay a *data* version.

This module composes them into one ``freeze`` over a Wave-V3 artifact, and it is careful
about a promise it cannot always keep.

**Two modes, named rather than assumed.** A freeze promises "you will see exactly what I
saw". On version-aware storage (DuckLake) that is deliverable: the pinned snapshot id is
replayable via ``AT (VERSION => n)`` — mode ``reproducible``. On a plain DuckDB file it is
not: the portable ``fp:`` token can only tell you the data *changed*, never reconstruct what
it was — mode ``detect_only``. Both are useful; conflating them is not, because a
``detect_only`` freeze that called itself reproducible would be exactly the
safety-by-coincidence this codebase has paid for before. When nothing can be pinned at all,
the freeze is **refused** rather than accepted and quietly not honoured.

**A frozen artifact never silently falls back to live data.** If the pin cannot be honoured,
reading it raises :class:`FrozenDataGoneError` carrying the as-of stamp and the reason. A
frozen label over live numbers is the one outcome worse than an error.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Sequence

from aughor.db.paths import state_dir
from aughor.kernel.errors import tolerate
from aughor.util.json_store import KeyedJsonStore

#: ``reproducible`` — the pinned data version can be replayed (AT VERSION).
#: ``detect_only`` — the pin can only detect that the data moved, never reconstruct it.
FreezeMode = Literal["reproducible", "detect_only"]

#: ``ok`` — the pin still holds. ``drifted`` — a detect-only pin's data has moved (the
#: artifact is still readable, but must be presented as lagging). ``gone`` — the pin cannot
#: be honoured at all; reading must fail loudly.
FreezeStatus = Literal["ok", "drifted", "gone"]

_store = KeyedJsonStore(state_dir() / "freeze_state.json", max_entries=1000)


class FreezeRefused(RuntimeError):
    """Raised when a freeze cannot be honoured *at all*, so it is not accepted.

    Better here than at read time: a user who asked to freeze deserves to hear "this
    connection cannot be frozen, because …" immediately, not to discover months later that
    the lock icon meant nothing.
    """


class FrozenDataGoneError(RuntimeError):
    """Raised when reading a frozen artifact whose pin can no longer be honoured.

    Carries the as-of stamp and the reason, because "this is frozen to 3 March and that
    snapshot no longer exists" is actionable and "an error occurred" is not.
    """

    def __init__(self, message: str, *, as_of: str = "", reason: str = ""):
        super().__init__(message)
        self.as_of, self.reason = as_of, reason


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(kind: str, natural_key: str) -> str:
    return f"{kind}|{natural_key}"


@dataclass
class Freeze:
    """A pin: an artifact version plus the data version it was computed on."""

    kind: str
    natural_key: str
    version: int
    data_version: str
    mode: FreezeMode
    as_of: str
    tables: list[str]
    connection_id: str = ""

    @property
    def is_reproducible(self) -> bool:
        return self.mode == "reproducible"

    def describe(self) -> str:
        lock = "🔒" if self.is_reproducible else "🔒(detect-only)"
        return f"{lock} v{self.version} as of {self.as_of}"


def _as_freeze(kind: str, natural_key: str, raw: dict) -> Freeze:
    return Freeze(
        kind=kind, natural_key=natural_key,
        version=int(raw.get("version") or 0),
        data_version=raw.get("data_version", ""),
        mode=raw.get("mode") or "detect_only",
        as_of=raw.get("as_of", ""),
        tables=list(raw.get("tables") or []),
        connection_id=raw.get("connection_id", ""),
    )


# ── Freezing ──────────────────────────────────────────────────────────────────

def freeze(
    kind: str, natural_key: str, *, version: int, connection_id: str,
    tables: Sequence[str] = (),
) -> Optional[Freeze]:
    """Pin ``natural_key`` at ``version`` and the data version behind it.

    Raises :class:`FreezeRefused` when no data version can be computed — the connection
    cannot be pinned, so accepting the freeze would mean showing a lock that guarantees
    nothing.
    """

    from aughor.db.connection import open_connection_for
    from aughor.db.snapshot import as_of_supported, data_version

    try:
        conn = open_connection_for(connection_id)
    except Exception as exc:
        raise FreezeRefused(
            f"cannot open connection {connection_id!r} to pin a data version: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    try:
        token = data_version(conn, tables)
        replayable = bool(token) and as_of_supported(conn)
    finally:
        try:
            conn.close()
        except Exception as exc:
            tolerate(exc, "closing the freeze probe handle is best-effort; the data version "
                          "is already captured", counter="freeze.db_close")

    if not token:
        raise FreezeRefused(
            f"cannot compute a data version for {connection_id!r} "
            f"(tables={list(tables) or 'unknown'}) — nothing to pin, so this artifact "
            "cannot be frozen. It stays live."
        )

    fz = Freeze(
        kind=kind, natural_key=natural_key, version=int(version), data_version=token,
        mode="reproducible" if replayable else "detect_only",
        as_of=_now(), tables=sorted({str(t) for t in (tables or [])}),
        connection_id=connection_id,
    )
    _store.put(_key(kind, natural_key), {
        "version": fz.version, "data_version": fz.data_version, "mode": fz.mode,
        "as_of": fz.as_of, "tables": fz.tables, "connection_id": fz.connection_id,
    })
    return fz


def unfreeze(kind: str, natural_key: str) -> bool:
    """Return an artifact to following live. True when a pin was removed."""
    had = _store.get(_key(kind, natural_key)) is not None
    _store.invalidate_prefix(_key(kind, natural_key))
    return had


def frozen(kind: str, natural_key: str) -> Optional[Freeze]:
    """The pin on this artifact, or None when it is live."""
    raw = _store.get(_key(kind, natural_key))
    return _as_freeze(kind, natural_key, raw) if raw else None


# ── Verifying ─────────────────────────────────────────────────────────────────

def verify(kind: str, natural_key: str) -> tuple[FreezeStatus, str]:
    """Can the pin still be honoured? Returns ``(status, reason)``.

    * ``reproducible`` — ``ok`` while the pinned snapshot is still replayable, ``gone`` once
      it is not. Drift is *expected* and harmless here: replay is at the pinned version.
    * ``detect_only`` — ``ok`` while the data fingerprint matches, ``drifted`` once it moves.
      Drifted is readable but must be labelled; it is never silently ``ok``.
    """
    fz = frozen(kind, natural_key)
    if fz is None:
        return "ok", "not frozen"

    from aughor.db.connection import open_connection_for
    from aughor.db.snapshot import as_of_supported, data_version, native_version_id

    try:
        conn = open_connection_for(fz.connection_id)
    except Exception as exc:
        return "gone", (f"the connection {fz.connection_id!r} behind this frozen artifact "
                        f"cannot be opened: {type(exc).__name__}: {exc}")
    try:
        current = data_version(conn, fz.tables)
        if fz.is_reproducible:
            if not as_of_supported(conn):
                return "gone", ("this artifact was frozen to a replayable snapshot, but the "
                                "connection no longer supports AS-OF reads")
            if native_version_id(fz.data_version) is None:
                return "gone", (f"the pinned data version {fz.data_version!r} is not a "
                                "replayable snapshot id")
            return "ok", f"pinned snapshot {fz.data_version} is still replayable"
        if not current:
            return "gone", ("the data behind this frozen artifact can no longer be "
                            "fingerprinted, so drift cannot be ruled out")
        if current != fz.data_version:
            return "drifted", (f"the data moved since this was frozen "
                               f"({fz.data_version} → {current}); this pin can detect the "
                               "change but cannot reconstruct the original")
        return "ok", "the data fingerprint still matches"
    finally:
        try:
            conn.close()
        except Exception as exc:
            tolerate(exc, "closing the freeze verify handle is best-effort",
                     counter="freeze.verify_db_close")


def read_frozen(kind: str, natural_key: str) -> tuple[Any, FreezeStatus, str]:
    """Read a frozen artifact's pinned content — ``(revision, status, reason)``.

    Raises :class:`FrozenDataGoneError` when the pin cannot be honoured. It would be easy to
    fall back to the live version here, and that is the one thing this must never do: a lock
    icon over live numbers is worse than an error, because the reader cannot tell.
    """
    fz = frozen(kind, natural_key)
    if fz is None:
        raise FrozenDataGoneError(f"{natural_key} is not frozen", reason="not frozen")

    status, reason = verify(kind, natural_key)
    if status == "gone":
        raise FrozenDataGoneError(
            f"{natural_key} is frozen as of {fz.as_of} but that pin can no longer be "
            f"honoured: {reason}. Unfreeze it to follow live data.",
            as_of=fz.as_of, reason=reason,
        )

    from aughor.kernel.lifecycle import revision

    rev = revision(kind, natural_key, version=fz.version)
    if rev is None:
        raise FrozenDataGoneError(
            f"{natural_key} is frozen to version {fz.version}, which is no longer in the "
            f"artifact history (as of {fz.as_of}).",
            as_of=fz.as_of, reason="pinned version missing from history",
        )
    return rev, status, reason
