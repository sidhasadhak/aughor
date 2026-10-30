"""Arc BC-3 (ROADMAP §3.67) — investigate, then compose; code checks every block before it is kept.

The model is replaced by a scripted tool loop: it breaks a check down, writes a SELECT, composes a page that is
refused (an unknown block type) and then one that passes. Code adds a floor figure the page left out, keeps the
edition per reader, and — when the model never composes — draws an edition from what was measured and says so.
"""
from __future__ import annotations

import contextlib
from datetime import date

import duckdb
import pytest

from aughor.agent.tool_loop import LoopResult
from aughor.briefing import guide as G
from aughor.briefing import ranges
from aughor.briefing.compose import write as W

OCT29 = date(2026, 10, 29)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""CREATE TABLE orders AS
        WITH days AS (SELECT d::DATE AS d FROM range(DATE '2026-06-01', DATE '2026-10-29', INTERVAL 1 DAY) t(d))
        SELECT d AS order_date, 'A' AS platform, i < 8 AS is_top,
               CASE WHEN d BETWEEN DATE '2026-10-19' AND DATE '2026-10-25' AND i < 8 THEN 400.0
                    ELSE 100.0 + (EXTRACT(week FROM d) % 3) * 4 END AS gmv
        FROM days, range(30) k(i)
        UNION ALL SELECT d, 'B', false, 50.0 + (EXTRACT(week FROM d) % 2) * 2 FROM days, range(10) k(i)""")
    yield c
    c.close()


def _run(con):
    def run(sql):
        try:
            cur = con.execute(sql)
            return [d[0] for d in cur.description], cur.fetchall(), None
        except Exception as exc:  # noqa: BLE001
            return [], [], str(exc)
    return run


def _week():
    spec, _ = ranges.resolve_range("last_week", today=OCT29, lag_days=1, lag_source="learned")
    return spec


SALES = G.Check(id="sales", label="Sales", sql="SUM(gmv)", tables=["orders"], time_column="orders.order_date",
                unit="EUR", better="up")
AOV = G.Check(id="aov", label="Average order", sql="AVG(gmv)", tables=["orders"], time_column="orders.order_date",
              unit="EUR", better="up")


def _top_orders(conn_id, args, **kw):
    return {"columns": ["platform", "value"], "rows": [("A", 400.0), ("A", 400.0)], "guard_receipts": [],
            "caveats": [], "truncated": False}


@pytest.fixture
def setup(con, monkeypatch, tmp_path):
    import aughor.knowledge.briefing as kb
    monkeypatch.setattr(kb, "_CACHE_PATH", tmp_path / "briefing_cache.json")
    monkeypatch.setattr(ranges, "governed_metrics", lambda *a, **k: [])
    monkeypatch.setattr("aughor.orgsettings.figure_currency", lambda *a, **k: "EUR")
    monkeypatch.setattr("aughor.business_profile.infer.gather_context", lambda c, s: ("TABLE: orders  (1 rows)", []))
    monkeypatch.setattr(W, "breakdown_columns", lambda conn_id, table: ["platform", "is_top"])
    G.save("compose_c1", None, G.BriefingGuide(business="A shop.", checks=[SALES, AOV]), by="user:amit", publish=True)
    return {"runner": lambda: contextlib.nullcontext((_run(con), "duckdb"))}


def _loop(script):
    """A tool loop that plays ``script`` — a list of (tool, arguments) — and records each tool's answer."""
    seen = []

    def loop(provider, system, question, tools, **kw):
        by = {t.name: t for t in tools}
        seen.append({"system": system, "question": question})
        for name, args in script:
            out = by[name].run(args)
            seen.append({name: out})
            if isinstance(out, dict) and out.get("concluded"):
                return LoopResult(answer=None, stop_reason="concluded", conclusion=out)
        return LoopResult(answer=None, stop_reason="budget")
    return loop, seen


LEAD = {"type": "lead", "text": "Sales rose to {€42.1k|sales}: top clients spent far more than usual."}


