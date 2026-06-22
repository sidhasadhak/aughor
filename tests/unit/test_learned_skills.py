"""Learned skills — agent procedural memory (R8 Agent-Skills). The inert stubs are now a real
subsystem: a finished investigation crystallizes into a reusable, governed `OntologyAction`
(origin='learned'), saved (EXPLAIN-gated) under a {conn}:{schema} store that the ontology overlay
re-enters. These tests cover the store CRUD, the conservative SQL parameterization, and the
crystallizer. The store is redirected to a tmp path so nothing touches the real data file."""
from __future__ import annotations

import pytest

from aughor.memory import skills as S
from aughor.memory.skills import (
    _parameterize_sql, _materialize, _is_read_only, _primary_sql, _primary_table,
    _infer_action_type, propose_skill_from_investigation, auto_crystallize,
)
from aughor.ontology.models import OntologyAction


@pytest.fixture
def _store(tmp_path, monkeypatch):
    from aughor.util.json_store import KeyedJsonStore
    monkeypatch.setattr(S, "_STORE", KeyedJsonStore(str(tmp_path / "skills.json")))


def _action(aid="learned_top_region", sql="SELECT region, SUM(rev) AS r FROM orders WHERE region = {region} GROUP BY region",
            params=None):
    from aughor.ontology.models import ActionParameter
    return OntologyAction(
        id=aid, display_name="Top by region", description="d", entity="Order",
        action_type="aggregate", sql_template=sql,
        parameters=params if params is not None else [ActionParameter(name="region", data_type="VARCHAR", default_value="EU")],
        returns="rows", source_table="orders", origin="learned", usage_count=0)


# ── SQL parameterization ────────────────────────────────────────────────────────

def test_parameterize_turns_where_literal_into_param():
    tmpl, params = _parameterize_sql(
        "SELECT region, SUM(rev) AS r FROM orders WHERE region = 'EU' GROUP BY region")
    assert "{region}" in tmpl and "'EU'" not in tmpl
    assert len(params) == 1 and params[0].name == "region" and params[0].default_value == "EU"


def test_parameterize_handles_multiple_and_dedupes_names():
    tmpl, params = _parameterize_sql(
        "SELECT * FROM o WHERE region = 'EU' AND region = 'US' AND tier = 5")
    names = [p.name for p in params]
    assert names == ["region", "region_1", "tier"] and tmpl.count("{") == 3


def test_parameterize_bails_to_verbatim_without_equality_filter():
    sql = "SELECT region, SUM(rev) FROM orders GROUP BY region"
    tmpl, params = _parameterize_sql(sql)
    assert tmpl == sql and params == []


def test_materialize_round_trips_to_concrete_sql():
    tmpl, params = _parameterize_sql("SELECT * FROM o WHERE region = 'EU' AND tier = 5")
    concrete = _materialize(tmpl, params)
    assert "{" not in concrete and "'EU'" in concrete and " = 5" in concrete


def test_read_only_gate():
    assert _is_read_only("SELECT 1") and _is_read_only("WITH a AS (SELECT 1) SELECT * FROM a")
    assert not _is_read_only("DELETE FROM orders") and not _is_read_only("DROP TABLE x")


def test_primary_sql_and_table_and_type():
    inv = {"report": {"sql": "SELECT region, SUM(rev) FROM orders GROUP BY region"}}
    assert _primary_sql(inv).startswith("SELECT")
    assert _primary_table("SELECT * FROM missimi.orders o") == "orders"
    assert _infer_action_type("SELECT SUM(x) FROM t") == "aggregate"
    assert _infer_action_type("SELECT * FROM t WHERE a=1") == "filter"


def test_primary_sql_falls_back_to_last_successful_query():
    inv = {"report": {}, "query_history": [
        {"sql": "SELECT bad", "error": "boom"},
        {"sql": "SELECT region FROM orders", "error": None}]}
    assert _primary_sql(inv) == "SELECT region FROM orders"


# ── store CRUD (isolated) ─────────────────────────────────────────────────────────

def test_save_load_use_delete_round_trip(_store):
    a = _action()
    assert S.save_skill("c", "missimi", a, validator=lambda sql: True) is True
    loaded = S.load_learned_actions("c", "missimi")
    assert a.id in loaded and loaded[a.id].origin == "learned"
    assert S.record_skill_use("c", "missimi", a.id) == 1
    assert S.record_skill_use("c", "missimi", a.id) == 2
    assert S.load_learned_actions("c", "missimi")[a.id].usage_count == 2
    assert S.delete_skill("c", "missimi", a.id) is True
    assert a.id not in S.load_learned_actions("c", "missimi")


def test_save_skill_rejected_when_validator_fails(_store):
    a = _action()
    assert S.save_skill("c", "missimi", a, validator=lambda sql: False) is False
    assert S.load_learned_actions("c", "missimi") == {}


def test_save_skill_validator_sees_concrete_sql(_store):
    seen = {}
    def _v(sql):
        seen["sql"] = sql
        return True
    S.save_skill("c", "missimi", _action(), validator=_v)
    assert "{region}" not in seen["sql"] and "'EU'" in seen["sql"]   # params materialized for EXPLAIN


def test_use_and_delete_missing_skill_are_safe(_store):
    assert S.record_skill_use("c", "missimi", "nope") == 0
    assert S.delete_skill("c", "missimi", "nope") is False


def test_skills_are_scoped_per_conn_schema(_store):
    S.save_skill("c", "missimi", _action(aid="learned_a"), validator=lambda s: True)
    assert "learned_a" not in S.load_learned_actions("c", "other")    # different schema → isolated
    assert "learned_a" not in S.load_learned_actions("other", "missimi")


# ── crystallization ───────────────────────────────────────────────────────────────

def test_propose_builds_a_parameterized_learned_action(monkeypatch):
    inv = {
        "question": "Which region has the highest revenue for EU?",
        "report": {"sql": "SELECT region, SUM(order_value) AS rev FROM missimi.orders WHERE region = 'EU' GROUP BY region",
                   "headline": "EU leads at €1.2M"},
    }
    monkeypatch.setattr("aughor.db.history.get_investigation", lambda _id: inv)
    cand = propose_skill_from_investigation("inv-1", table_to_entity={"orders": "Order"})
    assert cand is not None and cand.origin == "learned"
    assert cand.entity == "Order" and cand.source_table == "orders"
    assert cand.action_type == "aggregate"
    assert "{region}" in cand.sql_template and len(cand.parameters) == 1
    assert "EU leads" in cand.description


def test_propose_rejects_a_non_read_only_or_missing_query(monkeypatch):
    monkeypatch.setattr("aughor.db.history.get_investigation",
                        lambda _id: {"question": "q", "report": {"sql": "DELETE FROM orders"}})
    assert propose_skill_from_investigation("inv-x") is None
    monkeypatch.setattr("aughor.db.history.get_investigation", lambda _id: None)
    assert propose_skill_from_investigation("missing") is None


def test_auto_crystallize_is_a_noop_at_manual_autonomy():
    # L0 (the only level today) never auto-saves — a strong run stays a UI-confirmed candidate.
    assert auto_crystallize("inv-1", "c") is None
