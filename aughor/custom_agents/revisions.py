"""Wave H6 — an agent's configuration history, and the honesty it buys.

The scoped item was "a revisions table inside agents.db". Two measured facts moved it:

1. **A versioned store already exists.** ``Ledger.artifact_write`` supersedes rather than
   deletes and ``artifact_versions`` returns the whole series newest-first, indexed on
   ``(natural_key, version)``. Its own docstring was written for a history/diff/revert
   surface. A second versioning mechanism would be the thing J10/J12 forbid, so this
   module is thin glue over the one that exists: no new table, no new migration.

2. **Versioning alone would have deepened a lie.** Editing an agent left ``last_eval``
   untouched, so an agent whose instructions had been inverted and whose document scope
   had been emptied still displayed ``passed 5/5``. Adding a restore button on top of that
   would let a user roll back a configuration while the chip kept claiming a number earned
   by a different one. So the revision is not the feature — it is the identity the pass
   chip cites (``UserAgent.config_rev`` / ``eval_basis``), and the history is what makes
   that identity legible.

Restoring writes the old configuration FORWARD as a new revision. History is append-only:
"I went back to how it was on Tuesday" is itself an event worth keeping, and a rewind that
erased the intervening revisions would lose the record of what was tried.
"""
from __future__ import annotations

from typing import Optional

from aughor.custom_agents.models import GOVERNING_FIELDS, UserAgent

ARTIFACT_KIND = "user_agent_config"


def natural_key(agent_id: str) -> str:
    return f"user_agent:{agent_id}"


def _config_of(agent: UserAgent) -> dict:
    return {f: getattr(agent, f) for f in GOVERNING_FIELDS}


def record_revision(agent: UserAgent, *, author: str = "") -> Optional[str]:
    """Append the agent's current governing configuration as a new revision.

    Returns the artifact id, or None when the configuration is unchanged — a rename or an
    enable/disable is not a revision, and neither is saving the same text twice. Without
    that check the history fills with entries a reader cannot distinguish from real edits,
    which is how a version list stops being read.

    Best-effort: an agent must still save if the ledger is unavailable. A missing revision
    is recoverable (the next edit records one); a save that fails because its audit trail
    failed is not.
    """
    try:
        from aughor.kernel.ledger import Ledger
        ledger = Ledger.default()
        key = natural_key(agent.id)
        current = _config_of(agent)
        latest = ledger.artifact_latest(key)
        if latest and (latest.get("payload") or {}).get("config_rev") == agent.config_rev:
            return None
        return ledger.artifact_write(
            ARTIFACT_KIND, key,
            {"agent_id": agent.id, "name": agent.name, "config_rev": agent.config_rev,
             "author": author, "config": current},
            conn_id=agent.connection_id or None,
        )
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "recording an agent configuration revision is best-effort; the agent itself is saved",
                 counter="user_agents.revision.write")
        return None


def list_revisions(agent_id: str, *, limit: int = 50) -> list[dict]:
    """The configuration history, newest first.

    Each entry carries the version, when it was written, its ``config_rev`` and the
    configuration itself, so a caller can diff two revisions without a second round trip.
    """
    try:
        from aughor.kernel.ledger import Ledger
        rows = Ledger.default().artifact_versions(natural_key(agent_id), limit=limit)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "reading agent revision history is best-effort; the agent still renders without it",
                 counter="user_agents.revision.list")
        return []
    out = []
    for r in rows:
        payload = r.get("payload") or {}
        out.append({
            "version": r.get("version"),
            "at": r.get("created_at"),
            "config_rev": payload.get("config_rev", ""),
            "author": payload.get("author", ""),
            "name": payload.get("name", ""),
            "config": payload.get("config") or {},
        })
    return out


def revision_config(agent_id: str, version: int) -> Optional[dict]:
    """The governing configuration stored at ``version``, or None if there is no such one.

    Only the declared governing fields are returned, so a restore can never resurrect a
    field that is no longer part of what governs an agent's behaviour.
    """
    for rev in list_revisions(agent_id, limit=200):
        if rev["version"] == version:
            config = rev["config"] or {}
            return {f: config[f] for f in GOVERNING_FIELDS if f in config}
    return None
