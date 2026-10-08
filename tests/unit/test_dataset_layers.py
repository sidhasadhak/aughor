"""What a dataset is for — its layer — read from its signs, set by a person (2026-10-08).

The exploration principles' §5 and the user's decisions 1 and 2: six layers, read from SCHEMA and
table names as whole words and as prefixes (`stage_marketing`, `STAGE_API`, `fct_orders`), from
column signs — and a name never sets a layer by itself: it is proposed with its evidence, and
until a person sets one the dataset gets structure learning only.
"""
from __future__ import annotations

import uuid

import pytest

from aughor.ontology import dataset_layers as L


@pytest.mark.parametrize("name, words", [
    ("stage_marketing", ["stage", "marketing"]),
    ("STAGE_API", ["stage", "api"]),
    ("rawSalesforce", ["raw", "salesforce"]),
    ("dbt-marts.core", ["dbt", "marts", "core"]),
])
def test_a_name_is_read_as_its_words(name, words):
    assert L.name_words(name) == words


@pytest.mark.parametrize("schema, layer", [
    ("stage_marketing", "raw"), ("STAGE_API", "raw"), ("raw_salesforce", "raw"),
    ("analytics_marts", "business"), ("silver", "integration"), ("ref_codes", "reference"),
    ("sandbox_amit", "uploads"), ("audit", "system"),
])
def test_a_schemas_own_name_says_its_layer(schema, layer):
    p = L.propose_schema(schema, {})
    assert p.layer == layer and p.evidence and "schema's name" in p.evidence[0]


def test_a_word_inside_another_word_is_not_a_sign():
    """`restaurant` holds `rest`, `transfers` holds `ransfer`; `starfish` holds `tar`. None is a word."""
    assert L.propose_schema("restaurants", {}).evidence == ["no name or column sign of another layer"]
    assert L.propose_table("staged_rows").layer == ""            # `staged` is not `stage`
    assert L.propose_table("user_sessions").layer == ""          # a business table, whatever `user` says of a schema


def test_a_tables_prefix_suffix_and_columns_say_its_layer():
    assert L.propose_table("fct_orders").layer == "business"
    assert L.propose_table("orders_fact").layer == "business"
    assert L.propose_table("stg_orders").layer == "raw"
    loaded = L.propose_table("orders", [("id", "INTEGER"), ("_fivetran_synced", "TIMESTAMP")])
    assert loaded.layer == "raw" and "_fivetran_synced" in loaded.evidence[0]
    texts = L.propose_table("events", [("a", "VARCHAR"), ("b", "VARCHAR"), ("c", "TEXT")])
    assert texts.layer == "raw" and "text" in texts.evidence[0]
    narrow = L.propose_table("country", [("country_code", "VARCHAR"), ("country_name", "VARCHAR")])
    assert narrow.layer == "reference"


def test_a_schema_without_a_name_sign_reads_its_tables_else_says_business_as_such():
    staged = {f"stg_t{i}": [] for i in range(14)} | {"orders": [], "items": []}
    p = L.propose_schema("public", staged)
    assert p.layer == "raw" and p.evidence == ["14 of 16 tables read as raw"]
    mixed = {"fct_orders": [], "stg_orders": [], "customers": []}
    p = L.propose_schema("public", mixed, approved_metrics=3)
    assert p.layer == "business"
    assert p.evidence == ["3 approved metrics read it", "no name or column sign of another layer"]


def test_a_person_sets_a_layer_and_a_table_can_differ_from_its_schema():
    conn = f"c-{uuid.uuid4().hex[:8]}"
    assert L.layer_of(conn, "marts") == ""
    with pytest.raises(ValueError):
        L.set_layer(conn, "marts", "business", set_by="")        # a layer nobody set is not a layer
    with pytest.raises(ValueError):
        L.set_layer(conn, "marts", "gold", set_by="user:amit")
    rec = L.set_layer(conn, "marts", "business", set_by="user:amit")
    assert rec["set_by"] == "user:amit" and rec["set_at"]
    L.set_layer(conn, "marts", "reference", table="marts.dim_calendar", set_by="user:amit")
    assert L.layer_of(conn, "marts") == "business"
    assert L.layer_of(conn, "marts", "dim_calendar") == "reference"
    assert L.layer_of(conn, "marts", "orders") == "business"
    assert L.clear_layer(conn, "marts")
    assert L.layer_of(conn, "marts", "orders") == ""


def test_unset_learns_structure_only_and_each_layer_its_own_jobs():
    assert L.auto_jobs("") == {"structure"}
    assert L.auto_jobs("business") == {"structure", "questions", "time"}
    assert L.auto_jobs("raw") == {"structure"}
    assert L.auto_jobs("system") == set()
    assert L.auto_jobs("integration") == {"structure"}
    assert L.auto_jobs("integration", connection_has_business=False) == {"structure", "questions", "time"}
