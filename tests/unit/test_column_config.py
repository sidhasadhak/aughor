"""R11 — per-column {visible, sample, index} config (the Databricks column-configs analog).

Deterministic defaults from profiler facts, persisted as an editable YAML tree keyed
{conn}/{schema} (fingerprint-independent → rebuild-proof), human-override-wins, and
consumed by the schema render (prune), the value-annotation injector (sample), the
profiler's R5 capture gate (index) and the R8 doc tree (marking).

Fully hermetic: the store root is a per-test tmp dir (AUGHOR_COLUMN_CONFIG_ROOT),
in-memory DuckDB for the profiler, plain namespaces for profile ducks.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from aughor.db.connection import DuckDBConnection
from aughor.ontology.column_config import (
    ColumnFlags,
    apply_column_config_to_schema,
    default_flags,
    ensure_column_configs,
    hidden_columns,
    load_column_configs,
    load_index_disabled,
    load_table_config,
    sample_disabled,
    save_table_config,
    set_column_flags,
)
from aughor.tools.profiler import build_column_profiles


@pytest.fixture()
def store(monkeypatch, tmp_path):
    root = tmp_path / "colcfg"
    monkeypatch.setenv("AUGHOR_COLUMN_CONFIG_ROOT", str(root))
    return root


# ── deterministic default policy ─────────────────────────────────────────────

def test_default_entity_dimension_indexes_and_samples():
    f = default_flags(name="brand", dtype="VARCHAR", semantic_type="dimension")
    assert (f.visible, f.sample, f.index) == (True, True, True)
    assert f.source == "default"


def test_default_key_visible_but_never_indexed_or_sampled():
    f = default_flags(name="customer_id", dtype="VARCHAR", semantic_type="key", is_fk=True)
    assert f.visible is True
    assert f.sample is False
    assert f.index is False


def test_default_measure_visible_only():
    f = default_flags(name="amount", dtype="DOUBLE", semantic_type="measure")
    assert (f.visible, f.sample, f.index) == (True, False, False)


def test_default_dead_column_hidden():
    f = default_flags(name="legacy_col", dtype="VARCHAR", semantic_type="text", null_rate=1.0)
    assert f.visible is False


def test_default_freetext_blob_hidden_but_description_stays():
    blob = default_flags(name="comments", dtype="VARCHAR", semantic_type="text")
    assert blob.visible is False
    # `description`-style columns are often load-bearing — deliberately NOT hidden.
    desc = default_flags(name="description", dtype="VARCHAR", semantic_type="text")
    assert desc.visible is True


def test_default_index_gate_mirrors_r5():
    # entity-name-ish + text type → index; key suffix or non-text type → no index.
    assert default_flags(name="merchant_name", dtype="VARCHAR", semantic_type="text").index is True
    assert default_flags(name="brand_id", dtype="VARCHAR", semantic_type="key").index is False
    assert default_flags(name="brand", dtype="INTEGER", semantic_type="measure").index is False


# ── store: roundtrip, corruption tolerance ───────────────────────────────────

def test_store_roundtrip(store):
    save_table_config("c1", "main", "sales", {
        "brand": ColumnFlags(index=True),
        "notes": ColumnFlags(visible=False, sample=False),
    })
    loaded = load_table_config("c1", "main", "sales")
    assert loaded["brand"].index is True
    assert loaded["notes"].visible is False
    both = load_column_configs("c1", "main")
    assert both[("sales", "brand")].index is True
    assert both[("sales", "notes")].sample is False


def test_one_corrupt_file_does_not_blind_the_rest(store):
    save_table_config("c1", "main", "sales", {"brand": ColumnFlags(index=True)})
    bad = Path(str(store)) / "c1" / "main" / "broken.yaml"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("columns: [not, a, mapping")
    cfg = load_column_configs("c1", "main")
    assert ("sales", "brand") in cfg


# ── defaults refresh + human-override-wins ───────────────────────────────────

def _profiles():
    # The profiler-cache duck shape: {"table.column": profile-like}. Dicts exercise
    # the duck-typed adapter (attrs are what the real ColumnProfile provides).
    return {
        "sales.brand": dict(table="sales", column="brand", dtype="VARCHAR",
                            semantic_type="dimension", is_fk=False, null_rate=0.0),
        "sales.amount": dict(table="sales", column="amount", dtype="DOUBLE",
                             semantic_type="measure", is_fk=False, null_rate=0.0),
        "sales.comments": dict(table="sales", column="comments", dtype="VARCHAR",
                               semantic_type="text", is_fk=False, null_rate=0.1),
    }


def test_ensure_writes_defaults(store):
    eff = ensure_column_configs("c", "s", _profiles())
    assert eff[("sales", "brand")].index is True
    assert eff[("sales", "comments")].visible is False        # free-text blob hidden
    assert eff[("sales", "amount")].sample is False
    # persisted — a plain load sees the same decisions
    assert load_column_configs("c", "s")[("sales", "brand")].index is True


def test_human_edit_survives_defaults_refresh(store):
    ensure_column_configs("c", "s", _profiles())
    set_column_flags("c", "s", "sales", "comments", visible=True, note="ops needs it")
    eff = ensure_column_configs("c", "s", _profiles())        # refresh — must not clobber
    assert eff[("sales", "comments")].visible is True
    assert eff[("sales", "comments")].source == "human"
    assert eff[("sales", "comments")].note == "ops needs it"


def test_set_column_flags_partial_edit(store):
    ensure_column_configs("c", "s", _profiles())
    fl = set_column_flags("c", "s", "sales", "brand", index=False)
    assert fl.index is False
    assert fl.visible is True and fl.sample is True           # untouched flags keep values
    assert fl.source == "human"
    assert fl.edited_at


def test_stored_tables_absent_from_profiles_still_effective(store):
    set_column_flags("c", "s", "legacy_table", "old_col", visible=False)
    eff = ensure_column_configs("c", "s", _profiles())
    assert eff[("legacy_table", "old_col")].visible is False


def test_load_index_disabled_merges_schemas(store):
    set_column_flags("c", "s1", "sales", "brand", index=False)
    set_column_flags("c", "s2", "orders", "region", index=False)
    off = load_index_disabled("c")
    assert ("sales", "brand") in off
    assert ("orders", "region") in off


# ── consumer helpers + schema pruning (pure string transform) ────────────────

_SCHEMA = (
    "TABLE: main.sales  (300 rows)\n"
    "  id  INTEGER\n"
    "  brand  VARCHAR\n"
    "  notes  VARCHAR\n"
    "  status  VARCHAR\n"
    "  -- status  [open, closed]\n"
    "  -- notes  [a, b]\n"
    "\n"
    "DETECTED JOIN PATHS:\n"
    "sales.id = other.id"
)


def test_prune_hidden_column_and_sample_disabled_values():
    cfg = {
        ("sales", "notes"): ColumnFlags(visible=False, sample=False),
        ("sales", "status"): ColumnFlags(visible=True, sample=False),
    }
    out = apply_column_config_to_schema(_SCHEMA, cfg)
    assert "  notes  VARCHAR" not in out                      # hidden column line gone
    assert "-- notes" not in out                              # …and its value line
    assert "  status  VARCHAR" in out                         # visible column stays
    assert "-- status" not in out                             # …but sample=False strips values
    assert "  brand  VARCHAR" in out
    assert "  id  INTEGER" in out
    assert "DETECTED JOIN PATHS:" in out                      # non-TABLE sections untouched
    assert "sales.id = other.id" in out


def test_prune_matches_qualified_table_by_bare_name():
    cfg = {("sales", "brand"): ColumnFlags(visible=False)}    # bare key vs "main.sales" header
    out = apply_column_config_to_schema(_SCHEMA, cfg)
    assert "  brand  VARCHAR" not in out


def test_prune_all_visible_is_byte_identical():
    cfg = {("sales", "brand"): ColumnFlags()}                  # nothing hidden/disabled
    assert apply_column_config_to_schema(_SCHEMA, cfg) == _SCHEMA


def test_helper_sets():
    cfg = {
        ("t", "a"): ColumnFlags(visible=False),
        ("t", "b"): ColumnFlags(sample=False),
        ("t", "c"): ColumnFlags(),
    }
    assert hidden_columns(cfg) == {("t", "a")}
    assert sample_disabled(cfg) == {("t", "a"), ("t", "b")}   # hidden implies no sampling


# ── inject_value_annotations honours sample_disabled ─────────────────────────

def test_inject_value_annotations_respects_sample_disabled():
    from aughor.tools.schema import inject_value_annotations
    schema = "TABLE: sales  (10 rows)\n  status  VARCHAR"
    cp = {"sales.status": SimpleNamespace(
        top_values=["open", "closed"], is_low_cardinality=True,
        is_fk=False, semantic_type="dimension")}
    assert "-- [open, closed]" in inject_value_annotations(schema, cp)
    out = inject_value_annotations(schema, cp, sample_disabled={"sales.status"})
    assert "-- [open, closed]" not in out


# ── profiler: the R5 capture gate consults the config ────────────────────────

def _duck(setup: list[str]):
    c = DuckDBConnection.__new__(DuckDBConnection)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = "test"
    c._schema_name = None
    for s in setup:
        c._conn.execute(s)
    return c


def _by_col(profiles):
    return {p.column: p for p in profiles}


def test_profiler_index_config_overrides_r5_gate():
    c = _duck(["CREATE TABLE t (id INT, brand VARCHAR, notes VARCHAR)"])
    c._conn.execute(
        "INSERT INTO t SELECT i, 'Brand' || CAST(i % 60 AS VARCHAR), "
        "'note' || CAST(i % 60 AS VARCHAR) FROM range(300) tbl(i)"
    )
    cols = [("id", "INTEGER"), ("brand", "VARCHAR"), ("notes", "VARCHAR")]

    # No config → the built-in R5 gate: entity-ish brand sampled, free-text notes not.
    p = _by_col(build_column_profiles(c, "t", cols, fk_cols={"id"}, row_count=300))
    assert p["brand"].value_sample is not None
    assert p["notes"].value_sample is None

    # Config wins both ways: human excludes brand, includes notes.
    p = _by_col(build_column_profiles(
        c, "t", cols, fk_cols={"id"}, row_count=300,
        index_config={"brand": False, "notes": True}))
    assert p["brand"].value_sample is None
    assert p["notes"].value_sample is not None


def test_profiler_index_config_cannot_break_cardinality_band():
    # `index: true` widens the NAME gate but never the cardinality band — a low-card
    # column stays on the top_values path even when force-included.
    c = _duck(["CREATE TABLE t (id INT, status VARCHAR)"])
    c._conn.execute(
        "INSERT INTO t SELECT i, 'S' || CAST(i % 5 AS VARCHAR) FROM range(100) tbl(i)"
    )
    p = _by_col(build_column_profiles(
        c, "t", [("id", "INTEGER"), ("status", "VARCHAR")], fk_cols={"id"},
        row_count=100, index_config={"status": True}))
    assert p["status"].value_sample is None
    assert p["status"].top_values


# ── the wired path: apply_schema_enrichment prunes only when the flag is on ──

def test_apply_schema_enrichment_prunes_only_when_flag_on(monkeypatch, store):
    from aughor.tools.schema import apply_schema_enrichment
    set_column_flags("connX", "default", "sales", "notes", visible=False)
    raw = "TABLE: sales  (10 rows)\n  id  INTEGER\n  notes  VARCHAR"

    off = apply_schema_enrichment(raw, connection_id="connX")
    assert "  notes  VARCHAR" in off                          # flag off → byte-identical schema body

    monkeypatch.setenv("AUGHOR_ONTOLOGY_COLUMN_CONFIG", "1")
    on = apply_schema_enrichment(raw, connection_id="connX")
    assert "  notes  VARCHAR" not in on
    assert "  id  INTEGER" in on


# ── doc tree: column nodes carry the config marks ────────────────────────────

def test_doctree_stamps_config_flags():
    from aughor.ontology.doctree import build_doc_tree
    from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph
    ent = OntologyEntity(
        id="sales", display_name="Sales", source_tables=["sales"],
        identity_key="id", grain_verified=True,
        properties={
            "brand": EntityProperty(name="brand", data_type="VARCHAR", semantic_type="dimension"),
            "notes": EntityProperty(name="notes", data_type="VARCHAR", semantic_type="text"),
        },
    )
    graph = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="f",
                          entities={"sales": ent})
    cfg = {
        ("sales", "notes"): ColumnFlags(visible=False, sample=False),
        ("sales", "brand"): ColumnFlags(index=True),
    }
    tree = build_doc_tree(graph, column_config=cfg)
    notes = tree.nodes["s.sales.notes"]
    assert notes.facts["visible"] is False
    assert "hidden from agent prompts" in notes.summary
    assert tree.nodes["s.sales.brand"].facts["index"] is True

    # No config → facts keep their pre-R11 shape (no marker keys, unchanged hashes).
    bare = build_doc_tree(graph)
    assert "visible" not in bare.nodes["s.sales.brand"].facts


# ── REST surface ─────────────────────────────────────────────────────────────

def test_column_config_endpoints_roundtrip(client, store):
    r = client.get("/ontology/column-config", params={"connection_id": "fixture"})
    assert r.status_code == 200
    assert r.json()["tables"] == {}

    r = client.put(
        "/ontology/column-config",
        params={"connection_id": "fixture"},
        json={"table": "sales", "column": "notes", "visible": False, "note": "noise"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["flags"]["visible"] is False
    assert body["flags"]["source"] == "human"

    r = client.get("/ontology/column-config", params={"connection_id": "fixture"})
    assert r.json()["tables"]["sales"]["notes"]["visible"] is False


def test_column_config_put_requires_a_flag(client, store):
    r = client.put(
        "/ontology/column-config",
        params={"connection_id": "fixture"},
        json={"table": "sales", "column": "notes"},
    )
    assert r.status_code == 422
