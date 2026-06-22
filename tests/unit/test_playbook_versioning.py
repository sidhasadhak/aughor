"""Governed Dives — immutable versioning + receipt-binding on the playbook store.

A play's edit history is frozen and auditable; versions move only when the ADVICE moves,
not when bookkeeping (success rate / status) does. A finding that cited version N always
resolves to exactly what version N said."""
from __future__ import annotations

from aughor.playbook.models import PlaybookEntry
from aughor.playbook.store import (
    save_entry, get_entry, compute_receipt, list_versions, get_version, emit_playbook_use,
)


def _entry(**kw):
    base = dict(id="p1", trigger_metric="refund_rate", trigger_condition="above target",
                recommendation="Tighten the returns window")
    base.update(kw)
    return PlaybookEntry(**base)


def test_new_entry_gets_version_1_and_receipt(tmp_path):
    p = tmp_path / "playbook.json"
    e = _entry()
    save_entry(e, p)
    assert e.version == 1 and e.receipt.startswith("pbk_") and e.updated_at
    snaps = list_versions("p1", p)
    assert len(snaps) == 1 and snaps[0]["version"] == 1 and snaps[0]["receipt"] == e.receipt


def test_content_edit_bumps_version_and_logs_snapshot(tmp_path):
    p = tmp_path / "playbook.json"
    save_entry(_entry(), p)
    r1 = get_entry("p1", p).receipt
    save_entry(_entry(recommendation="Offer store credit instead of refunds"), p)
    cur = get_entry("p1", p)
    assert cur.version == 2 and cur.receipt != r1
    assert [s["version"] for s in list_versions("p1", p)] == [1, 2]


def test_meta_only_save_does_not_bump_version(tmp_path):
    # outcomes refreshing the success rate / promoting draft→active must NOT make a new version
    p = tmp_path / "playbook.json"
    save_entry(_entry(), p)
    e = get_entry("p1", p)
    v1, r1 = e.version, e.receipt
    e.historical_success_rate = 0.8
    e.status = "active"
    save_entry(e, p)
    cur = get_entry("p1", p)
    assert cur.version == v1 and cur.receipt == r1                  # the pin is preserved
    assert len(list_versions("p1", p)) == 1                         # no new snapshot
    assert cur.historical_success_rate == 0.8 and cur.status == "active"   # meta still persisted


def test_old_version_content_is_immutable(tmp_path):
    p = tmp_path / "playbook.json"
    save_entry(_entry(recommendation="ORIGINAL advice"), p)
    save_entry(_entry(recommendation="REVISED advice"), p)
    assert get_version("p1", 1, p)["content"]["recommendation"] == "ORIGINAL advice"  # frozen
    assert get_version("p1", 2, p)["content"]["recommendation"] == "REVISED advice"


def test_receipt_is_content_only():
    a = _entry(historical_success_rate=0.1, status="draft", evidence_sources=["i1"])
    b = _entry(historical_success_rate=0.9, status="active", evidence_sources=["i2", "i3"])
    assert compute_receipt(a) == compute_receipt(b)                 # meta differs, content same
    assert compute_receipt(_entry(recommendation="different")) != compute_receipt(a)


def test_emit_playbook_use_fail_open():
    emit_playbook_use(_entry(), used_in="test")                    # must not raise (hermetic ledger)
