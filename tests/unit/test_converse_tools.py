"""The tools a converse turn may choose — and the inversion they enforce.

The point of these tests is not that the tools return data. It is that the model
cannot reach the warehouse EXCEPT through the guarded chokepoint, that the guard
receipts arrive with the rows rather than being reconstructed afterwards, and that a
tool asked about something that does not exist answers rather than raises.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.agent import converse_tools as ct


class _Result:
    def __init__(self, **kw):
        self.sql = kw.get("sql", "")
        self.columns = kw.get("columns", ["n"])
        self.rows = kw.get("rows", [[412]])
        self.row_count = kw.get("row_count", 1)
        self.error = kw.get("error")
        self.caveats = kw.get("caveats", [])


@pytest.fixture
def fake_conn(monkeypatch):
    # The real schema-render format: `TABLE: name` then two-space-indented columns.
    schema = "TABLE: analytics.orders\n  order_id  BIGINT\n  total  DOUBLE\n"
    conn = SimpleNamespace(get_schema=lambda: schema)
    monkeypatch.setattr(ct, "_connection", lambda cid: conn)
    return conn


def test_run_sql_goes_through_the_guarded_chokepoint(monkeypatch, fake_conn):
    """The inversion. The model picks the tool; the guards are not optional and not
    the model's to skip — so the tool must call `execute_guarded`, never a raw cursor."""
    seen = {}

    def _guarded(conn, sql, *, query_id, **kw):
        seen["sql"] = sql
        seen["query_id"] = query_id
        return _Result()

    monkeypatch.setattr("aughor.sql.executor.execute_guarded", _guarded)

    out = ct.run_sql("c1", {"sql": "SELECT count(*) FROM orders"})

    assert seen["sql"] == "SELECT count(*) FROM orders"
    assert out["row_count"] == 1


def test_guard_receipts_ride_back_with_the_rows(monkeypatch, fake_conn):
    """#279 shipped the collector with no consumer; this is it. A number handed over
    without the guard record is the thing this product exists not to do."""
    from aughor.kernel.registries import execution_hooks

    def _guarded(conn, sql, *, query_id, **kw):
        execution_hooks.emit_guard_receipt(
            "defan", "rewrote", "collapsed a fan-out join")
        return _Result()

    monkeypatch.setattr("aughor.sql.executor.execute_guarded", _guarded)

    out = ct.run_sql("c1", {"sql": "SELECT 1"})

    assert out["guard_receipts"], "the guards did something and the model was not told"
    assert out["guard_receipts"][0]["guard"] == "defan"


def test_caveats_reach_the_model(monkeypatch, fake_conn):
    """A query that ran without error can still be silently wrong — that knowledge has
    to arrive with the number, not be dropped at the boundary."""
    monkeypatch.setattr("aughor.sql.executor.execute_guarded",
                        lambda *a, **k: _Result(caveats=["value-disjoint join"]))

    assert ct.run_sql("c1", {"sql": "SELECT 1"})["caveats"] == ["value-disjoint join"]


def test_large_results_are_truncated_and_say_so(monkeypatch, fake_conn):
    """The model reasons about a shape. A 10k-row answer spends the context the rest of
    the conversation needs — but silently truncating would make it miscount."""
    monkeypatch.setattr("aughor.sql.executor.execute_guarded",
                        lambda *a, **k: _Result(rows=[[i] for i in range(500)],
                                                row_count=500))

    out = ct.run_sql("c1", {"sql": "SELECT 1"})

    assert len(out["rows"]) == ct._MAX_PREVIEW_ROWS
    assert out["truncated"] is True
    assert out["row_count"] == 500, "the true count must survive the preview"


def test_empty_sql_is_an_answer_not_a_crash(fake_conn):
    assert "error" in ct.run_sql("c1", {"sql": "   "})


def test_answer_question_runs_the_real_core_with_a_noop_emit(monkeypatch):
    """The tool is a second CALLER of the answer path, never a second answer path: it
    hands `answer_core` a no-op emit and reads the terminal state — guard receipts
    included, because a headline without the guard record is the thing this product
    exists not to hand people. Rows deliberately stay behind (the headline is the
    answer; rows spend the window)."""
    from aughor.routers import investigations as inv

    got: dict = {}

    def fake_core(question, connection_id, history, *, emit, **kw):
        got.update(question=question, connection_id=connection_id, history=history)
        emit("headline", {"headline": "streamed"})   # must vanish, not crash or collect
        return inv._AnswerCoreResult(
            outcome="answered", headline="Total is **412**", sql="SELECT 412",
            columns=["n"], rows=[[412]], row_count=1,
            guard_receipts=[{"guard": "headline_grounding", "action": "rewrote_headline"}],
            caveats=["approximate"],
        )

    monkeypatch.setattr(inv, "answer_core", fake_core)

    out = ct.answer_question("c1", {"question": "how many?"})

    assert got == {"question": "how many?", "connection_id": "c1", "history": []}
    assert out["outcome"] == "answered"
    assert out["headline"] == "Total is **412**"
    assert out["sql"] == "SELECT 412"
    assert out["columns"] == ["n"] and out["row_count"] == 1
    assert out["guard_receipts"][0]["guard"] == "headline_grounding"
    assert out["caveats"] == ["approximate"]
    assert "rows" not in out
    assert "error" not in out, "a clean turn must not carry an empty error key"


def test_answer_question_reports_a_failed_turn_as_a_value(monkeypatch):
    """A deliberate terminal failure (`query_failed`) is a RESULT the model can narrate
    and recover from — outcome plus the error, never a raise."""
    from aughor.routers import investigations as inv

    monkeypatch.setattr(inv, "answer_core", lambda *a, **k: inv._AnswerCoreResult(
        outcome="query_failed", error="Binder Error: no such column"))

    out = ct.answer_question("c1", {"question": "q"})

    assert out["outcome"] == "query_failed"
    assert "Binder Error" in out["error"]


