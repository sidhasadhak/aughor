"""Catalog (== connection) delete cascade — purge every derived artifact.

A catalog's id *is* its connection id, and that id is the isolation unit. Deleting
the catalog must take its whole intelligence footprint with it: uploaded data,
business profiles, explorations/episodes, investigations + evidence, briefings +
subscriptions, monitors + alerts, packs (bindings + deltas), type overrides, and
the vector indexes (investigations / SQL examples / connection KB). Otherwise a
re-created connection that happens to reuse the id inherits a previous tenant's
stale intelligence — a correctness *and* privacy hazard.

Design:
  • **Best-effort, independent** — each store is purged in its own guarded step so
    one failure never blocks the rest. Failures are surfaced via ``tolerate`` (a
    counter), never silently swallowed.
  • **Returns a count summary** — the caller LOGS what was actually removed, so the
    cascade is observable (a silent purge that secretly no-ops is the bug we are
    guarding against, per the connection-delete history).
  • **Idempotent** — safe to run twice; a missing artifact is a no-op, not an error.
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from aughor.kernel.errors import tolerate

logger = logging.getLogger(__name__)

_DATA_DIR = Path("data")


def _safe(s: str) -> str:
    """The same filename sanitiser the per-connection JSON stores use."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def _purge_qdrant(conn_id: str, counts: dict[str, int]) -> None:
    """Drop the connection's cached investigations + SQL examples from the vector
    collections keyed by ``connection_id`` payload. (The connection-KB collection is
    purged by ``connection_kb.purge_connection``, which owns its own collection.)"""
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from aughor.semantic.vector_store import delete_by_filter
        from aughor.tools.prior_analyses import (
            INVESTIGATIONS_COLLECTION,
            SQL_EXAMPLES_COLLECTION,
        )
    except Exception as e:  # qdrant client / modules unavailable
        tolerate(e, "purge: qdrant imports", counter="conn.purge.qdrant_import")
        return

    filt = Filter(must=[FieldCondition(key="connection_id", match=MatchValue(value=conn_id))])
    for coll in (INVESTIGATIONS_COLLECTION, SQL_EXAMPLES_COLLECTION):
        try:
            counts["qdrant_points"] = counts.get("qdrant_points", 0) + (
                delete_by_filter(coll, filt) or 0
            )
        except Exception as e:
            tolerate(e, f"purge: qdrant {coll}", counter="conn.purge.qdrant")


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

    # ── Uploaded data (the bytes themselves) ─────────────────────────────────────
    try:
        from aughor.platform.vending import vend_storage
        root = vend_storage(conn_id, org_id).root
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
            counts["upload_dir"] = 1
    except Exception as e:
        tolerate(e, "purge: upload dir", counter="conn.purge.uploads")

    # ── Business profile + ontology + materialisation/profile caches ────────────
    for label, fn in (
        ("profile", lambda: _invalidate("aughor.profile.store", conn_id)),
        ("ontology", lambda: _invalidate("aughor.ontology.store", conn_id)),
        ("matcache", lambda: _invalidate("aughor.db.matcache", conn_id)),
        ("profile_cache", lambda: _invalidate("aughor.tools.profile_cache", conn_id)),
    ):
        try:
            fn()
            counts[label] = 1
        except Exception as e:
            tolerate(e, f"purge: {label}", counter=f"conn.purge.{label}")

    # ── File-pattern intelligence (explorer state, KB, annotations, benchmarks…) ─
    counts["exploration"] = _files(f"exploration_{safe}*.json", f"exploration_{raw}*.json")
    counts["episodes"]    = _files(f"episodes_{safe}*.jsonl", f"episodes_{raw}*.jsonl")
    counts["annotations"] = _files(f"annotations_{safe}.json", f"annotations_{raw}.json")
    counts["benchmarks"]  = _files(f"benchmarks_{safe}.json", f"benchmarks_{raw}.json")
    counts["sync_state"]  = _files(f"sync_state_{safe}.json", f"sync_state_{raw}.json",
                                   f"api_sync/{safe}.duckdb", f"api_sync/{raw}.duckdb")

    # ── Type overrides (nested dict keyed by conn_id) ───────────────────────────
    try:
        from aughor.db import type_overrides
        counts["type_overrides"] = 1 if type_overrides.purge_connection(conn_id) else 0
    except Exception as e:
        tolerate(e, "purge: type_overrides", counter="conn.purge.type_overrides")

    # ── Briefings: subscriptions + cached narratives ────────────────────────────
    try:
        from aughor.briefs import store as brief_store
        counts["brief_subscriptions"] = brief_store.delete_for_connection(conn_id)
    except Exception as e:
        tolerate(e, "purge: brief subscriptions", counter="conn.purge.briefs")
    try:
        from aughor.knowledge import briefing
        counts["briefing_cache"] = briefing.invalidate(conn_id)
    except Exception as e:
        tolerate(e, "purge: briefing cache", counter="conn.purge.briefing_cache")

    # ── Monitors + alerts ───────────────────────────────────────────────────────
    try:
        from aughor.monitors import store as monitor_store
        counts["monitors"] = monitor_store.purge_connection(conn_id)
    except Exception as e:
        tolerate(e, "purge: monitors", counter="conn.purge.monitors")

    # ── Investigations + evidence claims (evidence keys only by investigation) ──
    try:
        from aughor.db import history
        from aughor.evidence import store as evidence_store
        inv_ids = history.list_investigation_ids(conn_id, limit=100000)
        counts["evidence_claims"] = evidence_store.purge_investigations(inv_ids)
        counts["investigations"] = history.purge_connection(conn_id)
    except Exception as e:
        tolerate(e, "purge: investigations/evidence", counter="conn.purge.investigations")

    # ── Connection knowledge base (JSON source of truth + its vector points) ─────
    try:
        from aughor.semantic import connection_kb
        counts["knowledge"] = connection_kb.purge_connection(conn_id)
    except Exception as e:
        tolerate(e, "purge: connection_kb", counter="conn.purge.knowledge")

    # ── Packs: bindings + proposed deltas ───────────────────────────────────────
    try:
        from aughor.packs import bindings, deltastore
        counts["pack_bindings"] = bindings.purge_connection(conn_id)
        counts["pack_deltas"] = deltastore.purge_connection(conn_id)
    except Exception as e:
        tolerate(e, "purge: packs", counter="conn.purge.packs")

    # ── Derived metastore catalog row (reconciled from connections; drop now so it
    #    doesn't linger until the next startup sync) ──────────────────────────────
    try:
        from aughor.metastore import delete_catalog
        counts["catalog_row"] = 1 if delete_catalog(conn_id, org_id) else 0
    except Exception as e:
        tolerate(e, "purge: metastore catalog", counter="conn.purge.catalog")

    # ── Vector indexes ──────────────────────────────────────────────────────────
    _purge_qdrant(conn_id, counts)

    removed = {k: v for k, v in counts.items() if v}
    if removed:
        logger.info("Purged artifacts for deleted connection %s: %s", conn_id, removed)
    return counts


def _invalidate(module_path: str, conn_id: str) -> None:
    """Call a store module's ``invalidate(conn_id)`` by dotted path."""
    import importlib
    mod = importlib.import_module(module_path)
    mod.invalidate(conn_id)
