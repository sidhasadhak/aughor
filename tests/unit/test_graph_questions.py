"""Wave P5 — the graph's own review queue.

The queue must be worth working through, which means three properties beyond "it returns
items": it ranks by CONSEQUENCE (how much depends on the doubtful thing), it is STABLE
between two reads of the same graph, and it never manufactures work — a fully measured
graph produces an empty queue.
"""
from __future__ import annotations

from aughor.ontology.context_graph import (
    ContextGraph, GraphEdge, GraphNode, Provenance,
)
from aughor.ontology.graph_questions import queue_summary, review_queue


def _table(cg, nid, label=None, summary="", sources=None):
    cg.add_node(GraphNode(id=nid, kind="table", label=label or nid.split(":")[-1],
                          summary=summary,
                          provenance=Provenance(source="ontology.entity"),
                          data={"source_tables": sources or [nid.split(":")[-1].lower()]}))


def _join(cg, a, b, *, overlap=None, confidence="inferred"):
    note = (f"value_overlap={overlap:.3f} join_confidence={confidence}" if overlap is not None
            else f"unprobed join_confidence={confidence}")
    cg.add_edge(GraphEdge(id=f"{a}--joins_on-->{b}", kind="joins_on", from_id=a, to_id=b,
                          provenance=Provenance(source="join_guard", measured=overlap, note=note)))


def _finding(cg, nid, text, **data):
    cg.add_node(GraphNode(id=nid, kind="finding", label=text[:40], summary=text,
                          provenance=Provenance(source="dossier"), data=data))


# ── the queue must not manufacture work ──────────────────────────────────────────

def test_a_fully_measured_graph_produces_an_empty_queue():
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:Order", summary="orders placed")
    _table(cg, "table:Customer", summary="people who buy")
    _join(cg, "table:Order", "table:Customer", overlap=0.99, confidence="verified")
    assert review_queue(cg) == []


# ── 1. unprobed joins — the highest-consequence item ─────────────────────────────

def test_a_name_matched_join_is_queued_with_a_one_click_probe():
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:Order", summary="x")
    _table(cg, "table:Product", summary="y")
    _join(cg, "table:Order", "table:Product")           # unprobed, name-matched
    [item] = review_queue(cg)
    assert item.type == "unprobed_join"
    assert item.check == "probe_join"
    assert "Order" in item.question and "Product" in item.question
    assert "invents rows" in item.why                    # the consequence, not the mechanism


def test_a_declared_foreign_key_is_queued_but_worded_differently_from_a_name_match():
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:A", summary="x")
    _table(cg, "table:B", summary="y")
    _join(cg, "table:A", "table:B", confidence="exact")   # declared FK, still unprobed
    [item] = review_queue(cg)
    assert item.detail["warrant"] == "declared"
    assert "declared by the schema" in item.why


def test_unprobed_joins_rank_by_how_much_depends_on_them():
    """The hub join comes first: a wrong join there is wrong in more answers."""
    cg = ContextGraph(org_id="o", connection_id="c")
    for t in ("Hub", "A", "B", "C", "Lonely", "Other"):
        _table(cg, f"table:{t}", summary="x")
    _join(cg, "table:Hub", "table:A", overlap=1.0, confidence="verified")
    _join(cg, "table:Hub", "table:B", overlap=1.0, confidence="verified")
    _join(cg, "table:Hub", "table:C")                 # unprobed, on a hub
    _join(cg, "table:Lonely", "table:Other")          # unprobed, on a leaf
    ranked = [i for i in review_queue(cg) if i.type == "unprobed_join"]
    assert ranked[0].subject_label.startswith("Hub")
    assert ranked[0].depends > ranked[1].depends


# ── 2. isolated tables ───────────────────────────────────────────────────────────

def test_an_unjoined_table_is_queued():
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:Order", summary="x")
    _table(cg, "table:Customer", summary="y")
    _table(cg, "table:Orphan", summary="z")
    _join(cg, "table:Order", "table:Customer", overlap=1.0, confidence="verified")
    [item] = review_queue(cg)
    assert item.type == "isolated_table"
    assert item.subject_id == "table:Orphan"


# ── 3+4. findings that need a human ──────────────────────────────────────────────

def test_a_contested_finding_reaches_a_human_instead_of_being_settled_by_recency():
    cg = ContextGraph(org_id="o", connection_id="c")
    _finding(cg, "finding:f1", "Revenue was 1.2M last quarter",
             contested=True, contested_variants=[{"text": "Revenue was 900k"}])
    [item] = review_queue(cg)
    assert item.type == "contested_finding"
    assert item.check == "review_finding"
    assert item.depends == 2                       # the survivor plus one alternative
    assert len(item.detail["variants"]) == 1


def test_an_ungrounded_finding_is_queued_for_retirement():
    cg = ContextGraph(org_id="o", connection_id="c")
    _finding(cg, "finding:f2", "Churn spiked in March",
             stale=True, stale_reason="grounding table `signups` is no longer in the ontology")
    [item] = review_queue(cg)
    assert item.type == "ungrounded_finding"
    assert "signups" in item.why


