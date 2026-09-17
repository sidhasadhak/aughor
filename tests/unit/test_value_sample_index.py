"""R5 — a persisted, per-connection high-cardinality value index.

Low-card (≤30 distinct) dimensions already ship their values to the coder via
top_values. The "Mytheresa"-class entity columns (brands/merchants/categories)
sit above that cap, so binding them used to live-probe the warehouse on every
question. Now the profiler persists their distinct set (value_sample), and entity
resolution binds from it OFFLINE — a hit skips the live probe; a miss still defers
to the probe (staleness-safe; never a false "absent").

Fully hermetic: in-memory DuckDB for the producer; canned dicts + a fake db for
the store and consumer (no touching data/schema_profiles.json).
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from aughor.db.connection import MAX_ROWS, DatabaseConnection, DuckDBConnection
from aughor.tools.profiler import ColumnProfile, build_column_profiles
import aughor.tools.profiler as profiler
import aughor.tools.profile_cache as pc
from aughor.semantic import answer_resolution as R


# ─────────────────────────── producer (profiler) ─────────────────────────────

def _duck(setup: list[str], cls=DuckDBConnection):
    c = cls.__new__(cls)
    c._path = Path(":memory:")
    c._conn = duckdb.connect(":memory:")
    c._connection_id = "test"
    c._schema_name = None
    for s in setup:
        c._conn.execute(s)
    return c


def _by_col(profiles):
    return {p.column: p for p in profiles}


def test_highcard_entity_dim_gets_full_value_sample():
    brands = [f"Brand{i:03d}" for i in range(60)]  # 60 distinct → above the low-card cap
    c = _duck(["CREATE TABLE sales (id INT, brand VARCHAR, status VARCHAR, amount DOUBLE)"])
    rows = ",".join(
        f"({i},'{brands[i % 60]}','{'open' if i % 2 else 'closed'}',{i * 1.5})"
        for i in range(300)
    )
    c._conn.execute(f"INSERT INTO sales VALUES {rows}")
    cols = [("id", "INTEGER"), ("brand", "VARCHAR"), ("status", "VARCHAR"), ("amount", "DOUBLE")]
    p = _by_col(build_column_profiles(c, "sales", cols, fk_cols={"id"}, row_count=300))

    assert p["brand"].value_sample is not None
    assert set(p["brand"].value_sample) == set(brands)       # the complete distinct set
    assert p["status"].value_sample is None                  # low-card → top_values path
    assert p["status"].top_values
    assert p["amount"].value_sample is None                  # numeric, not a dimension


def test_highcard_non_entity_string_is_not_sampled():
    """A high-card string that isn't entity-name-ish (free text) is left alone."""
    c = _duck(["CREATE TABLE t (id INT, notes VARCHAR)"])
    c._conn.execute(
        "INSERT INTO t VALUES " + ",".join(f"({i},'free text {i}')" for i in range(80))
    )
    p = _by_col(build_column_profiles(c, "t", [("id", "INTEGER"), ("notes", "VARCHAR")],
                                      fk_cols={"id"}, row_count=80))
    assert p["notes"].value_sample is None


def test_value_sample_respects_max_distinct_cap(monkeypatch):
    monkeypatch.setattr(profiler, "_VALUE_SAMPLE_MAX_DISTINCT", 35)   # 30 < cap keeps the range valid
    c = _duck(["CREATE TABLE s (id INT, brand VARCHAR)"])
    c._conn.execute(
        "INSERT INTO s VALUES " + ",".join(f"({i},'B{i % 40:02d}')" for i in range(120))
    )  # 40 distinct > cap 35
    p = _by_col(build_column_profiles(c, "s", [("id", "INTEGER"), ("brand", "VARCHAR")],
                                      fk_cols={"id"}, row_count=120))
    assert p["brand"].value_sample is None


# The caps below are the shipped ones. The test above monkeypatches the cap to 35 over 40 values, which
# sits under the connection's 500-row answer cap and so never met it.

def _cities(n_distinct: int, cls=DuckDBConnection):
    """`city` holds `City 0` … `City {n-1}`, each on two rows, so COUNT(DISTINCT) reads it exactly."""
    c = _duck([f"CREATE TABLE t AS SELECT i AS id, 'City ' || (i % {n_distinct}) AS city "
               f"FROM range({2 * n_distinct}) r(i)"], cls=cls)
    return c, 2 * n_distinct


def _city_profile(c, row_count: int, fast_stats=None) -> ColumnProfile:
    return _by_col(build_column_profiles(c, "t", [("id", "BIGINT"), ("city", "VARCHAR")], fk_cols={"id"},
                                         row_count=row_count, fast_stats=fast_stats))["city"]


def test_value_sample_holds_every_value_past_the_500_row_answer_cap():
    """900 distinct values sit between the answer cap and the sample cap. The distinct read went through `execute`,
    which keeps 500 rows, so the profile stored 500 of the 900 as the complete set (measured 2026-09-17). Which 500
    survived changed from build to build, and offline binding bound a token whose value was cut to a kept
    neighbour, 'City 3' as 'City 39', with no live probe: 366 and 369 of the 400 cut values in two builds."""
    assert MAX_ROWS < 900 <= profiler._VALUE_SAMPLE_MAX_DISTINCT
    c, rows = _cities(900)
    p = _city_profile(c, rows)
    assert p.distinct_count == 900
    assert sorted(p.value_sample) == sorted(f"City {i}" for i in range(900))


def test_value_sample_at_exactly_the_cap_is_kept_whole():
    cap = profiler._VALUE_SAMPLE_MAX_DISTINCT
    c, rows = _cities(cap)
    assert len(_city_profile(c, rows).value_sample) == cap


