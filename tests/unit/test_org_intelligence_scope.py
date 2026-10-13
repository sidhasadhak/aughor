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
                        lambda collection, limit=10_000, strict=False: list(_POINTS))


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


# ── a store that could not be read or written is said, never answered as "none" (2026-10-13) ───────────────────────

def test_a_store_that_could_not_be_read_is_said_not_listed_as_empty(monkeypatch):
    """Org said "Nothing promoted yet" over an outage: the read swallowed the failure into []."""
    import pytest

    from aughor.knowledge.org_intelligence import OrgIntelUnavailable, list_org_intelligence

    def down(collection, limit=10_000, strict=False):
        if strict:
            raise ConnectionError("qdrant refused the connection")
        return []
    monkeypatch.setattr("aughor.semantic.vector_store.scroll_points", down)
    with pytest.raises(OrgIntelUnavailable):
        list_org_intelligence()


def test_a_collection_never_created_is_still_empty():
    from aughor.semantic.vector_store import _collection_missing
    assert _collection_missing(RuntimeError("Not found: Collection `org_intelligence` doesn't exist!"))
    assert not _collection_missing(ConnectionError("connection refused"))


def test_a_promotion_org_could_not_store_is_refused_and_the_finding_is_not_flagged(monkeypatch):
    """The Briefing said "Promoted ✓" over a finding Org never received: the flag was set first and a failed Org write
    swallowed. Org is written first now; a failed write is a 503 with why, and the finding stays unflagged."""
    import pytest
    from fastapi import HTTPException

    from aughor.explorer import store
    from aughor.knowledge import org_intelligence
    from aughor.routers.exploration import promote_connection_finding

    finding = {"id": "f1", "finding": "Returns rose", "domain": "Sales"}
    monkeypatch.setattr(store, "find_connection_finding", lambda conn, fid: finding)
    flagged: list[str] = []
    monkeypatch.setattr(store, "promote_insight_conn", lambda conn, fid: flagged.append(fid) or finding)

    def refuse(**_):
        raise org_intelligence.OrgIntelUnavailable("no semantic index is available on this install")
    monkeypatch.setattr(org_intelligence, "promote_to_org", refuse)
    with pytest.raises(HTTPException) as said:
        promote_connection_finding("c1", "f1")
    assert said.value.status_code == 503 and "Not promoted" in said.value.detail and flagged == []

    stored: list[str] = []
    monkeypatch.setattr(org_intelligence, "promote_to_org", lambda **kw: stored.append(kw["insight_id"]) or {})
    assert promote_connection_finding("c1", "f1") == {"insight_id": "f1", "promoted": True}
    assert stored == ["f1"] and flagged == ["f1"]

