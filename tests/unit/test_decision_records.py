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
    would have to reproduce.

    And the probability must describe THAT label. The model said 0.4 about `direct`; once
    the floor moved the route, carrying 0.4 across would file a number about one answer
    against a different one. An overridden route is therefore `rule` with no probability —
    the pick was the platform's, not the model's."""
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
    assert row["chosen"] == "investigate"
    assert row["options"] == ["direct", "investigate", "explore", "final_text"]
    assert row["label"] == row["options"].index("investigate")
    # The model's 0.4 was about "direct". The floor chose this label, so the row says so
    # and carries no probability — rather than filing 0.4 against an answer nobody gave it.
    assert row["source"] == "rule"
    assert row["confidence"] == 0.0


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


def test_each_tool_loop_caller_files_under_its_own_site():
    """The site is the caller's, not a literal in the loop.

    Until 2026-09-21 `run_tool_loop` hardcoded `"converse.tool"`, so the analyst — a
    different roster (11 tools, no `delegate_task`) behind a system prompt carrying the
    resolved spec — filed every pick under the conversational label. Measured on the live
    corpus that was **46 of 58 rows, 79%**, and the two populations were separable only by an
    accident of roster size. A site column that answers "which decider" wrongly cannot be
    segmented by decider at all, which is what every judgment measurement over it needs.
    """
    _wipe()
    from aughor.agent.tool_loop import ToolSpec, run_tool_loop
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider

    params = {"type": "object", "properties": {}}
    tools = [ToolSpec(name="run_sql", description="d", parameters=params, run=lambda a: "1"),
             ToolSpec(name="baseline", description="d", parameters=params, run=lambda a: "2")]

    set_responses([FauxToolCall(payload={}, name="run_sql"), "done"])
    run_tool_loop(LLMProvider(backend="faux", role="coder"), "sys", "q", tools,
                  site="analyst.tool")
    set_responses([FauxToolCall(payload={}, name="baseline"), "done"])
    run_tool_loop(LLMProvider(backend="faux", role="coder"), "sys", "q", tools,
                  site="converse.tool")

    assert [r["chosen"] for r in decisions.list_for_export("analyst.tool")] == ["run_sql"]
    assert [r["chosen"] for r in decisions.list_for_export("converse.tool")] == ["baseline"]


def test_the_default_site_is_unchanged_so_an_un_updated_caller_keeps_its_label():
    """The default must stay `converse.tool`. Changing it would start a THIRD population
    under a new name for callers nobody updated, which is the same unsegmentable corpus in a
    different spelling."""
    _wipe()
    from aughor.agent.tool_loop import ToolSpec, run_tool_loop
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider

    params = {"type": "object", "properties": {}}
    set_responses([FauxToolCall(payload={}, name="a"), "done"])
    run_tool_loop(LLMProvider(backend="faux", role="coder"), "sys", "q",
                  [ToolSpec(name="a", description="d", parameters=params, run=lambda x: "1"),
                   ToolSpec(name="b", description="d", parameters=params, run=lambda x: "2")])
    assert len(decisions.list_for_export("converse.tool")) == 1


# ── JD-4: what a replay needs, recorded under the posture that governs it ─────

import hashlib as _hashlib  # noqa: E402

import pytest as _pytest  # noqa: E402


@_pytest.fixture
def closed_window():
    """Every capture test starts and ends with the window CLOSED — the product's default, and
    the state a test that forgot to close one would otherwise leak into the next."""
    from aughor.obs import prompt_window as PW
    PW.close_window()
    yield PW
    PW.close_window()


def _loop(tools, responses, **kw):
    from aughor.agent.tool_loop import run_tool_loop
    from aughor.llm.faux import set_responses
    from aughor.llm.provider import LLMProvider
    set_responses(responses)
    return run_tool_loop(LLMProvider(backend="faux", role="coder"), "THE SYSTEM PROMPT", "q",
                         tools, **kw)


def _two_tools():
    from aughor.agent.tool_loop import ToolSpec
    params = {"type": "object", "properties": {}}
    return [ToolSpec(name="run_sql", description="d", parameters=params, run=lambda a: "1"),
            ToolSpec(name="baseline", description="d", parameters=params, run=lambda a: "2")]


def test_every_decision_carries_a_digest_of_what_the_decider_was_shown(closed_window):
    """ALWAYS written, window or no window: a sha256 cannot be reversed into the prompt, so it
    is metadata under §6 item 4. It is what lets a later rebuild PROVE it produced the same
    input before a token is spent."""
    from aughor.llm.faux import FauxToolCall
    _wipe()
    _loop(_two_tools(), [FauxToolCall(payload={}, name="run_sql"), "done"])
    [r] = decisions.list_decisions(site="converse.tool")
    assert r["prompt_digest"] == _hashlib.sha256(b"THE SYSTEM PROMPT").hexdigest()
    assert closed_window.active() is False, "writing a digest must not need, or open, a window"


def test_no_replay_payload_is_captured_while_the_window_is_closed(closed_window, monkeypatch):
    """The DEFAULT. The builder's arguments carry the user's question and prior answers — a
    payload — so nothing is emitted, and no operator's budget is spent, unless a window is open."""
    from aughor.llm.faux import FauxToolCall
    from aughor.obs import session_log
    emitted = []
    monkeypatch.setattr(session_log, "emit", lambda kind, **kw: emitted.append((kind, kw)))
    _wipe()
    _loop(_two_tools(), [FauxToolCall(payload={}, name="run_sql"), "done"],
          trace_id="tr-1", replay_args={"builder": "converse_system_prompt", "extra": "secret"})
    assert [k for k, _ in emitted if k == "decision_replay"] == []


