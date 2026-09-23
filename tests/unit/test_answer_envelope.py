"""Arc CP · CP-4 — the answer envelope: the core emits structure, a door renders it.

The two CP-0 defects are the acceptance test (ROADMAP §3.22): a measured Slack answer on
2026-09-23 carried the same five rows twice — the model's prose table plus the attached
grid — and narrated the guard receipts to the reader. Here both are reproduced against the
old shape (prose + grid, two tables) and shown impossible on the envelope (the grid is one
field; receipts are a provenance field a door drops).
"""
from __future__ import annotations

from aughor.answer import AnswerEnvelope, Grid, lift_tables
from aughor.answer.doors import (
    gfm_table, render_grid_markdown, select_for_slack, slack_message,
)
from aughor.answer.envelope import first_line, fold_frames

# ── the 2026-09-23 shape, as frames ─────────────────────────────────────────────

COLUMNS = ["product_category", "revenue"]
ROWS = [["Outerwear & Coats", 41230.5], ["Jeans", 30110.0], ["Sweaters", 21870.25],
        ["Suits & Sport Coats", 19940.0], ["Swim", 8120.75]]

#: What the model wrote: its OWN table, with different headers, over the same rows.
PROSE = (
    "Outerwear & Coats led revenue last month at $41.2K.\n\n"
    "| # | Category | Revenue |\n|---|---|---|\n"
    "| 1 | Outerwear & Coats | $41,230 |\n| 2 | Jeans | $30,110 |\n| 3 | Sweaters | $21,870 |\n"
    "| 4 | Suits & Sport Coats | $19,940 |\n| 5 | Swim | $8,121 |\n\n"
    "Jeans and Sweaters follow at some distance.\n\n"
    "No guard receipts fired on this query."
)


def converse_frames(prose: str = PROSE) -> list[dict]:
    return [
        {"type": "sql", "sql": "SELECT product_category, SUM(sale_price) AS revenue FROM t GROUP BY 1"},
        {"type": "columns", "columns": COLUMNS},
        {"type": "rows", "rows": ROWS},
        {"type": "chart_type", "chart_type": "bar"},
        {"type": "chart_config", "chart_config": {"exhibit": {"kind": "ranked"}}},
        {"type": "tables_used", "tables": ["order_items", "products"]},
        {"type": "guard_receipt", "guard": "numeric grounding", "action": "rewrote the answer",
         "detail": "number(s) not present in the result: 99"},
        {"type": "headline", "headline": prose},
        {"type": "done", "inv_id": "inv-2309", "has_receipt": True, "body": "converse"},
    ]


# ── the fold ────────────────────────────────────────────────────────────────────

def test_the_converse_answer_folds_into_headline_body_and_one_grid():
    env = fold_frames(converse_frames(), question="top categories by revenue", connection_id="8233e4fd")
    assert env.headline == "Outerwear & Coats led revenue last month at $41.2K."
    assert "Jeans and Sweaters follow" in env.body
    # The body is what FOLLOWS the sentence — a door opens with the headline and continues
    # with the body, so the body carrying the sentence again would say it twice.
    assert not env.body.startswith("Outerwear & Coats led")
    assert slack_message(env).count("led revenue last month") == 1
    # The grid is the run's own result set, positional, in column order.
    assert env.grid is not None and env.grid.columns == COLUMNS
    assert env.grid.rows[0] == ["Outerwear & Coats", 41230.5]
    assert env.chart is not None and env.chart.chart_type == "bar"
    assert env.chart.chart_config == {"exhibit": {"kind": "ranked"}}
    assert env.provenance.investigation_id == "inv-2309"
    assert env.provenance.mode == "converse"
    assert env.provenance.connection_id == "8233e4fd"
    assert env.provenance.sql == ["SELECT product_category, SUM(sale_price) AS revenue FROM t GROUP BY 1"]
    assert env.provenance.tables_used == ["order_items", "products"]
    assert env.question == "top categories by revenue"


def test_the_body_never_carries_a_table_and_the_lift_is_counted():
    env = fold_frames(converse_frames())
    body, lifted = lift_tables(env.body)
    assert lifted == [], "a table survived into the body"
    assert "|---|" not in env.body and "| Jeans |" not in env.body
    assert env.lifted_tables == 1
    # The prose around the table is kept whole.
    assert "Jeans and Sweaters follow at some distance." in env.body


