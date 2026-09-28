"""Tell people when a Briefing they were given has changed (Arc BR-6, ROADMAP §3.48).

`answer/recheck.py` already does this for a chat answer: once a UTC day it re-runs the answer's
own query, compares at the departure gate's noise band, classifies a move as late rows or a
restatement, and tells the person where they were answered. A Briefing had no such recall — its
figures are the ones most likely to move, because a Briefing is written about the most recent
complete period and that is exactly the period still filling.

This is the same loop over a different subject, and it borrows rather than restates: the window
comes from `recheck.WINDOW_DAYS`, the noise band from `versions.revisions` (which imports the
gate's own `NOISE_REL`), and the late-rows-or-restatement reading from `recheck.classify`. What
it does NOT borrow is the store: a Briefing's history is its ledger artifact (`briefing.versions`),
so a re-measurement that moves a figure writes the next version there and nowhere else.

**Against the warehouse, never the cache.** §3.27's review caught law 1 checking a Briefing
against itself. `connection_runner(conn_id, cached=False)` is the reader that bypasses the result
cache, and it is the only one used here — a recall that reads the cache would confirm whatever it
was told.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from aughor.briefing import versions

#: The daily pass has run for this UTC day. Mirrors `recheck._last_run_day`.
_last_run_day: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def remeasure(conn_id: str, brief: dict, *, runner: Optional[Callable[[], Any]] = None) -> dict:
    """The stored Briefing's own metric queries, re-run against the WAREHOUSE, per metric.

    Returns ``{name: value}`` in the shape `versions.figures` produces, so the two are directly
    comparable. A metric whose query errors is omitted rather than recorded as zero — absent
    means "not measured now", which `versions.revisions` reports as such; a zero would be a
    figure the platform never read.
    """
    from aughor.knowledge.period_brief import connection_runner

    rows = ((brief.get("period") or {}).get("measured")
            if isinstance(brief.get("period"), dict) else None) or brief.get("measured") or []
    out: dict[str, float] = {}
    try:
        with (runner or (lambda: connection_runner(conn_id, cached=False)))() as (run_sql, _d):
            for m in rows:
                sql = str((m or {}).get("sql") or "").strip()
                name = str((m or {}).get("name") or "").strip()
                if not sql or not name:
                    continue
                try:
                    _cols, got, error = run_sql(sql)
                except Exception as exc:  # noqa: BLE001 — one metric's failure is not the pass's
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, f"{name} could not be re-measured; it is reported as "
                                  "unmeasured rather than unchanged",
                             counter="briefing.recall.metric")
                    continue
                if error:
                    continue
                value = _first_number(got)
                if value is not None:
                    out[name] = value
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a Briefing's recall could not open the connection; nothing is revised",
                 counter="briefing.recall.open")
        return {}
    return out


def recall_one(conn_id: str, artifact: dict, *, runner: Optional[Callable[[], Any]] = None,
               now: Optional[datetime] = None) -> dict:
    """Re-measure one stored Briefing and record a revision if its figures moved.

    Returns ``{"status": "unchanged" | "revised" | "unmeasured", ...}``. A typed verdict, not a
    bare dict-or-None: "nothing moved" and "nothing could be measured" are different facts and a
    caller that cannot tell them apart will report a dead connection as a stable Briefing.
    """
    payload = artifact.get("payload") or {}
    brief = payload.get("briefing") or {}
    fresh = remeasure(conn_id, brief, runner=runner)
    if not fresh:
        return {"status": "unmeasured", "revisions": []}
    moved = versions.revisions(versions.figures(brief), fresh)
    if not moved:
        return {"status": "unchanged", "revisions": []}
    rebuilt = _with_figures(brief, fresh)
    kept = versions.record(conn_id, rebuilt, scope_key=str(payload.get("scope_key") or ""),
                           range_key=str(payload.get("range_key") or ""),
                           recipe=str(payload.get("recipe") or ""),
                           as_of=(now or _now()).isoformat().replace("+00:00", "Z"))
    return {"status": "revised", "revisions": moved, "version": kept.get("version"),
            "artifact_id": kept.get("artifact_id")}


def revisions_since(conn_id: str, *, days: int = 1, now: Optional[datetime] = None) -> list[dict]:
    """The revisions recorded for this connection's Briefings in the last ``days``.

    What the next Day Briefing carries: "August's return rate, told as 10.0%, is now 12.4%".
    Read from the versions themselves rather than a second list, so a revision the store does
    not hold cannot appear in a Briefing — the page and the history cannot disagree.
    """
    cutoff = ((now or _now()) - timedelta(days=max(1, int(days)))).isoformat()
    out: list[dict] = []
    try:
        from aughor.kernel.ledger import Ledger
        for art in Ledger.default().artifacts_of_kind(versions.KIND, conn_id=conn_id, limit=50):
            payload = art.get("payload") or {}
            if str(art.get("created_at") or "") < cutoff:
                continue
            for r in payload.get("revisions") or []:
                if r.get("what") == "moved":
                    out.append({**r, "range": payload.get("range_key", ""),
                                "recipe": payload.get("recipe", ""),
                                "as_of": payload.get("as_of", "")})
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the revisions list is additive; the Briefing stands without it",
                 counter="briefing.recall.revisions")
    return out


def run_recall_daily(*, force: bool = False, now: Optional[datetime] = None,
                     runner: Optional[Callable[[], Any]] = None) -> dict:
    """Re-measure recent Briefings once a UTC day, from the heartbeat.

    Bounded the way `recheck` is bounded: only Briefings built inside its window, and the pass
    runs once a day. Off when `answers.recheck` is off — one switch for "re-check what we told
    people", because two switches is how one of them ends up forgotten in the on position.
    """
    global _last_run_day
    from aughor.answer.recheck import WINDOW_DAYS, enabled
    if not enabled():
        return {"skipped": "off"}
    now = now or _now()
    today = now.date().isoformat()
    if _last_run_day == today and not force:
        return {"skipped": "already ran today"}
    _last_run_day = today
    cutoff = (now - timedelta(days=WINDOW_DAYS)).isoformat()
    checked = revised = unmeasured = 0
    try:
        from aughor.kernel.ledger import Ledger
        recent = Ledger.default().artifacts_of_kind(versions.KIND, limit=100)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the Briefing recall could not read the store; nothing is revised",
                 counter="briefing.recall.scan")
        return {"skipped": "unreadable"}
    for art in recent:
        if str(art.get("created_at") or "") < cutoff:
            continue
        conn_id = str(art.get("conn_id") or "")
        if not conn_id:
            continue
        checked += 1
        out = recall_one(conn_id, art, runner=runner, now=now)
        revised += out["status"] == "revised"
        unmeasured += out["status"] == "unmeasured"
    return {"checked": checked, "revised": revised, "unmeasured": unmeasured}


def _with_figures(brief: dict, fresh: dict[str, float]) -> dict:
    """The Briefing with its measured figures replaced by what the warehouse says now.

    The narrative is left as written: it was true when it was written, and a version that
    silently re-wrote the prose around new numbers would destroy the record BR-6 exists to keep.
    """
    out = {k: v for k, v in (brief or {}).items()}
    block = dict(out.get("period") or {})
    rows = block.get("measured") if block else out.get("measured")
    updated = [{**m, "current": fresh.get(str(m.get("name") or ""), m.get("current"))}
               for m in (rows or [])]
    if block:
        block["measured"] = updated
        out["period"] = block
    else:
        out["measured"] = updated
    return out


def _first_number(rows) -> Optional[float]:
    for r in rows or []:
        for v in (r.values() if isinstance(r, dict) else r):
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                return float(v)
    return None
