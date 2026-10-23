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
    from aughor.briefing import store as brief_store
    from aughor.db import history, purge, type_overrides
    from aughor.evidence import store as evidence_store
    from aughor.monitors import store as monitor_store
    from aughor.packs import bindings, deltastore
    from aughor.canvas import store as canvas_store
    from aughor.explorer import watermark
    from aughor.knowledge import briefing, patterns
    from aughor.ontology import store as ontology_store
    from aughor.control_plane import vending
    from aughor.business_profile import store as profile_store
    from aughor.semantic import connection_kb
    from aughor.tools import profile_cache
    from aughor.util.json_store import KeyedJsonStore

    data = tmp_path / "data"
    data.mkdir()
    (data / "api_sync").mkdir()
    from aughor.explorer import store as explorer_store
    monkeypatch.setattr(purge, "_DATA_DIR", data)
    monkeypatch.setattr(profile_store, "_DATA_DIR", data)
    # The cascade now delegates exploration deletion to the store, so its dir must
    # point at this test's data too — the old file-glob purge never read it.
    monkeypatch.setattr(explorer_store, "_DATA_DIR", data)
    monkeypatch.setattr(briefing, "_CACHE_PATH", data / "briefing_cache.json")
    monkeypatch.setattr(patterns, "_CACHE_PATH", data / "patterns_cache.json")
    monkeypatch.setattr(connection_kb, "_DATA_DIR", data)
    monkeypatch.setattr(brief_store, "_PATH", data / "brief_subscriptions.json")
    monkeypatch.setattr(type_overrides, "_OVERRIDES_FILE", data / "type_overrides.json")
    monkeypatch.setattr(monitor_store, "_DB_PATH", data / "monitors.db")
    monkeypatch.setattr(history, "_DB_PATH", str(data / "history.db"))
    monkeypatch.setattr(evidence_store, "_DB_PATH", data / "evidence.db")
    monkeypatch.setattr(bindings, "_DB_PATH", data / "pack_bindings.db")
    monkeypatch.setattr(deltastore, "_DB_PATH", data / "pack_deltas.db")
    monkeypatch.setattr(vending, "STORAGE_ROOT", data / "uploads")
    monkeypatch.setattr(canvas_store, "_DB_PATH", data / "canvases.db")
    monkeypatch.setattr(canvas_store, "_ARTIFACT_DB_PATH", data / "artifacts.db")
    monkeypatch.setattr(watermark, "_PATH", data / "explore_watermark.json")
    monkeypatch.setattr(ontology_store, "_store", KeyedJsonStore(data / "ontology_cache.json"))
    monkeypatch.setattr(profile_cache, "_store", KeyedJsonStore(data / "schema_profiles.json"))
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
    (isolated / f"episodes_{conn}.jsonl").write_text("")          # the connection's own record
    (isolated / f"knowledge_{conn}.json").write_text("[]")
    (isolated / f"annotations_{conn}.json").write_text("{}")
    (isolated / f"benchmarks_{conn}.json").write_text("[]")
    (isolated / f"sync_state_{conn}.json").write_text("{}")
    type_overrides.set_override(conn, "t", "c", "DOUBLE")
    import time

    from aughor.db import metadata                                  # DE-3c: read once, kept per connection
    read = metadata.MetadataRead(engine="duckdb", strategy="catalog", facts={}, detail={})
    metadata._CACHE[conn] = (time.monotonic(), read)
    metadata._CACHE["other_conn"] = (time.monotonic(), read)
    inv9 = history.create_investigation("q", conn)
    evidence_store.append_claim(EvidenceClaim(
        investigation_id=inv9, claim_text="x", confidence=0.5))
    monitor_store.upsert_monitor(Monitor(conn_id=conn, name="rev drop"))
    bindings.save_binding("pack1", conn, {"role": {"table": "t"}})
    from aughor.semantic import ambiguity_ledger
    ambiguity_ledger.purge_connections([conn])  # start clean (session-shared ledger DB)
    ambiguity_ledger.crystallize_user_choice(conn, "top products", "by revenue")

    import json
    from aughor.knowledge import briefing, patterns
    briefing._CACHE_PATH.write_text(json.dumps({
        conn: {"briefing": "x"},                 # connection-level entry
        f"{conn}:main": {"briefing": "y"},        # schema-scoped entry
        "other_conn": {"briefing": "z"},          # another connection — must survive
    }))
    patterns._CACHE_PATH.write_text(json.dumps({
        conn: {"computed_at": "2026-01-01T00:00:00Z", "patterns": []},
        "other_conn": {"computed_at": "2026-01-01T00:00:00Z", "patterns": []},
    }))

    # uploaded data dir
    from aughor.control_plane.vending import vend_storage
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
    assert conn not in metadata._CACHE and metadata._CACHE.pop("other_conn", None) is not None
    assert history.list_investigation_ids(conn, limit=1000) == []

    # ── the cascade is OBSERVABLE (it actually ran) ──────────────────────────────
    assert counts["upload_dir"] == 1
    assert counts["exploration"] == 1
    # the connection's record goes WITH THE CONNECTION — both files, which is the other half
    # of the rule the schema purge keeps (see test_schema_cascade…)
    assert counts["episodes"] == 2
    assert not (isolated / f"episodes_{conn}.jsonl").exists()
    assert not (isolated / f"episodes_{conn}__main.jsonl").exists()
    assert counts["knowledge"] == 1
    assert counts["annotations"] == 1
    assert counts["benchmarks"] == 1
    assert counts["sync_state"] == 1
    assert counts["type_overrides"] == 1
    assert counts["declared_metadata"] == 1
    assert counts["investigations"] == 1
    assert counts["evidence_claims"] == 1
    assert counts["ambiguity_resolutions"] == 1
    assert ambiguity_ledger.list_resolutions(conn) == []
    assert counts["monitors"] == 1
    assert counts["pack_bindings"] == 1
    assert counts["briefing_cache"] == 2  # conn-level + schema-scoped, other_conn kept
    assert counts["patterns_cache"] == 1
    # Survivors read through the store, not the file: the caches live behind the
    # KeyedJsonStore/Ledger facade now, and the legacy file (imported once) is left
    # on disk untouched by design.
    assert set(briefing._store().load()) == {"other_conn"}
    assert set(patterns._store().load()) == {"other_conn"}


