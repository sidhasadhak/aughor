"""Delete-investigation cascade (user feature + audit follow-up).

Deleting an investigation must take its WHOLE footprint with it — the history
row, its evidence claims, and (best-effort) its RAG vector entry — not just the
history row, which previously left the investigation steering future analysis via
prior-analyses search and orphaned its evidence.

Hermetic: history + evidence stores redirected to tmp; the vector index is
absent, so the qdrant step is a guarded no-op (delete_by_filter returns 0)."""
from __future__ import annotations

import pytest


@pytest.fixture
def stores(tmp_path, monkeypatch):
    from aughor.db import history
    from aughor.evidence import store as evidence_store

    monkeypatch.setattr(history, "_DB_PATH", str(tmp_path / "history.db"))
    monkeypatch.setattr(evidence_store, "_DB_PATH", tmp_path / "evidence.db")
    return history, evidence_store


def _claim(evidence_store, inv_id: str):
    from aughor.evidence.models import EvidenceClaim
    evidence_store.append_claim(
        EvidenceClaim(investigation_id=inv_id, claim_text="x declined 12%", confidence=0.8)
    )


def test_delete_one_cascades_row_and_evidence(stores):
    history, evidence_store = stores
    from aughor.db.purge import purge_investigation_artifacts

    keep = history.create_investigation("keep me", "conn1")
    drop = history.create_investigation("drop me", "conn1")
    _claim(evidence_store, drop)
    _claim(evidence_store, keep)

    counts = purge_investigation_artifacts(drop)

    assert counts["investigations"] == 1
    assert counts["evidence_claims"] == 1
    # the dropped one is gone; the other is untouched
    assert history.get_investigation(drop) is None
    assert history.get_investigation(keep) is not None
    assert evidence_store.get_claims_for_investigation(drop) == []
    assert len(evidence_store.get_claims_for_investigation(keep)) == 1


def test_delete_missing_is_a_noop(stores):
    history, _ = stores
    from aughor.db.purge import purge_investigation_artifacts
    assert purge_investigation_artifacts("nope").get("investigations") == 0


def test_bulk_clear_all(stores):
    history, evidence_store = stores
    from aughor.db.purge import purge_investigations_bulk

    a = history.create_investigation("q1", "conn1")
    b = history.create_investigation("q2", "conn2")
    _claim(evidence_store, a)
    _claim(evidence_store, b)

    counts = purge_investigations_bulk(None)

    assert counts["investigations"] == 2
    assert counts["evidence_claims"] == 2
    assert history.all_investigation_ids() == []


def test_bulk_clear_scoped_to_connections(stores):
    history, evidence_store = stores
    from aughor.db.purge import purge_investigations_bulk

    a = history.create_investigation("q1", "conn1")
    b = history.create_investigation("q2", "conn2")
    _claim(evidence_store, a)
    _claim(evidence_store, b)

    counts = purge_investigations_bulk(["conn1"])

    assert counts["investigations"] == 1
    assert history.get_investigation(a) is None
    assert history.get_investigation(b) is not None
    # only conn1's evidence purged
    assert evidence_store.get_claims_for_investigation(a) == []
    assert len(evidence_store.get_claims_for_investigation(b)) == 1


def test_bulk_clear_empty_is_noop(stores):
    from aughor.db.purge import purge_investigations_bulk
    assert purge_investigations_bulk(None) == {}