def test_an_open_window_captures_the_first_turn_only(closed_window, monkeypatch):
    """A mid-loop decision saw a tool-result history persisted nowhere, so its arguments could
    not rebuild its prompt — capturing them would spend an operator's budget on a row no replay
    can use. Only the FIRST decision of a turn is captured."""
    from aughor.llm.faux import FauxToolCall
    from aughor.obs import session_log
    emitted = []
    monkeypatch.setattr(session_log, "emit", lambda kind, **kw: emitted.append((kind, kw)))
    closed_window.open_window(calls=10, minutes=5, opened_by="t", reason="jd-4 test")
    _wipe()
    _loop(_two_tools(),
          [FauxToolCall(payload={}, name="run_sql"), FauxToolCall(payload={}, name="baseline"),
           "done"],
          trace_id="tr-1",
          replay_args={"builder": "analyst_system_prompt", "intake": "{}", "budget": 6})
    replays = [kw for k, kw in emitted if k == "decision_replay"]
    assert len(replays) == 1, f"expected one capture (the first turn), got {len(replays)}"
    payload = replays[0]["payload"]
    assert payload["builder"] == "analyst_system_prompt"
    assert payload["question"] == "q"
    assert payload["prompt_digest"] == _hashlib.sha256(b"THE SYSTEM PROMPT").hexdigest()
    assert payload["requested_temperature"] == 0.1
    # The decision row and the capture are joinable, which is what the battery reads.
    first = [r for r in decisions.list_decisions(site="converse.tool")
             if r["context"].startswith("step 1 |")][0]
    assert payload["decision_id"] == first["id"]


def test_a_replay_capture_costs_exactly_one_unit_of_the_operators_budget(closed_window,
                                                                        monkeypatch):
    """The window's budget is SHARED with every other content capture — with a window open,
    each model call's prompt is stored too (`capture_prompt`). That is right: the window is the
    one control over how much sensitive content gets written, and a separate budget would let
    replay content bypass the operator's number.

    So what is pinned is the DELTA: the same turn run with and without replay arguments differs
    by exactly one unit. Not zero (the capture would be free, so unbounded) and not two (it would
    double-spend the operator's window).
    """
    from aughor.llm.faux import FauxToolCall
    from aughor.obs import session_log
    monkeypatch.setattr(session_log, "emit", lambda kind, **kw: None)
    responses = [FauxToolCall(payload={}, name="run_sql"), "done"]

    closed_window.open_window(calls=50, minutes=5)
    _wipe()
    _loop(_two_tools(), list(responses), trace_id="tr-a")
    spent_without = 50 - closed_window.status()["remaining"]

    closed_window.open_window(calls=50, minutes=5)
    _wipe()
    _loop(_two_tools(), list(responses), trace_id="tr-b",
          replay_args={"builder": "converse_system_prompt", "extra": "x"})
    spent_with = 50 - closed_window.status()["remaining"]

    assert spent_with - spent_without == 1, (
        f"a replay capture cost {spent_with - spent_without} units; it must cost exactly one")


def test_a_truncated_argument_is_marked_so_the_battery_can_refuse_it(closed_window, monkeypatch):
    """A capped intake rebuilds a DIFFERENT prompt. Marking it is what lets a replay refuse it
    instead of silently measuring a different question."""
    from aughor.obs import session_log
    monkeypatch.setattr(session_log, "_prompt_cap", lambda: 10)
    closed_window.open_window(calls=5, minutes=5)
    out = session_log.capture_replay({"intake": "x" * 50, "budget": 6})
    # `.get`, not indexing: a missing marker must FAIL AS AN ASSERTION that says what went
    # wrong. Indexing raised KeyError instead, which killed the mutant for the wrong reason —
    # a renamed key would crash the same way and the message would name neither.
    assert out.get("intake_truncated") is True, "a truncated argument was not marked"
    assert out["budget"] == 6


def test_the_ungated_decisions_door_no_longer_serves_the_users_question(client):
    """Measured live 2026-09-21: an UNAUTHENTICATED `GET /learning/decisions` answered 200 with
    58 rows whose `context` carried questions verbatim — a payload under §6 item 4, served with
    no gate while `obs/prompt_window.py` calls the question "the most sensitive thing this
    product can write down". The metadata the route exists for is still all there."""
    _wipe()
    decisions.record_decision("converse.tool", "step 1 | last (start) | what is my revenue?",
                              ["a", "b"], chosen="a", conn_id="c1", prompt_digest="d" * 64)
    body = client.get("/learning/decisions").json()
    [r] = body["recent"]
    assert "revenue" not in r["context"], "the question leaked through the ungated door"
    assert "§6 item 4" in r["payload_withheld"]
    # Metadata survives: the route's actual job.
    assert r["chosen"] == "a" and r["conn_id"] == "c1" and r["prompt_digest"] == "d" * 64
    assert body["stats"]
