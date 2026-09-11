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

import logging
import threading
import time
from pathlib import Path

import pytest

from aughor.db import single_flight
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


# ── Re-entrancy: the leader's own thread calling back in ─────────────────────────────
#
# `LocalUploadConnection.build_intelligence` is decorated and runs the decorated
# `DuckDBConnection.build_intelligence(self)`: same object, same key, same thread. The
# inner call used to find the outer one registered and wait WAIT_TIMEOUT_S (600s) for an
# event only the outer call's return could set, then build anyway — every workspace
# build paid the ten minutes, and the suite's session teardown joined four such workers.

#: Long enough that "well under it" is not a scheduling race; short enough that the
#: self-wait fails these tests in seconds instead of hanging them.
_WAIT_S = 5.0


def _waits(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records
            if r.name == single_flight.__name__ and "already building" in r.getMessage()]


class _Base:
    """Plays `DuckDBConnection`: a decorated build."""

    def __init__(self, connection_id: str, schema_name: str | None, log: list) -> None:
        self._connection_id = connection_id
        self._schema_name = schema_name
        self._log = log

    @single_flight_build
    def build_intelligence(self) -> str:
        self._log.append("inner")
        return "SCHEMA"


class _Override(_Base):
    """Plays `LocalUploadConnection`: a decorated override that runs the decorated base
    implementation explicitly, as the real one does."""

    @single_flight_build
    def build_intelligence(self) -> str:
        return _Base.build_intelligence(self)


def test_a_nested_decorated_call_does_not_wait_for_itself(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(single_flight, "WAIT_TIMEOUT_S", _WAIT_S)
    caplog.set_level(logging.INFO, logger=single_flight.__name__)
    before = inflight_count()
    log: list = []

    t0 = time.monotonic()
    result = _Override("c8", "main", log).build_intelligence()
    elapsed = time.monotonic() - t0

    assert result == "SCHEMA"
    assert log == ["inner"], "the nested build must still run, exactly once"
    assert elapsed < _WAIT_S / 10, (
        f"{elapsed:.2f}s against a {_WAIT_S:.0f}s wait: the nested call waited for its own leader")
    assert not _waits(caplog), "the leader's own nested call logged 'already building'"
    assert inflight_count() == before, "the outer call must still release the key"


def test_another_thread_still_waits_for_the_whole_nested_build(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Re-entrancy belongs to the leader's OWN thread. A caller on another thread must
    wait out the whole outer build — including the work after its nested call returns —
    or the guard has become a pass-through. Also the positive control for the test
    above: it proves `_waits` sees a wait when one happens."""
    monkeypatch.setattr(single_flight, "WAIT_TIMEOUT_S", _WAIT_S)
    caplog.set_level(logging.INFO, logger=single_flight.__name__)
    spans: list = []
    leader_inside = threading.Event()

    class _Busy(_Base):
        @single_flight_build
        def build_intelligence(self) -> str:
            t0 = time.monotonic()
            leader_inside.set()
            time.sleep(0.15)
            _Base.build_intelligence(self)  # nested: same key, same thread
            time.sleep(0.15)                # still holding the key after it returns
            spans.append((t0, time.monotonic()))
            return "SCHEMA"

    t0 = time.monotonic()
    first = threading.Thread(target=_Busy("c9", "main", []).build_intelligence)
    first.start()
    assert leader_inside.wait(timeout=_WAIT_S), "the leader never started"
    second = threading.Thread(target=_Busy("c9", "main", []).build_intelligence)
    second.start()
    first.join(timeout=3 * _WAIT_S)
    second.join(timeout=3 * _WAIT_S)
    elapsed = time.monotonic() - t0

    assert len(spans) == 2, "the other thread must still run (serialize, not skip)"
    leader, follower = sorted(spans)
    assert follower[0] >= leader[1], f"another thread's build overlapped the leader's: {spans}"
    assert len(_waits(caplog)) == 1, (
        f"expected exactly one wait, the other thread's; got {len(_waits(caplog))}")
    assert elapsed < _WAIT_S / 2, f"{elapsed:.2f}s: a caller waited out the timeout"


def test_the_local_upload_build_does_not_wait_for_itself(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    """The shipped instance: the real decorated override over the real decorated DuckDB
    build. The render and the heavy annotators are stubbed so only the guard is timed,
    and storage is vended under `tmp_path` so no checkout's `data/uploads` is touched."""
    from aughor.connectors.file.local_upload import LocalUploadConnection
    from aughor.control_plane import vending
    from aughor.db import schema_render
    from aughor.kernel.registries import schema_annotators

    phases: list = []

    def _annotate(conn, base: str, phase: str) -> str:
        phases.append(phase)
        return base

    monkeypatch.setattr(single_flight, "WAIT_TIMEOUT_S", _WAIT_S)
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(schema_render, "render_raw_schema", lambda *a, **k: "RAW SCHEMA")
    monkeypatch.setattr(schema_annotators, "run_annotators", _annotate)
    caplog.set_level(logging.INFO, logger=single_flight.__name__)

    conn = LocalUploadConnection(connection_id="single_flight_reentrant")
    try:
        t0 = time.monotonic()
        result = conn.build_intelligence()
        elapsed = time.monotonic() - t0
    finally:
        conn.close()

    assert list(tmp_path.glob("*/single_flight_reentrant")), "storage was not vended under tmp_path"
    assert result == "RAW SCHEMA"
    assert phases == ["heavy"], "the DuckDB build body must run exactly once"
    assert elapsed < _WAIT_S / 10, f"LocalUpload's build took {elapsed:.2f}s: it waited for itself"
    assert not _waits(caplog)