def test_answer_question_without_a_question_is_an_answer_not_a_crash():
    assert "error" in ct.answer_question("c1", {})


def test_converse_can_choose_answer_question_through_the_loop(monkeypatch, fake_conn):
    """The loop-level proof of the wiring: the model names the tool, the loop finds it
    in the registered set, the arguments parse, and the terminal state survives the
    JSON hop back into the conversation."""
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider
    from aughor.routers import investigations as inv

    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.setattr(inv, "answer_core", lambda *a, **k: inv._AnswerCoreResult(
        outcome="answered", headline="Total is **412**", sql="SELECT 412",
        columns=["n"], rows=[[412]], row_count=1))
    set_responses([
        FauxToolCall(payload={"question": "how many orders?"}, name="answer_question"),
        "there are 412",
    ])

    result = ct.converse("c1", "how many orders?",
                         provider=LLMProvider(backend="faux", role="coder"))

    assert result.answer == "there are 412"
    assert [s.tool for s in result.steps] == ["answer_question"]
    assert result.steps[0].ok is True


def test_describe_table_finds_a_table_by_bare_name(fake_conn):
    """Models write `orders`, schemas store `analytics.orders`."""
    out = ct.describe_table("c1", {"table": "orders"})

    assert out["table"] == "analytics.orders"
    assert "order_id" in out["columns"]


def test_a_missing_table_answers_with_the_real_ones(fake_conn):
    """P2 again: the near-misses are what let the model recover instead of inventing
    a column list for a table that does not exist."""
    out = ct.describe_table("c1", {"table": "ordrs"})

    assert out["error"] == "no such table"
    assert "analytics.orders" in out["available"]


def test_the_connection_is_bound_not_model_supplied(fake_conn):
    """A tool that cannot express the wrong connection cannot be talked into it — so
    `connection_id` must not appear in any tool's parameter schema."""
    for spec in ct.converse_tools("c1"):
        props = spec.parameters.get("properties", {})
        assert "connection" not in props and "connection_id" not in props, spec.name


def test_every_tool_carries_a_description_that_can_route(fake_conn):
    """Descriptions ARE the routing policy (P3) — there is no intent classifier, so an
    empty or terse one is a tool the model cannot choose correctly."""
    for spec in ct.converse_tools("c1"):
        assert len(spec.description) > 60, f"{spec.name} cannot be routed on"


def test_the_system_prompt_states_rather_than_scripts(fake_conn):
    """It must name the warehouse and the guard contract without re-stating the routing
    policy, which would become a second, drifting copy of the tool descriptions."""
    prompt = ct.converse_system_prompt("superstore")

    assert "superstore" in prompt
    assert "caveat" in prompt.lower()
    assert "run_sql" not in prompt, "routing belongs in the tool descriptions, once"


def test_the_identity_is_the_platform_not_one_warehouse(fake_conn):
    """CI-3. The old identity — 'you answer questions about warehouse X' — was the
    single-warehouse voice the roadmap diagnosed; the new one is the platform-wide
    analyst, with the warehouse as one of the things it knows."""
    prompt = ct.converse_system_prompt("superstore")

    assert "You are answering questions about the data warehouse" not in prompt
    assert "platform" in prompt
    assert "findings" in prompt and "briefings" in prompt


def test_latitude_is_granted_in_both_directions(fake_conn):
    """General knowledge is allowed AND data claims are bound to tools — the two
    halves of CI-3's latitude, stated in the same prompt so neither reads as the
    whole rule."""
    prompt = ct.converse_system_prompt("c1")

    assert "General knowledge and reasoning are yours" in prompt
    assert "tool result" in prompt, "the data-claims boundary must be stated"


def test_the_stated_gap_line_survives_the_rewrite(fake_conn):
    """The roadmap's parenthetical: keep that line — it's right."""
    assert ("A stated gap is worth more than a plausible number"
            in ct.converse_system_prompt("c1"))


def test_clarifying_in_prose_is_granted(fake_conn):
    """A conversation that may only clarify through the chip widget is not a
    conversation — the prompt grants the prose path without scripting it."""
    assert "clarifying question" in ct.converse_system_prompt("c1")


def test_converse_is_off_by_default(monkeypatch):
    """`ask.converse` is an EXPERIMENT. Off means /ask behaves exactly as today."""
    monkeypatch.delenv("AUGHOR_ASK_CONVERSE", raising=False)
    assert ct.converse_available() is False


def test_the_flag_is_read_at_call_time_not_import_time(monkeypatch):
    """A module-level read makes the flag unflippable in a running process and turns
    `monkeypatch.setenv` into a no-op — the trap that once had tests spending the real
    LLM budget."""
    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")
    assert ct.converse_available() is True
    monkeypatch.delenv("AUGHOR_ASK_CONVERSE")
    assert ct.converse_available() is False


def test_converse_answers_end_to_end_through_the_loop(monkeypatch, fake_conn):
    """The body in one call: prompt + tools + loop, with the steps preserved so a route
    receipt can be built from them."""
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider

    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.setattr("aughor.sql.executor.execute_guarded",
                        lambda *a, **k: _Result())
    set_responses([
        FauxToolCall(payload={"sql": "SELECT count(*) FROM analytics.orders"}, name="run_sql"),
        "there were 412 orders",
    ])

    result = ct.converse("c1", "how many orders?",
                         provider=LLMProvider(backend="faux", role="coder"))

    assert result.answer == "there were 412 orders"
    assert [s.tool for s in result.steps] == ["run_sql"]
    assert result.steps[0].ok is True
