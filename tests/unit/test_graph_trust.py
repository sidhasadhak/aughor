"""Wave P3 — the trust sidecar.

The property this wave turns on: **the labels must not blur use with verification.** A
table fourteen findings depend on is heavily used, not checked by anyone, and a surface
that called it "trusted" would be laundering a weak warrant into a strong one — the same
mistake `build_trusted_block` made in Wave L5.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aughor.ontology.context_graph import (
    ContextGraph, GraphEdge, GraphNode, Provenance,
)
from aughor.ontology.graph_trust import (
    CORROBORATION_MIN, VERDICT_HALF_LIFE_DAYS, build_trust,
)

NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


def _graph(findings):
    """`findings` = [(id, data_dict)] — each grounded in table:Order."""
    cg = ContextGraph(org_id="o", connection_id="c")
    cg.add_node(GraphNode(id="table:Order", kind="table", label="Order",
                          provenance=Provenance(source="ontology.entity"),
                          data={"source_tables": ["orders"]}))
    for fid, data in findings:
        cg.add_node(GraphNode(id=fid, kind="finding", label=fid, summary=fid,
                              provenance=Provenance(source="dossier"), data=data))
        cg.add_edge(GraphEdge(id=f"{fid}--grounded_in-->table:Order", kind="grounded_in",
                              from_id=fid, to_id="table:Order",
                              provenance=Provenance(source="dossier")))
    return cg


def _verdict(inv, verdict, *, days_ago=0):
    return {"investigation_id": inv, "verdict": verdict,
            "created_at": (NOW - timedelta(days=days_ago)).isoformat()}


# ── the distinction the whole wave rests on ──────────────────────────────────────

def test_many_findings_is_corroborated_never_confirmed():
    """Use is not verification. Nothing but a person may produce `confirmed`."""
    cg = _graph([(f"finding:f{i}", {}) for i in range(14)])
    t = build_trust(cg, now=NOW).get("table:Order")
    assert t.findings == 14
    assert t.standing == "corroborated"
    assert "none was checked by a person" in t.detail


def test_a_single_finding_is_not_corroboration():
    """One save cannot mint a trusted lesson."""
    cg = _graph([("finding:f1", {})])
    assert build_trust(cg, now=NOW).get("table:Order").standing == "unchecked"
    assert CORROBORATION_MIN == 2


def test_zero_verdicts_reports_unchecked_and_says_there_is_no_human_signal():
    """The state of every warehouse before anyone reviews anything — the honest report,
    stated in a field rather than left to be inferred from a row of zeros."""
    cg = _graph([("finding:f1", {})])
    sc = build_trust(cg, verdicts=[], now=NOW)
    assert sc.summary()["human_signal"] is False
    assert sc.summary()["verdicts_seen"] == 0
    assert sc.get("table:Order").standing == "unchecked"


# ── human verdicts ───────────────────────────────────────────────────────────────

def test_an_accept_confirms_the_nodes_the_finding_rests_on():
    cg = _graph([("finding:f1", {})])
    sc = build_trust(cg, verdicts=[_verdict("f1", "accept")], now=NOW)
    t = sc.get("table:Order")
    assert t.standing == "confirmed"
    assert sc.summary()["human_signal"] is True


def test_a_correction_counts_against_the_number_not_half_for_it():
    """'Right direction, wrong detail' means the figure a reader would have quoted was
    wrong — scoring it as a partial accept would report a wrong number as half-right."""
    cg = _graph([("finding:f1", {})])
    t = build_trust(cg, verdicts=[_verdict("f1", "correct")], now=NOW).get("table:Order")
    assert t.standing == "disputed"
    assert t.rejects > 0 and t.accepts == 0


def test_a_fresh_rejection_outweighs_an_old_acceptance():
    """Warehouses change; a decayed accept must not outrank a rejection recorded after
    the table was rebuilt."""
    cg = _graph([("finding:f1", {})])
    verdicts = [_verdict("f1", "accept", days_ago=int(VERDICT_HALF_LIFE_DAYS * 4)),
                _verdict("f1", "reject", days_ago=0)]
    t = build_trust(cg, verdicts=verdicts, now=NOW).get("table:Order")
    assert t.standing == "disputed"
    assert t.rejects > t.accepts


def test_verdict_weight_halves_over_the_half_life():
    cg = _graph([("finding:f1", {})])
    fresh = build_trust(cg, verdicts=[_verdict("f1", "accept")], now=NOW)
    old = build_trust(cg, verdicts=[_verdict("f1", "accept",
                                             days_ago=int(VERDICT_HALF_LIFE_DAYS))], now=NOW)
    assert abs(old.get("table:Order").accepts - fresh.get("table:Order").accepts / 2) < 0.01


def test_a_verdict_on_an_unknown_finding_scores_nothing():
    """No prose matching, no guessing: a verdict whose finding is not in the graph
    attributes to no node rather than to the nearest-looking one."""
    cg = _graph([("finding:f1", {})])
    sc = build_trust(cg, verdicts=[_verdict("nonexistent", "reject")], now=NOW)
    assert sc.get("table:Order").rejects == 0
    assert sc.verdicts_seen == 1     # counted as seen, so the tally stays honest


# ── a live disagreement outranks a tally ─────────────────────────────────────────

def test_contested_outranks_accepted_verdicts():
    """An accept cannot settle a disagreement about the numbers — only a decision can."""
    cg = _graph([("finding:f1", {"contested": True, "contested_variants": [{}]}),
                 ("finding:f2", {})])
    t = build_trust(cg, verdicts=[_verdict("f2", "accept")], now=NOW).get("table:Order")
    assert t.standing == "contested"
    assert "nobody has settled it" in t.detail


def test_stale_findings_block_corroboration():
    """Analyses standing on vanished data cannot corroborate anything."""
    cg = _graph([("finding:f1", {"stale": True}), ("finding:f2", {"stale": True})])
    t = build_trust(cg, now=NOW).get("table:Order")
    assert t.standing == "unchecked"
    assert t.stale == 2
    assert "no longer in the ontology" in t.detail


# ── the sidecar must stay a sidecar ──────────────────────────────────────────────

def test_nothing_is_written_back_into_the_graph():
    """Structural truth and experiential annotation age differently; a conclusion stamped
    into the structure outlives the evidence for it."""
    cg = _graph([("finding:f1", {})])
    before = cg.model_dump_json()
    build_trust(cg, verdicts=[_verdict("f1", "accept")], now=NOW)
    assert cg.model_dump_json() == before


def test_is_deterministic_for_a_fixed_now():
    cg = _graph([("finding:f1", {}), ("finding:f2", {})])
    v = [_verdict("f1", "accept", days_ago=30)]
    assert build_trust(cg, verdicts=v, now=NOW).to_dict() == \
           build_trust(cg, verdicts=v, now=NOW).to_dict()


def test_an_empty_graph_scores_nothing_without_raising():
    sc = build_trust(ContextGraph(org_id="o", connection_id="c"), now=NOW)
    assert sc.nodes == {}
    assert sc.summary()["scored_nodes"] == 0


def test_a_malformed_verdict_timestamp_does_not_crash_the_sidecar():
    cg = _graph([("finding:f1", {})])
    sc = build_trust(cg, verdicts=[{"investigation_id": "f1", "verdict": "accept",
                                    "created_at": "not-a-date"}], now=NOW)
    assert sc.get("table:Order").accepts > 0     # undecayed rather than dropped
