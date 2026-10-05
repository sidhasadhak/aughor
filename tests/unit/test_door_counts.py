"""The gate map's "last used": each of the SQL door's ten methods counts one use, at the method the
caller came in through (ROADMAP §6 item 42 — decided per entry point).

Two populations come from the code and the census, never from a list written here: every door the
census names is one the count knows, and every door method on every connection class is wrapped.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from aughor.db import door_count
from aughor.db.connection import DatabaseConnection
from aughor.govern import gate_map
from aughor.security.audit import DoorCounter

REPO = Path(__file__).resolve().parents[2]


class _Result:
    error = None
    rows = [(1,)]


class _Conn(DatabaseConnection):
    """The smallest connection: an engine's own `execute`, everything else the base's."""

    def execute(self, hypothesis_id, sql, *, sql_dialect=None, internal=False):
        return _Result()


_Conn.__abstractmethods__ = frozenset()


def _uses() -> dict[str, int]:
    return {door: row["uses"] for door, row in DoorCounter.totals()["doors"].items()}


def _gained(before: dict[str, int]) -> dict[str, int]:
    after = _uses()
    return {d: after[d] - before.get(d, 0) for d in after if after[d] != before.get(d, 0)}


def test_every_door_the_census_names_is_counted():
    census = json.loads((REPO / "docs" / "SQL_DOORS.json").read_text())
    named = {key.split("::")[2] for key in census["sites"]}
    assert named <= set(door_count.DOORS), f"the census names a door the count does not know: {named - set(door_count.DOORS)}"
    assert set(door_count.DOORS) <= named, "a counted door no call in the code goes through"


def _connection_classes() -> list[type]:
    import aughor.connectors.base  # noqa: F401 — the connectors' own base, so its subclasses are in the walk
    found, queue = [], [DatabaseConnection]
    while queue:
        cls = queue.pop()
        found.append(cls)
        queue.extend(cls.__subclasses__())
    return found


def test_every_door_method_on_every_connection_class_is_wrapped():
    classes = _connection_classes()
    assert len(classes) >= 4, "the walk found too few connection classes to mean anything"
    bare = [f"{cls.__name__}.{name}" for cls in classes for name in door_count.DOOR_METHODS
            if inspect.isfunction(cls.__dict__.get(name))
            and not getattr(cls.__dict__[name], "__isabstractmethod__", False)
            and getattr(cls.__dict__[name], "__counted_door__", None) != name]
    assert not bare, f"door methods that would run uncounted: {bare}"


def test_a_use_is_counted_once_at_the_method_the_caller_used():
    conn = _Conn()
    before = _uses()
    assert conn.rows("SELECT 1") == [(1,)]            # the base's `rows`, which runs through `execute`
    assert _gained(before) == {"rows": 1}
    before = _uses()
    conn.execute("a label", "SELECT 1")
    conn.execute("a label", "SELECT 1")
    assert _gained(before) == {"execute": 2}


def test_the_guarded_door_is_the_tenth_and_what_runs_beneath_it_is_the_same_use():
    from aughor.sql import executor
    assert getattr(executor.execute_guarded, "__counted_door__", None) == door_count.GUARDED
    conn = _Conn()

    def beneath():
        return conn.execute("a label", "SELECT 1")

    before = _uses()
    door_count.counted_door(door_count.GUARDED, beneath)()
    assert _gained(before) == {door_count.GUARDED: 1}


def test_a_failed_count_never_stops_the_statement(monkeypatch):
    def broken(door):
        raise RuntimeError("the audit store is away")

    monkeypatch.setattr(DoorCounter, "count", broken)
    assert _Conn().rows("SELECT 1") == [(1,)]


def test_the_gate_map_says_when_each_door_was_last_used_and_since_when_it_counts():
    _Conn().execute("a label", "SELECT 1")
    seen = gate_map.statement_doors()
    rows = {r["door"]: r for r in seen["by_door"]}
    assert rows["execute"]["uses"] >= 1 and rows["execute"]["last_used"][:4].isdigit()
    assert seen["counted_since"] and seen["counted_since"] in seen["uses_note"]
    # a door nobody used since counting began says so with a zero and no date, never a made-up one
    for row in rows.values():
        assert (row["uses"] == 0) == (row["last_used"] == "")