def test_schema_scoped_briefing_invalidate(isolated):
    """Removing ONE schema must drop only that schema's cached briefing — the
    connection-level entry and sibling schemas survive (the reported leak: a
    removed schema's briefing kept showing because schema-delete never cleared it)."""
    import json
    from aughor.knowledge import briefing, patterns
    briefing._CACHE_PATH.write_text(json.dumps({
        "workspace": {"b": 0},
        "workspace:missimi": {"b": 1},
        "workspace:swiss_air": {"b": 2},
    }))
    # removing a schema drops its own briefing AND the stale 'All schemas' aggregate,
    # but keeps sibling schemas
    removed = briefing.invalidate("workspace", "missimi")
    assert removed == 2
    assert set(briefing._store().load()) == {"workspace:swiss_air"}

    # patterns are connection-level; invalidate drops the whole entry (recomputes cheap)
    patterns._CACHE_PATH.write_text(json.dumps({"workspace": {"patterns": []}}))
    assert patterns.invalidate("workspace") == 1
    assert patterns._store().load() == {}
    assert patterns.invalidate("workspace") == 0  # idempotent


def test_schema_purge_removes_schema_and_aggregates_keeps_siblings(isolated):
    """Removing ONE schema purges its scoped intelligence + the stale connection-level
    aggregates, but leaves sibling schemas (the user's ask: deleting a catalog/schema
    takes its investigations, canvas, briefings, everything with it)."""
    import json
    from aughor.canvas import store as canvas_store
    from aughor.canvas.models import CanvasScope
    from aughor.db import history, purge
    from aughor.evidence import store as evidence_store
    from aughor.evidence.models import EvidenceClaim
    from aughor.knowledge import briefing, patterns
    from aughor.monitors import store as monitor_store
    from aughor.monitors.models import Monitor

    CONN = "workspace"
    gone, keep = "missimi", "zomato_data"

    # profiles: scoped (gone) + sibling (keep) + bare aggregate
    (isolated / f"business_profile_{CONN}__{gone}.json").write_text("{}")
    (isolated / f"business_profile_{CONN}__{keep}.json").write_text("{}")
    (isolated / f"business_profile_{CONN}.json").write_text("{}")  # 'All schemas'
    # explorer files: scoped (gone) + sibling (keep) + bare aggregate
    (isolated / f"exploration_{CONN}__{gone}.json").write_text("{}")
    (isolated / f"exploration_{CONN}__{keep}.json").write_text("{}")
    (isolated / f"exploration_{CONN}.json").write_text("{}")
    (isolated / f"episodes_{CONN}.jsonl").write_text("")
    (isolated / f"episodes_{CONN}__{gone}.jsonl").write_text("")
    (isolated / f"episodes_{CONN}__{keep}.jsonl").write_text("")
    # briefing cache: gone scope + aggregate + sibling
    briefing._CACHE_PATH.write_text(json.dumps({
        f"{CONN}:{gone}": 1, CONN: 0, f"{CONN}:{keep}": 2}))
    patterns._CACHE_PATH.write_text(json.dumps({CONN: {"patterns": []}}))
    # watermark: gone schema tables + sibling
    from aughor.explorer import watermark
    watermark._PATH.write_text(json.dumps({CONN: {f"{gone}.orders": "d", f"{keep}.sales": "d"}}))
    # canvas bound to the removed schema (+ an artifact) and a sibling canvas
    cv = canvas_store.create_canvas("missimi cv", [CanvasScope(connection_id=CONN, schema_name=gone)])
    canvas_store.create_artifact(cv.id, "query", "q")
    keep_cv = canvas_store.create_canvas("zomato cv", [CanvasScope(connection_id=CONN, schema_name=keep)])
    # investigations: one referencing missimi.* (gone), one on zomato.* (keep)
    inv_gone = history.create_investigation("q", CONN)
    history.complete_investigation(inv_gone, {"headline": "h"}, [],
                                   [{"sql": "SELECT * FROM missimi.orders"}])
    inv_keep = history.create_investigation("q2", CONN)
    history.complete_investigation(inv_keep, {"headline": "h2"}, [],
                                   [{"sql": "SELECT * FROM zomato_data.sales"}])
    evidence_store.append_claim(EvidenceClaim(investigation_id=inv_gone, claim_text="x", confidence=0.5))
    # monitors: one on missimi.*, one on zomato.*
    monitor_store.upsert_monitor(Monitor(conn_id=CONN, name="m1", custom_sql="SELECT count(*) FROM missimi.orders"))
    monitor_store.upsert_monitor(Monitor(conn_id=CONN, name="m2", custom_sql="SELECT count(*) FROM zomato_data.sales"))

    counts = purge.purge_schema_artifacts(CONN, gone)

    # the removed schema's own artifacts, and the DERIVED summaries that spanned it, go
    assert not (isolated / f"business_profile_{CONN}__{gone}.json").exists()
    assert not (isolated / f"business_profile_{CONN}.json").exists()   # 'All schemas' — rebuildable
    assert not (isolated / f"exploration_{CONN}__{gone}.json").exists()
    assert not (isolated / f"episodes_{CONN}__{gone}.jsonl").exists()
    # …but the connection's own RECORDS stay: they are not summaries of the schemas, they are
    # what every run that was never schema-scoped wrote — the siblings' history — and no later
    # change makes a record untrue. They go when the CONNECTION goes.
    assert (isolated / f"exploration_{CONN}.json").exists()
    assert (isolated / f"episodes_{CONN}.jsonl").exists()
    bc = briefing._store().load()
    assert set(bc) == {f"{CONN}:{keep}"}                      # sibling kept, gone+aggregate dropped
    assert json.loads(watermark._PATH.read_text())[CONN] == {f"{keep}.sales": "d"}
    assert history.list_investigation_ids(CONN, limit=1000) == [inv_keep]
    assert counts["canvases"] == 1 and counts["investigations"] == 1
    assert counts["evidence_claims"] == 1 and counts["monitors"] == 1

    # siblings survive
    assert (isolated / f"business_profile_{CONN}__{keep}.json").exists()
    assert (isolated / f"exploration_{CONN}__{keep}.json").exists()
    assert (isolated / f"episodes_{CONN}__{keep}.jsonl").exists()
    assert canvas_store.get_canvas(keep_cv.id) is not None


