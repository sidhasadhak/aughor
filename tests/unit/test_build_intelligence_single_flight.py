"""One heavy intelligence build per (connection, schema) at a time.

`build_intelligence()` is reachable from the birth rite, the /ontology route and the
explorer's Phase-8 gate, and nothing stopped two of them running the same build at
once. The gate exists BECAUSE exploration can outrun the build, so the collision is
the designed-for case, not an exotic one.

The guard serializes rather than skips: a follower waits, then runs the build itself
as a cache hit (measured 0.0s warm against ~16s cold), so it still sets `last_build`
on its own object. These tests therefore assert NON-OVERLAP, not call count — a
call-count assertion would encode the wrong contract.
"""
from __future__ import annotations

import threading
import time

from aughor.db.single_flight import inflight_count, single_flight_build


class _Conn:
    """Minimal stand-in carrying the identity attributes the key is built from."""

    def __init__(self, connection_id: str, schema_name: str | None, log: list, delay: float = 0.20):
        self._connection_id = connection_id
        self._schema_name = schema_name
        self._log = log
        self._delay = delay
        self.last_build = None

    @single_flight_build
    def build_intelligence(self) -> str:
        t0 = time.monotonic()
        time.sleep(self._delay)
        t1 = time.monotonic()
        self._log.append((self._connection_id, self._schema_name, t0, t1))
        self.last_build = {"ok": True}
        return "SCHEMA"


def _run_concurrently(conns) -> None:
    threads = [threading.Thread(target=c.build_intelligence) for c in conns]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _overlap(a, b) -> float:
    return min(a[3], b[3]) - max(a[2], b[2])


def test_same_connection_and_schema_do_not_overlap() -> None:
    log: list = []
    _run_concurrently([_Conn("c1", "main", log), _Conn("c1", "main", log)])

    assert len(log) == 2, "the follower must still run (serialize, not skip)"
    assert _overlap(log[0], log[1]) <= 0, (
        f"two builds for the same (connection, schema) overlapped: {log}")


def test_follower_sets_its_own_last_build() -> None:
    """The reason followers re-run rather than take the leader's return value:
    callers read `db.last_build` off their OWN object afterwards."""
    log: list = []
    a, b = _Conn("c2", "main", log), _Conn("c2", "main", log)
    _run_concurrently([a, b])
    assert a.last_build == {"ok": True}
    assert b.last_build == {"ok": True}


def test_different_schemas_are_independent() -> None:
    """Two schemas on one connection have independent ontologies. Serializing them
    against each other would make the guard a bottleneck instead of a lock."""
    log: list = []
    _run_concurrently([_Conn("c3", "main", log), _Conn("c3", "other", log)])

    assert len(log) == 2
    assert _overlap(log[0], log[1]) > 0, (
        f"different schemas were serialized against each other: {log}")


def test_different_connections_are_independent() -> None:
    log: list = []
    _run_concurrently([_Conn("c4", "main", log), _Conn("c5", "main", log)])
    assert _overlap(log[0], log[1]) > 0, f"different connections were serialized: {log}"


def test_registry_is_emptied_even_when_the_build_raises() -> None:
    """A leader that throws must release its key, or that (connection, schema) is
    wedged for the life of the process — a worse failure than the duplicate build."""
    before = inflight_count()

    class _Boom:
        _connection_id = "c6"
        _schema_name = "main"

        @single_flight_build
        def build_intelligence(self) -> str:
            raise RuntimeError("build exploded")

    try:
        _Boom().build_intelligence()
    except RuntimeError:
        pass

    assert inflight_count() == before, "a raising leader left its key in the registry"
    # and the next caller is not blocked by the corpse
    log: list = []
    c = _Conn("c6", "main", log, delay=0.01)
    c.build_intelligence()
    assert len(log) == 1


def test_serialized_builds_take_about_the_sum_not_the_max() -> None:
    """The point of the guard, stated as time: the second build starts after the
    first finishes. Without it both would run together and the wall clock would be
    ~one delay instead of ~two."""
    log: list = []
    t0 = time.monotonic()
    _run_concurrently([_Conn("c7", "main", log, delay=0.25),
                       _Conn("c7", "main", log, delay=0.25)])
    wall = time.monotonic() - t0
    assert wall >= 0.45, f"wall clock {wall:.3f}s suggests the builds ran concurrently"
