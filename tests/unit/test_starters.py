"""R13 — named research-starter playbooks + per-space curated questions.

The library is deterministic templates (question + declared mode + purpose tag):
no model in the loop. Locked invariants: the explore-mode starters' phrasing
passes R9's wide detector (template and router agree by construction), the
AskRequest mode override pins the route without a classifier call, and
/suggestions surfaces the library only behind `starters.library`.
"""
from __future__ import annotations

import pytest

from aughor.starters import (
    STARTERS,
    curated_questions,
    named_starters,
    starter_payload,
)


# ── the library itself ───────────────────────────────────────────────────────

def test_library_shape_and_stable_ids():
    ids = [s.id for s in STARTERS]
    assert ids == ["outlier_entities", "where_are_we_losing_money", "data_quality_scan"]
    for s in STARTERS:
        assert s.mode in ("investigate", "explore")
        assert s.purpose and s.question and s.title


def test_payload_speaks_the_chip_contract():
    for p in named_starters():
        assert set(p) >= {"id", "text", "mode", "purpose", "title", "source"}
        assert p["source"] == "library"
        assert "question" not in p                        # renamed to `text` for chips


def test_explore_starters_phrase_wide_by_construction():
    """The template and R9's router must agree: even a client that drops the
    `mode` field gets the explore wave via is_wide_question + explore.route_wide."""
    from aughor.agent.ask_router import is_wide_question
    from aughor.agent.complexity import assess_complexity
    for s in STARTERS:
        if s.mode == "explore":
            assert is_wide_question(s.question, assess_complexity(s.question)), s.id


# ── the router honors a starter's declared mode, deterministically ───────────

def _boom_classifier(question):
    raise AssertionError("mode override must not consult the classifier")


@pytest.mark.parametrize("mode", ["investigate", "explore"])
def test_mode_override_pins_route_without_classifier(mode):
    from aughor.agent.ask_router import decide_ask_route
    route = decide_ask_route("anything at all", mode_override=mode,
                             classifier=_boom_classifier)
    assert route.depth == "deep"
    assert route.mode == mode
    assert route.forced == "mode"


def test_mode_override_none_leaves_routing_unchanged():
    from aughor.agent.ask_router import decide_ask_route
    route = decide_ask_route("what tables are available?", mode_override=None)
    assert route.forced != "mode"


def test_mode_override_degrades_without_deep_capability():
    from aughor.agent.ask_router import decide_ask_route
    route = decide_ask_route("anything", mode_override="explore", has_deep=False)
    assert route.depth == "quick" and route.downgraded_from == "deep"


# ── curated questions from the R8 doc tree ───────────────────────────────────

def _tree():
    from aughor.ontology.doctree import build_doc_tree
    from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph
    def ent(eid, measure):
        return OntologyEntity(
            id=eid, display_name=eid.title(), source_tables=[eid],
            identity_key="id", grain_verified=True,
            properties={
                measure: EntityProperty(name=measure, data_type="DOUBLE",
                                        semantic_type="measure"),
                "region": EntityProperty(name="region", data_type="VARCHAR",
                                         semantic_type="dimension"),
            })
    graph = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="f",
                          entities={"sales": ent("sales", "amount"),
                                    "orders": ent("orders", "total")})
    return build_doc_tree(graph, table_stats={
        "sales": {"row_count": 10, "query_popularity": 9},
        "orders": {"row_count": 100},
    })


def test_curated_questions_round_robin_popularity_first():
    got = curated_questions("c", "s", tree=_tree(), limit=4)
    assert got, "doc-tree questions must project into starters"
    assert all(g["source"] == "curated" and g["mode"] == "investigate" for g in got)
    # popularity beats row_count: sales (popularity 9) asks before orders (100 rows)
    assert got[0]["table"] == "Sales"
    assert got[1]["table"] == "Orders"                    # round-robin, not all-of-one-table


def test_curated_questions_empty_without_tree(monkeypatch, tmp_path):
    monkeypatch.setattr("aughor.ontology.doctree.load_doc_tree", lambda c, s: None)
    assert curated_questions("c-none", "s") == []


def test_starter_payload_is_library_then_curated():
    payload = starter_payload("c-none", "nope")           # no tree → library only
    assert [p["id"] for p in payload[:3]] == [s.id for s in STARTERS]


# ── /suggestions surfaces the library only behind the flag ───────────────────

def test_suggestions_carries_starters_only_when_flag_on(client, monkeypatch):
    def _fake_suggestions(*a, **k):
        return [{"text": "q", "mode": "ask"}]
    # Avoid the LLM: serve from the fingerprint cache.
    monkeypatch.setattr("aughor.semantic.suggestions_cache.get_cached",
                        lambda cid, fp: [{"text": "cached q", "mode": "ask"}])

    r = client.get("/suggestions", params={"connection_id": "fixture"})
    assert r.status_code == 200
    assert "starters" not in r.json()                     # flag off → byte-identical

    monkeypatch.setenv("AUGHOR_STARTERS_LIBRARY", "1")
    r = client.get("/suggestions", params={"connection_id": "fixture"})
    body = r.json()
    assert r.status_code == 200
    ids = [s["id"] for s in body["starters"]]
    assert "outlier_entities" in ids and "where_are_we_losing_money" in ids
    assert all({"text", "mode", "purpose"} <= set(s) for s in body["starters"])
