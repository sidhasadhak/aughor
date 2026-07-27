"""A frozen measurement connection — Wave L2's harness.

The problem this exists to solve, stated exactly:

    ``assert_frozen_semantics`` refuses to measure on a connection carrying exploration
    insights, because they drift between runs and steer the model's metric choice. But
    `graph.readback`'s whole VALUE is reading knowledge a connection has accumulated.
    Measuring it on a pinned, unexplored connection measures it where it has nothing to
    read — a guaranteed null result. Measuring it on a rich connection trips the guard,
    and rightly so.

So neither branch of the existing choice is honest, and ``allow_exploration=True`` is
the worst of the three: it does not make the confound go away, it stops mentioning it.

**The resolution: prove invariance instead of requiring emptiness.** The guard's real
concern is that the volatile state *moves between cells*. A rich connection whose state
is provably IDENTICAL for every cell carries no confound — the state is a constant, and
a constant cannot explain a difference. This module captures a fingerprint of everything
volatile before the grid, suppresses the writers that would move it, and re-verifies
afterwards. A fingerprint that moved voids the measurement loudly rather than letting a
number through that nobody can attribute.

Two things this covers that the original guard does not:

* **The context graph.** Wave L1 made the graph a live-mutating input — every answer
  writes a `finding` node. So a two-cell readback grid would have the second cell
  reading a graph the first cell grew, which is precisely the confound the guard
  exists to prevent, arriving through a door it does not watch.
* **Prevention, not just detection.** Restoring after the fact still leaves cell 2
  having read cell 1's writes. The writers are suppressed for the duration instead, so
  the drift never happens.

Suppression is deliberately narrow: it stops the *measurement-time* graph writes
(`note_finding`/`note_brief`), which are best-effort side effects whose absence changes
no answer. It does not touch the Ledger receipt, the answer, or anything a cell is
actually measuring.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator, Optional

from aughor.kernel.errors import tolerate

#: True while a measured grid is in force. Read by the live graph writers so a
#: measurement cannot grow the very artifact it is measuring the effect of reading.
#: A ContextVar (not a global) so it is per-run and propagates through the repo's
#: context-preserving executor into fan-out threads.
_MEASURING: ContextVar[bool] = ContextVar("aughor_measurement_frozen", default=False)


def measurement_frozen() -> bool:
    """True iff a frozen measurement is in force in this context."""
    return bool(_MEASURING.get())


@dataclass
class FrozenState:
    """The pinned volatile state of a connection, and whether it held."""

    connection_id: str
    fingerprint: dict = field(default_factory=dict)
    verified: bool = False
    drift: list[str] = field(default_factory=list)

    @property
    def digest(self) -> str:
        return _digest(self.fingerprint)


class SemanticDriftError(RuntimeError):
    """The pinned state moved during a measured run, so the result is unattributable."""


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def graph_state(connection_id: str, org_id: Optional[str] = None) -> dict:
    """The context graph's contribution to the volatile fingerprint.

    Version, node and edge counts per schema — enough that any write shows up (a write
    always bumps `version` via `save_graph`), without hashing a megabyte of JSON on
    every probe.
    """
    out: dict = {}
    try:
        from aughor.org.context import current_org_id
        from aughor.ontology.context_graph_store import load_graphs_for_connection

        org = org_id or current_org_id()
        for g in load_graphs_for_connection(org, connection_id):
            out[g.schema_name or "_default"] = {
                "version": int(getattr(g, "version", 0)),
                "nodes": len(g.nodes),
                "edges": len(g.edges),
            }
    except Exception as exc:
        tolerate(exc, "frozen-state probe: context graph unreadable",
                 counter="evals.frozen.graph")
    return out


def full_semantic_state(connection_id: str, org_id: Optional[str] = None) -> dict:
    """Everything volatile that steers an answer: the original guard's probes plus the
    context graph, which Wave L1 turned into a live-mutating input."""
    from aughor.evals.experiments import volatile_semantic_state

    state = dict(volatile_semantic_state(connection_id))
    state["graph"] = graph_state(connection_id, org_id)
    return state


def _diff(before: dict, after: dict) -> list[str]:
    """Human-readable drift lines — a bare 'the hash changed' is not actionable."""
    drift: list[str] = []
    for key in sorted(set(before) | set(after)):
        b, a = before.get(key), after.get(key)
        if b != a:
            drift.append(f"{key}: {b!r} → {a!r}")
    return drift


@contextmanager
def frozen_semantics(connection_id: str, *, org_id: Optional[str] = None,
                     strict: bool = True) -> Iterator[FrozenState]:
    """Pin a connection's volatile semantic state for the duration of the block.

    On entry the state is fingerprinted and the measurement-time graph writers are
    suppressed. On exit it is re-probed: if anything moved, ``strict`` raises
    :class:`SemanticDriftError` (the default — an unattributable number is worse than
    no number) and otherwise records the drift on the yielded state.

    This is what makes a RICH connection measurable. It is not a way to silence the
    guard: the guarantee it provides ("the state was identical for every cell") is
    strictly stronger than the one the guard checks ("the state is empty"), which is
    why `run_experiment(freeze=True)` may stand down the emptiness check while this is
    in force.
    """
    state = FrozenState(connection_id=connection_id,
                        fingerprint=full_semantic_state(connection_id, org_id))
    token = _MEASURING.set(True)
    try:
        yield state
    finally:
        _MEASURING.reset(token)
        after = full_semantic_state(connection_id, org_id)
        state.drift = _diff(state.fingerprint, after)
        state.verified = not state.drift

    if state.drift and strict:
        raise SemanticDriftError(
            f"the pinned semantic state of {connection_id!r} moved during a measured "
            f"run, so its cells were not comparable and the result cannot be "
            f"attributed to the variant: " + "; ".join(state.drift)
        )
