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


# ── The exploration WRITER — the one path #193 missed ─────────────────────────
# `explore.py::_learn_from_exploration` persists schema discoveries back to the glossary
# after every exploration run. It took a `conn_id` it never read and called `update_column`
# with no schema at all — so it LOOKED scoped while writing bare keys. The connection was
# never the scoping dimension: the glossary is one file keyed by qualified table name.

from types import SimpleNamespace                                        # noqa: E402

from aughor.agent.explore import _learn_from_exploration                 # noqa: E402


def _report(table: str, column: str, issue: str):
    """An ExplorationReport stand-in carrying one data-quality note (pass 1 — no LLM)."""
    return SimpleNamespace(
        data_quality_notes=[SimpleNamespace(table=table, column=column, issue=issue)],
        conclusion="",
    )


def test_exploration_writes_under_the_runs_own_schema(gloss):
    _learn_from_exploration(
        _report("orders", "status", "status is free text, not an enum — never group on it"),
        chain_summary="", schema="luxexperience")

    tables = load_glossary()["tables"]
    assert "luxexperience.orders" in tables
    assert "orders" not in tables                    # no bare key written


def test_two_schemas_exploring_the_same_table_name_no_longer_collide(gloss):
    """THE BUG, on the writer side. Both workspaces have an `orders`; exploring one used to
    append its caveats onto the other's entry, so a caveat learned about luxexperience data
    would be shown to an analyst querying creditcard."""
    _learn_from_exploration(_report("orders", "status", "luxexperience: status is free text"),
                            chain_summary="", schema="luxexperience")
    _learn_from_exploration(_report("orders", "status", "creditcard: status uses ISO codes"),
                            chain_summary="", schema="creditcard")

    tables = load_glossary()["tables"]
    lux = tables["luxexperience.orders"]["columns"]["status"]["caveats"]
    ccd = tables["creditcard.orders"]["columns"]["status"]["caveats"]
    assert "luxexperience: status is free text" in lux
    assert "creditcard" not in lux                   # neither leaked into the other
    assert "creditcard: status uses ISO codes" in ccd
    assert "luxexperience" not in ccd


def test_unscoped_exploration_keeps_the_legacy_bare_key(gloss):
    """An unscoped run has no schema to qualify with, and inventing one would file the
    caveat under the wrong table — so bare stays bare."""
    _learn_from_exploration(_report("orders", "status", "some caveat about this column"),
                            chain_summary="", schema="")
    assert "orders" in load_glossary()["tables"]


def test_an_already_qualified_table_name_is_not_double_qualified(gloss):
    """Pass 2 takes table names from an LLM, which often emits `schema.table` — that must
    not become `luxexperience.luxexperience.orders`."""
    _learn_from_exploration(
        _report("luxexperience.orders", "status", "a caveat long enough to be written"),
        chain_summary="", schema="luxexperience")
    assert "luxexperience.orders" in load_glossary()["tables"]


def test_an_existing_legacy_caveat_is_found_and_not_duplicated(gloss):
    """Tolerant read: a bare entry written before scoping existed must still be seen, so the
    same caveat is not appended a second time under the qualified key."""
    update_column("orders", "status", caveats="status is free text, not an enum", schema=None)
    written = _learn_from_exploration(
        _report("orders", "status", "status is free text, not an enum"),
        chain_summary="", schema="luxexperience")
    assert written == 0                              # recognised as already known


def test_caveats_accumulate_within_one_schema(gloss):
    """Scoping must not break the append behaviour the writer already had."""
    _learn_from_exploration(_report("orders", "status", "first caveat about this column"),
                            chain_summary="", schema="lux")
    _learn_from_exploration(_report("orders", "status", "second caveat about this column"),
                            chain_summary="", schema="lux")

    caveats = load_glossary()["tables"]["lux.orders"]["columns"]["status"]["caveats"]
    assert "first caveat" in caveats and "second caveat" in caveats


def test_the_call_site_passes_the_schema_not_the_connection(gloss):
    """Wiring ratchet. The fix is worthless if the caller reverts to handing over
    `connection_id` — the function would still look scoped and still write bare keys, with
    every test above passing. Guards the seam, not just the function."""
    from pathlib import Path
    src = Path("aughor/agent/explore.py").read_text()
    call = [ln.strip() for ln in src.splitlines() if "_learn_from_exploration(" in ln
            and not ln.lstrip().startswith(("#", "def "))]
    assert call, "call site not found — did the learning loop move?"
    assert all("scope_schema" in ln for ln in call), call
    assert all("connection_id" not in ln for ln in call), call
