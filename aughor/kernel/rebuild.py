"""Staleness-resolved rebuild — Wave V2.

**An output is fresh iff its inputs AND its logic are unchanged**
(docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md, L44). Aughor rebuilds on a *timer* in ~10 places, and a timer is wrong in both
directions at once. Take the briefing's 2-hour TTL:

* it **rebuilds a brief whose inputs never moved** — pure cost, and each rebuild is an
  LLM call, not just CPU;
* it **serves a brief for up to two hours after its source table changed** — a wrong
  number, which is the expensive failure.

Both are the same bug: wall-clock is a proxy for "did the source move", and the real
signal already exists. Wave A3 built it — ``automations/probes.current_version`` fingerprints
a table with ONE bounded aggregate (``SELECT COUNT(*), MAX(signal)``), never a scan. A3's
docstring notes it already *"generalizes the shape of explorer.watermark"*; this module is
its second consumer, which is what turns it from an automations feature into a platform
primitive.

Composition with V1: the verdict vocabulary and the fingerprint composition come from
:mod:`aughor.kernel.freshness`; this module adds the *resolution* (probing live sources and
remembering what an artifact was last built on), which needs stores and therefore cannot
live in that deliberately dependency-free module.

Three refusals, so the resolver cannot quietly become a worse timer:

* **Fail open, loudly.** A table that cannot be versioned (no signal column, probe error)
  falls back to the caller's existing TTL decision and says so in ``reason`` — counted
  through ``tolerate``, never silently treated as "unchanged". Following A3's rule: noisy
  beats silent.
* **No silent caps.** Probing is capped at :data:`MAX_PROBE_TABLES`; when the cap bites,
  the reason names how many tables were skipped rather than implying full coverage.
* **Flag off ⇒ the caller's legacy decision, byte-identical.** ``resolve`` returns exactly
  ``should_rebuild=ttl_expired`` when the flag is off, so a caller can consult it
  unconditionally.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from aughor.db.paths import state_dir
from aughor.kernel.errors import tolerate
from aughor.kernel.freshness import StalenessState, compose_fingerprint
from aughor.util.json_store import KeyedJsonStore

#: Bounded aggregates are cheap but not free; a very wide warehouse should not pay for
#: hundreds on a cache check. When the cap bites, the reason says so (no silent coverage).
MAX_PROBE_TABLES = 25

_store = KeyedJsonStore(state_dir() / "rebuild_state.json", max_entries=500)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RebuildDecision:
    """Why an artifact will (or will not) be rebuilt.

    ``resolved`` is the honesty bit: ``True`` means a live source probe actually answered
    and this decision is evidence-based; ``False`` means the probe could not answer and the
    caller's TTL was used instead. A consumer that reports "we skipped a rebuild because
    nothing changed" must check it.
    """

    should_rebuild: bool
    staleness: StalenessState
    reason: str
    inputs_version: str = ""
    logic_version: str = ""
    as_of: str = ""
    resolved: bool = False

    @property
    def saved_a_rebuild(self) -> bool:
        """The cost half: the TTL said rebuild, the evidence said don't."""
        return self.resolved and not self.should_rebuild

    @property
    def caught_a_stale_read(self) -> bool:
        """The correctness half: the TTL said serve, the evidence said rebuild."""
        return self.resolved and self.should_rebuild


# ── Input signal: what the artifact is built ON ───────────────────────────────

def source_tables_for(connection_id: str, db) -> list[str]:
    """The connection's tables, from the cached introspection the trust checks already own.

    Deliberately reuses that cache rather than introspecting again: a freshness check must
    be cheaper than the rebuild it is deciding about.
    """
    from aughor.sql.trust_checks import connection_column_types

    types = connection_column_types(connection_id, db) or {}
    return sorted({k.split(".")[0] for k in types if "." in k})


