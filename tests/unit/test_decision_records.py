"""Decision records — the closed-set choices the platform makes, kept in a trainable shape.

Four things under test, one per section: the store itself (a record round-trips and a
failed write costs a counter, never a turn), the three wired sites (the tool loop, the
route classifier, the definition chooser — each records what its decider actually saw),
and the exporter (deterministic, disjoint train/golden split, -1 rows excluded).
Hermetic via AUGHOR_DECISIONS_DB in conftest's allowlist — same commit as the store.
"""
from __future__ import annotations

import json
from pathlib import Path

from aughor.learning import decisions


def _wipe():
    """Each test starts from an empty table (the suite-wide temp DB is shared)."""
    import sqlite3
    p = decisions._db_path()
    if Path(p).exists():
        c = sqlite3.connect(p)
        c.execute("DELETE FROM decision_record")
        c.commit()
        c.close()


# ── the store ─────────────────────────────────────────────────────────────────────────

def test_a_decision_round_trips_with_its_menu_and_derived_label():
    _wipe()
    rid = decisions.record_decision(
        "test.site", "which tool?", ["alpha", "beta", "gamma"],
        chosen="beta", source="llm", confidence=0.8, outcome="ok")
    assert rid
    [row] = decisions.list_decisions(site="test.site")
    assert row["options"] == ["alpha", "beta", "gamma"]
    assert (row["label"], row["chosen"], row["outcome"]) == (1, "beta", "ok")
    stats = decisions.site_stats()["test.site"]
    assert (stats["total"], stats["labeled"], stats["with_outcome"]) == (1, 1, 1)


def test_choosing_nothing_listed_is_a_real_row_with_label_minus_one():
    _wipe()
    decisions.record_decision("test.site", "q", ["a", "b"], chosen="unlisted")
    [row] = decisions.list_decisions(site="test.site")
    assert row["label"] == -1
    assert decisions.list_for_export("test.site") == []      # not a trainable example


def test_mark_outcome_closes_the_loop():
    _wipe()
    rid = decisions.record_decision("test.site", "q", ["a", "b"], chosen="a")
    assert decisions.mark_outcome(rid, "accepted") is True
    assert decisions.list_decisions(site="test.site")[0]["outcome"] == "accepted"
    assert decisions.mark_outcome("no-such-id", "ok") is False


def test_a_failed_write_never_raises(monkeypatch):
    """The recorder sits on the answer path: a broken store must cost a counter, not a turn."""
    monkeypatch.setattr(decisions, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("disk gone")))
    assert decisions.record_decision("test.site", "q", ["a", "b"], chosen="a") == ""
    assert decisions.mark_outcome("x", "ok") is False


def test_context_and_options_are_capped():
    _wipe()
    decisions.record_decision("test.site", "x" * 10_000, ["y" * 10_000, "b"], chosen="b")
    [row] = decisions.list_decisions(site="test.site")
    assert len(row["context"]) == decisions._MAX_CONTEXT
    assert len(row["options"][0]) == decisions._MAX_OPTION


# ── the wired sites ───────────────────────────────────────────────────────────────────

def test_the_tool_loop_records_each_executed_choice_with_its_menu():
    _wipe()
    from aughor.agent.tool_loop import ToolSpec, run_tool_loop
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider

    params = {"type": "object", "properties": {}}
    tools = [
        ToolSpec(name="run_sql", description="d", parameters=params, run=lambda a: "412"),
        ToolSpec(name="list_tables", description="d", parameters=params,
                 run=lambda a: (_ for _ in ()).throw(ValueError("boom"))),
    ]
    set_responses([
        FauxToolCall(payload={}, name="run_sql"),
        FauxToolCall(payload={}, name="list_tables"),
        "answered",
    ])
    run_tool_loop(LLMProvider(backend="faux", role="coder"), "sys", "how many orders?", tools)

    rows = decisions.list_for_export("converse.tool")
    assert [(r["chosen"], r["outcome"]) for r in rows] == [("run_sql", "ok"), ("list_tables", "error")]
    # The menu is sorted, so labels are stable regardless of roster assembly order.
    assert all(r["options"] == ["list_tables", "run_sql"] for r in rows)
    assert [r["label"] for r in rows] == [1, 0]
    # The context is a routing glimpse — the question, never tool results.
    assert "how many orders?" in rows[0]["context"] and "412" not in rows[1]["context"]