def test_a_prose_table_becomes_the_grid_when_the_run_streamed_none():
    frames = [f for f in converse_frames() if f["type"] not in ("columns", "rows", "chart_type", "chart_config")]
    env = fold_frames(frames)
    assert env.grid is not None
    assert env.grid.columns == ["#", "Category", "Revenue"]
    assert env.grid.rows[1] == ["2", "Jeans", "$30,110"]
    assert env.chart is not None and env.chart.chart_type == "auto"


def test_the_quick_path_folds_headline_narrative_and_follow_ups():
    frames = [
        {"type": "headline_delta", "headline": "Revenue rose"},
        {"type": "headline_delta", "headline": "Revenue rose 4% in March."},
        {"type": "headline", "headline": "Revenue rose 4% in March."},
        {"type": "columns", "columns": ["month", "revenue"]},
        {"type": "rows", "rows": [{"month": "Feb", "revenue": 10}, {"month": "Mar", "revenue": 10.4}]},
        {"type": "receipt_id", "receipt_id": "rcpt-1"},
        {"type": "done", "inv_id": "chat-7", "has_receipt": True},
        {"type": "narrative_delta", "narrative": "March was the"},
        {"type": "narrative", "narrative": "March was the strongest month since November."},
        {"type": "followups", "questions": ["Which region drove March?", "Is April on pace?"]},
    ]
    env = fold_frames(frames)
    assert env.headline == "Revenue rose 4% in March."
    assert env.body == "March was the strongest month since November."
    assert env.follow_ups == ["Which region drove March?", "Is April on pace?"]
    assert env.provenance.investigation_id == "chat-7"
    assert env.provenance.receipt_id == "rcpt-1"
    # Dict rows become positional, in column order.
    assert env.grid is not None and env.grid.rows == [["Feb", 10], ["Mar", 10.4]]


def test_a_settled_headline_wins_over_a_later_delta():
    frames = [{"type": "headline", "headline": "Final."}, {"type": "headline_delta", "headline": "Fin"}]
    assert fold_frames(frames).headline == "Final."


def test_a_deep_report_contributes_its_caveats_and_confidence():
    frames = [
        {"type": "start", "investigation_id": "inv-deep", "connection_id": "c1", "question": "why?"},
        {"type": "answer_report", "answer_report": {
            "headline": "Refunds rose because of one carrier.",
            "executive_summary": "Carrier X's late deliveries drove 80% of the rise.",
            "confidence": "MEDIUM",
            "data_gaps": ["No carrier data before March."],
            "phases": [{"caveats": ["Returns are counted at request, not refund."],
                        "findings": [{"trust_caveat": "revenue is not the governed definition"}]}],
        }},
        {"type": "done", "body": "deep"},
    ]
    env = fold_frames(frames)
    assert env.headline == "Refunds rose because of one carrier."
    assert env.body == "Carrier X's late deliveries drove 80% of the rise."
    assert env.provenance.confidence == "MEDIUM"
    assert env.provenance.investigation_id == "inv-deep"
    assert env.caveats == ["No carrier data before March.",
                           "Returns are counted at request, not refund.",
                           "revenue is not the governed definition"]


def test_an_error_frame_is_the_envelope_error_not_a_headline():
    env = fold_frames([{"type": "error", "message": "boom · boom", "hint": "the provider timed out"}])
    assert env.error == "the provider timed out"
    assert env.headline == "" and env.has_answer


# ── lifting tables ───────────────────────────────────────────────────────────────

def test_lift_tables_handles_alignment_rows_escaped_pipes_and_missing_outer_pipes():
    text = "Before.\n| a | b |\n:---|---:\n| 1 \\| one | 2 |\nx | y\n\nAfter."
    prose, grids = lift_tables(text)
    assert prose == "Before.\n\nAfter."
    assert len(grids) == 1
    assert grids[0].columns == ["a", "b"]
    assert grids[0].rows == [["1 | one", "2"], ["x", "y"]]