def inputs_version(
    connection_id: str, tables: Optional[Sequence[str]] = None
) -> tuple[Optional[str], str]:
    """One fingerprint over an artifact's source tables — ``(version, how)``.

    ``version=None`` means "cannot version these inputs"; ``how`` carries the reason so the
    caller can fail open *with an explanation*. One connection is opened for the whole
    batch, and each table costs one bounded aggregate (A3's probe).
    """
    from aughor.automations.probes import current_version
    from aughor.db.connection import open_connection_for

    try:
        db = open_connection_for(connection_id)
    except Exception as exc:
        return None, f"cannot open connection: {type(exc).__name__}: {exc}"

    try:
        names = list(tables) if tables else source_tables_for(connection_id, db)
        if not names:
            return None, "no source tables known for this connection"

        skipped = 0
        if len(names) > MAX_PROBE_TABLES:
            skipped = len(names) - MAX_PROBE_TABLES
            names = sorted(names)[:MAX_PROBE_TABLES]

        parts: list[str] = []
        unversionable: list[str] = []
        for t in sorted(names):
            v, how = current_version(connection_id, db, t)
            if v is None:
                unversionable.append(f"{t} ({how})")
                continue
            parts.append(f"{t}={v}")

        if not parts:
            return None, f"no table could be versioned: {'; '.join(unversionable[:3])}"

        note = f"{len(parts)} table(s) probed"
        if unversionable:
            # Partial coverage is still a usable signal, but it must be stated: a table we
            # cannot version is a table whose change we cannot see.
            note += f", {len(unversionable)} unversionable ({unversionable[0]})"
        if skipped:
            note += f", {skipped} skipped (cap {MAX_PROBE_TABLES})"
        return compose_fingerprint(parts), note
    finally:
        try:
            db.close()
        except Exception as exc:
            tolerate(exc, "closing the freshness probe handle is best-effort; the version "
                          "is already computed", counter="rebuild.db_close")


# ── The decision ──────────────────────────────────────────────────────────────

def resolve(
    artifact_key: str,
    *,
    connection_id: str,
    tables: Optional[Sequence[str]] = None,
    logic: str = "",
    ttl_expired: bool = False,
    force: bool = False,
) -> RebuildDecision:
    """Decide whether ``artifact_key`` needs rebuilding, on evidence rather than the clock.

    ``ttl_expired`` is the caller's existing wall-clock decision, kept as the backstop for
    when the input probe cannot answer — so this function is always safe to consult and
    never *less* correct than the timer it replaces.
    """
    if force:
        return RebuildDecision(True, "stale", "forced")

    try:
        version, how = inputs_version(connection_id, tables)
    except Exception as exc:
        tolerate(exc, "the freshness probe is best-effort; the caller's TTL still decides, "
                      "so a probe failure can never serve a stale artifact silently",
                 counter="rebuild.probe")
        version, how = None, f"probe raised {type(exc).__name__}"

    if version is None:
        return RebuildDecision(
            ttl_expired, "unknown",
            f"cannot resolve inputs ({how}) — failing open to the TTL decision "
            f"({'rebuild' if ttl_expired else 'serve'})",
            resolved=False,
        )

    prior = _store.get(artifact_key) or {}
    prev_inputs = prior.get("inputs_version") or ""
    prev_logic = prior.get("logic_version") or ""

    if not prev_inputs:
        return RebuildDecision(True, "stale", f"first resolution ({how})",
                               inputs_version=version, logic_version=logic, resolved=True)

    if prev_logic != logic:
        return RebuildDecision(
            True, "stale",
            f"producer logic changed ({prev_logic or 'unset'} → {logic or 'unset'})",
            inputs_version=version, logic_version=logic, resolved=True,
        )

    if prev_inputs != version:
        # The correctness half: rebuild NOW, whether or not the timer had lapsed.
        return RebuildDecision(
            True, "stale", f"source data moved ({how})",
            inputs_version=version, logic_version=logic,
            as_of=prior.get("as_of", ""), resolved=True,
        )

    # The cost half: inputs and logic are identical, so age alone is not a reason.
    return RebuildDecision(
        False, "fresh",
        f"inputs and logic unchanged ({how})"
        + ("; TTL had lapsed but nothing moved" if ttl_expired else ""),
        inputs_version=version, logic_version=logic,
        as_of=prior.get("as_of", ""), resolved=True,
    )


def record(artifact_key: str, decision: RebuildDecision, *, as_of: str = "") -> None:
    """Remember what an artifact was just built on — called AFTER a successful rebuild.

    Recording on failure would consume a change: the next check would compare against
    inputs whose output was never produced, so a genuinely stale artifact would read
    fresh. Same reasoning as A3 committing its baselines only on a *fired* tick.
    """
    if not decision.inputs_version:
        return
    _store.put(artifact_key, {
        "inputs_version": decision.inputs_version,
        "logic_version": decision.logic_version,
        # The source view the output was computed on (study L340) — what a
        # live-vs-frozen badge and V4's freeze will pin against.
        "as_of": as_of or _now(),
    })


def forget(artifact_key: str) -> None:
    """Drop an artifact's remembered state, so the next check rebuilds. Used by explicit
    invalidation (a connection reset must not leave a stale 'nothing moved' memory)."""
    _store.invalidate_prefix(artifact_key)


def last_built_as_of(artifact_key: str) -> str:
    """The source view an artifact was last built on ('' when never resolved)."""
    return (_store.get(artifact_key) or {}).get("as_of", "")
