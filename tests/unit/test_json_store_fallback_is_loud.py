"""The facade's fallback path — observable, and append-shaped where it must be.

`KeyedJsonStore` and `LedgerListStore` look like JSON files and are not: every public
method goes to the kernel Ledger, and the file on disk is a one-time import that the
healthy path never rewrites. Measured live 2026-09-19, 16 of the 31 top-level `.json`
files in `data/` were dead shadows — `agent_runs.json` held 1 run against the ledger's
220, `schema_profiles.json` was 211,920 bytes five weeks stale in front of 6.2 MB of
rows.

That makes the fallback the most dangerous state in the facade, and it used to be the
only silent one: a bare `except Exception: pass`. A read that falls back time-travels to
the stale file; a write that falls back is orphaned there forever, because the
`migrated:` marker is already set and the import never re-runs.
"""
import pytest

from aughor.kernel.ledger import Ledger
from aughor.util.json_store import KeyedJsonStore, LedgerListStore


class _Boom:
    """A store whose ledger is always unreachable."""
    def __init__(self, cls, path, **kw):
        self.store = cls(path, **kw)
        self.store._ledger = self._raise

    @staticmethod
    def _raise():
        raise RuntimeError("ledger unavailable")


@pytest.fixture()
def counters(monkeypatch):
    seen = []
    from aughor.kernel import errors as errmod

    real = errmod.tolerate

    def spy(exc, reason, **kw):
        seen.append({"reason": reason, "counter": kw.get("counter")})
        return real(exc, reason, **kw)

    monkeypatch.setattr(errmod, "tolerate", spy)
    return seen


# ── the fallback is recorded ─────────────────────────────────────────────────

class TestFallbackIsLoud:
    def test_a_read_that_falls_back_is_counted(self, tmp_path, counters):
        s = _Boom(KeyedJsonStore, tmp_path / "cache.json").store
        s.load()
        assert any(c["counter"] == "json_store.ledger_fallback.load" for c in counters), counters

    def test_a_write_that_falls_back_is_counted(self, tmp_path, counters):
        s = _Boom(KeyedJsonStore, tmp_path / "cache.json").store
        s.put("k", {"v": 1})
        assert any(c["counter"] == "json_store.ledger_fallback.put" for c in counters), counters

    def test_every_keyed_method_has_its_own_counter(self, tmp_path, counters):
        """Mutation guard: one shared counter, or a handler left bare, both pass a test
        that only checks 'something was counted'. Name every operation."""
        s = _Boom(KeyedJsonStore, tmp_path / "cache.json").store
        s.load(); s.save({}); s.get("k"); s.put("k", 1); s.delete("k")
        s.invalidate_prefix("p")

        got = {c["counter"] for c in counters}
        for op in ("load", "save", "get", "put", "delete", "invalidate_prefix"):
            assert f"json_store.ledger_fallback.{op}" in got, f"{op} falls back silently"

    def test_every_list_method_has_its_own_counter(self, tmp_path, counters):
        s = _Boom(LedgerListStore, tmp_path / "list.json").store
        s.all(); s.save_all([]); s.get("i"); s.upsert({"id": "i"}); s.delete("i")
        s.append({"id": "j"})

        got = {c["counter"] for c in counters}
        for op in ("list_all", "list_save_all", "list_get", "list_upsert",
                   "list_delete", "list_append"):
            assert f"json_store.ledger_fallback.{op}" in got, f"{op} falls back silently"

    def test_the_reason_names_the_file_being_served(self, tmp_path, counters):
        """The operator has to be able to tell WHICH store went stale."""
        s = _Boom(KeyedJsonStore, tmp_path / "profiles.json").store
        s.load()
        reasons = [c["reason"] for c in counters if "ledger_fallback" in (c["counter"] or "")]
        assert any("profiles.json" in r for r in reasons), reasons

    def test_falling_back_still_returns_the_file_contents(self, tmp_path, counters):
        """Loud, not fatal — the best-effort contract is unchanged."""
        p = tmp_path / "cache.json"
        p.write_text('{"a": 1}')
        s = _Boom(KeyedJsonStore, p).store
        assert s.load() == {"a": 1}


# ── append is one insert, not a table rewrite ────────────────────────────────

class TestLedgerListAppend:
    def test_append_writes_one_row_without_rewriting_the_store(self, tmp_path, monkeypatch):
        """The inherited append is all() + save_all(), and save_all is kv_replace_all —
        a DELETE of every row and a re-insert of every row, per append. Quadratic on the
        one shape (an append-only log) that this store now serves."""
        led = Ledger(tmp_path / "system.db")
        monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: led))
        s = LedgerListStore(tmp_path / "logs.json")

        replaced = []
        real_replace = led.kv_replace_all
        monkeypatch.setattr(led, "kv_replace_all",
                            lambda *a, **k: (replaced.append(1), real_replace(*a, **k))[1])

        for i in range(5):
            s.append({"id": f"r{i}", "n": i})

        assert [d["n"] for d in s.all()] == [0, 1, 2, 3, 4]
        assert replaced == [], "append rewrote the whole store"

    def test_append_preserves_insertion_order(self, tmp_path, monkeypatch):
        led = Ledger(tmp_path / "system.db")
        monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: led))
        s = LedgerListStore(tmp_path / "logs.json")

        for i in range(20):
            s.append({"id": f"r{i}", "n": i})

        # list_logs slices the tail for "newest N" — order is load-bearing.
        assert [d["n"] for d in s.all()][-3:] == [17, 18, 19]

    def test_an_item_without_an_id_stays_append_only(self, tmp_path, monkeypatch):
        """`_key` renders a missing id as the string "None", and kv's (store, key)
        primary key would make every such append overwrite the last."""
        led = Ledger(tmp_path / "system.db")
        monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: led))
        s = LedgerListStore(tmp_path / "logs.json")

        s.append({"no_id": 1})
        s.append({"no_id": 2})

        assert len(s.all()) == 2, "id-less appends collapsed onto one kv key"
