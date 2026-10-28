"""Incremental equals rebuilt, for the REST API mirrors (Arc SV-3, `docs/GRIST_STUDY_2026-10-26.md` §3).

Grist's reload oracle: wherever state is kept incrementally, a from-scratch rebuild of the same final data must give
the same result. Here the incremental state is the DuckDB mirror a `RestApiSync` keeps by fetching what changed since a
watermark; the rebuild is a fresh mirror's full sync of what the API holds at the end. Reading for the study found three
ways the two parted, each a test below: columns written by position, a watermark stamped after the fetch, and an object
with no `id` appended to on every sync. The fake API touches no network, and a hand-moved clock stands in for `now()`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aughor.connectors.api import base_sync
from aughor.connectors.api.base_sync import RestApiSync

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


class _Clock(datetime):
    """`base_sync.datetime` for these tests: `now()` reads a clock the test moves by hand."""

    current = T0

    @classmethod
    def now(cls, tz=None):
        return cls.current


class _FakeApi:
    """One object's records, each stamped with when it last changed — what a real API filters `since` on (`>=`, as
    HubSpot's GTE and Stripe's `gte`). Pages of two, so every sync here reads more than one page."""

    PAGE = 2

    def __init__(self, key: str = "id") -> None:
        self.key = key
        self.records: dict[str, dict] = {}
        self.changed: dict[str, datetime] = {}
        self.sinces: list[datetime | None] = []   # the `since` of every sync's first page
        self.during_fetch = None                   # run once, after a page is read: an edit made while a sync runs

    def put(self, record: dict) -> None:
        self.records[record[self.key]] = dict(record)
        self.changed[record[self.key]] = _Clock.current

    def delete(self, key: str) -> None:
        del self.records[key]
        del self.changed[key]

    def page(self, after: str | None, since: datetime | None) -> tuple[list[dict], str | None]:
        if after is None:
            self.sinces.append(since)
        matching = [k for k in sorted(self.records) if since is None or self.changed[k] >= since]
        start = int(after or 0)
        page = [dict(self.records[k]) for k in matching[start:start + self.PAGE]]
        if self.during_fetch:
            edit, self.during_fetch = self.during_fetch, None
            edit()
        more = start + self.PAGE < len(matching)
        return page, str(start + self.PAGE) if more else None


class _Mirror(RestApiSync):
    def __init__(self, api: _FakeApi, connection_id: str) -> None:
        super().__init__(connection_id=connection_id)
        self.api = api

    def _objects(self) -> list[str]:
        return ["deals"]

    def _fetch_page(self, obj, after, since):
        return self.api.page(after, since)

    def test(self) -> tuple[bool, str]:
        return True, "fake"


@pytest.fixture
def mirrors(tmp_path, monkeypatch):
    """Mirrors in this test's own directory, on the hand-moved clock; each closed at the end."""
    monkeypatch.setattr(base_sync, "_STATE_ROOT", tmp_path)
    monkeypatch.setattr(base_sync, "_SYNC_ROOT", tmp_path / "api_sync")
    monkeypatch.setattr(base_sync, "datetime", _Clock)
    _Clock.current = T0 - timedelta(days=1)
    opened: list[_Mirror] = []

    def make(api: _FakeApi, connection_id: str = "sv3") -> _Mirror:
        mirror = _Mirror(api, connection_id)
        opened.append(mirror)
        return mirror

    yield make
    for mirror in opened:
        mirror.close()


def _sync(mirror: _Mirror, *, incremental: bool = True) -> None:
    results = mirror.sync_all(incremental=incremental)
    assert -1 not in results.values(), f"the sync failed (its warning is in the captured log): {results}"


def _table(mirror: _Mirror) -> tuple[dict[str, str], list[dict]]:
    """The mirror's `deals` by NAMED column: each column's type, and every row as {column: value}, in one order."""
    described = mirror._duckdb.execute("DESCRIBE deals").fetchall()
    types = {name.lower(): dtype for name, dtype, *_ in described}
    names = sorted(name for name, *_ in described)
    columns = ", ".join(f'"{n}"' for n in names)
    rows = mirror._duckdb.execute(f"SELECT {columns} FROM deals ORDER BY ALL").fetchall()
    return types, [dict(zip([n.lower() for n in names], row)) for row in rows]


def _assert_equals_rebuilt(mirror: _Mirror, mirrors) -> None:
    """The oracle: a fresh mirror's full sync of the API's final data reads the same, column by named column."""
    rebuilt = mirrors(mirror.api, connection_id=f"{mirror._connection_id}-rebuilt")
    _sync(rebuilt, incremental=False)
    assert _table(mirror) == _table(rebuilt)


