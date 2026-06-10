"""K0 Ledger invariants — the kernel's transactional state store.

The headline test is the concurrency hammer: the unlocked load→mutate→save
round-trip in the old JSON stores made concurrent puts silently drop each
other's writes (the confirmed ontology/profile cache race, WCH-3). Under the
ledger that loss is impossible by construction — the hammer proves it.
"""
import json
import threading

import pytest

from aughor.kernel.ledger import Ledger
from aughor.util.json_store import KeyedJsonStore


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


# ── kv semantics (parity with the old KeyedJsonStore behaviour) ───────────────

class TestKvSemantics:
    def test_roundtrip(self, ledger):
        ledger.kv_put("s", "a", {"x": 1})
        assert ledger.kv_get("s", "a") == {"x": 1}
        assert ledger.kv_get("s", "missing") is None
        assert ledger.kv_get("s", "missing", 42) == 42

    def test_stores_are_isolated(self, ledger):
        ledger.kv_put("s1", "k", 1)
        ledger.kv_put("s2", "k", 2)
        assert ledger.kv_get("s1", "k") == 1
        assert ledger.kv_get("s2", "k") == 2

    def test_lru_eviction(self, ledger):
        for k, v in (("a", 1), ("b", 2), ("c", 3)):
            ledger.kv_put("s", k, v, max_entries=2)
        assert set(ledger.kv_load_all("s")) == {"b", "c"}

    def test_mru_refresh_on_reput(self, ledger):
        ledger.kv_put("s", "a", 1, max_entries=2)
        ledger.kv_put("s", "b", 2, max_entries=2)
        ledger.kv_put("s", "a", 11, max_entries=2)   # refresh a → MRU
        ledger.kv_put("s", "c", 3, max_entries=2)    # evicts b, not a
        d = ledger.kv_load_all("s")
        assert set(d) == {"a", "c"} and d["a"] == 11

    def test_load_all_oldest_first(self, ledger):
        ledger.kv_put("s", "old", 1)
        ledger.kv_put("s", "new", 2)
        assert list(ledger.kv_load_all("s")) == ["old", "new"]

    def test_replace_all_caps_to_newest(self, ledger):
        ledger.kv_replace_all("s", {"a": 1, "b": 2, "c": 3}, max_entries=2)
        assert list(ledger.kv_load_all("s")) == ["b", "c"]

    def test_invalidate_prefix(self, ledger):
        ledger.kv_put("s", "c1:fp1", 1)
        ledger.kv_put("s", "c1:fp2", 2)
        ledger.kv_put("s", "c2:fp", 3)
        assert ledger.kv_invalidate_prefix("s", "c1:") == 2
        assert set(ledger.kv_load_all("s")) == {"c2:fp"}


# ── the race that motivated K0 ────────────────────────────────────────────────

class TestConcurrency:
    def test_concurrent_puts_lose_nothing(self, ledger):
        """8 threads × 50 puts to one store: with the old file store, concurrent
        load→save round-trips silently dropped each other's keys. The ledger
        must retain every key with its exact value."""
        errors = []

        def worker(t):
            try:
                for i in range(50):
                    ledger.kv_put("hammer", f"t{t}:k{i}", {"t": t, "i": i})
            except Exception as e:        # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for th in threads: th.start()
        for th in threads: th.join()

        assert not errors
        data = ledger.kv_load_all("hammer")
        assert len(data) == 8 * 50
        assert data["t3:k17"] == {"t": 3, "i": 17}

    def test_concurrent_puts_with_eviction_keep_cap(self, ledger):
        def worker(t):
            for i in range(40):
                ledger.kv_put("capped", f"t{t}:k{i}", i, max_entries=10)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for th in threads: th.start()
        for th in threads: th.join()
        assert len(ledger.kv_load_all("capped")) == 10


# ── facade: legacy migration + fallback contract ──────────────────────────────

class TestFacadeMigration:
    def test_legacy_json_imported_once(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "sys.db"))
        Ledger._instances.clear()
        legacy = tmp_path / "ontology_cache.json"
        legacy.write_text(json.dumps({"conn:fp": {"entities": 3}}))
        s = KeyedJsonStore(legacy, max_entries=5)
        assert s.get("conn:fp") == {"entities": 3}          # imported
        assert legacy.exists()                              # original untouched
        # Emptying the store must NOT resurrect the legacy file on next read
        s.save({})
        assert KeyedJsonStore(legacy).load() == {}

    def test_corrupt_legacy_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "sys.db"))
        Ledger._instances.clear()
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        assert KeyedJsonStore(bad).load() == {}

    def test_facade_full_parity_suite(self, tmp_path, monkeypatch):
        """The original json_store behaviours, through the ledger backend."""
        monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "sys.db"))
        Ledger._instances.clear()
        s = KeyedJsonStore(tmp_path / "k.json", max_entries=2)
        s.put("a", 1); s.put("b", 2); s.put("a", 11); s.put("c", 3)
        d = s.load()
        assert set(d) == {"a", "c"} and d["a"] == 11


