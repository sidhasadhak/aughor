"""SE-4 I — the result cache is keyed on the request SHAPE, not just the SQL text.

Two defects, one cause. The key was ``(conn_id, [tenancy], sql)``; the rows stored under
it were whatever the caller's row cap produced.

  1. **The legacy path served the wrong row count, labelled `cached: true`.** Run a query
     at ``limit=2``, then the same text at ``limit=10``: the second call returned 2 rows.
     Live on main before this wave — not a typed-path concern at all.
  2. **`use_cache` was silently a no-op under `format:"typed"`.** The route refused to
     cache typed responses (rows are stringified; a typed run wraps at LIMIT n+1). It
     refused *quietly*: the request succeeded, `cached` was always false, and the Query
     Builder's Cache checkbox — which shares this contract now that the builder uses the
     workbench grid — was a switch wired to nothing.

The fix is one thing: a `variant` naming the row cap and the format. These tests pin
both failures, plus the boundary that made caching typed responses unsafe in the first
place (the n+1 probe row must never reach the cache).
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    import aughor.db.matcache as mc
    monkeypatch.setattr(mc, "_CACHE_PATH", tmp_path / "mat.duckdb")
    monkeypatch.setattr(mc, "_conn", None)
    db = tmp_path / "cache.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE t AS SELECT i AS id, 'n' || i AS name FROM range(50) AS r(i)")
    c.close()
    cid = registry.add_connection("se4i-cache", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)
    mc._conn = None


def _run(cid: str, sql: str, **extra) -> dict:
    r = client.post("/query/run", json={"conn_id": cid, "sql": sql, **extra})
    assert r.status_code == 200, r.text
    return r.json()


SQL = "SELECT id, name FROM t ORDER BY id"


# ── 1. the limit is part of the key ───────────────────────────────────────────

def test_a_larger_limit_is_not_served_from_a_smaller_cached_run(conn):
    """The live defect: 2 rows returned for a limit=10 request, `cached: true`."""
    assert _run(conn, SQL, limit=2, use_cache=True)["row_count"] == 2
    big = _run(conn, SQL, limit=10, use_cache=True)
    assert big["row_count"] == 10, "the cache served a smaller run's rows"
    assert big["cached"] is False, "a different row cap must be a MISS, not a hit"


def test_a_smaller_limit_is_not_served_from_a_larger_cached_run(conn):
    """The same defect in the other direction — over-serving rows the caller capped out."""
    assert _run(conn, SQL, limit=10, use_cache=True)["row_count"] == 10
    assert _run(conn, SQL, limit=2, use_cache=True)["row_count"] == 2


def test_the_same_shape_still_hits(conn):
    """The variant must not be so fine-grained that the cache never hits — that would
    'fix' the bug by disabling the feature."""
    _run(conn, SQL, limit=5, use_cache=True)
    again = _run(conn, SQL, limit=5, use_cache=True)
    assert again["cached"] is True and again["row_count"] == 5


def test_use_cache_false_neither_reads_nor_writes(conn):
    _run(conn, SQL, limit=5, use_cache=False)
    assert _run(conn, SQL, limit=5, use_cache=True)["cached"] is False


# ── 2. typed responses cache, and cache CORRECTLY ─────────────────────────────

def test_typed_caches_at_all(conn):
    """The builder's Cache checkbox, under the shared grid contract."""
    first = _run(conn, SQL, limit=5, use_cache=True, format="typed", source="query_workbench")
    assert first["cached"] is False
    second = _run(conn, SQL, limit=5, use_cache=True, format="typed", source="query_workbench")
    assert second["cached"] is True, "use_cache is still a no-op under format='typed'"


def test_a_cached_typed_response_is_identical_to_the_live_one(conn):
    """A cache that returns a DIFFERENT body is worse than no cache — it makes the bug
    depend on whether you ran the query before. Everything but the timing must match."""
    live = _run(conn, SQL, limit=5, use_cache=True, format="typed", source="query_workbench")
    hit = _run(conn, SQL, limit=5, use_cache=True, format="typed", source="query_workbench")
    for key in ("columns", "columns_typed", "rows", "row_count", "truncated", "format"):
        assert hit[key] == live[key], f"cached typed response differs on {key!r}"
    assert hit["cached"] is True and live["cached"] is False


def test_the_truncation_probe_row_never_reaches_the_cache(conn):
    """A typed run fetches LIMIT n+1 to learn whether more rows exist. That extra row is
    sliced off before the response — and must be sliced off before the STORE too, or the
    cache becomes the way it leaks back out. This is the boundary that made caching typed
    responses unsafe, so it is the one to pin."""
    live = _run(conn, SQL, limit=5, use_cache=True, format="typed", source="query_workbench")
    assert live["row_count"] == 5 and live["truncated"] is True
    hit = _run(conn, SQL, limit=5, use_cache=True, format="typed", source="query_workbench")
    assert len(hit["rows"]) == 5, f"the n+1 probe row leaked through the cache: {len(hit['rows'])}"
    assert hit["truncated"] is True, "truncation must survive the round trip, or 'first 5' lies"


