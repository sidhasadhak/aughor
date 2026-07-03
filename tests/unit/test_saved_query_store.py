"""Saved-query store CRUD — the persistence behind Query Builder save/load.

The store round-trips an opaque visual ``spec`` (dims/measures/filters/joins) alongside the SQL,
is connection-scoped (list filters by connection, newest-first), and supports partial updates.
DB path is isolated per-test so the real data/ dir is never touched."""
import pytest

from aughor.savedquery import store as S


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_DB_PATH", tmp_path / "saved_queries.db")


SPEC = {
    "primaryTable": "order_items",
    "joinedTables": ["orders"],
    "dims": [{"id": "d1", "col": "traffic_source", "table": "order_items"}],
    "measures": [{"id": "m1", "col": "final_price_usd", "table": "order_items", "agg": "SUM"}],
    "filters": [],
    "orderBy": "",
    "limit": 1000,
}


class TestCreateGet:
    def test_round_trips_sql_and_spec(self):
        q = S.create_saved_query("conn1", "Revenue by source", sql="SELECT 1", spec=SPEC)
        assert q.id and q.created_at and q.updated_at
        got = S.get_saved_query(q.id)
        assert got is not None
        assert got.name == "Revenue by source"
        assert got.sql == "SELECT 1"
        assert got.spec == SPEC  # nested dict survives the JSON round-trip
        assert got.connection_id == "conn1"

    def test_missing_get_is_none(self):
        assert S.get_saved_query("nope") is None

    def test_empty_spec_defaults_to_dict(self):
        q = S.create_saved_query("conn1", "bare", sql="SELECT 1")
        assert S.get_saved_query(q.id).spec == {}


class TestList:
    def test_filters_by_connection(self):
        S.create_saved_query("connA", "a1", spec={})
        S.create_saved_query("connB", "b1", spec={})
        a = S.list_saved_queries("connA")
        assert [q.name for q in a] == ["a1"]
        assert len(S.list_saved_queries()) == 2  # no filter → all

    def test_newest_first(self):
        q1 = S.create_saved_query("c", "first", spec={})
        S.create_saved_query("c", "second", spec={})
        # updating q1 bumps updated_at so it sorts ahead of q2
        S.update_saved_query(q1.id, name="first-edited")
        names = [q.name for q in S.list_saved_queries("c")]
        assert names[0] == "first-edited"


class TestUpdate:
    def test_partial_update_name_only(self):
        q = S.create_saved_query("c", "old", sql="SELECT 1", spec=SPEC)
        upd = S.update_saved_query(q.id, name="new")
        assert upd.name == "new"
        assert upd.sql == "SELECT 1"      # untouched
        assert upd.spec == SPEC           # untouched

    def test_partial_update_spec_only(self):
        q = S.create_saved_query("c", "n", sql="SELECT 1", spec={})
        upd = S.update_saved_query(q.id, spec=SPEC)
        assert upd.spec == SPEC
        assert upd.name == "n"

    def test_update_missing_is_none(self):
        assert S.update_saved_query("nope", name="x") is None


class TestDelete:
    def test_delete_removes(self):
        q = S.create_saved_query("c", "n", spec={})
        assert S.delete_saved_query(q.id) is True
        assert S.get_saved_query(q.id) is None

    def test_delete_missing_is_false(self):
        assert S.delete_saved_query("nope") is False
