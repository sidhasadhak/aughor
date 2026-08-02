"""Build orchestration for the connection knowledge graph — Wave C1.

Gathers the deterministic sources (the built ontology, the merged glossary, the
crystallized ambiguity resolutions, the discovered findings) and hands them to the
pure projection in :mod:`aughor.ontology.context_graph`, then persists the committed
artifact. Every source read is best-effort: one empty or unavailable store degrades
that slice of the graph, never the whole build.

Gated behind ``graph.build`` (default off) so ``main`` is byte-identical until the
flag flips — C1 writes the artifact but nothing reads it back until C2.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from aughor.kernel.errors import tolerate
from aughor.org.context import current_org_id
from aughor.ontology.context_graph import ContextGraph, project_graph


def _safe(fn: Callable, what: str, default):
    """Run a source read, returning ``default`` (never raising) on failure so a
    single unavailable store can't sink the build."""
    try:
        return fn()
    except Exception as exc:
        tolerate(exc, f"context-graph source '{what}' is best-effort",
                 counter="context_graph.source_read")
        return default


def load_findings(connection_id: str) -> list[dict]:
    """Normalize the connection's discovered findings into the projection's finding
    shape ``{id, text, sql, tables, source, generated_at}``. Enumerated from the
    exploration store (conn-scoped, the enumerable source) and marked ``source=
    "dossier"`` when the finding carries a captured dossier in the Ledger — the
    write-only half of the open loop, finally a graph node."""
    from aughor.explorer.store import get_insights
    from aughor.explorer.scope import tables_in_sql

    out: list[dict] = []
    for ins in get_insights(connection_id):
        fid = str(ins.get("id") or "")
        text = str(ins.get("finding") or "")
        if not fid or not text:
            continue
        sql = str(ins.get("sql") or "")
        tables = sorted(tables_in_sql(sql)) if sql else []
        source = "dossier" if _has_dossier(connection_id, fid) else "exploration"
        out.append({
            "id": fid,
            "text": text,
            "sql": sql,
            "tables": tables,
            "source": source,
            "generated_at": ins.get("generated_at", ""),
        })
    return out


#: Answer-receipt kinds `_write_answer_receipt` lands (investigations.py). An ADA run
#: and a chat answer are both "Aughor looked and found something" — the graph treats
#: them as one finding kind and keeps the receipt kind in the node's data.
#:
#: Public because a second reader arrived (`semantic.answer_divergence`): two hand-kept
#: copies of this tuple is exactly how a new receipt kind gets read by one consumer and
#: not the other — the same drift shape the L1 glossary bug cost a session to find.
RECEIPT_KINDS = ("ada_report", "chat_answer")

#: How many answer receipts become finding nodes, newest first. The graph is a
#: committed, diff-readable artifact, so this is bounded on purpose — but the bound is
#: DECLARED and the drop is counted (`context_graph.receipts_truncated`), never silent.
#: Read-back caps its own slice far below this (`_MAX_FINDINGS` = 5), so the bound
#: trades disk and git-diff legibility, not prompt tokens.
#:
#: Chosen by measurement on the 412-receipt workspace connection (~36 serialized lines
#: per finding, on a 5,455-line no-findings baseline):
#:     cap  25 → 0.20 MB /  6,375 lines      cap 200 → 0.46 MB / 12,952 lines
#:     cap 100 → 0.32 MB /  9,356 lines      cap 400 → 0.76 MB / 20,023 lines
#: 100 keeps the artifact reviewable (~9k lines, under 2× the baseline) while giving
#: read-back a deep pool to match against; 400 made it a 20k-line file nobody diffs.
MAX_RECEIPT_FINDINGS = 100


