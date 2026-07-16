"""R14 — query popularity as a unified notability signal.

Mines real query history (SQL-examples store + task_history span inputs) into a
persisted per-table / per-column counter, consumed by: R11 column-config default
protection, R8 doc-tree table facts + ranking, the overview learned-prior fold,
and the /suggestions prompt. All consumption flag-gated (`obs.popularity`).

Hermetic: per-test tmp SQLite via AUGHOR_POPULARITY_DB; SQL corpora injected.
"""
from __future__ import annotations

import pytest

from aughor.sql.popularity import (
    PopularitySignal,
    load_popularity,
    merge_popularity_into_priors,
    mine_popularity,
    most_queried_block,
    refresh_popularity,
    save_popularity,
)


@pytest.fixture()
def popdb(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_POPULARITY_DB", str(tmp_path / "popularity.db"))
    return tmp_path / "popularity.db"


_CORPUS = [
    "SELECT brand, SUM(amount) FROM sales GROUP BY brand",
    "SELECT s.brand, o.region FROM sales s JOIN orders o ON s.id = o.sale_id",
    "SELECT region FROM orders WHERE region = 'EU'",
]


# ── mining ───────────────────────────────────────────────────────────────────

def test_mine_popularity_counts_tables_and_columns():
    sig = mine_popularity("c1", sqls=_CORPUS)
    assert sig.n_queries == 3
    assert sig.table_counts["sales"] == 2
    assert sig.table_counts["orders"] == 2
    assert sig.column_counts["sales.brand"] >= 2          # occurrences across queries
    assert sig.column_counts["orders.region"] >= 1


def test_mine_popularity_empty_history_is_empty_signal():
    sig = mine_popularity("c1", sqls=[])
    assert sig.table_counts == {} and sig.column_counts == {} and sig.n_queries == 0


def test_mine_popularity_skips_unparseable_sql():
    sig = mine_popularity("c1", sqls=["NOT SQL AT ALL ((", _CORPUS[0]])
    assert sig.table_counts.get("sales") == 1


# ── store roundtrip ──────────────────────────────────────────────────────────

def test_save_load_roundtrip(popdb):
    save_popularity(PopularitySignal(
        connection_id="c1", table_counts={"sales": 5}, column_counts={"sales.brand": 3},
        n_queries=5))
    pop = load_popularity("c1")
    assert pop["table"] == {"sales": 5}
    assert pop["column"] == {"sales.brand": 3}
    assert load_popularity("other")["table"] == {}        # keyed per connection


def test_refresh_replaces_stale_counts(popdb):
    save_popularity(PopularitySignal(connection_id="c1", table_counts={"gone": 9}))
    import aughor.sql.popularity as P
    sig = P.mine_popularity("c1", sqls=_CORPUS)
    save_popularity(sig)
    pop = load_popularity("c1")
    assert "gone" not in pop["table"]                     # replace, not accumulate
    assert pop["table"]["sales"] == 2


def test_refresh_popularity_uses_history_sources(popdb, monkeypatch):
    monkeypatch.setattr("aughor.sql.query_log_miner.collect_logged_sql",
                        lambda cid, limit=5000: list(_CORPUS))
    sig = refresh_popularity("c1")
    assert sig.table_counts["sales"] == 2
    assert load_popularity("c1")["table"]["sales"] == 2


# ── consumer helpers ─────────────────────────────────────────────────────────

def test_merge_into_priors_sums_with_drills(popdb):
    save_popularity(PopularitySignal(connection_id="c1", table_counts={"sales": 4}))
    priors = {"lens": {"outlier": 2}, "table": {"sales": 1, "orders": 2}}
    merged = merge_popularity_into_priors(priors, "c1")
    assert merged["table"] == {"sales": 5, "orders": 2}   # drills + queries
    assert merged["lens"] == {"outlier": 2}
    assert priors["table"] == {"sales": 1, "orders": 2}   # input never mutated


def test_merge_into_priors_noop_when_nothing_mined(popdb):
    priors = {"lens": {}, "table": {"sales": 1}}
    assert merge_popularity_into_priors(priors, "c-none") is priors


def test_most_queried_block(popdb):
    save_popularity(PopularitySignal(
        connection_id="c1", table_counts={"sales": 9, "orders": 3, "audit_log": 1}))
    block = most_queried_block("c1", top=2)
    assert "sales" in block and "orders" in block
    assert "audit_log" not in block                        # top-N respected
    assert most_queried_block("c-none") == ""


# ── R11 column-config protection: a queried column never default-hides ───────

def test_popularity_protects_queried_column_from_default_hide(popdb):
    from aughor.ontology.column_config import default_flags
    hidden = default_flags(name="comments", dtype="VARCHAR", semantic_type="text")
    assert hidden.visible is False                        # blob default (R11)
    kept = default_flags(name="comments", dtype="VARCHAR", semantic_type="text",
                         popularity=4)
    assert kept.visible is True                           # queried → protected
    # popularity never *hides* anything
    plain = default_flags(name="brand", dtype="VARCHAR", semantic_type="dimension",
                          popularity=0)
    assert plain.visible is True


def test_defaults_from_profiles_threads_popularity(popdb):
    from aughor.ontology.column_config import defaults_from_profiles
    profiles = {"sales.comments": dict(table="sales", column="comments", dtype="VARCHAR",
                                       semantic_type="text", is_fk=False, null_rate=0.0)}
    plain = defaults_from_profiles(profiles)
    assert plain["sales"]["comments"].visible is False
    prot = defaults_from_profiles(profiles, column_popularity={"sales.comments": 2})
    assert prot["sales"]["comments"].visible is True


# ── R8 doc-tree: table facts carry query_popularity ──────────────────────────

def test_doctree_table_facts_carry_popularity():
    from aughor.ontology.doctree import build_doc_tree
    from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph
    ent = OntologyEntity(
        id="sales", display_name="Sales", source_tables=["sales"],
        identity_key="id", grain_verified=True,
        properties={"brand": EntityProperty(name="brand", data_type="VARCHAR",
                                            semantic_type="dimension")})
    graph = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="f",
                          entities={"sales": ent})
    tree = build_doc_tree(graph, table_stats={"sales": {"row_count": 10,
                                                        "query_popularity": 7}})
    assert tree.nodes["s.sales"].facts["query_popularity"] == 7
