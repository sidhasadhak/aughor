"""Org-intelligence scoping — the Hub is a scoped surface and must not blend
every connection's (or schema's) promoted insights together; the unscoped
org-wide view is the Org layer's job.

Hermetic at the SEAM: `list_org_intelligence` reads `vector_store.scroll_points`
(S1 — it stopped building its own QdrantClient, which kept it pointed at
localhost:6333 whatever backend actually held the index), so that function is
what the fake replaces. The subject here is the scoping/sort logic, not the
backend; the seam itself is proven end-to-end in test_vector_store_embedded."""
from __future__ import annotations

_POINTS = [
    {"id": "1", "payload": {"insight_id": "a", "text": "t1", "connection_id": "conn1",
                            "schema": "sales", "promoted_at": "2026-07-02"}},
    {"id": "2", "payload": {"insight_id": "b", "text": "t2", "connection_id": "conn1",
                            "schema": "ops", "promoted_at": "2026-07-03"}},
    {"id": "3", "payload": {"insight_id": "c", "text": "t3", "connection_id": "conn2",
                            "schema": "sales", "promoted_at": "2026-07-04"}},
    # promoted before scoping existed — no connection_id/schema recorded
    {"id": "4", "payload": {"insight_id": "legacy", "text": "t4",
                            "promoted_at": "2026-07-01"}},
]


def _patched(monkeypatch):
    monkeypatch.setattr("aughor.semantic.vector_store.scroll_points",
                        lambda collection, limit=10_000: list(_POINTS))


def test_unscoped_returns_everything_newest_first(monkeypatch):
    _patched(monkeypatch)
    from aughor.knowledge.org_intelligence import list_org_intelligence

    out = list_org_intelligence()
    assert [r["insight_id"] for r in out] == ["c", "b", "a", "legacy"]


def test_connection_scope_filters(monkeypatch):
    _patched(monkeypatch)
    from aughor.knowledge.org_intelligence import list_org_intelligence

    out = list_org_intelligence(connection_id="conn1")
    assert {r["insight_id"] for r in out} == {"a", "b"}


def test_connection_and_schema_scope_filters(monkeypatch):
    _patched(monkeypatch)
    from aughor.knowledge.org_intelligence import list_org_intelligence

    out = list_org_intelligence(connection_id="conn1", schema="sales")
    assert [r["insight_id"] for r in out] == ["a"]


def test_legacy_unattributed_rows_stay_out_of_scoped_views(monkeypatch):
    """Insights promoted before scoping carry no connection_id; they appear only
    in the unscoped org-wide view, never inside another connection's Hub."""
    _patched(monkeypatch)
    from aughor.knowledge.org_intelligence import list_org_intelligence

    for conn in ("conn1", "conn2", "conn3"):
        assert all(r["insight_id"] != "legacy" for r in list_org_intelligence(connection_id=conn))
    assert any(r["insight_id"] == "legacy" for r in list_org_intelligence())
