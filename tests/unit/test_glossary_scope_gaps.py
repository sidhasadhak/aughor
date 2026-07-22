"""The three remaining glossary-scoping gaps #193 documented but did not close.

Each is the same shape as the bug #193 fixed — a store keyed without the dimension that
distinguishes its owners — surviving in a different layer:

  1. the Qdrant schema index keyed points by table alone, so two connections holding the
     same qualified table wrote ONE point and the later index replaced the earlier's
     embedding; searches were unfiltered, so a sibling's tables also consumed top-k slots
     that the schema filter then dropped — silently returning fewer tables than requested;
  2. the dbt merge layer keyed bare + lowercased, so a dbt annotation could never meet a
     qualified YAML entry: the merge unions on exact keys, and `orders` vs `analytics.orders`
     layered as two unrelated tables;
  3. the autoseed fingerprint hashed structure only, so two schemas built from the same DDL
     shared one "fully seeded" marker and the second skipped seeding entirely.
"""
from __future__ import annotations

import pytest

from aughor.db.schema_cache import compute_fingerprint, scope_key
from aughor.semantic import retriever
from aughor.semantic.dbt import _table_key
from aughor.semantic.glossary import _align_keys


# ── Gap 3: the autoseed fingerprint ───────────────────────────────────────────

def test_same_structure_in_two_scopes_no_longer_collides():
    """THE BUG. A dev copy, a second tenant, or a sibling schema built from the same DDL
    hashed identically — so the second inherited the first's "seeded" marker."""
    blocks = {"orders": "id\nstatus\n", "customers": "id\nname\n"}
    assert (compute_fingerprint(blocks, scope_key("connA", "lux"))
            != compute_fingerprint(blocks, scope_key("connB", "lux")))
    assert (compute_fingerprint(blocks, scope_key("conn", "lux"))
            != compute_fingerprint(blocks, scope_key("conn", "creditcard")))


def test_fingerprint_is_stable_for_one_scope():
    """It must still be a CACHE: same schema, same scope ⇒ same hash, or the fast-path
    never hits and every reconnect pays the seeding LLM calls again."""
    blocks = {"orders": "id\nstatus\n"}
    assert (compute_fingerprint(blocks, scope_key("c", "s"))
            == compute_fingerprint(blocks, scope_key("c", "s")))


def test_structure_still_matters_within_a_scope():
    """Scope is added to the hash, not substituted for it — a changed schema must still
    invalidate, otherwise a new table would never get seeded."""
    assert (compute_fingerprint({"orders": "id\n"}, scope_key("c", "s"))
            != compute_fingerprint({"orders": "id\nstatus\n"}, scope_key("c", "s")))


def test_unscoped_fingerprint_keeps_the_legacy_hash():
    blocks = {"orders": "id\n"}
    assert compute_fingerprint(blocks) == compute_fingerprint(blocks, "")


def test_scope_key_is_empty_only_when_nothing_is_known():
    assert scope_key("", "") == ""
    assert scope_key(None, None) == ""
    assert scope_key("c", "") and scope_key("", "s")
    assert scope_key("a", "bc") != scope_key("ab", "c")   # separated, not concatenated


# ── Gap 2: the dbt merge layer ────────────────────────────────────────────────

def test_dbt_key_is_qualified_by_the_schema_dbt_declares():
    assert _table_key({"name": "Orders", "schema": "Analytics"}) == "analytics.orders"


def test_dbt_key_prefers_the_alias_the_warehouse_actually_holds():
    """`stg_orders` materialised as `orders` must be keyed by what the schema reader sees."""
    assert _table_key({"name": "stg_orders", "alias": "orders",
                       "schema": "analytics"}) == "analytics.orders"


def test_dbt_key_stays_bare_when_the_manifest_declares_no_schema():
    assert _table_key({"name": "Orders"}) == "orders"
    assert _table_key({}) == ""


def test_bare_dbt_entry_reaches_a_qualified_yaml_entry():
    """THE BUG. The merge unions on exact keys, so a dbt `orders` never layered onto the
    `luxexperience.orders` an analyst actually reads — the description silently vanished."""
    assert list(_align_keys({"orders": {"description": "d"}}, {"luxexperience.orders"})) \
        == ["luxexperience.orders"]


def test_alignment_refuses_to_guess_between_two_candidate_schemas():
    """With `beauty.orders` AND `ecommerce.orders` present, a bare `orders` belongs to
    either. Attaching it to one would describe the wrong table — worse than not merging."""
    aligned = _align_keys({"orders": {"description": "d"}}, {"beauty.orders", "ecommerce.orders"})
    assert list(aligned) == ["orders"]


def test_alignment_is_case_tolerant():
    assert list(_align_keys({"orders": {}}, {"Analytics.Orders"})) == ["Analytics.Orders"]


def test_an_exactly_matching_key_is_untouched():
    assert list(_align_keys({"lux.orders": {}}, {"lux.orders"})) == ["lux.orders"]


def test_a_dbt_only_table_keeps_its_own_key():
    assert list(_align_keys({"lux.audit_log": {}}, {"lux.orders"})) == ["lux.audit_log"]