def test_lift_tables_leaves_prose_with_a_pipe_alone():
    text = "We compared revenue | margin across regions.\nThen we stopped."
    prose, grids = lift_tables(text)
    assert prose == text and grids == []


def test_lift_tables_is_not_fooled_by_a_pipe_row_with_no_delimiter():
    text = "| a | b |\n| 1 | 2 |"
    prose, grids = lift_tables(text)
    assert prose == text and grids == []


def test_first_line_strips_heading_marks_and_emphasis():
    assert first_line("## **Revenue fell 3%**:\nmore") == "Revenue fell 3%"
    assert first_line("\n\n  plain sentence  \n") == "plain sentence"


# ── the two CP-0 defects: reproduced on the old shape, impossible on the envelope ──

def test_the_old_shape_said_it_twice_and_the_envelope_cannot():
    grid = Grid(columns=COLUMNS, rows=ROWS)
    # The old path: the prose the model wrote, then the transport's grid under it.
    old_message = PROSE + "\n\n" + gfm_table(grid)
    # "Swim" appears only as a row — once in the model's table, once in the grid.
    assert old_message.count("Swim") == 2, "the defect did not reproduce"

    env = fold_frames(converse_frames())
    new_message = slack_message(env)
    assert new_message.count("Swim") == 1
    assert "| Jeans | 30110.0 |" in new_message      # the grid, once, from the field
    assert "| 2 | Jeans |" not in new_message         # the prose copy is gone


def test_receipts_ride_provenance_and_slack_drops_the_field():
    env = fold_frames(converse_frames())
    assert env.provenance.guard_receipts == [{
        "guard": "numeric grounding", "action": "rewrote the answer",
        "detail": "number(s) not present in the result: 99"}]
    message = slack_message(env)
    assert "numeric grounding" not in message
    assert "rewrote the answer" not in message
    sel = select_for_slack(env)
    assert not hasattr(sel, "provenance")


def test_slack_selection_takes_headline_body_grid_once_and_two_caveats():
    env = fold_frames(converse_frames())
    env = env.model_copy(update={"caveats": ["one", "two", "three"]})
    sel = select_for_slack(env)
    assert sel.text.startswith("Outerwear & Coats led revenue")
    assert sel.table.startswith("| product_category | revenue |")
    assert sel.caveats == ["one", "two"]
    assert sel.chart is not None and sel.chart.chart_type == "bar"
    msg = slack_message(env)
    assert "⚠️ one" in msg and "⚠️ two" in msg and "three" not in msg
    assert "```\n| product_category" in msg


def test_a_one_number_result_earns_no_table():
    env = AnswerEnvelope(headline="Revenue was $1.2M.", grid=Grid(columns=["revenue"], rows=[[1.2e6]]))
    sel = select_for_slack(env)
    assert sel.table == "" and sel.grid is None and sel.chart is None
    assert slack_message(env) == "Revenue was $1.2M."


def test_a_long_grid_previews_with_a_caption_and_a_wide_one_only_captions():
    long_grid = Grid(columns=["r", "v"], rows=[[f"r{i}", i] for i in range(60)])
    md = render_grid_markdown(long_grid)
    assert md.count("\n| r") == 5 and "Showing 5 of 60 rows" in md
    wide = Grid(columns=[f"c{i}" for i in range(8)], rows=[[1] * 8, [2] * 8])
    assert render_grid_markdown(wide) == "_2 rows × 8 columns — the full result is in the report._"


def test_an_error_turn_reaches_slack_as_one_sentence():
    env = fold_frames([{"type": "error", "hint": "the provider timed out"}])
    assert slack_message(env) == "⚠️ the provider timed out"


# ── the seams: the stream ends with the envelope, the row keeps it, the doors read it ──

def _sse(frame: dict) -> str:
    import json
    return f"data: {json.dumps(frame)}\n\n"