def test_the_model_investigates_then_composes_and_code_checks_it(setup, monkeypatch):
    from aughor.knowledge.briefing import peek_entry

    good = [LEAD, {"type": "bridge", "source": "sales_by_is_top", "title": "Where the week's sales came from"},
            {"type": "table", "source": "top_orders", "title": "The largest orders"},
            {"type": "figure", "source": "aov"}]
    loop, seen = _loop([("breakdown", {"check_id": "sales", "column": "is_top"}),
                        ("query", {"id": "top_orders", "label": "The largest orders", "sql": "SELECT 1",
                                   "purpose": "the week's largest orders"}),
                        ("compose", {"blocks": [LEAD, {"type": "pie", "source": "sales"}]}),
                        ("compose", {"blocks": good})])
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    entry = W.compose("compose_c1", _week(), scope_key="compose_c1", reader_id="", llm=object(), runner=setup["runner"],
                      run_query=_top_orders)

    breakdown = seen[1]["breakdown"]
    assert breakdown["columns"][0] == "segment" and breakdown["rows"][0][0] is True     # the top clients first
    assert seen[2]["query"]["rows"] == [["A", 400.0], ["A", 400.0]]
    assert "no block type 'pie'" in " ".join(seen[3]["compose"]["refused"])           # refused back, in words
    assert [b["type"] for b in entry["blocks"]] == ["lead", "bridge", "table", "figure"]
    assert {"sales_by_is_top", "top_orders", "sales", "aov"} <= set(entry["sources"])
    assert entry["model_steps"] == 4 and entry["queries"] == 1 and entry["stop_reason"] == "concluded"
    assert entry["drill_columns"]["sales"] == ["platform", "is_top"]
    assert entry["guide"]["state"] == "published" and entry["version"]["kept"] is True
    assert peek_entry(f"compose_c1#{_week().key}@_organisation")["composed"] is True           # kept per reader
    assert "the 8 weeks before" in seen[0]["question"] or "usual" in seen[0]["question"]


def test_a_floor_figure_the_page_left_out_is_added_by_code(setup, monkeypatch):
    loop, _ = _loop([("compose", {"blocks": [LEAD]})])
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    entry = W.compose("compose_c1", _week(), scope_key="compose_c1", llm=object(), runner=setup["runner"], run_query=_top_orders)
    added = [b for b in entry["blocks"] if b["by_code"]]
    assert set(entry["floor"]) == {"sales", "aov"}
    assert [b["source"] for b in added] == ["aov"]                 # sales is cited in the lead; aov was left out
    assert all(b["type"] == "figure" for b in added)


def test_a_model_that_does_not_finish_leaves_an_edition_drawn_by_code_that_says_so(setup, monkeypatch):
    loop, _ = _loop([("breakdown", {"check_id": "sales", "column": "platform"})])
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    entry = W.compose("compose_c1", _week(), scope_key="compose_c1", llm=object(), runner=setup["runner"], run_query=_top_orders)
    assert "did not finish" in entry["drawn_by_code"] and entry["stop_reason"] == "budget"
    assert entry["blocks"] and all(b["type"] == "figure" and b["by_code"] for b in entry["blocks"])


def test_the_queries_an_edition_may_run_are_limited(setup, monkeypatch):
    script = [("query", {"id": f"q{i}", "label": "Q", "sql": "SELECT 1", "purpose": "p"}) for i in range(9)]
    loop, seen = _loop(script)
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    entry = W.compose("compose_c1", _week(), scope_key="compose_c1", llm=object(), runner=setup["runner"], run_query=_top_orders)
    assert "spent" in seen[-1]["query"]["error"] and entry["queries"] == W.MAX_QUERIES


def test_no_guide_no_edition():
    with pytest.raises(LookupError):
        W.compose("nobody", _week(), scope_key="nobody")


def test_an_edition_departs_as_its_blocks_words():
    lines = W.sheet_lines({"blocks": [{"type": "lead", "text": "Sales rose to {€19.6k|sales}."},
                                      {"type": "table", "title": "The largest orders"}, {"type": "control"}]})
    assert lines == [("narrative", ["Sales rose to €19.6k.", "The largest orders"])]


# ── BC-4 · drills and questions ──────────────────────────────────────────────────────────────

def _composed(setup, monkeypatch):
    blocks = [LEAD, {"id": "where", "type": "bridge", "source": "sales_by_is_top", "title": "Where it came from"},
              {"type": "table", "source": "top_orders"}]
    loop, _ = _loop([("breakdown", {"check_id": "sales", "column": "is_top"}),
                     ("query", {"id": "top_orders", "label": "Largest orders", "sql": "SELECT 1", "purpose": "p"}),
                     ("compose", {"blocks": blocks})])
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    return W.compose("compose_c1", _week(), scope_key="compose_c1", llm=object(), runner=setup["runner"],
                     run_query=_top_orders)


