"""Argument graph — the briefing's narrative layer, made structural.

Slice 3 of docs/BRIEFING_COCKPIT_2026-07-18.md. Turns the impact-ranked briefing findings
into a small directed graph the frontend renders as a node+edge lens over the linear brief.

Deterministic-first — this is what makes the graph *trustworthy* rather than decorative: nodes
and edges are derived from the SAME impact ranking the prose uses and from the explorer's OWN
typed edges (`composition_type` + `parents`, and `drill_of`), NOT from an LLM drawing arrows.

Edges point evidence → claim, so the DAG reads bottom-up to the verdict at its apex:

    supports                                   driver      → verdict   (impact ranking)
    chain / tension / confound / concentration / share
                                               parent      → synthesis (composition_type)
    explains_why                               drill child → parent    (drill_of)

Pure: no LLM, no I/O, no mutation of the inputs — so it is cheap to unit-test.
"""
from __future__ import annotations

from typing import Optional

VERDICT_ID = "verdict"

# The explorer's typed cross-finding relationships (aughor/explorer/synthesis.py OPERATORS).
COMPOSITION_TYPES = ("share", "tension", "concentration", "confound", "chain")


def _index_by_id(domain_data: dict[str, list[dict]]) -> dict[str, dict]:
    """id → insight over EVERY finding (all domains) so a parent/drill id resolves even when
    the referenced finding is not itself among the ranked drivers."""
    by_id: dict[str, dict] = {}
    for insights in domain_data.values():
        for ins in insights or []:
            iid = ins.get("id")
            if iid and iid not in by_id:
                by_id[iid] = ins
    return by_id


def build_argument_graph(
    top: list[dict],
    headline_theme: str,
    domain_data: dict[str, list[dict]],
    citations: Optional[list[dict]] = None,
    *,
    max_parents: int = 6,
) -> dict:
    """Build ``{"nodes": [...], "edges": [...]}`` from the ranked drivers ``top`` (the same
    impact-ordered list the narrative cites), the verdict ``headline_theme``, and the full
    ``domain_data`` (used only to resolve parent/drill ids). ``citations`` (the brief's
    ``[N]`` → finding map) flags which drivers the verdict prose actually rests on.

    Deterministic and side-effect-free. Returns an empty graph when there are no drivers.

    Node shape (frontend-owned rendering; engine-neutral):
        {id, kind: verdict|finding, title, domain, angle, impact, plausibility,
         has_sql, composition_type, is_driver, cited}
    Edge shape: {source, target, type}  — source is the evidence, target the claim.
    """
    citations = citations or []
    if not top:
        return {"nodes": [], "edges": []}

    by_id = _index_by_id(domain_data)
    cited_ids = {c.get("insight_id") for c in citations if c.get("insight_id")}

    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()
    edge_keys: set[tuple] = set()

    def _add_finding(ins: dict, *, is_driver: bool) -> Optional[str]:
        iid = ins.get("id")
        if not iid or iid in node_ids:
            return iid or None
        node_ids.add(iid)
        nodes.append({
            "id": iid,
            "kind": "finding",
            "title": ins.get("finding", ""),
            "domain": ins.get("domain", ""),
            "angle": ins.get("angle", ""),
            # `_impact` is the brief's internal score; fall back to the /domains annotation.
            "impact": round(float(ins.get("_impact", ins.get("impact", 0.0)) or 0.0), 4),
            "plausibility": ins.get("plausibility"),
            "has_sql": bool((ins.get("sql") or "").strip()),
            "composition_type": ins.get("composition_type"),
            "is_driver": is_driver,
            "cited": iid in cited_ids,
        })
        return iid

    def _add_edge(source: str, target: str, etype: str) -> None:
        key = (source, target, etype)
        if source and target and source != target and key not in edge_keys:
            edge_keys.add(key)
            edges.append({"source": source, "target": target, "type": etype})

    # 1) Verdict node — the headline, apex of the DAG.
    nodes.append({
        "id": VERDICT_ID, "kind": "verdict", "title": headline_theme or "This cycle",
        "domain": "", "angle": "", "impact": 1.0, "plausibility": None,
        "has_sql": False, "composition_type": None, "is_driver": False, "cited": False,
    })
    node_ids.add(VERDICT_ID)

    # 2) Driver nodes + a `supports` edge from each to the verdict.
    for ins in top:
        iid = _add_finding(ins, is_driver=True)
        if iid:
            _add_edge(iid, VERDICT_ID, "supports")

    # 3) The explorer's own typed edges among the drivers + the parent findings they reference.
    #    Bounded by max_parents so a dense synthesis run can't explode the graph into a hairball.
    added_parents = 0
    for ins in top:
        iid = ins.get("id")
        if not iid:
            continue

        # Synthesis: parent findings compose into this driver via a typed relationship.
        ctype = ins.get("composition_type")
        if ctype in COMPOSITION_TYPES:
            for pid in ins.get("parents") or []:
                parent = by_id.get(pid)
                if not parent:
                    continue
                if pid not in node_ids:
                    if added_parents >= max_parents:
                        continue
                    added_parents += 1
                    _add_finding(parent, is_driver=False)
                _add_edge(pid, iid, ctype)

        # Drill: this driver was a deeper look INTO another finding → it explains it. Only
        # connect a parent that is ALREADY in the graph, so no drill parent floats unrooted
        # (a composition parent is instead rooted via its synthesis→verdict path above).
        # Pulling drill parents in as new nodes is deferred densify work.
        drill_parent = ins.get("drill_of")
        if drill_parent and drill_parent in node_ids:
            _add_edge(iid, drill_parent, "explains_why")

    return {"nodes": nodes, "edges": edges}
