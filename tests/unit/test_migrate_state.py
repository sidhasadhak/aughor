"""IN-4 — the migration copies, verifies, and only then counts. It never deletes.

The three properties worth a test each, all of them expensive to get wrong:
a migration must not run beside a live writer (`data/system.db` has been corrupted four times
by one), a SQLite store must be copied through SQLite rather than through the filesystem
(WAL content is invisible to `cp` and the copy still opens cleanly), and the marker that makes
the home live must be written only after every copy verified.
"""
from __future__ import annotations

import sqlite3

import pytest

from aughor.db import home, migrate


@pytest.fixture
def staged(monkeypatch, tmp_path):
    """A source `data/` holding one generated file, one authored file and one SQLite store
    with UNCHECKPOINTED WAL content, plus an empty home."""
    source = tmp_path / "checkout" / "data"
    source.mkdir(parents=True)
    (source / "watermark.json").write_text('{"seen": 7}')
    (source / "glossary.yaml").write_text("terms: []")          # authored — must stay
    db = source / "system.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    # Both lines are load-bearing, and the control test below is what proved it. SQLite
    # checkpoints on the last connection close, so a fixture that commits and closes leaves
    # NOTHING in the WAL — the first version of this did exactly that, and the "WAL content
    # survives" test passed while exercising nothing. Autocheckpoint off, connection held open.
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE receipts (id INTEGER, note TEXT)")
    conn.executemany("INSERT INTO receipts VALUES (?, ?)", [(i, f"r{i}") for i in range(50)])
    conn.commit()

    hm = tmp_path / "home"
    monkeypatch.setenv(home.HOME_ENV, str(hm))
    monkeypatch.setattr("aughor.db.serving.serving_pid", lambda: None)
    try:
        yield source, hm
    finally:
        conn.close()


class TestItRefuses:
    def test_while_the_api_is_serving(self, staged, monkeypatch):
        source, hm = staged
        monkeypatch.setattr("aughor.db.serving.serving_pid", lambda: 4242)
        out = migrate.migrate(source)
        assert out.status == "refused"
        assert "4242" in out.reason
        assert not home.marker_path().exists()

    def test_when_there_is_nothing_to_migrate(self, staged, tmp_path):
        out = migrate.migrate(tmp_path / "absent")
        assert out.status == "refused"
        assert out.ok is False
        assert not home.marker_path().exists()

    def test_a_home_inside_the_source_is_refused(self, staged, monkeypatch):
        """`copytree` would otherwise walk into the copy it is writing."""
        source, _hm = staged
        monkeypatch.setenv(home.HOME_ENV, str(source / "nested"))
        out = migrate.migrate(source)
        assert out.status == "refused"
        assert "inside the directory being migrated" in out.reason

    def test_a_second_run_reports_already_rather_than_copying_again(self, staged):
        source, _hm = staged
        assert migrate.migrate(source).status == "migrated"
        second = migrate.migrate(source)
        assert second.status == "already"
        assert second.ok


class TestWhatMoves:
    def test_generated_state_moves_and_authored_content_stays(self, staged):
        source, hm = staged
        out = migrate.migrate(source)
        assert out.status == "migrated", out.problems
        state = hm / home.STATE_SUBDIR
        assert (state / "watermark.json").read_text() == '{"seen": 7}'
        assert not (state / "glossary.yaml").exists()
        assert "glossary.yaml" in out.skipped_authored

    def test_the_source_is_never_deleted(self, staged):
        source, _hm = staged
        migrate.migrate(source)
        assert (source / "watermark.json").exists()
        assert (source / "system.db").exists()
        assert (source / "glossary.yaml").exists()


class TestSqliteIsCopiedThroughSqlite:
    def test_wal_content_survives_the_copy(self, staged):
        """THE test. These stores run in WAL mode, so committed rows can live in `-wal` until a
        checkpoint. A filesystem copy of the `.db` alone drops them AND still opens cleanly —
        a migration that verifies fine and quietly lost the newest writes."""
        source, hm = staged
        out = migrate.migrate(source)
        assert out.status == "migrated", out.problems
        copied = hm / home.STATE_SUBDIR / "system.db"
        with sqlite3.connect(f"file:{copied}?mode=ro", uri=True) as conn:
            assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 50

    def test_a_plain_byte_copy_would_have_lost_rows(self, staged):
        """The control that makes the test above mean something. Without it, "50 rows arrived"
        could be true of any copy method and would prove nothing about WAL handling."""
        import shutil
        source, _hm = staged
        naive = source.parent / "naive.db"
        shutil.copy2(source / "system.db", naive)          # the `.db` only, as `cp` would
        # It does not merely lose ROWS — with the schema itself still in the WAL, the copy has
        # no `receipts` table at all. Both outcomes are the same finding, and the copy opens
        # perfectly well either way, which is what makes the loss silent.
        try:
            with sqlite3.connect(f"file:{naive}?mode=ro", uri=True) as conn:
                rows = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        except sqlite3.OperationalError as exc:
            assert "no such table" in str(exc), exc
            return
        assert rows < 50, (
            "the fixture no longer leaves anything in the WAL, so the test above is vacuous")

    def test_a_sidecar_is_never_treated_as_a_source_of_its_own(self, staged):
        """Asserted on `sources()`, not on the destination: SQLite creates `-wal`/`-shm` beside
        the COPY itself, so their absence there is not something this module decides. What it
        decides is never copying a stale sidecar over a freshly-backed-up database."""
        source, _hm = staged
        assert (source / "system.db-wal").exists(), "fixture drift: no WAL to be tempted by"
        moving, _staying = migrate.sources(source)
        names = {p.name for p in moving}
        assert "system.db" in names
        assert not {n for n in names if n.endswith(("-wal", "-shm", "-journal"))}, names


class TestTheMarkerIsEarned:
    def test_it_is_written_only_after_everything_verified(self, staged):
        source, _hm = staged
        assert not home.marker_path().exists()
        migrate.migrate(source)
        assert home.marker_path().is_file()
        assert home.in_use() is True

    def test_a_failed_verification_leaves_the_deployment_where_it_was(self, staged, monkeypatch):
        source, _hm = staged
        monkeypatch.setattr(migrate, "_verify", lambda _s, _d: ["watermark.json: contents differ"])
        out = migrate.migrate(source)
        assert out.status == "failed"
        assert out.problems
        assert not home.marker_path().exists(), "the marker was written despite a failed verify"
        assert home.in_use() is False

    def test_verification_actually_compares_rows_not_just_openability(self, staged, tmp_path):
        """A copy that opens and passes `integrity_check` can still be missing everything the
        WAL held, so the verifier compares per-table counts."""
        source, _hm = staged
        empty = tmp_path / "empty.db"
        with sqlite3.connect(empty) as conn:
            conn.execute("CREATE TABLE receipts (id INTEGER, note TEXT)")
        problems = migrate._verify(source / "system.db", empty)
        assert any("receipts" in p and "0 rows" in p for p in problems), problems