def test_a_drill_goes_one_level_deeper_within_the_segment_and_is_written_under_its_block(setup, monkeypatch):
    from aughor.knowledge.briefing import peek_entry

    _composed(setup, monkeypatch)
    out = W.drill("compose_c1", _week(), scope_key="compose_c1", source_id="sales_by_is_top", segment=True,
                  column="platform", after="where", runner=setup["runner"])
    assert [r[0] for r in out["source"]["rows"]] == ["A"]          # within the top clients: only storefront A
    assert out["source"]["facts"]["within"] == {"is_top": True} and out["source"]["kind"] == "drill"
    assert out["block"]["type"] == "compare" and out["block"]["by_code"] is True
    kept = peek_entry(f"compose_c1#{_week().key}@_organisation")
    assert [b["id"] for b in kept["blocks"]][:3] == ["lead_1", "where", out["block"]["id"]]   # under its block
    assert out["source"]["id"] in kept["sources"]


def test_a_check_drills_by_any_column_and_a_written_query_cannot_be_drilled(setup, monkeypatch):
    import pytest as _pt
    _composed(setup, monkeypatch)
    out = W.drill("compose_c1", _week(), scope_key="compose_c1", source_id="sales", column="platform",
                  runner=setup["runner"])
    assert {r[0] for r in out["source"]["rows"]} == {"A", "B"}
    with _pt.raises(ValueError, match="written query"):
        W.drill("compose_c1", _week(), scope_key="compose_c1", source_id="top_orders", column="platform",
                runner=setup["runner"])
    with _pt.raises(LookupError):
        W.drill("compose_c1", _week(), scope_key="compose_c1", source_id="nope", column="platform",
                runner=setup["runner"])
    with _pt.raises(ValueError, match="drilled by platform, is_top"):
        W.drill("compose_c1", _week(), scope_key="compose_c1", source_id="sales", column="gmv",
                runner=setup["runner"])


def test_a_question_asked_from_an_edition_reads_what_is_on_screen(setup, monkeypatch):
    from aughor.knowledge import brief_context as BC

    entry = _composed(setup, monkeypatch)
    key = f"{_week().key}@_organisation"
    assert BC.PERIOD_KEY.match(key) and BC.PERIOD_KEY.match(f"{_week().key}@digital-and-growth")
    block = BC.build_brief_block(entry)
    assert "ON SCREEN, IN ORDER:" in block and "Where it came from" in block
    assert "Sales rose to €42.1k" in block and "{" not in block.split("ON SCREEN")[1].split("WHAT IT READS")[0]
    assert "sales_by_is_top: Sales by is top (drill" not in block and "sales_by_is_top" in block


# ── BC-6 · a send is judged against its sources re-run ───────────────────────────────────────

def test_a_send_measures_a_written_querys_numbers_again_at_departure(con, setup):
    sql = ("SELECT platform, SUM(gmv) AS sales FROM orders WHERE order_date >= DATE '2026-10-19' "
           "AND order_date < DATE '2026-10-26' GROUP BY 1 ORDER BY 1")
    first = con.execute(sql).fetchall()
    entry = {"period": {"label": "Weekly", "measured": [], "last_day": "2026-10-25"},
             "sources": {"by_store": {"id": "by_store", "label": "Sales by storefront", "kind": "query",
                                      "columns": ["platform", "sales"], "rows": [[r[0], float(r[1])] for r in first], "sql": sql}}}
    before = W.departure_measurement("compose_c1", entry, runner=setup["runner"])
    a_sales = float(dict(first)["A"])
    assert any(abs(v - a_sales) < 0.01 for v in before.values)            # measured at the send
    con.execute("INSERT INTO orders VALUES (DATE '2026-10-20', 'A', false, 9999.0)")   # late rows land
    after = W.departure_measurement("compose_c1", entry, runner=setup["runner"])
    assert not any(abs(v - a_sales) < 0.01 for v in after.values)         # the old figure no longer stands
    assert any(abs(v - (a_sales + 9999.0)) < 0.01 for v in after.values)