def load_investigation_findings(
    connection_id: str, org_id: Optional[str] = None, *, limit: Optional[int] = None
) -> list[dict]:
    """Answer receipts → the projection's finding shape.

    The gap this closes: :func:`load_findings` enumerates the *explorer* store, while
    an investigation or a chat answer writes a Ledger receipt under ``ada:``/``chat:``
    keys. So every investigation Aughor has ever run was structurally invisible to the
    graph — no trigger could have fixed that, because the source was never read. The
    receipt already carries the two things a `finding` node needs (the headline and
    the tables its SQL touched, extracted at write time), so this is a read, not a
    re-derivation.

    Sourced ``evidence_ledger`` — the receipt's grounded claim, never a model's
    self-reported confidence (J4).

    ``limit`` defaults to :data:`MAX_RECEIPT_FINDINGS`, which is the **graph artifact's**
    size budget — a constraint about keeping a committed JSON diff-readable, and nothing
    to do with how many receipts are worth reading. A second consumer arrived (the eval
    corpus in :mod:`aughor.evals.from_receipts`) whose only limit is how much material
    exists, and it silently inherited the graph's budget: 628 receipts on this connection
    became a 100-receipt window, and because the window is newest-first, eval runs
    writing their own receipts pushed the older, more varied questions out of it.
    Two consumers, two honest limits, one parameter.
    """
    from aughor.kernel.ledger import Ledger

    cap = MAX_RECEIPT_FINDINGS if limit is None else max(1, int(limit))
    out: list[dict] = []
    # Ask for one past the cap so truncation is DETECTED rather than assumed from a
    # full page (a page that happens to be exactly full is not evidence of more).
    arts = Ledger.default().artifacts_of_kind(
        list(RECEIPT_KINDS), conn_id=connection_id, org_id=org_id, limit=cap + 1)
    if len(arts) > cap:
        dropped = len(arts) - cap
        arts = arts[:cap]
        from aughor.stats import bump
        bump("context_graph.receipts_truncated", dropped)
    for art in arts:
        payload = art.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        # The headline IS the finding; a receipt without one never concluded anything,
        # so it is not a finding node (the question alone is not a discovery).
        text = str(payload.get("headline") or "").strip()
        fid = str(art.get("id") or "")
        if not fid or not text:
            continue
        out.append({
            "id": fid,
            "text": text,
            "sql": str(payload.get("sql") or ""),
            "tables": [str(t) for t in (payload.get("tables") or [])],
            "source": "evidence_ledger",
            "generated_at": art.get("created_at", ""),
            "receipt_kind": art.get("kind", ""),
            "question": str(payload.get("question") or ""),
        })
    return out


def load_briefs(connection_id: str) -> list[dict]:
    """The connection's synthesized brief, normalized to ``{id, text, theme,
    citations, generated_at}``.

    A brief has no persisted entity — it lives as an entry in the briefing cache,
    keyed by ``scope_key`` (which defaults to the connection id). Only the entry keyed
    by this connection is projected: canvas briefs are keyed ``canvas:<id>``, which
    does not name the connection, and attributing one by guessing would ground a brief
    in data it may never have read.
    """
    from aughor.knowledge.briefing import peek_briefing

    entry = peek_briefing(connection_id)
    if not isinstance(entry, dict):
        return []
    narrative = str(entry.get("narrative") or "").strip()
    if not narrative:
        return []
    citations = [
        str(c.get("insight_id") or "")
        for c in (entry.get("citations") or [])
        if isinstance(c, dict) and c.get("insight_id")
    ]
    return [{
        "id": connection_id,
        "text": narrative,
        "theme": str(entry.get("headline_theme") or ""),
        "citations": citations,
        "generated_at": str(entry.get("generated_at") or ""),
    }]


def note_brief(
    connection_id: str,
    brief: dict,
    *,
    org_id: Optional[str] = None,
    schema_name: Optional[str] = None,
) -> bool:
    """Add/refresh ONE brief on the connection's committed graph, in place.

    The brief twin of :func:`note_finding` — same gating, same lock, same
    decline-rather-than-guess rule, and the same projector the full build uses
    (``context_graph.add_briefs``), so the incremental and rebuilt nodes agree.
    """
    if _suppressed_for_measurement():
        return False
    from aughor.ontology.context_graph import add_briefs
    from aughor.ontology.context_graph_store import (
        load_graph, load_graphs_for_connection, save_graph,
    )

    resolved_org = org_id or current_org_id()
    try:
        with _WRITE_LOCK:
            cg = None
            if schema_name is not None:
                cg = load_graph(resolved_org, connection_id, schema_name)
            if cg is None:
                built = load_graphs_for_connection(resolved_org, connection_id)
                if len(built) != 1:
                    return False
                cg = built[0]

            # A regenerated brief reuses its node id, so a node COUNT cannot tell an
            # update from a rejection — the emitted-ids list can.
            if not add_briefs(cg, [brief]):
                return False
            save_graph(cg)
            return True
    except Exception as exc:
        tolerate(exc, "incremental brief write is best-effort; the next full build "
                      "projects the brief from the cache",
                 counter="context_graph.note_brief")
        return False


