"""Flywheel delta store (Bet 1 safe writeback, 2026-06-27).

A steered+verified run proposes deltas here; a human accepts/dismisses (never auto-applied).
Org-scoped, dedup'd. See aughor/packs/deltastore.py.
"""
import pytest

import aughor.packs.deltastore as ds
from aughor.packs.flywheel import PackDelta
from aughor.org.context import using_org


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "_DB_PATH", tmp_path / "pack_deltas.db")
    return ds


def _deltas():
    return [
        PackDelta(kind="caveat", target="tickets.days_to_departure", content="has negatives", confidence=0.6),
        PackDelta(kind="diagnostic", target="", content="check acquisition-mix shift", confidence=0.7),
    ]


def test_record_and_list(store):
    with using_org("default"):
        n = store.record_deltas("customer-analytics", "workspace", _deltas(), source_run="inv1")
        assert n == 2
        rows = store.list_deltas("customer-analytics")
        assert len(rows) == 2
        assert {r["kind"] for r in rows} == {"caveat", "diagnostic"}


def test_dedup_same_learning(store):
    with using_org("default"):
        store.record_deltas("ca", "c", _deltas())
        again = store.record_deltas("ca", "c", _deltas())   # identical → no new rows
        assert again == 0
        assert len(store.list_deltas("ca")) == 2


def test_accept_and_dismiss(store):
    with using_org("default"):
        store.record_deltas("ca", "c", _deltas())
        d = store.list_deltas("ca")[0]
        assert store.set_delta_status(d["id"], "accepted")
        assert len(store.list_deltas("ca", status="proposed")) == 1
        assert len(store.list_deltas("ca", status="accepted")) == 1


def test_bad_status_raises(store):
    with using_org("default"):
        with pytest.raises(ValueError):
            store.set_delta_status(1, "loved-it")


def test_org_scoped(store):
    with using_org("org-a"):
        store.record_deltas("ca", "c", _deltas())
    with using_org("org-b"):
        assert store.list_deltas("ca") == []
