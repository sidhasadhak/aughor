"""The exploration principles, the parts the first build left out (2026-10-08, "keep building").

Each was listed as not built in the study's §12: an automatic re-run never reaching the model's free
curiosity (now where a test sees it), table layers inside a schema (one entity, several layers — findings
from the business copy), a run capped at what is left of its month, ranking by what people query, a
question the platform could not answer and a new value in a known dimension as reopen events, a raw
dataset's pipeline health, a move explained by its segments, and a dbt manifest as a layer sign.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import duckdb
import pytest

from aughor.explorer import program as P


# ── an automatic re-run never reaches the model's free curiosity ─────────────

def _explorer(**kw):
    from aughor.explorer.agent import SchemaExplorer
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.connection_id, ex.schema_name, ex._state = "c", None, {}
    for k, v in kw.items():
        setattr(ex, k, v)
    return ex


def test_an_automatic_rerun_with_no_uncovered_cell_calls_no_model():
    from aughor.explorer import agent as A
    calls = []

    async def probe(*a, **k):
        calls.append("probe")
        return None

    llm = SimpleNamespace(complete=lambda **k: calls.append("free-form"))
    ex = _explorer(_manifest_driven=True, _gaps_only=True)
    ex._manifest_nq = lambda cols, NQ: None
    ex._grounded_probe_nq = probe
    got = asyncio.run(ex._next_question("Sales", {"orders": ["id"]}, {}, object, llm, lambda: "", "s", "u"))
    assert got is A._NO_MORE_QUESTIONS and calls == []

    ex._gaps_only = False                      # a person's run, a first run or a reopen: curiosity runs
    asyncio.run(ex._next_question("Sales", {"orders": ["id"]}, {}, object, llm, lambda: "", "s", "u"))
    assert calls == ["probe", "free-form"]


def test_a_question_list_cell_comes_first_and_spends_no_generation():
    cell = SimpleNamespace(sql="SELECT 1")
    ex = _explorer(_manifest_driven=True, _gaps_only=True)
    ex._manifest_nq = lambda cols, NQ: cell
    assert asyncio.run(ex._next_question("Sales", {}, {}, object, None, lambda: "", "s", "u")) is cell


# ── table layers inside a schema: findings from the business copy ─────────────

def test_a_table_set_to_another_layer_is_never_asked_about_on_its_own(monkeypatch):
    from aughor.explorer.coverage_manifest import ManifestCell
    conn = f"c-{uuid.uuid4().hex[:6]}"
    from aughor.ontology import dataset_layers as L
    L.set_layer(conn, "public", "raw", table="stg_orders", set_by="amit")
    L.set_layer(conn, "public", "reference", table="dim_country", set_by="amit")
    ex = _explorer(connection_id=conn, schema_name="public", _manifest_attempted=set(), _state={})
    ex._manifest_cells = [ManifestCell("amount", "stg_orders", "headline", None, "profiled_measure"),
                          ManifestCell("n", "dim_country", "headline", None, "profiled_measure"),
                          ManifestCell("amount", "orders", "headline", None, "profiled_measure")]
    asked = []
    monkeypatch.setattr("aughor.explorer.manifest_query.cell_to_sql", lambda cell, *a, **k: "SELECT 1")
    monkeypatch.setattr("aughor.explorer.manifest_query.cell_question",
                        lambda cell, *a, **k: asked.append(cell.table) or f"q {cell.table}")
    ex._tp_by_table, ex._cp_by_key = {}, {}
    try:
        ex._manifest_nq({"stg_orders": [], "dim_country": [], "orders": []}, lambda **k: SimpleNamespace(**k))
    except Exception:  # noqa: BLE001 — only which cell it reached is under test
        pass
    assert {c[1] for c in ex._manifest_attempted} == {"orders"}, ex._manifest_attempted
    from aughor.explorer.agent import _QUIET_LAYERS
    assert ex._table_layer("stg_orders") in _QUIET_LAYERS and ex._table_layer("orders") == ""


def test_one_entity_in_several_layers_is_read_as_copies():
    from aughor.ontology import dataset_layers as L
    assert L.entity_key("stg_orders") == L.entity_key("fct_orders") == L.entity_key("orders_raw") == "order"
    assert L.entity_key("address") == "address"
    copies = L.copies_of({"raw": ["stg_orders", "events"], "marts": ["fct_orders", "dim_customer"]})
    assert copies[("raw", "stg_orders")] == ["marts.fct_orders"]
    assert ("raw", "events") not in copies


# ── a dbt manifest is a layer sign ────────────────────────────────────────────

MANIFEST = {
    "sources": {"source.p.shop.orders": {"resource_type": "source", "schema": "raw", "name": "orders"}},
    "nodes": {
        "model.p.stg_orders": {"resource_type": "model", "schema": "analytics", "name": "stg_orders",
                               "fqn": ["p", "staging", "shop", "stg_orders"]},
        "model.p.int_orders": {"resource_type": "model", "schema": "analytics", "name": "int_orders",
                               "fqn": ["p", "intermediate", "int_orders"]},
        "model.p.orders": {"resource_type": "model", "schema": "analytics", "name": "orders", "alias": "orders",
                           "fqn": ["p", "marts", "core", "orders"]},
        "seed.p.country_codes": {"resource_type": "seed", "schema": "analytics", "name": "country_codes",
                                 "fqn": ["p", "country_codes"]},
        "model.p.fct_daily": {"resource_type": "model", "schema": "analytics", "name": "fct_daily",
                              "fqn": ["p", "staging", "fct_daily"]},
    },
}


def test_dbt_lineage_says_each_tables_layer_and_outweighs_its_name():
    from aughor.ontology import dataset_layers as L
    signs = L.lineage_signs(MANIFEST)
    assert signs[("raw", "orders")].layer == "raw"
    assert signs[("analytics", "stg_orders")].layer == "raw"
    assert signs[("analytics", "int_orders")].layer == "integration"
    assert signs[("analytics", "orders")].layer == "business"
    assert signs[("analytics", "country_codes")].layer == "reference"
    # a staging model named like a fact table: dbt's folder wins over the name
    p = L.propose_table("fct_daily", lineage=signs[("analytics", "fct_daily")])
    assert p.layer == "raw" and p.evidence == ["dbt builds it under models/staging"]


def test_the_configured_manifest_is_read_and_reread_when_it_changes(tmp_path, monkeypatch):
    import json
    from aughor.ontology import dataset_layers as L
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(MANIFEST))
    monkeypatch.setenv("AUGHOR_DBT_MANIFEST", str(path))
    assert L.configured_lineage()[("analytics", "orders")].layer == "business"
    monkeypatch.delenv("AUGHOR_DBT_MANIFEST")
    assert L.configured_lineage() == {}


# ── a run capped at what is left of its month ─────────────────────────────────

def test_a_jobs_token_cap_tightens_its_agents_budget_and_never_raises_it(monkeypatch):
    from aughor.kernel import jobs as J
    from aughor.kernel.agents import Governance
    k = J.JobKernel.__new__(J.JobKernel) if hasattr(J, "JobKernel") else None
    if k is None:
        k = type(J.kernel()).__new__(type(J.kernel()))
    monkeypatch.setattr("aughor.kernel.agents.effective_governance",
                        lambda agent, ws=None: Governance(enabled=True, token_budget=200_000, time_budget_s=600))
    monkeypatch.setattr("aughor.workspace.store.workspace_for_connection", lambda c: None)

    def with_payload(payload):
        k.ledger = SimpleNamespace(job_get=lambda jid: {"kind": "exploration", "conn_id": "c", "payload": payload})
        return k._resolve_governance("j")[0].token_budget

    assert with_payload({"token_cap": 50_000}) == 50_000
    assert with_payload({"token_cap": 900_000}) == 200_000, "a cap never raises the agent's own budget"
    assert with_payload({}) == 200_000
    assert with_payload({"token_cap": True}) == 200_000


def test_runs_started_together_share_what_is_left_and_rank_by_what_people_query(monkeypatch):
    import aughor.explorer.continuous as cont
    from tests.unit.test_continuous_exploration import _complete, _planner
    states = {"marts": _complete(distributions={"orders:amount": {}}),
              "sales": _complete(distributions={"tickets:n": {}}), "ops": _complete()}
    _planner(monkeypatch, states, layers={"marts": "business", "sales": "business", "ops": "business"})
    monkeypatch.setattr(cont, "_approved_count", lambda cid, sch: 1)          # a tie on metrics
    monkeypatch.setattr(cont, "_asked_counts", lambda cid, now: {"tickets": 40, "orders": 3})
    monkeypatch.setattr("aughor.explorer.budget.standing",
                        lambda cid, now=None: {"spent_out": False, "sentence": "", "remaining": 90_000})
    runs, _ = cont.plan_jobs(now=datetime(2026, 7, 12, tzinfo=timezone.utc))
    model = [r for r in runs if r["uses_model"]]
    assert [r["schema"] for r in model] == ["sales", "marts"], "what people query breaks the tie"
    assert [r["token_cap"] for r in model] == [45_000, 45_000]


# ── a question it could not answer, and a new value, reopen ───────────────────

def test_two_questions_a_dataset_could_not_answer_in_a_week_reopen_it():
    key = f"wh-{uuid.uuid4().hex[:6]}__marts"
    assert P.note_unanswered(key, "the query failed") is False
    assert P.note_unanswered(key, "an analytical question came back empty") is True
    assert "2 questions it could not answer" in P.load(key)["reopened"]["reason"]


def test_a_refusal_is_not_a_gap_and_a_failure_counts_against_its_dataset(monkeypatch):
    from aughor.routers import investigations as inv
    noted = []
    monkeypatch.setattr(P, "note_unanswered", lambda key, why: noted.append((key, why)))
    monkeypatch.setattr(P, "dataset_key", lambda conn, schema: f"{conn}__{schema}")
    inv._note_unanswered("wh", "marts", "SELECT 1", "error", "[EXCLUDED] stage.orders is turned off …")
    inv._note_unanswered("wh", "marts", "SELECT 1", "causal_thin", "")
    assert noted == []
    inv._note_unanswered("wh", None, "SELECT * FROM sales.orders", "no_rows", "")
    assert noted == [("wh__sales", "an analytical question came back empty")]


@pytest.fixture
def wh(tmp_path):
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA landing")
    con.execute("CREATE TABLE landing.events AS SELECT range AS id, "
                "CASE WHEN range % 2 = 0 THEN 'a' ELSE NULL END AS kind, "
                "DATE '2026-10-01' + CAST(range % 5 AS INTEGER) AS loaded_on FROM range(40)")
    con.close()
    return f"wh-{uuid.uuid4().hex[:6]}", str(path)


def test_a_raw_datasets_health_says_what_changed_since_the_last_reading(wh, monkeypatch):
    from aughor.db.connection import open_connection
    from aughor.explorer import health as H
    conn_id, path = wh
    monkeypatch.setattr("aughor.tools.profile_cache.merged_profile_entry", lambda c: {})
    monkeypatch.setattr("aughor.semantic.metric_time.primary_date", lambda prof, t: "loaded_on")
    db = open_connection("duckdb", path, schema_name="landing", connection_id=conn_id)
    first = H.read_dataset(conn_id, "landing", layer="raw", reopen_questions=False, db=db)
    assert first == {"kind": "health", "notes": [], "tables": 1}
    reading = P.load(P.key_for(conn_id, "landing"))["health"]["tables"]["events"]
    assert reading["rows"] == 40 and reading["newest"] == "2026-10-05" and reading["empty"]["kind"] == 0.5
    assert H.read_dataset(conn_id, "landing", layer="raw", reopen_questions=False, db=db) == {}, "once a day"
    later = datetime.now(timezone.utc) + timedelta(days=1, minutes=1)
    db.close()
    con = duckdb.connect(path)
    con.execute("UPDATE landing.events SET kind = NULL WHERE id < 30")
    con.close()
    db2 = open_connection("duckdb", path, schema_name="landing", connection_id=conn_id)
    again = H.read_dataset(conn_id, "landing", layer="raw", reopen_questions=False, db=db2, now=later)
    assert "events: no new rows since the last reading (40)" in again["notes"]
    assert any(n.startswith("events.kind: empty in") for n in again["notes"])


def test_a_new_value_in_a_known_dimension_reopens_and_the_first_reading_is_a_baseline(wh, monkeypatch):
    from aughor.db.connection import open_connection
    from aughor.explorer import health as H
    conn_id, path = wh
    prof = {"columns": {"events.kind": {"table": "events", "column": "kind", "dtype": "VARCHAR",
                                        "is_low_cardinality": True}}}
    monkeypatch.setattr("aughor.tools.profile_cache.merged_profile_entry", lambda c: prof)
    db = open_connection("duckdb", path, schema_name="landing", connection_id=conn_id)
    key = P.key_for(conn_id, "landing")
    assert H.read_dataset(conn_id, "landing", layer="business", reopen_questions=True, db=db)["news"] == []
    assert P.load(key)["reopened"] is None
    db.close()
    con = duckdb.connect(path)
    con.execute("INSERT INTO landing.events VALUES (99, 'returned', DATE '2026-10-06')")
    con.close()
    db2 = open_connection("duckdb", path, schema_name="landing", connection_id=conn_id)
    later = datetime.now(timezone.utc) + timedelta(days=1, minutes=1)
    got = H.read_dataset(conn_id, "landing", layer="business", reopen_questions=True, db=db2, now=later)
    assert got["news"] == ["a new value in events.kind: 'returned'"]
    assert P.load(key)["reopened"]["reason"] == "a new value in events.kind: 'returned'"


# ── a move explained by its segments ──────────────────────────────────────────

def test_a_move_is_explained_by_the_segment_that_carries_it_and_the_reopen_says_so(monkeypatch):
    from aughor.explorer import watch as W
    conn = f"wh-{uuid.uuid4().hex[:6]}"
    m = SimpleNamespace(name="revenue", label="revenue", time_grain="day", time_kind="flow",
                        time_column="orders.created_at", until_column="", outcome_column="",
                        sql="SUM(amount)", tables=["orders"], dimensions=[])
    monkeypatch.setattr("aughor.briefing.ranges.governed_metrics", lambda c, s=None: [m])
    spec = SimpleNamespace(start=date(2026, 10, 7), end=date(2026, 10, 8), last_day=date(2026, 10, 7))
    monkeypatch.setattr("aughor.briefing.ranges.resolve_for", lambda c, preset, **k: (spec, ""))
    measure = lambda sp: {"measured": [{"name": "revenue", "metric": "revenue", "rel": -0.12, "status": "final"}],
                          "unmeasured": []}
    explain = lambda ms, sp: [{"metric": "revenue", "name": "revenue", "dimension": "country", "group": "US",
                               "change": -4200.0, "share": False}]
    W.read_due(conn, "marts", reopen_questions=True, measure=measure, explain=explain)
    prog = P.load(f"{conn}__marts")
    assert prog["watch"]["day"]["explained"][0]["group"] == "US"
    assert prog["reopened"]["reason"].endswith("most of it country = US (-4,200)")


def test_the_breakdown_falls_back_to_its_tables_known_dimensions(monkeypatch):
    from aughor.explorer import watch as W
    prof = {"columns": {
        "orders.country": {"table": "orders", "column": "country", "dtype": "VARCHAR", "is_low_cardinality": True},
        "orders.customer_id": {"table": "orders", "column": "customer_id", "is_fk": True, "is_low_cardinality": True},
        "orders.created_at": {"table": "orders", "column": "created_at", "dtype": "DATE", "is_low_cardinality": True}}}
    m = SimpleNamespace(time_column="orders.created_at", tables=["orders"])
    assert W._fallback_dimensions(m, prof) == ["country"]
