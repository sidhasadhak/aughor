"""Opening an uploads connection must not build its database.

`__init__` called `_shared_base(..., build=self._materialize)`, so merely OPENING the
connection re-read every uploaded file into DuckDB. Caching made the second open free
and did nothing for the first — and on serverless every open is a first: production
cold-started 43 times in a 30-minute window, so it paid the full rebuild on
essentially every request.

Measured locally before this change: `open_connection_for("workspace")` was 9.56s of
a 9.87s `/catalog/tree` — 97% — spent so the catalog could read table NAMES that
`list_files()` already derives from the upload directory without touching DuckDB.

So the cost belongs to the first QUERY, not to the open. These tests pin that, and
pin the three paths that must NOT trigger a build: listing files, closing, and the
catalog's own schema listing.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.connectors.file.local_upload import LocalUploadConnection
from aughor.control_plane import vending


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")


@pytest.fixture
def seed_db(tmp_path):
    p = tmp_path / "seed.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE SCHEMA demo")
    con.execute("CREATE TABLE demo.orders AS SELECT * FROM range(3) t(id)")
    con.close()
    return str(p)


def _built(c) -> bool:
    """Whether the expensive database actually exists yet — read WITHOUT the
    property, which would build it just to answer."""
    return getattr(c, "_cursor", None) is not None


def _conn(seed_db, **kw):
    return LocalUploadConnection(connection_id="c1", meta={"seed_duckdb": seed_db}, **kw)


def test_opening_does_not_build_the_database(seed_db):
    c = _conn(seed_db)
    assert not _built(c), "constructing the connection materialized the whole workspace"


def test_listing_files_does_not_build_the_database(seed_db):
    """The catalog's path: names come from the upload dir and the sidecars, so this
    must stay free. It was the 97%."""
    c = _conn(seed_db)
    c.list_files()
    assert not _built(c)


def test_closing_without_querying_does_not_build_the_database(seed_db):
    """close() read `self._duckdb`, which would BUILD the database so it could
    immediately close it — the whole cost, paid by the one caller needing nothing."""
    c = _conn(seed_db)
    c.close()
    assert not _built(c)


def test_the_first_query_builds_it_and_the_data_is_right(seed_db):
    """Laziness must not become absence: the query still gets a real database."""
    c = _conn(seed_db)
    rows = c.execute("__t__", "SELECT count(*) FROM demo.orders").rows
    assert _built(c), "a query ran without the database being built"
    assert int(rows[0][0]) == 3


def test_the_build_happens_once(seed_db):
    c = _conn(seed_db)
    c.execute("__t__", "SELECT 1")
    first = c._cursor
    c.execute("__t__", "SELECT 2")
    assert c._cursor is first, "a second query rebuilt the database"


def test_materialize_does_not_recurse_through_its_own_property(seed_db):
    """`_materialize` runs AS the `build=` callback of the `_duckdb` property, so any
    read of `self._duckdb` inside it re-enters and recurses. It must use `_cursor`."""
    c = _conn(seed_db)
    c.execute("__t__", "SELECT 1")          # would RecursionError, not fail an assert
    assert _built(c)


def test_a_reader_clone_still_works(seed_db):
    """make_reader builds clones through __new__, which runs no __init__ — so the
    property has to tolerate `_cursor` never having been assigned."""
    c = _conn(seed_db)
    r = c.make_reader()
    assert int(r.execute("__t__", "SELECT count(*) FROM demo.orders").rows[0][0]) == 3
