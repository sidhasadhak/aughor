"""
Persist a user-initiated SQL fix from the Activity log.

When an explorer query errored and the user repairs it (per-row "Run fix" or bulk
"Fix all"), the corrected query should not just run on the surface — a *successful*
fix should be saved like any successful explorer query:

  1. **Heal the episode** — append a resolved turn so the Activity log reflects the
     fix as a successful query (append-only; never rewrites history).
  2. **Store a finding** — for domain-intelligence queries, interpret the result and
     store it as an insight that flows into Briefing / Hub / Domains — but through the
     *same* Phase-8 guards (degenerate / grounding / de-temporalisation). A fix that
     trips a guard is still stored (the user made the effort) but flagged
     ``unverified`` with a note, so it is visible yet down-weighted and never
     auto-promotable. A genuinely empty (degenerate) result has no finding to store.

This is deliberately a *repair* path — it never generates new questions and never
starts the explorer. "Fix all" simply maps this over the exact episodes it is handed.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from aughor.db.connection import open_connection_for
from aughor.sql.writer import SqlWriter
from aughor.llm.provider import get_provider
from aughor.explorer import store as _store
from aughor.explorer.episodes import EpisodeCollector
from aughor.explorer.grounding import verify_finding, numeric_cells_block
from aughor.explorer.agent import (
    _is_degenerate_result,
    _query_columns,
    _has_temporal_sql,
    _has_vacuous_temporal,
)

logger = logging.getLogger(__name__)


class _Interp(BaseModel):
    finding: str
    novelty: int = 3
    angle_covered: str = ""


# Phase-8 encodes its episode `think` as "Domain X | angle=Y | <question>".
_THINK_RE = re.compile(
    r"Domain\s+(?P<domain>[^|]+?)\s*\|\s*angle=(?P<angle>[^|]+?)\s*\|\s*(?P<question>.+)",
    re.S,
)


def _parse_think(think: str) -> tuple[Optional[str], Optional[str], str]:
    m = _THINK_RE.search(think or "")
    if m:
        return m.group("domain").strip(), m.group("angle").strip(), m.group("question").strip()
    return None, None, (think or "").strip()


def _is_domain_intel(phase: str, think: str) -> bool:
    return (phase or "").startswith("domain") or "angle=" in (think or "")


def _interpret(llm, *, domain: str, question: str, sql: str, rows, columns) -> _Interp:
    """Interpret a result into a finding — same grounding-aware prompt as Phase 8."""
    cells = numeric_cells_block(rows)
    result_text = "\n".join(str(r) for r in rows[:20])
    sys = (
        "You are interpreting a SQL query result as a concise business insight. Write 1-2 "
        "sentences. Include specific numbers from the result. CRITICAL: use ONLY numbers that "
        "appear in the result — copy each value exactly, never scale it or add a magnitude "
        "suffix (K/M/B) it does not already have. Novelty: 1=trivial, 5=genuinely new."
    )
    usr = (
        f"DOMAIN: {domain}\n"
        f"QUESTION: {question}\n"
        f"SQL:\n{sql}\n\n"
        f"SQL RESULT (first 20 rows):\n{result_text}\n\n"
        f"NUMERIC VALUES IN THE RESULT (cite these exactly):\n{cells}\n\n"
        "Interpret this result as a business insight."
    )
    return llm.complete(system=sys, user=usr, response_model=_Interp)


def persist_fixed_finding(
    conn_id: str,
    *,
    original_sql: str,
    error: str,
    think: str = "",
    phase: str = "domain_intel",
    hint: str = "",
    canvas_id: Optional[str] = None,
) -> dict:
    """Repair ``original_sql``, and on a successful run heal the episode and (for
    domain-intelligence queries) store a finding through the Phase-8 guards. Never
    generates new questions. Returns a result dict (see module docstring)."""
    out: dict = {"ok": False, "stored": False, "corrected_sql": original_sql}
    try:
        db = open_connection_for(conn_id)
    except Exception as e:
        out["error"] = f"connection not found: {e}"
        return out

    writer = SqlWriter(db)
    fix = writer.fix(original_sql, error or "", hint=hint, max_retries=2)
    if not fix.ok:
        out["error"] = fix.final_error or "could not repair the query"
        return out
    fixed_sql = fix.sql
    out["corrected_sql"] = fixed_sql
    out["explanation"] = fix.explanation

    result = db.execute("__fix_save__", fixed_sql)
    if getattr(result, "error", None):
        out["error"] = result.error
        return out

    rows = result.rows or []
    columns = result.columns or []
    out.update(ok=True, columns=columns,
               rows=[[str(c) for c in r] for r in rows[:50]])

    # 1. Heal the episode — a resolved turn so the Activity log shows a successful query.
    try:
        EpisodeCollector(conn_id, phase=phase or "domain_intel").add(
            think=f"✓ fix | {think}", sql=fixed_sql,
            observation=f"RESOLVED: {getattr(result, 'row_count', len(rows))} rows",
        )
    except Exception:
        pass

    # 2. Store a finding — domain-intelligence queries only.
    if not _is_domain_intel(phase, think):
        out["reason"] = "query fixed; not a domain-intelligence query, so there is no finding to store"
        return out

    if _is_degenerate_result(rows, ""):
        out["reason"] = "query fixed, but the result has no real data (all-NULL / empty) — nothing to store"
        return out

    domain, angle, question = _parse_think(think)
    domain = domain or "General"
    angle = angle or "fixed"

    # Guards → flags. A flagged finding is still stored (user effort), marked unverified.
    flags: list[str] = []
    removed = _query_columns(original_sql) - _query_columns(fixed_sql)
    if removed and _has_temporal_sql(original_sql) and not _has_temporal_sql(fixed_sql):
        flags.append("the repair removed all time logic from a time-based question (de-temporalised)")
    if _has_vacuous_temporal(fixed_sql):
        flags.append("the repair reduced the time computation to a constant (date difference of identical dates)")

    llm = get_provider("coder")
    try:
        interp = _interpret(llm, domain=domain, question=question, sql=fixed_sql,
                            rows=rows, columns=columns)
    except Exception as e:
        out["reason"] = f"query fixed, but interpretation failed ({e}) — not stored"
        return out

    g = verify_finding(interp.finding, rows)
    if not g.grounded:
        flags.append(f"unverifiable number(s): {', '.join(g.ungrounded)}")

    unverified = bool(flags)

    state = _store.load_canvas(canvas_id) if canvas_id else _store.load(conn_id)
    insights = state.setdefault("insights", [])
    insight_id = f"{domain}__{angle}__fix{len(insights) + 1}"
    insight = {
        "id": insight_id,
        "domain": domain,
        "angle": angle,
        "entities_involved": [],
        "dimensions": [],
        "measures": [],
        "finding": interp.finding,
        "sql": fixed_sql,
        # Flagged findings are pinned low so they never headline or auto-promote.
        "confidence": 0.3 if unverified else min(0.95, 0.4 + interp.novelty * 0.1),
        "novelty": 1 if unverified else interp.novelty,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canvas_id": canvas_id,
        "promoted_to_org": False,
        "promotion_confidence": 0.0,
        "source": "user_fix",
        "unverified": unverified,
        "verification_note": "; ".join(flags),
    }
    insights.append(insight)
    if canvas_id:
        _store.save_canvas(canvas_id, state)
    else:
        _store.save(conn_id, state)

    out.update(stored=True, insight={
        "id": insight_id, "domain": domain, "angle": angle,
        "finding": interp.finding, "unverified": unverified,
        "verification_note": insight["verification_note"],
    })
    out["reason"] = (
        "saved as a finding (UNVERIFIED — " + "; ".join(flags) + ")" if unverified
        else "saved as a finding"
    )
    logger.info(
        "[fix_persist:%s] %s/%s — stored %sfinding from user fix",
        conn_id, domain, angle, "UNVERIFIED " if unverified else "",
    )
    return out