def test_a_send_measures_a_breakdowns_change_against_usual_again_at_departure(con, setup):
    from aughor.briefing import edition as E
    from aughor.briefing.compose import sources as S

    m, _ = E.measurable(SALES, {})
    src = S.breakdown("sales_by_is_top", "Sales by top client", m, "is_top", _week(), usual_n=8,
                      run_sql=_run(con), dialect="duckdb", unit="EUR", check_id="sales")
    top = next(r for r in src.rows if r[0] is True)
    change = top[3]
    entry = {"period": {"label": "Weekly", "measured": [], "last_day": "2026-10-25"},
             "sources": {src.id: src.model_dump(mode="json")}}
    before = W.departure_measurement("compose_c1", entry, runner=setup["runner"])
    assert any(abs(v - change) < 0.01 for v in before.values)             # "€X above its usual" departs
    con.execute("INSERT INTO orders VALUES (DATE '2026-10-21', 'A', true, 5000.0)")   # late rows land
    after = W.departure_measurement("compose_c1", entry, runner=setup["runner"])
    assert not any(abs(v - change) < 0.01 for v in after.values)          # the old change no longer stands
    assert any(abs(v - (change + 5000.0)) < 0.01 for v in after.values)   # the change measured now does


def test_a_read_finds_the_composed_edition_and_never_an_older_one(setup, monkeypatch):
    from aughor.knowledge.briefing import keep_entry
    from aughor.routers import exploration as R

    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: (_week(), ""))
    monkeypatch.setattr("aughor.routers._shared.canonical_schema", lambda conn, schema: schema)
    monkeypatch.setattr(R, "briefing_off_for", lambda *a, **k: None)
    block = ranges.range_block(_week())
    keep_entry(f"compose_c1#{_week().key}@_organisation", {"edition": True, "headline": "old", "period": block})
    assert R.read_briefing_edition("compose_c1", preset="last_week", reader="")["built"] is False   # Arc BG's shape
    _composed(setup, monkeypatch)
    got = R.read_briefing_edition("compose_c1", preset="last_week", reader="")
    assert got["built"] is True and got["blocks"][0]["type"] == "lead" and "lag_now" not in got


def test_an_edition_is_still_read_when_only_the_learned_lag_has_moved_and_the_move_is_said(setup, monkeypatch):
    from aughor.routers import exploration as R

    monkeypatch.setattr("aughor.routers._shared.canonical_schema", lambda conn, schema: schema)
    monkeypatch.setattr(R, "briefing_off_for", lambda *a, **k: None)
    written = _week()                                                              # lag 1 when it was written
    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: (written, ""))
    _composed(setup, monkeypatch)
    later, _ = ranges.resolve_range("last_week", today=OCT29, lag_days=2, lag_source="learned")
    assert later.key == written.key and later.lag_days != written.lag_days          # the same week, the lag moved
    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: (later, ""))
    got = R.read_briefing_edition("compose_c1", preset="last_week", reader="")
    assert got["built"] is True and got["blocks"][0]["type"] == "lead"            # still the week's edition
    assert got["lag_now"] == 2 and got["period"]["lag_days"] == 1                  # the move said, the figures as written


def test_a_whole_statement_check_is_offered_no_column_to_break_it_down_by(setup, monkeypatch):
    stmt = G.Check(id="net", label="Net sales", sql="SELECT SUM(gmv) FROM orders", tables=["orders"],
                   time_column="orders.order_date", unit="EUR")
    G.save("compose_c1", None, G.BriefingGuide(business="A shop.", checks=[SALES, AOV, stmt]), by="user:amit",
           publish=True)
    loop, seen = _loop([("compose", {"blocks": [LEAD]})])
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    entry = W.compose("compose_c1", _week(), scope_key="compose_c1", llm=object(), runner=setup["runner"],
                      run_query=_top_orders)
    assert entry["drill_columns"]["net"] == [] and entry["drill_columns"]["sales"] == ["platform", "is_top"]


# ── a decision, given to a team ──────────────────────────────────────────────────────────────

class _Group:
    def __init__(self, gid, name, channel=""):
        self.id, self.name, self.channel_trigger_id = gid, name, channel


