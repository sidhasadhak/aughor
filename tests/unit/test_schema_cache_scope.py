"""get_schema_cached must key on (conn_id, schema-SCOPE), not conn_id alone.

A schema-SCOPED connection (open_connection_for_with_schema pins ._schema_name) returns a
NARROWER get_schema() than the full connection. Keying the cache on conn_id alone let a
single-schema op (e.g. a canvas scoped to `main`) poison the entry a later full-connection
consumer read.

Regression (the live bug): a workspace folding `main` (airline/sales) + `luxexperience`
(luxury retail); the `main.*`-scoped "Airline And Sales" canvas cached workspace as main-only,
so the interesting-facts overview on the unscoped "Luxury Retail" canvas inherited it — fixating
the whole tour on `main` and silently dropping every `luxexperience` table.
"""
import pytest

from aughor.routers import _shared
from aughor.routers._shared import get_schema_cached, invalidate_schema_cache


class _FakeDB:
    """A connection whose get_schema() narrows to ._schema_name — like LocalUploadConnection:
    pinned → bare names of the one schema; unpinned → qualified names across all schemas."""

    def __init__(self, schema_name=None):
        self._schema_name = schema_name
        self.calls = 0

    def get_schema(self):
        self.calls += 1
        if self._schema_name == "main":
            return "TABLE: tickets  (100 rows)"
        return "TABLE: main.tickets  (100 rows)\nTABLE: luxexperience.order_items  (200 rows)"


@pytest.fixture(autouse=True)
def _clean_cache():
    _shared._schema_cache.clear()
    yield
    _shared._schema_cache.clear()


def test_scoped_open_does_not_poison_full_connection_cache():
    conn = "ws"
    # 1) a `main`-scoped op caches first — narrowed to one schema.
    main_schema = get_schema_cached(conn, _FakeDB(schema_name="main"))
    assert "tickets" in main_schema and "luxexperience" not in main_schema
    # 2) a full-connection consumer must see BOTH schemas, not the poisoned main-only view.
    full_schema = get_schema_cached(conn, _FakeDB(schema_name=None))
    assert "main.tickets" in full_schema
    assert "luxexperience.order_items" in full_schema


def test_same_scope_served_from_cache_not_reintrospected():
    conn = "ws"
    db = _FakeDB(schema_name=None)
    first = get_schema_cached(conn, db)
    second = get_schema_cached(conn, db)  # same (conn, scope) → cache hit
    assert first == second
    assert db.calls == 1  # get_schema() invoked exactly once


def test_invalidate_clears_every_scope_variant():
    conn = "ws"
    get_schema_cached(conn, _FakeDB(schema_name="main"))
    get_schema_cached(conn, _FakeDB(schema_name=None))
    assert sum(1 for k in _shared._schema_cache if k.startswith(f"{conn}\x00")) == 2
    invalidate_schema_cache(conn)
    assert not any(k.startswith(f"{conn}\x00") for k in _shared._schema_cache)