def test_cascade_is_idempotent(isolated):
    from aughor.db import purge
    # Purging a connection that never existed is a clean no-op, not an error.
    counts = purge.purge_connection_artifacts("never_existed")
    assert counts.get("investigations", 0) == 0
    assert counts.get("upload_dir", 0) == 0


def test_purge_removes_store_seeded_exploration_state(isolated):
    """The post-migration reality: exploration state that never existed as a file —
    written through the family store — must be purged just as thoroughly. A finding
    that survives purge in ANY home is the stale-intelligence class (the 2026-08-04
    briefing citing a deleted table)."""
    from aughor.db import purge
    from aughor.explorer import store as explorer_store

    def _seed(key: str, finding_id: str) -> None:
        explorer_store.save(key, {"phase": "complete", "insights": [{"id": finding_id}]})

    _seed("cat_gone", "f1")
    _seed("cat_gone__main", "f2")
    _seed("cat_stays", "f3")

    counts = purge.purge_connection_artifacts("cat_gone")

    assert counts["exploration"] == 2                       # bare + schema scope
    assert explorer_store.get_insights("cat_gone") == []           # empty, not the old state
    assert explorer_store.get_insights("cat_gone__main") == []
    assert explorer_store.schema_run_keys("cat_gone") == []
    assert [f["id"] for f in explorer_store.get_insights("cat_stays")] == ["f3"]   # sibling intact