def _with_decision(setup, monkeypatch):
    blocks = [LEAD, {"id": "ask", "type": "decision", "text": "Hold the {€42.1k|sales} as provisional?"}]
    loop, _ = _loop([("compose", {"blocks": blocks})])
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    return W.compose("compose_c1", _week(), scope_key="compose_c1", llm=object(), runner=setup["runner"],
                     run_query=_top_orders)


def test_every_decision_offers_deep_analysis_a_team_and_not_now(setup, monkeypatch):
    entry = _with_decision(setup, monkeypatch)
    assert next(b for b in entry["blocks"] if b["type"] == "decision")["actions"] == [
        "deep_analysis", "give_to_team", "not_now"]


def test_a_team_with_no_channel_is_not_reached_and_the_edition_says_so(setup, monkeypatch):
    from aughor.knowledge.briefing import peek_entry

    _with_decision(setup, monkeypatch)
    monkeypatch.setattr("aughor.rbac.groups.get_group", lambda org, gid: _Group(gid, "Finance"))
    fired = []
    monkeypatch.setattr("aughor.notifications.executor.fire_action", lambda *a, **k: fired.append(a))
    out = W.give("compose_c1", _week(), scope_key="compose_c1", block_id="ask", group_id="finance",
                 by="user:amit", runner=setup["runner"])
    assert out["status"] == "not_sent" and "Finance has no channel bound" in out["note"] and not fired
    kept = peek_entry(f"compose_c1#{_week().key}@_organisation")
    assert kept["given"] == [out] and out["by"] == "user:amit"                    # written into the edition


def test_a_decision_given_to_a_team_departs_through_the_gate_once(setup, monkeypatch):
    from types import SimpleNamespace

    _with_decision(setup, monkeypatch)
    monkeypatch.setattr("aughor.rbac.groups.get_group", lambda org, gid: _Group(gid, "Finance", "trg_fin"))
    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: SimpleNamespace(id=tid))
    gated, fired = [], []

    def gate(**kw):
        gated.append(kw)
        return SimpleNamespace(held=False, record_id="dep_1", receipt={}, receipt_line=lambda: "receipt",
                               reason_sentence=lambda: "")
    monkeypatch.setattr("aughor.govern.departure.gate_departure", gate)
    monkeypatch.setattr("aughor.notifications.executor.fire_action",
                        lambda trigger, payload: fired.append(payload) or SimpleNamespace(status="ok", error=None))
    out = W.give("compose_c1", _week(), scope_key="compose_c1", block_id="ask", group_id="finance",
                 by="user:amit", runner=setup["runner"])
    assert out["status"] == "sent" and out["departure_id"] == "dep_1"
    assert gated[0]["text"] == "Hold the €42.1k as provisional?" and gated[0]["origin"] == "person"
    assert any(abs(v - 42100) < 100 for v in gated[0]["measurement"].values)     # judged on the re-run sources
    assert "Given to Finance by user:amit" in fired[0].recommendation
    again = W.give("compose_c1", _week(), scope_key="compose_c1", block_id="ask", group_id="finance",
                   by="user:amit", runner=setup["runner"])
    assert again == out and len(fired) == 1                                      # given once per group


def test_a_held_decision_is_not_posted_and_says_why(setup, monkeypatch):
    from types import SimpleNamespace

    _with_decision(setup, monkeypatch)
    monkeypatch.setattr("aughor.rbac.groups.get_group", lambda org, gid: _Group(gid, "Finance", "trg_fin"))
    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: SimpleNamespace(id=tid))
    monkeypatch.setattr("aughor.govern.departure.gate_departure", lambda **kw: SimpleNamespace(
        held=True, record_id="dep_2", reason_sentence=lambda: "€42.1k was not measured at the send"))
    fired = []
    monkeypatch.setattr("aughor.notifications.executor.fire_action", lambda *a, **k: fired.append(a))
    out = W.give("compose_c1", _week(), scope_key="compose_c1", block_id="ask", group_id="finance",
                 by="user:amit", runner=setup["runner"])
    assert out["status"] == "held" and "not measured" in out["note"] and not fired
    with pytest.raises(LookupError, match="no decision"):
        W.give("compose_c1", _week(), scope_key="compose_c1", block_id="lead_1", group_id="finance", by="user:amit")


# ── an edition inside a Data Canvas ──────────────────────────────────────────────────────────