def _has_dossier(connection_id: str, insight_id: str) -> bool:
    """True iff a captured dossier artifact exists for this finding (the derivation
    the CEO-'how was this derived?' path renders). Best-effort — a Ledger miss just
    means the finding is sourced as a plain exploration insight."""
    try:
        from aughor.kernel.ledger import Ledger
        art = Ledger.default().artifact_latest(f"insight:{connection_id}:{insight_id}")
        return bool(art and (art.get("payload") or {}).get("dossier"))
    except Exception:
        return False


#: How many receipts to read per finding slot when consolidating (Wave N3). Consolidation
#: only pays off if it can see the repeats it is folding, and the repeats live BEHIND the
#: cap — reading exactly `cap` receipts and then consolidating just shrinks the corpus.
#:
#: Chosen by measurement on the 794-receipt reference connection (cap 100), counting how
#: many LIVE distinct subjects survive into the capped slice:
#:     1× → 59    3× → 68    5× → 89    8× → 100
#:     2× → 63    4× → 73    6× → 100  10× → 100 (the ledger is exhausted at ~8×)
#: 6× saturates here; 8× is taken for headroom on a longer history, and costs one bounded
#: read of a local store — no warehouse query, no LLM.
CONSOLIDATION_OVERFETCH = 8


def _consolidated_investigation_findings(
    connection_id: str, org_id: Optional[str], schema_name: Optional[str],
) -> list[dict]:
    """Receipt-sourced findings for the projection — consolidated first when N3 is on.

    Over-fetch, fold repeated subjects together, age out findings whose grounding has
    vanished, and only THEN apply the cap — so the artifact's node budget buys distinct
    live knowledge rather than the 100 most recent receipts.
    """
    from aughor.ontology.finding_consolidation import consolidate, live_tables_for

    raw = _safe(
        lambda: load_investigation_findings(
            connection_id, org_id, limit=MAX_RECEIPT_FINDINGS * CONSOLIDATION_OVERFETCH),
        "investigation_findings", [])
    if not raw:
        return []
    live = _safe(lambda: live_tables_for(connection_id, schema_name),
                 "consolidation_live_tables", None)
    survivors, report = consolidate(raw, live_tables=live)

    from aughor.stats import bump
    bump("context_graph.consolidation_superseded", report.superseded)
    bump("context_graph.consolidation_contested", report.contested_subjects)
    bump("context_graph.consolidation_stale", report.stale)
    if not report.balanced:
        # Count-in ≠ count-out means a finding was lost in consolidation — the one outcome
        # this module exists to make impossible. Say so loudly rather than shipping a
        # quietly-thinner graph.
        from aughor.kernel.errors import tolerate
        tolerate(RuntimeError(f"consolidation lost findings: {report.to_dict()}"),
                 "finding consolidation must be lossless",
                 counter="context_graph.consolidation_unbalanced")
        return _safe(lambda: load_investigation_findings(connection_id, org_id),
                     "investigation_findings", [])

    kept = survivors[:MAX_RECEIPT_FINDINGS]
    if len(survivors) > MAX_RECEIPT_FINDINGS:
        bump("context_graph.consolidation_capped", len(survivors) - MAX_RECEIPT_FINDINGS)
    return kept


def build_context_graph(
    connection_id: str,
    schema_name: Optional[str] = None,
    *,
    org_id: Optional[str] = None,
    persist: bool = True,
) -> Optional[ContextGraph]:
    """Build (and, by default, persist) the connection knowledge graph.

    Returns ``None`` when the connection has no built ontology yet — the graph is a
    projection *of* the ontology, so it cannot precede it.
    """
    from aughor.ontology.store import load_latest_ontology

    resolved_org = org_id or current_org_id()
    ontology = _safe(lambda: load_latest_ontology(connection_id, schema_name),
                     "ontology", None)
    if ontology is None:
        return None

    merged_glossary = _safe(_load_glossary, "glossary", {})
    resolutions = _safe(
        lambda: _list_resolutions(connection_id, resolved_org), "ambiguity_ledger", [])
    findings = _safe(lambda: load_findings(connection_id), "findings", [])
    # Two independent sources, each best-effort: the explorer's insights and the
    # answer receipts. Ids cannot collide (insight id vs artifact id) and either
    # store being empty just thins that slice.
    findings += _consolidated_investigation_findings(
        connection_id, resolved_org, schema_name)

    briefs = _safe(lambda: load_briefs(connection_id), "briefs", [])

    cg = project_graph(
        ontology,
        org_id=resolved_org,
        connection_id=connection_id,
        schema_name=schema_name or getattr(ontology, "schema_name", "") or "",
        merged_glossary=merged_glossary,
        resolutions=resolutions,
        findings=findings,
        briefs=briefs,
    )

    if persist:
        try:
            from aughor.ontology.context_graph_store import save_graph
            save_graph(cg)
        except Exception as exc:
            tolerate(exc, "context-graph persistence is best-effort; the built graph "
                          "is still returned to the caller",
                     counter="context_graph.persist")
    return cg