def test_purge_counts_a_key_once_when_it_lives_in_store_and_file(isolated):
    """An imported entry exists as a store row AND its legacy file; purging it is
    ONE removal — double-counting would overstate what the cascade did."""
    import json as _json
    from aughor.db import purge
    from aughor.explorer import store as explorer_store

    (isolated / "exploration_cat_dual.json").write_text(_json.dumps({"phase": "complete"}))
    assert explorer_store.load("cat_dual")["phase"] == "complete"   # import into the store

    counts = purge.purge_connection_artifacts("cat_dual")
    assert counts["exploration"] == 1
    assert not (isolated / "exploration_cat_dual.json").exists()    # file gone too
    assert not explorer_store.has_state("cat_dual")


def test_a_deleted_connection_leaves_nothing_on_disk():
    """Idea 1 — "deleting a connection leaves nothing behind". Measured 2026-10-04 on the live
    install: the two connections deleted in September still had their column-config and doc
    trees, their indexed schema documents, their watermarks, orphaned metastore schemas,
    ~1,160 popularity rows each, and the kernel's jobs, events and artifacts.

    Each store is written below by its OWN writer. The oracle is not this list: it is
    `residue_of`, which reads every SQLite table with a connection column, every path and
    every JSON/YAML store under the data directory — so a store nobody seeds here still shows
    up the first time a real delete runs (the cascade logs it)."""
    from aughor.db import purge
    from aughor.explorer import watermark
    from aughor.kernel.ledger import Ledger
    from aughor.knowledge import indexer
    from aughor.metastore import store as metastore
    from aughor.ontology import column_config, doctree
    from aughor.sql import popularity

    conn = "deadbeef42"
    column_config.save_table_config(conn, "main", "orders",
                                    {"status": column_config.ColumnFlags()})
    doctree.save_doc_tree(doctree.DocTree(connection_id=conn, schema_name="main"))
    indexer._register(indexer.doctree_doc_id(conn, "main"), "schema.md",
                      f"Schema documentation — {conn}/main", 3, "2026-10-04T00:00:00Z")
    watermark.set_watermark(conn, "main.orders", "2026-10-01T00:00:00")
    metastore.upsert_catalog(conn, name="gone", conn_id=conn)
    metastore.upsert_schema(conn, "main")
    popularity.save_popularity(popularity.PopularitySignal(
        connection_id=conn, table_counts={"orders": 9}, column_counts={"orders.status": 4}))
    ledger = Ledger.default()
    ledger.job_insert({"id": f"job-{conn}", "kind": "explore", "conn_id": conn,
                       "state": "succeeded", "attempt": 1, "created_at": "2026-10-04T00:00:00Z"})
    ledger.emit("job.finished", {"ok": True}, conn_id=conn, job_id=f"job-{conn}")
    ledger.artifact_write("profile", f"profile:{conn}", {"tables": 1}, conn_id=conn,
                          lineage=[("derived_from", "orders", None)])
    ledger.task_history_insert({"span_id": f"span-{conn}", "trace_id": "t", "task": "explore",
                                "start_time": "2026-10-04T00:00:00Z",
                                "labels": {"connection_id": conn}})
    assert set(purge.residue_of(conn)) >= {                       # the oracle sees the seeds
        "documents.json", "explore_watermark.json", "metastore.db:schemas.catalog_id",
        "popularity.db:popularity.connection_id", f"ontology_column_config/{conn}"}

    counts = purge.purge_connection_artifacts(conn)

    assert purge.residue_of(conn) == {}
    assert counts["residue"] == 0
    assert counts["popularity"] == 3 and counts["kernel_jobs"] == 1      # 2 counts + 1 meta row
    assert counts["kernel_artifacts"] == 1 and counts["kernel_lineage"] == 1
    assert (counts["task_traces"], counts["schema_documents"]) == (1, 1)
    assert counts["column_config"] == 1 and counts["doc_tree"] == 1


