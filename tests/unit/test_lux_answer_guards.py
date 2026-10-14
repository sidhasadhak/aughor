"""What the Lux answer of 2026-10-14 (99201af8) exposed, and the guards that channel it.

The reader saw, under the answer: "I did not test new versus returning customers, promotions or
events, or the weak August itself. I could not run the category and brand cut myself because the
query errored. I rely on the phase tool's summaries for those splits." Read back from the trace:
the schema linker had kept `order_items` and dropped `orders`, the table that carries the date;
the intake wrote "orders.order_ts is an assumption: the orders columns are not listed"; the date
resolver had no `orders` block to correct it against; the phase planners wrote the column and the
SQL fixer repaired it nine times; the analyst's own cut failed twice on it ("column o.order_ts
does not exist" with Postgres's hint to try `o.order_id`), listed the whole schema (81k chars),
wrote it again, and concluded in the first person about its tools. Its two `decompose` runs also
carried the same finding ids, so the page keyed two children `decomp_2`.

Hermetic: no model, no warehouse."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

import aughor.agent.investigate as I
from aughor.agent.analyst import AnalystTurn, _phase_payload, _unique_phase_ids, conclude
from aughor.sql.writer import diagnose_sql_error
from aughor.tools.schema_linker import complete_join_paths

FULL = """TABLE: brands  (120 rows)
  brand_id  text
  brand_name  text
  tier  text

TABLE: order_items  (9,000 rows)
  order_item_id  text
  order_id  text
  platform  text
  brand  text
  category  text
  quantity  integer
  unit_price_eur  numeric
  cost_eur  numeric

TABLE: orders  (3,000 rows)
  order_id  text
  platform  text
  customer_id  text
  order_date  date
  gmv_eur  numeric
  status  text

TABLE: web_sessions  (50,000 rows)
  session_id  text
  started_at  timestamp
  device  text

JOIN PATHS:
  order_items.order_id -> orders.order_id
"""
LINKED = """TABLE: order_items  (9,000 rows)
  order_item_id  text
  order_id  text
  platform  text
  brand  text
  category  text
  quantity  integer
  unit_price_eur  numeric
  cost_eur  numeric

JOIN PATHS:
  order_items.order_id -> orders.order_id
