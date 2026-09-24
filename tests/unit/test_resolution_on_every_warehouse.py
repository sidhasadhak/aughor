"""PENDING item 19 — values a question names bind on every warehouse, from what is already cached.

Measured 2026-09-24: the resolver read only the house schema form (indented column lines). The
inline form BigQuery, Snowflake, MySQL, MotherDuck and Exasol write (`TABLE: t [a INT, b TEXT]`)
parsed as tables with no columns, so nothing bound there; and the column-name gate that limits
LIVE probes (a warehouse round trip each) also gated the offline read of values the profiler had
already cached, so a value in a column named `make` never bound anywhere.

Now the parser reads both forms, and the offline pass covers every cached column whose table is
in scope — the profiler's high-cardinality samples and its low-cardinality top values. The live
probe keeps its gate: on the inline form it still never runs, so no new billed scan and no new
"not present" abstention.
"""
from __future__ import annotations

import pytest

from aughor.semantic import answer_resolution as ar

INLINE = ("TABLE: cars (120 rows) [car_id INTEGER, make STRING, model STRING]\n"
          "TABLE: sales (4000 rows) [sale_id INTEGER, car_id INTEGER, revenue FLOAT64]\n"
          "TABLE: customers (900 rows) [customer_id INTEGER, country STRING]")


class _NoProbes:
    """A warehouse the resolver must not touch: every live probe is a failure here."""
    dialect = "bigquery"

    def rows(self, sql, label=""):
        raise AssertionError(f"a live probe ran on the inline form: {sql}")


@pytest.fixture()
def cached(monkeypatch):
    samples = {("cars", "make"): ["Ferrari", "Fiat", "Ford"],
               ("dealers", "make"): ["Ferrari"]}                     # a table not in scope
    top = {("customers", "country"): ["Germany", "France", "Italy"]}
    monkeypatch.setattr("aughor.tools.profile_cache.load_value_samples", lambda cid: samples)
    monkeypatch.setattr("aughor.tools.profile_cache.load_top_values", lambda cid: top)
    monkeypatch.setattr("aughor.ontology.column_config.load_index_disabled", lambda cid: set())


def test_the_inline_form_parses_to_tables_with_columns():
    tables, domains = ar._parse_schema(INLINE)
    assert tables["cars"] == ["car_id", "make", "model"]
    assert tables["sales"] == ["sale_id", "car_id", "revenue"]
    assert domains == []                                  # the inline form carries no values


def test_a_value_in_a_column_the_name_gate_skips_binds_offline(cached):
    r = ar.resolve("What was the revenue from Ferrari last year?", schema=INLINE,
                   db=_NoProbes(), connection_id="c1")
    binding = next(b for b in r.entity_bindings if b.value == "Ferrari")
    assert (binding.table, binding.column) == ("cars", "make")   # never the out-of-scope table


def test_a_low_cardinality_value_binds_from_the_top_values(cached):
    r = ar.resolve("How many customers are in Germany?", schema=INLINE, db=_NoProbes(),
                   connection_id="c1")
    assert [(b.table, b.column, b.value) for b in r.entity_bindings] == [
        ("customers", "country", "Germany")]
    assert not r.not_found


def test_an_uncached_value_on_the_inline_form_is_never_called_absent(cached):
    r = ar.resolve("What was the revenue from Lamborghini cars?", schema=INLINE, db=_NoProbes(),
                   connection_id="c1")
    assert not r.not_found and r.feasibility != "not_answerable"


def test_a_binding_names_the_table_as_the_schema_spells_it(monkeypatch):
    monkeypatch.setattr("aughor.tools.profile_cache.load_value_samples",
                        lambda cid: {("cars", "make"): ["Ferrari"]})
    monkeypatch.setattr("aughor.tools.profile_cache.load_top_values", lambda cid: {})
    monkeypatch.setattr("aughor.ontology.column_config.load_index_disabled", lambda cid: set())
    schema = "TABLE: showroom.cars (120 rows) [car_id INTEGER, make STRING]"

    r = ar.resolve("revenue from Ferrari", schema=schema, db=_NoProbes(), connection_id="c1")

    assert [(b.table, b.column) for b in r.entity_bindings] == [("showroom.cars", "make")]


def test_the_top_values_reader_is_read_only_and_keyed_like_the_samples(monkeypatch):
    from aughor.tools import profile_cache
    monkeypatch.setattr(profile_cache, "_load", lambda: {
        "c1:fp1": {"columns": {"customers.country": {"table": "customers", "column": "country",
                                                     "top_values": ["Germany", "France"]},
                               "orders.id": {"table": "orders", "column": "id"}}},
        "c2:fp9": {"columns": {"x.y": {"table": "x", "column": "y", "top_values": ["z"]}}},
    })
    assert profile_cache.load_top_values("c1") == {("customers", "country"): ["Germany", "France"]}
