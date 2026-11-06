"""Track D (docs/TENX_PROGRAM_2026-11-05.md §3): data stays in the warehouse by default.

D1 — a cross-source join over a source the federation engine cannot read in place COPIES that source's
rows into DuckDB. That is an organisation's choice (`copy_rows_across_sources`, off by default), not the
platform's; until it is on, the federation refuses and says where to allow it — never a missing-view error.
D2 — an answer whose rows moved between sources says so on its door trail: `copied:duckdb` on a federated
read over a copied member, `cross-source:<connection>` on a join in the platform.
D3 — measured already true, no code: a removed connection takes its cache rows (`db/purge.py`,
`test_connection_purge.py`), expired rows are evicted on the monitors' clock (`monitors/scheduler.py`,
`test_matcache_evict.py`), and `cache_stats()` says the retention (`ttl_default_s`).
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.connectors.federated import COPY_SETTING, FederatedConnection
from aughor.db import doors as D
from aughor.orgsettings import allows as A
from aughor.orgsettings.models import OrgSettings


class _Mirror:
    """A connector the federation cannot ATTACH (an upload, an API mirror): its rows live in a DuckDB of its own."""
    def __init__(self):
        self._duckdb = duckdb.connect(":memory:")
        self._duckdb.execute("CREATE TABLE orders AS SELECT 1 AS id, 'acme' AS customer UNION ALL SELECT 2, 'globex'")


@pytest.fixture
def mirror_member(monkeypatch):
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: _Mirror())
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda cid: {})
    monkeypatch.setattr("aughor.db.registry.get_dsn", lambda cid: ("duckdb", ""))


def test_the_setting_is_born_without_a_flag_and_off():
    assert A.FORMER_ENV[COPY_SETTING] == ()
    assert OrgSettings().copy_rows_across_sources is None
    assert "copied" in D.WORDS and "cross-source" in D.WORDS


def test_without_the_setting_the_federation_copies_nothing_and_every_answer_says_where_to_allow_it(mirror_member, monkeypatch):
    monkeypatch.setattr(A, "allows", lambda s: False)
    fed = FederatedConnection(connection_id="fed-d1", meta={"connection_ids": ["m1"]})
    assert fed._namespaces["m1"]["tables"] == [] and fed._copied == []
    r = fed.execute("__probe__", "SELECT 1")
    assert r.error and COPY_SETTING in r.error and A.WHERE in r.error and "copy its rows" in r.error
    assert r.rows == [] and "blocked:copy-not-allowed" in r.doors
    assert fed.execute_bounded("__probe__", "SELECT 1", 10).error == r.error


def test_with_the_setting_the_copy_is_taken_and_said_on_every_answer(mirror_member, monkeypatch):
    monkeypatch.setattr(A, "allows", lambda s: s == COPY_SETTING)
    fed = FederatedConnection(connection_id="fed-d2", meta={"connection_ids": ["m1"]})
    assert fed._namespaces["m1"]["tables"] == ["m1__orders"] and fed._copied == ["m1"]
    r = fed.execute("__probe__", 'SELECT customer FROM "m1__orders" ORDER BY id')
    assert r.error is None and [row[0] for row in r.rows] == ["acme", "globex"]
    assert "copied:duckdb" in r.doors
    assert "COPIED out of their source" in D.WORDS["copied"].format(d="duckdb")


def test_a_join_in_the_platform_names_the_connection_its_right_rows_came_from():
    from aughor.connectors.remote_join import batched_foreach_join
    from aughor.control_plane.contracts.execution import QueryResult
    from aughor.db.connection import DuckDBConnection

    from pathlib import Path
    right = DuckDBConnection.__new__(DuckDBConnection)      # as test_remote_join builds one: in memory, no file
    right._path, right._schema_name, right._connection_id = Path(":memory:"), None, "conn-right"
    right._conn = duckdb.connect(":memory:")
    right._conn.execute("CREATE TABLE customers AS SELECT 'acme' AS name, 'EU' AS region UNION ALL SELECT 'globex', 'US'")
    left = QueryResult(hypothesis_id="__left__", sql="SELECT …", columns=["id", "customer"],
                       rows=[[1, "acme"], [2, "globex"]], row_count=2, doors=["validated:duckdb", "audited"])
    joined = batched_foreach_join(left, "customer", right, "name", right_table="customers")
    assert joined.error is None and joined.row_count == 2
    assert joined.doors[-1] == "cross-source:conn-right" and joined.doors[:2] == ["validated:duckdb", "audited"]