def test_a_canvas_edition_reads_only_the_canvas_tables(setup, monkeypatch):
    refunds = G.Check(id="refunds", label="Refunds", sql="SUM(refund)", tables=["returns"],
                      time_column="returns.return_date", unit="EUR")
    G.save("compose_cv", None, G.BriefingGuide(business="A shop.", checks=[SALES, refunds]), by="user:amit",
           publish=True)
    monkeypatch.setattr("aughor.business_profile.infer.gather_context", lambda c, s: (
        "TABLE: orders  (1 rows)\n  gmv DOUBLE\n\nTABLE: returns  (1 rows)\n  refund DOUBLE\n", []))
    asked = {}

    def run_query(conn_id, args, **kw):
        asked.update(kw)
        return _top_orders(conn_id, args)
    loop, seen = _loop([("query", {"id": "q", "label": "Q", "sql": "SELECT 1", "purpose": "p"}),
                        ("compose", {"blocks": [LEAD]})])
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    entry = W.compose("compose_cv", _week(), scope_key="canvas:cv1", canvas_id="cv1", tables=("orders",),
                      llm=object(), runner=setup["runner"], run_query=run_query)
    assert entry["canvas"] == {"id": "cv1", "tables": ["orders"], "checks_outside": ["Refunds"]}
    assert [f["id"] for f in entry["period"]["measured"]] == ["sales"]           # the canvas's check only
    schema_seen = seen[0]["question"].split("SCHEMA (for query):")[1]
    assert "TABLE: orders" in schema_seen and "returns" not in schema_seen       # shown the canvas's tables
    assert asked["canvas_id"] == "cv1"                                           # queries run in its scope


def _canvas(monkeypatch, cid: str, conn: str, tables: list[str]):
    from aughor.canvas.models import Canvas, CanvasScope
    canvas = Canvas(id=cid, name=cid, scopes=[CanvasScope(connection_id=conn, tables=tables)])
    monkeypatch.setattr("aughor.canvas.store.get_canvas", lambda c: canvas if c == cid else None)


def test_a_canvas_on_every_table_reads_the_datasets_own_edition(setup, monkeypatch):
    from aughor.routers import exploration as R

    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: (_week(), ""))
    monkeypatch.setattr("aughor.routers._shared.canonical_schema", lambda conn, schema: schema)
    monkeypatch.setattr(R, "briefing_off_for", lambda *a, **k: None)
    _canvas(monkeypatch, "cv_all", "compose_c1", [])
    _composed(setup, monkeypatch)                                                   # the dataset's edition
    got = R.read_briefing_edition("compose_c1", preset="last_week", reader="", canvas_id="cv_all")
    assert got["built"] is True and got["scope_key"] == "compose_c1"                # written once, read here too
    assert got["canvas"] == {"id": "cv_all", "own": False, "dataset": "", "tables": [], "checks_inside": [],
                             "checks_outside": []}


def test_a_canvas_that_names_tables_has_its_own_edition_and_says_what_it_leaves_out(setup, monkeypatch):
    from fastapi import HTTPException

    from aughor.routers import exploration as R

    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: (_week(), ""))
    monkeypatch.setattr("aughor.routers._shared.canonical_schema", lambda conn, schema: schema)
    monkeypatch.setattr(R, "briefing_off_for", lambda *a, **k: None)
    refunds = G.Check(id="refunds", label="Refunds", sql="SUM(refund)", tables=["returns"],
                      time_column="returns.return_date")
    G.save("compose_cv2", None, G.BriefingGuide(business="A shop.", checks=[SALES, refunds]), by="user:amit",
           publish=True)
    _canvas(monkeypatch, "cv_named", "compose_cv2", ["orders"])
    got = R.read_briefing_edition("compose_cv2", preset="last_week", reader="", canvas_id="cv_named")
    assert got["built"] is False and got["scope_key"] == "canvas:cv_named"          # kept apart, not written yet
    assert got["canvas"]["own"] is True and got["canvas"]["tables"] == ["orders"]
    assert got["canvas"]["checks_inside"] == ["Sales"] and got["canvas"]["checks_outside"] == ["Refunds"]
    with pytest.raises(HTTPException) as refused:
        R.read_briefing_edition("compose_c1", preset="last_week", reader="", canvas_id="cv_named")
    assert refused.value.status_code == 422                                         # another connection's canvas


