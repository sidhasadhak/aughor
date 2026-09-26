"""TJ-2 (§3.47), the three bullets left open the same morning: the guard table says which
of its two meanings a row has; the explorer's step log writes the same `step` record every
tool loop writes; the bronze tier vouches for a turn by its own trajectory when no envelope
exists (TJ-1's falsifier fired: 1 row from 821 turns).
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from aughor import telemetry
from aughor.kernel.ledger import Ledger
from aughor.obs import prompt_window, session_log


@pytest.fixture(autouse=True)
def _no_capture_window():
    prompt_window.close_window()
    yield
    prompt_window.close_window()


# ── migration 4: one meaning per column ───────────────────────────────────────────────

def _old_store(path) -> None:
    """A guard table as it was written before migration 4: the action in `phase`."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE audit_log (id TEXT PRIMARY KEY, ts TEXT NOT NULL, connection_id TEXT NOT NULL,
            hypothesis_id TEXT NOT NULL DEFAULT '', sql_digest TEXT NOT NULL, sql_full TEXT NOT NULL,
            verdict TEXT NOT NULL DEFAULT 'safe', row_count INTEGER NOT NULL DEFAULT 0,
            duration_ms REAL NOT NULL DEFAULT 0, pii_redacted INTEGER NOT NULL DEFAULT 0, error TEXT,
            org_id TEXT NOT NULL DEFAULT 'default', trace_id TEXT NOT NULL DEFAULT '');
        CREATE TABLE guard_verdicts (id TEXT NOT NULL PRIMARY KEY, ts TEXT NOT NULL, trace_id TEXT NOT NULL,
            org_id TEXT NOT NULL DEFAULT 'default', sql_digest TEXT NOT NULL DEFAULT '', pattern TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT '', phase TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '');
        INSERT INTO guard_verdicts VALUES ('r1','2026-09-20T00:00:00Z','t','default','SELECT','preflight_repair','','repaired_sql','');
        INSERT INTO guard_verdicts VALUES ('r2','2026-09-20T00:00:00Z','t','default','SELECT','fanout_detected','','flagged','');
        INSERT INTO guard_verdicts VALUES ('e1','2026-09-20T00:00:00Z','t','default','SELECT','E1-quoted-identifier','orders','validate','');
        INSERT INTO guard_verdicts VALUES ('e2','2026-09-20T00:00:00Z','t','default','SELECT','E1-lexicographic-order','x','deep','');
        INSERT INTO guard_verdicts VALUES ('ev','2026-09-20T00:00:00Z','t','default','SELECT','E1-quoted-identifier','y','eval','');
        PRAGMA user_version = 3;
    """)
    c.commit()
    c.close()


def test_migration_4_moves_the_action_out_of_the_phase_column(tmp_path):
    """Run the store's own schema function against a v3 file — the same call every open
    makes — rather than re-pointing the store's path, which it resolves once at import."""
    path = tmp_path / "audit.db"
    _old_store(path)
    from aughor.security.audit import _ensure_schema
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    _ensure_schema(c)                                                # opening runs the migration
    assert c.execute("PRAGMA user_version").fetchone()[0] == 4
    rows = {r["id"]: dict(r) for r in c.execute("SELECT * FROM guard_verdicts")}
    assert (rows["r1"]["phase"], rows["r1"]["action"]) == ("execute", "repaired_sql")
    assert (rows["r2"]["phase"], rows["r2"]["action"]) == ("execute", "flagged")
    for e in ("e1", "e2", "ev"):
        assert rows[e]["action"] == ""                               # a real phase is untouched
    assert rows["e1"]["phase"] == "validate" and rows["ev"]["phase"] == "eval"
    _ensure_schema(c)                                                # idempotent: a second open changes nothing
    assert {r["id"]: dict(r) for r in c.execute("SELECT * FROM guard_verdicts")} == rows
    assert c.execute("PRAGMA user_version").fetchone()[0] == 4
    c.close()


def test_the_rewrite_hook_writes_action_and_phase_apart():
    from aughor.kernel.registries.execution_hooks import _record_guard_verdict
    from aughor.security.audit import GuardVerdicts
    with telemetry.bind_trace("tj2-hook"):
        _record_guard_verdict("fanout_defan", "rewrote_sql", "de-fanned", "SELECT a FROM b")
        GuardVerdicts.record(pattern="E1-quoted-identifier", subject="orders", phase="quick", sql="SELECT 1")
    rows = {r["pattern"]: r for r in GuardVerdicts.recent(limit=10, trace_id="tj2-hook")}
    assert (rows["fanout_defan"]["phase"], rows["fanout_defan"]["action"]) == ("execute", "rewrote_sql")
    assert (rows["E1-quoted-identifier"]["phase"], rows["E1-quoted-identifier"]["action"]) == ("quick", "")


def test_the_quick_body_labels_its_fires_quick_not_deep():
    import inspect

    from aughor.routers import investigations as inv
    src = inspect.getsource(inv._answer_core)
    assert 'phase="quick"' in src and 'phase="deep"' not in src


# ── the explorer's step log writes the step record ────────────────────────────────────