# ── 5. undocumented hubs ─────────────────────────────────────────────────────────

def test_an_undocumented_hub_is_queued_but_an_undocumented_leaf_is_not():
    """The queue has to stay workable: every undefined table would be noise."""
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:Hub")            # no summary, 2 joins → load-bearing and undefined
    _table(cg, "table:A", summary="x")
    _table(cg, "table:B", summary="y")
    _table(cg, "table:Leaf")           # no summary, 1 join → not worth a queue slot
    _join(cg, "table:Hub", "table:A", overlap=1.0, confidence="verified")
    _join(cg, "table:Hub", "table:B", overlap=1.0, confidence="verified")
    _join(cg, "table:Leaf", "table:A", overlap=1.0, confidence="verified")
    queued = {i.subject_id for i in review_queue(cg) if i.type == "undocumented_hub"}
    assert queued == {"table:Hub"}


def test_a_table_with_glossary_terms_counts_as_documented():
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:Hub", sources=["hub"])
    _table(cg, "table:A", summary="x")
    _table(cg, "table:B", summary="y")
    _join(cg, "table:Hub", "table:A", overlap=1.0, confidence="verified")
    _join(cg, "table:Hub", "table:B", overlap=1.0, confidence="verified")
    cg.add_node(GraphNode(id="glossary_term:hub.id", kind="glossary_term", label="id",
                          summary="the hub key",
                          provenance=Provenance(source="glossary"),
                          data={"table": "hub", "column": "id"}))
    assert not [i for i in review_queue(cg) if i.type == "undocumented_hub"]


# ── the graph's own shortfall outranks everything derived from it ────────────────

def test_a_drifted_graph_is_reported_first():
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:A", summary="x")
    _table(cg, "table:B", summary="y")
    _join(cg, "table:A", "table:B")     # would otherwise be item #1
    items = review_queue(cg, drift={"drifted": True, "reason": "100 findings missing",
                                    "missing": {"finding": 100}})
    assert items[0].type == "graph_behind"
    assert items[0].check == "rebuild"
    assert items[1].type == "unprobed_join"


def test_a_fresh_graph_gets_no_rebuild_item():
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:A", summary="x")
    assert not [i for i in review_queue(cg, drift={"drifted": False, "missing": {}})
                if i.type == "graph_behind"]


# ── the queue must be stable and bounded ─────────────────────────────────────────

def test_the_queue_is_byte_stable_across_reads():
    """A queue that reorders itself between two reads cannot be worked through."""
    cg = ContextGraph(org_id="o", connection_id="c")
    for t in ("A", "B", "C", "D"):
        _table(cg, f"table:{t}", summary="x")
    _join(cg, "table:A", "table:B")
    _join(cg, "table:C", "table:D")
    first = [i.to_dict() for i in review_queue(cg)]
    second = [i.to_dict() for i in review_queue(cg)]
    assert first == second


def test_limit_is_respected():
    cg = ContextGraph(org_id="o", connection_id="c")
    for i in range(30):
        _table(cg, f"table:T{i}", summary="x")
    items = review_queue(cg, limit=5)
    assert len(items) == 5


def test_summary_counts_by_type():
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:A", summary="x")
    _table(cg, "table:B", summary="y")
    _join(cg, "table:A", "table:B")
    _finding(cg, "finding:f", "text", contested=True, contested_variants=[])
    s = queue_summary(review_queue(cg))
    assert s["total"] == 2
    assert s["by_type"] == {"unprobed_join": 1, "contested_finding": 1}


def test_a_non_integer_limit_does_not_crash_a_direct_caller():
    """The HTTP handler's default arrives as a FastAPI Query object for any direct Python
    caller; slicing on it raised a TypeError that only a route test caught."""
    cg = ContextGraph(org_id="o", connection_id="c")
    _table(cg, "table:A", summary="x")
    _table(cg, "table:B", summary="y")
    _join(cg, "table:A", "table:B")
    assert len(review_queue(cg, limit=object())) == 1     # falls back to the default


def test_the_queue_declares_truncation_rather_than_capping_silently():
    """Rendering '50 things this graph cannot vouch for' over a warehouse with 300 would
    under-report the very thing the queue exists to report."""
    from aughor.ontology.graph_questions import queue_summary, review_queue_with_total

    cg = ContextGraph(org_id="o", connection_id="c")
    for i in range(12):
        _table(cg, f"table:A{i}", summary="x")
        _table(cg, f"table:B{i}", summary="y")
        _join(cg, f"table:A{i}", f"table:B{i}")      # 12 unprobed joins
    items, found = review_queue_with_total(cg, limit=5)
    s = queue_summary(items, total_found=found)
    assert s["total"] == 5
    assert s["total_found"] == 12
    assert s["truncated"] is True
    # …and an unlimited read declares no truncation
    items2, found2 = review_queue_with_total(cg, limit=100)
    assert queue_summary(items2, total_found=found2)["truncated"] is False