"""
Q = "Why did revenue change in September 2026 against August 2026?"


# ── the schema the intake reads carries the table its date is on ───────────────────────

def test_the_linked_schema_is_completed_with_the_dated_parent_before_its_join_hints():
    out, tables = complete_join_paths(Q, LINKED, FULL, cap=10)
    assert "orders" in tables and "order_items" in tables
    assert "TABLE: orders" in out and "order_date  date" in out
    assert out.index("TABLE: orders") < out.index("JOIN PATHS:")        # before the trailing sections
    assert out.index("TABLE: order_items") < out.index("TABLE: orders")  # the linked tables stay first
    assert "web_sessions" not in out                                     # not a neighbour, not pulled in
    assert out.count("TABLE: order_items") == 1


def test_a_linked_schema_that_already_holds_its_neighbours_comes_back_unchanged():
    whole = FULL.replace("TABLE: web_sessions  (50,000 rows)\n  session_id  text\n  started_at  timestamp\n  device  text\n\n", "")
    out, _tables = complete_join_paths(Q, whole, FULL, cap=10)
    assert out == whole
    assert complete_join_paths(Q, "", FULL, cap=10) == ("", [])


def test_the_date_resolver_corrects_the_invented_column_against_the_completed_schema():
    before = I._resolve_date_column("orders.order_ts", "order_items", LINKED, ["order_items.platform"])
    assert before == ("orders.order_ts", False)                           # blind: no `orders` block to read
    completed, _ = complete_join_paths(Q, LINKED, FULL, cap=10)
    assert I._resolve_date_column("orders.order_ts", "order_items", completed, ["order_items.platform"]) == ("orders.order_date", True)
    assert I._resolve_date_column("orders.order_ts", "order_items", FULL, ["order_items.platform"]) == ("orders.order_date", True)


class _Intake:
    def __init__(self, date_column: str):
        self.date_column = date_column

    def complete(self, **kw):
        from aughor.agent.prompts_investigate import IntakeOutput
        return IntakeOutput(metric_label="revenue", metric_sql="SUM(unit_price_eur * quantity)", observation_start="2026-09-01",
                            observation_end="2026-09-30", observation_label="September 2026", comparison_start="2026-08-01",
                            comparison_end="2026-08-31", comparison_label="August 2026", date_column=self.date_column,
                            metric_table="order_items", dimensions=["order_items.platform"], intake_notes="", cross_sectional=False)


@pytest.fixture
def hermetic_intake(monkeypatch):
    import aughor.agent.explore as ex
    import aughor.agent.framing as AF
    import aughor.llm.profile as P
    import aughor.semantic.data_understanding as du
    monkeypatch.setattr(ex, "build_analysis_ledger", lambda state: "")
    monkeypatch.setattr(du, "build_data_understanding", lambda *a, **k: NS(grounding_block=lambda: "", trusted_used=[]))
    monkeypatch.setattr(I, "_measure_date_span", lambda *a, **k: ("", ""))
    monkeypatch.setattr(AF, "frame_from_state", lambda state, dialect="duckdb", provider=None: None)
    monkeypatch.setattr(P, "profile_for", lambda role: NS(capable=True))


def _spec_row(state: dict, field: str) -> str:
    phase = [p for p in state["investigation_phases"] if p["phase_id"] == "intake"][0]
    return dict(phase["findings"][0]["rows"])[field]


def test_the_intake_reads_the_full_catalogue_when_the_excerpt_lacks_the_dated_table(hermetic_intake, monkeypatch):
    monkeypatch.setattr(I, "_provider", lambda role: _Intake("orders.order_ts"))
    state = {"question": Q, "schema_context": LINKED, "full_schema_context": FULL, "scan_context": "",
             "connection_id": "", "scope_schema": ""}
    out = I.ada_intake(state, conn=object())
    assert _spec_row(out, "Date column") == "orders.order_date"
    # without the catalogue the excerpt is all the resolver has — the invented column passed (99201af8)
    monkeypatch.setattr(I, "_provider", lambda role: _Intake("orders.order_ts"))
    blind = I.ada_intake({**state, "full_schema_context": ""}, conn=object())
    assert _spec_row(blind, "Date column") == "orders.order_ts"


# ── a failed statement comes back with the table's real columns ───────────────────────

SQL = ("select oi.platform, sum(case when o.order_ts >= '2026-09-01' then oi.unit_price_eur * oi.quantity end) sep "
       "from order_items oi join orders o on o.order_id = oi.order_id where o.order_ts >= '2026-08-01' group by 1")
COLS = {"orders": ["order_id", "platform", "customer_id", "order_date", "gmv_eur", "status"],
        "order_items": ["order_item_id", "order_id", "platform", "brand", "category", "quantity", "unit_price_eur", "cost_eur"]}


@pytest.mark.parametrize("error", [
    'column o.order_ts does not exist\nLINE 1: SELECT oi.platform, SUM(CASE WHEN o.order_ts >= ...\nHINT:  Perhaps you meant to reference the column "o.order_id".',
    "Name order_ts not found inside o at [1:40]",
    "SQL compilation error: invalid identifier 'O.ORDER_TS'",
])
def test_the_missing_column_diagnosis_lists_the_real_columns_of_the_table_the_alias_names(error):
    diag = diagnose_sql_error(error, SQL, COLS, dialect="postgres")
    assert diag.startswith("DIAGNOSIS:") and "does not exist in table 'orders'" in diag
    assert "orders: order_id, platform, customer_id, order_date, gmv_eur, status" in diag
    assert "order_items:" not in diag                                   # the alias named one table
    assert "a date or timestamp column when it stood for a date" in diag


def test_an_unqualified_missing_column_lists_every_table_the_query_reads():
    diag = diagnose_sql_error('column "order_ts" does not exist', SQL, COLS, dialect="postgres")
    assert "any table this query reads" in diag and "orders: order_id" in diag and "order_items: order_item_id" in diag
    assert "does not exist" not in diagnose_sql_error("permission denied for table orders", SQL, COLS, dialect="postgres")


def test_run_sql_hands_the_diagnosis_back_with_the_error(monkeypatch):
    import aughor.agent.converse_tools as CT
    import aughor.sql.executor as EX
    conn = NS(dialect="postgres", get_schema=lambda: FULL)
    monkeypatch.setattr(CT, "_connection", lambda cid, canvas_id=None, schema_scope=None: conn)
    monkeypatch.setattr(EX, "execute_guarded", lambda c, sql, query_id, metric_rules: NS(
        error="column o.order_ts does not exist\nHINT:  Perhaps you meant to reference the column \"o.order_id\".",
        columns=[], rows=[], row_count=0, caveats=[], sql=sql, doors=["failed:sql"]))
    import aughor.semantic.enforcement as EN
    monkeypatch.setattr(EN, "rules_for_statement", lambda *a, **k: [])
    out = CT.run_sql("c1", {"sql": SQL})
    assert out["error"].startswith("column o.order_ts does not exist")
    assert out["repair"]["diagnosis"].startswith("DIAGNOSIS: 'order_ts' does not exist in table 'orders'")
    assert "order_date" in out["repair"]["diagnosis"]
    assert out["repair"]["instruction"].startswith("DIAGNOSIS:")        # read first, the class guidance after


# ── a second run of a phase tool gets ids of its own ───────────────────────────────────

def _decomp(*ids: str) -> dict:
    return {"phase_id": "decomposition", "phase_name": "Metric Decomposition", "status": "complete", "summary": "s",
            "findings": [{"finding_id": i, "title": i, "sql": "SELECT 1", "columns": ["a"], "rows": [[1]], "row_count": 1,
                          "error": None, "interpretation": "", "key_numbers": [], "chart_type": "auto"} for i in ids]}


def test_a_repeated_phase_is_renamed_before_the_model_reads_its_ids():
    turn = AnalystTurn(connection_id="c", conn=NS(dialect="duckdb"), state={"question": Q, "investigation_phases": []})
    first = turn.merge({"investigation_phases": [_decomp("decomp_0", "decomp_1", "decomp_2")]}, tool="decompose")
    phases = turn.state["investigation_phases"]
    second = turn.merge({"investigation_phases": phases + [_decomp("decomp_0", "decomp_1", "decomp_2")]}, tool="decompose")
    assert [p["phase_id"] for p in turn.state["investigation_phases"]] == ["decomposition", "decomposition_2"]
    assert [f["finding_id"] for f in second[0]["findings"]] == ["decomp_0_2", "decomp_1_2", "decomp_2_2"]
    assert [f["finding_id"] for f in first[0]["findings"]] == ["decomp_0", "decomp_1", "decomp_2"]
    payload = _phase_payload(second)
    assert [r["result_id"] for r in payload["phases"][0]["results"]] == ["decomp_0_2", "decomp_1_2", "decomp_2_2"]
    ids = [f["finding_id"] for p in turn.state["investigation_phases"] for f in p["findings"]]
    assert len(ids) == len(set(ids)) == 6
    third = turn.merge({"investigation_phases": turn.state["investigation_phases"] + [_decomp("decomp_0")]}, tool="decompose")
    assert third[0]["phase_id"] == "decomposition_3" and third[0]["findings"][0]["finding_id"] == "decomp_0_3"


def test_distinct_phases_are_left_alone():
    phases = [{"phase_id": "baseline", "findings": [{"finding_id": "baseline_0"}]}]
    fresh = [{"phase_id": "decomposition", "findings": [{"finding_id": "decomp_0"}]},
             {"phase_id": "adhoc_3", "findings": [{"finding_id": "adhoc_3_1"}]}]
    _unique_phase_ids(phases, fresh)
    assert [p["phase_id"] for p in fresh] == ["decomposition", "adhoc_3"]
    assert fresh[0]["findings"][0]["finding_id"] == "decomp_0"


# ── the answer's gaps are written for the reader ───────────────────────────────────────

def _turn() -> AnalystTurn:
    phases = [{"phase_id": "adhoc_1", "phase_name": "Revenue by platform", "status": "complete", "summary": "", "findings": [
        {"finding_id": "adhoc_1_1", "title": "Revenue by platform", "sql": "SELECT 1", "columns": ["platform", "revenue"],
         "rows": [["Mytheresa", 300300.0], ["Mr Porter", 180000.0]], "row_count": 2, "interpretation": "", "key_numbers": [],
         "chart_type": "auto", "error": None}]}]
    return AnalystTurn(connection_id="c1", conn=NS(dialect="duckdb"), state={"question": Q, "investigation_phases": phases})


GOOD = {"headline": "September revenue rose 14.9% on August; Mytheresa carried 60.6% of the change",
        "answer": "September revenue rose €93.8K on August. Mytheresa carried €56.9K of the rise; all four platforms grew.",
        "exhibits": [{"result": "adhoc_1_1", "claim": "All four platforms grew; Mytheresa +€56.9K is the largest"}],
        "gaps": "This analysis did not test new versus returning customers, promotions or events; category and brand "
                "were read from the decomposition's top rows only."}
LUX_GAPS = ("I did not test new versus returning customers, promotions or events, or the weak August itself. I could not "
            "run the category and brand cut myself because the query errored. I rely on the phase tool's summaries for those splits.")


def test_gaps_in_the_reports_voice_are_accepted():
    out = conclude(_turn(), GOOD)
    assert out["concluded"] is True and out["gaps"] == GOOD["gaps"]


def test_the_lux_gaps_are_refused_for_the_first_person_and_the_machinery():
    turn = _turn()
    out = conclude(turn, {**GOOD, "gaps": LUX_GAPS})
    assert "concluded" not in out and turn.conclusion is None
    assert "gaps names the machinery ('the query errored')" in out["refused"] or "gaps names the machinery ('phase tool'" in out["refused"]
    assert "gaps speaks in the first person" in out["refused"]
    assert "This analysis did not test" in out["refused"]                 # the register asked for, in the refusal


def test_the_answer_is_held_to_the_same_register_and_words_that_merely_contain_i_are_not():
    out = conclude(_turn(), {**GOOD, "answer": "I measured September at €721.8K; my platform cut shows Mytheresa leading."})
    assert "the answer speaks in the first person" in out["refused"]
    # "AI", "MY_COL", "Mytheresa" contain the letters and are not the pronoun
    out = conclude(_turn(), {**GOOD, "answer": "AI-led merchandising at Mytheresa carried the rise; MY_COL is a column name here."})
    assert out["concluded"] is True


# ── a metric's date must be on a table its definition reads ────────────────────────────

def test_a_date_on_a_table_the_definition_does_not_read_is_refused_at_the_door(monkeypatch):
    from fastapi.testclient import TestClient
    import aughor.routers.metrics as MR
    from aughor.api import app
    saved: list = []
    # The door is what is under test; nothing is written to the shared catalogue (a row left behind
    # here reached `test_metric_dedup`'s raw read of the file).
    monkeypatch.setattr(MR, "save_metric", lambda m: saved.append(m))
    monkeypatch.setattr(MR, "_restate_briefings", lambda *a, **k: None)
    client = TestClient(app)
    body = {"name": "gross_margin_lux_test", "label": "Gross margin %", "connection": "lux-guard-conn", "tables": [],
            "sql": "SELECT (SUM(unit_price_eur * quantity) - SUM(cost_eur * quantity)) / NULLIF(SUM(unit_price_eur * quantity), 0) * 100 AS gross_margin_pct FROM order_items",
            "time_kind": "flow", "time_column": "luxexperience.order.order_date"}
    res = client.post("/metrics", json=body)
    assert res.status_code == 422, res.text
    assert res.json()["detail"] == ("luxexperience.order.order_date is on luxexperience.order, which this definition does not read "
                                    "(it reads order_items). Add the join to luxexperience.order in the SQL, then choose the date here.")
    joined = {**body, "sql": body["sql"].replace("FROM order_items", "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id"),
              "time_column": "orders.order_date"}
    res = client.post("/metrics", json=joined)
    assert res.status_code == 201, res.text
    assert res.json()["time_column"] == "orders.order_date"