def test_a_deleted_canvas_takes_its_cards_and_cockpit_history_and_keeps_its_filed_runs():
    """CT-3 found it by reading: a deleted canvas left its cards and its dashboard's history
    behind, unreachable. Measured 2026-10-04 on the live install: four deleted canvases still
    held 881 kernel artifacts, 680 jobs and 5,478 events. A chat answer filed under the canvas
    is a RUN and stays, with its receipt — as a deleted chat thread's runs do (FL-6)."""
    from aughor.cards import store as cards
    from aughor.cards.models import StoredCard
    from aughor.db import purge
    from aughor.kernel.ledger import Ledger

    canvas = "cv_gone_01"
    cards.upsert_card(StoredCard(connection_id="c1", scope="canvas", scope_ref=canvas,
                                    title="Revenue"))
    cards.set_viz_config(f"canvas:{canvas}", "t1", "u1", {"type": "bar"})
    ledger = Ledger.default()
    ledger.artifact_write("cockpit", f"cockpit:{canvas}", {"v": 3}, canvas_id=canvas)
    ledger.artifact_write("finding", f"insight:c1:{canvas}:x", {"h": "x"}, canvas_id=canvas)
    kept = ledger.artifact_write("chat_answer", "chat:c1:inv1", {"a": 1}, canvas_id=canvas)
    ledger.job_insert({"id": f"job-{canvas}", "kind": "exploration", "canvas_id": canvas,
                       "state": "succeeded", "attempt": 1, "created_at": "2026-10-04T00:00:00Z"})
    ledger.emit("job.finished", {"ok": True}, canvas_id=canvas, job_id=f"job-{canvas}")

    counts = purge.purge_canvas_artifacts(canvas)

    assert cards.list_cards(scope="canvas", scope_ref=canvas) == []
    assert cards.get_viz_configs(f"canvas:{canvas}", "u1") == {}
    assert ledger.artifact_latest(f"cockpit:{canvas}") is None
    assert ledger.artifact_latest(f"insight:c1:{canvas}:x") is None
    assert ledger.artifact_by_id(kept) is not None                     # the filed run's receipt
    assert ledger.job_get(f"job-{canvas}") is None
    assert (counts["cards"], counts["kernel_artifacts"], counts["kernel_jobs"]) == (2, 2, 1)


