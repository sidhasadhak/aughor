"""Human-verdict store (Bet 0, 0-V, 2026-06-27).

The non-circular ground truth the trust economy calibrates against. Org-scoped, validated,
acceptance rate credits accept fully and 'correct' at half. See aughor/verify/verdicts.py.
"""

import pytest

from aughor.org.context import using_org
import aughor.verify.verdicts as vd


@pytest.fixture
def store(tmp_path, monkeypatch):
    # Isolate the SQLite file per test so we never touch data/verdicts.db.
    monkeypatch.setattr(vd, "_DB_PATH", tmp_path / "verdicts.db")
    return vd


def test_record_and_stats(store):
    store.record_verdict("conn1", "inv1", "accept", headline="refunds are flat")
    store.record_verdict("conn1", "inv2", "accept")
    store.record_verdict("conn1", "inv3", "correct")
    store.record_verdict("conn1", "inv4", "reject")
    s = store.verdict_stats("conn1")
    assert s["counts"] == {"accept": 2, "correct": 1, "reject": 1}
    assert s["total"] == 4
    # acceptance = (2 + 0.5*1) / 4 = 0.625
    assert s["acceptance_rate"] == 0.625


def test_invalid_verdict_raises(store):
    with pytest.raises(ValueError):
        store.record_verdict("c", "i", "love-it")


def test_stats_empty_is_safe(store):
    s = store.verdict_stats("nope")
    assert s["total"] == 0
    assert s["acceptance_rate"] is None


def test_org_scoping_isolates_verdicts(store):
    with using_org("org-a"):
        store.record_verdict("c", "i1", "accept")
    with using_org("org-b"):
        store.record_verdict("c", "i2", "reject")
        assert store.verdict_stats("c")["counts"]["accept"] == 0   # org-b can't see org-a's
        assert store.verdict_stats("c")["counts"]["reject"] == 1
    with using_org("org-a"):
        assert store.verdict_stats("c")["counts"]["accept"] == 1


def test_list_is_most_recent_first(store):
    store.record_verdict("c", "i1", "accept")
    store.record_verdict("c", "i2", "reject")
    rows = store.list_verdicts("c")
    assert [r["investigation_id"] for r in rows] == ["i2", "i1"]