def test_a_canvas_that_names_no_schema_reads_its_connections_default_dataset(setup, monkeypatch):
    from aughor.routers import exploration as R

    monkeypatch.setattr(ranges, "resolve_for", lambda *a, **k: (_week(), ""))
    monkeypatch.setattr("aughor.routers._shared.canonical_schema", lambda conn, schema: schema)
    monkeypatch.setattr(R, "briefing_off_for", lambda *a, **k: None)
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn: {"schema_name": "lux"})
    _canvas(monkeypatch, "cv_lux", "compose_c1", [])
    got = R.read_briefing_edition("compose_c1", preset="last_week", reader="", canvas_id="cv_lux")
    assert got["scope_key"] == "compose_c1:lux" and got["canvas"]["dataset"] == "lux"


# ── what the platform already knows, read and cited; one deep analysis started ──────────────

def _known_stub(conn_id, schema, spec, tables):
    from aughor.briefing.compose import sources as S
    return S.known_analyses("compose_c1", list_runs=lambda: [
        {"id": "a1", "connection_id": "compose_c1", "kind": "investigation", "status": "complete",
         "completed_at": "2026-10-28", "question": "Why did sales rise?", "headline": "Top clients carried €9,417 more"}],
        get_run=lambda i: {"report": {"headline": "Top clients carried €9,417 more", "confidence": "HIGH",
                                      "causal_checks": {"licence": "descriptive"}}})


class _Run:
    def __init__(self, status="executed", message=""):
        self.status, self.message = status, message


def test_the_writer_reads_what_the_platform_knows_and_starts_one_deep_analysis(setup, monkeypatch):
    asked = []
    blocks = [{"type": "lead", "text": "Sales rose to {€42.1k|sales}; {top clients carried €9,417 more|analysis_a1}."},
              {"type": "context", "source": "analysis_a1"}, {"type": "context", "source": "analysis_started"}]
    loop, seen = _loop([("deep_analysis", {"question": "Why did average order value rise in the week of 19 October?"}),
                        ("deep_analysis", {"question": "And why did refunds fall in the same week, by reason?"}),
                        ("compose", {"blocks": blocks})])
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    entry = W.compose("compose_c1", _week(), scope_key="compose_c1", llm=object(), runner=setup["runner"],
                      run_query=_top_orders, known=_known_stub,
                      start_analysis=lambda q, s: asked.append((q, s)) or _Run())
    payload = seen[0]["question"]
    assert '"deep_analyses"' in payload and "Top clients carried" in payload        # shown to the model
    assert seen[1]["deep_analysis"]["started"] is True
    assert "already" in seen[2]["deep_analysis"]["error"]                           # one per edition
    assert len(asked) == 1 and asked[0][1] == f"briefing:compose_c1#{_week().key}@_organisation"
    assert [b["type"] for b in entry["blocks"]][:3] == ["lead", "context", "context"]   # then the floor, by code
    assert entry["sources"]["analysis_started"]["status"] == "running"
    assert entry["known"] == {"analyses": 2, "findings": 0, "decisions": 0, "started": "analysis_started"}


def test_a_scheduled_send_starts_no_deep_analysis_unless_the_organisation_allows_it(setup, monkeypatch):
    asked = []
    loop, seen = _loop([("deep_analysis", {"question": "Why did average order value rise in the week of 19 October?"}),
                        ("compose", {"blocks": [LEAD]})])
    monkeypatch.setattr("aughor.agent.tool_loop.run_tool_loop", loop)
    W.compose("compose_c1", _week(), scope_key="compose_c1", llm=object(), runner=setup["runner"],
              run_query=_top_orders, known=lambda *a: [], may_start_analysis=False,
              start_analysis=lambda q, s: asked.append(q) or _Run())
    assert "has not allowed" in seen[1]["deep_analysis"]["error"] and asked == []


def test_a_read_shows_a_started_deep_analysis_as_it_stands(setup, monkeypatch):
    from aughor.briefing.compose import sources as S

    entry = {"sources": {"analysis_started": S.started_analysis("analysis_started", "Why?", "briefing:k").model_dump()}}
    monkeypatch.setattr(S, "refreshed", lambda src, **kw: src.model_copy(update={"status": "final"}))
    assert W.as_it_stands(entry)["sources"]["analysis_started"]["status"] == "final"
    assert entry["sources"]["analysis_started"]["status"] == "running"             # a read keeps nothing
