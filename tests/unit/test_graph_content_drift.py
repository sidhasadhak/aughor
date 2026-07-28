"""Wave N2 — "Fresh" must not stand over a graph missing what the platform has learned.

The gap this closes was found by looking at the rendered panel, not the code. On the
reference connection it showed **Fresh** next to **0 Findings**, while the same connection
held 793 answer receipts and a projection would have produced 100 finding nodes and 255
glossary terms against the committed 3.

Nothing had lied. C3's classifier answers "does the schema still match", and no column had
changed. But a person reading a Fresh badge hears "up to date", and the cause is structural:
the live path writes INCREMENTALLY, so projection fixes and grown sources only land on a full
rebuild, and nothing was watching for that. So this is an additive axis, deliberately NOT a
new state in the kernel's fresh/dirty/stale/unknown vocabulary.
"""
from __future__ import annotations

from aughor.ontology.graph_freshness import ContentDrift, content_drift


def test_missing_reports_only_shortfalls():
    d = ContentDrift(committed={"table": 18, "finding": 0, "glossary_term": 3},
                     available={"table": 18, "finding": 100, "glossary_term": 255})
    assert d.missing == {"finding": 100, "glossary_term": 252}
    assert d.drifted


def test_a_graph_that_carries_everything_is_not_drifted():
    d = ContentDrift(committed={"table": 18, "finding": 100},
                     available={"table": 18, "finding": 100})
    assert d.missing == {} and not d.drifted


def test_a_committed_graph_with_MORE_than_the_projection_is_not_drift():
    """Findings age out of the projection's newest-first window while staying in the
    committed artifact. That is the bound doing its job, not a shortfall — reporting it as
    drift would nag for a rebuild that DELETES nodes."""
    d = ContentDrift(committed={"finding": 100}, available={"finding": 80})
    assert d.missing == {} and not d.drifted


def test_no_committed_graph_is_reported_as_such_not_as_drift(monkeypatch):
    monkeypatch.setattr("aughor.ontology.context_graph_store.load_graphs_for_connection",
                        lambda org, conn: [])
    d = content_drift("nope", org_id="default")
    assert not d.drifted
    assert "no committed graph" in d.reason


def test_a_failed_projection_says_so_rather_than_reporting_no_drift(monkeypatch):
    """A drift check that cannot build must not answer "nothing missing" — that is the
    silent-success shape the L-wave kept catching."""
    class _G:
        def counts(self):
            return {"table": 3}

    monkeypatch.setattr("aughor.ontology.context_graph_store.load_graphs_for_connection",
                        lambda org, conn: [_G()])
    monkeypatch.setattr("aughor.ontology.context_graph_search.merge_graphs", lambda gs: _G())
    monkeypatch.setattr("aughor.ontology.context_graph_build.build_context_graph",
                        lambda *a, **k: None)
    d = content_drift("c1", org_id="default")
    assert not d.drifted
    assert "could not project" in d.reason
    assert d.committed == {"table": 3}, "what IS known is still reported"


def test_the_drift_check_does_not_require_graph_build_to_be_enabled(monkeypatch):
    """`graph.build` gates WRITING the artifact. Asking "is a rebuild owed?" must not require
    the operator to have already turned on the thing they are being advised to run — that
    would hide the shortfall from exactly the connection most likely to have one."""
    seen: dict = {}

    class _G:
        def counts(self):
            return {"finding": 0}

    class _Fresh:
        def counts(self):
            return {"finding": 100}

    def _fake_build(conn, schema, *, org_id=None, persist=True):
        from aughor.kernel.flags import flag_enabled
        seen["build_flag"] = flag_enabled("graph.build")
        seen["persist"] = persist
        return _Fresh()

    monkeypatch.setattr("aughor.ontology.context_graph_store.load_graphs_for_connection",
                        lambda org, conn: [_G()])
    monkeypatch.setattr("aughor.ontology.context_graph_search.merge_graphs", lambda gs: _G())
    monkeypatch.setattr("aughor.ontology.context_graph_build.build_context_graph", _fake_build)

    d = content_drift("c1", org_id="default")
    assert seen["build_flag"] is True, "the projection is forced on for the comparison"
    assert seen["persist"] is False, "a drift CHECK must never write the artifact"
    assert d.missing == {"finding": 100}


def test_drift_is_not_a_staleness_state():
    """The kernel vocabulary stays fresh/dirty/stale/unknown. Adding a fifth state would
    ripple through every consumer of StalenessState to express something orthogonal."""
    from aughor.kernel.freshness import StalenessState
    import typing

    assert set(typing.get_args(StalenessState)) == {"fresh", "dirty", "stale", "unknown"}
