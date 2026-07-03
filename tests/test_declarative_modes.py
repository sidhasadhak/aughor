"""P5 declarative modes (aughor.agent.modes) — file-driven routing + fallback."""
from __future__ import annotations


from aughor.agent.modes import registry


class _Dec:
    """Minimal stand-in for RouteDecision (mode + reasoning)."""
    def __init__(self, mode):
        self.mode = mode
        self.reasoning = ""


def test_shipped_manifests_load_and_scope():
    m = registry.load_manifests()
    assert set(m) >= set(registry.STRUCTURAL_MODES)
    assert registry.scope_for_mode("explore").top_k_tables == 8   # broad
    assert registry.scope_for_mode("direct").top_k_tables == 4    # tight
    assert registry.scope_for_mode("final_text").max_tables == 0  # no SQL, no tables
    # unknown mode → default scope (fallback, never raises)
    assert registry.scope_for_mode("nope").top_k_tables == 4


def test_override_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("AUGHOR_DECLARATIVE_MODES", raising=False)
    q = "does discount affect revenue?"
    mode, _ = registry.apply_route_overrides(q, "explore", _Dec("explore"))
    assert mode == "explore"  # unchanged when the flag is off


def test_driver_question_overrides_explore_to_investigate(monkeypatch):
    monkeypatch.setenv("AUGHOR_DECLARATIVE_MODES", "1")
    q = "does discount level affect revenue across regions?"
    mode, dec = registry.apply_route_overrides(q, "explore", _Dec("explore"))
    assert mode == "investigate"
    assert "mode-manifest" in dec.reasoning


def test_route_from_condition_respected(monkeypatch):
    monkeypatch.setenv("AUGHOR_DECLARATIVE_MODES", "1")
    # investigate's driver keywords are route_from:[explore] — a 'direct' question
    # must NOT be pulled into investigate by them.
    mode, _ = registry.apply_route_overrides("does discount affect revenue?", "direct", _Dec("direct"))
    assert mode == "direct"


def test_non_matching_question_unchanged(monkeypatch):
    monkeypatch.setenv("AUGHOR_DECLARATIVE_MODES", "1")
    mode, _ = registry.apply_route_overrides("give me an overview of customers", "explore", _Dec("explore"))
    assert mode == "explore"


def test_new_keyword_added_via_file_changes_routing(tmp_path, monkeypatch):
    """The P5 gate: tune routing by editing a manifest FILE — no code change."""
    (tmp_path / "investigate.yaml").write_text(
        "name: investigate\nroute_from: [explore]\nroute_keywords:\n  - 'teardown'\n")
    monkeypatch.setattr(registry, "_MANIFEST_DIR", tmp_path)
    registry.load_manifests.cache_clear()
    monkeypatch.setenv("AUGHOR_DECLARATIVE_MODES", "1")
    try:
        mode, _ = registry.apply_route_overrides("give me a teardown of the funnel", "explore", _Dec("explore"))
        assert mode == "investigate"   # the file-defined keyword now routes
    finally:
        registry.load_manifests.cache_clear()   # don't leak the tmp manifests to other tests


def test_bad_regex_in_manifest_does_not_break_routing(tmp_path, monkeypatch):
    (tmp_path / "investigate.yaml").write_text(
        "name: investigate\nroute_from: [explore]\nroute_keywords:\n  - '('\n")  # invalid regex
    monkeypatch.setattr(registry, "_MANIFEST_DIR", tmp_path)
    registry.load_manifests.cache_clear()
    monkeypatch.setenv("AUGHOR_DECLARATIVE_MODES", "1")
    try:
        mode, _ = registry.apply_route_overrides("anything", "explore", _Dec("explore"))
        assert mode == "explore"   # bad pattern skipped, routing survives
    finally:
        registry.load_manifests.cache_clear()


def test_malformed_manifest_skipped(tmp_path, monkeypatch):
    (tmp_path / "good.yaml").write_text("name: direct\n")
    (tmp_path / "bad.yaml").write_text("{ this is not: valid: yaml ::: ")
    monkeypatch.setattr(registry, "_MANIFEST_DIR", tmp_path)
    registry.load_manifests.cache_clear()
    try:
        loaded = registry.load_manifests()
        assert "direct" in loaded   # the good one still loads despite the bad sibling
    finally:
        registry.load_manifests.cache_clear()
