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
    purges what it owns inline (uploads, matcache, type-overrides, declared metadata,
    the data/ file artifacts, the metastore row, canvases) and delegates every AGENT-owned store to
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
orphans it. A store that is missed is no longer silent: the cascade ends with
``residue_of``, which reads the DISK (every table with a connection column, every path,
every JSON/YAML store) and logs what a delete left — measured 2026-10-04, eight kinds of
store had been outliving every deleted connection.
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
        from aughor.control_plane.vending import vend_storage
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
    # Exploration state moved into the agent's family store; its deletion is the
    # "exploration"-labelled CONNECTION HOOK (agent/bootstrap.py), not a glob here —
    # the platform must not import the agent store it cascades into.
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

    # ── Declared metadata (platform) — the engine's keys and comments, as last read ──
    try:
        from aughor.db import metadata
        counts["declared_metadata"] = 1 if metadata.invalidate(conn_id) else 0
    except Exception as e:
        tolerate(e, "purge: declared metadata", counter="conn.purge.declared_metadata")

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

    # ── Mined query popularity (platform) — the tables and columns its queries read ──
    try:
        from aughor.sql import popularity
        counts["popularity"] = popularity.purge_connection(conn_id)
    except Exception as e:
        tolerate(e, "purge: popularity", counter="conn.purge.popularity")

    # ── The kernel's jobs, events, artifacts (+ lineage) and task traces (platform) ──
    try:
        from aughor.kernel.ledger import Ledger
        for k, v in Ledger.default().purge_connection(conn_id).items():
            counts[k] = counts.get(k, 0) + v
    except Exception as e:
        tolerate(e, "purge: kernel ledger", counter="conn.purge.kernel")

    removed = {k: v for k, v in counts.items() if v}
    if removed:
        logger.info("Purged artifacts for deleted connection %s: %s", conn_id, removed)

    # ── And then LOOK. Idea 1: a delete is checked against what is on disk, not against
    # the list of stores this file knows — a store added later without a purge is found
    # here the first time anyone deletes a connection, and said.
    residue = residue_of(conn_id)
    if residue:
        logger.warning("Deleted connection %s left residue in %d place(s): %s",
                       conn_id, len(residue), residue)
    counts["residue"] = sum(residue.values())
    return counts


#: What a connection delete KEEPS, by table, each with its reason. Records of what the
#: platform DID, not what it learned: deleting them would let a delete erase the account of
#: what was read from a warehouse and what it cost.
KEPT_ON_DELETE = {
    "audit_log": "the SQL audit log — every statement run against the warehouse, and by whom",
    "session_events": "the session log — every model call and what it cost",
}
#: Columns that hold a connection id in some store or other (`catalog_id` is the metastore's).
_CONNECTION_COLUMNS = ("conn_id", "connection_id", "catalog_id")
#: A person's backup folder is not a store; the vector store is binary and has its own hook.
_NOT_A_STORE = re.compile(r"backup|^qdrant$", re.IGNORECASE)
#: Text stores larger than this are not read whole by a delete.
_TEXT_SCAN_MAX_BYTES = 20_000_000


def residue_of(conn_id: str, root: Path | None = None) -> dict[str, int]:
    """Where ``conn_id`` still appears under the data directory — ``{place: count}``.

    The population is the DISK, never a list kept here: every SQLite file's every table with
    a connection column (rows equal to the id), every path named after it, and every JSON or
    YAML store mentioning it as a whole token. ``KEPT_ON_DELETE`` tables are not residue. An
    id shorter than six characters is matched in tables only — as a token it would match
    words in unrelated files."""
    import sqlite3

    base = Path(root) if root is not None else _DATA_DIR
    found: dict[str, int] = {}
    if not conn_id or not base.exists():
        return found
    ids = {conn_id, _safe(conn_id)}
    token = re.compile("|".join(rf"(?<![A-Za-z0-9]){re.escape(i)}(?![A-Za-z0-9])" for i in ids))
    named: list[Path] = []                      # a folder named after it counts once
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base)
        if any(_NOT_A_STORE.search(part) for part in rel.parts):
            continue
        if any(rel.is_relative_to(n) for n in named):
            continue
        if len(conn_id) >= 6 and token.search(path.name):
            named.append(rel)
            found[str(rel)] = 1
            continue
        if not path.is_file():
            continue
        if path.suffix in (".db", ".sqlite"):
            try:
                con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
                con.execute("PRAGMA busy_timeout = 2000")   # a store mid-write waits, never fails the scan
                try:
                    for (table,) in con.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                        if table in KEPT_ON_DELETE:
                            continue
                        cols = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
                        for col in (c for c in _CONNECTION_COLUMNS if c in cols):
                            n = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IN '
                                            f'({",".join("?" * len(ids))})', list(ids)).fetchone()[0]
                            if n:
                                found[f"{rel}:{table}.{col}"] = n
                finally:
                    con.close()
            except sqlite3.Error as e:
                tolerate(e, f"residue: could not read {rel}", counter="conn.purge.residue_read")
        elif (len(conn_id) >= 6 and path.suffix in (".json", ".jsonl", ".yaml", ".yml")
              and path.stat().st_size <= _TEXT_SCAN_MAX_BYTES):
            try:
                if token.search(path.read_text(encoding="utf-8", errors="replace")):
                    found[str(rel)] = found.get(str(rel), 0) + 1
            except OSError as e:
                tolerate(e, f"residue: could not read {rel}", counter="conn.purge.residue_read")
    return found


