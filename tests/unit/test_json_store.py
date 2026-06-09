"""Shared JSON-store primitives — see aughor/util/json_store.py (C1)."""
from aughor.util.json_store import KeyedJsonStore, JsonListStore


# ── KeyedJsonStore ────────────────────────────────────────────────────────────

def test_keyed_roundtrip(tmp_path):
    s = KeyedJsonStore(tmp_path / "k.json")
    assert s.load() == {}
    s.put("a", {"x": 1})
    assert s.get("a") == {"x": 1}
    assert s.get("missing") is None


def test_keyed_lru_eviction(tmp_path):
    s = KeyedJsonStore(tmp_path / "k.json", max_entries=2)
    s.put("a", 1); s.put("b", 2); s.put("c", 3)
    assert set(s.load()) == {"b", "c"}   # oldest "a" evicted


def test_keyed_mru_refresh_on_reput(tmp_path):
    s = KeyedJsonStore(tmp_path / "k.json", max_entries=2)
    s.put("a", 1); s.put("b", 2)
    s.put("a", 11)        # refresh a → most-recently-used
    s.put("c", 3)         # evicts b (now oldest), not a
    d = s.load()
    assert set(d) == {"a", "c"} and d["a"] == 11


def test_keyed_invalidate_prefix(tmp_path):
    s = KeyedJsonStore(tmp_path / "k.json")
    s.put("c1:fp1", 1); s.put("c1:fp2", 2); s.put("c2:fp", 3)
    assert s.invalidate_prefix("c1:") == 2
    assert set(s.load()) == {"c2:fp"}


def test_keyed_missing_or_corrupt_file(tmp_path):
    assert KeyedJsonStore(tmp_path / "nope.json").load() == {}
    p = tmp_path / "bad.json"; p.write_text("{not json")
    assert KeyedJsonStore(p).load() == {}


# ── JsonListStore ─────────────────────────────────────────────────────────────

def test_list_upsert_get_delete(tmp_path):
    s = JsonListStore(tmp_path / "l.json")
    s.upsert({"id": "a", "v": 1})
    s.upsert({"id": "b", "v": 2})
    s.upsert({"id": "a", "v": 11})        # update in place
    assert len(s.all()) == 2
    assert s.get("a")["v"] == 11
    assert s.delete("b") is True
    assert s.delete("missing") is False
    assert [d["id"] for d in s.all()] == ["a"]


def test_list_append_allows_dups(tmp_path):
    s = JsonListStore(tmp_path / "log.json")
    s.append({"id": "1"}); s.append({"id": "1"})
    assert len(s.all()) == 2


def test_list_custom_id_field(tmp_path):
    s = JsonListStore(tmp_path / "l.json", id_field="key")
    s.upsert({"key": "x"}); s.upsert({"key": "x", "v": 2})
    assert len(s.all()) == 1 and s.get("x")["v"] == 2


def test_list_missing_file(tmp_path):
    assert JsonListStore(tmp_path / "nope.json").all() == []
