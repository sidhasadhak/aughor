"""Wave L2 — the frozen measurement connection.

The harness exists because both existing options were dishonest for a flag like
`graph.readback`: an unexplored connection measures it where it has nothing to read,
and `allow_exploration=True` does not remove the confound, it stops mentioning it.
These tests pin the property that makes the third option legitimate — the state was
IDENTICAL for every cell, verified, not assumed.
"""
from __future__ import annotations

import pytest

from aughor.evals import frozen as F


def test_writes_are_suppressed_only_inside_the_pin():
    assert F.measurement_frozen() is False
    with F.frozen_semantics("c1"):
        assert F.measurement_frozen() is True
    assert F.measurement_frozen() is False


def test_the_pin_is_released_even_when_the_grid_raises():
    """A cell that blew up must not leave every later answer silently unable to write
    to the graph."""
    with pytest.raises(ValueError):
        with F.frozen_semantics("c1"):
            raise ValueError("cell exploded")
    assert F.measurement_frozen() is False


def test_a_stable_connection_verifies(monkeypatch):
    monkeypatch.setattr(F, "full_semantic_state",
                        lambda conn, org=None: {"exploration_bytes": 6309,
                                                "graph": {"main": {"version": 3}}})
    with F.frozen_semantics("rich") as state:
        pass
    assert state.verified and state.drift == []
    # rich, and still measurable — that is the whole point
    assert state.fingerprint["exploration_bytes"] == 6309


def test_drift_voids_the_run_and_names_what_moved(monkeypatch):
    """An unattributable number is worse than no number, so this raises rather than
    warning — and it says WHICH input moved, because 'the hash changed' is not
    actionable."""
    seq = iter([
        {"exploration_bytes": 10, "graph": {"main": {"version": 3, "nodes": 100}}},
        {"exploration_bytes": 10, "graph": {"main": {"version": 4, "nodes": 101}}},
    ])
    monkeypatch.setattr(F, "full_semantic_state", lambda conn, org=None: next(seq))

    with pytest.raises(F.SemanticDriftError) as exc:
        with F.frozen_semantics("c1"):
            pass
    assert "graph" in str(exc.value) and "'version': 4" in str(exc.value)


def test_non_strict_records_drift_instead_of_raising(monkeypatch):
    seq = iter([{"exploration_bytes": 1}, {"exploration_bytes": 2}])
    monkeypatch.setattr(F, "full_semantic_state", lambda conn, org=None: next(seq))
    with F.frozen_semantics("c1", strict=False) as state:
        pass
    assert not state.verified and state.drift


def test_the_fingerprint_covers_the_context_graph():
    """Wave L1 made the graph a live-mutating input — every answer writes a `finding`
    node. The original guard does not look at it, so a readback grid would have cell 2
    reading a graph cell 1 grew: the exact confound, through a door nobody watched."""
    assert "graph" in F.full_semantic_state("c1")


def test_graph_writes_no_op_while_frozen(tmp_path, monkeypatch):
    """The end-to-end property: a measured answer cannot grow the artifact whose
    effect is being measured."""
    from aughor.ontology import context_graph_store as store
    from aughor.ontology import context_graph_build as build_mod
    from tests.unit.test_context_graph import _build, _L1_FINDING

    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    store.save_graph(_build())
    before = store.graph_path("org1", "c1", "main").read_bytes()

    with F.frozen_semantics("c1", strict=False):
        assert build_mod.note_finding("c1", _L1_FINDING, org_id="org1") is False
        assert build_mod.note_brief("c1", {"id": "c1", "text": "b"},
                                    org_id="org1") is False
    assert store.graph_path("org1", "c1", "main").read_bytes() == before

    # and writes resume afterwards — suppression is scoped, not a kill switch
    assert build_mod.note_finding("c1", _L1_FINDING, org_id="org1") is True
