"""Tests for sharded-table schema compression (aughor/tools/schema_linker.compress_schema).

Contract: collapse families of dated/sharded tables to one representative + a count note, keep every
non-sharded table in full, and be a no-op on ordinary schemas (recall-safe wide-warehouse lever).
"""
from __future__ import annotations

from aughor.tools.schema_linker import compress_schema, _shard_stem, link_schema


def _sharded_schema(n=12):
    rows = [f"TABLE: events_2021_{m:02d} [event_id INT, ts TIMESTAMP, user STRING]" for m in range(1, n + 1)]
    rows.append("TABLE: users [user_id INT, name STRING]")          # non-sharded — must survive
    return "\n".join(rows)


def test_stem_strips_shard_suffixes():
    assert _shard_stem("events_2021_01") == "events"
    assert _shard_stem("GA_SESSIONS_20160801") == "ga_sessions"
    assert _shard_stem("TCGA_HG19_DATA_V0") == "tcga_hg19_data"
    assert _shard_stem("dataset.events_2023_12") == "events"
    assert _shard_stem("orders") == "orders"                        # nothing to strip


def test_collapses_sharded_family_to_one_representative():
    out = compress_schema(_sharded_schema(12))
    # exactly one representative events table remains, plus the count note
    assert out.count("TABLE: events_2021_") == 1
    assert "+ 11 more sharded tables" in out
    # the representative keeps its full column list
    assert "event_id INT" in out


def test_non_sharded_table_survives_in_full():
    out = compress_schema(_sharded_schema(12))
    assert "TABLE: users [user_id INT, name STRING]" in out         # never collapsed


def test_size_reduction():
    full = _sharded_schema(12)
    out = compress_schema(full)
    assert len(out.splitlines()) < len(full.splitlines())           # genuinely smaller


def test_noop_on_ordinary_schema():
    schema = ("TABLE: orders [id INT, total NUMERIC]\n"
              "TABLE: customers [id INT, name STRING]\n"
              "TABLE: products [id INT, sku STRING]")
    assert compress_schema(schema) == schema                        # no shard family ⇒ unchanged


def test_small_family_below_threshold_not_collapsed():
    schema = ("TABLE: events_2021_01 [a INT]\n"
              "TABLE: events_2021_02 [a INT]")                       # only 2 < min_group(3)
    assert compress_schema(schema) == schema


def test_link_schema_applies_compression():
    """The wired path: link_schema compresses before keyword-linking, so a question about events
    returns the representative, not 12 partitions."""
    out = link_schema("how many events did users trigger", _sharded_schema(12))
    assert out.count("TABLE: events_2021_") <= 1
