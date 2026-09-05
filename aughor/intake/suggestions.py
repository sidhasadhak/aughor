"""KI-4 (§3.10) — the suggestions loop: mine what the platform already witnesses.

The Snowflake study's biggest PORT item, landed where it belongs: validated runs and
recurring guard fires become PROPOSALS in the same accept/edit/dismiss lane as every
import. Nothing auto-applies; the miner judges nothing — it only states what happened,
deterministically, and every proposal carries the run it came from.

The populations are measured and PUBLISHED with every run (a catalogue is a
measurement with a timestamp): mining over a dozen examples is motion without
progress, and the numbers in the response are what say when that changes.

Two refusals built in, both grounded in the corpus laws:

* A question whose validated history holds MORE THAN ONE distinct SQL is divergence,
  not a candidate — proposing either variant would fabricate an attribution, and a
  wrong trusted query teaches a falsehood with full confidence. Those questions are
  counted and named for the consistency surface instead.
* A guard cluster with no subject is unmineable — a rule about nothing instructs
  nobody. (Measured live 2026-09-05: the only cluster ≥3 was 24 subject-less
  `preflight_repair` fires; the threshold and the subject requirement keep exactly
  that out.)
"""
from __future__ import annotations

import re
from typing import Any

#: A cluster smaller than this is noise; the response's populations say what was cut.
DEFAULT_MIN_FIRES = 3


def _norm_question(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def mine_trusted_from_examples(connection_id: str, *,
                               limit: int = 200) -> tuple[list[dict], dict]:
    """Validated (question, SQL) pairs → trusted-query proposals.

    Reads the `aughor_sql_examples` collection — every entry executed cleanly and
    returned rows on THIS connection (the indexer's own guarantee). One proposal per
    question, and only when the history holds exactly one distinct SQL for it.
    Returns ``(proposals, population)``.
    """
    from aughor.semantic.vector_store import scroll_payloads
    from aughor.tools.prior_analyses import SQL_EXAMPLES_COLLECTION

    payloads = [p for p in scroll_payloads(SQL_EXAMPLES_COLLECTION, limit=10_000)
                if str(p.get("connection_id") or "") == connection_id
                and (p.get("question") or "").strip()
                and len((p.get("sql") or "").strip()) >= 12]
    by_question: dict[str, list[dict]] = {}
    for p in payloads:
        by_question.setdefault(_norm_question(p["question"]), []).append(p)

    proposals: list[dict] = []
    divergent: list[str] = []
    for _norm, entries in sorted(by_question.items()):
        sqls = {e["sql"].strip() for e in entries}
        if len(sqls) > 1:
            divergent.append(entries[0]["question"])
            continue
        e = entries[0]
        runs = sorted({str(x.get("inv_id") or "") for x in entries if x.get("inv_id")})
        proposals.append({
            "question": e["question"],
            "sql": e["sql"].strip(),
            "note": ("Mined from validated run(s) " + ", ".join(runs)
                     + " — executed cleanly and returned rows on this connection. "
                       "Consistency-warranted until a human approves it."),
            "tags": ["mined:usage"],
            "source_runs": runs,
        })
        if len(proposals) >= limit:
            break
    population = {"sql_examples": len(payloads),
                  "questions": len(by_question),
                  "proposed": len(proposals),
                  "divergent_questions": divergent[:25]}
    return proposals, population


def mine_rules_from_guard_fires(connection_id: str, *,
                                min_fires: int = DEFAULT_MIN_FIRES,
                                limit: int = 2000) -> tuple[list[dict], dict]:
    """Recurring guard fires → business-rule proposals for the connection KB.

    Deterministic and factual: the rule body states WHAT fired, on WHAT, how often —
    prompt context that warns the SQL writer off a repeatedly-tripped footgun. Eval-
    phase fires are excluded (a corpus built from the benchmark trains on it), and a
    cluster with no subject is unmineable by construction.
    """
    from aughor.security.audit import GuardVerdicts

    rows = [r for r in GuardVerdicts.recent(limit=limit)
            if r.get("phase") != "eval"]
    clusters: dict[tuple[str, str], int] = {}
    for r in rows:
        pattern = str(r.get("pattern") or "").strip()
        subject = str(r.get("subject") or "").strip()
        if pattern and subject:
            clusters[(pattern, subject)] = clusters.get((pattern, subject), 0) + 1

    proposals = []
    for (pattern, subject), n in sorted(clusters.items()):
        if n < min_fires:
            continue
        proposals.append({
            "title": f"Recurring guard finding: {pattern} on {subject}",
            "body": (f"The {pattern} guard has fired {n} times on {subject} on this "
                     f"connection. Treat {subject} with care when writing SQL — check "
                     f"the guard's finding class before comparing, joining or "
                     f"filtering on it."),
            "tags": ["mined:guard", f"pattern:{pattern}"],
        })
    population = {"guard_fires": len(rows),
                  "clusters": len(clusters),
                  "clusters_meeting_threshold": len(proposals),
                  "min_fires": min_fires}
    return proposals, population


def unresolved_questions(connection_id: str, *, limit: int = 200) -> list[dict]:
    """Questions the platform could not answer — Snowflake's commonly-asked-but-
    unanswered surface, as a REPORT rather than staged candidates: an unanswered
    question has no SQL to stage, and writing one is exactly the human act the lane
    exists to receive (seed it through KI-0's door)."""
    from aughor.db.history import list_investigations

    rows = list_investigations(limit=1000)
    out: dict[str, dict] = {}
    for r in rows:
        if str(r.get("connection_id") or "") != connection_id:
            continue
        if str(r.get("status") or "") in ("complete", ""):
            continue
        q = _norm_question(str(r.get("question") or ""))
        if not q:
            continue
        cur = out.setdefault(q, {"question": r.get("question"), "count": 0,
                                 "statuses": set(), "last_id": ""})
        cur["count"] += 1
        cur["statuses"].add(str(r.get("status")))
        cur["last_id"] = cur["last_id"] or str(r.get("id") or "")
    ranked = sorted(out.values(), key=lambda x: -x["count"])[:limit]
    return [{**r, "statuses": sorted(r["statuses"])} for r in ranked]


def build_bundle(connection_id: str, *, min_fires: int = DEFAULT_MIN_FIRES,
                 limit: int = 200) -> tuple[dict | None, dict, list[dict]]:
    """One mining pass → ``(bundle-or-None, populations, unresolved)``.

    The bundle deliberately carries NO timestamp: an unchanged corpus must hash to
    the same bundle so a re-run dedupes to it and proposes nothing — the same
    idempotence law every other door in the lane obeys. The timestamp belongs to the
    RESPONSE, where the measurement lives."""
    trusted, pop_t = mine_trusted_from_examples(connection_id, limit=limit)
    rules, pop_g = mine_rules_from_guard_fires(connection_id, min_fires=min_fires)
    populations = {"trusted": pop_t, "rules": pop_g}
    sections: dict[str, Any] = {}
    if trusted:
        sections["trusted_queries"] = trusted
    if rules:
        sections["rules"] = rules
    bundle = None
    if sections:
        bundle = {"version": 1, "connection_id": connection_id,
                  "mined_from": "usage", "sections": sections}
    return bundle, populations, unresolved_questions(connection_id)