def _seed_leftovers(root, conn: str) -> None:
    """What a removed Postgres connection left on the live install (2026-10-11), each in its own shape — beside a
    longer id that merely starts with this one, and another connection's entries, which must survive."""
    import json
    import sqlite3

    for rel in (f"context_graph/default/{conn}/luxexperience.json", f"ontology_recommendations/{conn}/lux/t.yaml",
                f"ontology_drafts/{conn}/lux.yaml", f"context_graph/default/{conn}99/keep.json"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("{}")
    (root / "connection_settings.json").write_text(json.dumps({conn: {"briefings_enabled": False}, "other": {"x": 1}}))
    (root / "notes.json").write_text(json.dumps({"mentions": [conn]}))
    # keyed by a key it scopes (the briefing cache's `conn:schema`); records naming it in a connection field, grouped
    # under another key (causal proposals by investigation) or as a list (cards) — beside another connection's
    (root / "briefing_cache.json").write_text(json.dumps({f"{conn}:lux": {"n": 1}, "other:lux": {"n": 2},
                                                          f"{conn}99:lux": {"n": 3}}))
    (root / "causal_proposals.json").write_text(json.dumps({
        "inv1": [{"conn_id": conn, "edge": "a"}], "inv2": [{"conn_id": conn, "edge": "b"}, {"conn_id": "other"}],
        "inv3": [{"conn_id": "other", "edge": "c"}]}))
    (root / "cards.json").write_text(json.dumps([{"connection_id": conn, "id": 1}, {"connection_id": "other", "id": 2}]))
    audit = sqlite3.connect(root / "audit.db")
    audit.execute("CREATE TABLE audit_log (connection_id TEXT, sql TEXT)")
    audit.execute("CREATE TABLE internal_counts (connection_id TEXT, n INTEGER)")
    audit.executemany("INSERT INTO internal_counts VALUES (?, ?)", [(conn, 1), ("other", 2)])
    audit.execute("INSERT INTO audit_log VALUES (?, 'SELECT 1')", (conn,))
    audit.commit()
    audit.close()
    system = sqlite3.connect(root / "system.db")
    system.execute("CREATE TABLE kv (store TEXT, key TEXT, value TEXT, seq INTEGER, updated_at TEXT)")
    system.execute("CREATE TABLE session_events (conn_id TEXT, cost REAL)")
    system.executemany("INSERT INTO kv VALUES (?, ?, '{}', 1, '')", [
        ("briefing", f"{conn}:lux#day"), ("explore", f"{conn}__lux"), ("explore", conn),
        ("explore", f"{conn}99__lux"), ("explore", f"other:{conn}")])
    system.execute("INSERT INTO session_events VALUES (?, 0.4)", (conn,))
    system.commit()
    system.close()


def test_a_removed_connection_is_swept_from_every_store_keeping_only_the_audit_and_model_call_logs(tmp_path):
    """The user, 2026-10-11: "when a connection is removed its underlying details are gone except the SQL audit log
    and logs of model cost and calls … let this be default". A delete of the Postgres connection left its settings
    entry, its context graph, the schemas it turned off, a counter row — and key-value rows the census could not see."""
    import json
    import sqlite3

    from aughor.db import purge

    conn = "e5b0c74c"
    _seed_leftovers(tmp_path, conn)
    before = purge.residue_of(conn, tmp_path)
    assert before == {f"context_graph/default/{conn}": 1, f"ontology_recommendations/{conn}": 1,
                      f"ontology_drafts/{conn}": 1, "connection_settings.json": 1, "notes.json": 1,
                      "briefing_cache.json": 1, "causal_proposals.json": 1, "cards.json": 1,
                      "audit.db:internal_counts.connection_id": 1, "system.db:kv.key": 3}

    swept = purge.sweep_residue(conn, tmp_path)

    assert swept == {"swept_paths": 3, "swept_rows": 4, "swept_json_keys": 5}
    assert purge.residue_of(conn, tmp_path) == {"notes.json": 1}          # a mention it cannot safely edit, said
    assert json.loads((tmp_path / "connection_settings.json").read_text()) == {"other": {"x": 1}}
    assert json.loads((tmp_path / "briefing_cache.json").read_text()) == {"other:lux": {"n": 2},
                                                                          f"{conn}99:lux": {"n": 3}}
    assert json.loads((tmp_path / "causal_proposals.json").read_text()) == {
        "inv2": [{"conn_id": "other"}], "inv3": [{"conn_id": "other", "edge": "c"}]}
    assert json.loads((tmp_path / "cards.json").read_text()) == [{"connection_id": "other", "id": 2}]
    assert (tmp_path / f"context_graph/default/{conn}99/keep.json").exists()
    audit = sqlite3.connect(tmp_path / "audit.db")
    assert audit.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1           # kept: the SQL audit log
    assert audit.execute("SELECT connection_id FROM internal_counts").fetchall() == [("other",)]
    system = sqlite3.connect(tmp_path / "system.db")
    assert system.execute("SELECT COUNT(*) FROM session_events").fetchone()[0] == 1     # kept: model calls + cost
    assert sorted(k for (k,) in system.execute("SELECT key FROM kv")) == [f"{conn}99__lux", f"other:{conn}"]


def test_a_delete_ends_by_sweeping_what_its_stores_left(tmp_path, monkeypatch):
    from aughor.db import purge

    conn = "e5b0c74c"
    _seed_leftovers(tmp_path, conn)
    monkeypatch.setattr(purge, "_DATA_DIR", tmp_path)
    counts = purge.purge_connection_artifacts(conn)
    assert counts["swept_paths"] == 3 and counts["swept_rows"] == 4 and counts["swept_json_keys"] == 5
    assert counts["residue"] == 1                                                       # notes.json, said


def test_a_removed_connection_can_be_read_and_cleared_through_its_doors_and_a_held_one_cannot(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor import govern
    from aughor.db import purge, registry
    from aughor.routers import connections as R

    app = FastAPI()
    app.include_router(R.router)
    client = TestClient(app)
    held = {"live1234"}
    guarded = []
    monkeypatch.setattr(registry, "is_registered", lambda c: c in held)
    monkeypatch.setattr(govern, "guard", lambda action, scope="", **k: guarded.append((action, scope)))
    purged = []
    monkeypatch.setattr(purge, "residue_of",
                        lambda c, root=None: {} if purged else {"connection_settings.json": 1})
    monkeypatch.setattr(purge, "purge_connection_artifacts", lambda c: purged.append(c) or {"matcache": 1})

    assert client.get("/connections/gone5678/residue").json()["residue"] == {"connection_settings.json": 1}
    assert client.get("/connections/live1234/residue").status_code == 409
    assert client.post("/connections/live1234/purge").status_code == 409
    assert guarded == []                                                   # refused before the gate
    got = client.post("/connections/gone5678/purge").json()
    assert guarded == [("connection.delete", "gone5678")]                  # the same approval as a delete
    assert got == {"connection_id": "gone5678", "cleared": {"connection_settings.json": 1}, "residue": {}}