def test_an_explorer_step_lands_as_a_step_event_under_its_job_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_EPISODES_DIR", str(tmp_path))
    import importlib

    from aughor.explorer import episodes
    importlib.reload(episodes)                       # the module resolves its dir at import
    with telemetry.bind_trace("tj2-explore"):
        col = episodes.EpisodeCollector("c1", phase="exploration")
        col.add("look at orders", "SELECT COUNT(*) FROM orders", "412")
        col.add("then customers", "SELECT COUNT(*) FROM customers", "99")
    rows = sorted(Ledger.default().session_events(trace_id="tj2-explore", kind=session_log.STEP, limit=10),
                  key=lambda r: r["seq"])
    assert [r["payload"]["index"] for r in rows] == [1, 2]
    p = rows[0]["payload"]
    assert p["site"] == "explorer" and p["sql"] == "SELECT COUNT(*) FROM orders"
    assert p["phase"] == "exploration" and p["episode_id"] == col.episode_id
    assert p["captured"] is False and "arguments" not in p            # the think is a payload
    # The file is still written for its readers.
    lines = (tmp_path / "episodes_c1.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["think"] == "look at orders"
    # Outside any trace: the file, not the log.
    before = len(Ledger.default().session_events(kind=session_log.STEP, limit=5000))
    episodes.EpisodeCollector("c2").add("t", "SELECT 1", "1")
    assert len(Ledger.default().session_events(kind=session_log.STEP, limit=5000)) == before


def test_an_explorer_step_carries_its_reasoning_only_under_a_capture_window(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_EPISODES_DIR", str(tmp_path))
    import importlib

    from aughor.explorer import episodes
    importlib.reload(episodes)
    prompt_window.open_window(calls=3, minutes=5, opened_by="test", reason="tj2")
    with telemetry.bind_trace("tj2-explore-cap"):
        episodes.EpisodeCollector("c1").add("the reasoning", "SELECT 1", "the observation")
    p = Ledger.default().session_events(trace_id="tj2-explore-cap", kind=session_log.STEP, limit=5)[0]["payload"]
    assert p["captured"] is True and p["arguments"] == "the reasoning" and p["result_excerpt"] == "the observation"


# ── bronze vouched by the trajectory ─────────────────────────────────────────────────

def _turn_without_envelope(question: str, sql: str, *, trace: str) -> str:
    """A chat answer filed BEFORE envelopes were: rows, no envelope, its trace on the row."""
    from aughor.db.history import save_chat_turn
    with telemetry.bind_trace(trace):
        return save_chat_turn(question=question, connection_id="conn-1", headline="h", sql=sql,
                              columns=["n"], rows=[[1]])


def _ran(trace: str, sql: str, *, error: str | None = None, guard: str = "") -> None:
    from aughor.security.audit import AuditLogger, GuardVerdicts
    with telemetry.bind_trace(trace):
        AuditLogger.log(connection_id="conn-1", sql=sql, verdict="safe", row_count=1, error=error)
        if guard:
            GuardVerdicts.record(pattern=guard, subject="n", phase="quick", sql=sql)


def test_bronze_vouches_for_an_envelope_less_turn_by_its_own_trajectory(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_LEARNING_DB", str(tmp_path / "learning.db"))
    monkeypatch.setenv("AUGHOR_DATASETS_DIR", str(tmp_path / "datasets"))
    from aughor.db.history import recent_chat_answers
    from aughor.learning import exporters, store

    clean = _turn_without_envelope("how many clean?", "SELECT 1 AS clean", trace="tj2-b-clean")
    _ran("tj2-b-clean", "SELECT 1 AS clean")
    _turn_without_envelope("how many fired?", "SELECT 2 AS fired", trace="tj2-b-fired")
    _ran("tj2-b-fired", "SELECT 2 AS fired", guard="E1-quoted-identifier")
    _turn_without_envelope("how many failed?", "SELECT 3 AS failed", trace="tj2-b-failed")
    _ran("tj2-b-failed", "SELECT 3 AS failed", error="no such column")
    _turn_without_envelope("how many traceless?", "SELECT 4 AS traceless", trace="")

    assert {a["id"]: a["trace_id"] for a in recent_chat_answers("0000")}[clean] == "tj2-b-clean"
    # The history store is shared across the suite, so other tests' turns ride the same
    # export: membership is the claim, never the whole set.
    rows = {r["prompt"]: r for r in store.rows_of(exporters.export_bronze(name="bronze-tj2"))}
    assert "how many clean?" in rows
    for out in ("how many fired?", "how many failed?", "how many traceless?"):
        assert out not in rows, out
    row = rows["how many clean?"]
    assert row["vouched_by"] == "trajectory"
    assert row["trajectory"] == {"steps": [], "guard_fires": [], "execution": "ok", "label": "positive",
                                 "reasons": ["ran without error, returned rows, no guard but lint fired, the "
                                             "re-check found it unchanged or did not run, nobody rejected it"]}


def test_bronze_still_prefers_the_envelope_when_there_is_one(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_LEARNING_DB", str(tmp_path / "learning.db"))
    monkeypatch.setenv("AUGHOR_DATASETS_DIR", str(tmp_path / "datasets"))
    from aughor.db.history import attach_envelope
    from aughor.learning import exporters, store
    turn = _turn_without_envelope("how many enveloped?", "SELECT 5 AS e", trace="tj2-b-env")
    attach_envelope(turn, {"question": "how many enveloped?", "headline": "h", "caveats": [],
                           "provenance": {"guard_receipts": []}})
    rows = {r["prompt"]: r for r in store.rows_of(exporters.export_bronze(name="bronze-tj2-env"))}
    assert rows["how many enveloped?"]["vouched_by"] == "envelope"
    assert "trajectory" not in rows["how many enveloped?"]