def test_the_ask_stream_ends_with_the_envelope_and_files_it(monkeypatch):
    import asyncio
    import json

    from aughor.routers.investigations import stream_with_envelope

    filed: list[tuple[str, dict]] = []
    monkeypatch.setattr("aughor.db.history.attach_envelope",
                        lambda inv_id, env: filed.append((inv_id, env)) or True)

    async def body():
        for frame in converse_frames():
            yield _sse(frame)

    async def run():
        return [e async for e in stream_with_envelope(body(), question="q", conn_id="c1")]

    events = asyncio.run(run())
    assert len(events) == len(converse_frames()) + 1
    last = json.loads(events[-1][6:])
    assert last["type"] == "envelope"
    env = last["envelope"]
    assert env["headline"] == "Outerwear & Coats led revenue last month at $41.2K."
    assert env["grid"]["columns"] == COLUMNS and env["lifted_tables"] == 1
    assert filed == [("inv-2309", env)]


def test_a_stream_with_nothing_to_say_emits_no_envelope(monkeypatch):
    import asyncio

    from aughor.routers.investigations import stream_with_envelope

    monkeypatch.setattr("aughor.db.history.attach_envelope",
                        lambda *_a: (_ for _ in ()).throw(AssertionError("must not file")))

    async def body():
        yield _sse({"type": "route", "depth": "quick"})

    async def run():
        return [e async for e in stream_with_envelope(body(), question="q", conn_id="c1")]

    assert len(asyncio.run(run())) == 1


def test_the_envelope_round_trips_through_the_history_row():
    from aughor.db.history import attach_envelope, get_investigation, save_chat_turn

    inv_id = save_chat_turn(question="q", connection_id="conn-env", headline="h", sql="SELECT 1")
    env = fold_frames(converse_frames()).model_dump()
    assert attach_envelope(inv_id, env) is True
    stored = (get_investigation(inv_id) or {}).get("report", {}).get("envelope")
    assert stored["headline"] == env["headline"]
    assert stored["provenance"]["guard_receipts"] == env["provenance"]["guard_receipts"]


def test_a_turn_with_no_row_gets_one_from_the_envelope_under_the_receipts_own_id():
    # Measured live 2026-09-23: a converse turn that ran `run_sql` carried the 12-character id
    # its receipt minted and NO history row, so the export and the reload had nothing.
    from aughor.db.history import attach_envelope, get_investigation

    env = fold_frames(converse_frames(), question="top categories", connection_id="conn-env",
                      session_id="slack:C1:1712.9").model_dump()
    assert env["provenance"]["session_id"] == "slack:C1:1712.9"
    assert get_investigation("inv-2309") is None
    assert attach_envelope("inv-2309", env) is True
    row = get_investigation("inv-2309")
    assert row is not None and row["kind"] == "chat" and row["question"] == "top categories"
    assert row["session_id"] == "slack:C1:1712.9"
    rep = row["report"]
    assert rep["headline"] == env["headline"]
    assert rep["sql"].startswith("SELECT product_category") and rep["columns"] == COLUMNS
    assert rep["envelope"]["grid"]["rows"][0] == ["Outerwear & Coats", 41230.5]
    # An envelope with nothing to file (no connection) writes no row.
    bare = {"headline": "x", "provenance": {}}
    assert attach_envelope("inv-none", bare) is False
    assert get_investigation("inv-none") is None


def test_the_runner_publishes_the_envelope_whole(monkeypatch):
    from aughor.runners import InvestigationRequest, run_investigation

    env = fold_frames(converse_frames()).model_dump()
    monkeypatch.setattr("aughor.kernel.jobs.submit_background_tick", lambda *a, **kw: None)

    def fake_stream(req, request):
        async def _gen():
            for frame in ({"type": "start", "investigation_id": "inv-2309"},
                          {"type": "envelope", "envelope": env}):
                yield _sse(frame)
        return _gen()

    monkeypatch.setattr("aughor.routers.investigations.build_ask_stream", fake_stream)
    run = run_investigation(InvestigationRequest(question="q", connection_id="conn-x"),
                            idempotency_key="k")
    assert run.status == "executed"
    assert run.envelope["headline"] == env["headline"]
    assert run.envelope["grid"]["rows"][0] == ["Outerwear & Coats", 41230.5]


