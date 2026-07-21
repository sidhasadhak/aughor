"""RC5b — re-validate stored findings against LIVE data before they reach a briefing.

A finding is generated once and stored; the data can change, and a finding may have slipped
a guard that has since tightened. Before the briefing HEADLINES a finding, re-run its query
and re-apply the SAME deterministic gate (`verify_insight`, incl. the RC4 implausible-ratio
check) + numeral grounding. Anything that no longer reproduces, is degenerate/implausible,
or whose claimed numbers aren't in the live cells is flagged ``invalid`` (reversible, with a
reason) so the store filter drops it from BOTH the headline (/domains) and the synthesis
(/briefing). Bounded to the top-N by novelty (the set that actually feeds the headline +
synthesis), cached per (store_key, id, sql-hash), and fail-open — a re-validation bug must
never suppress a sound finding.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from aughor.db.paths import state_dir

logger = logging.getLogger(__name__)

# In-process memo so a refresh doesn't re-run every finding's SQL again.
_SEEN: dict[str, bool] = {}

# Re-validate only the findings that can actually headline the brief.
_REVALIDATE_LIMIT = 12


def _revalidate_one_run(conn_id: str, store_key: str, schema: Optional[str], limit: int) -> list[dict]:
    """Re-run + re-gate the top-N findings for one exploration store. Persists invalid on
    failure. Returns the list of {id, reason} dropped. Never raises."""
    from aughor.explorer import store as _store
    from aughor.explorer.agent import verify_insight
    from aughor.explorer.grounding import verify_finding

    by_domain = _store.get_domain_insights(store_key)
    flat: list[dict] = []
    for items in (by_domain or {}).values():
        for ins in (items or []):
            if (ins.get("sql") or "").strip():
                flat.append(ins)
    if not flat:
        return []
    flat.sort(key=lambda i: i.get("novelty", 0) or 0, reverse=True)

    db = None
    try:
        if schema:
            from aughor.db.connection import open_connection_for_with_schema
            db = open_connection_for_with_schema(conn_id, schema_name=schema)
        else:
            from aughor.db.connection import open_connection_for
            db = open_connection_for(conn_id)
    except Exception:
        return []   # can't open the connection — fail-open (don't suppress anything)

    failed: list[tuple[str, str]] = []
    try:
        for ins in flat[:limit]:
            sql = (ins.get("sql") or "").strip()
            iid = ins.get("id", "")
            finding = ins.get("finding", "")
            ck = f"{store_key}:{iid}:{hashlib.sha1(sql.encode()).hexdigest()[:12]}"
            if ck in _SEEN:
                continue   # already validated this exact finding+SQL this process
            reason: Optional[str] = None
            try:
                res = db.execute("__revalidate__", sql)
                if res.error:
                    reason = f"query no longer runs ({str(res.error)[:70]})"
                elif not (res.rows or []):
                    reason = "query now returns zero rows"
                else:
                    ok, why = verify_insight(res.rows, finding, sql, None, conn=db)
                    if not ok:
                        reason = why or "failed re-validation"
                    else:
                        gr = verify_finding(finding, res.rows)
                        if not gr.grounded:
                            reason = "claimed numbers not in live result (" + ", ".join(gr.ungrounded[:3]) + ")"
            except Exception:
                reason = None   # fail-open on a re-validation error
            _SEEN[ck] = (reason is None)
            if reason:
                failed.append((iid, reason))
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "revalidate connection close is best-effort (pooled release)",
                         counter="revalidate.db_close")

    if not failed:
        return []
    # Persist invalid (reversible) so the store filter drops these everywhere.
    try:
        state = _store.load(store_key)
        idx = {i.get("id"): i for i in state.get("insights", [])}
        for iid, reason in failed:
            i = idx.get(iid)
            if i is not None and not i.get("invalid"):
                i["invalid"] = True
                i["invalid_reason"] = f"auto re-validation: {reason}"
        _store.save(store_key, state)
    except Exception:
        logger.debug("revalidate_live: persist failed for %s", store_key, exc_info=True)
        return []
    for iid, reason in failed:
        logger.info("[revalidate:%s] suppressed finding %s — %s", store_key, iid, reason)
    return [{"id": iid, "reason": reason} for iid, reason in failed]


def revalidate_for_briefing(conn_id: str, schema: Optional[str], limit: int = _REVALIDATE_LIMIT) -> list[dict]:
    """Re-validate the findings that feed a (connection, schema) briefing. Resolves the right
    exploration store(s): the specific per-schema run, every per-schema run for the 'All
    schemas' aggregate, or the connection-level run. Returns all dropped {id, reason}."""
    from aughor.explorer import store as _store

    runs: list[tuple[str, Optional[str]]] = []
    if schema:
        store_key = f"{conn_id}__{schema}"
        # specific schema: per-schema file if it exists, else the connection store
        if (state_dir() / f"exploration_{store_key}.json").exists():
            runs.append((store_key, schema))
        else:
            runs.append((conn_id, None))
    else:
        keys = _store.schema_run_keys(conn_id)
        if keys:
            for k in keys:
                sch = k.split("__", 1)[1] if "__" in k else None
                runs.append((k, sch))
        else:
            runs.append((conn_id, None))

    dropped: list[dict] = []
    for store_key, sch in runs:
        try:
            dropped += _revalidate_one_run(conn_id, store_key, sch, limit)
        except Exception:
            logger.debug("revalidate_live: run failed for %s", store_key, exc_info=True)
    return dropped
