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
from aughor.kernel.flags import flag_enabled
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
_RECEIPT_KINDS = ("ada_report", "chat_answer")

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
_MAX_RECEIPT_FINDINGS = 100


def load_investigation_findings(
    connection_id: str, org_id: Optional[str] = None
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
    """
    from aughor.kernel.ledger import Ledger

    out: list[dict] = []
    # Ask for one past the cap so truncation is DETECTED rather than assumed from a
    # full page (a page that happens to be exactly full is not evidence of more).
    arts = Ledger.default().artifacts_of_kind(
        list(_RECEIPT_KINDS), conn_id=connection_id, org_id=org_id,
        limit=_MAX_RECEIPT_FINDINGS + 1)
    if len(arts) > _MAX_RECEIPT_FINDINGS:
        dropped = len(arts) - _MAX_RECEIPT_FINDINGS
        arts = arts[:_MAX_RECEIPT_FINDINGS]
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


def build_context_graph(
    connection_id: str,
    schema_name: Optional[str] = None,
    *,
    org_id: Optional[str] = None,
    persist: bool = True,
) -> Optional[ContextGraph]:
    """Build (and, by default, persist) the connection knowledge graph.

    Returns ``None`` when the flag is off (byte-identical: nothing read, nothing
    written) or when the connection has no built ontology yet — the graph is a
    projection *of* the ontology, so it cannot precede it.
    """
    if not flag_enabled("graph.build"):
        return None

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
    findings += _safe(
        lambda: load_investigation_findings(connection_id, resolved_org),
        "investigation_findings", [])

    cg = project_graph(
        ontology,
        org_id=resolved_org,
        connection_id=connection_id,
        schema_name=schema_name or getattr(ontology, "schema_name", "") or "",
        merged_glossary=merged_glossary,
        resolutions=resolutions,
        findings=findings,
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
    if not flag_enabled("graph.build"):
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

            before = len(cg.nodes)
            add_findings(cg, [finding])
            if len(cg.nodes) == before:
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