#: Graph writes are read-modify-write (`save_graph` loads the prior version to bump
#: `version`), so two concurrent answers on one connection could lose a node. Writes
#: are serialized here rather than declared parallel-safe — Wave R5's rule is that the
#: check sits on the DANGEROUS side, and a file mutation genuinely is not safe.
_WRITE_LOCK = threading.Lock()


def _suppressed_for_measurement() -> bool:
    """True while a frozen eval grid is running.

    An answer produced during a measured run must not grow the graph, because the next
    cell would then read what the previous cell wrote and the two cells would differ by
    something neither of them varied. Suppressing the write is safe: it is a
    best-effort side effect that changes no answer, and the receipt still lands, so the
    next full build projects the finding afterwards.

    Imported lazily and tolerantly — the evals package must never become a hard
    dependency of the answer path.
    """
    try:
        from aughor.evals.frozen import measurement_frozen
        return measurement_frozen()
    except Exception:
        return False


def note_finding(
    connection_id: str,
    finding: dict,
    *,
    org_id: Optional[str] = None,
    schema_name: Optional[str] = None,
) -> bool:
    """Add ONE finding to the connection's committed graph, in place.

    The live-path half of Wave L1. A full rebuild per answer would re-read the whole
    ontology and rewrite a ~9k-line artifact for one node, and C3's ``classify`` would
    refuse anyway — it compares *schema* fingerprints, and a new finding changes no
    schema. So the answer path writes incrementally and the scheduled refresh keeps
    doing structural work.

    Returns True iff a node was added and persisted. False (never raises) when the
    flag is off, no graph has been built yet for this connection, or the write fails —
    a missing graph is not an error, it just means the next full build picks the
    finding up from :func:`load_investigation_findings`.

    The node is emitted by ``context_graph.add_findings`` — the SAME projector the full
    build uses — so the incremental and rebuilt graphs cannot drift into two shapes.
    """
    if _suppressed_for_measurement():
        return False
    from aughor.ontology.context_graph import add_findings
    from aughor.ontology.context_graph_store import (
        load_graph, load_graphs_for_connection, save_graph,
    )

    resolved_org = org_id or current_org_id()
    try:
        with _WRITE_LOCK:
            # Load the ONE schema's graph, never the merged view: a merged graph has an
            # ambiguous schema_name and would be written back to the wrong file.
            cg = None
            if schema_name is not None:
                cg = load_graph(resolved_org, connection_id, schema_name)
            if cg is None:
                built = load_graphs_for_connection(resolved_org, connection_id)
                if len(built) != 1:
                    # Zero → nothing to add to. More than one → the caller did not say
                    # which schema, and guessing would put the finding on the wrong one.
                    return False
                cg = built[0]

            if not add_findings(cg, [finding]):
                return False  # rejected by the projector (no id/text) — nothing to save
            save_graph(cg)
            return True
    except Exception as exc:
        tolerate(exc, "incremental finding write is best-effort; the finding is still "
                      "in the Ledger and the next full build projects it",
                 counter="context_graph.note_finding")
        return False


def _load_glossary() -> dict:
    """The merged glossary as the projection wants it: a ``{table: meta}`` mapping.

    ``load_merged_glossary`` returns the *envelope* ``{"tables": {table: meta}}``, and
    the projection iterates its argument as table→meta. Handing over the envelope made
    the loop run exactly once, on the literal key ``"tables"``, which then failed the
    connection-scope check — so every glossary term on every connection was silently
    dropped and the ``defines`` edge kind was unreachable. Unwrap here, at the boundary
    that knows the store's shape.
    """
    from aughor.semantic.glossary import load_merged_glossary
    merged = load_merged_glossary() or {}
    return merged.get("tables", merged)


def _list_resolutions(connection_id: str, org_id: str) -> list:
    from aughor.semantic.ambiguity_ledger import list_resolutions
    return list_resolutions(connection_id, org_id)