def test_typed_rows_stay_json_native_through_the_cache(conn):
    """The whole point of `typed`. A cached hit that returns stringified cells would
    silently undo it for anyone who happened to run the query twice."""
    _run(conn, SQL, limit=3, use_cache=True, format="typed", source="query_workbench")
    hit = _run(conn, SQL, limit=3, use_cache=True, format="typed", source="query_workbench")
    assert hit["cached"] is True
    assert all(isinstance(r[0], int) for r in hit["rows"]), \
        "ids came back stringified — a cached typed response degraded to legacy"


def test_typed_and_legacy_do_not_read_each_others_entries(conn):
    """Same SQL, same limit, different format. Sharing a key is how stringified rows
    would be served under a 'typed' label."""
    _run(conn, SQL, limit=4, use_cache=True)                       # legacy fills the cache
    typed = _run(conn, SQL, limit=4, use_cache=True, format="typed", source="query_workbench")
    assert typed["cached"] is False, "a typed request hit a legacy entry"
    assert all(isinstance(r[0], int) for r in typed["rows"])


def test_a_cached_typed_hit_still_carries_column_types(conn):
    _run(conn, SQL, limit=3, use_cache=True, format="typed", source="query_workbench")
    hit = _run(conn, SQL, limit=3, use_cache=True, format="typed", source="query_workbench")
    assert hit["cached"] is True
    by_name = {c["name"]: c["type"] for c in hit["columns_typed"]}
    assert by_name["id"] == "BIGINT" and by_name["name"] == "VARCHAR"


# ── 3. the store's own contract ───────────────────────────────────────────────

def test_variant_partitions_the_key_and_none_reproduces_the_legacy_key():
    """Callers with no cap of their own (the metric-moves path) must keep the historical
    key — the variant is additive, not a re-keying of every consumer."""
    from aughor.db.matcache import _cache_key
    import hashlib
    legacy = hashlib.sha256(b"c1::SELECT 1").hexdigest()[:32]
    assert _cache_key("c1", "SELECT 1") == legacy
    assert _cache_key("c1", "SELECT 1", None, None) == legacy
    assert _cache_key("c1", "SELECT 1", None, "typed:500:std") != legacy
    assert (_cache_key("c1", "SELECT 1", None, "typed:500:std")
            != _cache_key("c1", "SELECT 1", None, "typed:100:std"))


def test_extras_round_trip_beside_the_result(tmp_path, monkeypatch):
    """`get_cached_entry` returns extras BESIDE the QueryResult, never on it — QueryResult
    is the execution contract and must not grow a display concern."""
    import aughor.db.matcache as mc
    from aughor.control_plane.contracts.execution import QueryResult
    monkeypatch.setattr(mc, "_CACHE_PATH", tmp_path / "m.duckdb")
    monkeypatch.setattr(mc, "_conn", None)
    res = QueryResult(hypothesis_id="h", sql="SELECT 1", columns=["a"], rows=[[1]], row_count=1)
    mc.put_cache("c1", "SELECT 1", res, variant="typed:5:std",
                 extra={"columns_typed": [{"name": "a", "type": "BIGINT"}], "truncated": True})

    got, extras = mc.get_cached_entry("c1", "SELECT 1", variant="typed:5:std")
    assert got.rows == [[1]]
    assert extras["truncated"] is True
    assert extras["columns_typed"][0]["type"] == "BIGINT"
    assert not hasattr(got, "cache_extra"), "extras were attached to the execution contract"
    # get_cached stays the rows-only view every non-typed caller wants
    assert mc.get_cached("c1", "SELECT 1", variant="typed:5:std").rows == [[1]]
    assert mc.get_cached_entry("c1", "SELECT 1", variant="other") is None


def test_an_entry_without_extras_reports_an_empty_dict(tmp_path, monkeypatch):
    """Legacy entries carry no extra_json; the tuple shape must not depend on that."""
    import aughor.db.matcache as mc
    from aughor.control_plane.contracts.execution import QueryResult
    monkeypatch.setattr(mc, "_CACHE_PATH", tmp_path / "m2.duckdb")
    monkeypatch.setattr(mc, "_conn", None)
    res = QueryResult(hypothesis_id="h", sql="SELECT 1", columns=["a"], rows=[[1]], row_count=1)
    mc.put_cache("c1", "SELECT 1", res)
    got, extras = mc.get_cached_entry("c1", "SELECT 1")
    assert extras == {} and got.row_count == 1
