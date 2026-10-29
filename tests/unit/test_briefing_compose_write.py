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


def test_a_question_asked_from_an_edition_reads_what_is_on_screen(setup, monkeypatch):
    from aughor.knowledge import brief_context as BC

    entry = _composed(setup, monkeypatch)
    key = f"{_week().key}@_organisation"
    assert BC.PERIOD_KEY.match(key) and BC.PERIOD_KEY.match(f"{_week().key}@digital-and-growth")
    block = BC.build_brief_block(entry)
    assert "ON SCREEN, IN ORDER:" in block and "Where it came from" in block
    assert "Sales rose to €42.1k" in block and "{" not in block.split("ON SCREEN")[1].split("WHAT IT READS")[0]
    assert "sales_by_is_top: Sales by is top (drill" not in block and "sales_by_is_top" in block
