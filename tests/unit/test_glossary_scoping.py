"""The glossary is scoped per schema — one schema's comment can't overwrite another's.

The store is keyed by whatever the connector's ``TABLE:`` header carried, and the connectors
disagree: DuckDB qualifies (``analytics.orders``), Postgres / SQLite / Snowflake / MySQL /
BigQuery emit bare names. So the live file holds BOTH forms — 81 bare keys and 70 qualified,
with 61 colliding leaves (``orders`` alone had five competing entries). The lookup was an
exact-string ``.get()``, so:

  * a bare header never found a qualified entry, and vice versa — the schema dimension was
    already half-present in the data and simply invisible to the reader; and
  * every seed wrote under whichever form the header used, so exploring one schema silently
    replaced a same-named table's description in another.

Fix: canonical on WRITE (qualify with the schema when known), tolerant on READ (exact first,
then schema-tolerant via ``tools.table_names.resolve_in``). A bare key still answers for any
schema — that is the migration path for the 81 unqualified entries already on disk — but a
QUALIFIED key answers only for its own.
"""
from __future__ import annotations

import pytest

from aughor.semantic.glossary import (
    apply_glossary,
    canonical_key,
    lookup_table,
    load_glossary,
    update_column,
    update_table,
)

META = {
    "orders":            {"description": "bare fallback"},
    "beauty.orders":     {"description": "beauty orders"},
    "ecommerce.orders":  {"description": "ecommerce orders"},
    "analytics.signups": {"description": "analytics signups"},
}


# ── Read: tolerant, but never across schemas ──────────────────────────────────


def test_bare_header_resolves_to_the_callers_schema():
    """The core fix: same table name, two schemas, two different answers."""
    assert lookup_table(META, "orders", "beauty")["description"] == "beauty orders"
    assert lookup_table(META, "orders", "ecommerce")["description"] == "ecommerce orders"


def test_qualified_entry_never_answers_for_another_schema():
    """`beauty.orders` must not describe `ecommerce.orders`. This is the leak."""
    assert lookup_table({"beauty.orders": META["beauty.orders"]}, "orders", "ecommerce") == {}
    assert lookup_table(META, "ecommerce.orders")["description"] == "ecommerce orders"


def test_bare_key_still_answers_for_any_schema():
    """The migration path: 81 unqualified entries are already on disk and must keep working
    for schemas that have no scoped entry of their own."""
    assert lookup_table(META, "orders", "netflix")["description"] == "bare fallback"


def test_qualified_header_against_bare_key():
    """The other half of the mismatch — a qualified header used to miss a bare entry."""
    assert lookup_table({"signups": {"description": "bare"}}, "analytics.signups")["description"] == "bare"


def test_absent_table_is_empty_not_a_neighbour():
    assert lookup_table(META, "widgets", "beauty") == {}
    assert lookup_table({}, "orders", "beauty") == {}


# ── Write: canonical ──────────────────────────────────────────────────────────


def test_canonical_key_qualifies_only_when_it_can():
    assert canonical_key("orders", "beauty") == "beauty.orders"
    assert canonical_key("beauty.orders", "other") == "beauty.orders"   # already qualified: untouched
    assert canonical_key("orders", None) == "orders"                    # unknown schema: unchanged


@pytest.fixture
def gloss(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(tmp_path / "glossary.yaml"))
    return tmp_path / "glossary.yaml"


def test_two_schemas_no_longer_clobber_each_other(gloss):
    """THE REPORTED BUG. Exploring luxexperience overwrote the Brazilian e-commerce
    descriptions for order_items / products / brands, because both wrote the same key."""
    update_table("orders", description="beauty orders", schema="beauty")
    update_table("orders", description="ecommerce orders", schema="ecommerce")

    tables = load_glossary()["tables"]
    assert tables["beauty.orders"]["description"] == "beauty orders"
    assert tables["ecommerce.orders"]["description"] == "ecommerce orders"
    assert lookup_table(tables, "orders", "beauty")["description"] == "beauty orders"


def test_column_writes_are_scoped_too(gloss):
    update_column("orders", "status", description="beauty status", schema="beauty")
    update_column("orders", "status", description="ecommerce status", schema="ecommerce")

    tables = load_glossary()["tables"]
    assert tables["beauty.orders"]["columns"]["status"]["description"] == "beauty status"
    assert tables["ecommerce.orders"]["columns"]["status"]["description"] == "ecommerce status"


def test_unscoped_write_keeps_the_legacy_key(gloss):
    """No schema in scope → unchanged behaviour, so existing callers aren't broken."""
    update_table("orders", description="legacy", schema=None)
    assert "orders" in load_glossary()["tables"]


# ── The enrichment path end to end ────────────────────────────────────────────

SCHEMA_STR = "TABLE: orders\n  id  INTEGER\n  status  VARCHAR\n"


def test_apply_glossary_annotates_from_the_right_schema(gloss):
    update_table("orders", description="beauty orders", schema="beauty")
    update_table("orders", description="ecommerce orders", schema="ecommerce")

    assert "beauty orders" in apply_glossary(SCHEMA_STR, schema="beauty")
    assert "ecommerce orders" not in apply_glossary(SCHEMA_STR, schema="beauty")
    assert "ecommerce orders" in apply_glossary(SCHEMA_STR, schema="ecommerce")


def test_apply_glossary_without_a_schema_is_unchanged(gloss):
    """Byte-identical for callers that have no schema — the whole change is additive."""
    update_table("orders", description="legacy", schema=None)
    assert "legacy" in apply_glossary(SCHEMA_STR)


def test_apply_glossary_column_annotations_are_scoped(gloss):
    update_column("orders", "status", description="beauty status", schema="beauty")
    update_column("orders", "status", description="ecommerce status", schema="ecommerce")

    out = apply_glossary(SCHEMA_STR, schema="beauty")
    assert "beauty status" in out
    assert "ecommerce status" not in out


# ── The consumer that a re-key would have broken ──────────────────────────────
#
# `retriever._filter_schema` keeps only the TABLE: blocks the vector search returned.
# `keep_tables` holds GLOSSARY keys (now qualified) while the header is whatever the
# connector emitted (often bare) — an exact-string check would drop the block entirely and
# tell the model the table doesn't exist. Far worse than over-inclusion.

RETRIEVAL_SCHEMA = "TABLE: orders\n  id  INTEGER\n\nTABLE: widgets\n  id  INTEGER\n"


def test_qualified_index_still_keeps_a_bare_header_block():
    from aughor.semantic.retriever import _filter_schema

    out = _filter_schema(RETRIEVAL_SCHEMA, {"beauty.orders"})
    assert "TABLE: orders" in out
    assert "TABLE: widgets" not in out


def test_filter_never_keeps_another_schemas_same_named_table():
    from aughor.semantic.retriever import _filter_schema

    # Only `other.widgets` was retrieved; the bare `widgets` header belongs to a different
    # schema in this run, so nothing matches → the safety net returns the full schema
    # rather than a wrong subset.
    out = _filter_schema("TABLE: beauty.widgets\n  id  INTEGER\n", {"other.widgets"})
    assert out == "TABLE: beauty.widgets\n  id  INTEGER\n"


def test_bare_index_and_bare_header_still_match():
    from aughor.semantic.retriever import _filter_schema

    assert "TABLE: orders" in _filter_schema(RETRIEVAL_SCHEMA, {"orders"})
