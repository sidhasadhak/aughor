"""One heavy intelligence build per (connection, schema) at a time.

`build_intelligence()` is reachable from four places that can fire at once:

  * the birth rite (`routers/_shared.run_birth`),
  * the `/ontology` request path (`routers/ontology`),
  * the explorer's Phase-8 gate, which builds when it finds no ontology
    (`explorer/agent`) — its own comment notes phases 3-7 can finish before the
    build "triggered by the first /ontology API request" has happened,
  * and any future caller, since nothing about the method says it is exclusive.

Nothing prevented two of those running the same build concurrently. Both would
render the schema, profile every column, infer the ontology, and save — duplicating
minutes of work and racing each other's write. The hazard is not theoretical: the
gate exists precisely because exploration can outrun the build.

SERIALIZE, DO NOT SKIP. A follower waits for the leader and then runs the build
itself, rather than being handed the leader's return value. That is deliberate:

  * callers read `db.last_build` off THEIR OWN connection object afterwards, so a
    follower handed someone else's string would be left with no build record and a
    caller reading None,
  * and the second run is nearly free — with the ontology now cached on its
    fingerprint, a warm `build_intelligence()` measured **0.0s** against a schema
    where the cold build takes ~16s.

So the follower pays a cache hit, keeps its own state consistent, and the expensive
work happens exactly once.

Thread-based rather than async: the callers reach this through
`run_in_executor`, and one calls it synchronously.
"""
from __future__ import annotations

import functools
import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

#: How long a follower waits for the leader before building anyway. A leader that
#: wedges must not strand every other caller forever — the duplicate build is the
#: lesser failure, and it is what happened on every call before this existed.
WAIT_TIMEOUT_S = 600.0

_registry_lock = threading.Lock()
_inflight: dict[tuple[str, str], threading.Event] = {}


def _key(conn) -> tuple[str, str]:
    """Identity of the thing being built. Schema matters: two schemas on one
    connection have independent ontologies and must not block each other."""
    return (
        str(getattr(conn, "_connection_id", "") or ""),
        str(getattr(conn, "_schema_name", "") or ""),
    )


def inflight_count() -> int:
    """Builds currently held by a leader — for tests and diagnostics."""
    with _registry_lock:
        return len(_inflight)


def single_flight_build(fn: Callable[..., str]) -> Callable[..., str]:
    """Serialize `build_intelligence` per (connection, schema)."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        key = _key(self)
        with _registry_lock:
            event = _inflight.get(key)
            is_leader = event is None
            if is_leader:
                event = threading.Event()
                _inflight[key] = event

        if not is_leader:
            logger.info("build_intelligence: %s already building — waiting", key)
            if not event.wait(timeout=WAIT_TIMEOUT_S):
                logger.warning(
                    "build_intelligence: waited %.0fs for %s and it never finished — "
                    "building anyway", WAIT_TIMEOUT_S, key)
            # Runs warm: the leader has saved the ontology under its fingerprint, so
            # this is a cache hit that still sets THIS object's `last_build`.
            return fn(self, *args, **kwargs)

        try:
            return fn(self, *args, **kwargs)
        finally:
            with _registry_lock:
                _inflight.pop(key, None)
            event.set()

    return wrapper