# ── the event journal ─────────────────────────────────────────────────────────

class TestEvents:
    def test_emit_and_query(self, ledger):
        s1 = ledger.emit("job.state", {"state": "RUNNING"}, conn_id="c1", job_id="j1")
        s2 = ledger.emit("job.state", {"state": "FAILED"}, conn_id="c1", job_id="j1")
        ledger.emit("artifact.written", {"kind": "finding"}, conn_id="c2")
        assert s2 > s1
        evs = ledger.events(kind="job.state")
        assert len(evs) == 2
        assert evs[0]["payload"]["state"] == "FAILED"       # newest first
        assert ledger.events(conn_id="c2")[0]["kind"] == "artifact.written"

    def test_since_seq_pagination(self, ledger):
        first = ledger.emit("tick", {"n": 1})
        ledger.emit("tick", {"n": 2})
        newer = ledger.events(since_seq=first)
        assert len(newer) == 1 and newer[0]["payload"]["n"] == 2


# ── K3: artifacts + lineage + the Trust Receipt ───────────────────────────────

class TestArtifacts:
    def test_versioning_supersedes_never_deletes(self, ledger):
        a1 = ledger.artifact_write("finding", "insight:c1:rev_drop", {"finding": "v1"})
        a2 = ledger.artifact_write("finding", "insight:c1:rev_drop", {"finding": "v2"})
        latest = ledger.artifact_latest("insight:c1:rev_drop")
        assert latest["id"] == a2 and latest["version"] == 2
        assert latest["payload"]["finding"] == "v2"
        # v1 survives, marked superseded — preserve-artifacts at schema level
        with ledger._lock:
            row = ledger._conn.execute(
                "SELECT version, superseded_by FROM artifacts WHERE id=?", (a1,)
            ).fetchone()
        assert row == (1, a2)

    def test_receipt_joins_lineage_and_job(self, ledger):
        ledger.job_insert({
            "id": "job1", "kind": "exploration", "conn_id": "c1",
            "state": "SUCCEEDED", "attempt": 1,
            "created_at": "2026-06-10T00:00:00+00:00",
            "started_at": "2026-06-10T00:00:01+00:00",
            "finished_at": "2026-06-10T00:05:00+00:00",
        })
        ledger.artifact_write(
            "finding", "insight:c1:aov", {"finding": "AOV is $19.94"},
            conn_id="c1", created_by_job="job1",
            lineage=[("source_sql", "sql", "SELECT AVG(totalPrice) FROM t"),
                     ("input", "table:bakehouse.sales_transactions", None),
                     ("validated_by", "guard:numeric_grounding", "ok")],
        )
        rec = ledger.receipt("insight:c1:aov")
        assert rec["artifact"]["payload"]["finding"] == "AOV is $19.94"
        assert rec["job"]["id"] == "job1" and rec["job"]["state"] == "SUCCEEDED"
        rels = {e["relation"] for e in rec["lineage"]}
        assert rels == {"source_sql", "input", "validated_by"}
        assert any("SELECT AVG" in (e["detail"] or "") for e in rec["lineage"])

    def test_receipt_missing_returns_none(self, ledger):
        assert ledger.receipt("insight:none:nothing") is None


class TestJobContextStamping:
    def test_artifact_written_inside_job_gets_job_id(self, ledger):
        import asyncio
        from aughor.kernel.jobs import JobKernel, current_job_id

        captured = {}

        async def main():
            k = JobKernel(ledger)

            async def work():
                captured["jid"] = current_job_id()
                ledger.artifact_write(
                    "finding", "insight:c1:ctx", {"x": 1},
                    created_by_job=current_job_id(),
                )

            jid = await k.submit("exploration", work, conn_id="c1")
            while jid in k._tasks:
                await asyncio.sleep(0.01)
            return jid

        jid = asyncio.run(main())
        assert captured["jid"] == jid
        assert ledger.artifact_latest("insight:c1:ctx")["created_by_job"] == jid
        assert current_job_id() is None   # context reset outside the job