def test_the_send_reads_the_envelope_grid_and_the_chart_decision():
    from aughor.automations.engine import chart_grid
    from aughor.automations.models import Effect

    env = fold_frames(converse_frames()).model_dump()
    effect = Effect(kind="slack_post", config={"bot_id": "b1", "channel": "#c",
                                              "envelope": {"$from": "step1.envelope"}})
    grid = chart_grid(effect, {"step1": {"envelope": env, "answer": "x"}})
    assert grid["columns"] == COLUMNS
    assert grid["rows"][1] == ["Jeans", 30110.0]
    assert grid["chart_type"] == "bar"
    assert grid["chart_config"] == {"exhibit": {"kind": "ranked"}}


def test_a_bound_envelope_posts_its_slack_selection_and_the_gate_judges_that_text(monkeypatch):
    from aughor.automations import engine
    from aughor.automations.models import Effect

    env = fold_frames(converse_frames()).model_dump()
    gated: list[str] = []
    posted: list[str] = []

    class _Bot:
        bot_token, name, enabled = "xoxb", "Aughor", True

    class _Automation:
        id, name, conn_id = "auto-1", "Top sellers", ""

    monkeypatch.setattr(engine, "_gate_departure",
                        lambda effect, automation, **kw: gated.append(kw["text"]))
    monkeypatch.setattr(engine, "_attach_chart", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "_file_departure_link", lambda *a, **kw: "")
    monkeypatch.setattr("aughor.slackbots.store.get_bot_decrypted", lambda bot_id: _Bot())
    monkeypatch.setattr("aughor.slackbots.post.post_as_bot",
                        lambda token, channel, text, thread_ts=None:
                        posted.append(text) or (True, {"ts": "1.2", "channel": "C1"}))

    # The envelope is bound (already resolved by the engine); `message` is bound too and
    # would say the headline a second time, so the envelope wins.
    effect = Effect(kind="slack_post", config={"bot_id": "b1", "channel": "#c",
                                              "message": env["headline"], "envelope": env})
    outcome = engine._dispatch_slack_post(effect, _Automation())
    assert outcome.status == "executed"
    assert posted == gated == [slack_message(AnswerEnvelope.model_validate(env))]
    assert posted[0].count("Swim") == 1 and "numeric grounding" not in posted[0]

    # A send with only `message` posts exactly what it always did.
    plain = Effect(kind="slack_post", config={"bot_id": "b1", "channel": "#c", "message": "hello"})
    engine._dispatch_slack_post(plain, _Automation())
    assert posted[-1] == "hello"


def test_the_export_takes_every_field_of_the_envelope(monkeypatch):
    from aughor.export import document
    from aughor.export.document import build_export_doc

    env = fold_frames(converse_frames(), question="top categories").model_dump()
    env["caveats"] = ["revenue is not the governed definition"]
    env["follow_ups"] = ["Which category grew fastest?"]
    inv = {"id": "inv-2309", "kind": "chat", "question": "top categories", "connection_id": "c1",
           "completed_at": "2026-09-23T10:00:00", "report": {"headline": "old", "envelope": env}}
    doc = build_export_doc(inv)
    headings = [b.text for b in doc.blocks if b.kind == "heading"]
    assert headings == ["Summary", "Evidence", "Caveats", "Questions to ask next", "Query", "Checks"]
    assert doc.title == env["headline"] and doc.subtitle == "top categories"
    table = next(b for b in doc.blocks if b.kind == "table")
    assert table.columns == COLUMNS and table.rows[0][0] == "Outerwear & Coats"
    checks = [b for b in doc.blocks if b.kind == "bullets"][-1]
    assert checks.items == ["numeric grounding — rewrote the answer — number(s) not present in the result: 99"]
    code = next(b for b in doc.blocks if b.kind == "code")
    assert code.text.startswith("SELECT product_category")

    # A deep report keeps its richer builder even when it carries an envelope.
    monkeypatch.setattr(document, "_build_ada", lambda inv, money_symbol="": "deep-builder")
    deep = {"id": "d", "kind": "investigation", "question": "why?",
            "report": {"phases": [], "headline": "h", "envelope": env}}
    assert build_export_doc(deep) == "deep-builder"


def test_the_converse_prompt_records_receipts_instead_of_narrating_them():
    from aughor.agent.converse_tools import converse_system_prompt

    prompt = converse_system_prompt("conn-x")
    assert "never report that none fired" in prompt
    assert "Do not write markdown tables" in prompt
    assert "say so in your answer" not in prompt