def test_value_sample_is_dropped_when_the_catalog_under_reads_past_the_cap():
    """The gate trusts the catalog's distinct estimate, and SUMMARIZE's `approx_unique` is a HyperLogLog: it read
    851 for 900 values (DuckDB 1.5.2). A column the estimate puts under the cap but that holds more must come back
    None, and the LIMIT cap+1 read is what catches it. Behind the 500-row cap that read could never hold more than
    the cap, so such a column stored 500 values."""
    c, rows = _cities(2500)
    p = _city_profile(c, rows, fast_stats={"city": {"approx_unique": 1950, "null_pct": 0.0}})
    assert p.value_sample is None


def test_value_sample_is_dropped_when_the_connection_cuts_the_bounded_read():
    """A connector that does not override `execute_bounded` falls back to its capped `execute` and returns 500 rows
    while counting 900. A cut read is not the distinct set, so nothing is stored."""
    class _Capped(DuckDBConnection):
        execute_bounded = DatabaseConnection.execute_bounded

    c, rows = _cities(900, cls=_Capped)
    assert _city_profile(c, rows).value_sample is None


# ─────────────────────────── serialization ───────────────────────────────────

def test_column_profile_value_sample_roundtrips_and_is_backward_compatible():
    cp = ColumnProfile(table="main.t", column="brand", dtype="VARCHAR",
                       semantic_type="dimension", value_sample=["A", "B"])
    d = cp.to_dict()
    assert d["value_sample"] == ["A", "B"]
    assert ColumnProfile.from_dict(d).value_sample == ["A", "B"]
    # A pre-R5 cached row has no value_sample key → loads as None, never errors.
    old = {k: v for k, v in d.items() if k != "value_sample"}
    assert ColumnProfile.from_dict(old).value_sample is None


# ─────────────────────────── store (profile_cache) ───────────────────────────

def test_load_value_samples_merges_conn_and_skips_others(monkeypatch):
    canned = {
        "c1:fp1": {"columns": {
            "k1": {"table": "main.sales_franchises", "column": "name",
                   "value_sample": ["Mytheresa", "Zara"]},
            "k2": {"table": "main.sales", "column": "status", "value_sample": None},
        }},
        "c1:fp2": {"columns": {
            "k3": {"table": "main.orders", "column": "city", "value_sample": ["Zurich", "Milan"]},
        }},
        "OTHER:fp": {"columns": {
            "k4": {"table": "x", "column": "y", "value_sample": ["z"]},
        }},
    }
    monkeypatch.setattr(pc, "_load", lambda: canned)
    out = pc.load_value_samples("c1")
    assert out == {
        ("main.sales_franchises", "name"): ["Mytheresa", "Zara"],
        ("main.orders", "city"): ["Zurich", "Milan"],
    }


# ─────────────────────────── consumer (_db_find_value) ───────────────────────

_FRANCHISE = """\
TABLE: main.sales_franchises  (48 rows)
  franchiseID  BIGINT
  name  VARCHAR
  city  VARCHAR
TABLE: main.sales_transactions  (3333 rows)
  dateTime  TIMESTAMP
  product  VARCHAR
  totalPrice  BIGINT
"""


class _FakeDB:
    def __init__(self, hits=None):
        self.hits = hits or {}
        self.seen = []

    def rows(self, sql, label=None):
        self.seen.append(sql)
        for needle, rows in self.hits.items():
            if needle in sql:
                return rows
        return []


def test_exact_sample_hit_binds_offline_without_probing():
    db = _FakeDB(hits={"sales_franchises": [["Mytheresa"]]})
    samples = {("main.sales_franchises", "name"): ["Aldi", "Mytheresa", "Zara"]}
    out = R._db_find_value(db, _FRANCHISE, "mytheresa", value_samples=samples)
    assert out == ("main.sales_franchises", "name", "Mytheresa")
    assert db.seen == []          # bound from the warmed sample — no live probe


def test_fuzzy_sample_hit_binds_offline():
    samples = {("main.sales_franchises", "name"): ["Mytheresa", "Zalando"]}
    out = R._db_find_value(None, _FRANCHISE, "mytheresaa", value_samples=samples)  # typo
    assert out == ("main.sales_franchises", "name", "Mytheresa")


def test_sample_miss_without_db_returns_none_never_false_absent():
    samples = {("main.sales_franchises", "name"): ["Zalando", "Asos"]}
    assert R._db_find_value(None, _FRANCHISE, "mytheresa", value_samples=samples) is None


def test_sample_miss_falls_back_to_live_probe():
    db = _FakeDB(hits={"sales_franchises": [["Mytheresa"]]})
    samples = {("main.sales_franchises", "name"): ["Zalando"]}   # miss → must live-probe
    out = R._db_find_value(db, _FRANCHISE, "mytheresa", value_samples=samples)
    assert out == ("main.sales_franchises", "name", "Mytheresa")
    assert any("sales_franchises" in s for s in db.seen)


def test_resolve_uses_warmed_samples_and_skips_live_probe(monkeypatch):
    monkeypatch.setattr(pc, "load_value_samples",
                        lambda cid: {("main.sales_franchises", "name"): ["Mytheresa", "Zalando"]})
    db = _FakeDB(hits={"sales_franchises": [["Mytheresa"]]})
    r = R.resolve("sales for mytheresa", schema=_FRANCHISE, db=db, connection_id="c1")
    assert any(b.value == "Mytheresa" and b.column == "name" for b in r.entity_bindings)
    assert db.seen == []          # the warmed index answered — warehouse untouched
