"""Catalog-delete cascade — deleting a connection must purge its whole intelligence
footprint, leaving no orphaned profile / investigation / monitor / pack / upload.

Two layers:
  • the per-store ``purge_connection`` helpers each delete by connection id, and
  • ``purge_connection_artifacts`` fans out across every store and returns an
    observable count summary (the cascade must actually RUN, not silently no-op).

Hermetic: every store's on-disk path is redirected to a tmp dir.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect every connection-keyed store + the upload root to tmp."""
    from aughor.briefs import store as brief_store
    from aughor.db import history, purge, type_overrides
    from aughor.evidence import store as evidence_store
    from aughor.monitors import store as monitor_store
    from aughor.packs import bindings, deltastore
    from aughor.knowledge import briefing
    from aughor.platform import vending
    from aughor.profile import store as profile_store
    from aughor.semantic import connection_kb

    data = tmp_path / "data"
    data.mkdir()
    (data / "api_sync").mkdir()
    monkeypatch.setattr(purge, "_DATA_DIR", data)
    monkeypatch.setattr(profile_store, "_DATA_DIR", data)
    monkeypatch.setattr(briefing, "_CACHE_PATH", data / "briefing_cache.json")
    monkeypatch.setattr(connection_kb, "_DATA_DIR", data)
    monkeypatch.setattr(brief_store, "_PATH", data / "brief_subscriptions.json")
    monkeypatch.setattr(type_overrides, "_OVERRIDES_FILE", data / "type_overrides.json")
    monkeypatch.setattr(monitor_store, "_DB_PATH", data / "monitors.db")
    monkeypatch.setattr(history, "_DB_PATH", str(data / "history.db"))
    monkeypatch.setattr(evidence_store, "_DB_PATH", data / "evidence.db")
    monkeypatch.setattr(bindings, "_DB_PATH", data / "pack_bindings.db")
    monkeypatch.setattr(deltastore, "_DB_PATH", data / "pack_deltas.db")
    monkeypatch.setattr(vending, "STORAGE_ROOT", data / "uploads")
    monitor_store._init_schema()  # monitors inits its schema once at import; redo for the tmp DB
    return data


def test_store_helpers_delete_by_connection(isolated):
    from aughor.db import history, type_overrides
    from aughor.evidence import store as evidence_store
    from aughor.evidence.models import EvidenceClaim
    from aughor.monitors import store as monitor_store
    from aughor.monitors.models import Monitor

    # type override
    type_overrides.set_override("c1", "orders", "amount", "DOUBLE")
    type_overrides.set_override("c2", "orders", "amount", "DOUBLE")
    assert type_overrides.purge_connection("c1") is True
    assert type_overrides.get_override("c1", "orders", "amount") is None
    assert type_overrides.get_override("c2", "orders", "amount") == "DOUBLE"  # other conn untouched

    # investigations + evidence
    inv1 = history.create_investigation("why?", "c1")
    history.create_investigation("why?", "c2")
    evidence_store.append_claim(EvidenceClaim(
        investigation_id=inv1, claim_text="x", confidence=0.9))
    ids = history.list_investigation_ids("c1", limit=1000)
    assert inv1 in ids
    assert evidence_store.purge_investigations(ids) == 1
    assert history.purge_connection("c1") == 1
    assert len(history.list_investigation_ids("c2", limit=1000)) == 1  # other conn untouched

    # monitors
    monitor_store.upsert_monitor(Monitor(conn_id="c1", name="rev drop"))
    monitor_store.upsert_monitor(Monitor(conn_id="c2", name="keep me"))
    assert monitor_store.purge_connection("c1") == 1
    assert monitor_store.purge_connection("c2") == 1


def test_cascade_purges_everything_and_reports_counts(isolated):
    from aughor.db import history, purge, type_overrides
    from aughor.evidence import store as evidence_store
    from aughor.evidence.models import EvidenceClaim
    from aughor.monitors import store as monitor_store
    from aughor.monitors.models import Monitor
    from aughor.packs import bindings

    conn = "cat_to_delete"

    # ── seed artifacts across stores ─────────────────────────────────────────────
    (isolated / f"business_profile_{conn}.json").write_text("{}")
    (isolated / f"exploration_{conn}__main.json").write_text("{}")
    (isolated / f"episodes_{conn}__main.jsonl").write_text("")
    (isolated / f"knowledge_{conn}.json").write_text("[]")
    (isolated / f"annotations_{conn}.json").write_text("{}")
    (isolated / f"benchmarks_{conn}.json").write_text("[]")
    (isolated / f"sync_state_{conn}.json").write_text("{}")
    type_overrides.set_override(conn, "t", "c", "DOUBLE")
    inv9 = history.create_investigation("q", conn)
    evidence_store.append_claim(EvidenceClaim(
        investigation_id=inv9, claim_text="x", confidence=0.5))
    monitor_store.upsert_monitor(Monitor(conn_id=conn, name="rev drop"))
    bindings.save_binding("pack1", conn, {"role": {"table": "t"}})

    import json
    from aughor.knowledge import briefing
    briefing._CACHE_PATH.write_text(json.dumps({
        conn: {"briefing": "x"},                 # connection-level entry
        f"{conn}:main": {"briefing": "y"},        # schema-scoped entry
        "other_conn": {"briefing": "z"},          # another connection — must survive
    }))

    # uploaded data dir
    from aughor.platform.vending import vend_storage
    root = vend_storage(conn).root
    (root / "main").mkdir(parents=True)
    (root / "main" / "sales.csv").write_text("a,b\n1,2\n")

    # ── delete the catalog ───────────────────────────────────────────────────────
    counts = purge.purge_connection_artifacts(conn)

    # ── everything is gone ───────────────────────────────────────────────────────
    leftovers = list(isolated.glob(f"*{conn}*"))
    assert leftovers == [], f"orphaned artifacts: {leftovers}"
    assert not root.exists()
    assert type_overrides.get_override(conn, "t", "c") is None
    assert history.list_investigation_ids(conn, limit=1000) == []

    # ── the cascade is OBSERVABLE (it actually ran) ──────────────────────────────
    assert counts["upload_dir"] == 1
    assert counts["exploration"] == 1
    assert counts["episodes"] == 1
    assert counts["knowledge"] == 1
    assert counts["annotations"] == 1
    assert counts["benchmarks"] == 1
    assert counts["sync_state"] == 1
    assert counts["type_overrides"] == 1
    assert counts["investigations"] == 1
    assert counts["evidence_claims"] == 1
    assert counts["monitors"] == 1
    assert counts["pack_bindings"] == 1
    assert counts["briefing_cache"] == 2  # conn-level + schema-scoped, other_conn kept
    import json
    surviving = json.loads(briefing._CACHE_PATH.read_text())
    assert set(surviving) == {"other_conn"}


def test_cascade_is_idempotent(isolated):
    from aughor.db import purge
    # Purging a connection that never existed is a clean no-op, not an error.
    counts = purge.purge_connection_artifacts("never_existed")
    assert counts.get("investigations", 0) == 0
    assert counts.get("upload_dir", 0) == 0