#: Kernel artifacts a canvas delete KEEPS: the receipts of runs FILED under it. A chat
#: answer or a deep report stays in history as a deleted chat thread's runs do (FL-6, and
#: `purge_chat_session_artifacts`), and its receipt stays with it.
from aughor.kernel.ledger import RECEIPT_KINDS as CANVAS_KEEPS  # noqa: E402


def purge_canvas_artifacts(canvas_id: str) -> dict[str, int]:
    """Delete what only a canvas could show, once the canvas is gone: its cards and saved
    chart configs, its cockpit's versions, its saved artifacts, and its exploration (the
    findings, the jobs and their events). Before this a deleted canvas left them all,
    unreachable (found by CT-3; measured 2026-10-04 on the live install). Best-effort per
    store, like the connection cascade; returns ``{artifact: count}``."""
    counts: dict[str, int] = {}
    try:
        from aughor.dashboard.store import purge_scope
        counts["cards"] = purge_scope("canvas", canvas_id)
    except Exception as e:
        tolerate(e, "purge: canvas cards", counter="canvas.purge.cards")
    try:
        from aughor.canvas import store as canvas_store
        canvas_store.delete_canvas_artifacts(canvas_id)
        counts["saved_artifacts"] = 1
    except Exception as e:
        tolerate(e, "purge: canvas saved artifacts", counter="canvas.purge.artifacts")
    try:
        from aughor.kernel.ledger import Ledger
        for k, v in Ledger.default().purge_canvas(canvas_id, keep_kinds=CANVAS_KEEPS).items():
            counts[k] = counts.get(k, 0) + v
    except Exception as e:
        tolerate(e, "purge: canvas kernel rows", counter="canvas.purge.kernel")
    removed = {k: v for k, v in counts.items() if v}
    if removed:
        logger.info("Purged artifacts for deleted canvas %s: %s", canvas_id, removed)
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


def purge_chat_session_artifacts(session_id: str) -> dict[str, int]:
    """Delete a whole CHAT THREAD and everything its turns derived.

    Not the same call as :func:`purge_investigation_artifacts` with a session id: the
    history delete does key on ``id OR session_id`` and would take every row, but the
    evidence/vector hooks are keyed per TURN. Passing the session id to them would
    purge the artifacts of one id that does not exist and silently orphan the rest —
    so the turn ids are collected first and the hooks run over all of them.
    """
    from aughor.db import history

    counts: dict[str, int] = {}
    # FL-6 — deep runs are FILED under a thread, not owned by it: unfile them
    # (session_id → NULL) so the runs survive for Fleet / agent history while
    # the thread stops resurrecting in the rail. MUST run before
    # `delete_investigation`, whose id-OR-session_id predicate would otherwise
    # take the runs down with the thread.
    unfiled = history.unfile_session_deep_runs(session_id)
    if unfiled:
        counts["deep_runs_unfiled"] = unfiled
    turn_ids = history.chat_session_turn_ids(session_id)
    if not turn_ids and not unfiled:
        return counts  # nothing owned by this caller — the route turns this into a 404
    if turn_ids:
        from aughor.kernel.registries.purge_hooks import run_investigations_purge_hooks
        for k, v in run_investigations_purge_hooks(turn_ids).items():
            counts[k] = counts.get(k, 0) + v
    try:
        counts["investigations"] = 1 if history.delete_investigation(session_id) else 0
    except Exception as e:
        tolerate(e, "purge-thread: history rows", counter="chat.purge.history")
    history.forget_chat_session_meta(session_id)
    removed = {k: v for k, v in counts.items() if v}
    if removed:
        logger.info("Purged artifacts for deleted chat thread %s (%d turn(s)): %s",
                    session_id, len(turn_ids), removed)
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
    schema's entries via registered schema hooks.

    **A connection-level artifact is dropped only if it is a DERIVED SUMMARY.** The bare
    ``*_{conn}`` profile, briefing and patterns describe all of a connection's schemas at
    once, so removing one genuinely makes them stale — and they can be rebuilt from the
    data that is left. What they are NOT is history: the connection's episode log and its
    exploration runs are records of what the agent actually did, and no later change makes
    a record untrue. On a multi-schema connection they also hold work belonging to the
    OTHER schemas — every run that was never schema-scoped writes there — so dropping them
    when one schema goes deletes siblings' history (measured 2026-09-12: removing a
    two-row test schema from a ten-schema workspace took the connection's whole episode
    log, which the Activity feed reads by merging with the per-schema files). They go with
    the CONNECTION instead, in :func:`purge_connection_artifacts`.

    Canvases bound to the schema, and the investigations they (or schema-qualified SQL
    references) imply, cascade their evidence. Best-effort + observable.
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

    # ── this schema's episode log; the connection's stays ──────────────────────
    # Episodes are platform-owned files (the bare profile is the "profile_bare" SCHEMA
    # HOOK in agent/bootstrap.py, already merged above). The bare `episodes_{conn}.jsonl`
    # is NOT this schema's to delete — see the docstring.
    counts["explorer_files"] = counts.get("explorer_files", 0) + _unlink_exact(
        f"episodes_{safe}__{ssafe}.jsonl",
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
