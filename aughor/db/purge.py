"""Catalog (== connection) delete cascade — purge every derived artifact.

A catalog's id *is* its connection id, and that id is the isolation unit. Deleting
the catalog must take its whole intelligence footprint with it: uploaded data,
business profiles, explorations/episodes, investigations + evidence, briefings +
subscriptions, monitors + alerts, packs (bindings + deltas), type overrides, and
the vector indexes (investigations / SQL examples / connection KB). Otherwise a
re-created connection that happens to reuse the id inherits a previous tenant's
stale intelligence — a correctness *and* privacy hazard.

Design:
  • **Platform owns the orchestration, the Agent owns its stores.** The platform
    purges what it owns inline (uploads, matcache, type-overrides, the data/ file
    artifacts, the metastore row, canvases) and delegates every AGENT-owned store to
    **registered purge hooks** (``aughor.kernel.registries.purge_hooks``), so this
    module never imports the agent. The hooks are registered at startup by
    ``aughor.agent.bootstrap.register_agent_plugins``.
  • **Best-effort, independent** — each step / hook is guarded so one failure never
    blocks the rest. Failures surface via ``tolerate`` (a counter), never silently.
  • **Returns a count summary** — the caller LOGS what was actually removed, so the
    cascade is observable (a silent purge that secretly no-ops is the bug we guard
    against).
  • **Idempotent** — safe to run twice; a missing artifact is a no-op, not an error.

Adding a new connection-keyed store: register a hook in
``aughor.agent.bootstrap`` (``register_purge_hook`` / ``register_schema_purge_hook``
/ ``register_investigations_purge_hook``) returning ``{label: count}`` — and add a
case to ``tests/unit/test_connection_purge.py`` — otherwise a deleted catalog
orphans it.
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from aughor.db.paths import state_dir
from aughor.kernel.errors import tolerate

logger = logging.getLogger(__name__)

# MUST resolve the same dir as the stores it purges. This module used to hard-code the
# directory itself, so it unlinked from the LIVE one even when a test had redirected the
# target store — a redirect the deleter doesn't share is not isolation.
_DATA_DIR = state_dir()


def _safe(s: str) -> str:
    """The same filename sanitiser the per-connection JSON stores use."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def purge_connection_artifacts(conn_id: str, org_id: str | None = None) -> dict[str, int]:
    """Delete every artifact derived from / belonging to ``conn_id``.

    Returns a ``{artifact: count}`` summary of what was removed. Best-effort: every
    step is independently guarded so a failure in one store still purges the rest.
    """
    counts: dict[str, int] = {}

    def _files(*patterns: str) -> int:
        """Unlink data/ files matching any glob pattern (raw + sanitised id)."""
        removed = 0
        seen: set[Path] = set()
        for pat in patterns:
            for p in _DATA_DIR.glob(pat):
                if p in seen or not p.exists():
                    continue
                seen.add(p)
                try:
                    p.unlink()
                    removed += 1
                except Exception as e:
                    tolerate(e, f"purge: unlink {p}", counter="conn.purge.unlink")
        return removed

    raw, safe = conn_id, _safe(conn_id)

    # ── Uploaded data (the bytes themselves) — platform storage ─────────────────
    try:
        from aughor.platform.vending import vend_storage
        root = vend_storage(conn_id, org_id).root
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
            counts["upload_dir"] = 1
    except Exception as e:
        tolerate(e, "purge: upload dir", counter="conn.purge.uploads")

    # ── Materialisation cache (platform) ────────────────────────────────────────
    try:
        from aughor.db import matcache
        matcache.invalidate(conn_id)
        counts["matcache"] = 1
    except Exception as e:
        tolerate(e, "purge: matcache", counter="conn.purge.matcache")

    # ── File-pattern intelligence (platform-owned data/ files) ──────────────────
    counts["exploration"] = _files(f"exploration_{safe}*.json", f"exploration_{raw}*.json")
    counts["episodes"]    = _files(f"episodes_{safe}*.jsonl", f"episodes_{raw}*.jsonl")
    counts["annotations"] = _files(f"annotations_{safe}.json", f"annotations_{raw}.json")
    counts["benchmarks"]  = _files(f"benchmarks_{safe}.json", f"benchmarks_{raw}.json")
    counts["sync_state"]  = _files(f"sync_state_{safe}.json", f"sync_state_{raw}.json",
                                   f"api_sync/{safe}.duckdb", f"api_sync/{raw}.duckdb")

    # ── Type overrides (platform) ───────────────────────────────────────────────
    try:
        from aughor.db import type_overrides
        counts["type_overrides"] = 1 if type_overrides.purge_connection(conn_id) else 0
    except Exception as e:
        tolerate(e, "purge: type_overrides", counter="conn.purge.type_overrides")

    # ── Canvases (+ their saved artifacts) scoped to this connection (platform) ──
    try:
        from aughor.canvas import store as canvas_store
        counts["canvases"] = canvas_store.purge_connection(conn_id)
    except Exception as e:
        tolerate(e, "purge: canvases", counter="conn.purge.canvases")

    # ── AGENT-owned derived stores via registered hooks ─────────────────────────
    # profile, ontology, profile-cache, briefings, monitors, evidence, connection KB,
    # packs, vector indexes. Runs BEFORE the history rows are deleted below, so the
    # evidence hook can read the investigation ids it must cascade.
    from aughor.kernel.registries.purge_hooks import run_purge_hooks
    for k, v in run_purge_hooks(conn_id, org_id).items():
        counts[k] = counts.get(k, 0) + v

    # ── Investigations (platform) — after the evidence hook read the ids ────────
    try:
        from aughor.db import history
        counts["investigations"] = history.purge_connection(conn_id)
    except Exception as e:
        tolerate(e, "purge: investigations", counter="conn.purge.investigations")

    # ── Derived metastore catalog row (platform) ────────────────────────────────
    try:
        from aughor.metastore import delete_catalog
        counts["catalog_row"] = 1 if delete_catalog(conn_id, org_id) else 0
    except Exception as e:
        tolerate(e, "purge: metastore catalog", counter="conn.purge.catalog")

    removed = {k: v for k, v in counts.items() if v}
    if removed:
        logger.info("Purged artifacts for deleted connection %s: %s", conn_id, removed)
    return counts