def test_dbt_description_actually_survives_the_merge(tmp_path, monkeypatch):
    """End to end through `load_merged_glossary`: the layering, not just the alignment."""
    import yaml as _yaml

    from aughor.semantic import glossary as G

    gpath = tmp_path / "glossary.yaml"
    gpath.write_text(_yaml.dump({"tables": {"lux.orders": {"grain": "one row per order"}}}))
    monkeypatch.setattr(G, "_load_raw", lambda path=None: _yaml.safe_load(gpath.read_text()))
    monkeypatch.setattr("aughor.semantic.dbt.load_dbt_glossary",
                        lambda: {"tables": {"orders": {"description": "from dbt"}}})

    tables = G.load_merged_glossary()["tables"]
    assert "orders" not in tables                      # not a second, unrelated table
    assert tables["lux.orders"]["description"] == "from dbt"
    assert tables["lux.orders"]["grain"] == "one row per order"   # YAML kept


def test_manual_yaml_still_outranks_dbt(tmp_path, monkeypatch):
    """Alignment must not disturb the documented precedence: manual > dbt > auto-seed."""
    import yaml as _yaml

    from aughor.semantic import glossary as G

    gpath = tmp_path / "glossary.yaml"
    gpath.write_text(_yaml.dump({"tables": {"lux.orders": {"description": "hand written"}}}))
    monkeypatch.setattr(G, "_load_raw", lambda path=None: _yaml.safe_load(gpath.read_text()))
    monkeypatch.setattr("aughor.semantic.dbt.load_dbt_glossary",
                        lambda: {"tables": {"orders": {"description": "from dbt"}}})

    assert G.load_merged_glossary()["tables"]["lux.orders"]["description"] == "hand written"


# ── Gap 1: the Qdrant schema index ────────────────────────────────────────────

def test_retriever_scope_key_separates_connections():
    assert retriever.scope_key("connA", "lux") != retriever.scope_key("connB", "lux")
    assert retriever.scope_key("", "") == ""


def test_no_filter_when_unscoped_so_legacy_callers_are_unchanged():
    assert retriever._scope_filter("") is None


def test_a_scoped_search_is_filtered():
    f = retriever._scope_filter("connA|lux")
    if f is None:
        pytest.skip("qdrant_client not installed")
    assert "scope" in str(f) and "connA|lux" in str(f)


def _fake_index(monkeypatch):
    """Capture what would be written to Qdrant."""
    captured: dict = {}
    monkeypatch.setattr("aughor.semantic.embedder.embed", lambda texts: [[0.0]] * len(texts))
    monkeypatch.setattr("aughor.semantic.vector_store.ensure_collection", lambda *a, **k: None)
    monkeypatch.setattr("aughor.semantic.vector_store.upsert",
                        lambda coll, points: captured.update(points=points))
    return captured


def test_indexed_points_carry_their_scope(monkeypatch):
    captured = _fake_index(monkeypatch)
    monkeypatch.setattr("aughor.semantic.glossary.load_merged_glossary",
                        lambda path=None: {"tables": {"lux.orders": {"description": "d"}}})

    n = retriever.build_schema_index(connection_id="connA", schema_name="lux")
    assert n == 1
    point = captured["points"][0]
    assert point["payload"]["scope"] == "connA|lux"
    assert point["id"].startswith("connA|lux|")


def test_two_connections_no_longer_write_the_same_point(monkeypatch):
    """THE BUG. Identical qualified table, two connections — one point id, so indexing the
    second silently replaced the first's embedding and retrieval ranked by the wrong text."""
    monkeypatch.setattr("aughor.semantic.glossary.load_merged_glossary",
                        lambda path=None: {"tables": {"lux.orders": {"description": "d"}}})

    captured = _fake_index(monkeypatch)
    retriever.build_schema_index(connection_id="connA", schema_name="lux")
    id_a = captured["points"][0]["id"]

    captured = _fake_index(monkeypatch)
    retriever.build_schema_index(connection_id="connB", schema_name="lux")
    id_b = captured["points"][0]["id"]

    assert id_a != id_b


def test_retrieval_passes_the_scope_filter_to_qdrant(monkeypatch):
    """Wiring: the filter is worthless if the search never receives it."""
    seen: dict = {}

    monkeypatch.setattr("aughor.semantic.embedder.embed_one", lambda q: [0.0])
    monkeypatch.setattr("aughor.semantic.vector_store.collection_count", lambda c: 5)

    def fake_search(collection, vector, top_k=10, query_filter=None):
        seen["filter"] = query_filter
        return [{"score": 1.0, "payload": {"table": "lux.orders"}}]

    monkeypatch.setattr("aughor.semantic.vector_store.search", fake_search)

    schema_str = "".join(f"TABLE: t{i}\n  id INTEGER\n" for i in range(20))
    retriever.retrieve_relevant_schema("why did orders drop", schema_str,
                                       connection_id="connA", schema_name="lux")
    assert seen["filter"] is not None


def test_small_schemas_still_skip_retrieval_entirely(monkeypatch):
    """The threshold short-circuit must survive the new parameters — below it, no Qdrant
    call happens at all and the full schema is returned untouched."""
    def boom(*a, **k):                                   # noqa: ARG001
        raise AssertionError("retrieval must not run below TABLE_THRESHOLD")

    monkeypatch.setattr("aughor.semantic.embedder.embed_one", boom)
    small = "TABLE: orders\n  id INTEGER\n"
    assert retriever.retrieve_relevant_schema("q", small, connection_id="c",
                                              schema_name="s") == small