def test_a_single_tool_roster_is_not_a_choice_and_records_nothing():
    _wipe()
    from aughor.agent.tool_loop import ToolSpec, run_tool_loop
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider

    set_responses([FauxToolCall(payload={}, name="only"), "done"])
    run_tool_loop(LLMProvider(backend="faux", role="coder"), "sys", "q",
                  [ToolSpec(name="only", description="d",
                            parameters={"type": "object", "properties": {}}, run=lambda a: "1")])
    assert decisions.list_decisions(site="converse.tool") == []


def test_the_route_classifier_records_the_final_route_not_the_raw_pick(monkeypatch):
    """The confidence floor re-routes a low-confidence 'direct' to 'investigate'; the
    record must carry the route the platform actually took — that is what a reflex
    would have to reproduce."""
    _wipe()
    import aughor.agent.nodes as nodes
    from aughor.agent.state import RouteDecision

    class _Stub:
        def complete(self, **kw):
            return RouteDecision(mode="direct", confidence=0.4, reasoning="uncertain")

    monkeypatch.setattr(nodes, "get_provider", lambda role: _Stub())
    effective, _ = nodes.classify_question("total revenue by region last month")
    assert effective == "investigate"

    [row] = decisions.list_decisions(site="ask.route")
    assert row["chosen"] == "investigate" and row["confidence"] == 0.4
    assert row["options"] == ["direct", "investigate", "explore", "final_text"]
    assert row["label"] == row["options"].index("investigate")


def test_the_definition_chooser_records_the_listing_it_showed(monkeypatch):
    _wipe()
    from aughor.ontology.models import OntologyGraph
    import aughor.agent.framing as AF
    from aughor.ontology.framing import frame_question

    repo = Path(__file__).resolve().parents[2]
    graph = OntologyGraph.model_validate(json.loads(
        (repo / "evals" / "ablation_olist_business_ontology.json").read_text()))

    class _Model:
        def __init__(self, answer):
            self.answer = answer

        def complete(self, *, system, user, response_model, temperature=None):
            return response_model(definition=self.answer)

    frame = frame_question("What was late last month?", graph)
    assert frame.ambiguous
    names = [c.name for c in frame.candidates()]

    AF.choose_definition(frame, graph, provider=_Model("delivery_breach_rate"))
    [row] = decisions.list_decisions(site="framing.definition")
    assert row["chosen"] == "delivery_breach_rate"
    assert row["label"] == names.index("delivery_breach_rate")
    assert row["options"][row["label"]].startswith("delivery_breach_rate:")

    _wipe()
    AF.choose_definition(frame, graph, provider=_Model(""))       # picked none of them
    [row] = decisions.list_decisions(site="framing.definition")
    assert (row["label"], row["chosen"]) == (-1, "")


# ── the exporter ──────────────────────────────────────────────────────────────────────

def _seed(n: int, site: str = "test.export"):
    for i in range(n):
        decisions.record_decision(site, f"question {i}", ["a", "b", "c"], chosen="abc"[i % 3])


def test_export_splits_disjointly_and_skips_unchosen_rows():
    _wipe()
    _seed(40)
    decisions.record_decision("test.export", "picked nothing", ["a", "b"], chosen="zzz")
    from aughor.learning import exporters
    out = exporters.export_decisions(site="test.export")["test.export"]
    total = out["choice"]["row_count"] + out["golden"]["row_count"]
    assert total == 40                                    # the -1 row is excluded
    assert out["choice"]["kind"] == "choice" and out["golden"]["kind"] == "choice_golden"
    from aughor.learning import store
    for row in store.rows_of(out["choice"]):
        assert set(row) == {"context", "options", "label", "task"}
        assert row["task"] == "decision:test.export"
        assert 0 <= row["label"] < len(row["options"])


def test_export_is_deterministic_and_idempotent():
    _wipe()
    _seed(12)
    from aughor.learning import exporters
    first = exporters.export_decisions(site="test.export")["test.export"]
    again = exporters.export_decisions(site="test.export")["test.export"]
    assert first["choice"]["data_id"] == again["choice"]["data_id"]
    assert first["choice"]["version"] == again["choice"]["version"]   # no new version minted