@pytest.mark.parametrize("key", ["id", "Id"], ids=["id", "salesforce-Id"])
def test_an_incremental_page_that_drops_a_field_and_adds_one_equals_a_rebuild(mirrors, key):
    """The study's reproduction: deal 2 comes back without `email` and with a new `phone`, beside a new deal 7 of the
    same shape. Written by position, `id, name, phone` landed in `email, id, name` — deal 2 read `email='2'` — with no
    error. By name, over the union of columns, the mirror matches a rebuild through a later sync of deal 7 too.
    Salesforce spells the key `Id`; DuckDB's names ignore case, so it is the same key."""
    api = _FakeApi(key)
    for n, name in (("1", "Ann"), ("2", "Bob"), ("3", "Cy")):
        api.put({key: n, "name": name, "email": f"{name.lower()}@x.test"})
    mirror = mirrors(api)
    _Clock.current = T0
    _sync(mirror)

    _Clock.current = T0 + timedelta(hours=1)
    api.put({key: "2", "name": "Bob", "phone": "555-2"})
    api.put({key: "7", "name": "Gina", "phone": "555-7"})
    _Clock.current = T0 + timedelta(hours=2)
    _sync(mirror)

    _Clock.current = T0 + timedelta(hours=3)
    api.put({key: "7", "name": "Gina R", "email": "gina@x.test"})
    _Clock.current = T0 + timedelta(hours=4)
    _sync(mirror)

    # Both later syncs ran INCREMENTALLY — a full sync would equal the rebuild without writing a single page by name.
    assert api.sinces == [None, T0, T0 + timedelta(hours=2)]
    _, rows = _table(mirror)
    assert {"id": "2", "name": "Bob", "email": None, "phone": "555-2"} in rows
    _assert_equals_rebuilt(mirror, mirrors)


def test_the_watermark_is_the_fetch_start_so_an_edit_made_during_a_sync_is_fetched_next(mirrors):
    """Deal 2 changes while the first sync is still reading pages, after its page was read. Stamped with the clock at
    the END of the fetch, the next sync asks only for changes since then and never fetches it; stamped at the START,
    it does, and the mirror matches a rebuild."""
    api = _FakeApi()
    for n, name in (("1", "Ann"), ("2", "Bob"), ("3", "Cy")):
        api.put({"id": n, "name": name})
    mirror = mirrors(api)

    def edit_while_syncing():
        _Clock.current = T0 + timedelta(minutes=1)
        api.put({"id": "2", "name": "Bob (edited mid-sync)"})
        _Clock.current = T0 + timedelta(minutes=2)   # the fetch goes on reading pages

    api.during_fetch = edit_while_syncing
    _Clock.current = T0
    _sync(mirror)
    assert mirror._load_state()["deals"]["last_sync"] == T0.isoformat()

    _Clock.current = T0 + timedelta(hours=1)
    _sync(mirror)
    assert api.sinces == [None, T0]
    _assert_equals_rebuilt(mirror, mirrors)


def test_an_object_with_no_id_does_not_duplicate_rows_across_two_syncs(mirrors):
    """HubSpot's records carry their key as `hs_object_id`, never `id`, so there is nothing to replace a changed row
    by. Appended, the changed deal sat in the mirror twice after the second sync; run as a full sync, it is once."""
    api = _FakeApi(key="hs_object_id")
    for n, amount in (("1", "10"), ("2", "20"), ("3", "30")):
        api.put({"hs_object_id": n, "dealname": f"deal {n}", "amount": amount})
    mirror = mirrors(api)
    _Clock.current = T0
    _sync(mirror)

    _Clock.current = T0 + timedelta(hours=1)
    api.put({"hs_object_id": "2", "dealname": "deal 2", "amount": "25"})
    _Clock.current = T0 + timedelta(hours=2)
    _sync(mirror)

    assert mirror._duckdb.execute("SELECT count(*), count(DISTINCT hs_object_id) FROM deals").fetchone() == (3, 3)
    _assert_equals_rebuilt(mirror, mirrors)


def test_a_deletion_is_seen_by_a_full_sync_and_never_by_an_incremental_one(mirrors):
    """An incremental sync fetches what changed, and a deleted record does not come back to say so: the docstring says
    deletions are seen only by a full sync, and this holds it to both halves. The full sync replaces the table — upserted
    instead, deal 3 outlived its deletion there too."""
    api = _FakeApi()
    for n, name in (("1", "Ann"), ("2", "Bob"), ("3", "Cy")):
        api.put({"id": n, "name": name})
    mirror = mirrors(api)
    _Clock.current = T0
    _sync(mirror)

    _Clock.current = T0 + timedelta(hours=1)
    api.delete("3")
    _sync(mirror)
    assert mirror._duckdb.execute("SELECT count(*) FROM deals WHERE id = '3'").fetchone() == (1,)

    _sync(mirror, incremental=False)
    assert mirror._duckdb.execute("SELECT count(*) FROM deals WHERE id = '3'").fetchone() == (0,)
    _assert_equals_rebuilt(mirror, mirrors)