def purge_investigation_artifacts(inv_id: str) -> dict[str, int]:
    """Delete ONE investigation and everything derived from it: the history row (or
    whole chat session, since delete keys on id OR session_id), its evidence claims,
    and its vector-index entry. Returns a ``{artifact: count}`` summary. Best-effort
    + idempotent — the per-user 'delete this investigation' cascade.

    Without this, deleting from the UI left the investigation searchable in the RAG
    index (still steering future analysis) and orphaned its evidence claims.
    """
    counts: dict[str, int] = {}
    try:
        from aughor.db import history
        counts["investigations"] = 1 if history.delete_investigation(inv_id) else 0
    except Exception as e:
        tolerate(e, "purge-inv: history row", counter="inv.purge.history")
    # Evidence + vector points (agent-owned) via the investigation-keyed hooks.
    from aughor.kernel.registries.purge_hooks import run_investigations_purge_hooks
    for k, v in run_investigations_purge_hooks([inv_id]).items():
        counts[k] = counts.get(k, 0) + v
    removed = {k: v for k, v in counts.items() if v}
    if removed:
        logger.info("Purged artifacts for deleted investigation %s: %s", inv_id, removed)
    return counts


def purge_investigations_bulk(connection_ids: list[str] | None = None) -> dict[str, int]:
    """Clear investigations in bulk — platform-wide (``connection_ids=None``) or only
    those belonging to a set of connections (workspace-scoped clear) — cascading
    evidence claims and vector-index points. Returns a ``{artifact: count}`` summary.
    """
    from aughor.db import history
    from aughor.kernel.registries.purge_hooks import run_investigations_purge_hooks

    counts: dict[str, int] = {}
    ids = history.all_investigation_ids(connection_ids)
    if not ids:
        return counts
    # Evidence + vector points (agent-owned) for every investigation being cleared.
    for k, v in run_investigations_purge_hooks(ids).items():
        counts[k] = counts.get(k, 0) + v
    try:
        counts["investigations"] = history.purge_ids(ids)
    except Exception as e:
        tolerate(e, "purge-inv-bulk: history rows", counter="inv.purge.bulk_history")
    removed = {k: v for k, v in counts.items() if v}
    if removed:
        logger.info("Bulk-purged investigations (%s): %s",
                    "all" if connection_ids is None else f"{len(connection_ids)} conn(s)", removed)
    return counts


def purge_schema_artifacts(conn_id: str, schema: str) -> dict[str, int]:
    """Delete every derived artifact tied to a single (connection, schema) when a schema
    is removed — the schema-scoped analogue of :func:`purge_connection_artifacts`.

    Sibling schemas keep their intelligence. Schema-scoped agent stores
    (profile/ontology/briefing/watermark/pack bindings/monitors) drop only this
    schema's entries via registered schema hooks; the connection-level aggregates
    (the bare ``*_{conn}`` profile / exploration / briefing) are dropped because they
    are stale the moment any schema is removed. Canvases bound to the schema, and the
    investigations they (or schema-qualified SQL references) imply, cascade their
    evidence. Best-effort + observable.
    """
    from aughor.kernel.registries.purge_hooks import (
        run_investigations_purge_hooks,
        run_schema_purge_hooks,
    )

    counts: dict[str, int] = {}
    safe, ssafe = _safe(conn_id), _safe(schema)

    def _run(label: str, fn):
        try:
            counts[label] = fn() or 0
        except Exception as e:
            tolerate(e, f"purge-schema: {label}", counter=f"schema.purge.{label}")

    # ── schema-scoped + connection-aggregate agent stores via hooks ─────────────
    for k, v in run_schema_purge_hooks(conn_id, schema).items():
        counts[k] = counts.get(k, 0) + v

    # ── connection-level aggregate files (platform) — stale once any schema goes ─
    counts["explorer_files"] = _unlink_exact(
        f"exploration_{safe}__{ssafe}.json", f"exploration_{safe}.json",
        f"episodes_{safe}__{ssafe}.jsonl", f"episodes_{safe}.jsonl",
        f"business_profile_{safe}.json",   # the bare 'All schemas' profile
    )

    # ── canvases bound to this schema (platform) → their investigations + evidence ─
    canvas_ids: list[str] = []

    def _canvases() -> int:
        nonlocal canvas_ids
        from aughor.canvas import store as canvas_store
        canvas_ids = canvas_store.purge_schema(conn_id, schema)
        return len(canvas_ids)
    _run("canvases", _canvases)

    def _investigations() -> int:
        from aughor.db import history
        ids = history.purge_schema(conn_id, schema, canvas_ids)
        for k, v in run_investigations_purge_hooks(ids).items():
            counts[k] = counts.get(k, 0) + v
        return len(ids)
    _run("investigations", _investigations)

    removed = {k: v for k, v in counts.items() if v}
    if removed:
        logger.info("Purged artifacts for removed schema %s.%s: %s", conn_id, schema, removed)
    return counts


def _unlink_exact(*names: str) -> int:
    """Unlink exact data/ files by name (precise paths, no globbing). Returns count."""
    removed = 0
    for name in names:
        p = _DATA_DIR / name
        if p.exists():
            try:
                p.unlink()
                removed += 1
            except Exception as e:
                tolerate(e, f"purge-schema: unlink {p}", counter="schema.purge.unlink")
    return removed
